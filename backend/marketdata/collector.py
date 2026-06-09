"""
Shared market data collector. Phase D1 / D1-H1 / D4.
Polls Polygon REST once per cycle, writes to Redis.
No broker. No live trading. No real orders. No real-money execution.
No AI/LLM/Ollama. Data collection only.

Phase D4: symbol list is rebuilt each cycle from the dynamic universe builder,
merging open positions, paper universe, V5 universe, base, and extra symbols.
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

    Rate-limit design (D1-H1):
      _polygon_attempt_ts counts every actual Polygon HTTP call (including retries).
      Budget is checked before each attempt; retries are skipped if budget is exhausted.
      This ensures MARKETDATA_MAX_REQUESTS_PER_MINUTE limits real Polygon calls, not just cycles.
    """

    def __init__(self, symbols: list[str] | None = None) -> None:
        self._symbols: list[str] = symbols or settings.marketdata_base_symbols_list()
        self._universe_info: dict = {}   # populated each cycle by universe builder (D4)
        self._running: bool = False
        self._last_cycle_at: str | None = None
        self._last_success_at: str | None = None
        self._last_error: str | None = None
        # Sliding-window counters (monotonic timestamps, 60-second window)
        self._cycle_ts: deque[float] = deque()           # one per cycle started
        self._polygon_attempt_ts: deque[float] = deque() # one per actual Polygon HTTP call
        self._retry_ts: deque[float] = deque()           # one per retry (excludes first attempt)
        self._skipped_ts: deque[float] = deque()         # one per cycle skipped due to rate limit
        self._timeout_ts: deque[float] = deque()         # one per timeout error
        self._error_ts: deque[float] = deque()           # one per non-timeout error

    # ── Public interface ──────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        return {
            "running": self._running,
            "symbols": list(self._symbols),
            "universe_info": dict(self._universe_info),
            "last_cycle_at": self._last_cycle_at,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "cycles_last_minute": self._count_recent(self._cycle_ts),
            "polygon_attempts_last_minute": self._count_recent(self._polygon_attempt_ts),
            "retries_last_minute": self._count_recent(self._retry_ts),
            "skipped_due_to_rate_limit_last_minute": self._count_recent(self._skipped_ts),
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

    def _has_budget(self) -> bool:
        """True if at least one Polygon attempt slot remains within the rate limit."""
        return (
            self._count_recent(self._polygon_attempt_ts)
            < settings.MARKETDATA_MAX_REQUESTS_PER_MINUTE
        )

    async def _fetch_with_retry(self) -> list[SymbolPayload]:
        """
        Fetch bulk snapshots with retry.
        Each attempt (including retries) consumes one slot from the rate-limit budget.
        If the budget is exhausted before a retry, the retry is skipped.
        """
        last_exc: Exception | None = None
        for attempt in range(settings.MARKETDATA_RETRY_COUNT + 1):
            if not self._has_budget():
                logger.warning(
                    "rate limit: budget exhausted (%d/%d req/min), "
                    "stopping at attempt %d",
                    self._count_recent(self._polygon_attempt_ts),
                    settings.MARKETDATA_MAX_REQUESTS_PER_MINUTE,
                    attempt + 1,
                )
                if last_exc:
                    self._last_error = (
                        f"budget exhausted after {attempt} attempt(s): {last_exc}"
                    )
                break

            # Consume one budget slot before the actual HTTP call
            self._polygon_attempt_ts.append(time.monotonic())
            if attempt > 0:
                self._retry_ts.append(time.monotonic())
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
        # Gate the entire cycle on having at least one budget slot
        if not self._has_budget():
            self._skipped_ts.append(time.monotonic())
            logger.warning(
                "rate limit reached (%d req/min max), skipping cycle",
                settings.MARKETDATA_MAX_REQUESTS_PER_MINUTE,
            )
            return

        self._cycle_ts.append(time.monotonic())

        # Rebuild symbol universe each cycle (Phase D4)
        from marketdata.universe_builder import build_collector_universe
        symbols, tier_info = build_collector_universe()
        if symbols:
            self._symbols = symbols
        self._universe_info = tier_info

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
