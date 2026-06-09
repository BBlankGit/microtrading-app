"""
Read-only journal API endpoints for the paper simulator history.
No auth required (read-only; no sensitive data exposed).
Research-only fake-money simulation. No live trading. No real orders.
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response

from core.config import settings
from paper import db as _db
from paper.journal import get_journal_status

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("/status")
async def journal_status():
    from paper.journal import try_reinit
    j = get_journal_status()
    if not j["enabled"] and settings.DATABASE_URL:
        await try_reinit()
        j = get_journal_status()
    return {
        **j,
        "retention_days": settings.JOURNAL_RETENTION_DAYS,
        "auto_cleanup_enabled": False,
    }


@router.get("/retention/status")
async def journal_retention_status():
    base = {
        "retention_days": settings.JOURNAL_RETENTION_DAYS,
        "auto_cleanup_enabled": False,
    }
    pool = await _db.get_pool()
    if pool is None:
        return {**base, "total_ticks": None, "total_candidates": None,
                "oldest_tick_at": None, "newest_tick_at": None}
    try:
        async with pool.acquire() as conn:
            tick_row = await conn.fetchrow(
                """
                SELECT COUNT(*)::int AS total_ticks,
                       MIN(created_at) AS oldest_tick_at,
                       MAX(created_at) AS newest_tick_at
                FROM paper_ticks
                """
            )
            total_candidates = await conn.fetchval(
                "SELECT COUNT(*)::int FROM paper_candidates"
            ) or 0
        return {
            **base,
            "total_ticks": tick_row["total_ticks"] or 0,
            "total_candidates": total_candidates,
            "oldest_tick_at": tick_row["oldest_tick_at"].isoformat() if tick_row["oldest_tick_at"] else None,
            "newest_tick_at": tick_row["newest_tick_at"].isoformat() if tick_row["newest_tick_at"] else None,
        }
    except Exception as exc:
        return {
            **base,
            "total_ticks": None,
            "total_candidates": None,
            "oldest_tick_at": None,
            "newest_tick_at": None,
            "error": str(exc),
        }


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
                       negative_reasons_json, decision_reason,
                       entry_mode, catalyst_required,
                       no_catalyst_momentum_eligible,
                       no_catalyst_momentum_reasons_json,
                       no_catalyst_momentum_blockers_json,
                       no_catalyst_config_snapshot_json,
                       created_at
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
        elif hasattr(v, "__float__") and type(v).__name__ == "Decimal":
            d[k] = float(v)
    return d


# ── Today / session helpers ───────────────────────────────────────────────────

def _today_range() -> tuple[datetime, datetime, str]:
    """Return (today_start, today_end, date_str) using America/New_York trading date."""
    try:
        from zoneinfo import ZoneInfo
        ny_tz = ZoneInfo("America/New_York")
    except Exception:
        ny_tz = timezone(timedelta(hours=-4))
    now_ny = datetime.now(ny_tz)
    today_ny = now_ny.date()
    today_start = datetime(today_ny.year, today_ny.month, today_ny.day, tzinfo=ny_tz)
    today_end = today_start + timedelta(days=1)
    return today_start, today_end, today_ny.isoformat()


def _perf_stats(pnls: list[float]) -> dict:
    """Compute performance metrics from a list of closed-trade PnLs."""
    if not pnls:
        return {
            "win_rate_today": None,
            "average_win_today": None,
            "average_loss_today": None,
            "profit_factor_today": None,
        }
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    decided = len(wins) + len(losses)
    return {
        "win_rate_today": round(len(wins) / decided * 100, 2) if decided > 0 else None,
        "average_win_today": round(sum(wins) / len(wins), 4) if wins else None,
        "average_loss_today": round(sum(losses) / len(losses), 4) if losses else None,
        "profit_factor_today": (
            round(sum(wins) / abs(sum(losses)), 4) if wins and losses else None
        ),
    }


def _tick_age(last_tick_at_str: str | None) -> float | None:
    if not last_tick_at_str:
        return None
    try:
        lt = datetime.fromisoformat(last_tick_at_str)
        if lt.tzinfo is None:
            lt = lt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - lt).total_seconds(), 1)
    except Exception:
        return None


# ── Today endpoints ───────────────────────────────────────────────────────────

@router.get("/today/summary")
async def today_summary():
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    today_start, today_end, date_str = _today_range()
    try:
        async with pool.acquire() as conn:
            tr = await conn.fetchrow(
                """
                SELECT COUNT(*)::int AS total_ticks,
                       COALESCE(SUM(symbols_evaluated),0)::int AS symbols_evaluated,
                       COALESCE(SUM(entries_made),0)::int    AS total_entries,
                       COALESCE(SUM(exits_made),0)::int      AS total_exits,
                       MIN(started_at) AS first_tick_at,
                       MAX(started_at) AS last_tick_at
                FROM paper_ticks
                WHERE created_at >= $1 AND created_at < $2
                """,
                today_start, today_end,
            )
            cr = await conn.fetchrow(
                """
                SELECT COUNT(*)::int          AS total_candidates,
                       COUNT(DISTINCT symbol)::int AS unique_symbols
                FROM paper_candidates
                WHERE created_at >= $1 AND created_at < $2
                """,
                today_start, today_end,
            )
            pnl_rows = await conn.fetch(
                """
                SELECT pnl::float AS pnl
                FROM paper_trades_journal
                WHERE event = 'exit' AND pnl IS NOT NULL
                  AND created_at >= $1 AND created_at < $2
                """,
                today_start, today_end,
            )

        pnls = [r["pnl"] for r in pnl_rows]
        perf = _perf_stats(pnls)

        # Live state from in-memory simulator (non-fatal if unavailable)
        sim: dict = {}
        try:
            import paper.simulator as _sim
            sim = _sim.get_status()
        except Exception:
            pass

        from paper.journal import get_journal_status as _jst
        js = _jst()
        journal_healthy = js["enabled"] and js["database_connected"] and js["tables_ready"]

        db_last = tr["last_tick_at"].isoformat() if tr["last_tick_at"] else None
        live_last = sim.get("last_tick_at") or db_last
        age = _tick_age(live_last)

        notes: list[str] = []
        if not tr["total_ticks"]:
            notes.append("No ticks recorded today yet.")
        if not journal_healthy:
            notes.append("Journal unhealthy — tick data may not be persisted.")

        return {
            "trading_date": date_str,
            "total_ticks_today": tr["total_ticks"] or 0,
            "total_candidates_today": cr["total_candidates"] or 0,
            "total_entries_today": tr["total_entries"] or 0,
            "total_exits_today": tr["total_exits"] or 0,
            "symbols_evaluated_today": tr["symbols_evaluated"] or 0,
            "unique_symbols_seen_today": cr["unique_symbols"] or 0,
            "open_positions_current": sim.get("open_position_count", 0),
            "closed_trades_today": len(pnls),
            "realized_pnl_today": round(sum(pnls), 4) if pnls else None,
            "unrealized_pnl_current": sim.get("unrealized_pnl"),
            "total_pnl_current": sim.get("total_pnl"),
            "best_closed_trade_today": round(max(pnls), 4) if pnls else None,
            "worst_closed_trade_today": round(min(pnls), 4) if pnls else None,
            **perf,
            "first_tick_at": tr["first_tick_at"].isoformat() if tr["first_tick_at"] else None,
            "last_tick_at": db_last,
            "last_tick_age_seconds": age,
            "journal_healthy": journal_healthy,
            "notes": notes,
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/today/rejections")
async def today_rejections():
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    today_start, today_end, _ = _today_range()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT rejection_reason, COUNT(*)::int AS count
                FROM paper_candidates
                WHERE rejection_reason IS NOT NULL
                  AND created_at >= $1 AND created_at < $2
                GROUP BY rejection_reason
                ORDER BY count DESC
                LIMIT 20
                """,
                today_start, today_end,
            )
        return [{"reason": r["rejection_reason"], "count": r["count"]} for r in rows]
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/today/catalysts")
async def today_catalysts():
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    today_start, today_end, _ = _today_range()
    try:
        async with pool.acquire() as conn:
            cand_rows = await conn.fetch(
                """
                SELECT catalyst_type, COUNT(*)::int AS candidate_count
                FROM paper_candidates
                WHERE catalyst_type IS NOT NULL
                  AND created_at >= $1 AND created_at < $2
                GROUP BY catalyst_type
                """,
                today_start, today_end,
            )
            trade_rows = await conn.fetch(
                """
                SELECT catalyst_type,
                       COUNT(*) FILTER (WHERE event='entry')::int AS entries,
                       COUNT(*) FILTER (WHERE event='exit')::int  AS exits,
                       COALESCE(SUM(pnl) FILTER (WHERE event='exit'), 0)::float AS realized_pnl
                FROM paper_trades_journal
                WHERE catalyst_type IS NOT NULL
                  AND created_at >= $1 AND created_at < $2
                GROUP BY catalyst_type
                """,
                today_start, today_end,
            )

        trade_map = {r["catalyst_type"]: r for r in trade_rows}
        result = []
        for c in cand_rows:
            ct = c["catalyst_type"]
            t = trade_map.get(ct)
            result.append({
                "type": ct,
                "candidate_count": c["candidate_count"],
                "entries": t["entries"] if t else 0,
                "exits": t["exits"] if t else 0,
                "realized_pnl": round(t["realized_pnl"], 4) if t else None,
            })
        result.sort(key=lambda x: x["candidate_count"], reverse=True)
        return result
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/today/symbols")
async def today_symbols(limit: int = Query(50, ge=1, le=200)):
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    today_start, today_end, _ = _today_range()
    try:
        async with pool.acquire() as conn:
            cand_rows = await conn.fetch(
                """
                SELECT symbol,
                       COUNT(*)::int                              AS candidate_count,
                       ROUND(AVG(total_score)::numeric, 1)::float AS avg_score,
                       MAX(created_at)                           AS last_seen_at
                FROM paper_candidates
                WHERE created_at >= $1 AND created_at < $2
                GROUP BY symbol
                ORDER BY candidate_count DESC
                LIMIT $3
                """,
                today_start, today_end, limit,
            )
            trade_rows = await conn.fetch(
                """
                SELECT symbol,
                       COUNT(*) FILTER (WHERE event='entry')::int  AS entries,
                       COUNT(*) FILTER (WHERE event='exit')::int   AS exits,
                       COALESCE(SUM(pnl) FILTER (WHERE event='exit'), 0)::float AS realized_pnl
                FROM paper_trades_journal
                WHERE created_at >= $1 AND created_at < $2
                GROUP BY symbol
                """,
                today_start, today_end,
            )

        trade_map = {r["symbol"]: r for r in trade_rows}
        result = []
        for c in cand_rows:
            sym = c["symbol"]
            t = trade_map.get(sym)
            result.append({
                "symbol": sym,
                "candidate_count": c["candidate_count"],
                "entries": t["entries"] if t else 0,
                "exits": t["exits"] if t else 0,
                "realized_pnl": round(t["realized_pnl"], 4) if t else None,
                "avg_score": c["avg_score"],
                "last_seen_at": c["last_seen_at"].isoformat() if c["last_seen_at"] else None,
            })
        return result
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/today/report")
async def today_report():
    pool = await _db.get_pool()
    if pool is None:
        return _disabled()
    today_start, today_end, date_str = _today_range()
    try:
        # Reuse individual endpoint logic inline for one DB connection
        summary_resp = await today_summary()
        rejections_resp = await today_rejections()
        catalysts_resp = await today_catalysts()
        symbols_resp = await today_symbols()

        async with pool.acquire() as conn:
            tick_rows = await conn.fetch(
                """
                SELECT tick_id, started_at, completed_at,
                       symbols_evaluated, universe_active_count,
                       universe_refresh_reason, entries_made, exits_made,
                       errors_count, account_cash, account_equity,
                       realized_pnl, unrealized_pnl, total_pnl,
                       total_pnl_percent, created_at
                FROM paper_ticks
                WHERE created_at >= $1 AND created_at < $2
                ORDER BY created_at DESC
                LIMIT 5
                """,
                today_start, today_end,
            )

        return {
            "summary": summary_resp,
            "top_rejections": rejections_resp if isinstance(rejections_resp, list) else [],
            "catalysts": catalysts_resp if isinstance(catalysts_resp, list) else [],
            "symbols": symbols_resp if isinstance(symbols_resp, list) else [],
            "latest_ticks": [_row(r) for r in tick_rows],
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/today/report.csv")
async def today_report_csv():
    pool = await _db.get_pool()
    if pool is None:
        return Response(content="error,journal disabled or database unavailable\n", media_type="text/csv")
    _, _, date_str = _today_range()
    try:
        symbols_resp = await today_symbols(limit=200)
        if isinstance(symbols_resp, dict) and "error" in symbols_resp:
            return Response(
                content=f"error,{symbols_resp['error']}\n", media_type="text/csv"
            )
        rows = symbols_resp if isinstance(symbols_resp, list) else []

        out = io.StringIO()
        fields = ["trading_date", "symbol", "candidate_count",
                  "entries", "exits", "realized_pnl", "avg_score", "last_seen_at"]
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "trading_date": date_str})

        return Response(
            content=out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=paper_today_{date_str}.csv"},
        )
    except Exception as exc:
        return Response(content=f"error,{exc}\n", media_type="text/csv")
