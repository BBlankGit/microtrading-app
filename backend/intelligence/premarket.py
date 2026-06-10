"""
Pre-market movers intelligence — read-only snapshot.

Reads from the marketdata collector's Redis cache (market:snapshot:{symbol}).
No direct Polygon calls. No broker. No live trading. No real orders.

gap_percent is computed from validated last_price and previous_close.
raw_change_percent stores the collector's todaysChangePerc (Polygon) for reference.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MIN_PRICE = 3.0        # skip sub-$3 symbols
_TOP_N = 20             # movers returned per direction
_TTL_ACTIVE = 60        # seconds — premarket / regular session
_TTL_IDLE = 300         # seconds — afterhours / closed

# ── In-memory state ──────────────────────────────────────────────────────────
_snapshot: dict[str, Any] = {}
_fetched_at: float = 0.0
_fetch_lock = asyncio.Lock()


# ── Session detection ─────────────────────────────────────────────────────────

def get_current_session() -> str:
    """Return 'premarket' | 'regular' | 'afterhours' | 'closed'."""
    try:
        from zoneinfo import ZoneInfo
        ny_tz = ZoneInfo("America/New_York")
        now = datetime.now(ny_tz)
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


def _cache_ttl(session: str) -> int:
    return _TTL_ACTIVE if session in ("premarket", "regular") else _TTL_IDLE


# ── Safe numeric coercion ─────────────────────────────────────────────────────

def _safe_float(val: Any) -> float | None:
    """Coerce val to float; return None if missing, non-numeric, or non-finite."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ── Mover computation ─────────────────────────────────────────────────────────

def _compute_mover(snap: dict) -> dict | None:
    """
    Convert a SymbolPayload dict to a mover entry.

    Returns None to skip this symbol; never raises.
    Exclusion rules (per symbol, no global failure):
      - last_price missing, non-numeric, non-finite, <= 0, or < _MIN_PRICE
      - previous_close missing, non-numeric, non-finite, or <= 0
      - change_percent missing, non-numeric, or non-finite
    gap_percent is computed from validated last_price and previous_close.
    raw_change_percent is the collector's todaysChangePerc stored for reference.
    """
    try:
        symbol = (snap.get("symbol") or "").upper()
        if not symbol:
            return None

        last_price = _safe_float(snap.get("last_price"))
        prev_close = _safe_float(snap.get("prev_close"))
        raw_change_pct = _safe_float(snap.get("change_percent"))
        volume = snap.get("day_volume")

        if last_price is None or last_price <= 0 or last_price < _MIN_PRICE:
            return None
        if prev_close is None or prev_close <= 0:
            return None
        if raw_change_pct is None:
            return None

        gap_percent = ((last_price - prev_close) / prev_close) * 100

        day_volume: int | None = None
        if volume is not None:
            try:
                day_volume = int(volume)
            except (TypeError, ValueError):
                day_volume = None

        return {
            "symbol": symbol,
            "last_price": round(last_price, 4),
            "previous_close": round(prev_close, 4),
            "gap_percent": round(gap_percent, 4),
            "raw_change_percent": round(raw_change_pct, 4),
            "day_volume": day_volume,
            "as_of": snap.get("as_of"),
        }
    except Exception:
        return None


# ── Core refresh ──────────────────────────────────────────────────────────────

async def fetch_and_refresh() -> dict[str, Any]:
    """
    Refresh pre-market movers from Redis marketdata cache.

    TTL guard + asyncio.Lock double-checked locking prevents redundant reads.
    Never raises — on failure returns snapshot with error field.
    """
    global _snapshot, _fetched_at

    session = get_current_session()
    ttl = _cache_ttl(session)

    now = time.time()
    if _fetched_at and (now - _fetched_at) < ttl:
        return get_snapshot()

    async with _fetch_lock:
        now = time.time()
        if _fetched_at and (now - _fetched_at) < ttl:
            return get_snapshot()

        try:
            from marketdata.cache import read_active_symbols, read_symbol

            symbols = await read_active_symbols()
            movers: list[dict] = []
            symbol_count = len(symbols)

            for sym in symbols:
                raw = await read_symbol(sym)
                if not raw:
                    continue
                mover = _compute_mover(raw)
                if mover:
                    movers.append(mover)

            movers.sort(key=lambda x: abs(x["gap_percent"]), reverse=True)
            gainers = [m for m in movers if m["gap_percent"] > 0][:_TOP_N]
            losers  = [m for m in movers if m["gap_percent"] < 0][:_TOP_N]

            _snapshot = {
                "ok": True,
                "session": session,
                "symbol_count": symbol_count,
                "gainers": gainers,
                "losers": losers,
                "error": None,
            }
            _fetched_at = time.time()
            logger.info(
                "Premarket movers: %d gainers, %d losers from %d symbols",
                len(gainers), len(losers), symbol_count,
            )

        except Exception as exc:
            logger.warning("Premarket movers fetch failed: %s", exc)
            if _snapshot:
                _snapshot = {**_snapshot, "ok": False, "error": str(exc)}
            else:
                _snapshot = {
                    "ok": False,
                    "session": session,
                    "symbol_count": 0,
                    "gainers": [],
                    "losers": [],
                    "error": str(exc),
                }

    return get_snapshot()


# ── Snapshot read ─────────────────────────────────────────────────────────────

def get_snapshot() -> dict[str, Any]:
    """Return the current in-memory state with live age/ttl fields."""
    session = get_current_session()
    ttl = _cache_ttl(session)
    age = int(time.time() - _fetched_at) if _fetched_at else None
    remaining_ttl = max(0, ttl - age) if age is not None else None
    base = _snapshot if _snapshot else {
        "ok": False,
        "session": session,
        "symbol_count": 0,
        "gainers": [],
        "losers": [],
        "error": None,
    }
    return {
        **base,
        "session": session,
        "fetched_at": _fetched_at if _fetched_at else None,
        "age_seconds": age,
        "ttl_seconds": remaining_ttl,
    }
