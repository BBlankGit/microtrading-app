"""
Health metrics for the market data collector. Phase D1 / D4.
No broker. No live trading. No real orders. No real-money execution.
"""

from datetime import datetime, timezone
from typing import Any

from core.config import settings


async def get_health() -> dict[str, Any]:
    from data.redis_client import redis_ping_status
    from marketdata import cache, service

    svc = service.get_service_status()
    symbols: list[str] = svc.get("symbols") or settings.marketdata_base_symbols_list()
    universe_info: dict = svc.get("universe_info") or {}

    redis_status = await redis_ping_status()
    redis_ok: bool = redis_status.get("redis_connected", False)

    # Count fresh vs stale from cache
    symbols_fresh = 0
    symbols_stale = 0
    for sym in symbols:
        data = await cache.read_symbol(sym)
        if data and data.get("raw_status") == "ok":
            try:
                fetched = datetime.fromisoformat(
                    data["fetched_at"].replace("Z", "+00:00")
                )
                age = (datetime.now(timezone.utc) - fetched).total_seconds()
                if age <= data.get("ttl_seconds", settings.MARKETDATA_CACHE_TTL_SECONDS):
                    symbols_fresh += 1
                else:
                    symbols_stale += 1
            except Exception:
                symbols_stale += 1
        else:
            symbols_stale += 1

    return {
        "enabled": settings.MARKETDATA_COLLECTOR_ENABLED,
        "running": svc.get("running", False),
        "started_at": svc.get("started_at"),
        "auto_started": svc.get("auto_started", False),
        "source": "polygon",
        # Universe composition (Phase D4)
        "configured_base_symbols_count": len(settings.marketdata_base_symbols_list()),
        "paper_universe_symbols_count": universe_info.get("paper_universe_count", 0),
        "v5_symbols_count": universe_info.get("v5_symbols_count", 0),
        "extra_symbols_count": len(settings.marketdata_extra_symbols_list()),
        "total_collector_symbols": universe_info.get("total_collector_symbols", len(symbols)),
        "skipped_due_to_budget": universe_info.get("skipped_due_to_budget", 0),
        "skipped_by_tier": universe_info.get("skipped_by_tier", {}),
        # Per-symbol freshness
        "symbols_total": len(symbols),
        "symbols_fresh": symbols_fresh,
        "symbols_stale": symbols_stale,
        "last_cycle_at": svc.get("last_cycle_at"),
        "last_success_at": svc.get("last_success_at"),
        "last_error": svc.get("last_error"),
        # requests_last_minute = actual Polygon HTTP attempts (D1 spec field name kept)
        "requests_last_minute": svc.get("polygon_attempts_last_minute", 0),
        "timeouts_last_minute": svc.get("timeouts_last_minute", 0),
        "errors_last_minute": svc.get("errors_last_minute", 0),
        "cache_ttl_seconds": settings.MARKETDATA_CACHE_TTL_SECONDS,
        "redis_connected": redis_ok,
    }
