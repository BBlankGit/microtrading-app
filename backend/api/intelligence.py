"""
Intelligence API — read-only data layer, no broker, no live trading, no real orders.
Phase I2: Reddit ranking. Phase I3-A: Pre-market movers. Phase I3-B: Full-universe scanner.
"""
import time

from fastapi import APIRouter, Depends, Query

from api.dependencies import require_admin_token
from core.config import settings
from intelligence import full_premarket as full_premarket_intel
from intelligence import premarket as premarket_intel
from intelligence import reddit as reddit_intel

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


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
