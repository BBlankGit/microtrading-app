"""
Fake-money paper simulator analytics — pure in-memory computation.
No broker. No real orders. No external API calls. Research-only.
"""

from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any


# ── Public API ────────────────────────────────────────────────────────────────

def get_trade_analytics(
    status: dict,
    positions: list[dict],
    trades: list[dict],
    candidates: list[dict],
    universe: dict | None,
) -> dict[str, Any]:
    """
    Compute analytics from current in-memory simulator state.

    Never raises. Returns None for metrics that cannot be calculated.
    No Polygon calls. No broker. No real orders. Research-only.
    """
    try:
        return {
            "session": _session(status),
            "pnl": _pnl(status, trades),
            "performance": _performance(trades),
            "candidate_funnel": _candidate_funnel(candidates),
            "score_distribution": _score_distribution(candidates),
            "rejections": _rejections(candidates),
            "catalysts": _catalysts(candidates, trades),
            "universe_health": _universe_health(universe),
            "market_session": _market_session(),
        }
    except Exception:
        return {"error": "analytics computation failed"}


# ── Section helpers ───────────────────────────────────────────────────────────

def _session(status: dict) -> dict:
    try:
        return {
            "running": bool(status.get("running")),
            "last_tick_at": status.get("last_tick_at"),
            "daily_trade_count": int(status.get("daily_trade_count") or 0),
            "max_trades_per_day": int(status.get("max_trades_per_day") or 0),
            "open_position_count": int(status.get("open_position_count") or 0),
            "closed_trade_count": int(status.get("closed_trade_count") or 0),
        }
    except Exception:
        return {
            "running": False, "last_tick_at": None,
            "daily_trade_count": 0, "max_trades_per_day": 0,
            "open_position_count": 0, "closed_trade_count": 0,
        }


def _pnl(status: dict, trades: list[dict]) -> dict:
    try:
        realized = float(status.get("realized_pnl") or 0)
        unrealized = float(status.get("unrealized_pnl") or 0)
        total = float(status.get("total_pnl") or 0)
        total_pct = float(status.get("total_pnl_percent") or 0)

        pnls = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
        best = round(max(pnls), 4) if pnls else None
        worst = round(min(pnls), 4) if pnls else None

        return {
            "realized_pnl": round(realized, 4),
            "unrealized_pnl": round(unrealized, 4),
            "total_pnl": round(total, 4),
            "total_pnl_percent": round(total_pct, 4),
            "best_trade_pnl": best,
            "worst_trade_pnl": worst,
        }
    except Exception:
        return {
            "realized_pnl": 0, "unrealized_pnl": 0, "total_pnl": 0,
            "total_pnl_percent": 0, "best_trade_pnl": None, "worst_trade_pnl": None,
        }


def _performance(trades: list[dict]) -> dict:
    try:
        if not trades:
            return {
                "wins": 0, "losses": 0, "breakeven": 0,
                "win_rate_percent": None, "average_win": None,
                "average_loss": None, "profit_factor": None,
                "average_hold_minutes": None,
            }

        winning = [float(t["pnl"]) for t in trades if float(t.get("pnl") or 0) > 0]
        losing  = [float(t["pnl"]) for t in trades if float(t.get("pnl") or 0) < 0]
        even    = [t for t in trades if float(t.get("pnl") or 0) == 0]

        wins = len(winning)
        losses = len(losing)
        breakeven = len(even)

        decided = wins + losses
        win_rate = round(wins / decided * 100, 2) if decided > 0 else None
        avg_win  = round(sum(winning) / wins, 4) if wins > 0 else None
        avg_loss = round(sum(losing) / losses, 4) if losses > 0 else None

        gross_loss = abs(sum(losing))
        profit_factor = round(sum(winning) / gross_loss, 4) if gross_loss > 0 else None

        hold_times = [
            float(t["hold_minutes"])
            for t in trades
            if t.get("hold_minutes") is not None
        ]
        avg_hold = round(sum(hold_times) / len(hold_times), 2) if hold_times else None

        return {
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate_percent": win_rate,
            "average_win": avg_win,
            "average_loss": avg_loss,
            "profit_factor": profit_factor,
            "average_hold_minutes": avg_hold,
        }
    except Exception:
        return {
            "wins": 0, "losses": 0, "breakeven": 0,
            "win_rate_percent": None, "average_win": None,
            "average_loss": None, "profit_factor": None,
            "average_hold_minutes": None,
        }


def _candidate_funnel(candidates: list[dict]) -> dict:
    try:
        total = len(candidates)
        eligible = sum(1 for c in candidates if c.get("eligible"))
        entered  = sum(1 for c in candidates if c.get("action") == "entered")
        score_rejected = sum(1 for c in candidates if c.get("action") == "score_rejected")
        # Hard rejected: hard gate set rejection_reason, action never assigned
        hard_rejected = sum(
            1 for c in candidates
            if c.get("action") is None and c.get("rejection_reason") is not None
        )
        blocked = sum(
            1 for c in candidates
            if isinstance(c.get("action"), str) and c["action"].startswith("blocked")
        )
        entry_failed = sum(
            1 for c in candidates
            if c.get("action") in ("entry_failed", "no_valid_price")
        )
        return {
            "total_candidates": total,
            "eligible": eligible,
            "entered": entered,
            "score_rejected": score_rejected,
            "hard_rejected": hard_rejected,
            "blocked": blocked,
            "entry_failed": entry_failed,
        }
    except Exception:
        return {
            "total_candidates": 0, "eligible": 0, "entered": 0,
            "score_rejected": 0, "hard_rejected": 0,
            "blocked": 0, "entry_failed": 0,
        }


def _score_distribution(candidates: list[dict]) -> dict:
    try:
        scores = [
            int(c["total_score"])
            for c in candidates
            if c.get("total_score") is not None
        ]
        threshold = next(
            (int(c["score_threshold"]) for c in candidates if c.get("score_threshold") is not None),
            70,
        )
        if not scores:
            return {
                "above_threshold": 0, "score_80_plus": 0,
                "score_70_to_79": 0, "score_50_to_69": 0,
                "below_50": 0, "average_score": None,
            }
        return {
            "above_threshold": sum(1 for s in scores if s >= threshold),
            "score_80_plus":   sum(1 for s in scores if s >= 80),
            "score_70_to_79":  sum(1 for s in scores if 70 <= s <= 79),
            "score_50_to_69":  sum(1 for s in scores if 50 <= s <= 69),
            "below_50":        sum(1 for s in scores if s < 50),
            "average_score":   round(sum(scores) / len(scores), 2),
        }
    except Exception:
        return {
            "above_threshold": 0, "score_80_plus": 0,
            "score_70_to_79": 0, "score_50_to_69": 0,
            "below_50": 0, "average_score": None,
        }


def _rejections(candidates: list[dict]) -> dict:
    try:
        reasons = [
            c["rejection_reason"]
            for c in candidates
            if c.get("rejection_reason")
        ]
        counts = Counter(reasons).most_common(5)
        return {
            "top_rejection_reasons": [
                {"reason": r, "count": n} for r, n in counts
            ]
        }
    except Exception:
        return {"top_rejection_reasons": []}


def _catalysts(candidates: list[dict], trades: list[dict]) -> dict:
    try:
        # Count from last-tick candidates (current session view)
        ctype_counts: Counter = Counter()
        for c in candidates:
            ct = c.get("catalyst_type")
            if ct:
                ctype_counts[ct] += 1
        # Supplement with closed trade catalyst types for session history
        for t in trades:
            ct = t.get("entry_catalyst_type")
            if ct:
                ctype_counts[ct] += 1
        sorted_types = sorted(ctype_counts.items(), key=lambda x: x[1], reverse=True)
        return {
            "by_type": [{"type": t, "count": n} for t, n in sorted_types]
        }
    except Exception:
        return {"by_type": []}


def _universe_health(universe: dict | None) -> dict:
    try:
        if universe is None:
            return {
                "active_count": None,
                "max_symbols_per_tick": None,
                "refresh_reason": "not built",
                "error_count": 0,
                "top_errors": [],
            }
        errors = universe.get("errors") or []
        return {
            "active_count": universe.get("active_count"),
            "max_symbols_per_tick": universe.get("max_symbols_per_tick"),
            "refresh_reason": universe.get("refresh_reason", "unknown"),
            "error_count": len(errors),
            "top_errors": errors[:3],
        }
    except Exception:
        return {
            "active_count": None, "max_symbols_per_tick": None,
            "refresh_reason": "error", "error_count": 0, "top_errors": [],
        }


def _market_session() -> dict:
    try:
        from zoneinfo import ZoneInfo
        ny_tz = ZoneInfo("America/New_York")
        now_ny = datetime.now(ny_tz)
        tz_label = "America/New_York"
    except Exception:
        # Fallback: approximate EDT (UTC-4) used for most of trading season
        now_ny = datetime.now(timezone(timedelta(hours=-4)))
        tz_label = "UTC-4 (approximate)"

    is_weekday = now_ny.weekday() < 5  # 0=Mon … 4=Fri
    t = now_ny.time()
    is_session = is_weekday and time(9, 30) <= t < time(16, 0)

    return {
        "timezone": tz_label,
        "regular_open": "09:30",
        "regular_close": "16:00",
        "is_regular_session_now": is_session,
        "note": "Best-effort clock only; does not account for market holidays yet.",
    }
