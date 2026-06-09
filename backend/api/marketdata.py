"""
Read-only market data cache endpoints + admin start/stop. Phase D1 / D1-H1.
No broker. No live trading. No real orders. No real-money execution.
"""

import re

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin_token
from core.config import settings

router = APIRouter(prefix="/api/marketdata", tags=["marketdata"])

_DISCLAIMER = (
    "Market data collector — research/observational use only. "
    "No broker. No live trading. No real orders."
)

# Valid: 1-15 chars, uppercase A-Z, digits 0-9, dot, hyphen
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")


# ── Read-only endpoints (no auth required) ────────────────────────────────────

@router.get("/health")
async def marketdata_health():
    from marketdata.health import get_health
    h = await get_health()
    h["disclaimer"] = _DISCLAIMER
    return h


@router.get("/symbol/{symbol}")
async def marketdata_symbol(symbol: str):
    from marketdata import cache
    sym = symbol.upper().strip()
    if not sym or not _SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid symbol '{symbol}'. "
                "Must be 1-15 characters: A-Z, 0-9, dot, or hyphen."
            ),
        )
    data = await cache.read_symbol(sym)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No cached market data for {sym}. "
                "Collector may be stopped or symbol not in watchlist."
            ),
        )
    return data


@router.get("/symbols")
async def marketdata_symbols():
    """Return the list of currently active cached symbols."""
    from marketdata import cache, service
    svc = service.get_service_status()
    configured = settings.marketdata_base_symbols_list()
    cached = await cache.read_active_symbols()
    return {
        "configured": configured,
        "cached": cached,
        "running": svc.get("running", False),
        "disclaimer": _DISCLAIMER,
    }


@router.get("/metrics")
async def marketdata_metrics():
    """Return collector counters and cycle timing (D1-H1: per-attempt breakdown)."""
    from marketdata import cache, service
    svc = service.get_service_status()
    redis_metrics = await cache.read_metrics() or {}
    return {
        "running": svc.get("running", False),
        "last_cycle_at": svc.get("last_cycle_at"),
        "last_success_at": svc.get("last_success_at"),
        "last_error": svc.get("last_error"),
        "cycles_last_minute": svc.get("cycles_last_minute", 0),
        "polygon_attempts_last_minute": svc.get("polygon_attempts_last_minute", 0),
        "retries_last_minute": svc.get("retries_last_minute", 0),
        "skipped_due_to_rate_limit_last_minute": svc.get("skipped_due_to_rate_limit_last_minute", 0),
        "timeouts_last_minute": svc.get("timeouts_last_minute", 0),
        "errors_last_minute": svc.get("errors_last_minute", 0),
        "symbols": svc.get("symbols", []),
        "universe_info": svc.get("universe_info", {}),
        "redis_metrics": redis_metrics,
        "disclaimer": _DISCLAIMER,
    }


# ── Admin endpoints (ADMIN_API_TOKEN required) ────────────────────────────────

@router.post("/start")
async def marketdata_start(_: None = Depends(require_admin_token)):
    """Start the market data collector as a background task."""
    from marketdata import service
    result = await service.start_collector()
    return {**result, "disclaimer": _DISCLAIMER}


@router.post("/stop")
async def marketdata_stop(_: None = Depends(require_admin_token)):
    """Stop the market data collector."""
    from marketdata import service
    result = await service.stop_collector()
    return {**result, "disclaimer": _DISCLAIMER}
