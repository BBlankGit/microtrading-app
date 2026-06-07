"""
Market-wide movers discovery layer — fake-money research only.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM calls. Fetches market movers from Polygon REST only.

Discovery expands the candidate pool only. It does not bypass quality gates,
scoring, sentiment checks, or fake-money limits. Research use only.
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from data import polygon_client
from data.polygon_client import PolygonError

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")

# Module-level cache
_cache: dict[str, Any] | None = None
_cache_time: float | None = None

DISCLAIMER = (
    "Discovery expands the candidate pool only. "
    "It does not bypass quality gates, scoring, sentiment checks, or fake-money limits. "
    "Research/fake-money simulation use only. No broker. No live trading. No real orders."
)


def clear_cache() -> None:
    """Reset discovery cache. Used in tests and after forced refresh."""
    global _cache, _cache_time
    _cache = None
    _cache_time = None


async def discover_market_movers(force_refresh: bool = False) -> dict[str, Any]:
    """
    Return cached market-wide mover discovery data, refreshing if stale or forced.
    Never raises — errors go into the returned payload.

    No broker. No live trading. No real orders. No AI/LLM.
    """
    global _cache, _cache_time

    if not settings.PAPER_MARKET_DISCOVERY_ENABLED:
        return _disabled_result()

    now_mono = time.monotonic()

    if not force_refresh and _cache is not None and _cache_time is not None:
        if now_mono - _cache_time < settings.PAPER_MARKET_DISCOVERY_REFRESH_SECONDS:
            return dict(_cache, refresh_reason="cached")

    refresh_reason = "startup" if _cache is None else ("manual" if force_refresh else "ttl")

    try:
        result = await _build_discovery(refresh_reason)
    except Exception as exc:
        logger.warning("Discovery build failed unexpectedly: %s", exc)
        result = _error_result(refresh_reason, str(exc))

    _cache = result
    _cache_time = now_mono
    return dict(result)


async def _build_discovery(refresh_reason: str) -> dict[str, Any]:
    sources: dict[str, list[str]] = {"gainers": [], "losers": [], "most_active": []}
    errors: list[str] = []
    warnings: list[str] = []

    # ── Gainers ───────────────────────────────────────────────────────────────
    if settings.PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS:
        try:
            raw = await polygon_client.get_market_movers("gainers")
            sources["gainers"] = _filter_movers(raw)
        except PolygonError as exc:
            errors.append(f"gainers: {exc}")
            logger.warning("Discovery gainers fetch failed: %s", exc)
        except Exception as exc:
            errors.append(f"gainers: {type(exc).__name__}: {exc}")
            logger.warning("Discovery gainers unexpected error: %s", exc)

    # ── Losers ────────────────────────────────────────────────────────────────
    if settings.PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS:
        try:
            raw = await polygon_client.get_market_movers("losers")
            sources["losers"] = _filter_movers(raw)
        except PolygonError as exc:
            errors.append(f"losers: {exc}")
            logger.warning("Discovery losers fetch failed: %s", exc)
        except Exception as exc:
            errors.append(f"losers: {type(exc).__name__}: {exc}")
            logger.warning("Discovery losers unexpected error: %s", exc)

    # ── Most active ───────────────────────────────────────────────────────────
    # Polygon REST does not expose a dedicated "most_active" movers endpoint.
    # Gainers + losers already cover high-movement active symbols.
    if settings.PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE:
        warnings.append(
            "most_active: no dedicated Polygon REST endpoint available; "
            "gainers and losers already cover the most active movers."
        )

    # ── Merge + deduplicate: gainers → losers → most_active ──────────────────
    seen: set[str] = set()
    discovered: list[str] = []
    for source_syms in (sources["gainers"], sources["losers"], sources["most_active"]):
        for sym in source_syms:
            if sym not in seen:
                seen.add(sym)
                discovered.append(sym)

    discovered = discovered[: settings.PAPER_MARKET_DISCOVERY_MAX_SYMBOLS]

    return {
        "enabled": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "refresh_reason": refresh_reason,
        "sources": sources,
        "discovered_symbols": discovered,
        "discovered_count": len(discovered),
        "errors": errors,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }


def _filter_movers(movers: list[dict]) -> list[str]:
    """Apply price/volume/change filters and return valid symbol strings."""
    result: list[str] = []
    min_price = settings.PAPER_MARKET_DISCOVERY_MIN_PRICE
    max_price = settings.PAPER_MARKET_DISCOVERY_MAX_PRICE
    min_volume = settings.PAPER_MARKET_DISCOVERY_MIN_VOLUME
    min_abs_change = settings.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT

    for m in movers:
        sym = m.get("symbol", "")
        if not sym or not _SYMBOL_RE.match(sym):
            continue

        price = m.get("last_trade_price") or m.get("ask") or m.get("bid")
        if price is None or price <= 0:
            continue
        if price < min_price or price > max_price:
            continue

        vol = m.get("day_volume")
        if vol is not None and vol < min_volume:
            continue

        chg = m.get("change_percent")
        if chg is not None and abs(chg) < min_abs_change:
            continue

        result.append(sym)

    return result


def _disabled_result() -> dict[str, Any]:
    return {
        "enabled": False,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "refresh_reason": "disabled",
        "sources": {"gainers": [], "losers": [], "most_active": []},
        "discovered_symbols": [],
        "discovered_count": 0,
        "errors": [],
        "warnings": [],
        "disclaimer": DISCLAIMER,
    }


def _error_result(refresh_reason: str, error: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "refresh_reason": refresh_reason,
        "sources": {"gainers": [], "losers": [], "most_active": []},
        "discovered_symbols": [],
        "discovered_count": 0,
        "errors": [f"build_error: {error}"],
        "warnings": [],
        "disclaimer": DISCLAIMER,
    }
