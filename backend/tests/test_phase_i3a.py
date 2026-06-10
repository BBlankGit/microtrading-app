"""
Phase I3-A tests — Pre-market movers intelligence.
No broker. No live trading. No real orders. No real-money execution.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _reset_module_state():
    import intelligence.premarket as p
    p._snapshot = {}
    p._fetched_at = 0.0
    p._fetch_lock = asyncio.Lock()


def _make_snap(symbol: str, last_price: float, prev_close: float,
               change_pct: float, volume: int = 100_000) -> dict:
    return {
        "symbol": symbol,
        "last_price": last_price,
        "prev_close": prev_close,
        "change_percent": change_pct,
        "day_volume": volume,
        "as_of": "2026-01-01T09:00:00Z",
    }


# ── session detection ─────────────────────────────────────────────────────────

def test_get_current_session_returns_valid_value():
    from intelligence.premarket import get_current_session
    session = get_current_session()
    assert session in ("premarket", "regular", "afterhours", "closed")


def test_session_returns_string():
    """get_current_session always returns one of the four valid session strings."""
    from intelligence.premarket import get_current_session
    # Already tested by test_get_current_session_returns_valid_value; this confirms type
    result = get_current_session()
    assert isinstance(result, str)
    assert result in ("premarket", "regular", "afterhours", "closed")


def test_cache_ttl_active_sessions():
    from intelligence.premarket import _cache_ttl, _TTL_ACTIVE, _TTL_IDLE
    assert _cache_ttl("premarket") == _TTL_ACTIVE
    assert _cache_ttl("regular") == _TTL_ACTIVE
    assert _cache_ttl("afterhours") == _TTL_IDLE
    assert _cache_ttl("closed") == _TTL_IDLE


# ── mover computation ─────────────────────────────────────────────────────────

def test_compute_mover_valid():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    result = _compute_mover(snap)
    assert result is not None
    assert result["symbol"] == "AAPL"
    assert result["last_price"] == 150.0
    assert result["change_percent"] == 3.45
    assert result["day_volume"] == 100_000


def test_compute_mover_filters_sub_3_dollar():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("PENNY", 2.99, 2.50, 4.0)
    assert _compute_mover(snap) is None


def test_compute_mover_filters_missing_change_pct():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 0.0)
    snap["change_percent"] = None
    assert _compute_mover(snap) is None


def test_compute_mover_filters_missing_price():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    snap["last_price"] = None
    assert _compute_mover(snap) is None


# ── fetch_and_refresh ─────────────────────────────────────────────────────────

def test_fetch_and_refresh_basic():
    """Fetch splits symbols into gainers and losers sorted by abs(change_pct)."""
    _reset_module_state()

    symbols = ["AAPL", "TSLA", "MSFT"]
    snapshots = {
        "AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45),
        "TSLA": _make_snap("TSLA", 200.0, 210.0, -4.76),
        "MSFT": _make_snap("MSFT", 300.0, 298.0, 0.67),
    }

    async def _run():
        with patch("marketdata.cache.read_active_symbols",
                   new_callable=AsyncMock, return_value=symbols), \
             patch("marketdata.cache.read_symbol",
                   new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)):
            from intelligence.premarket import fetch_and_refresh
            result = await fetch_and_refresh()
        return result

    result = asyncio.run(_run())
    assert result["ok"] is True
    assert len(result["gainers"]) == 2   # AAPL, MSFT (both > 0)
    assert len(result["losers"]) == 1    # TSLA
    assert result["gainers"][0]["symbol"] == "AAPL"  # sorted by abs(change_pct)
    assert result["error"] is None


def test_fetch_and_refresh_filters_sub_3():
    """Symbols priced below $3 are excluded from movers."""
    _reset_module_state()

    symbols = ["AAPL", "PENNY"]
    snapshots = {
        "AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45),
        "PENNY": _make_snap("PENNY", 1.50, 1.40, 7.14),
    }

    async def _run():
        with patch("marketdata.cache.read_active_symbols",
                   new_callable=AsyncMock, return_value=symbols), \
             patch("marketdata.cache.read_symbol",
                   new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)):
            from intelligence.premarket import fetch_and_refresh
            return await fetch_and_refresh()

    result = asyncio.run(_run())
    assert all(m["symbol"] != "PENNY" for m in result["gainers"] + result["losers"])


def test_fetch_and_refresh_ttl_guard():
    """Second call within TTL does not re-read Redis."""
    _reset_module_state()

    symbols = ["AAPL"]
    snapshots = {"AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45)}
    call_count = 0

    async def fake_read_symbols():
        nonlocal call_count
        call_count += 1
        return symbols

    async def _run():
        with patch("marketdata.cache.read_active_symbols",
                   side_effect=fake_read_symbols), \
             patch("marketdata.cache.read_symbol",
                   new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)), \
             patch("intelligence.premarket.get_current_session", return_value="premarket"):
            from intelligence.premarket import fetch_and_refresh
            await fetch_and_refresh()
            await fetch_and_refresh()

    asyncio.run(_run())
    assert call_count == 1


def test_fetch_and_refresh_error_preserves_cache():
    """On error, ok=False but previous gainers/losers are preserved."""
    _reset_module_state()

    symbols = ["AAPL"]
    snapshots = {"AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45)}

    async def _run():
        import intelligence.premarket as p

        # First: successful fetch
        with patch("marketdata.cache.read_active_symbols",
                   new_callable=AsyncMock, return_value=symbols), \
             patch("marketdata.cache.read_symbol",
                   new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)), \
             patch("intelligence.premarket.get_current_session", return_value="closed"):
            from intelligence.premarket import fetch_and_refresh
            first = await fetch_and_refresh()

        p._fetched_at = 0.0  # force TTL expiry for second call

        # Second: raise on read_active_symbols
        with patch("marketdata.cache.read_active_symbols",
                   new_callable=AsyncMock, side_effect=RuntimeError("Redis down")), \
             patch("intelligence.premarket.get_current_session", return_value="closed"):
            second = await fetch_and_refresh()
        return first, second

    first, second = asyncio.run(_run())
    assert first["ok"] is True
    assert len(first["gainers"]) == 1
    assert second["ok"] is False
    assert second["error"] is not None
    assert len(second["gainers"]) == 1   # cached gainers preserved


# ── endpoint smoke test ───────────────────────────────────────────────────────

def test_get_premarket_endpoint():
    """GET /api/intelligence/premarket returns valid shape."""
    _reset_module_state()

    from fastapi.testclient import TestClient
    from main import app

    symbols = ["AAPL", "TSLA"]
    snapshots = {
        "AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45),
        "TSLA": _make_snap("TSLA", 200.0, 210.0, -4.76),
    }

    with patch("marketdata.cache.read_active_symbols",
               new_callable=AsyncMock, return_value=symbols), \
         patch("marketdata.cache.read_symbol",
               new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)):
        client = TestClient(app)
        resp = client.get("/api/intelligence/premarket")

    assert resp.status_code == 200
    data = resp.json()
    assert "gainers" in data
    assert "losers" in data
    assert "session" in data
    assert "fetched_at" in data
