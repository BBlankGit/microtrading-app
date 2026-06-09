"""
Phase 2O-Lite tests — Runtime-configurable minimum volume ratio hard gate.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All simulation is fake-money research only.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND_ROOT = Path(__file__).parent.parent

FORBIDDEN_MODULES = {
    "openai", "anthropic", "langchain", "ollama", "broker", "alpaca", "ibapi",
    "tastytrade", "td_ameritrade", "schwab",
}
FORBIDDEN_EXECUTION = {"place_order", "submit_order", "execute_order", "send_order"}


def _ast_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


# ── 1. Config has PAPER_MIN_VOLUME_RATIO with default 0.8 ────────────────────

def test_config_has_paper_min_volume_ratio():
    from core.config import settings
    assert hasattr(settings, "PAPER_MIN_VOLUME_RATIO"), \
        "Settings must have PAPER_MIN_VOLUME_RATIO"
    assert settings.PAPER_MIN_VOLUME_RATIO == 0.8, \
        f"Default must be 0.8, got {settings.PAPER_MIN_VOLUME_RATIO}"


def test_runtime_schema_has_paper_min_volume_ratio():
    from paper.runtime_config import _SCHEMA
    assert "PAPER_MIN_VOLUME_RATIO" in _SCHEMA, \
        "Runtime schema must include PAPER_MIN_VOLUME_RATIO"
    spec = _SCHEMA["PAPER_MIN_VOLUME_RATIO"]
    assert spec["type"] == "float"
    assert spec["min"] == 0.0
    assert spec["max"] == 5.0
    assert spec["category"] == "quality"
    assert spec["runtime_applied"] is True
    assert spec["restart_required"] is False


def test_effective_value_returns_default():
    from paper.runtime_config import effective_value, _runtime_overrides
    old = dict(_runtime_overrides)
    _runtime_overrides.clear()
    try:
        val = effective_value("PAPER_MIN_VOLUME_RATIO")
        assert val == 0.8, f"Effective value must default to 0.8, got {val}"
    finally:
        _runtime_overrides.clear()
        _runtime_overrides.update(old)


# ── 2. Default 0.8 still rejects low volume ───────────────────────────────────

def test_default_rejects_volume_ratio_below_0_8():
    """With default config, volume_ratio=0.5 must be hard-rejected."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    acc = PaperAccount(1000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 0.5,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }
    catalyst = [{
        "symbol": "AAPL", "classified_event_type": "earnings",
        "sentiment": "bullish", "materiality_score": 0.9, "title": "Record earnings",
    }]

    rc._runtime_overrides.update({
        "PAPER_MIN_VOLUME_RATIO": 0.8,
        "PAPER_DAILY_MAX_LOSS_ENABLED": False,
        "PAPER_MOMENTUM_MODE_ENABLED": False,
        "PAPER_ENTRY_SCORE_THRESHOLD": 70,
        "PAPER_TAKE_PROFIT_PERCENT": 0.60,
        "PAPER_STOP_LOSS_PERCENT": 0.35,
        "PAPER_MAX_HOLD_MINUTES": 15,
        "PAPER_MAX_OPEN_POSITIONS": 5,
        "PAPER_MAX_TRADES_PER_DAY": 100,
        "PAPER_POSITION_SIZE_PERCENT": 25.0,
        "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
        "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
        "MARKET_REGIME_ENABLED": False,
    })

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={
                      "active_symbols": ["AAPL"], "active_count": 1,
                      "last_refreshed_at": None, "refresh_reason": "test",
                      "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
                  }),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": catalyst}}),
            patch("paper.simulator.score_candidate", return_value={
                "total_score": 90, "score_threshold": 70, "score_pass": True,
                "components": {}, "positive_reasons": [], "negative_reasons": [],
                "decision_reason": "pass", "catalyst_sentiment": "bullish",
                "catalyst_sentiment_score": 0.9, "catalyst_materiality_score": 0.9,
                "catalyst_sentiment_reasons": [], "bullish_flags": [], "bearish_flags": [],
                "strongest_catalyst_title": "test", "strongest_catalyst_sentiment": "bullish",
            }),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    tick = result.get("tick", result)
    assert tick["entries_made"] == 0, "Default 0.8 gate must reject volume_ratio=0.5"
    cands = tick.get("candidates", [])
    aapl = next((c for c in cands if c["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["eligible"] is False
    assert "volume_ratio" in aapl["rejection_reason"]
    assert "0.8" in aapl["rejection_reason"]


# ── 3. Override to 0.1 allows candidate with volume_ratio=0.108 ──────────────

def test_override_to_0_1_allows_low_volume_candidate():
    """PAPER_MIN_VOLUME_RATIO=0.1 must allow a candidate with volume_ratio=0.108."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    acc = PaperAccount(1000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 0.108,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }
    catalyst = [{
        "symbol": "AAPL", "classified_event_type": "earnings",
        "sentiment": "bullish", "materiality_score": 0.9, "title": "Record earnings",
    }]

    rc._runtime_overrides.update({
        "PAPER_MIN_VOLUME_RATIO": 0.1,
        "PAPER_DAILY_MAX_LOSS_ENABLED": False,
        "PAPER_MOMENTUM_MODE_ENABLED": False,
        "PAPER_ENTRY_SCORE_THRESHOLD": 70,
        "PAPER_TAKE_PROFIT_PERCENT": 0.60,
        "PAPER_STOP_LOSS_PERCENT": 0.35,
        "PAPER_MAX_HOLD_MINUTES": 15,
        "PAPER_MAX_OPEN_POSITIONS": 5,
        "PAPER_MAX_TRADES_PER_DAY": 100,
        "PAPER_POSITION_SIZE_PERCENT": 25.0,
        "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
        "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
        "MARKET_REGIME_ENABLED": False,
    })

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={
                      "active_symbols": ["AAPL"], "active_count": 1,
                      "last_refreshed_at": None, "refresh_reason": "test",
                      "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
                  }),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": catalyst}}),
            patch("paper.simulator.score_candidate", return_value={
                "total_score": 90, "score_threshold": 70, "score_pass": True,
                "components": {}, "positive_reasons": [], "negative_reasons": [],
                "decision_reason": "pass", "catalyst_sentiment": "bullish",
                "catalyst_sentiment_score": 0.9, "catalyst_materiality_score": 0.9,
                "catalyst_sentiment_reasons": [], "bullish_flags": [], "bearish_flags": [],
                "strongest_catalyst_title": "test", "strongest_catalyst_sentiment": "bullish",
            }),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    tick = result.get("tick", result)
    assert tick["entries_made"] == 1, \
        f"PAPER_MIN_VOLUME_RATIO=0.1 must allow volume_ratio=0.108; entries_made={tick['entries_made']}"
    cands = tick.get("candidates", [])
    aapl = next((c for c in cands if c["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["eligible"] is True
    assert aapl["action"] in ("buy", "entered")


# ── 4. Rejection reason includes configured threshold ─────────────────────────

def test_rejection_reason_shows_configured_threshold():
    """Rejection reason must show the runtime-configured threshold, not hardcoded 0.8."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    acc = PaperAccount(1000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 0.12,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }
    catalyst = [{
        "symbol": "AAPL", "classified_event_type": "earnings",
        "sentiment": "bullish", "materiality_score": 0.9, "title": "Record earnings",
    }]

    rc._runtime_overrides.update({
        "PAPER_MIN_VOLUME_RATIO": 0.15,
        "PAPER_DAILY_MAX_LOSS_ENABLED": False,
        "PAPER_MOMENTUM_MODE_ENABLED": False,
        "PAPER_ENTRY_SCORE_THRESHOLD": 70,
        "PAPER_TAKE_PROFIT_PERCENT": 0.60,
        "PAPER_STOP_LOSS_PERCENT": 0.35,
        "PAPER_MAX_HOLD_MINUTES": 15,
        "PAPER_MAX_OPEN_POSITIONS": 5,
        "PAPER_MAX_TRADES_PER_DAY": 100,
        "PAPER_POSITION_SIZE_PERCENT": 25.0,
        "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
        "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
        "MARKET_REGIME_ENABLED": False,
    })

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={
                      "active_symbols": ["AAPL"], "active_count": 1,
                      "last_refreshed_at": None, "refresh_reason": "test",
                      "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
                  }),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": catalyst}}),
            patch("paper.simulator.score_candidate", return_value={
                "total_score": 90, "score_threshold": 70, "score_pass": True,
                "components": {}, "positive_reasons": [], "negative_reasons": [],
                "decision_reason": "pass", "catalyst_sentiment": "bullish",
                "catalyst_sentiment_score": 0.9, "catalyst_materiality_score": 0.9,
                "catalyst_sentiment_reasons": [], "bullish_flags": [], "bearish_flags": [],
                "strongest_catalyst_title": "test", "strongest_catalyst_sentiment": "bullish",
            }),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    tick = result.get("tick", result)
    cands = tick.get("candidates", [])
    aapl = next((c for c in cands if c["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["eligible"] is False
    reason = aapl["rejection_reason"]
    assert "0.15" in reason, \
        f"Rejection reason must show configured threshold 0.15, got: {reason!r}"
    assert "0.12" in reason, \
        f"Rejection reason must show actual volume_ratio 0.12, got: {reason!r}"


# ── 5. Validation rejects out-of-range values ─────────────────────────────────

def test_validation_rejects_negative_volume_ratio():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_MIN_VOLUME_RATIO": -0.1})
    assert not ok
    assert any("PAPER_MIN_VOLUME_RATIO" in e for e in errors)


def test_validation_rejects_volume_ratio_above_max():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_MIN_VOLUME_RATIO": 6.0})
    assert not ok
    assert any("PAPER_MIN_VOLUME_RATIO" in e for e in errors)


def test_validation_accepts_zero():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_MIN_VOLUME_RATIO": 0.0})
    assert ok, f"0.0 must be valid: {errors}"


def test_validation_accepts_valid_values():
    from paper.runtime_config import validate_runtime_config
    for val in (0.0, 0.1, 0.15, 0.5, 0.8, 1.0, 2.0, 5.0):
        ok, errors = validate_runtime_config({"PAPER_MIN_VOLUME_RATIO": val})
        assert ok, f"{val} must be valid: {errors}"


# ── 6. Simulator uses _cfg, not hardcoded value ───────────────────────────────

def test_simulator_does_not_hardcode_0_8():
    path = BACKEND_ROOT / "paper" / "simulator.py"
    source = path.read_text()
    # The only acceptable occurrence of literal "< 0.8" is in a string/comment,
    # not as a comparison with a hardcoded float.
    import ast as _ast
    tree = _ast.parse(source)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, _ast.Lt) and isinstance(comp, _ast.Constant) and comp.value == 0.8:
                    # Check if this is the volume_ratio comparison — it should not be
                    raise AssertionError(
                        f"Hardcoded '< 0.8' comparison found in simulator.py at line {node.lineno}. "
                        "Must use _cfg('PAPER_MIN_VOLUME_RATIO') instead."
                    )


# ── 7. No forbidden imports in simulator or risk ──────────────────────────────

def test_no_forbidden_imports_in_simulator():
    imports = _ast_imports(BACKEND_ROOT / "paper" / "simulator.py")
    for mod in FORBIDDEN_MODULES:
        assert not any(mod in i for i in imports), \
            f"Forbidden module {mod!r} found in simulator.py imports"


def test_no_broker_execution_in_simulator():
    source = (BACKEND_ROOT / "paper" / "simulator.py").read_text()
    for fn in FORBIDDEN_EXECUTION:
        assert fn not in source, f"Forbidden execution call {fn!r} found in simulator.py"


# ── 8. Runtime config API includes PAPER_MIN_VOLUME_RATIO ────────────────────

def test_runtime_config_api_returns_paper_min_volume_ratio():
    import sys
    sys.path.insert(0, str(BACKEND_ROOT))
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/config/runtime")
    assert resp.status_code == 200
    data = resp.json()
    eff = data.get("effective_config", data)
    assert "PAPER_MIN_VOLUME_RATIO" in eff, \
        "Effective config must include PAPER_MIN_VOLUME_RATIO"
    assert eff["PAPER_MIN_VOLUME_RATIO"] == 0.8
