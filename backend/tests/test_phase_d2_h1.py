"""
Phase D2-H1 additional tests.
Cache-first simulator integration — new fields, granular counters,
intrabar safety, monitoring endpoint, safety invariants.

No broker. No live trading. No real orders. No real-money execution.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (duplicated from test_phase_d2.py to keep files independent)
# ─────────────────────────────────────────────────────────────────────────────

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

_FULL_CFG = {
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
}

_UNIVERSE_AMD = {
    "active_symbols": ["AMD"],
    "active_count": 1,
    "last_refreshed_at": None,
    "refresh_reason": "test",
    "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
}

_JOURNAL_OK = {"ok": True, "skipped": False}
_GUARD_OFF = {"triggered": False, "reason": None, "enabled": False}
_RC_STATUS = {"overrides_active": False, "override_count": 0, "persistent": False, "warnings": []}


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-1: Cache miss + fallback enabled → Polygon called, source=polygon_fallback
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_cache_miss_fallback_calls_polygon():
    """Cache miss + fallback enabled → Polygon called; marketdata_fallback_used=True."""
    import paper.simulator as sim

    miss_meta = {
        "marketdata_source": "missing",
        "marketdata_age_seconds": None,
        "marketdata_fetched_at": None,
        "marketdata_stale": True,
    }

    with (
        patch("paper.simulator.get_active_paper_universe",
              new=AsyncMock(return_value=_UNIVERSE_AMD)),
        patch("paper.simulator._cfg", side_effect=_FULL_CFG.get),
        patch("paper.runtime_config.get_runtime_status", return_value=_RC_STATUS),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, miss_meta))),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})) as mock_snap,
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})) as mock_prev,
        patch("paper.simulator.evaluate_market_quality", return_value=dict(_MOCK_QUALITY)),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick", new=AsyncMock(return_value=_JOURNAL_OK)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered", return_value=_GUARD_OFF),
    ):
        result = await sim.run_tick()

    assert mock_snap.call_count == 1, "Polygon snapshot must be called on cache miss+fallback"
    assert mock_prev.call_count == 1
    md = result.get("marketdata", {})
    assert md.get("cache_misses_last_tick") == 1
    assert md.get("polygon_fallbacks_last_tick") == 1
    assert md.get("cache_hits_last_tick") == 0
    candidates = result.get("candidates", [])
    amd = next((c for c in candidates if c.get("symbol") == "AMD"), None)
    if amd:
        assert amd.get("marketdata_source") == "polygon_fallback"
        assert amd.get("marketdata_fallback_used") is True
        assert amd.get("marketdata_stale") is False  # Polygon gave fresh data on a miss


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-2: Cache stale + fallback enabled → stale counter increments
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_cache_stale_fallback_increments_stale_counter():
    """Stale cache + fallback enabled → cache_stale_last_tick increments."""
    import paper.simulator as sim

    stale_meta = {
        "marketdata_source": "stale",
        "marketdata_age_seconds": 45.0,
        "marketdata_fetched_at": (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat(),
        "marketdata_stale": True,
    }

    with (
        patch("paper.simulator.get_active_paper_universe",
              new=AsyncMock(return_value=_UNIVERSE_AMD)),
        patch("paper.simulator._cfg", side_effect=_FULL_CFG.get),
        patch("paper.runtime_config.get_runtime_status", return_value=_RC_STATUS),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, stale_meta))),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.simulator.evaluate_market_quality", return_value=dict(_MOCK_QUALITY)),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick", new=AsyncMock(return_value=_JOURNAL_OK)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered", return_value=_GUARD_OFF),
    ):
        result = await sim.run_tick()

    md = result.get("marketdata", {})
    assert md.get("cache_stale_last_tick") == 1, md
    assert md.get("polygon_fallbacks_last_tick") == 1


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-3: No-fallback path → missing_marketdata_last_tick increments
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_no_fallback_missing_counter_increments():
    """miss_no_fallback path → missing_marketdata_last_tick == 1, no quality produced."""
    import paper.simulator as sim

    no_fallback_meta = {
        "marketdata_source": "missing_no_fallback",
        "marketdata_age_seconds": None,
        "marketdata_fetched_at": None,
        "marketdata_stale": True,
    }

    cfg_no_fallback = dict(_FULL_CFG, PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED=False)

    with (
        patch("paper.simulator.get_active_paper_universe",
              new=AsyncMock(return_value=_UNIVERSE_AMD)),
        patch("paper.simulator._cfg", side_effect=cfg_no_fallback.get),
        patch("paper.runtime_config.get_runtime_status", return_value=_RC_STATUS),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, no_fallback_meta))),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock()) as mock_snap,
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick", new=AsyncMock(return_value=_JOURNAL_OK)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered", return_value=_GUARD_OFF),
    ):
        result = await sim.run_tick()

    assert mock_snap.call_count == 0, "Polygon must NOT be called on no-fallback path"
    md = result.get("marketdata", {})
    assert md.get("missing_marketdata_last_tick") == 1, md
    assert md.get("polygon_fallbacks_last_tick") == 0
    assert result["symbols_evaluated"] == 0, "Symbol with no quality must be excluded"


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-4: polygon_direct counter when cache disabled
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_polygon_direct_counter_when_cache_disabled():
    """When PAPER_USE_MARKETDATA_CACHE=False → polygon_direct_last_tick increments."""
    import paper.simulator as sim

    cfg_disabled = dict(_FULL_CFG, PAPER_USE_MARKETDATA_CACHE=False)

    with (
        patch("paper.simulator.get_active_paper_universe",
              new=AsyncMock(return_value=_UNIVERSE_AMD)),
        patch("paper.simulator._cfg", side_effect=cfg_disabled.get),
        patch("paper.runtime_config.get_runtime_status", return_value=_RC_STATUS),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.simulator.evaluate_market_quality", return_value=dict(_MOCK_QUALITY)),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick", new=AsyncMock(return_value=_JOURNAL_OK)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered", return_value=_GUARD_OFF),
    ):
        result = await sim.run_tick()

    md = result.get("marketdata", {})
    assert md.get("polygon_direct_last_tick") == 1, md
    assert md.get("cache_hits_last_tick") == 0
    assert md.get("polygon_fallbacks_last_tick") == 0


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-5: candidate has marketdata_fallback_used and marketdata_error fields
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_candidate_has_fallback_used_and_error_fields():
    """Candidates must include marketdata_fallback_used and marketdata_error."""
    import paper.simulator as sim

    fresh_meta = {
        "marketdata_source": "cache",
        "marketdata_age_seconds": 5.0,
        "marketdata_fetched_at": datetime.now(timezone.utc).isoformat(),
        "marketdata_stale": False,
    }

    with (
        patch("paper.simulator.get_active_paper_universe",
              new=AsyncMock(return_value=_UNIVERSE_AMD)),
        patch("paper.simulator._cfg", side_effect=_FULL_CFG.get),
        patch("paper.runtime_config.get_runtime_status", return_value=_RC_STATUS),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(dict(_MOCK_QUALITY), fresh_meta))),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick", new=AsyncMock(return_value=_JOURNAL_OK)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered", return_value=_GUARD_OFF),
    ):
        result = await sim.run_tick()

    candidates = result.get("candidates", [])
    assert candidates, "Must produce at least one candidate"
    c = candidates[0]
    assert "marketdata_fallback_used" in c, "D2-H1: marketdata_fallback_used must be in candidate"
    assert "marketdata_error" in c, "D2-H1: marketdata_error must be in candidate"
    assert c["marketdata_fallback_used"] is False  # fresh cache hit, no fallback
    assert c["marketdata_error"] is None


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-6: Monitoring endpoint includes last_tick_stats
# ─────────────────────────────────────────────────────────────────────────────

def test_monitoring_status_includes_last_tick_stats():
    """GET /api/monitoring/status → marketdata_cache.last_tick_stats is present."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200
    data = resp.json()
    mc = data.get("marketdata_cache", {})
    assert "last_tick_stats" in mc, (
        f"D2-H1: last_tick_stats must be in marketdata_cache; got keys: {list(mc.keys())}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-7: last_tick_marketdata persisted to get_status()
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_status_exposes_last_tick_marketdata():
    """get_status()['last_tick_marketdata'] is populated after run_tick()."""
    import paper.simulator as sim

    fresh_meta = {
        "marketdata_source": "cache",
        "marketdata_age_seconds": 8.0,
        "marketdata_fetched_at": datetime.now(timezone.utc).isoformat(),
        "marketdata_stale": False,
    }

    with (
        patch("paper.simulator.get_active_paper_universe",
              new=AsyncMock(return_value=_UNIVERSE_AMD)),
        patch("paper.simulator._cfg", side_effect=_FULL_CFG.get),
        patch("paper.runtime_config.get_runtime_status", return_value=_RC_STATUS),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(dict(_MOCK_QUALITY), fresh_meta))),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.simulator._persist_journal_tick", new=AsyncMock(return_value=_JOURNAL_OK)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered", return_value=_GUARD_OFF),
    ):
        await sim.run_tick()

    status = sim.get_status()
    ltm = status.get("last_tick_marketdata", {})
    assert "cache_hits_last_tick" in ltm, f"D2-H1: expected last_tick_marketdata in status; got {ltm}"
    assert ltm["cache_hits_last_tick"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-8: Intrabar exits: no aggregate calls for non-open-position candidates
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intrabar_exits_aggregate_calls_limited_to_open_positions():
    """
    get_intrabar_data must only be called for symbols with open positions.
    Non-open-position candidate symbols must not trigger aggregate calls.
    """
    import paper.simulator as sim
    import paper.account as _acct_mod

    # Use a universe with multiple symbols but no open positions
    universe = {
        "active_symbols": ["AMD", "TSLA", "NVDA"],
        "active_count": 3,
        "last_refreshed_at": None,
        "refresh_reason": "test",
        "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
    }
    fresh_meta = {
        "marketdata_source": "cache",
        "marketdata_age_seconds": 5.0,
        "marketdata_fetched_at": datetime.now(timezone.utc).isoformat(),
        "marketdata_stale": False,
    }

    intrabar_call_symbols: list[str] = []

    async def _fake_intrabar(sym, *args, **kwargs):
        intrabar_call_symbols.append(sym)
        return None

    with (
        patch("paper.simulator.get_active_paper_universe",
              new=AsyncMock(return_value=universe)),
        patch("paper.simulator._cfg", side_effect=_FULL_CFG.get),
        patch("paper.runtime_config.get_runtime_status", return_value=_RC_STATUS),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(dict(_MOCK_QUALITY), fresh_meta))),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.get_intrabar_data", side_effect=_fake_intrabar),
        patch("paper.simulator._persist_journal_tick", new=AsyncMock(return_value=_JOURNAL_OK)),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.risk.daily_loss_guard_triggered", return_value=_GUARD_OFF),
    ):
        result = await sim.run_tick()

    # Intrabar called only for symbols with open positions (none here → 0 calls)
    assert len(intrabar_call_symbols) == 0, (
        f"D2-H1: get_intrabar_data must not be called for candidates without open positions; "
        f"called for: {intrabar_call_symbols}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-9: Cache fresh but insufficient fields → fallback or clean reject, no crash
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_fresh_insufficient_fields_no_crash():
    """
    Fresh cache hit with missing critical fields (bid=None, ask=None) must not crash.
    The quality dict should have tradable=False → hard rejection, no entry.
    """
    from paper.marketdata_adapter import _build_quality_from_payload

    # Payload missing bid/ask — this is the "insufficient fields" case
    payload = {
        "symbol": "BAD",
        "source": "polygon",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw_status": "ok",
        "last_price": None,
        "bid": None,
        "ask": None,
        "spread_percent": None,
        "day_volume": None,
        "prev_day_volume": None,
        "volume_ratio": None,
        "change_percent": None,
        "prev_close": None,
        "minute_high": None,
        "minute_low": None,
        "minute_close": None,
        "error": None,
    }
    q = _build_quality_from_payload("BAD", payload)
    # Must return a dict (no crash), tradable=False
    assert isinstance(q, dict)
    assert q["tradable"] is False
    assert q["rejection_reasons"]  # at least one reason


# ─────────────────────────────────────────────────────────────────────────────
# D2-H1-10: Safety — no broker/live/AI/Ollama imports in cache path
# ─────────────────────────────────────────────────────────────────────────────

def test_d2h1_safety_no_broker_live_ai_imports():
    """
    paper/marketdata_adapter.py must not contain import statements for broker,
    live-trading, AI, or Ollama modules. Comments are excluded from the check.
    """
    import pathlib, ast
    src_path = pathlib.Path(__file__).parent.parent / "paper" / "marketdata_adapter.py"
    text = src_path.read_text()
    # Parse imports only (not comments or docstrings)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise AssertionError("marketdata_adapter.py has a syntax error")

    import_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                import_names.extend(alias.name for alias in node.names)
            else:
                if node.module:
                    import_names.append(node.module)

    forbidden_modules = ["broker", "live_trading", "real_order", "ollama",
                         "openai", "anthropic", "langchain", "alpaca", "tdameritrade"]
    lowered = [n.lower() for n in import_names]
    for word in forbidden_modules:
        for name in lowered:
            assert word not in name, (
                f"D2-H1: forbidden import '{word}' found in marketdata_adapter.py imports: {name}"
            )


def test_d2h1_safety_simulator_no_v5_v6_imports():
    """
    paper/simulator.py must not import V5 or V6 modules.
    (V5/V6 scanner files must be untouched.)
    """
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "paper" / "simulator.py"
    text = src.read_text()
    for forbidden in ["scanner_v5", "scanner_v6", "v5_scanner", "v6_scanner"]:
        assert forbidden not in text.lower(), (
            f"D2-H1: forbidden reference '{forbidden}' found in simulator.py"
        )
