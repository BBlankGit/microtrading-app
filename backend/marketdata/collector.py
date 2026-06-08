"""
Shared market data collector. Phase D1.
Polls Polygon REST once per cycle, writes to Redis.
No broker. No live trading. No real orders. No real-money execution.
No AI/LLM/Ollama. Data collection only.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone

from core.config import settings
from marketdata import cache, polygon_source
from marketdata.models import SymbolPayload

logger = logging.getLogger(__name__)


class MarketDataCollector:
    """
    Collects market data from Polygon REST and writes to Redis.
    One instance per process. Runs as a background asyncio task.
    """

    def __init__(self, symbols: list[str] | None = None) -> None:
        self._symbols: list[str] = symbols or settings.marketdata_base_symbols_list()
        self._running: bool = False
        self._last_cycle_at: str | None = None
        self._last_success_at: str | None = None
        self._last_error: str | None = None
        # Sliding-window request counters (monotonic timestamps)
        self._request_ts: deque[float] = deque()
        self._timeout_ts: deque[float] = deque()
        self._error_ts: deque[float] = deque()

    # ── Public interface ──────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        return {
            "running": self._running,
            "symbols": list(self._symbols),
            "last_cycle_at": self._last_cycle_at,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "requests_last_minute": self._count_recent(self._request_ts),
            "timeouts_last_minute": self._count_recent(self._timeout_ts),
            "errors_last_minute": self._count_recent(self._error_ts),
        }

    async def run(self) -> None:
        """Main loop. Runs until cancelled."""
        self._running = True
        logger.info("market-data collector started — symbols=%s", self._symbols)
        try:
            while True:
                try:
                    await self._cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    logger.error("collector cycle unhandled error: %s", exc)
                await asyncio.sleep(settings.MARKETDATA_BULK_SNAPSHOT_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            logger.info("market-data collector stopped")

    # ── Internals ─────────────────────────────────────────────────────────────

    def _count_recent(self, dq: deque, window: float = 60.0) -> int:
        """Sliding-window count; evicts entries older than window seconds."""
        now = time.monotonic()
        while dq and now - dq[0] > window:
            dq.popleft()
        return len(dq)

    def _can_request(self) -> bool:
        return self._count_recent(self._request_ts) < settings.MARKETDATA_MAX_REQUESTS_PER_MINUTE

    def _record_request(self) -> None:
        self._request_ts.append(time.monotonic())

    async def _fetch_with_retry(self) -> list[SymbolPayload]:
        last_exc: Exception | None = None
        for attempt in range(settings.MARKETDATA_RETRY_COUNT + 1):
            if attempt > 0:
                await asyncio.sleep(settings.MARKETDATA_RETRY_BACKOFF_SECONDS)
            try:
                return await polygon_source.fetch_bulk_snapshots(
                    self._symbols,
                    settings.MARKETDATA_CACHE_TTL_SECONDS,
                )
            except Exception as exc:
                msg = str(exc).lower()
                if "timed out" in msg or "timeout" in msg:
                    self._timeout_ts.append(time.monotonic())
                else:
                    self._error_ts.append(time.monotonic())
                last_exc = exc
                logger.debug("fetch attempt %d failed: %s", attempt + 1, exc)
        if last_exc:
            self._last_error = str(last_exc)
        return []

    async def _cycle(self) -> None:
        if not self._can_request():
            logger.warning(
                "rate limit reached (%d req/min max), skipping cycle",
                settings.MARKETDATA_MAX_REQUESTS_PER_MINUTE,
            )
            return

        self._record_request()
        payloads = await self._fetch_with_retry()
        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_cycle_at = now_iso

        if payloads:
            payload_dicts = [p.to_dict() for p in payloads]
            await cache.write_cycle_results(
                payload_dicts,
                self.get_metrics(),
                settings.MARKETDATA_CACHE_TTL_SECONDS,
            )
            self._last_success_at = now_iso
            self._last_error = None
        else:
            # Still write metrics so health endpoint reflects the failure
            await cache.write_cycle_results(
                [],
                self.get_metrics(),
                settings.MARKETDATA_CACHE_TTL_SECONDS,
            )
