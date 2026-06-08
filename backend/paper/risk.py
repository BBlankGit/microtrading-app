"""
Daily loss guard for the fake-money paper simulator.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. Deterministic rule-based logic for research purposes only.

Blocks new fake-money entries when the account's daily P&L falls below the
configured loss threshold. Exits (stop-loss, take-profit, max-hold) are
never blocked. No liquidation. No upside ceiling.

Trading-day scoped (Phase 2N-H1):
  daily_pnl = current_equity - daily_start_equity
  Baseline resets at each new America/New_York calendar date.
  daily_start_equity is set by the simulator at startup and on date rollover.
"""

from paper.runtime_config import effective_value as _cfg


def daily_loss_guard_triggered(
    account,
    last_prices: dict[str, float],
) -> dict:
    """
    Evaluate whether the daily max loss guard should block new entries.

    Uses account.daily_start_equity as the trading-day baseline.
    daily_pnl = current_equity - daily_start_equity

    Returns a dict with: enabled, triggered, trading_date, daily_start_equity,
    current_equity, daily_pnl, daily_pnl_percent, threshold_percent,
    threshold_usd, reason. Never raises.
    """
    try:
        enabled = bool(_cfg("PAPER_DAILY_MAX_LOSS_ENABLED"))
        threshold_pct = float(_cfg("PAPER_DAILY_MAX_LOSS_PERCENT") or 2.0)
        threshold_usd_raw = _cfg("PAPER_DAILY_MAX_LOSS_USD")
        threshold_usd = float(threshold_usd_raw or 0.0)

        current_equity = account.get_equity(last_prices)
        daily_start_equity = float(account.daily_start_equity)
        trading_date = str(account.daily_baseline_date)

        daily_pnl = current_equity - daily_start_equity
        daily_pnl_pct = (
            (daily_pnl / daily_start_equity * 100)
            if daily_start_equity else 0.0
        )

        base = {
            "enabled": enabled,
            "trading_date": trading_date,
            "daily_start_equity": round(daily_start_equity, 4),
            "current_equity": round(current_equity, 4),
            "daily_pnl": round(daily_pnl, 4),
            "daily_pnl_percent": round(daily_pnl_pct, 4),
            "threshold_percent": threshold_pct,
            "threshold_usd": threshold_usd if threshold_usd > 0 else None,
        }

        if not enabled:
            return {**base, "triggered": False, "reason": None}

        triggered = False
        reason = None

        if daily_pnl_pct <= -abs(threshold_pct):
            triggered = True
            reason = "daily_max_loss_percent"

        if threshold_usd > 0 and daily_pnl <= -abs(threshold_usd):
            if not triggered:
                reason = "daily_max_loss_usd"
            triggered = True

        return {**base, "triggered": triggered, "reason": reason}
    except Exception:
        return {
            "triggered": False, "reason": None,
            "trading_date": "",
            "daily_start_equity": 0.0,
            "current_equity": 0.0,
            "daily_pnl": 0.0, "daily_pnl_percent": 0.0,
            "threshold_percent": 2.0, "threshold_usd": None,
            "enabled": False,
        }
