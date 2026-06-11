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
from datetime import datetime, date, timezone
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
    return age is not None and age < settings.INSIDER_CACHE_TTL_SECONDS


def provider() -> str:
    return (settings.INSIDER_DATA_PROVIDER or "none").strip().lower()


def is_enabled() -> bool:
    return provider() not in ("", "none")


_BUY_CODES = {"P"}
_OPTION_CODES = {"M"}
_SALE_CODES = {"S"}
_AWARD_CODES = {"A"}
_TAX_CODES = {"F"}
_GIFT_CODES = {"G"}


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
    return "other", "unknown"


def _normalize_row(raw: dict, today: date) -> dict:
    ticker = (raw.get("symbol") or raw.get("ticker") or "").upper()
    code = (raw.get("transaction_code") or raw.get("transactionCode") or "").upper()
    tx_type, label = _normalize_code(code)
    txn_date_s = raw.get("transaction_date") or raw.get("transactionDate") or raw.get("date")
    try:
        d = date.fromisoformat(str(txn_date_s)[:10])
        days_back = (today - d).days
    except Exception:
        d = None
        days_back = None

    shares = raw.get("shares") or raw.get("share")
    price = raw.get("price")
    value = raw.get("value")
    if value is None and shares is not None and price is not None:
        try:
            value = float(shares) * float(price)
        except Exception:
            value = None

    is_recent = days_back is not None and days_back <= settings.PAPER_INSIDER_LOOKBACK_DAYS
    # Discretionary = code P with no plan flag; open-market purchases are
    # the only category we treat as discretionary by default.
    is_discretionary_buy = code == "P"

    return {
        "ticker": ticker,
        "transaction_date": txn_date_s,
        "insider_name": raw.get("insider_name") or raw.get("name"),
        "insider_title": raw.get("insider_title") or raw.get("title"),
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
        "warning": None,
    }


async def fetch_and_refresh(force: bool = False) -> dict:
    """Single-flight refresh. Returns the cache dict. Never raises."""
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
                    "Insider transactions provider not configured "
                    "(INSIDER_DATA_PROVIDER=none). Set INSIDER_DATA_PROVIDER "
                    "and the matching API key to enable real data."
                ),
            }
            _cache_time = time.monotonic()
            return _cache

        try:
            results_raw: list[dict] = []
            errors: list[dict] = []
            warning: str | None = None
            prov = provider()
            if prov == "polygon":
                warning = (
                    "Polygon REST has no clean SEC Form 4 endpoint on the basic "
                    "plan; leaving cache empty until a dedicated insider feed is wired."
                )
            elif prov == "finnhub":
                warning = (
                    "Finnhub insider provider stub not yet wired. "
                    "Set FINNHUB_API_KEY and implement the fetcher to enable."
                )
            else:
                warning = f"Unknown INSIDER_DATA_PROVIDER={prov!r}; no data fetched."

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
            logger.warning("Insider fetch failed: %s", exc)
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
