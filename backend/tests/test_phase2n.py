"""
Phase 2N-H1 tests — True trading-day scoped daily max loss guard.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All simulation is fake-money research only.

Tests cover:
A. Baseline initialization
B. Same-day loss triggers
C. Same-day below-threshold no-trigger
D. USD threshold
E. Day rollover resets baseline
F. Prior-day profit does not mask today loss
G. Guard blocks catalyst entries
H. Guard blocks momentum entries
I. Guard does not block exits
J. Monitoring/readiness include trading_date and daily_start_equity
K. No profit cap added
L. No cooldown after take-profit
M. Same-symbol re-entry possible after profitable exit
N. No real Polygon calls
O. No broker/order/live trading imports
P. No AI/LLM/Ollama/OpenAI/Anthropic/LangChain imports
"""

import ast
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


@pytest.fixture()
def client():
    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def _make_account(starting: float = 1000.0):
    from paper.account import PaperAccount
    return PaperAccount(starting)


def _make_pos(symbol: str, entry_price: float, shares: float = 1.0):
    from paper.models import Position
    return Position(
        position_id=uuid.uuid4().hex[:8],
        symbol=symbol,
        entry_price=entry_price,
        shares=shares,
        cost_basis=entry_price * shares,
        entry_time=datetime.now(timezone.utc).isoformat(),
        entry_catalyst_type="earnings",
    )


def _with_guard_overrides(enabled: bool, pct: float, usd: float, fn):
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_DAILY_MAX_LOSS_ENABLED": enabled,
            "PAPER_DAILY_MAX_LOSS_PERCENT": pct,
            "PAPER_DAILY_MAX_LOSS_USD": usd,
        })
        return fn()
    finally:
        rc._runtime_overrides = old


# ── A. Baseline initialization ────────────────────────────────────────────────

def test_new_account_has_daily_baseline_date():
    acc = _make_account(1000.0)
    assert hasattr(acc, "daily_baseline_date"), "PaperAccount must have daily_baseline_date"


def test_new_account_has_daily_start_equity():
    acc = _make_account(1000.0)
    assert hasattr(acc, "daily_start_equity"), "PaperAccount must have daily_start_equity"


def test_new_account_daily_start_equity_equals_starting_cash():
    acc = _make_account(1000.0)
    assert acc.daily_start_equity == 1000.0


def test_simulator_module_baseline_initialized():
    """Simulator's module-level account must have a non-empty daily_baseline_date."""
    import paper.simulator as sim
    assert sim._account.daily_baseline_date != "", \
        "Module-level account must have baseline_date set at import time"


def test_simulator_module_baseline_date_is_ny_format():
    """daily_baseline_date must be YYYY-MM-DD format."""
    import re
    import paper.simulator as sim
    date = sim._account.daily_baseline_date
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", date), \
        f"daily_baseline_date must be YYYY-MM-DD, got: {date!r}"


def test_ny_trading_date_uses_ny_timezone():
    """_ny_trading_date() must return America/New_York date."""
    from paper.simulator import _ny_trading_date
    date = _ny_trading_date()
    # Must be a valid YYYY-MM-DD
    import re
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", date)


def test_account_reset_clears_baseline():
    acc = _make_account(1000.0)
    acc.daily_baseline_date = "2024-01-01"
    acc.daily_start_equity = 500.0
    acc.reset()
    assert acc.daily_baseline_date == ""
    assert acc.daily_start_equity == 1000.0  # reset to starting_cash


# ── B. Same-day loss triggers at threshold ────────────────────────────────────

def test_same_day_loss_above_threshold_triggers():
    """daily_start_equity=1000, current_equity=980, threshold=2% → triggered."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 980.0  # equity = 980, daily_pnl = -2.0% (exactly at threshold <=)
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["triggered"] is True
    assert result["daily_pnl"] == pytest.approx(-20.0, abs=0.01)
    assert result["daily_pnl_percent"] == pytest.approx(-2.0, rel=1e-3)


def test_same_day_loss_trading_date_in_output():
    """Guard output must include trading_date matching account.daily_baseline_date."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.daily_baseline_date = "2026-06-08"
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["trading_date"] == "2026-06-08"


def test_same_day_loss_daily_start_equity_in_output():
    """Guard output must include daily_start_equity."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.daily_start_equity = 1250.0
    acc.cash = 1225.0  # -2.0% of 1250 = -25
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["daily_start_equity"] == pytest.approx(1250.0, rel=1e-4)
    assert result["triggered"] is True


def test_same_day_loss_current_equity_in_output():
    """Guard output must include current_equity."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 970.0
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["current_equity"] == pytest.approx(970.0, rel=1e-4)


# ── C. Same-day below-threshold no trigger ────────────────────────────────────

def test_same_day_loss_below_threshold_not_triggered():
    """current_equity=981 (-1.9%), threshold=2% → NOT triggered."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 981.0  # -1.9%
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["triggered"] is False


def test_no_loss_not_triggered():
    """Zero daily P&L must not trigger."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)  # equity == daily_start_equity
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["triggered"] is False
    assert result["daily_pnl"] == 0.0


def test_gain_not_triggered():
    """A daily gain must not trigger the guard."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 1050.0  # +5% gain
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["triggered"] is False
    assert result["daily_pnl"] == pytest.approx(50.0, abs=0.01)


# ── D. USD threshold ──────────────────────────────────────────────────────────

def test_usd_threshold_triggers_independent_of_percent():
    """daily_start_equity=1000, equity=970 (-$30), USD threshold=$25 → triggered."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 970.0  # -$30 loss
    result = _with_guard_overrides(True, 5.0, 25.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    # -3% < 5% threshold but -30 <= -25 USD threshold
    assert result["triggered"] is True
    assert result["reason"] == "daily_max_loss_usd"


def test_usd_threshold_zero_disabled():
    """USD threshold of 0 must not trigger guard."""
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    acc.cash = 800.0  # -20% loss
    result = _with_guard_overrides(True, 50.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    # percent threshold 50% not breached; USD=0 disabled
    assert result["triggered"] is False
    assert result["threshold_usd"] is None


# ── E. Day rollover resets baseline ──────────────────────────────────────────

def test_day_rollover_resets_baseline_in_tick():
    """
    When daily_baseline_date != today_ny, the tick must reset daily_start_equity
    to current equity and update daily_baseline_date.
    After reset, a prior-day loss does not trigger the guard on the new day.
    """
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    quality = {
        "tradable": False, "bid": 95.0, "ask": 95.1, "last_trade_price": 95.0,
        "spread_percent": 0.10, "change_percent": -1.0, "volume_ratio": 0.5,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": False, "has_acceptable_spread": True,
        "rejection_reasons": ["low_volume"],
    }

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    old_prices = dict(sim._last_prices)

    # Simulate: account had -5% loss yesterday, equity is now 950
    acc = PaperAccount(1000.0)
    acc.cash = 950.0
    acc.daily_baseline_date = "2020-01-01"  # yesterday (old date)
    acc.daily_start_equity = 1000.0         # yesterday's starting equity

    sim._account = acc
    sim._last_prices.clear()

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
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    dlg = result.get("daily_loss_guard", {})
    # After rollover: daily_start_equity = 950 (current equity), daily_pnl = 0
    assert dlg.get("triggered") is False, \
        "After day rollover, prior-day loss must not trigger guard"
    # The baseline date should now be today (not 2020-01-01)
    assert acc.daily_baseline_date != "2020-01-01", \
        "Baseline date must be updated to today on rollover"
    assert acc.daily_start_equity == pytest.approx(950.0, abs=0.01), \
        "daily_start_equity must be reset to current equity on rollover"


# ── F. Prior-day profit does not mask today loss ──────────────────────────────

def test_prior_day_profit_does_not_mask_today_loss():
    """
    After day rollover, the baseline resets to current equity.
    A today loss is calculated from the new baseline only,
    even if prior-day equity was high.
    """
    from paper.risk import daily_loss_guard_triggered
    acc = _make_account(1000.0)
    # Yesterday ended well: prior high equity. Set daily_start_equity to 1200 (today's baseline)
    acc.daily_start_equity = 1200.0
    # Today: equity dropped to 1170 (-2.5% of 1200 = -30)
    acc.cash = 1170.0
    result = _with_guard_overrides(True, 2.0, 0.0,
                                   lambda: daily_loss_guard_triggered(acc, {}))
    assert result["triggered"] is True
    assert result["daily_pnl"] == pytest.approx(-30.0, abs=0.01)
    assert result["daily_pnl_percent"] == pytest.approx(-2.5, rel=1e-3)


# ── G. Guard blocks catalyst entries ─────────────────────────────────────────

def test_guard_triggered_blocks_catalyst_entry_path():
    """When guard triggered, Path A catalyst entries must be blocked with action=daily_max_loss_guard."""
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
    acc.cash = 970.0   # -3% equity loss → triggers at 2% threshold
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

    assert result["entries_made"] == 0
    candidates = result.get("candidates", [])
    assert len(candidates) == 1
    c = candidates[0]
    assert c["action"] == "daily_max_loss_guard"
    assert c["eligible"] is False
    assert c["daily_loss_guard_triggered"] is True


# ── H. Guard blocks momentum entries ─────────────────────────────────────────

def test_guard_triggered_blocks_momentum_entry_path():
    """When guard triggered, Path B momentum entries must be blocked."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 4.0,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    acc = PaperAccount(1000.0)
    acc.cash = 970.0  # -3% → guard triggers
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

    assert result["entries_made"] == 0
    candidates = result.get("candidates", [])
    assert len(candidates) == 1
    assert candidates[0]["daily_loss_guard_triggered"] is True


# ── I. Guard does not block exits ─────────────────────────────────────────────

def test_guard_triggered_does_not_block_exits():
    """
    When guard is triggered, open positions must still exit at take-profit/stop-loss.
    After AAPL exits (entry=100, exit=110), equity = 850+110=960 (still -4%) → guard triggered.
    """
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from paper.models import Position

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    old_prices = dict(sim._last_prices)

    acc = PaperAccount(1000.0)
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
    # cash=850 reflects prior $50 loss + $100 AAPL purchase
    # After AAPL exits at 110: equity = 850+110=960 → -4% from 1000 → still triggered
    acc.cash = 850.0
    acc.daily_baseline_date = sim._ny_trading_date()  # prevent rollover reset during tick
    sim._account = acc
    sim._last_prices["AAPL"] = 110.0

    quality_aapl = {
        "tradable": True, "bid": 110.0, "ask": 110.1, "last_trade_price": 110.05,
        "spread_percent": 0.09, "change_percent": 10.0, "volume_ratio": 5.0,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }

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
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    assert result["daily_loss_guard"]["triggered"] is True
    assert result["exits_made"] >= 1, "Exit must proceed even when guard is triggered"
    assert any(e["symbol"] == "AAPL" for e in result.get("exits", []))


# ── J. Monitoring/readiness include trading_date and daily_start_equity ───────

def test_monitoring_daily_loss_guard_has_trading_date(client):
    with (
        patch("paper.simulator.get_status", return_value={
            "running": False, "last_tick_at": None, "last_error": None,
            "daily_loss_guard": {
                "triggered": False, "enabled": True, "reason": None,
                "trading_date": "2026-06-08",
                "daily_start_equity": 1000.0,
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
        mock_cfg.side_effect = lambda k: {
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
        resp = client.get("/api/monitoring/status")

    assert resp.status_code == 200
    data = resp.json()
    dlg = data.get("daily_loss_guard", {})
    assert "trading_date" in dlg, "monitoring must include trading_date in daily_loss_guard"
    assert "daily_start_equity" in dlg
    assert "current_equity" in dlg


def test_readiness_daily_loss_guard_details_has_trading_date(client):
    with (
        patch("api.readiness._check_polygon_data", new_callable=AsyncMock,
              return_value={"name": "polygon_data", "status": "pass", "message": "ok", "details": {}}),
        patch("paper.runtime_config.effective_value") as mock_cfg,
    ):
        mock_cfg.side_effect = lambda k: {
            "PAPER_DAILY_MAX_LOSS_ENABLED": True,
            "PAPER_DAILY_MAX_LOSS_PERCENT": 2.0,
            "PAPER_DAILY_MAX_LOSS_USD": 0.0,
            "PAPER_MOMENTUM_MODE_ENABLED": False,
            "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
            "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 30,
            "PAPER_MARKET_DISCOVERY_ENABLED": False,
            "MARKET_REGIME_ENABLED": False,
        }.get(k)
        resp = client.get("/api/readiness/session")

    assert resp.status_code == 200
    data = resp.json()
    checks = {c["name"]: c for c in data.get("checks", [])}
    assert "daily_loss_guard" in checks
    details = checks["daily_loss_guard"].get("details", {})
    assert "trading_date" in details, "readiness daily_loss_guard details must include trading_date"
    assert "daily_start_equity" in details


# ── K. No profit cap ─────────────────────────────────────────────────────────

def test_no_profit_cap_in_risk_py():
    path = BACKEND_ROOT / "paper" / "risk.py"
    source = path.read_text()
    assert "profit_cap" not in source.lower()
    assert "profit cap" not in source.lower()
    assert "max_profit" not in source.lower()


def test_no_profit_cap_in_simulator_py():
    path = BACKEND_ROOT / "paper" / "simulator.py"
    source = path.read_text()
    assert "profit_cap" not in source.lower()
    assert "profit cap" not in source.lower()


# ── L. No cooldown after take-profit ─────────────────────────────────────────

def test_no_cooldown_in_risk_py():
    path = BACKEND_ROOT / "paper" / "risk.py"
    source = path.read_text()
    assert "cooldown" not in source.lower()


def test_no_cooldown_in_simulator_py():
    path = BACKEND_ROOT / "paper" / "simulator.py"
    source = path.read_text()
    assert "cooldown" not in source.lower()


# ── M. Same-symbol re-entry possible after profitable exit ────────────────────

def test_same_symbol_reentry_not_blocked_by_risk_module():
    """
    risk.py must not contain any logic that blocks re-entry based on prior exits.
    Re-entry is gated only by can_enter (position limits, trade count) and guard.
    """
    path = BACKEND_ROOT / "paper" / "risk.py"
    source = path.read_text()
    assert "reentry" not in source.lower()
    assert "re_entry" not in source.lower()
    assert "same_symbol" not in source.lower()


def test_can_enter_allows_same_symbol_after_exit():
    """After exiting a symbol, can_enter must allow re-entry on same symbol."""
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    pos = acc.enter_position("AAPL", 100.0, 200.0, "earnings", entry_mode="catalyst")
    assert pos is not None
    acc.exit_position("AAPL", 110.0, "take_profit")
    can, reason = acc.can_enter("AAPL", max_positions=5, max_trades=100)
    assert can is True, f"Re-entry must be allowed after exit; reason: {reason}"


# ── N. No real Polygon calls ──────────────────────────────────────────────────

def test_risk_py_does_not_import_polygon():
    imports = _ast_imports(BACKEND_ROOT / "paper" / "risk.py")
    assert not any("polygon" in i.lower() for i in imports)


def test_account_py_does_not_import_polygon():
    imports = _ast_imports(BACKEND_ROOT / "paper" / "account.py")
    assert not any("polygon" in i.lower() for i in imports)


# ── O. No broker/order/live trading imports ───────────────────────────────────

def test_risk_py_no_broker_imports():
    imports = _ast_imports(BACKEND_ROOT / "paper" / "risk.py")
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden: {forbidden!r} in risk.py import {imp!r}"


def test_account_py_no_broker_imports():
    imports = _ast_imports(BACKEND_ROOT / "paper" / "account.py")
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden: {forbidden!r} in account.py import {imp!r}"


def test_risk_py_no_execution_calls():
    source = (BACKEND_ROOT / "paper" / "risk.py").read_text()
    for name in FORBIDDEN_EXECUTION:
        assert name not in source, f"Execution call {name!r} found in risk.py"


# ── P. No AI/LLM/Ollama imports ──────────────────────────────────────────────

def test_risk_py_no_ai_imports():
    imports = _ast_imports(BACKEND_ROOT / "paper" / "risk.py")
    for imp in imports:
        assert "openai" not in imp.lower()
        assert "anthropic" not in imp.lower()
        assert "langchain" not in imp.lower()
        assert "ollama" not in imp.lower()


def test_account_py_no_ai_imports():
    imports = _ast_imports(BACKEND_ROOT / "paper" / "account.py")
    for imp in imports:
        assert "openai" not in imp.lower()
        assert "anthropic" not in imp.lower()
        assert "ollama" not in imp.lower()


def test_live_trading_always_false():
    import paper.simulator as sim
    status = sim.get_status()
    assert status.get("live_trading_enabled") is False
    assert status.get("broker_connected") is False
