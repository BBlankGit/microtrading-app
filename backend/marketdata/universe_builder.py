"""
Dynamic symbol universe builder for the shared market-data collector. Phase D4.
Merges open positions, paper universe, V5 universe, base, and extra symbols.
No broker. No live trading. No real orders. No real-money execution.
No AI/LLM/Ollama.

Priority tiers (highest to lowest):
  Tier 0 — open positions (always kept, never budget-dropped)
  Tier 1 — paper universe active symbols
  Tier 2 — V5 MID symbols
  Tier 3 — base symbols + extra symbols

Symbols are de-duplicated (first occurrence wins) and normalized to uppercase.
When total > MARKETDATA_MAX_SYMBOLS_PER_CYCLE, lower-priority tiers are truncated first.
"""

from __future__ import annotations

import logging
from typing import Callable

from core.config import settings

logger = logging.getLogger(__name__)

# Optional callable registered by the paper simulator at startup.
# Returns the list of currently open position ticker symbols.
# No broker. No live trading. No real orders.
_positions_provider: Callable[[], list[str]] | None = None


def register_open_positions_provider(fn: Callable[[], list[str]]) -> None:
    """Register a callable that returns open position symbols (Tier 0).
    Called once at startup from main.py. No broker. No real orders.
    """
    global _positions_provider
    _positions_provider = fn


# ── Private tier collectors ───────────────────────────────────────────────────

def _get_open_position_symbols() -> list[str]:
    if _positions_provider is None:
        return []
    try:
        return [s.upper() for s in (_positions_provider() or []) if s]
    except Exception as exc:
        logger.debug("open_positions_provider error: %s", exc)
        return []


def _get_paper_universe_symbols() -> list[str]:
    if not settings.MARKETDATA_INCLUDE_PAPER_UNIVERSE:
        return []
    try:
        from paper.universe import get_cached_universe
        cached = get_cached_universe()
        if cached:
            return [s.upper() for s in (cached.get("active_symbols") or [])]
    except Exception as exc:
        logger.debug("paper universe read error: %s", exc)
    return []


def _get_v5_symbols() -> list[str]:
    if not settings.MARKETDATA_INCLUDE_V5_UNIVERSE:
        return []
    return settings.marketdata_v5_symbols_list()


def _dedup_ordered(lst: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in lst:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def build_collector_universe() -> tuple[list[str], dict]:
    """
    Build the merged collector symbol list from all configured sources.

    Returns (symbols, tier_info):
      symbols   — deduplicated list, priority-ordered, capped to max_symbols_per_cycle
      tier_info — per-tier counts and budget metadata for health/metrics reporting

    No broker. No live trading. No real orders. No Polygon calls.
    """
    max_syms = settings.MARKETDATA_MAX_SYMBOLS_PER_CYCLE

    tier0 = _dedup_ordered(_get_open_position_symbols())
    tier1 = _dedup_ordered(_get_paper_universe_symbols())
    tier2 = _dedup_ordered(_get_v5_symbols())
    tier3 = _dedup_ordered(
        settings.marketdata_base_symbols_list()
        + settings.marketdata_extra_symbols_list()
    )

    # Merge with global dedup — higher tiers claim symbols first
    seen_global: set[str] = set()
    included: dict[str, list[str]] = {
        "tier0": [], "tier1": [], "tier2": [], "tier3": []
    }

    for tier_name, tier_syms in [
        ("tier0", tier0), ("tier1", tier1), ("tier2", tier2), ("tier3", tier3)
    ]:
        for sym in tier_syms:
            if sym not in seen_global:
                seen_global.add(sym)
                included[tier_name].append(sym)

    total_before_cap = sum(len(v) for v in included.values())

    skipped_by_tier = {"tier0": 0, "tier1": 0, "tier2": 0, "tier3": 0}

    if total_before_cap <= max_syms:
        # No truncation needed
        final = (
            included["tier0"] + included["tier1"]
            + included["tier2"] + included["tier3"]
        )
    else:
        # Drop from lower tiers first: tier3 → tier2 → tier1; tier0 is never dropped
        to_drop = total_before_cap - max_syms

        drop_t3 = min(to_drop, len(included["tier3"]))
        skipped_by_tier["tier3"] = drop_t3
        to_drop -= drop_t3

        drop_t2 = min(to_drop, len(included["tier2"]))
        skipped_by_tier["tier2"] = drop_t2
        to_drop -= drop_t2

        drop_t1 = min(to_drop, len(included["tier1"]))
        skipped_by_tier["tier1"] = drop_t1

        keep_t1 = included["tier1"][:len(included["tier1"]) - skipped_by_tier["tier1"]]
        keep_t2 = included["tier2"][:len(included["tier2"]) - skipped_by_tier["tier2"]]
        keep_t3 = included["tier3"][:len(included["tier3"]) - skipped_by_tier["tier3"]]
        final = included["tier0"] + keep_t1 + keep_t2 + keep_t3

        skipped_total = sum(skipped_by_tier.values())
        logger.info(
            "universe builder: %d symbols (cap=%d), dropped %d: %s",
            len(final), max_syms, skipped_total, skipped_by_tier,
        )

    tier_info: dict = {
        "open_positions_count": len(included["tier0"]),
        "paper_universe_count": len(included["tier1"]),
        "v5_symbols_count": len(included["tier2"]),
        "base_extra_count": len(included["tier3"]),
        "total_before_cap": total_before_cap,
        "total_collector_symbols": len(final),
        "skipped_due_to_budget": sum(skipped_by_tier.values()),
        "skipped_by_tier": skipped_by_tier,
        "include_paper_universe": settings.MARKETDATA_INCLUDE_PAPER_UNIVERSE,
        "include_v5_universe": settings.MARKETDATA_INCLUDE_V5_UNIVERSE,
        "max_symbols_per_cycle": max_syms,
    }

    return final, tier_info
