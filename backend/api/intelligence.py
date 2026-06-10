"""
Intelligence API — read-only data layer, no broker, no live trading, no real orders.
Phase I2: Reddit ranking. Phase I3-A: Pre-market movers.
"""
from fastapi import APIRouter, Depends

from api.dependencies import require_admin_token
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
    # If cache is empty (cold start, no prior fetch), attempt a fresh fetch
    if not snapshot["results"] and snapshot["error"] is None:
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
    result = await reddit_intel.fetch_and_refresh()
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
    Pre-market movers from the marketdata collector cache.

    Reads from Redis market:snapshot:{symbol} keys — no direct Polygon calls.
    TTL: 60s during premarket/regular session, 300s afterhours/closed.
    Refreshes when: no snapshot exists (cold start) OR TTL has expired
    (age_seconds >= ttl_seconds, i.e. ttl_seconds == 0).
    Read-only — not integrated into trading decisions.
    """
    snap = premarket_intel.get_snapshot()
    needs_refresh = (
        not snap["fetched_at"]
        or (snap["ttl_seconds"] is not None and snap["ttl_seconds"] <= 0)
    )
    if needs_refresh:
        snap = await premarket_intel.fetch_and_refresh()
    return snap
