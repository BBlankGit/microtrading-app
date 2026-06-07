"""
Tests for Phase 2C paper universe builder.

No broker. No real orders. No real Polygon calls.
All external calls are mocked.
"""

import pytest
from unittest.mock import AsyncMock, patch

from paper.universe import (
    build_dynamic_universe,
    get_base_universe,
    get_cached_universe,
)

# ── Shared token fixture ──────────────────────────────────────────────────────

_TOKEN = "test_admin_token_universe"


@pytest.fixture(autouse=True)
def set_admin_token(monkeypatch):
    from core import config
    monkeypatch.setattr(config.settings, "ADMIN_API_TOKEN", _TOKEN)


# ── Cache-clearing fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=False)
def reset_universe_cache():
    """Clear the module-level universe cache before and after each test."""
    import paper.universe as uni
    uni._universe_cache = None
    uni._cache_built_at = None
    yield
    uni._universe_cache = None
    uni._cache_built_at = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _good_snapshot(sym: str) -> dict:
    """Normalized snapshot dict that passes the quality gate."""
    return {
        "symbol": sym,
        "last_quote": {"bid": 99.90, "ask": 100.10, "bid_size": 100, "ask_size": 100},
        "last_trade": {"price": 100.00},
        "day": {"volume": 2_000_000},
        "change_percent": 2.5,
    }


def _prev_close(volume: int = 1_500_000) -> dict:
    return {"volume": volume, "close": 98.0}


# ── Base universe tests ───────────────────────────────────────────────────────

def test_get_base_universe_deduplicates_symbols(monkeypatch):
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL,MSFT,AAPL,NVDA,MSFT")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    result = get_base_universe()
    assert result == ["AAPL", "MSFT", "NVDA"]


def test_get_base_universe_respects_max_size(monkeypatch):
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL,MSFT,NVDA,TSLA,AMD")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 3)
    result = get_base_universe()
    assert len(result) == 3
    assert result == ["AAPL", "MSFT", "NVDA"]


def test_get_base_universe_strips_whitespace(monkeypatch):
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", " AAPL , MSFT , NVDA ")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    result = get_base_universe()
    assert result == ["AAPL", "MSFT", "NVDA"]


# ── Dynamic universe disabled: falls back to base ─────────────────────────────

@pytest.mark.asyncio
async def test_build_dynamic_universe_disabled_falls_back_to_base(monkeypatch, reset_universe_cache):
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", False)
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL,MSFT,NVDA,TSLA,AMD")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 3)

    result = await build_dynamic_universe()

    assert result["refresh_reason"] == "disabled"
    assert result["active_symbols"] == ["AAPL", "MSFT", "NVDA"]
    assert result["active_count"] == 3
    assert result["dynamic_symbols"] == []


# ── Cap to max_symbols_per_tick ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_universe_capped_to_max_per_tick(monkeypatch, reset_universe_cache):
    from core import config
    syms = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META"]
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", ",".join(syms))
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 3)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)

    import paper.universe as uni

    async def fake_snapshot(s):
        return _good_snapshot(s)

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        result = await build_dynamic_universe()

    assert result["active_count"] <= 3
    assert len(result["active_symbols"]) <= 3


# ── Ranking ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ranking_prefers_larger_abs_change(monkeypatch, reset_universe_cache):
    """Symbol with higher abs change_percent should appear first in active_symbols."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "LOW,HIGH")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)

    import paper.universe as uni

    snapshots = {
        "LOW": {**_good_snapshot("LOW"), "change_percent": 1.0},
        "HIGH": {**_good_snapshot("HIGH"), "change_percent": 5.0},
    }

    async def fake_snapshot(s):
        return snapshots[s]

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        result = await build_dynamic_universe()

    assert result["active_symbols"][0] == "HIGH", (
        f"Expected HIGH first, got {result['active_symbols']}"
    )


@pytest.mark.asyncio
async def test_ranking_tradable_before_non_tradable(monkeypatch, reset_universe_cache):
    """Tradable symbols rank above non-tradable even with smaller change_percent."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "NONTRADE,TRADE")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)

    import paper.universe as uni

    snapshots = {
        # Has high change but no valid quote → non-tradable
        "NONTRADE": {
            "symbol": "NONTRADE",
            "last_quote": {},
            "last_trade": {"price": 50.0},
            "day": {"volume": 2_000_000},
            "change_percent": 10.0,
        },
        # Lower change but valid quote → tradable
        "TRADE": _good_snapshot("TRADE"),  # change_percent=2.5
    }

    async def fake_snapshot(s):
        return snapshots[s]

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        result = await build_dynamic_universe()

    tradable_index = result["active_symbols"].index("TRADE")
    nontrade_index = result["active_symbols"].index("NONTRADE")
    assert tradable_index < nontrade_index


# ── Eligibility filters ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eligibility_filters_out_low_volume(monkeypatch, reset_universe_cache):
    """Symbol with day_volume below PAPER_MIN_DAY_VOLUME is excluded from dynamic_symbols."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "LOWVOL,GOODVOL")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)

    import paper.universe as uni

    snapshots = {
        "LOWVOL": {**_good_snapshot("LOWVOL"), "day": {"volume": 100}},
        "GOODVOL": _good_snapshot("GOODVOL"),
    }

    async def fake_snapshot(s):
        return snapshots[s]

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        result = await build_dynamic_universe()

    assert "LOWVOL" not in result["dynamic_symbols"]
    assert "GOODVOL" in result["dynamic_symbols"]


@pytest.mark.asyncio
async def test_eligibility_filters_out_low_abs_change(monkeypatch, reset_universe_cache):
    """Symbol with abs(change_percent) < PAPER_MIN_CHANGE_ABS_PERCENT is excluded."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "FLAT,MOVER")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)

    import paper.universe as uni

    snapshots = {
        "FLAT": {**_good_snapshot("FLAT"), "change_percent": 0.1},
        "MOVER": {**_good_snapshot("MOVER"), "change_percent": 3.0},
    }

    async def fake_snapshot(s):
        return snapshots[s]

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        result = await build_dynamic_universe()

    assert "FLAT" not in result["dynamic_symbols"]
    assert "MOVER" in result["dynamic_symbols"]


# ── Cache behaviour ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_dynamic_universe_returns_cached_within_ttl(monkeypatch, reset_universe_cache):
    """Second call within TTL returns refresh_reason='cached' without new Polygon calls."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)
    monkeypatch.setattr(config.settings, "PAPER_MARKET_DISCOVERY_ENABLED", False)

    import paper.universe as uni

    call_count = {"n": 0}

    async def fake_snapshot(s):
        call_count["n"] += 1
        return _good_snapshot(s)

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        first = await build_dynamic_universe()
        second = await build_dynamic_universe()

    assert first["refresh_reason"] != "cached"
    assert second["refresh_reason"] == "cached"
    assert call_count["n"] == 1  # polygon called only once


@pytest.mark.asyncio
async def test_build_dynamic_universe_force_refresh_bypasses_cache(monkeypatch, reset_universe_cache):
    """force_refresh=True calls Polygon even when cache is fresh."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)
    monkeypatch.setattr(config.settings, "PAPER_MARKET_DISCOVERY_ENABLED", False)

    import paper.universe as uni

    call_count = {"n": 0}

    async def fake_snapshot(s):
        call_count["n"] += 1
        return _good_snapshot(s)

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        await build_dynamic_universe()
        await build_dynamic_universe(force_refresh=True)

    assert call_count["n"] == 2


# ── get_cached_universe ───────────────────────────────────────────────────────

def test_get_cached_universe_returns_none_when_not_built(reset_universe_cache):
    assert get_cached_universe() is None


@pytest.mark.asyncio
async def test_get_cached_universe_returns_dict_after_build(monkeypatch, reset_universe_cache):
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", False)
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    await build_dynamic_universe()
    cached = get_cached_universe()
    assert cached is not None
    assert "active_symbols" in cached


# ── Error handling ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_dynamic_universe_continues_on_per_symbol_error(monkeypatch, reset_universe_cache):
    """Polygon error on one symbol does not crash the builder; recorded in errors."""
    from core import config
    from data.polygon_client import PolygonError
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "GOOD,BAD")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_REFRESH_SECONDS", 300)
    monkeypatch.setattr(config.settings, "PAPER_MIN_PRICE", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_PRICE", 1000.0)
    monkeypatch.setattr(config.settings, "PAPER_MIN_DAY_VOLUME", 500_000)
    monkeypatch.setattr(config.settings, "PAPER_MIN_CHANGE_ABS_PERCENT", 0.5)

    import paper.universe as uni

    async def fake_snapshot(s):
        if s == "BAD":
            raise PolygonError("simulated failure")
        return _good_snapshot(s)

    async def fake_prev(s):
        return _prev_close()

    with (
        patch.object(uni.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(uni.polygon_client, "get_previous_close", side_effect=fake_prev),
    ):
        result = await build_dynamic_universe()

    assert any(e["symbol"] == "BAD" for e in result["errors"])
    # GOOD should still appear
    assert "GOOD" in result["dynamic_symbols"] or "GOOD" in result["active_symbols"]


# ── Simulator tick includes universe metadata ─────────────────────────────────

@pytest.mark.asyncio
async def test_tick_result_includes_universe_metadata(reset_universe_cache):
    """run_tick() result contains all four universe metadata fields."""
    import paper.simulator as sim

    sim._account.reset()
    sim._last_prices.clear()

    _uni_stub = {
        "active_symbols": ["AAPL"],
        "active_count": 1,
        "last_refreshed_at": "2026-01-01T00:00:00+00:00",
        "refresh_reason": "test",
    }
    q = {
        "tradable": False,
        "ask": None,
        "bid": None,
        "last_trade_price": None,
        "spread_percent": None,
        "change_percent": None,
        "volume_ratio": None,
        "rejection_reasons": ["mock"],
    }

    with (
        patch("paper.simulator.get_active_paper_universe", new=AsyncMock(return_value=_uni_stub)),
        patch.object(sim.polygon_client, "get_ticker_snapshot", new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close", new=AsyncMock(return_value={})),
        patch("paper.simulator.evaluate_market_quality", return_value=q),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
    ):
        result = await sim.run_tick()

    assert result["universe_active_count"] == 1
    assert result["universe_symbols"] == ["AAPL"]
    assert result["universe_last_refreshed_at"] == "2026-01-01T00:00:00+00:00"
    assert result["universe_refresh_reason"] == "test"


# ── API endpoint tests ────────────────────────────────────────────────────────

def test_universe_endpoint_public(client, monkeypatch, reset_universe_cache):
    """GET /api/paper/universe returns 200 without authentication."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", False)
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL,MSFT")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)

    resp = client.get("/api/paper/universe")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_symbols" in data
    assert "active_count" in data
    assert "refresh_reason" in data


def test_universe_refresh_endpoint_rejects_missing_token(client, reset_universe_cache):
    """POST /api/paper/universe/refresh without token → 401 or 503."""
    resp = client.post("/api/paper/universe/refresh")
    assert resp.status_code in (401, 503)


def test_universe_refresh_endpoint_rejects_wrong_token(client, reset_universe_cache):
    """POST /api/paper/universe/refresh with wrong token → 401."""
    resp = client.post(
        "/api/paper/universe/refresh",
        headers={"Authorization": "Bearer wrong_token"},
    )
    assert resp.status_code == 401


def test_universe_refresh_endpoint_accepts_correct_token(client, monkeypatch, reset_universe_cache):
    """POST /api/paper/universe/refresh with correct token → 200."""
    from core import config
    monkeypatch.setattr(config.settings, "PAPER_DYNAMIC_UNIVERSE_ENABLED", False)
    monkeypatch.setattr(config.settings, "PAPER_BASE_UNIVERSE", "AAPL")
    monkeypatch.setattr(config.settings, "PAPER_MAX_UNIVERSE_SIZE", 150)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SYMBOLS_PER_TICK", 50)

    resp = client.post(
        "/api/paper/universe/refresh",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "active_symbols" in data
    assert data["refresh_reason"] == "disabled"


def test_dashboard_universe_field_present(client, reset_universe_cache):
    """GET /api/paper/dashboard includes a 'universe' key (may be null if not built)."""
    resp = client.get("/api/paper/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "universe" in data
