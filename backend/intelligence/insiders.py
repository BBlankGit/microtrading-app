"""
Insider transactions intelligence — read-only feed and scoring input.

No broker. No live trading. No real orders. No AI/LLM calls.
Fake-money simulation only. All scoring is deterministic rule-based.

Data source is gated by `INSIDER_DATA_PROVIDER`:
  - "none"     → enabled=false; honest "not configured" payload, no fake data.
  - "polygon"  → wired but Polygon REST has no clean SEC Form 4 endpoint
                 in the basic plan; treated as enabled=false until a real
                 provider is hooked up.
  - "finnhub"  → reserved for a future FINNHUB_API_KEY configuration.

Scoring contributes 0 when no per-symbol data exists, so the integration is
safe to ship even before a provider is configured.

Rules:
  - Only recent open-market purchases (Form 4 code P) are treated as bullish.
  - Sales (S), option exercises (M), awards (A), tax withholdings (F),
    gifts (G), other (X) are NOT auto-bearish by default.
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
_last_attempt_iso: str | None = None
_last_successful_iso: str | None = None
_last_refresh_status: str = "never"
_last_refresh_error: str | None = None
_fetch_lock = asyncio.Lock()


def cache_age_seconds() -> float | None:
    if _cache_time is None:
        return None
    return max(0.0, time.monotonic() - _cache_time)


def cache_is_fresh() -> bool:
    age = cache_age_seconds()
    return age is not None and age < settings.INSIDER_CACHE_TTL_SECONDS


def provider() -> str:
    return (settings.INSIDER_DATA_PROVIDER or "none").strip().lower()


# Providers that have a real fetcher wired in this codebase.
# Phase I6-H2 wires Finnhub.
_WIRED_PROVIDERS: set[str] = {"finnhub"}


def is_available() -> bool:
    p = provider()
    if p not in _WIRED_PROVIDERS:
        return False
    if p == "finnhub":
        return finnhub_configured()
    return True


def provider_status() -> str:
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


# ── Symbol universe for insider refresh (strictly capped) ────────────────────

def _tracked_symbols() -> list[str]:
    """
    Controlled universe for insider refresh. Combines DEFAULT_UNIVERSE with the
    paper base universe; dedupes; caps at INSIDER_MAX_SYMBOLS_PER_REFRESH.
    Never 5,000 symbols.
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
    cap = max(1, int(getattr(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 50)))
    return out[:cap]


# ── Finnhub fetcher: per-symbol calls with delay ─────────────────────────────

async def _fetch_finnhub_insiders() -> tuple[list[dict], list[dict], str | None, str]:
    """
    Returns (raw_rows, errors, warning, effective_status).

    Calls /stock/insider-transactions per symbol with a small delay between
    calls. Stops early on the first rate-limit response and keeps whatever
    rows were collected (caller will preserve prior cache).
    """
    symbols = _tracked_symbols()
    today = date.today()
    cutoff = today - timedelta(days=int(settings.PAPER_INSIDER_LOOKBACK_DAYS) + 7)
    delay = max(0.0, float(settings.INSIDER_FETCH_INTERSYMBOL_DELAY_SECONDS))
    timeout = float(settings.INSIDER_FETCH_TIMEOUT_SECONDS)

    rows: list[dict] = []
    errors: list[dict] = []
    warning: str | None = None
    status_override: str | None = None

    for i, sym in enumerate(symbols):
        try:
            data = await finnhub_get(
                "/stock/insider-transactions",
                params={"symbol": sym, "from": cutoff.isoformat(), "to": today.isoformat()},
                timeout=timeout,
            )
        except FinnhubError as exc:
            if exc.rate_limited:
                warning = f"Finnhub rate-limited after {i} of {len(symbols)} symbols; partial data."
                status_override = "rate_limited"
                break
            errors.append({"symbol": sym, "error": str(exc)})
            continue

        items = data.get("data") if isinstance(data, dict) else None
        if isinstance(items, list):
            for it in items:
                # Inject symbol since Finnhub omits it when queried by symbol.
                if "symbol" not in it and "ticker" not in it:
                    it["symbol"] = sym
                rows.append(it)

        if delay and i + 1 < len(symbols):
            await asyncio.sleep(delay)

    if status_override is None and not rows and errors:
        status_override = "error"
        warning = "All Finnhub insider calls failed; serving previous cache if any."

    return rows, errors, warning, (status_override or "active")


_BUY_CODES = {"P"}
_OPTION_CODES = {"M"}
_SALE_CODES = {"S"}
_AWARD_CODES = {"A"}
_TAX_CODES = {"F"}
_GIFT_CODES = {"G"}
_DISPOSITION_CODES = {"D"}
_EXERCISE_AND_SALE_CODES = {"X"}


def _normalize_code(code: str | None) -> tuple[str, str]:
    """
    Return (transaction_type, buy_sell_label) for a Form 4 transaction code.
    """
    c = (code or "").strip().upper()
    if c in _BUY_CODES:
        return "open_market_purchase", "bullish_buy"
    if c in _OPTION_CODES:
        return "option_exercise", "informational_buy"
    if c in _SALE_CODES:
        return "sale", "sale"
    if c in _AWARD_CODES:
        return "stock_award", "neutral_compensation"
    if c in _TAX_CODES:
        return "tax_withholding", "neutral_compensation"
    if c in _GIFT_CODES:
        return "gift", "neutral_compensation"
    if c in _DISPOSITION_CODES:
        return "disposition", "sale"
    if c in _EXERCISE_AND_SALE_CODES:
        return "exercise_and_sale", "sale"
    return "other", "unknown"


def _normalize_row(raw: dict, today: date) -> dict:
    ticker = (raw.get("symbol") or raw.get("ticker") or "").upper()
    code = (raw.get("transaction_code") or raw.get("transactionCode") or raw.get("transactionType") or raw.get("transactionTypeCode") or raw.get("code") or "").upper().strip()
    # Finnhub sometimes returns multi-letter codes like "P-Purchase"; take first letter.
    if len(code) > 1 and code[1] in ("-", " "):
        code = code[0]
    tx_type, label = _normalize_code(code)
    txn_date_s = (
        raw.get("transaction_date")
        or raw.get("transactionDate")
        or raw.get("filingDate")
        or raw.get("date")
    )
    try:
        d = date.fromisoformat(str(txn_date_s)[:10])
        days_back = (today - d).days
    except Exception:
        d = None
        days_back = None

    shares = raw.get("shares")
    if shares is None:
        shares = raw.get("share") or raw.get("transactionShares") or raw.get("change")
    price = raw.get("price") or raw.get("transactionPrice")
    value = raw.get("value") or raw.get("transactionValue")
    if value is None and shares is not None and price is not None:
        try:
            value = float(shares) * float(price)
        except Exception:
            value = None

    # Heuristic value-sanity warning surfaced for the dashboard.
    sanity_warning: str | None = None
    try:
        if (shares is not None and float(shares) == 0) and (price is not None and float(price) == 0):
            sanity_warning = "zero shares and price"
        elif value is not None and abs(float(value)) > 1e10:
            sanity_warning = "suspiciously large value"
    except Exception:
        pass

    is_recent = days_back is not None and days_back <= settings.PAPER_INSIDER_LOOKBACK_DAYS
    # Discretionary = code P with no plan flag; open-market purchases are
    # the only category we treat as discretionary by default.
    is_discretionary_buy = code == "P"

    return {
        "ticker": ticker,
        "transaction_date": txn_date_s,
        "insider_name": raw.get("insider_name") or raw.get("name"),
        "insider_title": raw.get("insider_title") or raw.get("title") or raw.get("position"),
        "transaction_code": code or None,
        "transaction_type": tx_type,
        "buy_sell_label": label,
        "shares": shares,
        "price": price,
        "value": value,
        "is_discretionary_buy": is_discretionary_buy,
        "is_recent": is_recent,
        "source": raw.get("source") or provider(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "warning": sanity_warning,
    }


async def fetch_and_refresh(force: bool = False) -> dict:
    """Single-flight refresh. Returns the cache dict. Never raises."""
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
                    "Insider transactions provider is not configured "
                    "(INSIDER_DATA_PROVIDER=none). No fake data shown. "
                    "Set INSIDER_DATA_PROVIDER and the matching API key to enable real data."
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
                    f"Insider provider {prov!r} is configured but no fetcher is "
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
                    f"Insider provider {prov!r} fetcher is wired but FINNHUB_API_KEY "
                    "is not configured. No fake data shown."
                ),
            }
            _cache_time = time.monotonic()
            return _cache

        # status == "active": run wired fetcher
        global _last_attempt_iso, _last_successful_iso, _last_refresh_status, _last_refresh_error
        now_iso = datetime.now(timezone.utc).isoformat()
        _last_attempt_iso = now_iso
        try:
            if prov == "finnhub":
                results_raw, errors, warning, eff_status = await _fetch_finnhub_insiders()
            else:
                results_raw, errors, warning, eff_status = [], [], "Unknown provider", "error"

            today = date.today()
            results = [_normalize_row(r, today) for r in results_raw]

            # ── Rate-limit / error path ──────────────────────────────────────
            if eff_status in ("rate_limited", "error"):
                _last_refresh_status = eff_status
                _last_refresh_error = warning or eff_status

                if _cache and _cache.get("results"):
                    # Preserve prior cache rows AND prior cache age.
                    _cache["provider_status"] = eff_status
                    _cache["warning"] = (warning or eff_status) + " Serving previous successful cache."
                    _cache["errors"] = (_cache.get("errors") or []) + errors
                    _cache["last_attempted_at"] = now_iso
                    _cache["last_refresh_status"] = eff_status
                    _cache["last_refresh_error"] = warning or eff_status
                    _cache["serving_stale_cache"] = True
                    # _cache_time intentionally NOT updated.
                    return _cache

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
            logger.warning("Insider fetch failed: %s", type(exc).__name__)
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
    return _cache


def get_results_grouped_by_symbol() -> dict[str, list[dict]]:
    """Return cached results indexed by ticker for the scoring path."""
    if not _cache:
        return {}
    out: dict[str, list[dict]] = {}
    for r in _cache.get("results") or []:
        sym = (r.get("ticker") or "").upper()
        if not sym:
            continue
        out.setdefault(sym, []).append(r)
    return out


def score_insiders(symbol: str, transactions_by_symbol: dict[str, list[dict]]) -> dict:
    """
    Compute deterministic insider adjustment for one symbol.

    Returns a transparent dict:
      {
        "enabled": bool,
        "insider_recent_buy_count": int,
        "insider_recent_buy_value": float,
        "insider_score_adjustment": int,
        "insider_reason": str,
        "insider_latest_transaction_date": str | None,
        "insider_transaction_codes": list[str],
      }
    """
    base = {
        "enabled": settings.PAPER_INSIDER_SCORING_ENABLED,
        "insider_recent_buy_count": 0,
        "insider_recent_buy_value": 0.0,
        "insider_score_adjustment": 0,
        "insider_reason": "no insider data",
        "insider_latest_transaction_date": None,
        "insider_transaction_codes": [],
    }
    if not settings.PAPER_INSIDER_SCORING_ENABLED:
        base["insider_reason"] = "insider scoring disabled"
        return base
    txns = transactions_by_symbol.get(symbol.upper()) or []
    if not txns:
        return base

    codes: list[str] = []
    latest: str | None = None
    for tx in txns:
        c = tx.get("transaction_code")
        if c:
            codes.append(c)
        d = tx.get("transaction_date")
        if d and (latest is None or str(d) > str(latest)):
            latest = str(d)
    base["insider_transaction_codes"] = sorted(set(codes))
    base["insider_latest_transaction_date"] = latest

    # Only recent open-market purchases boost. Optional sales penalty is
    # additive and configurable (default 0 = informational only).
    recent_buys = [
        tx for tx in txns
        if tx.get("is_recent")
        and tx.get("transaction_type") == "open_market_purchase"
        and (not settings.PAPER_INSIDER_IGNORE_NON_DISCRETIONARY or tx.get("is_discretionary_buy"))
    ]
    total_buy_value = 0.0
    for tx in recent_buys:
        v = tx.get("value") or 0.0
        try:
            total_buy_value += float(v)
        except Exception:
            pass

    base["insider_recent_buy_count"] = len(recent_buys)
    base["insider_recent_buy_value"] = round(total_buy_value, 2)

    adj = 0
    reason_parts: list[str] = []
    if recent_buys and total_buy_value >= settings.PAPER_INSIDER_STRONG_BUY_VALUE:
        adj += settings.PAPER_INSIDER_STRONG_BUY_BOOST_POINTS
        reason_parts.append(f"strong recent insider buy ${total_buy_value:,.0f}")
    elif recent_buys and total_buy_value >= settings.PAPER_INSIDER_MIN_BUY_VALUE:
        adj += settings.PAPER_INSIDER_BUY_BOOST_POINTS
        reason_parts.append(f"recent insider buy ${total_buy_value:,.0f}")
    elif recent_buys:
        reason_parts.append(
            f"insider buy below threshold ${total_buy_value:,.0f} < "
            f"${settings.PAPER_INSIDER_MIN_BUY_VALUE:,.0f}"
        )

    # Optional sales penalty
    if settings.PAPER_INSIDER_SELL_PENALTY_POINTS:
        recent_sales = [
            tx for tx in txns
            if tx.get("is_recent") and tx.get("transaction_type") == "sale"
        ]
        if recent_sales:
            adj += settings.PAPER_INSIDER_SELL_PENALTY_POINTS  # config can make this negative
            reason_parts.append(f"recent insider sale(s) ×{len(recent_sales)}")

    base["insider_score_adjustment"] = adj
    base["insider_reason"] = "; ".join(reason_parts) if reason_parts else "no qualifying insider activity"
    return base
