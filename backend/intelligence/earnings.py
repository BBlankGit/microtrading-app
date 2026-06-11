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
from data.universe import DEFAULT_UNIVERSE
from intelligence.finnhub_client import FinnhubError, get as finnhub_get, is_configured as finnhub_configured

logger = logging.getLogger(__name__)

# ── In-memory cache ───────────────────────────────────────────────────────────
_cache: dict | None = None
_cache_time: float | None = None  # monotonic time of most recent successful fetch
_last_attempt_iso: str | None = None       # ISO time of most recent refresh attempt
_last_successful_iso: str | None = None    # ISO time of most recent successful fetch
_last_refresh_status: str = "never"        # "success" | "rate_limited" | "error" | "never"
_last_refresh_error: str | None = None
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


# Providers that have a real fetcher wired in this codebase.
# Phase I6-H2 wires Finnhub.
_WIRED_PROVIDERS: set[str] = {"finnhub"}


def is_available() -> bool:
    """True only when a real fetcher is wired for the configured provider AND the key is present."""
    p = provider()
    if p not in _WIRED_PROVIDERS:
        return False
    if p == "finnhub":
        return finnhub_configured()
    return True


def provider_status() -> str:
    """
    Honest status string for callers/dashboard:
      "not_configured"         — EARNINGS_DATA_PROVIDER=none
      "configured_but_unwired" — provider name set, no fetcher implemented
      "missing_api_key"        — fetcher wired but provider key not configured
      "active"                 — provider has a wired fetcher and key
    """
    p = provider()
    if p in ("", "none"):
        return "not_configured"
    if p not in _WIRED_PROVIDERS:
        return "configured_but_unwired"
    if p == "finnhub" and not finnhub_configured():
        return "missing_api_key"
    return "active"


def is_enabled() -> bool:
    """Backwards-compat alias: enabled iff a real fetcher is available."""
    return is_available()


# ── Symbol universe for earnings refresh (capped, never 5,000) ───────────────

def _tracked_symbols() -> list[str]:
    """
    Controlled universe for earnings refresh.
    Combines DEFAULT_UNIVERSE with the paper base universe, deduped and
    capped at EARNINGS_MAX_SYMBOLS_PER_REFRESH. No 5k-symbol polling.
    """
    seen: set[str] = set()
    out: list[str] = []
    for s in DEFAULT_UNIVERSE:
        u = s.strip().upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    raw = settings.PAPER_BASE_UNIVERSE or ""
    for tok in raw.split(","):
        u = tok.strip().upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    cap = max(1, int(getattr(settings, "EARNINGS_MAX_SYMBOLS_PER_REFRESH", 100)))
    return out[:cap]


# ── Finnhub fetcher ──────────────────────────────────────────────────────────

async def _fetch_finnhub_earnings() -> tuple[list[dict], list[dict], str | None, str]:
    """
    Returns (raw_rows, errors, warning, status_override_or_active).

    Calendar endpoint returns a broad window; we then filter to tracked symbols.
    """
    today = date.today()
    horizon = today + timedelta(days=int(settings.EARNINGS_LOOKAHEAD_DAYS))
    params = {"from": today.isoformat(), "to": horizon.isoformat()}
    try:
        data = await finnhub_get(
            "/calendar/earnings",
            params=params,
            timeout=settings.EARNINGS_FETCH_TIMEOUT_SECONDS,
        )
    except FinnhubError as exc:
        if exc.rate_limited:
            return [], [{"error": "rate_limited"}], "Finnhub rate-limited; serving previous cache if any.", "rate_limited"
        return [], [{"error": str(exc)}], f"Finnhub error: {exc}", "error"

    rows = data.get("earningsCalendar") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], [{"error": "unexpected_payload"}], "Unexpected Finnhub payload shape", "error"

    tracked = set(_tracked_symbols())
    filtered = [r for r in rows if (r.get("symbol") or "").upper() in tracked]
    return filtered, [], None, "active"


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
    raw_time = (raw.get("report_time") or raw.get("hour") or "").lower().strip()
    if raw_time in ("bmo", "before_market", "before market open"):
        report_time = "before_open"
    elif raw_time in ("amc", "after_market", "after market close"):
        report_time = "after_close"
    elif raw_time in ("dmh", "during_market", "during", "dmt"):
        report_time = "during_market"
    elif raw_time in ("", "tbd", "unknown"):
        report_time = "unknown"
    else:
        report_time = raw_time

    try:
        d = date.fromisoformat(str(report_date_s)[:10])
        days_until = (d - today).days
    except Exception:
        d = None
        days_until = None

    confirmed_raw = raw.get("confirmed")
    if confirmed_raw is None:
        confirmed = "unknown"
    else:
        confirmed = confirmed_raw

    return {
        "ticker": ticker,
        "report_date": report_date_s,
        "report_time": report_time,
        "eps_estimate": raw.get("eps_estimate") if raw.get("eps_estimate") is not None else raw.get("epsEstimate"),
        "revenue_estimate": raw.get("revenue_estimate") if raw.get("revenue_estimate") is not None else raw.get("revenueEstimate"),
        "eps_actual": raw.get("eps_actual") if raw.get("eps_actual") is not None else raw.get("epsActual"),
        "revenue_actual": raw.get("revenue_actual") if raw.get("revenue_actual") is not None else raw.get("revenueActual"),
        "surprise": raw.get("surprise"),
        "confirmed": confirmed,
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

        prov = provider()
        status = provider_status()

        if status == "not_configured":
            _cache = {
                "enabled": False,
                "available": False,
                "implemented": True,
                "provider_status": status,
                "source": "none",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "results": [],
                "errors": [],
                "warning": (
                    "Earnings calendar provider is not configured "
                    "(EARNINGS_DATA_PROVIDER=none). No fake data shown. "
                    "Set EARNINGS_DATA_PROVIDER and the matching API key to enable real data."
                ),
            }
            _cache_time = time.monotonic()
            return _cache

        if status == "configured_but_unwired":
            _cache = {
                "enabled": False,
                "available": False,
                "implemented": True,
                "provider_status": status,
                "source": prov,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "results": [],
                "errors": [],
                "warning": (
                    f"Earnings provider {prov!r} is configured but no fetcher is "
                    "implemented yet. No fake data shown."
                ),
            }
            _cache_time = time.monotonic()
            return _cache

        if status == "missing_api_key":
            _cache = {
                "enabled": False,
                "available": False,
                "implemented": True,
                "provider_status": status,
                "source": prov,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "results": [],
                "errors": [],
                "warning": (
                    f"Earnings provider {prov!r} fetcher is wired but FINNHUB_API_KEY "
                    "is not configured. No fake data shown."
                ),
            }
            _cache_time = time.monotonic()
            return _cache

        # status == "active": run the wired fetcher.
        global _last_attempt_iso, _last_successful_iso, _last_refresh_status, _last_refresh_error
        now_iso = datetime.now(timezone.utc).isoformat()
        _last_attempt_iso = now_iso
        try:
            if prov == "finnhub":
                results_raw, errors, warning, eff_status = await _fetch_finnhub_earnings()
            else:
                results_raw, errors, warning, eff_status = [], [], "Unknown provider", "error"

            today = date.today()
            results = [_normalize_row(r, today) for r in results_raw]

            # ── Rate-limit / error path ──────────────────────────────────────
            if eff_status in ("rate_limited", "error"):
                _last_refresh_status = eff_status
                _last_refresh_error = warning or eff_status

                if _cache and _cache.get("results"):
                    # Preserve prior cache rows AND prior cache age — do NOT
                    # reset _cache_time. Otherwise stale rows look fresh.
                    _cache["provider_status"] = eff_status
                    _cache["warning"] = (warning or eff_status) + " Serving previous successful cache."
                    _cache["errors"] = (_cache.get("errors") or []) + errors
                    _cache["last_attempted_at"] = now_iso
                    _cache["last_refresh_status"] = eff_status
                    _cache["last_refresh_error"] = warning or eff_status
                    _cache["serving_stale_cache"] = True
                    # _cache_time intentionally NOT updated.
                    return _cache

                # No prior usable cache: report unavailable, no fake rows.
                _cache = {
                    "enabled": True,
                    "available": False,
                    "implemented": True,
                    "provider_status": eff_status,
                    "source": prov,
                    "fetched_at": None,
                    "results": [],
                    "errors": errors,
                    "warning": warning,
                    "last_attempted_at": now_iso,
                    "last_successful_fetched_at": _last_successful_iso,
                    "serving_stale_cache": False,
                    "last_refresh_status": eff_status,
                    "last_refresh_error": warning or eff_status,
                }
                _cache_time = time.monotonic()
                return _cache

            # ── Success path ────────────────────────────────────────────────
            _last_successful_iso = now_iso
            _last_refresh_status = "success"
            _last_refresh_error = None

            _cache = {
                "enabled": True,
                "available": True,
                "implemented": True,
                "provider_status": eff_status,
                "source": prov,
                "fetched_at": now_iso,
                "results": results,
                "errors": errors,
                "warning": warning,
                "last_attempted_at": now_iso,
                "last_successful_fetched_at": now_iso,
                "serving_stale_cache": False,
                "last_refresh_status": "success",
                "last_refresh_error": None,
            }
            _cache_time = time.monotonic()
            return _cache
        except Exception as exc:
            logger.warning("Earnings fetch failed: %s", type(exc).__name__)
            err_str = f"{type(exc).__name__}: {exc}"
            _last_refresh_status = "error"
            _last_refresh_error = err_str

            if _cache and _cache.get("results"):
                _cache["provider_status"] = "error"
                _cache["errors"] = (_cache.get("errors") or []) + [{"error": err_str}]
                _cache["warning"] = "Last fetch failed; serving previous successful cache."
                _cache["last_attempted_at"] = now_iso
                _cache["last_refresh_status"] = "error"
                _cache["last_refresh_error"] = err_str
                _cache["serving_stale_cache"] = True
                # _cache_time intentionally NOT updated.
                return _cache

            _cache = {
                "enabled": True,
                "available": False,
                "implemented": True,
                "provider_status": "error",
                "source": prov,
                "fetched_at": None,
                "results": [],
                "errors": [{"error": err_str}],
                "warning": "Last fetch failed; no cache available.",
                "last_attempted_at": now_iso,
                "last_successful_fetched_at": _last_successful_iso,
                "serving_stale_cache": False,
                "last_refresh_status": "error",
                "last_refresh_error": err_str,
            }
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
