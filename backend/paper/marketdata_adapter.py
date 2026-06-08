"""
Market-data cache adapter for the paper simulator. Phase D2.
Cache-only lookup; Polygon fallback stays in the simulator.

No broker. No live trading. No real orders. No real-money execution.
All decisions based on fake-money research data only.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from paper.runtime_config import effective_value as _cfg

logger = logging.getLogger(__name__)

# Mirror constants from data.market_quality to avoid circular imports
_MIN_DAY_VOLUME = 500_000
_MIN_PREV_DAY_VOLUME = 1_000_000
_MAX_SPREAD_PERCENT = 0.50


async def try_cache_for_quality(sym: str) -> tuple[dict | None, dict]:
    """
    Check the shared Redis cache for market-quality data for sym.

    Returns (quality_dict | None, source_meta).
    - Fresh hit: quality_dict is populated, source_meta["marketdata_source"] == "cache"
    - Stale/miss + fallback enabled: None, source_meta["marketdata_source"] in ("stale","missing")
    - Stale/miss + fallback disabled: None, source_meta["marketdata_source"] ends with "_no_fallback"

    Never calls Polygon. Never raises.
    """
    max_age: int = _cfg("PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS")
    fallback: bool = _cfg("PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED")

    source_meta: dict[str, Any] = {
        "marketdata_source": "missing",
        "marketdata_age_seconds": None,
        "marketdata_fetched_at": None,
        "marketdata_stale": True,
    }

    try:
        from marketdata import cache as _cache
        payload = await _cache.read_symbol(sym)

        if payload and payload.get("raw_status") == "ok":
            fetched_at_str: str | None = payload.get("fetched_at")
            age_seconds: float | None = None
            if fetched_at_str:
                try:
                    fetched = datetime.fromisoformat(
                        fetched_at_str.replace("Z", "+00:00")
                    )
                    age_seconds = (
                        datetime.now(timezone.utc) - fetched
                    ).total_seconds()
                except Exception:
                    pass

            source_meta["marketdata_fetched_at"] = fetched_at_str
            source_meta["marketdata_age_seconds"] = (
                round(age_seconds, 2) if age_seconds is not None else None
            )

            if age_seconds is not None and age_seconds <= max_age:
                # Fresh cache hit — skip Polygon
                q = _build_quality_from_payload(sym, payload)
                source_meta["marketdata_source"] = "cache"
                source_meta["marketdata_stale"] = False
                return q, source_meta

            # Stale entry
            source_meta["marketdata_source"] = "stale" if fallback else "stale_no_fallback"
            return None, source_meta

        # Cache miss (no entry or raw_status != "ok")
        source_meta["marketdata_source"] = "missing" if fallback else "missing_no_fallback"
        return None, source_meta

    except Exception as exc:
        logger.debug("Cache read failed for %s: %s", sym, exc)
        source_meta["marketdata_source"] = (
            "cache_error" if fallback else "cache_error_no_fallback"
        )
        return None, source_meta


def _build_quality_from_payload(sym: str, payload: dict) -> dict:
    """
    Construct a quality dict from a SymbolPayload dict (as stored in Redis).

    Produces the same field shape as evaluate_market_quality() so downstream
    code (scorer, momentum evaluator, entry gates) is unaffected.
    Uses cached prev_day_volume when available (populated D2+ by the collector).
    """
    bid: float | None = payload.get("bid")
    ask: float | None = payload.get("ask")
    last_trade_price: float | None = payload.get("last_price")
    day_volume: float | None = payload.get("day_volume")
    prev_day_volume: float | None = payload.get("prev_day_volume")
    change_percent: float | None = payload.get("change_percent")
    spread_percent: float | None = payload.get("spread_percent")

    # Reconstruct spread absolute value
    spread: float | None = None
    if bid is not None and ask is not None and ask > 0:
        spread = round(ask - bid, 6)

    # Volume ratio (day vs prev session)
    volume_ratio: float | None = None
    if day_volume is not None and prev_day_volume and prev_day_volume > 0:
        volume_ratio = round(day_volume / prev_day_volume, 4)

    rejection_reasons: list[str] = []

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

    has_valid_trade = bool(last_trade_price is not None and last_trade_price > 0)
    if not has_valid_trade:
        rejection_reasons.append("last trade price is missing or zero")

    day_vol_ok = day_volume is not None and day_volume >= _MIN_DAY_VOLUME
    prev_vol_ok = (
        prev_day_volume is not None and prev_day_volume >= _MIN_PREV_DAY_VOLUME
    )
    has_sufficient_volume = day_vol_ok and prev_vol_ok
    if not day_vol_ok:
        rejection_reasons.append(
            f"day volume {int(day_volume) if day_volume is not None else 'N/A'} "
            f"below minimum {_MIN_DAY_VOLUME:,}"
        )
    if not prev_vol_ok:
        rejection_reasons.append(
            f"previous day volume "
            f"{int(prev_day_volume) if prev_day_volume is not None else 'N/A'} "
            f"below minimum {_MIN_PREV_DAY_VOLUME:,}"
        )

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
        "symbol": sym.upper(),
        "last_trade_price": last_trade_price,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "spread_percent": spread_percent,
        "bid_size": None,
        "ask_size": None,
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
