"""
Singleton lifecycle manager for the market data collector. Phase D1 / D4-H1.
No broker. No live trading. No real orders. No real-money execution.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_collector = None                        # MarketDataCollector instance
_task: asyncio.Task | None = None
_started_at: datetime | None = None     # wall-clock time of most recent start
_auto_started: bool = False              # True when started by lifespan, False when started via API


async def start_collector(
    symbols: list[str] | None = None,
    auto_started: bool = False,
) -> dict[str, Any]:
    global _collector, _task, _started_at, _auto_started
    if _task and not _task.done():
        return {"started": False, "reason": "already running"}
    from marketdata.collector import MarketDataCollector
    _collector = MarketDataCollector(symbols=symbols)
    _task = asyncio.create_task(_collector.run(), name="marketdata-collector")
    _started_at = datetime.now(timezone.utc)
    _auto_started = auto_started
    logger.info(
        "market-data collector task created (auto_started=%s)", auto_started
    )
    return {"started": True, "symbols": _collector._symbols}


async def stop_collector() -> dict[str, Any]:
    global _task, _started_at, _auto_started
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    _started_at = None
    _auto_started = False
    logger.info("market-data collector task stopped")
    return {"stopped": True}


def is_running() -> bool:
    return bool(_task and not _task.done())


def get_service_status() -> dict[str, Any]:
    from core.config import settings
    running = is_running()
    base: dict[str, Any] = {
        "started_at": _started_at.isoformat() if _started_at else None,
        "auto_started": _auto_started,
    }
    if _collector is not None:
        return {"running": running, **base, **_collector.get_metrics()}
    return {
        "running": running,
        **base,
        "symbols": settings.marketdata_base_symbols_list(),
        "last_cycle_at": None,
        "last_success_at": None,
        "last_error": None,
        "cycles_last_minute": 0,
        "polygon_attempts_last_minute": 0,
        "retries_last_minute": 0,
        "skipped_due_to_rate_limit_last_minute": 0,
        "timeouts_last_minute": 0,
        "errors_last_minute": 0,
    }
