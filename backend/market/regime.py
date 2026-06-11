"""
Market regime monitor.

No broker. No live trading. No real orders. No real-money execution.
Fetches ETF snapshots from Polygon REST to compute a market breadth/risk score.
Regime data is used by selected fake-money entry gates (momentum, no-catalyst,
market-mover risk-off block). It does not place orders and does not affect exits.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from data import polygon_client
from paper.runtime_config import effective_value as _cfg

logger = logging.getLogger(__name__)

# Module-level cache
_cache: dict[str, Any] | None = None
_cache_time: float | None = None

DISCLAIMER = (
    "Used by selected fake-money entry gates (momentum, no-catalyst, market-mover risk-off). "
    "Does not place orders; does not affect exits. "
    "Research/fake-money simulation only. No broker. No live trading."
)


def clear_cache() -> None:
    """Reset cached regime data. Used in tests and after forced refresh."""
    global _cache, _cache_time
    _cache = None
    _cache_time = None


async def get_market_regime(force_refresh: bool = False) -> dict[str, Any]:
    """
    Return cached market regime data, refreshing if stale or forced.
    Never raises — returns error payload on failure.
    """
    global _cache, _cache_time

    if not force_refresh and _cache is not None and _cache_time is not None:
        elapsed = time.monotonic() - _cache_time
        if elapsed < _cfg("MARKET_REGIME_REFRESH_SECONDS"):
            return dict(_cache)

    try:
        result = await _build_regime()
    except Exception as exc:
        logger.warning("Market regime build failed: %s", exc)
        result = {
            "enabled": True,
            "symbols_requested": [],
            "symbols_fetched": [],
            "symbols_failed": [],
            "fetch_ratio": 0.0,
            "breadth": _empty_breadth(),
            "leaders": _empty_leaders(),
            "risk": {"regime": "unknown", "risk_on_score": None, "confidence": "unknown", "fetched_count": 0},
            "as_of": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "disclaimer": DISCLAIMER,
        }

    _cache = result
    _cache_time = time.monotonic()
    return dict(result)


async def _build_regime() -> dict[str, Any]:
    symbols = [s.strip().upper() for s in settings.MARKET_REGIME_SYMBOLS.split(",") if s.strip()]

    snapshots: dict[str, dict | None] = {}

    async def _fetch_symbol(sym: str) -> None:
        try:
            data = await polygon_client.get_ticker_snapshot(sym)
            snapshots[sym] = data
        except Exception as exc:
            logger.debug("Market regime: failed to fetch %s: %s", sym, exc)
            snapshots[sym] = None

    await asyncio.gather(*[_fetch_symbol(sym) for sym in symbols])

    valid = {sym: snap for sym, snap in snapshots.items() if snap is not None}
    failed = [sym for sym, snap in snapshots.items() if snap is None]

    total_requested = len(symbols)
    total_fetched = len(valid)
    fetch_ratio = total_fetched / total_requested if total_requested > 0 else 0.0

    # When no symbols were fetched, scoring is meaningless — return explicit unknown.
    # Calling _compute_risk() on empty data would produce a score of 20 → risk_off,
    # which is misleading: complete data failure is not the same as a bearish market.
    if total_fetched == 0:
        return {
            "enabled": True,
            "symbols_requested": symbols,
            "symbols_fetched": [],
            "symbols_failed": failed,
            "fetch_ratio": 0.0,
            "breadth": _empty_breadth(),
            "leaders": _empty_leaders(),
            "risk": {
                "regime": "unknown",
                "risk_on_score": None,
                "confidence": "unknown",
                "fetched_count": 0,
                "warnings": ["No market regime symbols fetched; regime unavailable."],
            },
            "as_of": datetime.now(timezone.utc).isoformat(),
            "error": "No market regime symbols fetched",
            "disclaimer": DISCLAIMER,
        }

    breadth = _compute_breadth(valid)
    leaders = _compute_leaders(valid)
    confidence = _data_confidence(fetch_ratio)
    risk = _compute_risk(breadth, leaders, confidence)

    return {
        "enabled": True,
        "symbols_requested": symbols,
        "symbols_fetched": list(valid.keys()),
        "symbols_failed": failed,
        "fetch_ratio": round(fetch_ratio, 3),
        "breadth": breadth,
        "leaders": leaders,
        "risk": risk,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
    }


def _compute_breadth(snapshots: dict[str, dict]) -> dict[str, Any]:
    if not snapshots:
        return _empty_breadth()

    positive = 0
    negative = 0
    flat = 0
    changes = []

    for snap in snapshots.values():
        chg = snap.get("change_percent")
        if chg is None:
            continue
        changes.append(chg)
        if chg > 0.1:
            positive += 1
        elif chg < -0.1:
            negative += 1
        else:
            flat += 1

    total = len(snapshots)
    positive_pct = round(positive / total * 100, 1) if total > 0 else None
    avg_chg = round(sum(changes) / len(changes), 3) if changes else None

    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "flat": flat,
        "positive_percent": positive_pct,
        "avg_change_percent": avg_chg,
    }


def _compute_leaders(snapshots: dict[str, dict]) -> dict[str, Any]:
    leader_syms = ["SPY", "QQQ", "IWM"]
    data: dict[str, dict | None] = {}

    for sym in leader_syms:
        snap = snapshots.get(sym)
        if snap:
            data[sym] = {
                "change_percent": snap.get("change_percent"),
                "last_trade_price": snap.get("last_trade_price"),
            }
        else:
            data[sym] = None

    bullish = 0
    bearish = 0
    for sym in leader_syms:
        entry = data.get(sym)
        if entry:
            chg = entry.get("change_percent")
            if chg is not None:
                if chg > 0.1:
                    bullish += 1
                elif chg < -0.1:
                    bearish += 1

    return {
        "data": data,
        "bullish_count": bullish,
        "bearish_count": bearish,
    }


def _compute_risk(
    breadth: dict[str, Any],
    leaders: dict[str, Any],
    confidence: str,
) -> dict[str, Any]:
    """
    Compute risk_on_score 0–100.

    Weights:
      60 pts — breadth (positive_percent maps to 0–60)
      40 pts — leaders (SPY/QQQ/IWM net-bullish ratio maps to 0–40, neutral = 20)
    """
    score = 0.0

    pos_pct = breadth.get("positive_percent")
    if pos_pct is not None:
        score += (pos_pct / 100.0) * 60.0

    bullish = leaders.get("bullish_count", 0)
    bearish = leaders.get("bearish_count", 0)
    net_ratio = (bullish - bearish) / 3.0  # -1 to +1
    score += 20.0 + net_ratio * 20.0

    risk_on_score = min(100, max(0, round(score)))

    if risk_on_score >= _cfg("MARKET_REGIME_MIN_RISK_ON_SCORE"):
        regime = "risk_on"
    elif risk_on_score <= _cfg("MARKET_REGIME_MAX_RISK_OFF_SCORE"):
        regime = "risk_off"
    else:
        regime = "neutral"

    return {
        "regime": regime,
        "risk_on_score": risk_on_score,
        "confidence": confidence,
        "fetched_count": breadth.get("total", 0),
        "warnings": [],
    }


def _data_confidence(fetch_ratio: float) -> str:
    if fetch_ratio >= 0.8:
        return "high"
    if fetch_ratio >= 0.5:
        return "medium"
    if fetch_ratio >= 0.25:
        return "low"
    return "unknown"


def _empty_breadth() -> dict[str, Any]:
    return {
        "total": 0,
        "positive": 0,
        "negative": 0,
        "flat": 0,
        "positive_percent": None,
        "avg_change_percent": None,
    }


def _empty_leaders() -> dict[str, Any]:
    return {
        "data": {"SPY": None, "QQQ": None, "IWM": None},
        "bullish_count": 0,
        "bearish_count": 0,
    }
