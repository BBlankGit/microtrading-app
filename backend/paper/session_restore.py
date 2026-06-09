"""
Paper session restore — Redis-then-DB restore logic.

No broker. No live trading. No real orders. No real-money execution.
Research-only fake-money simulation. Restore is read-only from Redis/Postgres.
"""

import json
import logging
from datetime import date
from typing import Any

from data.redis_client import make_redis
from paper import db as _db
from paper.models import ClosedTrade, Position

logger = logging.getLogger(__name__)

_REDIS_KEY = "paper:state"


async def try_redis_restore(ny_today: str) -> dict[str, Any] | None:
    """
    Read paper:state from Redis. Return snapshot dict if it's for today's NY date.
    Returns None if unavailable, stale, or any error. Never raises.
    """
    try:
        r = make_redis()
        raw = await r.get(_REDIS_KEY)
        await r.aclose()
        if not raw:
            return None
        snapshot = json.loads(raw)
        if snapshot.get("daily_baseline_date") != ny_today:
            return None
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
                logger.warning("session_restore: skipping malformed open row: %s", exc)

        realized_pnl = sum(t.pnl for t in trades)
        open_cost_basis = sum(p.cost_basis for p in positions.values())
        cash = starting_cash + realized_pnl - open_cost_basis

        return {
            "trades": trades,
            "positions": positions,
            "cash": cash,
            "daily_trade_count": len(closed_rows) + len(open_rows),
            "daily_start_equity": starting_cash,
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
        result["warning"] = "cash_estimated_from_db"
        logger.info(
            "session_restore: DB fallback — closed=%d open=%d pnl=%.4f",
            result["closed_trades_count"],
            result["open_positions_count"],
            result["daily_realized_pnl"],
        )
        return result

    logger.info(
        "session_restore: no valid snapshot for today (%s); starting fresh.", ny_today
    )
    return result
