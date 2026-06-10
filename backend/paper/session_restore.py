"""
Paper session restore — Redis-then-DB restore logic.

No broker. No live trading. No real orders. No real-money execution.
Research-only fake-money simulation. Restore is read-only from Redis/Postgres.
"""

import json
import logging
from datetime import date
from typing import Any

from core.config import settings
from data.redis_client import make_redis
from paper import db as _db
from paper.models import ClosedTrade, Position

logger = logging.getLogger(__name__)

_REDIS_KEY = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state:v2"

_ALLOWED_ENTRY_MODES: frozenset[str] = frozenset(
    {"catalyst", "momentum", "momentum_no_catalyst"}
)


async def _get_valid_journal_position_ids(ny_today: str) -> set[str] | None:
    """
    Return position_ids that have a matching entry event in the journal for ny_today.
    Returns None on DB error (callers fail-open: skip the journal check).
    """
    try:
        pool = await _db.get_pool()
        if pool is None:
            return None
        ny_date = date.fromisoformat(ny_today)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT position_id FROM paper_trades_journal
                WHERE event = 'entry'
                  AND position_id IS NOT NULL
                  AND (opened_at AT TIME ZONE 'America/New_York')::date = $1
                """,
                ny_date,
            )
        return {row["position_id"] for row in rows}
    except Exception as exc:
        logger.warning("session_restore: failed to fetch valid position_ids: %s", exc)
        return None


async def _get_closed_journal_position_ids() -> set[str] | None:
    """
    Return position_ids that have a matching exit event in the journal (any date).
    A position with an exit row is closed and must not be re-opened on restore.
    Returns None on DB error (callers fail-open: skip the closed check).
    """
    try:
        pool = await _db.get_pool()
        if pool is None:
            return None
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT position_id FROM paper_trades_journal
                WHERE event = 'exit'
                  AND position_id IS NOT NULL
                """
            )
        return {row["position_id"] for row in rows}
    except Exception as exc:
        logger.warning("session_restore: failed to fetch closed position_ids: %s", exc)
        return None


async def try_redis_restore(ny_today: str) -> dict[str, Any] | None:
    """
    Read the namespaced :v2 Redis key. Return snapshot if it's for today's NY date
    and was written by the Phase-2U-hardened code. Returns None otherwise.
    Never raises.

    Validation applied to every open position before returning the snapshot:
      1. schema_version must be 2 and saved_after_journal must be true.
      2. position_id must be non-empty.
      3. entry_mode must be in the allowed set (catalyst / momentum /
         momentum_no_catalyst). Missing/null emits missing_entry_mode_skipped.
      4. position_id must have a matching journal entry row (today).
         Missing entry emits orphaned_redis_position_skipped.
      5. position_id must NOT have a matching journal exit row (any date).
         Existing exit emits closed_position_skipped.
    """
    try:
        r = make_redis()
        raw = await r.get(_REDIS_KEY)
        await r.aclose()
        if not raw:
            return None
        snapshot = json.loads(raw)

        # ── Gate 1: date must match today ─────────────────────────────────────
        if snapshot.get("daily_baseline_date") != ny_today:
            return None

        # ── Gate 2: must have been saved by Phase-2U-hardened code ────────────
        if not snapshot.get("saved_after_journal"):
            logger.warning(
                "session_restore: rejected Redis snapshot: "
                "saved_after_journal missing/false (pre-Phase-2U snapshot)"
            )
            return None

        positions: dict[str, Any] = snapshot.get("positions") or {}
        if not positions:
            return snapshot

        # Fetch journal sets once; None means DB unavailable (fail-open).
        valid_pids = await _get_valid_journal_position_ids(ny_today)
        closed_pids = await _get_closed_journal_position_ids()

        filtered: dict[str, Any] = {}
        restore_warnings: list[str] = list(snapshot.get("restore_warnings") or [])

        for symbol, pos_data in positions.items():
            pid: str = pos_data.get("position_id") or ""
            entry_mode = pos_data.get("entry_mode")

            # ── Check 1: entry_mode must be in allowed set ─────────────────
            if entry_mode not in _ALLOWED_ENTRY_MODES:
                restore_warnings.append(
                    f"missing_entry_mode_skipped:{symbol}:{pid}"
                )
                logger.warning(
                    "session_restore: dropped %s/%s: entry_mode %r not in allowed set",
                    symbol, pid, entry_mode,
                )
                continue

            # ── Check 2: must have matching journal entry row ──────────────
            if valid_pids is not None and pid and pid not in valid_pids:
                restore_warnings.append(
                    f"orphaned_redis_position_skipped:{symbol}:{pid}"
                )
                logger.warning(
                    "session_restore: dropped %s/%s: no matching journal entry row",
                    symbol, pid,
                )
                continue

            # ── Check 3: must NOT have a journal exit row (already closed) ──
            if closed_pids is not None and pid and pid in closed_pids:
                restore_warnings.append(
                    f"closed_position_skipped:{symbol}:{pid}"
                )
                logger.warning(
                    "session_restore: dropped %s/%s: position already has exit row",
                    symbol, pid,
                )
                continue

            filtered[symbol] = pos_data

        snapshot = dict(snapshot)
        snapshot["positions"] = filtered
        snapshot["restore_warnings"] = restore_warnings
        return snapshot
    except Exception as exc:
        logger.warning("session_restore: Redis read failed: %s", exc)
        return None


async def try_db_restore(ny_today: str, starting_cash: float) -> dict[str, Any] | None:
    """
    Query paper_trades_journal for today's closed trades and open positions.
    Returns a data dict, or None on error/no pool. Never raises.

    Requires position_id column (added Phase 2S) for reliable open-position matching.
    Rows written before Phase 2S deployment have NULL position_id and are excluded
    from open-position restore; closed trades are always included.

    restore_warnings in the returned dict lists any excluded rows with reasons.
    """
    pool = await _db.get_pool()
    if pool is None:
        return None
    try:
        ny_date = date.fromisoformat(ny_today)

        async with pool.acquire() as conn:
            closed_rows = await conn.fetch(
                """
                SELECT symbol, entry_price, exit_price, shares, cost_basis,
                       pnl, pnl_percent, exit_reason, catalyst_type, total_score,
                       opened_at, closed_at, entry_mode, position_id
                FROM paper_trades_journal
                WHERE event = 'exit'
                  AND (closed_at AT TIME ZONE 'America/New_York')::date = $1
                ORDER BY closed_at ASC
                """,
                ny_date,
            )

            open_rows = await conn.fetch(
                """
                SELECT symbol, entry_price, shares, cost_basis, catalyst_type,
                       total_score, opened_at, entry_mode, position_id
                FROM paper_trades_journal
                WHERE event = 'entry'
                  AND position_id IS NOT NULL
                  AND (opened_at AT TIME ZONE 'America/New_York')::date = $1
                  AND position_id NOT IN (
                      SELECT position_id FROM paper_trades_journal
                      WHERE event = 'exit' AND position_id IS NOT NULL
                  )
                ORDER BY opened_at ASC
                """,
                ny_date,
            )

            # Count open entries skipped because position_id IS NULL
            # (rows written before Phase 2S deployment lack position_id)
            try:
                null_pid_count: int = await conn.fetchval(
                    """
                    SELECT COUNT(*)::int FROM paper_trades_journal
                    WHERE event = 'entry'
                      AND position_id IS NULL
                      AND (opened_at AT TIME ZONE 'America/New_York')::date = $1
                    """,
                    ny_date,
                ) or 0
            except Exception:
                null_pid_count = 0

            # Count open entries from prior NY days not yet exited
            # (excluded by the same-day filter above; useful diagnostics)
            try:
                prior_day_count: int = await conn.fetchval(
                    """
                    SELECT COUNT(*)::int FROM paper_trades_journal
                    WHERE event = 'entry'
                      AND position_id IS NOT NULL
                      AND (opened_at AT TIME ZONE 'America/New_York')::date < $1
                      AND position_id NOT IN (
                          SELECT position_id FROM paper_trades_journal
                          WHERE event = 'exit' AND position_id IS NOT NULL
                      )
                    """,
                    ny_date,
                ) or 0
            except Exception:
                prior_day_count = 0

        trades: list[ClosedTrade] = []
        for row in closed_rows:
            try:
                entry_time = row["opened_at"].isoformat() if row["opened_at"] else ""
                exit_time = row["closed_at"].isoformat() if row["closed_at"] else ""
                hold_minutes = 0.0
                if row["opened_at"] and row["closed_at"]:
                    hold_minutes = round(
                        (row["closed_at"] - row["opened_at"]).total_seconds() / 60, 1
                    )
                shares = float(row["shares"] or 0)
                exit_price = float(row["exit_price"] or 0)
                trades.append(
                    ClosedTrade(
                        position_id=row["position_id"] or "",
                        symbol=row["symbol"],
                        entry_price=float(row["entry_price"] or 0),
                        exit_price=exit_price,
                        shares=shares,
                        cost_basis=float(row["cost_basis"] or 0),
                        proceeds=round(shares * exit_price, 4),
                        pnl=float(row["pnl"] or 0),
                        pnl_percent=float(row["pnl_percent"] or 0),
                        entry_time=entry_time,
                        exit_time=exit_time,
                        exit_reason=row["exit_reason"] or "",
                        entry_catalyst_type=row["catalyst_type"] or "",
                        hold_minutes=hold_minutes,
                        entry_score=row["total_score"],
                        entry_mode=row["entry_mode"],
                    )
                )
            except Exception as exc:
                logger.warning("session_restore: skipping malformed closed row: %s", exc)

        positions: dict[str, Position] = {}
        skipped_malformed: int = 0
        for row in open_rows:
            try:
                sym = row["symbol"]
                if sym in positions:
                    continue  # dedup: keep earliest open entry per symbol
                positions[sym] = Position(
                    position_id=row["position_id"] or "",
                    symbol=sym,
                    entry_price=float(row["entry_price"] or 0),
                    shares=float(row["shares"] or 0),
                    cost_basis=float(row["cost_basis"] or 0),
                    entry_time=row["opened_at"].isoformat() if row["opened_at"] else "",
                    entry_catalyst_type=row["catalyst_type"] or "",
                    entry_score=row["total_score"],
                    entry_mode=row["entry_mode"],
                )
            except Exception as exc:
                skipped_malformed += 1
                logger.warning("session_restore: skipping malformed open row: %s", exc)

        realized_pnl = sum(t.pnl for t in trades)
        open_cost_basis = sum(p.cost_basis for p in positions.values())
        cash = starting_cash + realized_pnl - open_cost_basis

        restore_warnings: list[str] = []
        if null_pid_count:
            restore_warnings.append(
                f"{null_pid_count} open position entry row(s) skipped: "
                "position_id IS NULL (written before Phase 2S deployment; "
                "cannot reliably match entry to exit for restore)."
            )
            logger.warning(
                "session_restore: %d open entry row(s) with NULL position_id skipped.",
                null_pid_count,
            )
        if prior_day_count:
            restore_warnings.append(
                f"{prior_day_count} open position entry row(s) skipped: "
                "opened on a prior NY trading day (same-day restore only)."
            )
            logger.warning(
                "session_restore: %d prior-day open entry row(s) skipped.",
                prior_day_count,
            )
        if skipped_malformed:
            restore_warnings.append(
                f"{skipped_malformed} open position entry row(s) skipped: "
                "malformed row could not be reconstructed."
            )

        return {
            "trades": trades,
            "positions": positions,
            "cash": cash,
            "daily_trade_count": len(closed_rows) + len(open_rows),
            "daily_start_equity": starting_cash,
            "restore_warnings": restore_warnings,
            "skipped_open_positions_missing_position_id": null_pid_count,
            "skipped_open_positions_prior_day": prior_day_count,
            "skipped_open_positions_malformed": skipped_malformed,
        }

    except Exception as exc:
        logger.warning("session_restore: DB restore failed: %s", exc)
        return None


async def restore_session(ny_today: str, starting_cash: float) -> dict[str, Any]:
    """
    Orchestrate session restore: Redis first, DB fallback, then give up.
    Returns metadata dict describing what was restored. Never raises.
    """
    result: dict[str, Any] = {
        "source": "none",
        "snapshot": None,
        "db_data": None,
        "closed_trades_count": 0,
        "open_positions_count": 0,
        "daily_realized_pnl": 0.0,
        "trades_today": 0,
        "warning": None,
        "restore_warnings": [],
    }

    snapshot = await try_redis_restore(ny_today)
    if snapshot is not None:
        result["source"] = "redis"
        result["snapshot"] = snapshot
        trades_list = snapshot.get("trades") or []
        positions_map = snapshot.get("positions") or {}
        result["closed_trades_count"] = len(trades_list)
        result["open_positions_count"] = len(positions_map)
        result["daily_realized_pnl"] = round(
            sum(t.get("pnl", 0) for t in trades_list), 4
        )
        result["trades_today"] = int(snapshot.get("daily_trade_count", 0))
        logger.info(
            "session_restore: Redis OK — closed=%d open=%d pnl=%.4f",
            result["closed_trades_count"],
            result["open_positions_count"],
            result["daily_realized_pnl"],
        )
        return result

    db_data = await try_db_restore(ny_today, starting_cash)
    if db_data is not None:
        result["source"] = "db"
        result["db_data"] = db_data
        result["closed_trades_count"] = len(db_data["trades"])
        result["open_positions_count"] = len(db_data["positions"])
        result["daily_realized_pnl"] = round(
            sum(t.pnl for t in db_data["trades"]), 4
        )
        result["trades_today"] = int(db_data["daily_trade_count"])
        db_warnings = db_data.get("restore_warnings", [])
        result["restore_warnings"] = db_warnings
        # restore_warning: cash estimate note, plus any skip warnings surfaced together
        if db_warnings:
            result["warning"] = "cash_estimated_from_db; " + "; ".join(db_warnings)
        else:
            result["warning"] = "cash_estimated_from_db"
        logger.info(
            "session_restore: DB fallback — closed=%d open=%d pnl=%.4f warnings=%d",
            result["closed_trades_count"],
            result["open_positions_count"],
            result["daily_realized_pnl"],
            len(result["restore_warnings"]),
        )
        return result

    logger.info(
        "session_restore: no valid snapshot for today (%s); starting fresh.", ny_today
    )
    return result
