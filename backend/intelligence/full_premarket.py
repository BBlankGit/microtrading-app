"""
Full-universe pre-market scanner — read-only intelligence.

Architecture:
- Universe: /v3/reference/tickers (CS-only, daily Redis cache, ~5000–8000 symbols)
- Scan: /v2/snapshot/locale/us/markets/stocks/tickers bulk endpoint, chunked into
  PREMARKET_SCANNER_CHUNK_SIZE symbols per request, up to
  PREMARKET_SCANNER_MAX_CONCURRENT_CHUNKS concurrent requests.
- No per-ticker REST calls. No per-symbol Polygon endpoint.
- No broker. No live trading. No real orders. No real-money execution.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# ── Redis keys ────────────────────────────────────────────────────────────────
_REDIS_UNIVERSE_KEY = "intelligence:premarket:universe"
_REDIS_RESULT_KEY  = "intelligence:premarket:full_universe"

# ── In-memory state ───────────────────────────────────────────────────────────
_snapshot: dict[str, Any] = {}
_fetched_at: float = 0.0
_fetch_lock = asyncio.Lock()

_universe: list[str] = []
_universe_fetched_at: float = 0.0

_last_manual_refresh_at: float = 0.0

_bg_task: asyncio.Task | None = None

# ── Fallback universe (used when Polygon reference fails) ─────────────────────
def _fallback_universe() -> list[str]:
    """Return the paper base universe + V5 symbols as a small fallback."""
    base = settings.paper_base_universe_list()
    v5   = settings.marketdata_v5_symbols_list()
    seen: set[str] = set()
    out: list[str] = []
    for sym in base + v5:
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


# ── Session detection (mirrors intelligence/premarket.py) ─────────────────────

def get_current_session() -> str:
    """Return 'premarket' | 'regular' | 'afterhours' | 'closed'."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now(timezone(timedelta(hours=-4)))

    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if dtime(4, 0) <= t < dtime(9, 30):
        return "premarket"
    if dtime(9, 30) <= t < dtime(16, 0):
        return "regular"
    if dtime(16, 0) <= t < dtime(20, 0):
        return "afterhours"
    return "closed"


# ── Safe numeric coercion ─────────────────────────────────────────────────────

def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ── Raw Polygon bulk-entry → mover ────────────────────────────────────────────

def _entry_to_mover(entry: dict) -> dict | None:
    """
    Convert a raw Polygon bulk-snapshot ticker entry to a mover dict.
    Returns None to skip (bad data, price < MIN_PRICE). Never raises.
    """
    try:
        symbol = (entry.get("ticker") or "").upper()
        if not symbol:
            return None

        last_trade = entry.get("lastTrade") or {}
        prev_day   = entry.get("prevDay")   or {}
        day        = entry.get("day")       or {}

        last_price       = _safe_float(last_trade.get("p"))
        prev_close       = _safe_float(prev_day.get("c"))
        day_volume_raw   = _safe_float(day.get("v"))
        raw_change_pct   = _safe_float(entry.get("todaysChangePerc"))

        min_price = settings.PREMARKET_SCANNER_MIN_PRICE
        if last_price is None or last_price <= 0 or last_price < min_price:
            return None
        if prev_close is None or prev_close <= 0:
            return None
        if raw_change_pct is None:
            return None

        gap_percent  = ((last_price - prev_close) / prev_close) * 100
        day_volume   = int(day_volume_raw) if day_volume_raw is not None else None
        dollar_volume = round(last_price * day_volume_raw, 2) if day_volume_raw else None
        prev_day_volume_raw = _safe_float(prev_day.get("v"))
        prev_day_volume = int(prev_day_volume_raw) if prev_day_volume_raw is not None else None

        return {
            "symbol":              symbol,
            "last_price":          round(last_price, 4),
            "previous_close":      round(prev_close, 4),
            "gap_percent":         round(gap_percent, 4),
            "raw_change_percent":  round(raw_change_pct, 4),
            "day_volume":          day_volume,
            "dollar_volume":       dollar_volume,
            "previous_day_volume": prev_day_volume,
            "source":              "polygon_bulk_snapshot",
        }
    except Exception:
        return None


# ── Universe management ───────────────────────────────────────────────────────

async def _redis_save_universe(symbols: list[str]) -> None:
    try:
        from data.redis_client import make_redis
        r = make_redis()
        async with r:
            await r.set(
                _REDIS_UNIVERSE_KEY,
                json.dumps(symbols),
                ex=settings.PREMARKET_SCANNER_UNIVERSE_TTL_SECONDS,
            )
    except Exception as exc:
        logger.debug("Universe Redis save failed: %s", exc)


async def _redis_load_universe() -> list[str]:
    try:
        from data.redis_client import make_redis
        r = make_redis()
        async with r:
            raw = await r.get(_REDIS_UNIVERSE_KEY)
        return json.loads(raw) if raw else []
    except Exception as exc:
        logger.debug("Universe Redis load failed: %s", exc)
        return []


async def refresh_universe() -> list[str]:
    """
    Fetch fresh US common-stock universe from Polygon reference tickers.
    Caches in Redis and in-memory. Falls back to base universe on failure.
    """
    global _universe, _universe_fetched_at
    try:
        from data.polygon_client import get_reference_tickers
        symbols = await get_reference_tickers(
            ticker_type="CS",
            max_results=settings.PREMARKET_SCANNER_MAX_UNIVERSE_SIZE,
            timeout=30.0,
        )
        if symbols:
            _universe = symbols
            _universe_fetched_at = time.time()
            await _redis_save_universe(symbols)
            logger.info("Full-universe: refreshed %d CS symbols from Polygon", len(symbols))
            return _universe
    except Exception as exc:
        logger.warning("Universe refresh failed: %s", exc)

    if not _universe:
        _universe = _fallback_universe()
        _universe_fetched_at = time.time()
        logger.info("Full-universe: using fallback universe (%d symbols)", len(_universe))
    return _universe


async def get_universe() -> list[str]:
    """Return cached universe (in-memory → Redis → Polygon refresh)."""
    global _universe, _universe_fetched_at

    ttl = settings.PREMARKET_SCANNER_UNIVERSE_TTL_SECONDS
    if _universe and (time.time() - _universe_fetched_at) < ttl:
        return _universe

    cached = await _redis_load_universe()
    if cached:
        _universe = cached
        _universe_fetched_at = time.time()
        logger.debug("Full-universe: loaded %d symbols from Redis", len(_universe))
        return _universe

    return await refresh_universe()


# ── Core scan ─────────────────────────────────────────────────────────────────

async def _scan_universe(symbols: list[str], session: str) -> dict[str, Any]:
    """
    Fetch bulk snapshots for universe, compute movers.
    Chunks symbols into PREMARKET_SCANNER_CHUNK_SIZE batches and fetches in
    parallel with max PREMARKET_SCANNER_MAX_CONCURRENT_CHUNKS concurrency.
    No per-ticker REST calls.
    """
    from data.polygon_client import get_bulk_ticker_snapshots

    t_start = time.time()
    chunk_size   = settings.PREMARKET_SCANNER_CHUNK_SIZE
    max_conc     = settings.PREMARKET_SCANNER_MAX_CONCURRENT_CHUNKS
    req_timeout  = settings.PREMARKET_SCANNER_REQUEST_TIMEOUT_SECONDS
    top_n        = settings.PREMARKET_SCANNER_TOP_N
    top_movers_n = settings.PREMARKET_SCANNER_TOP_MOVERS_N

    chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]
    sem = asyncio.Semaphore(max_conc)
    warnings: list[str] = []

    async def _fetch_chunk(chunk: list[str]) -> list[dict]:
        async with sem:
            try:
                return await get_bulk_ticker_snapshots(chunk, timeout=req_timeout)
            except Exception as exc:
                warnings.append(f"chunk({len(chunk)}) failed: {exc!s:.80}")
                return []

    raw_batches  = await asyncio.gather(*[_fetch_chunk(c) for c in chunks])
    all_entries  = [e for batch in raw_batches for e in batch]

    movers: list[dict] = []
    skipped = 0
    for entry in all_entries:
        mover = _entry_to_mover(entry)
        if mover:
            movers.append(mover)
        else:
            skipped += 1

    movers.sort(key=lambda x: abs(x["gap_percent"]), reverse=True)

    gainers = [m for m in movers if m["gap_percent"] > 0]
    losers  = [m for m in movers if m["gap_percent"] < 0]

    top_gainers = gainers[:top_n]
    for i, m in enumerate(top_gainers):
        m["rank"] = i + 1

    top_losers = losers[:top_n]
    for i, m in enumerate(top_losers):
        m["rank"] = i + 1

    top_movers = movers[:top_movers_n]
    for i, m in enumerate(top_movers):
        m["rank"] = i + 1

    scan_duration_ms = int((time.time() - t_start) * 1000)

    if warnings:
        logger.warning("Full-universe scan warnings: %s", "; ".join(warnings))

    logger.info(
        "Full-universe scan complete: %d symbols → %d entries → %d movers "
        "(%d gainers, %d losers) in %dms",
        len(symbols), len(all_entries), len(movers),
        len(gainers), len(losers), scan_duration_ms,
    )

    return {
        "ok":                True,
        "mode":              "full_universe",
        "session":           session,
        "source":            "polygon_bulk_snapshot",
        "universe_count":    len(symbols),
        "symbols_requested": len(symbols),
        "symbols_returned":  len(all_entries),
        "valid_movers_count": len(movers),
        "skipped_count":     skipped,
        "scan_duration_ms":  scan_duration_ms,
        "top_gainers":       top_gainers,
        "top_losers":        top_losers,
        "top_movers":        top_movers,
        "error":             None,
        "warnings":          warnings,
    }


# ── Redis result persistence ──────────────────────────────────────────────────

async def _redis_save_result(snap: dict, fetched_at: float) -> None:
    try:
        from data.redis_client import make_redis
        r = make_redis()
        async with r:
            payload = json.dumps({"snapshot": snap, "fetched_at": fetched_at})
            # Store for 4× result TTL so stale data survives short outages
            await r.set(
                _REDIS_RESULT_KEY,
                payload,
                ex=settings.PREMARKET_SCANNER_RESULT_TTL_SECONDS * 4,
            )
    except Exception as exc:
        logger.debug("Full premarket Redis save failed: %s", exc)


async def _redis_load_result() -> tuple[dict, float] | None:
    try:
        from data.redis_client import make_redis
        r = make_redis()
        async with r:
            raw = await r.get(_REDIS_RESULT_KEY)
        if raw:
            p = json.loads(raw)
            return p.get("snapshot", {}), float(p.get("fetched_at", 0))
    except Exception as exc:
        logger.debug("Full premarket Redis load failed: %s", exc)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def _elapsed_ratio_for_enrichment() -> float:
    """
    Local helper — fraction of regular session (9:30–16:00 ET) elapsed.
    Mirrors paper.time_adjusted_volume.session_elapsed_ratio() to avoid cross-package import.
    Returns 1.0 outside regular session.
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        from datetime import timedelta
        now = datetime.now(timezone(timedelta(hours=-4)))
    t = now.time()
    if t < dtime(9, 30) or t >= dtime(16, 0):
        return 1.0
    elapsed = (t.hour - 9) * 3600 + (t.minute - 30) * 60 + t.second
    return min(elapsed / (390 * 60), 1.0)


def _enrich_mover_volumes(m: dict, elapsed_ratio: float, min_floor: float = 0.05) -> dict:
    """Add volume-multiple fields to a mover dict (non-mutating)."""
    dv = m.get("day_volume")
    pdv = m.get("previous_day_volume")
    enriched = dict(m)
    if dv is not None and pdv is not None and pdv > 0:
        enriched["volume_vs_prev_day"] = round(dv / pdv, 4)
        eff = max(elapsed_ratio, min_floor)
        ta = dv / (pdv * eff)
        import math as _math
        enriched["time_adj_volume_ratio"] = round(ta, 4) if _math.isfinite(ta) else None
        exp = pdv * eff
        enriched["expected_volume_now"] = int(exp) if _math.isfinite(exp) else None
    else:
        enriched["volume_vs_prev_day"] = None
        enriched["time_adj_volume_ratio"] = None
        enriched["expected_volume_now"] = None
    return enriched


def get_snapshot() -> dict[str, Any]:
    """
    Return in-memory snapshot with live age/ttl fields and volume-multiple enrichment.
    Returns empty dict if no data available yet (caller treats as unavailable).
    """
    if not _snapshot:
        return {}
    session     = get_current_session()
    ttl         = settings.PREMARKET_SCANNER_RESULT_TTL_SECONDS
    age         = int(time.time() - _fetched_at) if _fetched_at else None
    remaining   = max(0, ttl - age) if age is not None else None
    result = {
        **_snapshot,
        "session":     session,
        "fetched_at":  _fetched_at if _fetched_at else None,
        "age_seconds": age,
        "ttl_seconds": remaining,
    }
    # S1-V1: enrich mover lists with volume-multiple fields (non-mutating)
    _elapsed = _elapsed_ratio_for_enrichment()
    for _key in ("top_gainers", "top_losers", "top_movers"):
        if result.get(_key):
            result[_key] = [_enrich_mover_volumes(m, _elapsed) for m in result[_key]]
    return result


async def fetch_and_refresh(force: bool = False) -> dict[str, Any]:
    """
    Run a full-universe scan (TTL-guarded, asyncio.Lock double-checked).
    force=True bypasses TTL guard (used by admin refresh endpoint).
    Never raises — on failure returns last snapshot with error field set.
    """
    global _snapshot, _fetched_at

    if not settings.PREMARKET_SCANNER_ENABLED:
        return get_snapshot() or {
            "ok": False, "mode": "full_universe",
            "error": "PREMARKET_SCANNER_ENABLED=False",
            "top_gainers": [], "top_losers": [], "top_movers": [],
        }

    session = get_current_session()
    ttl = settings.PREMARKET_SCANNER_RESULT_TTL_SECONDS

    if not force:
        now = time.time()
        if _fetched_at and (now - _fetched_at) < ttl:
            return get_snapshot()

    async with _fetch_lock:
        if not force:
            now = time.time()
            if _fetched_at and (now - _fetched_at) < ttl:
                return get_snapshot()

        try:
            universe = await get_universe()
            if not universe:
                raise RuntimeError("Universe empty — Polygon reference tickers unavailable")

            new_snap = await _scan_universe(universe, session)
            _snapshot  = new_snap
            _fetched_at = time.time()
            await _redis_save_result(_snapshot, _fetched_at)

        except Exception as exc:
            logger.warning("Full premarket scan failed: %s", exc)
            if _snapshot:
                _snapshot = {**_snapshot, "ok": False, "error": str(exc)}
            else:
                _snapshot = {
                    "ok": False, "mode": "full_universe", "session": session,
                    "source": "polygon_bulk_snapshot",
                    "universe_count": 0, "symbols_requested": 0,
                    "symbols_returned": 0, "valid_movers_count": 0,
                    "skipped_count": 0, "scan_duration_ms": None,
                    "top_gainers": [], "top_losers": [], "top_movers": [],
                    "error": str(exc), "warnings": [],
                }

    return get_snapshot()


async def ensure_loaded() -> None:
    """
    Called at startup: populate from Redis if available.
    Does not trigger a live Polygon scan — background loop handles that.
    """
    global _snapshot, _fetched_at

    if _snapshot:
        return

    result = await _redis_load_result()
    if result:
        _snapshot, _fetched_at = result
        logger.info(
            "Full premarket scanner: loaded from Redis cache "
            "(%d gainers, %d losers)",
            len(_snapshot.get("top_gainers", [])),
            len(_snapshot.get("top_losers", [])),
        )


# ── Background loop ───────────────────────────────────────────────────────────

async def _background_loop() -> None:
    """Scan loop — active during premarket and regular session."""
    await asyncio.sleep(15)  # startup delay so server settles first
    while True:
        session  = get_current_session()
        if session == "premarket":
            interval = settings.PREMARKET_SCANNER_INTERVAL_PREMARKET_SECONDS
        elif session == "regular":
            interval = settings.PREMARKET_SCANNER_INTERVAL_REGULAR_SECONDS
        else:
            interval = 300  # afterhours/closed — long sleep, stale data served

        if session in ("premarket", "regular"):
            try:
                await fetch_and_refresh()
            except Exception as exc:
                logger.warning("Background scan loop error: %s", exc)

        await asyncio.sleep(interval)


def start_background_loop() -> None:
    """Start the background scan loop. Idempotent — safe to call multiple times."""
    global _bg_task
    if _bg_task is not None and not _bg_task.done():
        return
    try:
        loop = asyncio.get_event_loop()
        _bg_task = loop.create_task(_background_loop())
        logger.info(
            "Full premarket scanner: background loop started "
            "(premarket interval=%ds, regular interval=%ds)",
            settings.PREMARKET_SCANNER_INTERVAL_PREMARKET_SECONDS,
            settings.PREMARKET_SCANNER_INTERVAL_REGULAR_SECONDS,
        )
    except RuntimeError as exc:
        logger.warning("Full premarket scanner: could not start background loop — %s", exc)
