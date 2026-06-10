"""
Phase 2N-Lite tests — Active microtrading limits and daily max loss guard.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All simulation is fake-money research only.
"""

import ast
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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


# ── Client fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ── 1. Defaults — increased limits ────────────────────────────────────────────

def test_default_max_positions_is_5():
    from core.config import settings
    assert settings.PAPER_MAX_POSITIONS == 5, \
        "PAPER_MAX_POSITIONS must default to 5 (Phase 2N-Lite)"


def test_default_max_trades_per_day_is_100():
    from core.config import settings
    assert settings.PAPER_MAX_TRADES_PER_DAY == 100, \
        "PAPER_MAX_TRADES_PER_DAY must default to 100 (Phase 2N-Lite)"


def test_default_momentum_max_trades_per_day_is_30():
    from core.config import settings
    assert settings.PAPER_MOMENTUM_MAX_TRADES_PER_DAY == 30, \
        "PAPER_MOMENTUM_MAX_TRADES_PER_DAY must default to 30 (Phase 2N-Lite)"


def test_default_daily_loss_guard_enabled():
    from core.config import settings
    assert settings.PAPER_DAILY_MAX_LOSS_ENABLED is True, \
        "PAPER_DAILY_MAX_LOSS_ENABLED must default to True"


def test_default_daily_loss_percent():
    from core.config import settings
    assert settings.PAPER_DAILY_MAX_LOSS_PERCENT == 2.0, \
        "PAPER_DAILY_MAX_LOSS_PERCENT must default to 2.0"


def test_default_daily_loss_usd_zero():
    from core.config import settings
    assert settings.PAPER_DAILY_MAX_LOSS_USD == 0.0, \
        "PAPER_DAILY_MAX_LOSS_USD must default to 0.0 (USD threshold disabled)"


# ── 2. Runtime config schema ──────────────────────────────────────────────────

def test_daily_loss_fields_in_schema():
    from paper.runtime_config import _SCHEMA
    expected = [
        "PAPER_DAILY_MAX_LOSS_ENABLED",
        "PAPER_DAILY_MAX_LOSS_PERCENT",
        "PAPER_DAILY_MAX_LOSS_USD",
    ]
    for f in expected:
        assert f in _SCHEMA, f"Field {f!r} missing from runtime config _SCHEMA"


def test_daily_loss_schema_types():
    from paper.runtime_config import _SCHEMA
    assert _SCHEMA["PAPER_DAILY_MAX_LOSS_ENABLED"]["type"] == "bool"
    assert _SCHEMA["PAPER_DAILY_MAX_LOSS_PERCENT"]["type"] == "float"
    assert _SCHEMA["PAPER_DAILY_MAX_LOSS_USD"]["type"] == "float"


def test_daily_loss_schema_bounds():
    from paper.runtime_config import _SCHEMA
    pct = _SCHEMA["PAPER_DAILY_MAX_LOSS_PERCENT"]
    assert pct["min"] == 0.1
    assert pct["max"] == 20.0
    usd = _SCHEMA["PAPER_DAILY_MAX_LOSS_USD"]
    assert usd["min"] == 0.0
    assert usd["max"] == 1_000_000.0


def test_daily_loss_schema_category_risk():
    from paper.runtime_config import _SCHEMA
    for key in ("PAPER_DAILY_MAX_LOSS_ENABLED", "PAPER_DAILY_MAX_LOSS_PERCENT", "PAPER_DAILY_MAX_LOSS_USD"):
        assert _SCHEMA[key]["category"] == "risk", f"{key} category must be 'risk'"
        assert _SCHEMA[key]["applies_to"] == "risk", f"{key} applies_to must be 'risk'"
        assert _SCHEMA[key]["restart_required"] is False


def test_daily_loss_schema_validation_percent_below_min():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_DAILY_MAX_LOSS_PERCENT": 0.0})
    assert not ok
    assert any("below" in e.lower() or "minimum" in e.lower() for e in errors)


def test_daily_loss_schema_validation_percent_above_max():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_DAILY_MAX_LOSS_PERCENT": 25.0})
    assert not ok
    assert any("exceed" in e.lower() or "maximum" in e.lower() for e in errors)


def test_daily_loss_schema_validation_enabled_must_be_bool():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_DAILY_MAX_LOSS_ENABLED": "yes"})
    assert not ok
    assert any("bool" in e.lower() for e in errors)


def test_momentum_max_trades_schema_max_is_300():
    """PAPER_MOMENTUM_MAX_TRADES_PER_DAY schema upper bound raised to 300 in Phase 2N."""
    from paper.runtime_config import _SCHEMA
    assert _SCHEMA["PAPER_MOMENTUM_MAX_TRADES_PER_DAY"]["max"] == 300


# ── 3. daily_loss_guard_triggered logic ──────────────────────────────────────

def _make_account(starting: float = 1000.0):
    from paper.account import PaperAccount
    return PaperAccount(starting)


def test_guard_disabled_returns_not_triggered():
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": False,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["triggered"] is False
    assert result["enabled"] is False
    assert result["reason"] is None


def test_guard_no_loss_not_triggered():
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        # No positions, no trades — P&L is 0
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["triggered"] is False
    assert result["daily_pnl"] == 0.0
    assert result["daily_pnl_percent"] == 0.0


def test_guard_loss_below_percent_threshold_triggers():
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    # Equity = cash = 970 (loss of 30 embedded in cash); daily_start_equity = 1000
    acc.cash = 970.0
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["triggered"] is True
    assert result["reason"] == "daily_max_loss_percent"
    assert result["daily_pnl"] == pytest.approx(-30.0, rel=1e-3)
    assert result["daily_pnl_percent"] == pytest.approx(-3.0, rel=1e-3)


def test_guard_loss_exactly_at_threshold_triggers():
    """Loss exactly at -2.0% triggers (<=)."""
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 980.0  # -2.0% equity loss
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    # -20 / 1000 = -2.0% <= -2.0% → triggered
    assert result["triggered"] is True


def test_guard_loss_just_under_threshold_not_triggered():
    """Loss slightly less than -2.0% does not trigger."""
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 980.1  # -1.99% equity loss — just under threshold
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["triggered"] is False


def test_guard_usd_threshold_triggers():
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(10_000.0)
    # Equity = 9990 (loss of $10 embedded in cash)
    acc.cash = 9990.0
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,   # not triggered by percent (-0.1%)
            "PAPER_DAILY_MAX_LOSS_USD": 5.0,       # triggered: -10 <= -5
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["triggered"] is True
    assert result["reason"] == "daily_max_loss_usd"


def test_guard_both_thresholds_both_active():
    """When both percent and USD breach, reason = percent (checked first) and triggered."""
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 950.0  # -5% equity loss
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 30.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["triggered"] is True
    assert result["reason"] == "daily_max_loss_percent"


def test_guard_includes_unrealized_pnl():
    """Unrealized P&L from open positions counts toward the guard."""
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    # Enter a position at 100, current price is 95 → -5% unrealized = -$5
    import uuid
    from datetime import datetime, timezone
    from paper.models import Position
    pos = Position(
        position_id=uuid.uuid4().hex[:8],
        symbol="AAPL",
        entry_price=100.0,
        shares=1.0,
        cost_basis=100.0,
        entry_time=datetime.now(timezone.utc).isoformat(),
        entry_catalyst_type="earnings",
    )
    acc.positions["AAPL"] = pos
    acc.cash = 900.0  # 100 spent on position

    last_prices = {"AAPL": 70.0}  # unrealized loss of -30 on 1 share
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        result = daily_loss_guard_triggered(acc, last_prices)
    finally:
        rc._runtime_overrides = old
    # unrealized pnl = (70 - 100) * 1 = -30, which is -3% of 1000 starting cash
    assert result["triggered"] is True
    assert result["daily_pnl"] == pytest.approx(-30.0, abs=0.01)


def test_guard_exception_returns_safe_default():
    """If an exception occurs inside guard, returns triggered=False (safe default)."""
    from paper.risk import daily_loss_guard_triggered

    class BrokenAccount:
        daily_start_equity = 1000.0
        daily_baseline_date = "2026-06-08"
        def get_equity(self, _): raise RuntimeError("broken")

    result = daily_loss_guard_triggered(BrokenAccount(), {})
    assert result["triggered"] is False
    assert result["enabled"] is False


def test_guard_result_includes_threshold_fields():
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 3.0,
            "PAPER_DAILY_MAX_LOSS_USD": 50.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["threshold_percent"] == 3.0
    assert result["threshold_usd"] == 50.0


def test_guard_usd_zero_threshold_is_none():
    """When PAPER_DAILY_MAX_LOSS_USD=0, threshold_usd in result must be None."""
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old
    assert result["threshold_usd"] is None


# ── 4. get_status includes daily_loss_guard ───────────────────────────────────

def test_get_status_includes_daily_loss_guard():
    import paper.simulator as sim
    status = sim.get_status()
    assert "daily_loss_guard" in status
    dlg = status["daily_loss_guard"]
    assert "triggered" in dlg
    assert "enabled" in dlg
    assert "trading_date" in dlg
    assert "daily_start_equity" in dlg
    assert "current_equity" in dlg


# ── 5. Candidate output — daily_loss_guard_triggered field ────────────────────

def _make_closed_trade(symbol: str, pnl: float):
    from paper.models import ClosedTrade
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    return ClosedTrade(
        position_id="test",
        symbol=symbol,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        shares=1.0,
        cost_basis=100.0,
        proceeds=100.0 + pnl,
        pnl=pnl,
        pnl_percent=pnl / 100.0 * 100.0,
        entry_time=now,
        exit_time=now,
        exit_reason="take_profit",
        entry_catalyst_type="earnings",
        hold_minutes=5.0,
    )


def test_candidate_has_daily_loss_guard_triggered_field():
    """run_tick returns candidates with daily_loss_guard_triggered field."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    quality = {
        "tradable": False, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 0.5, "volume_ratio": 1.5,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": ["low_volume"],
    }

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    sim._account = PaperAccount(1000.0)

    rc._runtime_overrides.update({
        "PAPER_DAILY_MAX_LOSS_ENABLED": True,
        "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
        "PAPER_DAILY_MAX_LOSS_USD": 0.0,
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
                      "active_symbols": ["AAPL"],
                      "active_count": 1,
                      "last_refreshed_at": None,
                      "refresh_reason": "test",
                      "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
                  }),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": []}}),
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

    candidates = result.get("candidates", [])
    assert len(candidates) == 1
    assert "daily_loss_guard_triggered" in candidates[0]


# ── 6. Guard blocks catalyst entries (Path A) ─────────────────────────────────

def test_guard_triggered_blocks_catalyst_entry():
    """When guard is triggered, Path A candidate must have action=daily_max_loss_guard."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 4.0,
        "day_volume": 4_000_000, "previous_day_volume": 1_000_000,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }
    catalyst = [{
        "symbol": "AAPL", "classified_event_type": "earnings",
        "sentiment": "bullish", "materiality_score": 0.9, "title": "Record earnings",
    }]

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    acc = PaperAccount(1000.0)
    # Equity loss of -3% embedded in cash; daily_start_equity remains 1000 from __init__
    acc.cash = 970.0
    acc.daily_baseline_date = sim._ny_trading_date()  # prevent rollover reset during tick
    sim._account = acc

    rc._runtime_overrides.update({
        "PAPER_DAILY_MAX_LOSS_ENABLED": True,
        "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
        "PAPER_DAILY_MAX_LOSS_USD": 0.0,
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
                      "active_symbols": ["AAPL"],
                      "active_count": 1,
                      "last_refreshed_at": None,
                      "refresh_reason": "test",
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
                "strongest_catalyst_title": "Record earnings",
                "strongest_catalyst_sentiment": "bullish",
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

    assert result["entries_made"] == 0, "Guard should have blocked all entries"
    candidates = result.get("candidates", [])
    assert len(candidates) == 1
    c = candidates[0]
    assert c["action"] == "daily_max_loss_guard"
    assert c["rejection_reason"] == "daily_max_loss_guard"
    assert c["eligible"] is False
    assert c["daily_loss_guard_triggered"] is True


# ── 7. Guard blocks momentum entries (Path B) ─────────────────────────────────

def test_guard_triggered_blocks_momentum_entry():
    """When guard is triggered, Path B candidate must have action=daily_max_loss_guard."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 4.0,
        "day_volume": 4_000_000, "previous_day_volume": 1_000_000,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    acc = PaperAccount(1000.0)
    acc.cash = 970.0  # -3% equity loss → guard triggers
    acc.daily_baseline_date = sim._ny_trading_date()  # prevent rollover reset during tick
    sim._account = acc

    rc._runtime_overrides.update({
        "PAPER_DAILY_MAX_LOSS_ENABLED": True,
        "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
        "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        "PAPER_MOMENTUM_MODE_ENABLED": True,
        "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
        "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
        "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
        "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
        "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": False,
        "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
        "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": 0.5,
        "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 30,
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
                      "active_symbols": ["AAPL"],
                      "active_count": 1,
                      "last_refreshed_at": None,
                      "refresh_reason": "test",
                      "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
                  }),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            # No catalysts → momentum fallback path
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": []}}),
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

    assert result["entries_made"] == 0, "Guard should block momentum entries too"
    candidates = result.get("candidates", [])
    assert len(candidates) == 1
    c = candidates[0]
    assert c["action"] == "daily_max_loss_guard"
    assert c["daily_loss_guard_triggered"] is True


# ── 8. Guard never blocks exits ───────────────────────────────────────────────

def test_guard_does_not_prevent_exits():
    """When guard is triggered, existing positions must still be exited normally."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from datetime import datetime, timezone
    from paper.models import Position
    import uuid

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    old_prices = dict(sim._last_prices)

    acc = PaperAccount(1000.0)
    # AAPL position: bought at 100, 1 share, cost=100
    # Cash = 850 reflects: 1000 - 50 (MSFT loss) - 100 (AAPL purchase)
    # daily_start_equity=1000; after AAPL exits at 110: equity=850+110=960 → -4% → triggered
    p = Position(
        position_id=uuid.uuid4().hex[:8],
        symbol="AAPL",
        entry_price=100.0,
        shares=1.0,
        cost_basis=100.0,
        entry_time=datetime.now(timezone.utc).isoformat(),
        entry_catalyst_type="earnings",
    )
    acc.positions["AAPL"] = p
    acc.cash = 850.0  # accounts for prior realized loss (-50) and AAPL purchase (-100)
    acc.daily_baseline_date = sim._ny_trading_date()  # prevent rollover reset during tick
    sim._account = acc
    sim._last_prices["AAPL"] = 110.0  # above take-profit threshold (0.60%)

    rc._runtime_overrides.update({
        "PAPER_DAILY_MAX_LOSS_ENABLED": True,
        "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
        "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        "PAPER_MOMENTUM_MODE_ENABLED": False,
        "PAPER_ENTRY_SCORE_THRESHOLD": 70,
        "PAPER_TAKE_PROFIT_PERCENT": 0.60,  # entry*1.006 = 100.60; price=110 > TP
        "PAPER_STOP_LOSS_PERCENT": 0.35,
        "PAPER_MAX_HOLD_MINUTES": 15,
        "PAPER_MAX_OPEN_POSITIONS": 5,
        "PAPER_MAX_TRADES_PER_DAY": 100,
        "PAPER_POSITION_SIZE_PERCENT": 25.0,
        "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
        "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
        "MARKET_REGIME_ENABLED": False,
    })

    quality_aapl = {
        "tradable": True, "bid": 110.0, "ask": 110.1, "last_trade_price": 110.05,
        "spread_percent": 0.09, "change_percent": 10.0, "volume_ratio": 5.0,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={
                      "active_symbols": ["AAPL"],
                      "active_count": 1,
                      "last_refreshed_at": None,
                      "refresh_reason": "test",
                      "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
                  }),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality_aapl),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality_aapl),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": []}}),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        sim._last_prices = old_prices
        rc._runtime_overrides = old_overrides

    # Guard is triggered but exits must still happen
    assert result["daily_loss_guard"]["triggered"] is True
    assert result["exits_made"] >= 1, "Exit must proceed even when guard is triggered"
    exits = result.get("exits", [])
    assert any(e["symbol"] == "AAPL" for e in exits)


# ── 9. Re-entry allowed when guard clears ─────────────────────────────────────

def test_guard_clears_when_loss_recovers():
    """Guard must not trigger when equity loss is within threshold."""
    from paper import runtime_config as rc
    from paper.risk import daily_loss_guard_triggered

    acc = _make_account(1000.0)
    # Equity = 990 (-1.0%) — within 2.0% threshold
    acc.cash = 990.0

    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
        })
        result = daily_loss_guard_triggered(acc, {})
    finally:
        rc._runtime_overrides = old

    assert result["triggered"] is False, \
        "Guard must not trigger when loss is within threshold"


# ── 10. Monitoring — daily_loss_guard field ───────────────────────────────────

def test_monitoring_has_daily_loss_guard_field(client):
    with (
        patch("paper.simulator.get_status", return_value={
            "running": False, "last_tick_at": None, "last_error": None,
            "daily_loss_guard": {
                "triggered": False, "enabled": True, "reason": None,
                "trading_date": "2026-06-08", "daily_start_equity": 1000.0,
                "current_equity": 1000.0,
                "daily_pnl": 0.0, "daily_pnl_percent": 0.0,
                "threshold_percent": 2.0, "threshold_usd": None,
            },
        }),
        patch("paper.journal.get_journal_status", return_value={
            "enabled": False, "database_connected": False,
            "tables_ready": False, "last_persist_ok": None,
        }),
        patch("paper.runtime_config.effective_value") as mock_cfg,
        patch("paper.runtime_config.get_runtime_status", return_value={
            "overrides_active": False, "override_count": 0,
            "persistent": False, "warnings": [],
        }),
    ):
        def cfg_side(k):
            return {
                "MARKET_REGIME_ENABLED": False,
                "PAPER_MOMENTUM_MODE_ENABLED": False,
                "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
                "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
                "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
                "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
                "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": True,
                "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
                "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": 0.5,
                "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 30,
                "PAPER_DAILY_MAX_LOSS_ENABLED": True,
                "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
                "PAPER_DAILY_MAX_LOSS_USD": 0.0,
            }.get(k)
        mock_cfg.side_effect = cfg_side
        resp = client.get("/api/monitoring/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "daily_loss_guard" in data, "monitoring/status must include daily_loss_guard"
    dlg = data["daily_loss_guard"]
    assert "triggered" in dlg
    assert "enabled" in dlg
    assert "trading_date" in dlg


def test_monitoring_guard_triggered_adds_warning(client):
    with (
        patch("paper.simulator.get_status", return_value={
            "running": False, "last_tick_at": None, "last_error": None,
            "daily_loss_guard": {
                "triggered": True, "enabled": True,
                "reason": "daily_max_loss_percent",
                "trading_date": "2026-06-08", "daily_start_equity": 1000.0,
                "current_equity": 975.0,
                "daily_pnl": -25.0, "daily_pnl_percent": -2.5,
                "threshold_percent": 2.0, "threshold_usd": None,
            },
        }),
        patch("paper.journal.get_journal_status", return_value={
            "enabled": False, "database_connected": False,
            "tables_ready": False, "last_persist_ok": None,
        }),
        patch("paper.runtime_config.effective_value") as mock_cfg,
        patch("paper.runtime_config.get_runtime_status", return_value={
            "overrides_active": False, "override_count": 0,
            "persistent": False, "warnings": [],
        }),
    ):
        def cfg_side(k):
            return {
                "MARKET_REGIME_ENABLED": False,
                "PAPER_MOMENTUM_MODE_ENABLED": False,
                "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
                "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
                "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
                "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
                "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": True,
                "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
                "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": 0.5,
                "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 30,
                "PAPER_DAILY_MAX_LOSS_ENABLED": True,
                "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
                "PAPER_DAILY_MAX_LOSS_USD": 0.0,
            }.get(k)
        mock_cfg.side_effect = cfg_side
        resp = client.get("/api/monitoring/status")

    assert resp.status_code == 200
    data = resp.json()
    warnings = data.get("warnings", [])
    assert any("loss" in w.lower() or "guard" in w.lower() for w in warnings), \
        "monitoring must warn when daily loss guard is triggered"


# ── 11. Readiness — daily_loss_guard check ────────────────────────────────────

def test_readiness_daily_loss_guard_check_pass_when_not_triggered(client):
    with (
        patch("api.readiness._check_polygon_data", new_callable=AsyncMock,
              return_value={"name": "polygon_data", "status": "pass", "message": "ok", "details": {}}),
        patch("paper.runtime_config.effective_value") as mock_cfg,
    ):
        def cfg_side(k):
            return {
                "PAPER_DAILY_MAX_LOSS_ENABLED": True,
                "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
                "PAPER_DAILY_MAX_LOSS_USD": 0.0,
                "PAPER_MOMENTUM_MODE_ENABLED": False,
                "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
                "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 30,
                "PAPER_MARKET_DISCOVERY_ENABLED": False,
                "MARKET_REGIME_ENABLED": False,
            }.get(k)
        mock_cfg.side_effect = cfg_side
        resp = client.get("/api/readiness/session")

    assert resp.status_code == 200
    data = resp.json()
    checks = {c["name"]: c for c in data.get("checks", [])}
    assert "daily_loss_guard" in checks, "readiness must include daily_loss_guard check"
    assert checks["daily_loss_guard"]["status"] in ("pass", "warn")


# ── 12. Safety — no broker/AI imports in risk.py ─────────────────────────────

def test_risk_py_no_broker_or_ai_imports():
    path = BACKEND_ROOT / "paper" / "risk.py"
    imports = _ast_imports(path)
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden module {forbidden!r} found in risk.py import: {imp!r}"


def test_risk_py_no_execution_calls():
    path = BACKEND_ROOT / "paper" / "risk.py"
    source = path.read_text()
    for name in FORBIDDEN_EXECUTION:
        assert name not in source, \
            f"Execution-related name {name!r} found in risk.py"


def test_simulator_no_broker_imports_phase2n():
    path = BACKEND_ROOT / "paper" / "simulator.py"
    imports = _ast_imports(path)
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden module {forbidden!r} found in simulator.py: {imp!r}"


def test_guard_does_not_affect_live_trading_flag():
    """Simulator must always report live_trading_enabled=False regardless of guard state."""
    import paper.simulator as sim
    status = sim.get_status()
    assert status.get("live_trading_enabled") is False
    assert status.get("broker_connected") is False


def test_guard_disclaimer_present_in_risk_module():
    """risk.py module docstring must contain fake-money disclaimer."""
    path = BACKEND_ROOT / "paper" / "risk.py"
    source = path.read_text()
    assert "fake-money" in source.lower() or "no broker" in source.lower(), \
        "risk.py must contain fake-money / no-broker disclaimer"
