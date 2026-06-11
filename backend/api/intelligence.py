"""
Intelligence API — read-only data layer, no broker, no live trading, no real orders.
Phase I2: Reddit ranking. Phase I3-A: Pre-market movers. Phase I3-B: Full-universe scanner.
Phase I5: News/Earnings/Insiders intelligence feed surface (read-only display).
Phase I5-H1: Cache-first news GET + search/filter/sort + admin-protected refresh.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from api.dependencies import require_admin_token
from catalysts.news_collector import collect_news_for_symbols
from core.config import settings
from data.universe import DEFAULT_UNIVERSE
from intelligence import earnings as earnings_intel
from intelligence import full_premarket as full_premarket_intel
from intelligence import insiders as insiders_intel
from intelligence import premarket as premarket_intel
from intelligence import reddit as reddit_intel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])

# ── Phase I5-H1: News cache (module-level, no external call on every GET) ─────
_news_cache: dict | None = None
_news_cache_time: float | None = None
_news_fetch_lock = asyncio.Lock()
_NEWS_TTL_SECONDS = 300  # 5 minutes


@router.get("/reddit")
async def get_reddit():
    """
    Latest Reddit mention snapshot from ApeWisdom.

    Cached for up to 15 minutes. Read-only — not integrated into trading decisions.
    Returns cached data if available; fetches fresh if cache is empty.
    On ApeWisdom failure, returns the last successful snapshot with error field set.
    """
    snapshot = reddit_intel.get_snapshot()
    ttl = snapshot.get("ttl_seconds")
    needs_refresh = not snapshot["results"] or (ttl is not None and ttl <= 0)
    if needs_refresh and snapshot["error"] is None:
        snapshot = await reddit_intel.fetch_and_refresh()
    return snapshot


@router.post("/reddit/refresh", dependencies=[Depends(require_admin_token)])
async def refresh_reddit():
    """
    Force a fresh ApeWisdom fetch (admin-token protected).

    Still subject to the rate-guard: if the last fetch was < 15 minutes ago
    the cache is returned as-is. Use this to manually warm the cache or
    test connectivity.
    """
    result = await reddit_intel.fetch_and_refresh(force=True)
    return {
        "ok": result["ok"],
        "fetched_at": result["fetched_at"],
        "age_seconds": result["age_seconds"],
        "result_count": result["result_count"],
        "spike_count": len(result.get("spikes") or []),
        "error": result.get("error"),
    }


@router.get("/premarket")
async def get_premarket():
    """
    Pre-market movers — full-universe (~5000+ US stocks) when available,
    active-universe fallback when not.

    Full-universe: scans all CS tickers via Polygon bulk snapshots. TTL 90s.
    Active-universe fallback: reads from Redis market:snapshot:{symbol} keys.
    Read-only — not integrated into trading decisions.
    """
    # ── Full-universe primary path ────────────────────────────────────────────
    if settings.PREMARKET_SCANNER_ENABLED:
        full_snap = full_premarket_intel.get_snapshot()
        if full_snap:
            ttl = full_snap.get("ttl_seconds")
            if ttl is not None and ttl <= 0:
                full_snap = await full_premarket_intel.fetch_and_refresh()
            return full_snap

        # No in-memory snapshot — attempt a fresh scan (first request after cold start)
        full_snap = await full_premarket_intel.fetch_and_refresh()
        if full_snap and full_snap.get("ok"):
            return full_snap

    # ── Active-universe fallback ──────────────────────────────────────────────
    active = premarket_intel.get_snapshot()
    needs_refresh = (
        not active.get("fetched_at")
        or (active.get("ttl_seconds") is not None and active["ttl_seconds"] <= 0)
    )
    if needs_refresh:
        active = await premarket_intel.fetch_and_refresh()

    gainers   = active.get("gainers", [])
    losers    = active.get("losers",  [])
    combined  = sorted(
        gainers + losers,
        key=lambda x: abs(x.get("gap_percent", 0)),
        reverse=True,
    )
    sym_count = active.get("symbol_count", 0)

    return {
        **active,
        "mode":               "active_universe_fallback",
        "source":             "marketdata_cache",
        "universe_count":     sym_count,
        "symbols_requested":  sym_count,
        "symbols_returned":   sym_count,
        "valid_movers_count": len(gainers) + len(losers),
        "skipped_count":      max(0, sym_count - len(gainers) - len(losers)),
        "scan_duration_ms":   None,
        "top_gainers": [
            {**m, "rank": i + 1, "dollar_volume": None} for i, m in enumerate(gainers)
        ],
        "top_losers": [
            {**m, "rank": i + 1, "dollar_volume": None} for i, m in enumerate(losers)
        ],
        "top_movers": [
            {**m, "rank": i + 1, "dollar_volume": None}
            for i, m in enumerate(combined[:100])
        ],
        "warnings": [
            "Full-universe scanner not yet available; showing active universe only."
        ],
    }


@router.post("/premarket/refresh", dependencies=[Depends(require_admin_token)])
async def refresh_premarket(safe: bool = Query(default=False)):
    """
    Force a full-universe premarket scan (admin-token protected).

    Bypasses the normal TTL guard. Subject to a safety cooldown
    (PREMARKET_SCANNER_SAFETY_COOLDOWN_SECONDS) unless ?safe=true is passed.
    Returns a compact summary; fetch /premarket for the full mover list.
    """
    cooldown = settings.PREMARKET_SCANNER_SAFETY_COOLDOWN_SECONDS
    last_at  = full_premarket_intel._last_manual_refresh_at
    now      = time.time()

    if not safe and last_at and (now - last_at) < cooldown:
        remaining = int(cooldown - (now - last_at))
        return {
            "ok":            False,
            "error":         f"Safety cooldown active — {remaining}s remaining. Pass ?safe=true to override.",
            "cooldown_remaining_seconds": remaining,
        }

    full_premarket_intel._last_manual_refresh_at = now
    snap = await full_premarket_intel.fetch_and_refresh(force=True)
    return {
        "ok":                   snap.get("ok"),
        "mode":                 snap.get("mode"),
        "session":              snap.get("session"),
        "universe_count":       snap.get("universe_count"),
        "symbols_returned":     snap.get("symbols_returned"),
        "valid_movers_count":   snap.get("valid_movers_count"),
        "scan_duration_ms":     snap.get("scan_duration_ms"),
        "fetched_at":           snap.get("fetched_at"),
        "age_seconds":          snap.get("age_seconds"),
        "ttl_seconds":          snap.get("ttl_seconds"),
        "error":                snap.get("error"),
        "warnings":             snap.get("warnings", []),
    }


@router.get("/premarket/status")
async def premarket_status():
    """
    Lightweight status for the full-universe premarket scanner.

    Returns configuration, last-scan metadata, and universe size.
    Does not trigger a scan. Does not return mover lists.
    """
    snap          = full_premarket_intel.get_snapshot()
    universe_size = len(full_premarket_intel._universe)
    bg_running    = (
        full_premarket_intel._bg_task is not None
        and not full_premarket_intel._bg_task.done()
    )

    return {
        "scanner_enabled":    settings.PREMARKET_SCANNER_ENABLED,
        "session":            full_premarket_intel.get_current_session(),
        "background_running": bg_running,
        "universe_size":      universe_size,
        "last_scan": {
            "ok":                 snap.get("ok"),
            "mode":               snap.get("mode"),
            "fetched_at":         snap.get("fetched_at"),
            "age_seconds":        snap.get("age_seconds"),
            "ttl_seconds":        snap.get("ttl_seconds"),
            "scan_duration_ms":   snap.get("scan_duration_ms"),
            "universe_count":     snap.get("universe_count"),
            "symbols_returned":   snap.get("symbols_returned"),
            "valid_movers_count": snap.get("valid_movers_count"),
            "error":              snap.get("error"),
        } if snap else None,
        "config": {
            "chunk_size":            settings.PREMARKET_SCANNER_CHUNK_SIZE,
            "max_concurrent_chunks": settings.PREMARKET_SCANNER_MAX_CONCURRENT_CHUNKS,
            "min_price":             settings.PREMARKET_SCANNER_MIN_PRICE,
            "top_n":                 settings.PREMARKET_SCANNER_TOP_N,
            "top_movers_n":          settings.PREMARKET_SCANNER_TOP_MOVERS_N,
            "result_ttl_seconds":    settings.PREMARKET_SCANNER_RESULT_TTL_SECONDS,
            "universe_ttl_seconds":  settings.PREMARKET_SCANNER_UNIVERSE_TTL_SECONDS,
            "interval_premarket_s":  settings.PREMARKET_SCANNER_INTERVAL_PREMARKET_SECONDS,
            "interval_regular_s":    settings.PREMARKET_SCANNER_INTERVAL_REGULAR_SECONDS,
            "max_universe_size":     settings.PREMARKET_SCANNER_MAX_UNIVERSE_SIZE,
        },
    }


# ── Phase I5: News / Earnings / Insiders feeds (read-only display) ────────────


def _cache_age_seconds() -> float | None:
    if _news_cache_time is None:
        return None
    return max(0.0, time.monotonic() - _news_cache_time)


def _cache_is_fresh() -> bool:
    age = _cache_age_seconds()
    return age is not None and age < _NEWS_TTL_SECONDS


def _bucket_impact_level(materiality_score) -> str:
    """
    Deterministic bucketing of the existing materiality_score into a
    human-readable impact level. Does NOT change scoring math — only labels
    the existing value for display.

      materiality >= 0.7  → high
      materiality >= 0.4  → medium
      materiality >  0.0  → low
      materiality == 0    → low
      materiality is None → unknown
    """
    if materiality_score is None:
        return "unknown"
    try:
        m = float(materiality_score)
    except (TypeError, ValueError):
        return "unknown"
    if m >= 0.7:
        return "high"
    if m >= 0.4:
        return "medium"
    return "low"


def _normalize_for_display(it: dict) -> dict:
    """
    Add stable `rule_*` and `ai_*` keys for the dashboard, mapped from the
    existing rule-based fields. The original fields are kept so existing
    sort_by keys (materiality_score / sentiment_score) continue to work.

    No new analysis is performed: rule_impact_level is a deterministic
    bucketing of the existing materiality_score; everything else is a
    rename of the value already produced by catalysts.sentiment /
    catalysts.classify.
    """
    sentiment = it.get("sentiment")
    materiality = it.get("materiality_score")
    classification_method = it.get("classification_method")
    sentiment_method = it.get("sentiment_method")

    it["rule_analysis_available"] = bool(classification_method or sentiment_method)
    it["rule_event_type"] = it.get("classified_event_type") or it.get("event_type")
    it["rule_impact_level"] = _bucket_impact_level(materiality)
    it["rule_sentiment"] = sentiment if sentiment is not None else "unknown"
    it["rule_materiality_score"] = materiality
    it["rule_sentiment_score"] = it.get("sentiment_score")
    it["rule_bullish_flags"] = list(it.get("bullish_flags") or [])
    it["rule_bearish_flags"] = list(it.get("bearish_flags") or [])
    it["rule_reasons"] = list(it.get("sentiment_reasons") or [])
    it["rule_explanation"] = "; ".join(it["rule_reasons"]) if it["rule_reasons"] else None

    # used_by_engine: the engine consumes catalyst rows through
    # catalysts.scoring, not through this display endpoint. We surface a
    # conservative "unknown" rather than overclaim a yes/no per item.
    it["used_by_engine"] = "unknown"

    # AI placeholder fields — stable shape for future comparison work.
    # No AI calls in this phase.
    it["ai_analysis_available"] = False
    it["ai_sentiment"] = None
    it["ai_impact_level"] = None
    it["ai_materiality_score"] = None
    it["ai_confidence"] = None
    it["ai_explanation"] = None
    it["ai_model"] = None
    return it


async def _fetch_news_into_cache(force: bool = False) -> dict:
    """
    Single-flight refresh: only one task touches Polygon at a time.
    Skips fetch if cache is already fresh (unless force=True).
    """
    global _news_cache, _news_cache_time
    async with _news_fetch_lock:
        if not force and _cache_is_fresh():
            return {"refreshed": False, "reason": "cache_fresh"}

        started = time.monotonic()
        raw = await collect_news_for_symbols(
            list(DEFAULT_UNIVERSE),
            limit_per_symbol=20,
            apply_filter=False,
            max_age_hours=72,
            classify_events=True,
            analyze_sentiment=True,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        catalysts = [_normalize_for_display(c) for c in (raw.get("catalysts") or [])]

        _news_cache = {
            "results": catalysts,
            "errors": raw.get("errors", []),
            "symbols_requested": raw.get("symbols_requested", []),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fetch_duration_ms": elapsed_ms,
        }
        _news_cache_time = time.monotonic()
        return {"refreshed": True, "duration_ms": elapsed_ms, "result_count": len(catalysts)}


def _haystack(it: dict) -> str:
    parts = [
        it.get("title") or "",
        it.get("description") or "",
        it.get("source") or "",
        it.get("publisher") or "",
        it.get("event_type") or "",
        it.get("classified_event_type") or "",
        it.get("sentiment") or "",
        it.get("symbol") or "",
        " ".join(it.get("tickers") or []),
        it.get("article_url") or "",
        " ".join(it.get("bullish_flags") or []),
        " ".join(it.get("bearish_flags") or []),
        " ".join(it.get("keywords") or []),
        " ".join(it.get("sentiment_reasons") or []),
    ]
    return " ".join(parts).lower()


_SORT_KEYS = {
    "published_at":     lambda it: it.get("published_utc") or "",
    "fetched_at":       lambda it: it.get("collected_at") or "",
    "ticker":           lambda it: (it.get("symbol") or "").upper(),
    "event_type":       lambda it: (it.get("classified_event_type") or it.get("event_type") or "").lower(),
    "materiality_score": lambda it: it.get("materiality_score") if it.get("materiality_score") is not None else -1,
    "sentiment_score":  lambda it: it.get("sentiment_score") if it.get("sentiment_score") is not None else 0,
}


@router.get("/news")
async def get_intelligence_news(
    q: str | None = Query(default=None, description="Free-text search over title/source/url/event/flags."),
    ticker: str | None = Query(default=None, description="Exact ticker filter (case-insensitive)."),
    symbol: str | None = Query(default=None, description="Alias for ticker."),
    event_type: str | None = Query(default=None, description="Catalyst/event type filter."),
    sentiment: str | None = Query(default=None, description="bullish/bearish/mixed/neutral/unknown."),
    rule_impact_level: str | None = Query(default=None, description="high/medium/low/unknown."),
    min_materiality: float | None = Query(default=None, description="Materiality score floor."),
    sort_by: str = Query(default="published_at"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """
    Cache-first news/catalyst feed for the Intelligence dashboard.

    Reads from a module-level cache (TTL 5 min). Does NOT call Polygon on
    every GET — dashboard auto-refresh polls only the local cache. To force
    a fresh collection, use POST /api/intelligence/news/refresh (admin).

    The cold start (cache empty) triggers one single-flight initial fetch
    so the page is not empty on first load; subsequent requests in the
    same TTL window read the in-memory cache.

    Rule-based — NO AI/LLM. Engine's catalyst scoring uses its own path
    (catalysts.scoring); this endpoint is a display feed only.
    """
    # Cold-start: one initial fetch (single-flight via lock)
    if _news_cache is None:
        try:
            await _fetch_news_into_cache()
        except Exception as exc:
            logger.warning("News cache cold-start fetch failed: %s", exc)

    cache_present = _news_cache is not None
    age = _cache_age_seconds()
    stale = bool(age is not None and age >= _NEWS_TTL_SECONDS)

    if not cache_present:
        return {
            "ok": True,
            "enabled": True,
            "implemented": True,
            "source": "polygon_news + deterministic rule-based classify/sentiment (cache-first)",
            "analysis_mode": "rule-based (no AI/LLM)",
            "fetched_at": None,
            "cache_age_seconds": None,
            "ttl_seconds": _NEWS_TTL_SECONDS,
            "stale": False,
            "total_count": 0,
            "returned_count": 0,
            "limit": limit,
            "offset": offset,
            "filters_applied": {},
            "sort_by": sort_by,
            "sort_dir": sort_dir.lower(),
            "symbols_requested": [],
            "results": [],
            "errors": [],
            "warning": "News cache is empty — POST /api/intelligence/news/refresh to populate.",
            "note": "Cache-first display feed. No external calls per GET.",
        }

    items = list(_news_cache.get("results") or [])
    filters_applied: dict = {}

    tkr_filter = (ticker or symbol or "").strip().upper()
    if tkr_filter:
        def _matches_ticker(it: dict) -> bool:
            if (it.get("symbol") or "").upper() == tkr_filter:
                return True
            tickers = [str(t).upper() for t in (it.get("tickers") or [])]
            return tkr_filter in tickers
        items = [it for it in items if _matches_ticker(it)]
        filters_applied["ticker"] = tkr_filter

    if event_type:
        et = event_type.strip().lower()
        items = [
            it for it in items
            if (it.get("classified_event_type") or it.get("event_type") or "").lower() == et
        ]
        filters_applied["event_type"] = et

    if sentiment:
        s = sentiment.strip().lower()
        items = [it for it in items if (it.get("rule_sentiment") or it.get("sentiment") or "").lower() == s]
        filters_applied["sentiment"] = s

    if rule_impact_level:
        il = rule_impact_level.strip().lower()
        items = [it for it in items if (it.get("rule_impact_level") or "").lower() == il]
        filters_applied["rule_impact_level"] = il

    if min_materiality is not None:
        items = [
            it for it in items
            if (it.get("materiality_score") if it.get("materiality_score") is not None else 0) >= min_materiality
        ]
        filters_applied["min_materiality"] = min_materiality

    if q:
        ql = q.strip().lower()
        items = [it for it in items if ql in _haystack(it)]
        filters_applied["q"] = q

    key_fn = _SORT_KEYS.get(sort_by, _SORT_KEYS["published_at"])
    reverse = (sort_dir or "desc").lower() != "asc"
    try:
        items.sort(key=key_fn, reverse=reverse)
    except TypeError:
        items.sort(key=lambda it: str(key_fn(it)), reverse=reverse)

    total = len(items)
    paged = items[offset:offset + limit]

    return {
        "ok": True,
        "enabled": True,
        "implemented": True,
        "source": "polygon_news + deterministic rule-based classify/sentiment (cache-first)",
        "analysis_mode": "rule-based (no AI/LLM)",
        "fetched_at": _news_cache.get("fetched_at"),
        "cache_age_seconds": int(age) if age is not None else None,
        "ttl_seconds": _NEWS_TTL_SECONDS,
        "stale": stale,
        "total_count": total,
        "returned_count": len(paged),
        "limit": limit,
        "offset": offset,
        "filters_applied": filters_applied,
        "sort_by": sort_by,
        "sort_dir": (sort_dir or "desc").lower(),
        "symbols_requested": _news_cache.get("symbols_requested", []),
        "results": paged,
        "errors": _news_cache.get("errors", []),
        "warning": ("Cache is stale; POST /api/intelligence/news/refresh to update." if stale else None),
        "note": (
            "Used by engine via catalysts.scoring (deterministic rules). "
            "Display feed only — no live orders, no AI/LLM."
        ),
    }


@router.post("/news/refresh", dependencies=[Depends(require_admin_token)])
async def refresh_intelligence_news():
    """
    Admin: force a fresh Polygon news collection and update the news cache.
    Single-flight via lock; concurrent calls coalesce.
    """
    try:
        info = await _fetch_news_into_cache(force=True)
    except Exception as exc:
        logger.warning("News refresh failed: %s", exc)
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "fetched_at": _news_cache.get("fetched_at") if _news_cache else None,
        }
    return {
        "ok": True,
        "refreshed": info.get("refreshed", True),
        "fetched_at": _news_cache.get("fetched_at") if _news_cache else None,
        "total_count": len(_news_cache.get("results", [])) if _news_cache else 0,
        "fetch_duration_ms": info.get("duration_ms"),
    }


_EARNINGS_SORT_KEYS = {
    "report_date": lambda r: r.get("report_date") or "",
    "ticker":      lambda r: (r.get("ticker") or "").upper(),
    "days_until":  lambda r: r.get("days_until") if r.get("days_until") is not None else 10**9,
    "confirmed":   lambda r: str(r.get("confirmed") or ""),
}


@router.get("/earnings")
async def get_intelligence_earnings(
    ticker: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    days_ahead: int = Query(default=30, ge=1, le=365),
    sort_by: str = Query(default="report_date"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """
    Cache-first earnings calendar feed.

    Reads from a module-level cache (TTL settings.EARNINGS_CACHE_TTL_SECONDS,
    default 2h). GET never calls external APIs on every request — only on
    cold start and TTL expiry. Use POST /api/intelligence/earnings/refresh
    (admin) to force a fresh fetch.

    When EARNINGS_DATA_PROVIDER=none (the default), returns enabled=false
    with a clear warning instead of fake rows.
    """
    if earnings_intel.get_snapshot() is None:
        try:
            await earnings_intel.fetch_and_refresh()
        except Exception:
            pass

    snap = earnings_intel.get_snapshot() or {}
    age = earnings_intel.cache_age_seconds()
    # stale=true when: serving preserved cache after failure, OR no usable
    # cache, OR cache age exceeds TTL. Successful + within-TTL → stale=false.
    stale = bool(
        snap.get("serving_stale_cache")
        or (snap and not snap.get("available", False))
        or (age is not None and age >= settings.EARNINGS_CACHE_TTL_SECONDS)
    )

    items = list(snap.get("results") or [])
    filters_applied: dict = {}

    tkr = (ticker or symbol or "").strip().upper()
    if tkr:
        items = [r for r in items if (r.get("ticker") or "").upper() == tkr]
        filters_applied["ticker"] = tkr

    if from_date:
        items = [r for r in items if (r.get("report_date") or "") >= from_date]
        filters_applied["from_date"] = from_date

    if to_date:
        items = [r for r in items if (r.get("report_date") or "") <= to_date]
        filters_applied["to_date"] = to_date

    if days_ahead is not None:
        items = [r for r in items if r.get("days_until") is None or r["days_until"] <= days_ahead]
        filters_applied["days_ahead"] = days_ahead

    key_fn = _EARNINGS_SORT_KEYS.get(sort_by, _EARNINGS_SORT_KEYS["report_date"])
    reverse = (sort_dir or "asc").lower() == "desc"
    try:
        items.sort(key=key_fn, reverse=reverse)
    except TypeError:
        items.sort(key=lambda r: str(key_fn(r)), reverse=reverse)

    total = len(items)
    paged = items[offset:offset + limit]

    return {
        "ok": True,
        "enabled": bool(snap.get("enabled", earnings_intel.is_available())),
        "available": bool(snap.get("available", earnings_intel.is_available())),
        "implemented": True,
        "provider_status": snap.get("provider_status", earnings_intel.provider_status()),
        "source": snap.get("source") or earnings_intel.provider(),
        "fetched_at": snap.get("fetched_at"),
        "cache_age_seconds": int(age) if age is not None else None,
        "ttl_seconds": settings.EARNINGS_CACHE_TTL_SECONDS,
        "stale": stale,
        "total_count": total,
        "returned_count": len(paged),
        "limit": limit,
        "offset": offset,
        "filters_applied": filters_applied,
        "sort_by": sort_by,
        "sort_dir": (sort_dir or "asc").lower(),
        "results": paged,
        "errors": snap.get("errors") or [],
        "warning": snap.get("warning"),
        "last_attempted_at": snap.get("last_attempted_at"),
        "last_successful_fetched_at": snap.get("last_successful_fetched_at"),
        "serving_stale_cache": bool(snap.get("serving_stale_cache", False)),
        "last_refresh_status": snap.get("last_refresh_status"),
        "last_refresh_error": snap.get("last_refresh_error"),
        "note": "Display feed + scoring proximity input. Earnings alone does not create an entry.",
    }


@router.post("/earnings/refresh", dependencies=[Depends(require_admin_token)])
async def refresh_intelligence_earnings():
    """Admin: force a fresh earnings calendar fetch (single-flight)."""
    snap = await earnings_intel.fetch_and_refresh(force=True)
    return {
        "ok": True,
        "enabled": bool(snap.get("enabled", earnings_intel.is_available())),
        "available": bool(snap.get("available", earnings_intel.is_available())),
        "provider_status": snap.get("provider_status", earnings_intel.provider_status()),
        "source": snap.get("source"),
        "fetched_at": snap.get("fetched_at"),
        "total_count": len(snap.get("results") or []),
        "warning": snap.get("warning"),
    }


_INSIDER_SORT_KEYS = {
    "transaction_date": lambda r: r.get("transaction_date") or "",
    "ticker":           lambda r: (r.get("ticker") or "").upper(),
    "value":            lambda r: r.get("value") if r.get("value") is not None else 0.0,
    "transaction_type": lambda r: (r.get("transaction_type") or ""),
}


@router.get("/insiders")
async def get_intelligence_insiders(
    ticker: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    transaction_type: str | None = Query(default=None),
    min_value: float | None = Query(default=None),
    days_back: int = Query(default=30, ge=1, le=365),
    sort_by: str = Query(default="transaction_date"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """
    Cache-first insider transactions feed.

    Returns enabled=false with a clear warning when INSIDER_DATA_PROVIDER
    is unconfigured. Sales/awards/option exercises are surfaced informationally
    and are NOT auto-bearish for scoring purposes.
    """
    if insiders_intel.get_snapshot() is None:
        try:
            await insiders_intel.fetch_and_refresh()
        except Exception:
            pass

    snap = insiders_intel.get_snapshot() or {}
    age = insiders_intel.cache_age_seconds()
    stale = bool(
        snap.get("serving_stale_cache")
        or (snap and not snap.get("available", False))
        or (age is not None and age >= settings.INSIDER_CACHE_TTL_SECONDS)
    )

    items = list(snap.get("results") or [])
    filters_applied: dict = {}

    tkr = (ticker or symbol or "").strip().upper()
    if tkr:
        items = [r for r in items if (r.get("ticker") or "").upper() == tkr]
        filters_applied["ticker"] = tkr

    if transaction_type:
        tt = transaction_type.strip().lower()
        items = [r for r in items if (r.get("transaction_type") or "").lower() == tt]
        filters_applied["transaction_type"] = tt

    if min_value is not None:
        items = [r for r in items if (r.get("value") or 0) >= min_value]
        filters_applied["min_value"] = min_value

    if days_back is not None:
        from datetime import date as _date, timedelta as _td
        cutoff = (_date.today() - _td(days=days_back)).isoformat()
        items = [r for r in items if not r.get("transaction_date") or str(r["transaction_date"])[:10] >= cutoff]
        filters_applied["days_back"] = days_back

    key_fn = _INSIDER_SORT_KEYS.get(sort_by, _INSIDER_SORT_KEYS["transaction_date"])
    reverse = (sort_dir or "desc").lower() != "asc"
    try:
        items.sort(key=key_fn, reverse=reverse)
    except TypeError:
        items.sort(key=lambda r: str(key_fn(r)), reverse=reverse)

    total = len(items)
    paged = items[offset:offset + limit]

    return {
        "ok": True,
        "enabled": bool(snap.get("enabled", insiders_intel.is_available())),
        "available": bool(snap.get("available", insiders_intel.is_available())),
        "implemented": True,
        "provider_status": snap.get("provider_status", insiders_intel.provider_status()),
        "source": snap.get("source") or insiders_intel.provider(),
        "fetched_at": snap.get("fetched_at"),
        "cache_age_seconds": int(age) if age is not None else None,
        "ttl_seconds": settings.INSIDER_CACHE_TTL_SECONDS,
        "stale": stale,
        "total_count": total,
        "returned_count": len(paged),
        "limit": limit,
        "offset": offset,
        "filters_applied": filters_applied,
        "sort_by": sort_by,
        "sort_dir": (sort_dir or "desc").lower(),
        "results": paged,
        "errors": snap.get("errors") or [],
        "warning": snap.get("warning"),
        "last_attempted_at": snap.get("last_attempted_at"),
        "last_successful_fetched_at": snap.get("last_successful_fetched_at"),
        "serving_stale_cache": bool(snap.get("serving_stale_cache", False)),
        "last_refresh_status": snap.get("last_refresh_status"),
        "last_refresh_error": snap.get("last_refresh_error"),
        "note": (
            "Only recent open-market purchases (code P) are treated as bullish. "
            "Sales, awards, tax withholding, and option exercises are cautious / informational."
        ),
    }


@router.post("/insiders/refresh", dependencies=[Depends(require_admin_token)])
async def refresh_intelligence_insiders():
    """Admin: force a fresh insider transactions fetch (single-flight)."""
    snap = await insiders_intel.fetch_and_refresh(force=True)
    return {
        "ok": True,
        "enabled": bool(snap.get("enabled", insiders_intel.is_available())),
        "available": bool(snap.get("available", insiders_intel.is_available())),
        "provider_status": snap.get("provider_status", insiders_intel.provider_status()),
        "source": snap.get("source"),
        "fetched_at": snap.get("fetched_at"),
        "total_count": len(snap.get("results") or []),
        "warning": snap.get("warning"),
    }
