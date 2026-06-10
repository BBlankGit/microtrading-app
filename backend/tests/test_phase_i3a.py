"""
Phase I3-A + I3-A-H1 tests — Pre-market movers intelligence.
No broker. No live trading. No real orders. No real-money execution.
"""
from __future__ import annotations

import asyncio
import time as _time
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
    """Build a collector-cache-format SymbolPayload dict (input to _compute_mover)."""
    return {
        "symbol": symbol,
        "last_price": last_price,
        "prev_close": prev_close,          # collector field name (input)
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
    from intelligence.premarket import get_current_session
    result = get_current_session()
    assert isinstance(result, str)
    assert result in ("premarket", "regular", "afterhours", "closed")


def test_cache_ttl_active_sessions():
    from intelligence.premarket import _cache_ttl, _TTL_ACTIVE, _TTL_IDLE
    assert _cache_ttl("premarket") == _TTL_ACTIVE
    assert _cache_ttl("regular") == _TTL_ACTIVE
    assert _cache_ttl("afterhours") == _TTL_IDLE
    assert _cache_ttl("closed") == _TTL_IDLE


# ── safe float coercion ───────────────────────────────────────────────────────

def test_safe_float_valid():
    from intelligence.premarket import _safe_float
    assert _safe_float(3.5) == 3.5
    assert _safe_float("3.5") == 3.5
    assert _safe_float(0) == 0.0


def test_safe_float_invalid():
    from intelligence.premarket import _safe_float
    assert _safe_float(None) is None
    assert _safe_float("bad") is None
    assert _safe_float(float("inf")) is None
    assert _safe_float(float("nan")) is None


# ── mover computation ─────────────────────────────────────────────────────────

def test_compute_mover_valid():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    result = _compute_mover(snap)
    assert result is not None
    assert result["symbol"] == "AAPL"
    assert result["last_price"] == 150.0
    assert result["previous_close"] == 145.0          # renamed output field
    assert result["raw_change_percent"] == 3.45        # collector value preserved
    assert "gap_percent" in result
    # gap = (150 - 145) / 145 * 100 = 3.4483…
    assert abs(result["gap_percent"] - 3.4483) < 0.01
    assert result["day_volume"] == 100_000


def test_compute_mover_gap_percent_computed_from_prices():
    """gap_percent is computed from prices, not taken from collector change_percent."""
    from intelligence.premarket import _compute_mover
    # Deliberately set change_percent to a value that differs from the real gap
    snap = _make_snap("TEST", 110.0, 100.0, 99.99)  # real gap = 10%, not 99.99
    result = _compute_mover(snap)
    assert result is not None
    assert abs(result["gap_percent"] - 10.0) < 0.01
    assert result["raw_change_percent"] == 99.99      # collector value stored as-is


def test_compute_mover_filters_sub_3_dollar():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("PENNY", 2.99, 2.50, 4.0)
    assert _compute_mover(snap) is None


def test_compute_mover_filters_missing_price():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    snap["last_price"] = None
    assert _compute_mover(snap) is None


def test_compute_mover_filters_missing_change_pct():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 0.0)
    snap["change_percent"] = None
    assert _compute_mover(snap) is None


# ── H1: new validation tests ──────────────────────────────────────────────────

def test_compute_mover_excludes_none_prev_close():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    snap["prev_close"] = None
    assert _compute_mover(snap) is None


def test_compute_mover_excludes_zero_prev_close():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    snap["prev_close"] = 0
    assert _compute_mover(snap) is None


def test_compute_mover_excludes_negative_prev_close():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    snap["prev_close"] = -5.0
    assert _compute_mover(snap) is None


def test_compute_mover_excludes_invalid_last_price_string():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    snap["last_price"] = "not_a_number"
    assert _compute_mover(snap) is None


def test_compute_mover_excludes_invalid_change_pct_string():
    from intelligence.premarket import _compute_mover
    snap = _make_snap("AAPL", 150.0, 145.0, 3.45)
    snap["change_percent"] = "bad_value"
    assert _compute_mover(snap) is None


def test_compute_mover_skips_malformed_symbol_does_not_raise():
    """_compute_mover returns None for any malformed input without raising."""
    from intelligence.premarket import _compute_mover
    assert _compute_mover({}) is None
    assert _compute_mover({"symbol": "X", "last_price": "???", "prev_close": "???",
                            "change_percent": "???"}) is None


# ── fetch_and_refresh ─────────────────────────────────────────────────────────

def test_fetch_and_refresh_basic():
    """Fetch splits symbols into gainers and losers sorted by abs(gap_percent)."""
    _reset_module_state()

    symbols = ["AAPL", "TSLA", "MSFT"]
    snapshots = {
        # AAPL gap = (150-145)/145*100 = 3.448%
        "AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45),
        # TSLA gap = (200-210)/210*100 = -4.762%
        "TSLA": _make_snap("TSLA", 200.0, 210.0, -4.76),
        # MSFT gap = (300-298)/298*100 = 0.671%
        "MSFT": _make_snap("MSFT", 300.0, 298.0, 0.67),
    }

    async def _run():
        with patch("marketdata.cache.read_active_symbols",
                   new_callable=AsyncMock, return_value=symbols), \
             patch("marketdata.cache.read_symbol",
                   new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)):
            from intelligence.premarket import fetch_and_refresh
            return await fetch_and_refresh()

    result = asyncio.run(_run())
    assert result["ok"] is True
    assert len(result["gainers"]) == 2   # AAPL, MSFT (gap > 0)
    assert len(result["losers"]) == 1    # TSLA (gap < 0)
    assert result["gainers"][0]["symbol"] == "AAPL"   # |3.448| > |0.671|
    assert result["error"] is None
    # Each mover exposes gap_percent and previous_close
    assert "gap_percent" in result["gainers"][0]
    assert "previous_close" in result["gainers"][0]


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

        with patch("marketdata.cache.read_active_symbols",
                   new_callable=AsyncMock, return_value=symbols), \
             patch("marketdata.cache.read_symbol",
                   new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)), \
             patch("intelligence.premarket.get_current_session", return_value="closed"):
            from intelligence.premarket import fetch_and_refresh
            first = await fetch_and_refresh()

        p._fetched_at = 0.0  # force TTL expiry

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


# ── H1: malformed symbol skipped in batch ─────────────────────────────────────

def test_fetch_and_refresh_skips_malformed_symbol():
    """A symbol with invalid data is skipped; valid symbols still appear in result."""
    _reset_module_state()

    symbols = ["AAPL", "BADSTOCK"]
    snapshots = {
        "AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45),
        "BADSTOCK": {
            "symbol": "BADSTOCK",
            "last_price": "not_a_number",
            "prev_close": 100.0,
            "change_percent": 5.0,
            "day_volume": 50_000,
            "as_of": "2026-01-01T09:00:00Z",
        },
    }

    async def _run():
        with patch("marketdata.cache.read_active_symbols",
                   new_callable=AsyncMock, return_value=symbols), \
             patch("marketdata.cache.read_symbol",
                   new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)):
            from intelligence.premarket import fetch_and_refresh
            return await fetch_and_refresh()

    result = asyncio.run(_run())
    assert result["ok"] is True
    all_symbols = [m["symbol"] for m in result["gainers"] + result["losers"]]
    assert "AAPL" in all_symbols
    assert "BADSTOCK" not in all_symbols


# ── H1: endpoint refreshes on TTL expiry ─────────────────────────────────────

def test_endpoint_refreshes_on_ttl_expiry():
    """GET /api/intelligence/premarket triggers refresh when snapshot is stale."""
    _reset_module_state()

    import intelligence.premarket as p

    symbols = ["AAPL"]
    snapshots = {"AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45)}

    # Seed a stale snapshot (fetched 2 hours ago — past any TTL)
    p._snapshot = {
        "ok": True, "session": "closed", "symbol_count": 1,
        "gainers": [], "losers": [], "error": None,
    }
    p._fetched_at = _time.time() - 7200

    call_count = 0

    async def fake_read_symbols():
        nonlocal call_count
        call_count += 1
        return symbols

    from fastapi.testclient import TestClient
    from main import app

    # I3-B: stub full-universe scanner as unavailable so active-universe path runs
    with patch("intelligence.full_premarket.get_snapshot", return_value={}), \
         patch("intelligence.full_premarket.fetch_and_refresh",
               new_callable=AsyncMock, return_value={"ok": False}), \
         patch("marketdata.cache.read_active_symbols", side_effect=fake_read_symbols), \
         patch("marketdata.cache.read_symbol",
               new_callable=AsyncMock, side_effect=lambda s: snapshots.get(s)):
        client = TestClient(app)
        resp = client.get("/api/intelligence/premarket")

    assert resp.status_code == 200
    assert call_count == 1   # refresh was triggered by TTL expiry


# ── endpoint smoke test ───────────────────────────────────────────────────────

def test_get_premarket_endpoint():
    """GET /api/intelligence/premarket returns valid shape including gap_percent."""
    _reset_module_state()

    from fastapi.testclient import TestClient
    from main import app

    symbols = ["AAPL", "TSLA"]
    snapshots = {
        "AAPL": _make_snap("AAPL", 150.0, 145.0, 3.45),
        "TSLA": _make_snap("TSLA", 200.0, 210.0, -4.76),
    }

    # I3-B: stub full-universe scanner as unavailable so active-universe path runs
    with patch("intelligence.full_premarket.get_snapshot", return_value={}), \
         patch("intelligence.full_premarket.fetch_and_refresh",
               new_callable=AsyncMock, return_value={"ok": False}), \
         patch("marketdata.cache.read_active_symbols",
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
    # Each mover exposes gap_percent and previous_close (H1 Fix 3)
    for mover in data["gainers"] + data["losers"]:
        assert "gap_percent" in mover
        assert "previous_close" in mover
        assert "raw_change_percent" in mover
