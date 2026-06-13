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

# Phase G1B Part A: bound the per-candidate sanitized snapshot.
# 32 KB is generous for the typical 100-150 runtime fields while keeping
# total write volume sane (≤ ~3 MB per 100-candidate tick).
_EXTRAS_MAX_BYTES = 32 * 1024

# Fields that may legitimately carry large/raw payloads — keep counts/IDs
# but strip the bulky body before snapshotting. Adjust as new sections are added.
_EXTRAS_DROP_KEYS = {
    "news_items_raw", "raw_news_items", "reddit_posts_raw", "raw_reddit_posts",
    "marketdata_quote_raw", "raw_quote",
}

# Phase G1B Part B: forward-return horizons (minutes).
_OUTCOME_HORIZONS = (5, 10, 15, 30, 60)

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

                # 2. Candidates — per-row INSERT ... RETURNING id so Part B
                # can queue forward-return outcomes for the inserted rows.
                # Columns include sentiment ($19/$20/$21) and extras_json ($38).
                inserted_candidate_ids: list[tuple[int, dict]] = []
                for c in candidates:
                    row_id = await conn.fetchval(
                        """
                        INSERT INTO paper_candidates (
                            tick_id, symbol, eligible, action, rejection_reason,
                            quality_tradable, spread_percent, change_percent,
                            volume_ratio, catalyst_count, catalyst_type,
                            total_score, score_threshold, score_pass,
                            score_components_json, positive_reasons_json,
                            negative_reasons_json, decision_reason,
                            catalyst_sentiment, catalyst_sentiment_score,
                            catalyst_materiality_score,
                            entry_mode, momentum_eligible, momentum_score,
                            momentum_score_threshold, momentum_rejection_reason,
                            momentum_gate_results_json,
                            marketdata_source, marketdata_age_seconds, marketdata_stale,
                            marketdata_fallback_used, marketdata_error,
                            catalyst_required,
                            no_catalyst_momentum_eligible,
                            no_catalyst_momentum_reasons_json,
                            no_catalyst_momentum_blockers_json,
                            no_catalyst_config_snapshot_json,
                            extras_json
                        ) VALUES (
                            $1,$2,$3,$4,$5,$6,$7,$8,
                            $9,$10,$11,$12,$13,$14,
                            $15,$16,$17,$18,$19,$20,$21,
                            $22,$23,$24,$25,$26,$27,
                            $28,$29,$30,$31,$32,
                            $33,$34,$35,$36,$37,
                            $38
                        )
                        RETURNING id
                        """,
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
                        c.get("entry_mode"),
                        _bool(c.get("momentum_eligible")),
                        _int(c.get("momentum_score")),
                        _int(c.get("momentum_score_threshold")),
                        c.get("momentum_rejection_reason"),
                        json.dumps(c["momentum_gate_results"]) if c.get("momentum_gate_results") else None,
                        c.get("marketdata_source"),
                        _float(c.get("marketdata_age_seconds")),
                        _bool(c.get("marketdata_stale")) if c.get("marketdata_stale") is not None else None,
                        _bool(c.get("marketdata_fallback_used")) if c.get("marketdata_fallback_used") is not None else None,
                        c.get("marketdata_error"),
                        _bool(c.get("catalyst_required")) if c.get("catalyst_required") is not None else None,
                        _bool(c.get("no_catalyst_momentum_eligible")) if c.get("no_catalyst_momentum_eligible") is not None else None,
                        json.dumps(c["no_catalyst_momentum_reasons"]) if c.get("no_catalyst_momentum_reasons") else None,
                        json.dumps(c["no_catalyst_momentum_blockers"]) if c.get("no_catalyst_momentum_blockers") else None,
                        json.dumps(c["no_catalyst_config_snapshot"]) if c.get("no_catalyst_config_snapshot") else None,
                        _sanitize_extras_json(c),
                    )
                    if row_id is not None:
                        inserted_candidate_ids.append((int(row_id), c))

                # 2b. Forward-return outcomes: queue one pending row per
                # (candidate, horizon). Resolver fills future_* later.
                if inserted_candidate_ids:
                    outcome_rows = []
                    for cand_id, cand in inserted_candidate_ids:
                        ref_price = _float(cand.get("price"))
                        if ref_price is None:
                            ref_price = _float(cand.get("close")) or _float(cand.get("last_price"))
                        for horizon in _OUTCOME_HORIZONS:
                            outcome_rows.append(
                                (
                                    cand_id,
                                    tick_id,
                                    cand.get("symbol"),
                                    int(horizon),
                                    ref_price,
                                    now,
                                )
                            )
                    if outcome_rows:
                        await conn.executemany(
                            """
                            INSERT INTO paper_candidate_outcomes (
                                candidate_id, tick_id, symbol, horizon_minutes,
                                reference_price, reference_at, status
                            ) VALUES ($1,$2,$3,$4,$5,$6,'pending')
                            ON CONFLICT (candidate_id, horizon_minutes) DO NOTHING
                            """,
                            outcome_rows,
                        )

                # 3. Entry events (wallet_id default 'engine' preserves old rows)
                for entry in tick_result.get("entries") or []:
                    await conn.execute(
                        """
                        INSERT INTO paper_trades_journal (
                            tick_id, symbol, side, event,
                            entry_price, shares, cost_basis,
                            catalyst_type, total_score, opened_at, entry_mode,
                            position_id, wallet_id, strategy_id
                        ) VALUES ($1,$2,'long','entry',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                        """,
                        tick_id,
                        entry.get("symbol"),
                        _float(entry.get("entry_price")),
                        _float(entry.get("shares")),
                        _float(entry.get("cost_basis")),
                        entry.get("catalyst_type"),
                        _int(entry.get("total_score")),
                        now,
                        entry.get("entry_mode"),
                        entry.get("position_id"),
                        entry.get("wallet_id") or "engine",
                        entry.get("strategy_id") or "engine",
                    )

                # 4. Exit events
                for exit_ in tick_result.get("exits") or []:
                    await conn.execute(
                        """
                        INSERT INTO paper_trades_journal (
                            tick_id, symbol, side, event,
                            entry_price, exit_price, pnl, pnl_percent,
                            exit_reason, catalyst_type, total_score, closed_at,
                            entry_mode, position_id, shares, cost_basis,
                            wallet_id, strategy_id
                        ) VALUES ($1,$2,'long','exit',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
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
                        exit_.get("entry_mode"),
                        exit_.get("position_id"),
                        _float(exit_.get("shares")),
                        _float(exit_.get("cost_basis")),
                        exit_.get("wallet_id") or "engine",
                        exit_.get("strategy_id") or "engine",
                    )

                # 4b. Shadow wallet entries / exits (Phase G1B Part C).
                # Tagged with wallet_id ∈ {deterministic_shadow, ai_shadow}.
                for entry in tick_result.get("shadow_entries") or []:
                    await conn.execute(
                        """
                        INSERT INTO paper_trades_journal (
                            tick_id, symbol, side, event,
                            entry_price, shares, cost_basis,
                            catalyst_type, total_score, opened_at, entry_mode,
                            position_id, wallet_id, strategy_id
                        ) VALUES ($1,$2,'long','entry',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                        """,
                        tick_id,
                        entry.get("symbol"),
                        _float(entry.get("entry_price")),
                        _float(entry.get("shares")),
                        _float(entry.get("cost_basis")),
                        entry.get("catalyst_type"),
                        _int(entry.get("total_score")),
                        now,
                        entry.get("entry_mode"),
                        entry.get("position_id"),
                        entry.get("wallet_id"),
                        entry.get("strategy_id") or entry.get("wallet_id"),
                    )
                for exit_ in tick_result.get("shadow_exits") or []:
                    await conn.execute(
                        """
                        INSERT INTO paper_trades_journal (
                            tick_id, symbol, side, event,
                            entry_price, exit_price, pnl, pnl_percent,
                            exit_reason, catalyst_type, total_score, closed_at,
                            entry_mode, position_id, shares, cost_basis,
                            wallet_id, strategy_id
                        ) VALUES ($1,$2,'long','exit',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
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
                        exit_.get("entry_mode"),
                        exit_.get("position_id"),
                        _float(exit_.get("shares")),
                        _float(exit_.get("cost_basis")),
                        exit_.get("wallet_id"),
                        exit_.get("strategy_id") or exit_.get("wallet_id"),
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


# ── Phase G1B Part A: sanitized full-candidate snapshot ──────────────────────

def _sanitize_extras_json(candidate: dict) -> str | None:
    """
    Build the JSON payload for `paper_candidates.extras_json`.

    Includes the full runtime candidate dict (deterministic shadow, LLM,
    catalyst/news, reddit, premarket, earnings, insider, market regime,
    market trend, marketdata metadata, runtime config snapshot) so the
    freeze produces a complete record for later analysis. Secrets are
    redacted, raw bulky payloads are dropped, and the result is bounded
    to `_EXTRAS_MAX_BYTES` to keep write volume sane.

    Returns a JSON string ready for the JSONB column, or None if the
    candidate cannot be serialized.
    """
    try:
        from intelligence.llm_shadow import _redact
    except Exception:  # pragma: no cover — import safety
        def _redact(s: str | None) -> str:  # type: ignore[misc]
            return s or ""

    pruned = {k: v for k, v in candidate.items() if k not in _EXTRAS_DROP_KEYS}
    try:
        encoded = json.dumps(pruned, default=str, separators=(",", ":"))
    except Exception as exc:
        logger.debug("extras_json: encode failed for %s: %s",
                     candidate.get("symbol"), exc)
        return None

    redacted = _redact(encoded)

    if len(redacted.encode("utf-8")) > _EXTRAS_MAX_BYTES:
        envelope = {
            "_truncated": True,
            "_reason": "max_bytes_exceeded",
            "_max_bytes": _EXTRAS_MAX_BYTES,
            "symbol": candidate.get("symbol"),
            "tick_id": candidate.get("tick_id"),
            "eligible": candidate.get("eligible"),
            "action": candidate.get("action"),
            "rejection_reason": candidate.get("rejection_reason"),
            "entry_mode": candidate.get("entry_mode"),
            "final_selected_path": candidate.get("final_selected_path"),
            "total_score": candidate.get("total_score"),
            "enhanced_shadow_decision": candidate.get("enhanced_shadow_decision"),
            "llm_decision": candidate.get("llm_decision"),
            "llm_status": candidate.get("llm_status"),
        }
        try:
            redacted = _redact(json.dumps(envelope, default=str, separators=(",", ":")))
        except Exception:
            return None
    return redacted


