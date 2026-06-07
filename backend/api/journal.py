"""
Read-only journal API endpoints for the paper simulator history.
No auth required (read-only; no sensitive data exposed).
No broker. No real orders. Research-only fake-money simulation.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from paper import db as _db
from paper.journal import get_journal_status

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("/status")
async def journal_status():
    return get_journal_status()


@router.get("/summary")
async def journal_summary():
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    try:
        async with pool.acquire() as conn:
            ticks = await conn.fetchval("SELECT COUNT(*) FROM paper_ticks") or 0
            candidates = await conn.fetchval("SELECT COUNT(*) FROM paper_candidates") or 0
            entries = await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE event='entry'"
            ) or 0
            exits = await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE event='exit'"
            ) or 0
            first_at = await conn.fetchval("SELECT MIN(created_at) FROM paper_ticks")
            last_at = await conn.fetchval("SELECT MAX(created_at) FROM paper_ticks")
        return {
            "total_ticks": ticks,
            "total_candidates": candidates,
            "total_entries": entries,
            "total_exits": exits,
            "total_closed_trades": exits,
            "first_tick_at": first_at.isoformat() if first_at else None,
            "last_tick_at": last_at.isoformat() if last_at else None,
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/ticks")
async def journal_ticks(limit: int = Query(50, ge=1, le=500)):
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tick_id, started_at, completed_at,
                       symbols_evaluated, universe_active_count,
                       universe_refresh_reason, entries_made, exits_made,
                       errors_count, account_cash, account_equity,
                       realized_pnl, unrealized_pnl, total_pnl,
                       total_pnl_percent, created_at
                FROM paper_ticks
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [_row(r) for r in rows]
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/candidates")
async def journal_candidates(
    tick_id: str | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if tick_id:
            params.append(tick_id)
            conditions.append(f"tick_id = ${len(params)}")
        if symbol:
            params.append(symbol.upper())
            conditions.append(f"symbol = ${len(params)}")
        params.append(limit)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT tick_id, symbol, eligible, action, rejection_reason,
                       quality_tradable, spread_percent, change_percent,
                       volume_ratio, catalyst_count, catalyst_type,
                       total_score, score_threshold, score_pass,
                       score_components_json, positive_reasons_json,
                       negative_reasons_json, decision_reason, created_at
                FROM paper_candidates
                {where}
                ORDER BY created_at DESC
                LIMIT ${len(params)}
                """,
                *params,
            )
        return [_row(r) for r in rows]
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/trades")
async def journal_trades(limit: int = Query(100, ge=1, le=1000)):
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tick_id, symbol, side, event,
                       entry_price, exit_price, shares, cost_basis,
                       pnl, pnl_percent, exit_reason, catalyst_type,
                       total_score, opened_at, closed_at, created_at
                FROM paper_trades_journal
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [_row(r) for r in rows]
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/rejections")
async def journal_rejections(limit: int = Query(20, ge=1, le=100)):
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT rejection_reason, COUNT(*) AS count
                FROM paper_candidates
                WHERE rejection_reason IS NOT NULL
                GROUP BY rejection_reason
                ORDER BY count DESC
                LIMIT $1
                """,
                limit,
            )
        return [{"reason": r["rejection_reason"], "count": r["count"]} for r in rows]
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/performance")
async def journal_performance():
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT pnl, catalyst_type, total_score
                FROM paper_trades_journal
                WHERE event = 'exit' AND pnl IS NOT NULL
                """
            )
        if not rows:
            return {
                "total_trades": 0,
                "win_rate": None,
                "avg_win": None,
                "avg_loss": None,
                "profit_factor": None,
                "best_trade": None,
                "worst_trade": None,
                "pnl_by_catalyst_type": [],
                "pnl_by_score_bucket": [],
                "pnl_by_symbol": [],
            }

        pnls = [float(r["pnl"]) for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        decided = len(wins) + len(losses)

        by_cat: dict[str, list[float]] = {}
        for r in rows:
            ct = r["catalyst_type"] or "unknown"
            by_cat.setdefault(ct, []).append(float(r["pnl"]))

        by_bucket: dict[str, list[float]] = {
            "80+": [], "70-79": [], "50-69": [], "<50": [], "no_score": [],
        }
        for r in rows:
            sc = r["total_score"]
            p = float(r["pnl"])
            if sc is None:
                by_bucket["no_score"].append(p)
            elif sc >= 80:
                by_bucket["80+"].append(p)
            elif sc >= 70:
                by_bucket["70-79"].append(p)
            elif sc >= 50:
                by_bucket["50-69"].append(p)
            else:
                by_bucket["<50"].append(p)

        return {
            "total_trades": len(pnls),
            "win_rate": round(len(wins) / decided * 100, 2) if decided > 0 else None,
            "avg_win": round(sum(wins) / len(wins), 4) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 4) if losses else None,
            "profit_factor": (
                round(sum(wins) / abs(sum(losses)), 4)
                if wins and losses
                else None
            ),
            "best_trade": max(pnls),
            "worst_trade": min(pnls),
            "pnl_by_catalyst_type": [
                {"type": ct, "count": len(vs), "total_pnl": round(sum(vs), 4)}
                for ct, vs in sorted(
                    by_cat.items(), key=lambda x: sum(x[1]), reverse=True
                )
            ],
            "pnl_by_score_bucket": [
                {"bucket": bk, "count": len(vs), "total_pnl": round(sum(vs), 4)}
                for bk, vs in by_bucket.items()
                if vs
            ],
            "pnl_by_symbol": [],
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _disabled() -> dict:
    return {"error": "journal disabled or database unavailable"}


def _row(record: Any) -> dict:
    """Convert asyncpg Record to a JSON-serializable dict."""
    d = dict(record)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d
