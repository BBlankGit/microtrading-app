from typing import Any

_MIN_DAY_VOLUME = 500_000
_MIN_PREV_DAY_VOLUME = 1_000_000
_MAX_SPREAD_PERCENT = 0.50


def evaluate_market_quality(
    snapshot: dict[str, Any],
    previous_close: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate market data quality for a single ticker.

    Returns a structured dict with quality flags and rejection reasons.
    Does not make buy/sell decisions. Does not produce a score.
    tradable=True only when all quality gates pass.
    """
    symbol = snapshot.get("symbol", "")

    last_quote = snapshot.get("last_quote") or {}
    last_trade = snapshot.get("last_trade") or {}
    day = snapshot.get("day") or {}

    bid: float | None = last_quote.get("bid")
    ask: float | None = last_quote.get("ask")
    bid_size: int | None = last_quote.get("bid_size")
    ask_size: int | None = last_quote.get("ask_size")
    last_trade_price: float | None = last_trade.get("price")
    day_volume: float | None = day.get("volume")
    prev_day_volume: float | None = previous_close.get("volume")
    change_percent: float | None = snapshot.get("change_percent")

    # Spread
    spread: float | None = None
    spread_percent: float | None = None
    if bid is not None and ask is not None and ask > 0:
        spread = round(ask - bid, 6)
        spread_percent = round((spread / ask) * 100, 4)

    # Volume ratio (today vs previous session)
    volume_ratio: float | None = None
    if day_volume is not None and prev_day_volume and prev_day_volume > 0:
        volume_ratio = round(day_volume / prev_day_volume, 4)

    rejection_reasons: list[str] = []

    # Gate 1: valid quote
    has_valid_quote = bool(
        bid is not None and bid > 0
        and ask is not None and ask > 0
        and ask > bid
    )
    if not has_valid_quote:
        if bid is None or bid <= 0:
            rejection_reasons.append("bid is missing or zero")
        if ask is None or ask <= 0:
            rejection_reasons.append("ask is missing or zero")
        elif bid is not None and ask <= bid:
            rejection_reasons.append("ask is not greater than bid")

    # Gate 2: valid last trade
    has_valid_trade = bool(last_trade_price is not None and last_trade_price > 0)
    if not has_valid_trade:
        rejection_reasons.append("last trade price is missing or zero")

    # Gate 3: sufficient volume
    day_vol_ok = day_volume is not None and day_volume >= _MIN_DAY_VOLUME
    prev_vol_ok = prev_day_volume is not None and prev_day_volume >= _MIN_PREV_DAY_VOLUME
    has_sufficient_volume = day_vol_ok and prev_vol_ok
    if not day_vol_ok:
        rejection_reasons.append(
            f"day volume {int(day_volume) if day_volume is not None else 'N/A'} "
            f"below minimum {_MIN_DAY_VOLUME:,}"
        )
    if not prev_vol_ok:
        rejection_reasons.append(
            f"previous day volume {int(prev_day_volume) if prev_day_volume is not None else 'N/A'} "
            f"below minimum {_MIN_PREV_DAY_VOLUME:,}"
        )

    # Gate 4: acceptable spread
    if spread_percent is None:
        has_acceptable_spread = False
        rejection_reasons.append("spread cannot be calculated (missing bid or ask)")
    else:
        has_acceptable_spread = spread_percent <= _MAX_SPREAD_PERCENT
        if not has_acceptable_spread:
            rejection_reasons.append(
                f"spread {spread_percent:.4f}% exceeds maximum {_MAX_SPREAD_PERCENT}%"
            )

    tradable = (
        has_valid_quote
        and has_valid_trade
        and has_sufficient_volume
        and has_acceptable_spread
    )

    return {
        "symbol": symbol,
        "last_trade_price": last_trade_price,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "spread_percent": spread_percent,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "day_volume": day_volume,
        "previous_day_volume": prev_day_volume,
        "volume_ratio": volume_ratio,
        "change_percent": change_percent,
        "has_valid_quote": has_valid_quote,
        "has_valid_trade": has_valid_trade,
        "has_sufficient_volume": has_sufficient_volume,
        "has_acceptable_spread": has_acceptable_spread,
        "tradable": tradable,
        "rejection_reasons": rejection_reasons,
    }
