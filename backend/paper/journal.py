"""
Paper journal — persistent tick logging to PostgreSQL.

No broker. No real orders. Research-only fake-money simulation.
All writes are non-fatal: if Postgres is unavailable the simulator continues normally.
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from paper import db as _db

logger = logging.getLogger(__name__)

_journal_enabled: bool = False
_last_persist_ok: bool | None = None
_last_retry_at: float | None = None


async def init_journal() -> None:
    """Called at application startup. Sets _journal_enabled. Non-fatal."""
    global _journal_enabled
    ok = await _db.init_tables()
    _journal_enabled = ok
    if ok:
        logger.info("Paper journal initialized.")
    else:
        logger.warning(
            "Paper journal disabled (Postgres unavailable or DATABASE_URL not set)."
        )


def get_journal_status() -> dict:
    return {
        "enabled": _journal_enabled,
        "database_connected": _db.pool_exists(),
        "tables_ready": _db.is_ready(),
        "last_error": _db.last_error(),
        "last_persist_ok": _last_persist_ok,
        "last_retry_at": _last_retry_at,
    }


async def try_reinit() -> bool:
    """
    Attempt lazy re-initialization if journal was disabled at startup.
    Respects JOURNAL_RETRY_SECONDS cooldown. Non-fatal.
    """
    global _journal_enabled, _last_retry_at
    from core.config import settings
    now = time.monotonic()
    if _last_retry_at is not None and now - _last_retry_at < settings.JOURNAL_RETRY_SECONDS:
        return False
    _last_retry_at = now
    try:
        ok = await _db.init_tables()
        if ok:
            _journal_enabled = True
            logger.info("Paper journal: re-initialized successfully on retry.")
        return ok
    except Exception as exc:
        logger.warning("Paper journal: retry failed: %s", exc)
        return False


async def persist_tick_result(
    tick_result: dict,
    account_status: dict,
    universe: dict | None,
) -> dict:
    """
    Write one tick's data to PostgreSQL journal tables.
    Returns a summary dict with ok/skipped/error. Never raises to caller.
    """
    global _last_persist_ok
    if not _journal_enabled:
        from core.config import settings
        if settings.DATABASE_URL:
            await try_reinit()
        if not _journal_enabled:
            return {"ok": False, "skipped": True, "reason": "journal disabled"}

    pool = await _db.get_pool()
    if pool is None:
        return {"ok": False, "skipped": True, "reason": "no pool"}

    tick_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    candidates = tick_result.get("candidates") or []

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Tick row
                started_at = _parse_dt(tick_result.get("tick_at")) or now
                await conn.execute(
                    """
                    INSERT INTO paper_ticks (
                        tick_id, started_at, completed_at,
                        symbols_evaluated, universe_active_count,
                        universe_refresh_reason,
                        entries_made, exits_made, errors_count,
                        account_cash, account_equity,
                        realized_pnl, unrealized_pnl,
                        total_pnl, total_pnl_percent
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15
                    )
                    """,
                    tick_id,
                    started_at,
                    now,
                    int(tick_result.get("symbols_evaluated") or 0),
                    int(tick_result.get("universe_active_count") or 0),
                    str(tick_result.get("universe_refresh_reason") or ""),
                    int(tick_result.get("entries_made") or 0),
                    int(tick_result.get("exits_made") or 0),
                    len(tick_result.get("errors") or []),
                    _float(account_status.get("cash")),
                    _float(account_status.get("equity")),
                    _float(account_status.get("realized_pnl")),
                    _float(account_status.get("unrealized_pnl")),
                    _float(account_status.get("total_pnl")),
                    _float(account_status.get("total_pnl_percent")),
                )

                # 2. Candidates
                if candidates:
                    await conn.executemany(
                        """
                        INSERT INTO paper_candidates (
                            tick_id, symbol, eligible, action, rejection_reason,
                            quality_tradable, spread_percent, change_percent,
                            volume_ratio, catalyst_count, catalyst_type,
                            total_score, score_threshold, score_pass,
                            score_components_json, positive_reasons_json,
                            negative_reasons_json, decision_reason,
                            catalyst_sentiment, catalyst_sentiment_score,
                            catalyst_materiality_score
                        ) VALUES (
                            $1,$2,$3,$4,$5,$6,$7,$8,
                            $9,$10,$11,$12,$13,$14,
                            $15,$16,$17,$18,$19,$20,$21
                        )
                        """,
                        [
                            (
                                tick_id,
                                c.get("symbol"),
                                _bool(c.get("eligible")),
                                c.get("action"),
                                c.get("rejection_reason"),
                                _bool(c.get("quality_tradable")),
                                _float(c.get("spread_percent")),
                                _float(c.get("change_percent")),
                                _float(c.get("volume_ratio")),
                                _int(c.get("catalyst_count")),
                                c.get("catalyst_type"),
                                _int(c.get("total_score")),
                                _int(c.get("score_threshold")),
                                _bool(c.get("score_pass")),
                                json.dumps(c["score_components"]) if c.get("score_components") else None,
                                json.dumps(c["positive_reasons"]) if c.get("positive_reasons") else None,
                                json.dumps(c["negative_reasons"]) if c.get("negative_reasons") else None,
                                c.get("decision_reason"),
                                c.get("catalyst_sentiment"),
                                _float(c.get("catalyst_sentiment_score")),
                                _float(c.get("catalyst_materiality_score")),
                            )
                            for c in candidates
                        ],
                    )

                # 3. Entry events
                for entry in tick_result.get("entries") or []:
                    await conn.execute(
                        """
                        INSERT INTO paper_trades_journal (
                            tick_id, symbol, side, event,
                            entry_price, shares, cost_basis,
                            catalyst_type, total_score, opened_at
                        ) VALUES ($1,$2,'long','entry',$3,$4,$5,$6,$7,$8)
                        """,
                        tick_id,
                        entry.get("symbol"),
                        _float(entry.get("entry_price")),
                        _float(entry.get("shares")),
                        _float(entry.get("cost_basis")),
                        entry.get("catalyst_type"),
                        _int(entry.get("total_score")),
                        now,
                    )

                # 4. Exit events
                for exit_ in tick_result.get("exits") or []:
                    await conn.execute(
                        """
                        INSERT INTO paper_trades_journal (
                            tick_id, symbol, side, event,
                            entry_price, exit_price, pnl, pnl_percent,
                            exit_reason, catalyst_type, total_score, closed_at
                        ) VALUES ($1,$2,'long','exit',$3,$4,$5,$6,$7,$8,$9,$10)
                        """,
                        tick_id,
                        exit_.get("symbol"),
                        _float(exit_.get("entry_price")),
                        _float(exit_.get("exit_price")),
                        _float(exit_.get("pnl")),
                        _float(exit_.get("pnl_percent")),
                        exit_.get("exit_reason"),
                        exit_.get("catalyst_type"),
                        _int(exit_.get("total_score")),
                        now,
                    )

                # 5. Universe snapshot (if available)
                if universe is not None:
                    await conn.execute(
                        """
                        INSERT INTO paper_universe_snapshots (
                            tick_id, refreshed_at, active_count,
                            max_symbols_per_tick, refresh_reason,
                            active_symbols_json, errors_json
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        tick_id,
                        _parse_dt(universe.get("last_refreshed_at")) or now,
                        _int(universe.get("active_count")),
                        _int(universe.get("max_symbols_per_tick")),
                        universe.get("refresh_reason"),
                        json.dumps(universe.get("active_symbols") or []),
                        json.dumps(universe.get("errors") or []),
                    )

        _last_persist_ok = True
        return {
            "ok": True,
            "tick_id": tick_id,
            "candidates_written": len(candidates),
        }

    except Exception as exc:
        _last_persist_ok = False
        logger.warning("Paper journal: write failed: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ── Private helpers ───────────────────────────────────────────────────────────

def _float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> bool | None:
    return bool(v) if v is not None else None


def _parse_dt(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None
