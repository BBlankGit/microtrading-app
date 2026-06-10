"""
Phase I4-B-H1 — Injection-only symbols are cache-only during paper tick evaluation.
Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM/Ollama/OpenAI/Anthropic/LangChain.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Shared fixtures ───────────────────────────────────────────────────────────

def _quality(tradable: bool = True) -> dict:
    return {
        "tradable": tradable,
        "bid": 20.0, "ask": 20.02, "last_trade_price": 20.01,
        "spread_percent": 0.10, "change_percent": 5.0, "volume_ratio": 3.0,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }


def _cache_hit_meta() -> dict:
    return {
        "marketdata_source": "cache",
        "marketdata_age_seconds": 8,
        "marketdata_stale": False,
        "marketdata_fallback_used": False,
        "marketdata_error": None,
        "marketdata_fetched_at": None,
    }


def _cache_miss_meta() -> dict:
    return {
        "marketdata_source": "miss",
        "marketdata_age_seconds": None,
        "marketdata_stale": False,
        "marketdata_fallback_used": False,
        "marketdata_error": None,
        "marketdata_fetched_at": None,
    }


def _cache_stale_meta() -> dict:
    return {
        "marketdata_source": "stale",
        "marketdata_age_seconds": 120,
        "marketdata_stale": True,
        "marketdata_fallback_used": False,
        "marketdata_error": None,
        "marketdata_fetched_at": None,
    }


def _movers_snap(symbols: list[str] | None = None) -> dict:
    syms = symbols or ["CBRL"]
    return {
        "ok": True,
        "mode": "full_universe",
        "session": "premarket",
        "top_gainers": [
            {"symbol": s, "rank": i + 1, "gap_percent": 15.0 + i,
             "last_price": 20.0, "previous_close": 17.4,
             "day_volume": 500_000, "dollar_volume": 10_000_000,
             "source": "polygon_bulk_snapshot"}
            for i, s in enumerate(syms)
        ],
        "top_losers": [],
        "top_movers": [],
    }


def _base_universe(syms: list[str]) -> dict:
    return {
        "active_symbols": syms,
        "active_count": len(syms),
        "last_refreshed_at": None,
        "refresh_reason": "test",
        "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
    }


_STANDARD_OVERRIDES = {
    "PAPER_MARKET_MOVERS_CANDIDATES_ENABLED": True,
    "PAPER_MARKET_MOVERS_CANDIDATES_TOP_N": 50,
    "PAPER_MARKET_MOVERS_CANDIDATES_MIN_GAP_PERCENT": 2.0,
    "PAPER_MARKET_MOVERS_CANDIDATES_MAX_GAP_PERCENT": 40.0,
    "PAPER_MARKET_MOVERS_CANDIDATES_REQUIRE_FULL_UNIVERSE": True,
    "PAPER_ENTRY_SCORE_THRESHOLD": 70,
    "PAPER_TAKE_PROFIT_PERCENT": 0.60,
    "PAPER_STOP_LOSS_PERCENT": 0.35,
    "PAPER_MAX_HOLD_MINUTES": 15,
    "PAPER_MAX_OPEN_POSITIONS": 5,
    "PAPER_MAX_TRADES_PER_DAY": 100,
    "PAPER_MOMENTUM_MODE_ENABLED": False,
    "PAPER_NO_CATALYST_ENTRY_ENABLED": False,
    "PAPER_REJECT_STRONG_BEARISH_CATALYST": False,
    "PAPER_DAILY_MAX_LOSS_ENABLED": False,
    "MARKET_REGIME_ENABLED": False,
    "PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES": False,
    "PAPER_USE_MARKETDATA_CACHE": True,
    "PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED": True,
    "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY": False,
}


def _run_tick_with_mocks(
    *,
    base_symbols: list[str],
    movers_snap: dict,
    cache_response: dict[str, tuple],  # sym → (quality | None, meta)
    polygon_ticker_mock: AsyncMock | None = None,
    polygon_prev_mock: AsyncMock | None = None,
    extra_overrides: dict | None = None,
) -> dict:
    """
    Run run_tick() once with controlled per-symbol cache responses and optional
    Polygon mocks for tracing calls.  Returns the tick result dict.
    """
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account

    overrides = dict(_STANDARD_OVERRIDES)
    overrides.update(extra_overrides or {})
    rc._runtime_overrides.update(overrides)
    sim._account = PaperAccount(10_000.0)

    import intelligence.full_premarket as _fp
    _fp._snapshot = movers_snap
    _fp._fetched_at = time.time()

    async def _try_cache(sym):
        if sym in cache_response:
            return cache_response[sym]
        return (None, _cache_miss_meta())

    _poly_snap = polygon_ticker_mock or AsyncMock(return_value={})
    _poly_prev  = polygon_prev_mock  or AsyncMock(return_value={})

    try:
        with (
            patch("paper.simulator.get_active_paper_universe",
                  new=AsyncMock(return_value=_base_universe(base_symbols))),
            patch("paper.simulator.polygon_client.get_ticker_snapshot", new=_poly_snap),
            patch("paper.simulator.polygon_client.get_previous_close",  new=_poly_prev),
            patch("paper.simulator.evaluate_market_quality", return_value=_quality()),
            patch("paper.simulator.collect_news_for_symbols",
                  new=AsyncMock(return_value={"filter": {"accepted": []}})),
            patch("paper.simulator._persist_journal_tick",
                  new=AsyncMock(return_value={"ok": True})),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new=AsyncMock()),
            patch("paper.marketdata_adapter.try_cache_for_quality", side_effect=_try_cache),
        ):
            return asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides
        _fp._snapshot.clear()
        _fp._fetched_at = 0.0


# ── Test 1: Injection-only symbol with fresh cache is evaluated ───────────────

def test_injection_only_fresh_cache_is_evaluated():
    """An injected symbol that gets a fresh cache hit is fully evaluated."""
    result = _run_tick_with_mocks(
        base_symbols=["AAPL"],
        movers_snap=_movers_snap(["CBRL"]),
        cache_response={
            "AAPL": (_quality(), _cache_hit_meta()),
            "CBRL": (_quality(), _cache_hit_meta()),
        },
    )
    cands = result.get("candidates", [])
    cbrl_cands = [c for c in cands if c.get("symbol") == "CBRL"]
    assert len(cbrl_cands) == 1, "CBRL with fresh cache must appear as a candidate"
    assert "full_market_movers" in (cbrl_cands[0].get("candidate_sources") or [])


# ── Test 2: Injection-only with cache miss does not call Polygon ──────────────

def test_injection_only_cache_miss_no_polygon():
    """Injection-only symbol with cache miss must not trigger any Polygon call."""
    ticker_mock = AsyncMock(return_value={})
    prev_mock   = AsyncMock(return_value={})

    result = _run_tick_with_mocks(
        base_symbols=["AAPL"],
        movers_snap=_movers_snap(["CBRL"]),
        cache_response={
            "AAPL": (_quality(), _cache_hit_meta()),
            "CBRL": (None, _cache_miss_meta()),
        },
        polygon_ticker_mock=ticker_mock,
        polygon_prev_mock=prev_mock,
    )
    # Verify Polygon was never called for CBRL
    called_ticker_syms = [call.args[0] for call in ticker_mock.call_args_list]
    called_prev_syms   = [call.args[0] for call in prev_mock.call_args_list]
    assert "CBRL" not in called_ticker_syms, "get_ticker_snapshot must not be called for injection-only CBRL"
    assert "CBRL" not in called_prev_syms,   "get_previous_close must not be called for injection-only CBRL"

    # Error must be logged with the correct key
    errors = result.get("errors", [])
    assert any("missing_marketdata_for_injected_mover" in str(e.get("error", "")) for e in errors), \
        "result.errors must contain missing_marketdata_for_injected_mover"


# ── Test 3: Injection-only with stale cache does not call Polygon ─────────────

def test_injection_only_stale_cache_no_polygon():
    """Injection-only symbol with stale cache must not trigger any Polygon call."""
    ticker_mock = AsyncMock(return_value={})
    prev_mock   = AsyncMock(return_value={})

    result = _run_tick_with_mocks(
        base_symbols=["AAPL"],
        movers_snap=_movers_snap(["CBRL"]),
        cache_response={
            "AAPL": (_quality(), _cache_hit_meta()),
            "CBRL": (None, _cache_stale_meta()),
        },
        polygon_ticker_mock=ticker_mock,
        polygon_prev_mock=prev_mock,
    )
    called_ticker_syms = [call.args[0] for call in ticker_mock.call_args_list]
    called_prev_syms   = [call.args[0] for call in prev_mock.call_args_list]
    assert "CBRL" not in called_ticker_syms, "get_ticker_snapshot must not be called for stale injection-only CBRL"
    assert "CBRL" not in called_prev_syms,   "get_previous_close must not be called for stale injection-only CBRL"

    errors = result.get("errors", [])
    assert any("stale_marketdata_for_injected_mover" in str(e.get("error", "")) for e in errors), \
        "result.errors must contain stale_marketdata_for_injected_mover"


# ── Test 4: Symbol in base universe AND movers is not injection-only ──────────

def test_base_and_movers_symbol_not_injection_only():
    """A symbol already in the base universe is NOT injection-only even if it appears in movers."""
    ticker_mock = AsyncMock(return_value={})
    prev_mock   = AsyncMock(return_value={})

    # AAPL is in BOTH the base universe AND the movers snapshot → not injection-only
    result = _run_tick_with_mocks(
        base_symbols=["AAPL"],
        movers_snap=_movers_snap(["AAPL"]),
        cache_response={
            # AAPL gets a cache miss → should fall through to Polygon (normal path)
            "AAPL": (None, _cache_miss_meta()),
        },
        polygon_ticker_mock=ticker_mock,
        polygon_prev_mock=prev_mock,
        extra_overrides={"PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED": True},
    )
    # AAPL is NOT injection-only → Polygon path executed
    called_ticker_syms = [call.args[0] for call in ticker_mock.call_args_list]
    assert "AAPL" in called_ticker_syms, (
        "AAPL in base universe (not injection-only) must reach Polygon on cache miss"
    )

    # No stale/missing injected_mover error for AAPL
    errors = result.get("errors", [])
    assert not any("injected_mover" in str(e.get("error", "")) for e in errors)


# ── Test 5: End-to-end: injection-only cache miss — Polygon never called ─────

def test_e2e_injection_only_polygon_never_called():
    """
    Comprehensive end-to-end: CBRL is injection-only (not in base universe).
    With cache disabled (PAPER_USE_MARKETDATA_CACHE=False), CBRL must never
    reach Polygon; AAPL (base universe) follows the normal Polygon-direct path.
    """
    ticker_mock = AsyncMock(return_value={})
    prev_mock   = AsyncMock(return_value={})

    result = _run_tick_with_mocks(
        base_symbols=["AAPL"],
        movers_snap=_movers_snap(["CBRL"]),
        cache_response={},  # irrelevant — cache disabled
        polygon_ticker_mock=ticker_mock,
        polygon_prev_mock=prev_mock,
        extra_overrides={"PAPER_USE_MARKETDATA_CACHE": False},
    )
    called_ticker_syms = [call.args[0] for call in ticker_mock.call_args_list]
    called_prev_syms   = [call.args[0] for call in prev_mock.call_args_list]

    # CBRL must never appear in Polygon call args
    assert "CBRL" not in called_ticker_syms, "get_ticker_snapshot must not be called for injection-only CBRL"
    assert "CBRL" not in called_prev_syms,   "get_previous_close must not be called for injection-only CBRL"

    # AAPL (base universe, not injection-only) was attempted via Polygon
    assert "AAPL" in called_ticker_syms, "get_ticker_snapshot must still be called for base-universe AAPL"

    # Error logged for CBRL
    errors = result.get("errors", [])
    assert any("missing_marketdata_for_injected_mover" in str(e.get("error", "")) for e in errors)


# ── Test 6: candidate_sources includes full_market_movers ────────────────────

def test_candidate_sources_includes_full_market_movers():
    """When an injected symbol has fresh cache, candidate_sources still includes 'full_market_movers'."""
    result = _run_tick_with_mocks(
        base_symbols=["AAPL"],
        movers_snap=_movers_snap(["CBRL"]),
        cache_response={
            "AAPL": (_quality(), _cache_hit_meta()),
            "CBRL": (_quality(), _cache_hit_meta()),
        },
    )
    cands = result.get("candidates", [])
    cbrl = next((c for c in cands if c.get("symbol") == "CBRL"), None)
    assert cbrl is not None, "CBRL with fresh cache must appear as candidate"
    assert "full_market_movers" in (cbrl.get("candidate_sources") or [])
    assert cbrl.get("market_mover_rank") is not None
    assert cbrl.get("market_mover_gap_percent") == pytest.approx(15.0)


# ── Test 7: Existing gates still decide eligibility when fresh cache exists ───

def test_gates_decide_eligibility_fresh_cache():
    """Existing quality/catalyst/score gates still control eligibility for injected symbols."""
    q_not_tradable = _quality(tradable=False)
    q_not_tradable["rejection_reasons"] = ["not_tradable"]

    result = _run_tick_with_mocks(
        base_symbols=[],
        movers_snap=_movers_snap(["CBRL"]),
        cache_response={
            "CBRL": (q_not_tradable, _cache_hit_meta()),
        },
    )
    cands = result.get("candidates", [])
    cbrl = next((c for c in cands if c.get("symbol") == "CBRL"), None)
    # CBRL must appear as a candidate but be rejected via the hard gate
    assert cbrl is not None, "CBRL must appear in candidates even when rejected"
    assert cbrl.get("action") is None or cbrl.get("eligible") is False


# ── Test 8: Shadow score still does not control eligible/action/entry_mode ───

def test_shadow_score_does_not_control_entry_h1():
    """Shadow scoring output must never include eligible, action, or entry_mode."""
    from intelligence.shadow_scoring import compute_shadow_score

    result = compute_shadow_score(
        "CBRL",
        quality=_quality(),
        scoring={"total_score": 80, "score_pass": True, "catalyst_type": "earnings",
                 "catalyst_sentiment": "bullish", "catalyst_materiality_score": 0.7,
                 "components": {"momentum_score": 20}},
        tick_regime={"regime": "risk_on", "risk_on_score": 75},
        premarket_snap=_movers_snap(),
        reddit_snap=None,
    )
    for forbidden in ("eligible", "action", "entry_mode", "rejection_reason"):
        assert forbidden not in result, f"shadow result must not contain '{forbidden}'"


# ── Test 9: TP/SL/exit behavior unchanged ────────────────────────────────────

def test_no_tp_sl_exit_changes():
    """TP, SL, max_hold values are still read from runtime config, not hardcoded."""
    import paper.simulator as sim
    from paper import runtime_config as rc

    old = dict(rc._runtime_overrides)
    rc._runtime_overrides.update({
        "PAPER_TAKE_PROFIT_PERCENT": 1.25,
        "PAPER_STOP_LOSS_PERCENT": 0.75,
        "PAPER_MAX_HOLD_MINUTES": 30,
    })
    try:
        status = sim.get_status()
        assert status.get("take_profit_percent") == pytest.approx(1.25)
        assert status.get("stop_loss_percent") == pytest.approx(0.75)
        assert status.get("max_hold_minutes") == 30
    finally:
        rc._runtime_overrides = old


# ── Test 10: No forbidden imports in simulator ────────────────────────────────

def test_no_forbidden_imports_in_simulator_h1():
    """simulator.py must not import broker, live_trading, AI, or LLM libraries."""
    import ast
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "paper" / "simulator.py"
    tree = ast.parse(src.read_text())
    forbidden = {"broker", "live_trading", "openai", "anthropic", "ollama", "langchain"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = " ".join(a.name for a in node.names) if isinstance(node, ast.Import) else (node.module or "")
            for f in forbidden:
                assert f not in name.lower(), f"forbidden import '{f}' in simulator.py"
