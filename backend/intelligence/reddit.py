"""
ApeWisdom Reddit intelligence — read-only snapshot, no trading integration.

Fetches top-100 tickers by Reddit mentions from ApeWisdom (free, no key required).
Caches in memory + Redis (best-effort). Detects 3x mention spikes vs previous snapshot.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1"
_FETCH_TIMEOUT = 5.0   # seconds — spec requires reasonable timeout
_CACHE_TTL = 900       # 15 minutes — ApeWisdom updates on this cadence
_SPIKE_RATIO = 3.0     # mentions >= 3x previous snapshot → spike
_MAX_RESULTS = 100     # full page 1

# Redis keys
_REDIS_KEY = "intelligence:reddit:latest"
_REDIS_PREV_KEY = "intelligence:reddit:previous"

# ── In-memory state ──────────────────────────────────────────────────────────
_current: list[dict] = []       # latest normalized results
_previous: list[dict] = []      # results from the snapshot before current
_fetched_at: float = 0.0        # epoch seconds of last successful fetch
_fetch_error: str | None = None # last error message; cleared on success

# Async lock: coalesces concurrent cold-start fetches so only one HTTP call goes out
_fetch_lock = asyncio.Lock()

# Background loop handle (started at app lifespan if enabled)
_bg_task: asyncio.Task | None = None


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalize_rows(raw: list[dict]) -> list[dict]:
    """Normalize ApeWisdom API rows to our canonical schema."""
    out: list[dict] = []
    for i, item in enumerate(raw):
        ticker = (item.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        out.append({
            "rank": int(item.get("rank") or (i + 1)),
            "ticker": ticker,
            "name": (item.get("name") or "").strip(),
            "mentions": int(item.get("mentions") or 0),
            "upvotes": int(item.get("upvotes") or 0),
            "rank_24h_ago": item.get("rank_24h_ago") if item.get("rank_24h_ago") else None,
            "mentions_24h_ago": item.get("mentions_24h_ago") if item.get("mentions_24h_ago") else None,
        })
    return out


# ── Spike detection ───────────────────────────────────────────────────────────

def _detect_spikes(current: list[dict], previous: list[dict]) -> list[dict]:
    """
    Return spike events where current mentions >= SPIKE_RATIO * previous mentions.
    Requires a non-empty previous snapshot for comparison.
    """
    if not previous:
        return []
    prev_map: dict[str, int] = {
        r["ticker"]: r["mentions"] for r in previous if r.get("ticker")
    }
    spikes: list[dict] = []
    for row in current:
        ticker = row.get("ticker", "")
        prev_m = prev_map.get(ticker)
        curr_m = row.get("mentions", 0)
        if prev_m and prev_m > 0 and curr_m >= _SPIKE_RATIO * prev_m:
            spikes.append({
                "ticker": ticker,
                "mentions": curr_m,
                "prev_mentions": prev_m,
                "spike_ratio": round(curr_m / prev_m, 2),
            })
    return spikes


# ── Redis helpers (best-effort, never raise) ──────────────────────────────────

async def _redis_save(current: list[dict], previous: list[dict]) -> None:
    try:
        from data.redis_client import make_redis
        r = make_redis()
        async with r:
            await r.setex(_REDIS_KEY, _CACHE_TTL, json.dumps(current))
            if previous:
                await r.setex(_REDIS_PREV_KEY, _CACHE_TTL * 2, json.dumps(previous))
    except Exception as exc:
        logger.debug("Reddit intel: Redis save skipped — %s", exc)


async def _redis_load() -> tuple[list[dict], list[dict]]:
    """Returns (current, previous) from Redis, or ([], []) on any failure."""
    try:
        from data.redis_client import make_redis
        r = make_redis()
        async with r:
            cur_raw = await r.get(_REDIS_KEY)
            prev_raw = await r.get(_REDIS_PREV_KEY)
        cur = json.loads(cur_raw) if cur_raw else []
        prev = json.loads(prev_raw) if prev_raw else []
        return cur, prev
    except Exception as exc:
        logger.debug("Reddit intel: Redis load skipped — %s", exc)
        return [], []


# ── Core fetch ────────────────────────────────────────────────────────────────

async def fetch_and_refresh(force: bool = False) -> dict[str, Any]:
    """
    Fetch a fresh snapshot from ApeWisdom.

    Rate-guard: if the last successful fetch was < _CACHE_TTL seconds ago,
    returns the cached snapshot without making a network call.
    force=True bypasses the TTL guard (used by admin refresh endpoint).
    Lock: concurrent callers coalesce — only one upstream HTTP request runs at a time.
    On failure: logs the error, preserves the existing cache, returns snapshot
    with error field populated. Never raises.
    """
    global _current, _previous, _fetched_at, _fetch_error

    # Fast path: check TTL before acquiring lock (avoids lock contention when warm)
    now = time.time()
    if not force and _fetched_at and (now - _fetched_at) < _CACHE_TTL:
        logger.debug(
            "Reddit intel: cache still fresh (age=%.0fs, ttl=%ds)",
            now - _fetched_at, _CACHE_TTL,
        )
        return get_snapshot()

    # Slow path: acquire lock so concurrent cold-start callers coalesce
    async with _fetch_lock:
        # Re-check TTL inside lock — a concurrent caller may have refreshed while we waited
        now = time.time()
        if not force and _fetched_at and (now - _fetched_at) < _CACHE_TTL:
            return get_snapshot()

        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
                resp = await client.get(_APEWISDOM_URL)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            _fetch_error = str(exc)
            logger.warning("Reddit intel: ApeWisdom fetch failed — %s", exc)
            return get_snapshot(error=str(exc))

        raw = (data.get("results") or [])[:_MAX_RESULTS]
        new_results = _normalize_rows(raw)

        # Rotate snapshots: current becomes previous
        _previous = list(_current)
        _current = new_results
        _fetched_at = time.time()
        _fetch_error = None

        await _redis_save(_current, _previous)
        logger.info("Reddit intel: refreshed — %d tickers, %d spikes",
                    len(_current), len(_detect_spikes(_current, _previous)))
        return get_snapshot()


# ── Snapshot read ─────────────────────────────────────────────────────────────

def get_snapshot(error: str | None = None) -> dict[str, Any]:
    """Return the current in-memory state as an API-ready dict."""
    spikes = _detect_spikes(_current, _previous)
    age = int(time.time() - _fetched_at) if _fetched_at else None
    ttl = max(0, _CACHE_TTL - age) if age is not None else None
    effective_error = error or _fetch_error
    return {
        "ok": effective_error is None and bool(_current),
        "source": "apewisdom",
        "fetched_at": _fetched_at if _fetched_at else None,
        "age_seconds": age,
        "ttl_seconds": ttl,
        "result_count": len(_current),
        "results": _current,
        "spikes": spikes,
        "error": effective_error,
    }


# ── Startup loader ────────────────────────────────────────────────────────────

async def ensure_loaded() -> None:
    """
    Called at app startup: populate cache from Redis if available,
    otherwise fetch fresh. Never raises.
    """
    global _current, _previous, _fetched_at

    if _current:
        return  # already loaded

    # Try Redis first (faster — avoids a cold-start HTTP call)
    cached, prev = await _redis_load()
    if cached:
        _current = cached
        _previous = prev
        # Treat cached data as half-expired so we refresh soon
        _fetched_at = time.time() - (_CACHE_TTL // 2)
        logger.info("Reddit intel: loaded %d tickers from Redis cache", len(_current))
        return

    # No Redis cache — fetch fresh
    await fetch_and_refresh()


# ── Background loop ───────────────────────────────────────────────────────────

async def _background_loop() -> None:
    """Runs every _CACHE_TTL seconds, refreshes the snapshot silently."""
    await asyncio.sleep(90)  # short initial delay so startup settles
    while True:
        try:
            await fetch_and_refresh()
        except Exception as exc:
            logger.warning("Reddit intel background loop error: %s", exc)
        await asyncio.sleep(_CACHE_TTL)


def start_background_loop() -> None:
    """Start the 15-minute background refresh loop. Idempotent — safe to call multiple times."""
    global _bg_task
    if _bg_task is not None and not _bg_task.done():
        return
    try:
        loop = asyncio.get_event_loop()
        _bg_task = loop.create_task(_background_loop())
        logger.info("Reddit intel: background refresh started (interval=%ds)", _CACHE_TTL)
    except RuntimeError as exc:
        logger.warning("Reddit intel: could not start background loop — %s", exc)
