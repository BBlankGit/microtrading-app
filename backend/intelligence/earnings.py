"""
Earnings calendar intelligence — read-only feed and scoring input.

No broker. No live trading. No real orders. No AI/LLM calls.
Fake-money simulation only. All scoring is deterministic rule-based.

Data source is gated by `EARNINGS_DATA_PROVIDER`:
  - "none"     → enabled=false; honest "not configured" payload, no fake data.
  - "polygon"  → wired but no reliable earnings-calendar endpoint exists in
                 the basic Polygon plan; treated as enabled=false until a
                 real provider is hooked up.
  - "finnhub"  → reserved for a future FINNHUB_API_KEY configuration.

Scoring contributes 0 when no per-symbol data exists, so the integration is
safe to ship even before a provider is configured.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, date, timezone, timedelta
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# ── In-memory cache ───────────────────────────────────────────────────────────
_cache: dict | None = None
_cache_time: float | None = None
_fetch_lock = asyncio.Lock()


def cache_age_seconds() -> float | None:
    if _cache_time is None:
        return None
    return max(0.0, time.monotonic() - _cache_time)


def cache_is_fresh() -> bool:
    age = cache_age_seconds()
    return age is not None and age < settings.EARNINGS_CACHE_TTL_SECONDS


def provider() -> str:
    return (settings.EARNINGS_DATA_PROVIDER or "none").strip().lower()


def is_enabled() -> bool:
    return provider() not in ("", "none")


def get_results_by_symbol() -> dict[str, dict]:
    """Return cached results indexed by ticker for the scoring path."""
    if not _cache:
        return {}
    out: dict[str, dict] = {}
    for r in _cache.get("results") or []:
        sym = (r.get("ticker") or r.get("symbol") or "").upper()
        if not sym:
            continue
        prior = out.get(sym)
        if prior is None or (r.get("days_until") is not None and prior.get("days_until") is not None
                             and r["days_until"] < prior["days_until"]):
            out[sym] = r
    return out


def _normalize_row(raw: dict, today: date) -> dict:
    """Normalize a provider-specific raw row to our canonical earnings schema."""
    ticker = (raw.get("symbol") or raw.get("ticker") or "").upper()
    report_date_s = raw.get("report_date") or raw.get("date") or raw.get("epsActualDate")
    report_time = (raw.get("report_time") or raw.get("hour") or "unknown").lower()
    if report_time in ("bmo", "before_market"):
        report_time = "before_open"
    elif report_time in ("amc", "after_market"):
        report_time = "after_close"
    elif report_time in ("dmh", "during_market", "during"):
        report_time = "during_market"

    try:
        d = date.fromisoformat(str(report_date_s)[:10])
        days_until = (d - today).days
    except Exception:
        d = None
        days_until = None

    return {
        "ticker": ticker,
        "report_date": report_date_s,
        "report_time": report_time,
        "eps_estimate": raw.get("eps_estimate") or raw.get("epsEstimate"),
        "revenue_estimate": raw.get("revenue_estimate") or raw.get("revenueEstimate"),
        "eps_actual": raw.get("eps_actual") or raw.get("epsActual"),
        "revenue_actual": raw.get("revenue_actual") or raw.get("revenueActual"),
        "surprise": raw.get("surprise"),
        "confirmed": raw.get("confirmed") if raw.get("confirmed") is not None else "unknown",
        "days_until": days_until,
        "source": raw.get("source") or provider(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def fetch_and_refresh(force: bool = False) -> dict:
    """
    Single-flight refresh. Returns the cache payload (or a disabled payload
    when no provider is configured). Never raises.
    """
    global _cache, _cache_time

    async with _fetch_lock:
        if not force and cache_is_fresh() and _cache is not None:
            return _cache

        if not is_enabled():
            _cache = {
                "enabled": False,
                "implemented": True,
                "source": "none",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "results": [],
                "errors": [],
                "warning": (
                    "Earnings calendar provider not configured "
                    "(EARNINGS_DATA_PROVIDER=none). Set EARNINGS_DATA_PROVIDER "
                    "and the matching API key to enable real data."
                ),
            }
            _cache_time = time.monotonic()
            return _cache

        # Provider-specific fetchers go here. As of Phase I6 no provider is
        # wired in code; surfaces enabled=false with a clear warning rather
        # than fabricate rows.
        try:
            results_raw: list[dict] = []
            errors: list[dict] = []
            warning: str | None = None
            prov = provider()
            if prov == "polygon":
                warning = (
                    "Polygon REST does not expose a reliable earnings calendar; "
                    "leaving cache empty until a dedicated earnings provider is wired."
                )
            elif prov == "finnhub":
                warning = (
                    "Finnhub provider stub not yet wired. "
                    "Set FINNHUB_API_KEY and implement the fetcher to enable."
                )
            else:
                warning = f"Unknown EARNINGS_DATA_PROVIDER={prov!r}; no data fetched."

            today = date.today()
            results = [_normalize_row(r, today) for r in results_raw]
            _cache = {
                "enabled": True,
                "implemented": True,
                "source": prov,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "results": results,
                "errors": errors,
                "warning": warning,
            }
            _cache_time = time.monotonic()
            return _cache
        except Exception as exc:
            logger.warning("Earnings fetch failed: %s", exc)
            keep = _cache or {
                "enabled": True,
                "implemented": True,
                "source": provider(),
                "fetched_at": None,
                "results": [],
                "errors": [],
                "warning": None,
            }
            keep["errors"] = (keep.get("errors") or []) + [{"error": f"{type(exc).__name__}: {exc}"}]
            keep["warning"] = "Last fetch failed; serving previous cache (if any)."
            _cache = keep
            _cache_time = time.monotonic()
            return _cache


def get_snapshot() -> dict | None:
    """Snapshot accessor; returns the raw cache dict or None."""
    return _cache


def score_earnings_proximity(symbol: str, info_by_symbol: dict[str, dict]) -> dict:
    """
    Compute the deterministic earnings proximity adjustment for a symbol.

    Returns a transparent dict:
      {
        "enabled": bool,
        "earnings_next_date": str | None,
        "earnings_days_until": int | None,
        "earnings_score_adjustment": int (<= 0),
        "earnings_reason": str,
        "earnings_blocked": bool,
      }

    Earnings calendar alone never creates an entry. It only adjusts the
    score (and optionally hard-blocks within PAPER_EARNINGS_BLOCK_WITHIN_DAYS).
    """
    base = {
        "enabled": settings.PAPER_EARNINGS_SCORING_ENABLED,
        "earnings_next_date": None,
        "earnings_days_until": None,
        "earnings_score_adjustment": 0,
        "earnings_reason": "no earnings data",
        "earnings_blocked": False,
    }
    if not settings.PAPER_EARNINGS_SCORING_ENABLED:
        base["earnings_reason"] = "earnings scoring disabled"
        return base
    info = info_by_symbol.get(symbol.upper())
    if not info:
        return base

    days = info.get("days_until")
    base["earnings_next_date"] = info.get("report_date")
    base["earnings_days_until"] = days
    if days is None or days < 0:
        base["earnings_reason"] = "no upcoming earnings date"
        return base

    block_days = settings.PAPER_EARNINGS_BLOCK_WITHIN_DAYS
    if block_days is not None and block_days > 0 and days <= block_days:
        base["earnings_blocked"] = True
        base["earnings_score_adjustment"] = settings.PAPER_EARNINGS_STRONG_PENALTY_POINTS
        base["earnings_reason"] = f"earnings within {days}d — hard block configured"
        return base

    if days <= settings.PAPER_EARNINGS_STRONG_PENALTY_WITHIN_DAYS:
        adj = settings.PAPER_EARNINGS_STRONG_PENALTY_POINTS
        reason = f"earnings in {days}d (strong penalty)"
    elif days <= settings.PAPER_EARNINGS_MEDIUM_PENALTY_WITHIN_DAYS:
        adj = settings.PAPER_EARNINGS_MEDIUM_PENALTY_POINTS
        reason = f"earnings in {days}d (medium penalty)"
    elif days <= settings.PAPER_EARNINGS_LIGHT_PENALTY_WITHIN_DAYS:
        adj = settings.PAPER_EARNINGS_LIGHT_PENALTY_POINTS
        reason = f"earnings in {days}d (light penalty)"
    else:
        adj = 0
        reason = f"earnings in {days}d (no penalty)"
    base["earnings_score_adjustment"] = adj
    base["earnings_reason"] = reason
    return base
