"""
Dynamic paper universe builder — fake-money research only.
No broker. No real orders. REST data only. No AI/LLM calls.
Includes market-wide movers discovery (Phase 2J) to expand candidate pool.
Discovery does not bypass quality gates, scoring, or any fake-money limits.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from data import polygon_client
from data.market_quality import evaluate_market_quality
from data.polygon_client import PolygonError
from paper.runtime_config import effective_value as _cfg

logger = logging.getLogger(__name__)

# Module-level memory cache — one instance per process
_universe_cache: dict[str, Any] | None = None
_cache_built_at: datetime | None = None


# ── Public API ────────────────────────────────────────────────────────────────

def get_base_universe() -> list[str]:
    """Return deduplicated, size-capped list from PAPER_BASE_UNIVERSE config."""
    return settings.paper_base_universe_list()


async def build_dynamic_universe(force_refresh: bool = False) -> dict[str, Any]:
    """
    Fetch market quality for base symbols, apply eligibility filters, rank,
    and cap to PAPER_MAX_SYMBOLS_PER_TICK active symbols.

    Caches result in memory; re-uses if within PAPER_DYNAMIC_REFRESH_SECONDS.
    Falls back to first N base symbols if dynamic disabled or all fetches fail.
    Never raises — errors go into the returned errors list.

    No broker. No real orders. REST data only.
    """
    global _universe_cache, _cache_built_at

    now = datetime.now(timezone.utc)

    # Determine refresh reason
    if _universe_cache is None:
        reason = "startup"
    elif force_refresh:
        reason = "manual"
    else:
        reason = "ttl"

    # Return cached result if within TTL
    if not force_refresh and _universe_cache is not None and _cache_built_at is not None:
        elapsed = (now - _cache_built_at).total_seconds()
        if elapsed < _cfg("PAPER_DYNAMIC_REFRESH_SECONDS"):
            return dict(_universe_cache, refresh_reason="cached")

    base = get_base_universe()

    # Dynamic disabled — fall back to first N base symbols
    if not _cfg("PAPER_DYNAMIC_UNIVERSE_ENABLED"):
        active = base[:_cfg("PAPER_MAX_SYMBOLS_PER_TICK")]
        result = _make_result(base, [], active, now, "disabled", [], None)
        _universe_cache = result
        _cache_built_at = now
        return result

    # ── Market-wide discovery (Phase 2J) ──────────────────────────────────────
    discovery_result: dict | None = None
    discovered_syms: list[str] = []
    if _cfg("PAPER_MARKET_DISCOVERY_ENABLED"):
        try:
            from paper.discovery import discover_market_movers
            discovery_result = await discover_market_movers(force_refresh=force_refresh)
            discovered_syms = discovery_result.get("discovered_symbols") or []
        except Exception as exc:
            logger.warning("Universe: discovery call failed: %s", exc)
            discovery_result = {
                "enabled": True,
                "discovered_symbols": [],
                "discovered_count": 0,
                "errors": [f"{type(exc).__name__}: {exc}"],
                "warnings": [],
            }

    # Merge: discovered movers first (priority), then base symbols, dedup, cap
    seen_merge: set[str] = set()
    candidate_pool: list[str] = []
    for sym in discovered_syms + base:
        if sym not in seen_merge:
            seen_merge.add(sym)
            candidate_pool.append(sym)
    candidate_pool = candidate_pool[: _cfg("PAPER_MAX_UNIVERSE_SIZE")]

    # Fetch quality for all candidate symbols concurrently
    quality_map: dict[str, dict] = {}
    errors: list[dict] = []

    async def _fetch(sym: str) -> None:
        try:
            snapshot = await polygon_client.get_ticker_snapshot(sym)
            prev = await polygon_client.get_previous_close(sym)
            q = evaluate_market_quality(snapshot, prev)
            quality_map[sym] = q
        except PolygonError as exc:
            errors.append({"symbol": sym, "error": str(exc)})
        except Exception as exc:
            errors.append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"})

    await asyncio.gather(*[_fetch(sym) for sym in candidate_pool])

    # All fetches failed — fall back
    if not quality_map:
        active = base[:_cfg("PAPER_MAX_SYMBOLS_PER_TICK")]
        result = _make_result(base, [], active, now, f"{reason}_fallback", errors, discovery_result)
        _universe_cache = result
        _cache_built_at = now
        return result

    # Apply eligibility filters against the merged candidate pool
    filtered: list[tuple[str, dict]] = [
        (sym, quality_map[sym])
        for sym in candidate_pool
        if sym in quality_map and _passes_eligibility(quality_map[sym])
    ]

    # Rank: tradable first, abs change_percent desc, volume_ratio desc, spread_percent asc
    filtered.sort(key=lambda x: _rank_key(x[1]), reverse=True)

    dynamic_syms = [sym for sym, _ in filtered]
    active = dynamic_syms[:_cfg("PAPER_MAX_SYMBOLS_PER_TICK")]

    # Nothing survived filtering — fall back to first N base symbols
    if not active:
        active = base[:_cfg("PAPER_MAX_SYMBOLS_PER_TICK")]
        reason = f"{reason}_fallback"

    result = _make_result(base, dynamic_syms, active, now, reason, errors, discovery_result)
    _universe_cache = result
    _cache_built_at = now
    return result


async def get_active_paper_universe() -> dict[str, Any]:
    """Return active universe, building or refreshing if the TTL has expired."""
    return await build_dynamic_universe(force_refresh=False)


def get_cached_universe() -> dict[str, Any] | None:
    """Return the current cached universe without triggering a build. None if not built."""
    return dict(_universe_cache) if _universe_cache is not None else None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _passes_eligibility(q: dict) -> bool:
    """True if quality data clears the basic universe pre-filter."""
    price = q.get("last_trade_price") or q.get("ask")
    if price is not None and price > 0:
        if price < settings.PAPER_MIN_PRICE or price > settings.PAPER_MAX_PRICE:
            return False

    day_vol = q.get("day_volume")
    if day_vol is not None and day_vol < settings.PAPER_MIN_DAY_VOLUME:
        return False

    change_pct = q.get("change_percent")
    if change_pct is not None and abs(change_pct) < settings.PAPER_MIN_CHANGE_ABS_PERCENT:
        return False

    spread_pct = q.get("spread_percent")
    if spread_pct is not None and spread_pct > 0.50:
        return False

    return True


def _rank_key(q: dict) -> tuple:
    """Higher tuple → ranked first (sort descending)."""
    tradable = 1 if q.get("tradable") else 0
    change_abs = abs(q.get("change_percent") or 0.0)
    vol_ratio = q.get("volume_ratio") or 0.0
    spread = q.get("spread_percent") or 999.0
    # Negate spread so tighter spread ranks higher when reversed
    return (tradable, change_abs, vol_ratio, -spread)


def _make_result(
    base: list[str],
    dynamic: list[str],
    active: list[str],
    ts: datetime,
    reason: str,
    errors: list[dict],
    discovery: dict | None,
) -> dict[str, Any]:
    discovery_summary: dict[str, Any] = {
        "enabled": False,
        "discovered_count": 0,
        "discovered_symbols": [],
        "refresh_reason": None,
        "errors": [],
        "warnings": [],
    }
    if discovery is not None:
        discovery_summary = {
            "enabled": discovery.get("enabled", False),
            "discovered_count": discovery.get("discovered_count", 0),
            "discovered_symbols": (discovery.get("discovered_symbols") or [])[:50],
            "refresh_reason": discovery.get("refresh_reason"),
            "errors": discovery.get("errors") or [],
            "warnings": discovery.get("warnings") or [],
        }
    return {
        "base_symbols": base,
        "dynamic_symbols": dynamic,
        "active_symbols": active,
        "active_count": len(active),
        "max_symbols_per_tick": _cfg("PAPER_MAX_SYMBOLS_PER_TICK"),
        "last_refreshed_at": ts.isoformat(),
        "refresh_reason": reason,
        "errors": errors,
        "discovery": discovery_summary,
    }
