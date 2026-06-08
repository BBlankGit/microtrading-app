"""
Phase 2Q-Lite tests — Virtual bracket-order intrabar TP/SL detection.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All simulation is fake-money research only.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND_ROOT = Path(__file__).parent.parent

FORBIDDEN_MODULES = {
    "openai", "anthropic", "langchain", "ollama",
    "broker", "alpaca", "ibapi", "tastytrade", "td_ameritrade", "schwab",
}
FORBIDDEN_EXECUTION = {"place_order", "submit_order", "execute_order", "send_order"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pos(symbol="AAPL", entry_price=100.0, entry_mode="catalyst"):
    from paper.models import Position
    return Position(
        position_id="test1234",
        symbol=symbol,
        entry_price=entry_price,
        shares=1.0,
        cost_basis=entry_price,
        entry_time="2026-06-08T14:00:00+00:00",
        entry_catalyst_type="fda_regulatory",
        entry_score=75,
        entry_mode=entry_mode,
    )


def _make_account(entry_price=100.0, cash=900.0):
    from paper.account import PaperAccount
    from paper.simulator import _ny_trading_date
    acc = PaperAccount(1000.0)
    acc.cash = cash
    pos = _make_pos(entry_price=entry_price)
    acc.positions["AAPL"] = pos
    acc.daily_baseline_date = _ny_trading_date()
    acc.daily_start_equity = 1000.0
    return acc


def _intrabar(high, low):
    return {"high": high, "low": low, "source": "1m_agg", "bar_timestamp": "2026-06-08T14:01:00+00:00"}


def _quote(bid=100.5):
    return {"bid": bid, "last_trade_price": bid}


# ── 1. evaluate_virtual_bracket_exit: TP only touched ────────────────────────

def test_tp_only_intrabar():
    from paper.exits import evaluate_virtual_bracket_exit
    result = evaluate_virtual_bracket_exit(
        entry_price=100.0,
        tp_pct=0.6,
        sl_pct=0.35,
        quote=None,
        intrabar=_intrabar(high=100.7, low=100.2),
    )
    assert result["should_exit"] is True
    assert result["exit_reason"] == "take_profit_intrabar"
    assert result["exit_price"] == pytest.approx(100.6, rel=1e-6)
    assert result["tp_touched"] is True
    assert result["sl_touched"] is False
    assert result["intrabar_source"] == "1m_agg"
    assert result["conservative_both_touched"] is False


# ── 2. evaluate_virtual_bracket_exit: SL only touched ────────────────────────

def test_sl_only_intrabar():
    from paper.exits import evaluate_virtual_bracket_exit
    result = evaluate_virtual_bracket_exit(
        entry_price=100.0,
        tp_pct=0.6,
        sl_pct=0.35,
        quote=None,
        intrabar=_intrabar(high=100.2, low=99.5),
    )
    assert result["should_exit"] is True
    assert result["exit_reason"] == "stop_loss_intrabar"
    assert result["exit_price"] == pytest.approx(99.65, rel=1e-6)
    assert result["tp_touched"] is False
    assert result["sl_touched"] is True
    assert result["conservative_both_touched"] is False


# ── 3. evaluate_virtual_bracket_exit: both TP and SL touched ─────────────────

def test_both_touched_conservative_stop_loss_wins():
    from paper.exits import evaluate_virtual_bracket_exit
    result = evaluate_virtual_bracket_exit(
        entry_price=100.0,
        tp_pct=0.6,
        sl_pct=0.35,
        quote=None,
        intrabar=_intrabar(high=100.7, low=99.5),
    )
    assert result["should_exit"] is True
    assert result["exit_reason"] == "stop_loss_intrabar_both_touched_conservative"
    assert result["exit_price"] == pytest.approx(99.65, rel=1e-6)
    assert result["tp_touched"] is True
    assert result["sl_touched"] is True
    assert result["conservative_both_touched"] is True
    assert "Both TP and SL" in result.get("note", "")


# ── 4. evaluate_virtual_bracket_exit: no intrabar data, fallback bid ─────────

def test_no_intrabar_fallback_bid_tp():
    from paper.exits import evaluate_virtual_bracket_exit
    result = evaluate_virtual_bracket_exit(
        entry_price=100.0,
        tp_pct=0.6,
        sl_pct=0.35,
        quote=_quote(bid=100.65),
        intrabar=None,
    )
    assert result["should_exit"] is True
    assert result["exit_reason"] == "take_profit"
    assert result["exit_price"] == pytest.approx(100.65, rel=1e-6)
    assert result["intrabar_source"] == "point_in_time"
    assert result["intrabar_high"] is None


def test_no_intrabar_fallback_bid_sl():
    from paper.exits import evaluate_virtual_bracket_exit
    result = evaluate_virtual_bracket_exit(
        entry_price=100.0,
        tp_pct=0.6,
        sl_pct=0.35,
        quote=_quote(bid=99.60),
        intrabar=None,
    )
    assert result["should_exit"] is True
    assert result["exit_reason"] == "stop_loss"
    assert result["exit_price"] == pytest.approx(99.60, rel=1e-6)


def test_no_intrabar_no_exit_mid_price():
    from paper.exits import evaluate_virtual_bracket_exit
    result = evaluate_virtual_bracket_exit(
        entry_price=100.0,
        tp_pct=0.6,
        sl_pct=0.35,
        quote=_quote(bid=100.3),
        intrabar=None,
    )
    assert result["should_exit"] is False
    assert result["exit_reason"] is None


# ── 5. Max hold still fires when TP/SL not touched ───────────────────────────

@pytest.mark.asyncio
async def test_max_hold_fires_when_no_bracket_exit():
    import paper.simulator as sim
    from paper.exits import clear_intrabar_cache

    clear_intrabar_cache()
    old_acc = sim._account
    old_prices = dict(sim._last_prices)

    acc = _make_account(entry_price=100.0)
    # Make entry time old enough for max-hold to trigger (16 minutes ago)
    from datetime import datetime, timezone, timedelta
    old_entry = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    acc.positions["AAPL"].entry_time = old_entry

    sim._account = acc
    sim._last_prices = {"AAPL": 100.3}

    try:
        # Patch Polygon calls: no intrabar data, quality returns price in range
        quality_q = {
            "bid": 100.3, "last_trade_price": 100.3, "tradable": False,
            "rejection_reasons": ["test"], "change_percent": 1.0,
            "volume_ratio": 1.0, "spread_percent": 0.1,
        }
        with (
            patch("paper.simulator.polygon_client.get_ticker_snapshot", new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.polygon_client.get_previous_close", new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality_q),
            patch("paper.simulator.get_intrabar_data", new_callable=AsyncMock, return_value=None),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock, return_value={"filter": {"accepted": []}}),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock, return_value={"ok": True}),
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [], "active_count": 0, "last_refreshed_at": None, "refresh_reason": None, "discovery": {}}),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = await sim.run_tick()

        exits = result["exits"]
        assert len(exits) == 1, f"Expected 1 exit, got {exits}"
        assert exits[0]["exit_reason"] == "max_hold_time"
    finally:
        sim._account = old_acc
        sim._last_prices = old_prices


# ── 6. Daily loss guard does not block exits ──────────────────────────────────

@pytest.mark.asyncio
async def test_daily_loss_guard_does_not_block_exits():
    import paper.simulator as sim
    from paper.exits import clear_intrabar_cache

    clear_intrabar_cache()
    old_acc = sim._account
    old_prices = dict(sim._last_prices)

    acc = _make_account(entry_price=100.0, cash=50.0)
    # Trigger daily loss guard: set start equity high, current equity low
    acc.daily_start_equity = 1000.0
    acc.daily_baseline_date = sim._ny_trading_date()
    acc.cash = 50.0  # severe loss

    from datetime import datetime, timezone, timedelta
    old_entry = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    acc.positions["AAPL"].entry_time = old_entry

    sim._account = acc
    sim._last_prices = {"AAPL": 100.3}

    try:
        quality_q = {
            "bid": 100.3, "last_trade_price": 100.3, "tradable": False,
            "rejection_reasons": ["test"], "change_percent": 1.0,
            "volume_ratio": 1.0, "spread_percent": 0.1,
        }
        with (
            patch("paper.simulator.polygon_client.get_ticker_snapshot", new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.polygon_client.get_previous_close", new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality_q),
            patch("paper.simulator.get_intrabar_data", new_callable=AsyncMock, return_value=None),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock, return_value={"filter": {"accepted": []}}),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock, return_value={"ok": True}),
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [], "active_count": 0, "last_refreshed_at": None, "refresh_reason": None, "discovery": {}}),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = await sim.run_tick()

        # Exit must fire despite guard being triggered (guard blocks entries only)
        exits = result["exits"]
        assert len(exits) == 1, "Exit must not be blocked by daily loss guard"
        assert exits[0]["exit_reason"] == "max_hold_time"
        assert result["daily_loss_guard"]["triggered"] is True
    finally:
        sim._account = old_acc
        sim._last_prices = old_prices


# ── 7. Intrabar data only fetched for open positions, not candidates ──────────

@pytest.mark.asyncio
async def test_intrabar_only_fetched_for_open_positions():
    import paper.simulator as sim
    from paper.exits import clear_intrabar_cache

    clear_intrabar_cache()
    old_acc = sim._account
    old_prices = dict(sim._last_prices)

    # No open positions
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    acc.daily_start_equity = 1000.0
    sim._account = acc
    sim._last_prices = {}

    intrabar_calls: list = []

    async def _mock_intrabar(sym, entry_time, date_str):
        intrabar_calls.append(sym)
        return None

    try:
        with (
            patch("paper.simulator.polygon_client.get_ticker_snapshot", new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.polygon_client.get_previous_close", new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value={"tradable": False, "rejection_reasons": ["test"], "change_percent": 1.0, "volume_ratio": 1.0, "spread_percent": 0.1}),
            patch("paper.simulator.get_intrabar_data", side_effect=_mock_intrabar),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock, return_value={"filter": {"accepted": []}}),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock, return_value={"ok": True}),
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": ["AAPL", "MSFT"], "active_count": 2, "last_refreshed_at": None, "refresh_reason": None, "discovery": {}}),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            await sim.run_tick()

        # With 0 open positions, intrabar_data must never be called
        assert intrabar_calls == [], f"Expected no intrabar calls, got {intrabar_calls}"
    finally:
        sim._account = old_acc
        sim._last_prices = old_prices


# ── 8. TP intrabar triggers at exact target price ─────────────────────────────

def test_tp_triggers_at_exact_target():
    from paper.exits import evaluate_virtual_bracket_exit
    entry = 100.0
    tp_pct = 0.6
    tp_price = entry * (1 + tp_pct / 100)  # 100.6
    result = evaluate_virtual_bracket_exit(
        entry_price=entry,
        tp_pct=tp_pct,
        sl_pct=0.35,
        quote=None,
        intrabar=_intrabar(high=tp_price, low=99.9),  # high exactly == tp
    )
    assert result["should_exit"] is True
    assert result["exit_reason"] == "take_profit_intrabar"
    assert result["exit_price"] == pytest.approx(tp_price)


def test_sl_triggers_at_exact_target():
    from paper.exits import evaluate_virtual_bracket_exit
    entry = 100.0
    sl_pct = 0.35
    sl_price = entry * (1 - sl_pct / 100)  # 99.65
    result = evaluate_virtual_bracket_exit(
        entry_price=entry,
        tp_pct=0.6,
        sl_pct=sl_pct,
        quote=None,
        intrabar=_intrabar(high=100.1, low=sl_price),  # low exactly == sl
    )
    assert result["should_exit"] is True
    assert result["exit_reason"] == "stop_loss_intrabar"
    assert result["exit_price"] == pytest.approx(sl_price)


# ── 9. No forbidden imports in exits.py or simulator.py ──────────────────────

def _ast_all_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_no_forbidden_imports_in_exits():
    exits_path = BACKEND_ROOT / "paper" / "exits.py"
    imports = _ast_all_imports(exits_path)
    for mod in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in mod.lower(), \
                f"Forbidden import '{forbidden}' found in exits.py: {mod}"
    for imp in imports:
        assert not any(fn in imp for fn in FORBIDDEN_EXECUTION), \
            f"Forbidden execution symbol in exits.py: {imp}"


def test_no_forbidden_imports_in_simulator():
    sim_path = BACKEND_ROOT / "paper" / "simulator.py"
    imports = _ast_all_imports(sim_path)
    for mod in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in mod.lower(), \
                f"Forbidden import '{forbidden}' found in simulator.py: {mod}"


# ── 10. ClosedTrade dataclass carries intrabar fields ────────────────────────

def test_closed_trade_has_intrabar_fields():
    from paper.models import ClosedTrade
    trade = ClosedTrade(
        position_id="abc",
        symbol="AAPL",
        entry_price=100.0,
        exit_price=100.6,
        shares=1.0,
        cost_basis=100.0,
        proceeds=100.6,
        pnl=0.6,
        pnl_percent=0.6,
        entry_time="2026-06-08T14:00:00+00:00",
        exit_time="2026-06-08T14:05:00+00:00",
        exit_reason="take_profit_intrabar",
        entry_catalyst_type="fda_regulatory",
        hold_minutes=5.0,
    )
    trade.exit_intrabar_source = "1m_agg"
    trade.exit_intrabar_high = 100.7
    trade.exit_intrabar_low = 100.2
    trade.exit_tp_price = 100.6
    trade.exit_sl_price = 99.65
    trade.exit_conservative_both_touched = False

    d = trade.to_dict()
    assert d["exit_intrabar_source"] == "1m_agg"
    assert d["exit_intrabar_high"] == 100.7
    assert d["exit_tp_price"] == 100.6
    assert d["exit_conservative_both_touched"] is False
