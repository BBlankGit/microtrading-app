"""
Virtual bracket-order intrabar exit detection for the paper simulator.

No broker. No live trading. No real orders. No real-money execution.
Research fake-money simulation only. Phase 2Q-Lite.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Per-symbol intrabar cache: {symbol: (monotonic_fetched_at, data_or_None)}
_intrabar_cache: dict[str, tuple[float, dict | None]] = {}
_CACHE_TTL = 20.0  # seconds — avoid re-fetching within the same tick cycle


def evaluate_virtual_bracket_exit(
    entry_price: float,
    tp_pct: float,
    sl_pct: float,
    quote: dict | None,
    intrabar: dict | None,
) -> dict[str, Any]:
    """
    Evaluate whether a virtual bracket-order exit should trigger.

    Uses intrabar high/low when available for accuracy between polling cycles.
    Falls back to point-in-time bid/last_trade_price when no intrabar data exists.

    Conservative rule: if both TP and SL are touched in the same interval,
    stop-loss wins (worst-case ordering).

    Returns a dict; never raises. No broker. Research only.
    """
    tp_price = entry_price * (1 + tp_pct / 100)
    sl_price = entry_price * (1 - sl_pct / 100)

    intrabar_high: float | None = intrabar.get("high") if intrabar else None
    intrabar_low: float | None = intrabar.get("low") if intrabar else None
    intrabar_source: str = (intrabar.get("source") or "point_in_time") if intrabar else "point_in_time"
    intrabar_timestamp: str | None = intrabar.get("bar_timestamp") if intrabar else None

    if intrabar_high is not None and intrabar_low is not None:
        tp_touched = intrabar_high >= tp_price
        sl_touched = intrabar_low <= sl_price

        if tp_touched and sl_touched:
            return {
                "should_exit": True,
                "exit_reason": "stop_loss_intrabar_both_touched_conservative",
                "exit_price": sl_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "tp_touched": True,
                "sl_touched": True,
                "intrabar_high": intrabar_high,
                "intrabar_low": intrabar_low,
                "intrabar_source": intrabar_source,
                "intrabar_timestamp": intrabar_timestamp,
                "conservative_both_touched": True,
                "note": (
                    "Both TP and SL touched in same interval; "
                    "conservative stop-loss ordering applied."
                ),
            }

        if tp_touched:
            return {
                "should_exit": True,
                "exit_reason": "take_profit_intrabar",
                "exit_price": tp_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "tp_touched": True,
                "sl_touched": False,
                "intrabar_high": intrabar_high,
                "intrabar_low": intrabar_low,
                "intrabar_source": intrabar_source,
                "intrabar_timestamp": intrabar_timestamp,
                "conservative_both_touched": False,
            }

        if sl_touched:
            return {
                "should_exit": True,
                "exit_reason": "stop_loss_intrabar",
                "exit_price": sl_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "tp_touched": False,
                "sl_touched": True,
                "intrabar_high": intrabar_high,
                "intrabar_low": intrabar_low,
                "intrabar_source": intrabar_source,
                "intrabar_timestamp": intrabar_timestamp,
                "conservative_both_touched": False,
            }

        # Intrabar data present but neither target touched
        return {
            "should_exit": False,
            "exit_reason": None,
            "exit_price": None,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "tp_touched": False,
            "sl_touched": False,
            "intrabar_high": intrabar_high,
            "intrabar_low": intrabar_low,
            "intrabar_source": intrabar_source,
            "intrabar_timestamp": intrabar_timestamp,
            "conservative_both_touched": False,
        }

    # ── Fallback: no intrabar data — point-in-time bid or last trade price ─────
    point_price: float | None = None
    if quote:
        point_price = quote.get("bid") or quote.get("last_trade_price")

    if point_price and point_price > 0:
        if point_price >= tp_price:
            return {
                "should_exit": True,
                "exit_reason": "take_profit",
                "exit_price": point_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "tp_touched": True,
                "sl_touched": False,
                "intrabar_high": None,
                "intrabar_low": None,
                "intrabar_source": "point_in_time",
                "intrabar_timestamp": None,
                "conservative_both_touched": False,
            }
        if point_price <= sl_price:
            return {
                "should_exit": True,
                "exit_reason": "stop_loss",
                "exit_price": point_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "tp_touched": False,
                "sl_touched": True,
                "intrabar_high": None,
                "intrabar_low": None,
                "intrabar_source": "point_in_time",
                "intrabar_timestamp": None,
                "conservative_both_touched": False,
            }

    return {
        "should_exit": False,
        "exit_reason": None,
        "exit_price": None,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "tp_touched": False,
        "sl_touched": False,
        "intrabar_high": None,
        "intrabar_low": None,
        "intrabar_source": "point_in_time",
        "intrabar_timestamp": None,
        "conservative_both_touched": False,
    }


async def get_intrabar_data(
    symbol: str,
    entry_time_iso: str,
    date_str: str,
) -> dict | None:
    """
    Fetch recent 1-minute bars for an open position; return composite high/low
    across all completed bars at or after the position's entry time.

    Results are cached for _CACHE_TTL seconds to avoid repeated API calls
    within the same tick cycle. Open positions only — never called for candidates.

    Returns None if no bars exist since entry or the fetch fails.
    No broker. Research only.
    """
    now_mono = time.monotonic()
    cached = _intrabar_cache.get(symbol)
    if cached is not None:
        fetched_at, data = cached
        if now_mono - fetched_at < _CACHE_TTL:
            return data

    try:
        from data import polygon_client  # imported here to allow easy mocking in tests
        bars = await polygon_client.get_recent_minute_bars(symbol, date_str, limit=5)
    except Exception as exc:
        logger.debug("intrabar fetch failed for %s: %s", symbol, exc)
        _intrabar_cache[symbol] = (now_mono, None)
        return None

    # Filter to bars that started at or after position entry
    try:
        entry_dt = datetime.fromisoformat(entry_time_iso.replace("Z", "+00:00"))
        entry_ms = int(entry_dt.timestamp() * 1000)
    except Exception:
        entry_ms = 0

    since = [b for b in bars if isinstance(b, dict) and b.get("t", 0) >= entry_ms]
    if not since:
        _intrabar_cache[symbol] = (now_mono, None)
        return None

    highs = [b["h"] for b in since if b.get("h") is not None]
    lows  = [b["l"] for b in since if b.get("l") is not None]
    if not highs or not lows:
        _intrabar_cache[symbol] = (now_mono, None)
        return None

    latest_ts_ms = max(b["t"] for b in since if b.get("t"))
    try:
        bar_ts = datetime.fromtimestamp(
            latest_ts_ms / 1000, tz=timezone.utc
        ).isoformat()
    except Exception:
        bar_ts = None

    data: dict = {
        "high": max(highs),
        "low": min(lows),
        "source": "1m_agg",
        "bar_timestamp": bar_ts,
        "bars_used": len(since),
    }
    _intrabar_cache[symbol] = (now_mono, data)
    return data


def clear_intrabar_cache() -> None:
    """Evict all cached intrabar entries. Used in tests."""
    _intrabar_cache.clear()
