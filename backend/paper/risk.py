"""
Daily loss guard for the fake-money paper simulator.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. Deterministic rule-based logic for research purposes only.

Blocks new fake-money entries when the account's cumulative P&L
(realized + unrealized since simulator start) falls below the configured
loss threshold. Exits (stop-loss, take-profit, max-hold) are never blocked.

MVP baseline: starting_cash is used as the day baseline. No date-rollover
tracking — guard reflects cumulative P&L since simulator start or last reset.
"""

from paper.runtime_config import effective_value as _cfg


def daily_loss_guard_triggered(
    account,
    last_prices: dict[str, float],
) -> dict:
    """
    Evaluate whether the daily max loss guard should block new entries.

    Returns a dict with triggered, reason, daily_pnl, daily_pnl_percent,
    threshold_percent, threshold_usd, and enabled. Never raises.
    """
    try:
        enabled = bool(_cfg("PAPER_DAILY_MAX_LOSS_ENABLED"))
        threshold_pct = float(_cfg("PAPER_DAILY_MAX_LOSS_PERCENT") or 2.0)
        threshold_usd_raw = _cfg("PAPER_DAILY_MAX_LOSS_USD")
        threshold_usd = float(threshold_usd_raw or 0.0)

        realized = account.get_realized_pnl()
        unrealized = account.get_unrealized_pnl(last_prices)
        daily_pnl = realized + unrealized
        daily_pnl_pct = (
            (daily_pnl / account.starting_cash * 100)
            if account.starting_cash else 0.0
        )

        base = {
            "enabled": enabled,
            "daily_pnl": round(daily_pnl, 4),
            "daily_pnl_percent": round(daily_pnl_pct, 4),
            "threshold_percent": threshold_pct,
            "threshold_usd": threshold_usd if threshold_usd > 0 else None,
        }

        if not enabled:
            return {**base, "triggered": False, "reason": None}

        triggered = False
        reason = None

        if daily_pnl_pct < -abs(threshold_pct):
            triggered = True
            reason = "daily_max_loss_percent"

        if threshold_usd > 0 and daily_pnl < -abs(threshold_usd):
            if not triggered:
                reason = "daily_max_loss_usd"
            triggered = True

        return {**base, "triggered": triggered, "reason": reason}
    except Exception:
        return {
            "triggered": False, "reason": None,
            "daily_pnl": 0.0, "daily_pnl_percent": 0.0,
            "threshold_percent": 2.0, "threshold_usd": None,
            "enabled": False,
        }
