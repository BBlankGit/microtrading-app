"""
Phase D2 tests: Paper simulator reads shared market-data cache first.
No broker. No live trading. No real orders. No real-money execution.

Architecture:
  try_cache_for_quality()  — cache-only lookup; never calls Polygon.
  Simulator _fetch_quality — calls try_cache_for_quality; Polygon fallback
                             stays in the simulator (old mock targets preserved).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fresh_payload(sym: str, age_seconds: float = 5.0) -> dict:
    """Return a SymbolPayload dict (as stored in Redis) with a recent fetched_at."""
    fetched = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {
        "symbol": sym,
        "source": "polygon",
        "as_of": fetched.isoformat(),
        "fetched_at": fetched.isoformat(),
        "ttl_seconds": 30,
        "last_price": 150.50,
        "bid": 150.40,
        "ask": 150.60,
        "spread_percent": 0.13,
        "day_volume": 2_000_000.0,
        "prev_day_volume": 1_500_000.0,
        "volume_ratio": 1.33,
        "change_percent": 1.5,
        "prev_close": 148.50,
        "minute_high": None,
        "minute_low": None,
        "minute_close": None,
        "raw_status": "ok",
        "error": None,
    }


def _stale_payload(sym: str) -> dict:
    """Return a payload whose fetched_at is 60 seconds ago (stale for max_age=30)."""
    return _fresh_payload(sym, age_seconds=60.0)


def _cfg_map(fallback_enabled: bool = True, max_age: int = 30) -> dict:
    return {
        "PAPER_USE_MARKETDATA_CACHE": True,
        "PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS": max_age,
        "PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED": fallback_enabled,
        "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY": True,
    }


_MOCK_QUALITY = {
    "symbol": "AMD",
    "last_trade_price": 150.50,
    "bid": 150.40,
    "ask": 150.60,
    "spread": 0.20,
    "spread_percent": 0.13,
    "bid_size": None,
    "ask_size": None,
    "day_volume": 2_000_000.0,
    "previous_day_volume": 1_500_000.0,
    "volume_ratio": 1.33,
    "change_percent": 1.5,
    "has_valid_quote": True,
    "has_valid_trade": True,
    "has_sufficient_volume": True,
    "has_acceptable_spread": True,
    "tradable": True,
    "rejection_reasons": [],
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. try_cache_for_quality: fresh hit → quality returned, source=cache
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_fresh_hit_returns_quality():
    """Fresh cache hit: quality dict returned with source='cache'."""
    from paper.marketdata_adapter import try_cache_for_quality

    payload = _fresh_payload("AMD", age_seconds=5.0)

    with (
        patch("paper.marketdata_adapter._cfg", side_effect=lambda k: _cfg_map()[k]),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=payload)),
    ):
        q, meta = await try_cache_for_quality("AMD")

    assert q is not None
    assert q["symbol"] == "AMD"
    assert q["bid"] == 150.40
    assert meta["marketdata_source"] == "cache"
    assert meta["marketdata_stale"] is False
    assert meta["marketdata_age_seconds"] is not None
    assert meta["marketdata_age_seconds"] < 30


# ─────────────────────────────────────────────────────────────────────────────
# 2. try_cache_for_quality: stale + fallback enabled → None, source=stale
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_stale_fallback_enabled_signals_fallthrough():
    """Stale cache + fallback enabled → adapter signals fall-through (source=stale)."""
    from paper.marketdata_adapter import try_cache_for_quality

    payload = _stale_payload("NVDA")

    with (
        patch("paper.marketdata_adapter._cfg",
              side_effect=lambda k: _cfg_map(fallback_enabled=True)[k]),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=payload)),
    ):
        q, meta = await try_cache_for_quality("NVDA")

    assert q is None
    assert meta["marketdata_source"] == "stale"
    assert meta["marketdata_stale"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. try_cache_for_quality: stale + fallback disabled → None, source=stale_no_fallback
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_stale_no_fallback_signals_reject():
    """Stale cache + fallback disabled → source ends with _no_fallback."""
    from paper.marketdata_adapter import try_cache_for_quality

    payload = _stale_payload("TSLA")

    with (
        patch("paper.marketdata_adapter._cfg",
              side_effect=lambda k: _cfg_map(fallback_enabled=False)[k]),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=payload)),
    ):
        q, meta = await try_cache_for_quality("TSLA")

    assert q is None
    assert meta["marketdata_source"] == "stale_no_fallback"
    assert meta["marketdata_stale"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. try_cache_for_quality: miss + fallback enabled → None, source=missing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_miss_fallback_enabled_signals_fallthrough():
    """Cache miss + fallback enabled → source=missing (fall-through signal)."""
    from paper.marketdata_adapter import try_cache_for_quality

    with (
        patch("paper.marketdata_adapter._cfg",
              side_effect=lambda k: _cfg_map(fallback_enabled=True)[k]),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=None)),
    ):
        q, meta = await try_cache_for_quality("AMD")

    assert q is None
    assert meta["marketdata_source"] == "missing"
    assert meta["marketdata_stale"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. try_cache_for_quality: miss + fallback disabled → source=missing_no_fallback
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_miss_no_fallback_signals_reject():
    """Cache miss + fallback disabled → source=missing_no_fallback."""
    from paper.marketdata_adapter import try_cache_for_quality

    with (
        patch("paper.marketdata_adapter._cfg",
              side_effect=lambda k: _cfg_map(fallback_enabled=False)[k]),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=None)),
    ):
        q, meta = await try_cache_for_quality("AMD")

    assert q is None
    assert meta["marketdata_source"] == "missing_no_fallback"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Simulator: cache disabled → Polygon called directly, source=polygon_direct
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_cache_disabled_calls_polygon_directly():
    """
    When PAPER_USE_MARKETDATA_CACHE=False the simulator skips the adapter
    entirely and calls Polygon via the existing path. source_meta = polygon_direct.
    Note: patch paper.simulator._cfg (the module-level alias) to control config.
    """
    import paper.simulator as sim

    good_q = dict(_MOCK_QUALITY)

    # cfg overrides needed to control simulator behaviour; patch the alias directly
    def _cfg_disabled(k):
        return {
            "PAPER_USE_MARKETDATA_CACHE": False,
            "PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS": 30,
            "PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED": True,
            "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY": True,
            "PAPER_ENTRY_SCORE_THRESHOLD": 70,
            "PAPER_TAKE_PROFIT_PERCENT": 0.6,
            "PAPER_STOP_LOSS_PERCENT": 0.35,
            "PAPER_MAX_HOLD_MINUTES": 15,
            "PAPER_MOMENTUM_MODE_ENABLED": False,
            "PAPER_MAX_OPEN_POSITIONS": 5,
            "PAPER_MAX_TRADES_PER_DAY": 100,
            "PAPER_MIN_VOLUME_RATIO": 0.8,
            "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
            "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
            "PAPER_POSITION_SIZE_PERCENT": 25.0,
            "PAPER_DAILY_MAX_LOSS_ENABLED": False,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
            "MARKET_REGIME_ENABLED": False,
            "PAPER_MAX_SYMBOLS_PER_TICK": 50,
        }.get(k)

    with (
        patch("paper.simulator.get_active_paper_universe", new=AsyncMock(return_value={
            "active_symbols": ["AMD"],
            "active_count": 1,
            "last_refreshed_at": None,
            "refresh_reason": "test",
            "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
        })),
        patch("paper.simulator._cfg", side_effect=_cfg_disabled),
        patch("paper.runtime_config.get_runtime_status",
              return_value={"overrides_active": False, "override_count": 0,
                            "persistent": False, "warnings": []}),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.simulator.evaluate_market_quality", return_value=good_q),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.simulator._persist_journal_tick",
              new=AsyncMock(return_value={"ok": True})),
        patch("paper.risk.daily_loss_guard_triggered",
              return_value={"triggered": False, "reason": None, "enabled": False}),
        # Adapter must NOT be called when cache is disabled
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock()) as mock_adapter,
    ):
        result = await sim.run_tick()

    assert mock_adapter.call_count == 0, "Adapter must not be called when cache disabled"
    candidates = result.get("candidates", [])
    amd = next((c for c in candidates if c.get("symbol") == "AMD"), None)
    assert amd is not None
    assert amd.get("marketdata_source") == "polygon_direct"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Simulator: fresh cache hit → Polygon NOT called
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_cache_hit_skips_polygon():
    """Fresh cache hit in simulator → Polygon never called for that symbol."""
    import paper.simulator as sim

    good_q = dict(_MOCK_QUALITY)
    good_meta = {
        "marketdata_source": "cache",
        "marketdata_age_seconds": 5.0,
        "marketdata_fetched_at": datetime.now(timezone.utc).isoformat(),
        "marketdata_stale": False,
    }

    def _cfg_enabled(k):
        return {
            "PAPER_USE_MARKETDATA_CACHE": True,
            "PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS": 30,
            "PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED": True,
            "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY": True,
            "PAPER_ENTRY_SCORE_THRESHOLD": 70,
            "PAPER_TAKE_PROFIT_PERCENT": 0.6,
            "PAPER_STOP_LOSS_PERCENT": 0.35,
            "PAPER_MAX_HOLD_MINUTES": 15,
            "PAPER_MOMENTUM_MODE_ENABLED": False,
            "PAPER_MAX_OPEN_POSITIONS": 5,
            "PAPER_MAX_TRADES_PER_DAY": 100,
            "PAPER_MIN_VOLUME_RATIO": 0.8,
            "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
            "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
            "PAPER_POSITION_SIZE_PERCENT": 25.0,
            "PAPER_DAILY_MAX_LOSS_ENABLED": False,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
            "MARKET_REGIME_ENABLED": False,
            "PAPER_MAX_SYMBOLS_PER_TICK": 50,
        }.get(k)

    with (
        patch("paper.simulator.get_active_paper_universe", new=AsyncMock(return_value={
            "active_symbols": ["AMD"],
            "active_count": 1,
            "last_refreshed_at": None,
            "refresh_reason": "test",
            "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
        })),
        patch("paper.runtime_config.effective_value", side_effect=_cfg_enabled),
        patch("paper.runtime_config.get_runtime_status",
              return_value={"overrides_active": False, "override_count": 0,
                            "persistent": False, "warnings": []}),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(good_q, good_meta))),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock()) as mock_snap,
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock()) as mock_prev,
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.simulator._persist_journal_tick",
              new=AsyncMock(return_value={"ok": True})),
        patch("paper.risk.daily_loss_guard_triggered",
              return_value={"triggered": False, "reason": None, "enabled": False}),
    ):
        result = await sim.run_tick()

    assert mock_snap.call_count == 0, "Polygon must not be called on cache hit"
    assert mock_prev.call_count == 0
    assert result["marketdata_cache_hits"] == 1
    assert result["marketdata_cache_misses"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. _build_quality_from_payload produces correct quality dict shape
# ─────────────────────────────────────────────────────────────────────────────

def test_build_quality_from_payload_tradable():
    """_build_quality_from_payload returns correct shape for a fully-loaded payload."""
    from paper.marketdata_adapter import _build_quality_from_payload

    payload = _fresh_payload("AMD")
    q = _build_quality_from_payload("AMD", payload)

    assert q["symbol"] == "AMD"
    assert q["bid"] == 150.40
    assert q["ask"] == 150.60
    assert q["last_trade_price"] == 150.50
    assert q["day_volume"] == 2_000_000.0
    assert q["previous_day_volume"] == 1_500_000.0
    assert q["change_percent"] == 1.5
    assert q["spread_percent"] == 0.13
    assert q["has_valid_quote"] is True
    assert q["has_valid_trade"] is True
    assert q["has_sufficient_volume"] is True
    assert q["has_acceptable_spread"] is True
    assert q["tradable"] is True
    assert q["rejection_reasons"] == []
    assert q["volume_ratio"] == pytest.approx(2_000_000 / 1_500_000, rel=1e-3)


def test_build_quality_from_payload_missing_prev_day_volume():
    """Without prev_day_volume, has_sufficient_volume is False → not tradable."""
    from paper.marketdata_adapter import _build_quality_from_payload

    payload = _fresh_payload("AMD")
    payload["prev_day_volume"] = None
    q = _build_quality_from_payload("AMD", payload)

    assert q["has_sufficient_volume"] is False
    assert q["tradable"] is False
    assert any("previous day volume" in r for r in q["rejection_reasons"])


def test_build_quality_from_payload_bad_spread():
    """Wide spread → has_acceptable_spread=False → not tradable."""
    from paper.marketdata_adapter import _build_quality_from_payload

    payload = _fresh_payload("AMD")
    payload["spread_percent"] = 0.60  # > 0.50 limit
    q = _build_quality_from_payload("AMD", payload)

    assert q["has_acceptable_spread"] is False
    assert q["tradable"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 9. Tick result includes cache counter fields
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_result_includes_cache_counters():
    """
    run_tick() result dict must include marketdata_cache_hits/misses/fallbacks.
    Both symbols served from fresh cache → hits == 2, misses == 0.
    """
    import paper.simulator as sim

    fresh_q = dict(_MOCK_QUALITY)
    fresh_meta = {
        "marketdata_source": "cache",
        "marketdata_age_seconds": 5.0,
        "marketdata_fetched_at": datetime.now(timezone.utc).isoformat(),
        "marketdata_stale": False,
    }

    with (
        patch("paper.simulator.get_active_paper_universe", new=AsyncMock(return_value={
            "active_symbols": ["AMD", "NVDA"],
            "active_count": 2,
            "last_refreshed_at": None,
            "refresh_reason": "test",
            "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
        })),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(fresh_q, fresh_meta))),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick",
              new=AsyncMock(return_value={"ok": True, "skipped": False})),
        patch("paper.simulator._save_state", new=AsyncMock()),
    ):
        result = await sim.run_tick()

    assert "marketdata_cache_hits" in result
    assert "marketdata_cache_misses" in result
    assert "marketdata_cache_fallbacks" in result
    assert result["marketdata_cache_hits"] == 2
    assert result["marketdata_cache_misses"] == 0
    assert result["marketdata_cache_fallbacks"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 10. Config defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_config_new_settings_defaults():
    """All 4 D2 settings exist with correct defaults."""
    from core.config import Settings

    s = Settings()
    assert s.PAPER_USE_MARKETDATA_CACHE is True
    assert s.PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS == 30
    assert s.PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED is True
    assert s.PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY is True


def test_runtime_config_schema_has_d2_fields():
    """All 4 D2 fields are present in the runtime config schema with category marketdata."""
    from paper.runtime_config import _SCHEMA

    for field in (
        "PAPER_USE_MARKETDATA_CACHE",
        "PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS",
        "PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED",
        "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY",
    ):
        assert field in _SCHEMA, f"Missing schema entry: {field}"
        assert _SCHEMA[field]["category"] == "marketdata"


# ─────────────────────────────────────────────────────────────────────────────
# 11. require_fresh_for_entry blocks stale entries
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_require_fresh_for_entry_blocks_stale_entries():
    """
    REQUIRE_FRESH_FOR_ENTRY=True + stale data → candidate hard_rejection set,
    no entry taken even when quality would otherwise pass.
    """
    import paper.simulator as sim

    # Adapter signals fallback (stale), then Polygon quality passes all gates
    stale_q = dict(_MOCK_QUALITY)
    stale_meta = {
        "marketdata_source": "polygon_fallback",
        "marketdata_age_seconds": 45.0,
        "marketdata_fetched_at": (
            datetime.now(timezone.utc) - timedelta(seconds=45)
        ).isoformat(),
        "marketdata_stale": True,
    }

    def _cfg_side_effect(k):
        return {
            "PAPER_USE_MARKETDATA_CACHE": True,
            "PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS": 30,
            "PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED": True,
            "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY": True,
            "PAPER_ENTRY_SCORE_THRESHOLD": 70,
            "PAPER_TAKE_PROFIT_PERCENT": 0.6,
            "PAPER_STOP_LOSS_PERCENT": 0.35,
            "PAPER_MAX_HOLD_MINUTES": 15,
            "PAPER_MOMENTUM_MODE_ENABLED": False,
            "PAPER_MAX_OPEN_POSITIONS": 5,
            "PAPER_MAX_TRADES_PER_DAY": 100,
            "PAPER_MIN_VOLUME_RATIO": 0.8,
            "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
            "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
            "PAPER_POSITION_SIZE_PERCENT": 25.0,
            "PAPER_DAILY_MAX_LOSS_ENABLED": False,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
            "MARKET_REGIME_ENABLED": False,
            "PAPER_MAX_SYMBOLS_PER_TICK": 50,
        }.get(k)

    mock_scoring = {
        "total_score": 80,
        "score_threshold": 70,
        "score_pass": True,
        "components": {},
        "positive_reasons": ["catalyst"],
        "negative_reasons": [],
        "decision_reason": "score_pass",
        "catalyst_sentiment": "bullish",
        "catalyst_sentiment_score": 0.8,
        "catalyst_materiality_score": 0.7,
        "catalyst_sentiment_reasons": [],
        "bullish_flags": [],
        "bearish_flags": [],
        "strongest_catalyst_title": None,
        "strongest_catalyst_sentiment": None,
    }

    mock_catalyst = [{
        "symbol": "AMD",
        "classified_event_type": "earnings",
        "sentiment": "bullish",
    }]

    with (
        patch("paper.simulator.get_active_paper_universe", new=AsyncMock(return_value={
            "active_symbols": ["AMD"],
            "active_count": 1,
            "last_refreshed_at": None,
            "refresh_reason": "test",
            "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
        })),
        # Adapter returns stale signal → simulator falls through to Polygon
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, {
                  "marketdata_source": "stale",
                  "marketdata_age_seconds": 45.0,
                  "marketdata_fetched_at": None,
                  "marketdata_stale": True,
              }))),
        # Polygon then returns good quality
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.simulator.evaluate_market_quality", return_value=stale_q),
        patch("paper.simulator.collect_news_for_symbols", new=AsyncMock(
            return_value={"filter": {"accepted": mock_catalyst}}
        )),
        patch("paper.scoring.score_candidate", return_value=mock_scoring),
        patch("paper.runtime_config.effective_value", side_effect=_cfg_side_effect),
        patch("paper.runtime_config.get_runtime_status",
              return_value={"overrides_active": False, "override_count": 0,
                            "persistent": False, "warnings": []}),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick",
              new=AsyncMock(return_value={"ok": True, "skipped": False})),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered",
              return_value={"triggered": False, "reason": None, "enabled": False}),
    ):
        result = await sim.run_tick()

    candidates = result.get("candidates", [])
    amd_candidates = [c for c in candidates if c.get("symbol") == "AMD"]
    assert amd_candidates, "AMD should appear as a candidate"
    c = amd_candidates[0]
    assert c.get("rejection_reason") == "stale_marketdata_entry_blocked", (
        f"Expected stale_marketdata_entry_blocked, got {c.get('rejection_reason')}"
    )
    assert c.get("eligible") is False
    assert c.get("marketdata_stale") is True
    assert result["entries_made"] == 0
