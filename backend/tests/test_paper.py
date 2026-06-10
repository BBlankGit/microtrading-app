"""
Tests for the Phase 2A paper simulator.

All tests use in-memory state only. No broker. No real orders.
No real money. Research-only fake-money simulation.
"""
import asyncio
import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from paper.account import PaperAccount
from paper.models import ClosedTrade, Position


# ── PaperAccount unit tests ──────────────────────────────────────────────────

def _make_account(cash: float = 1000.0) -> PaperAccount:
    return PaperAccount(starting_cash=cash)


def test_reset_restores_initial_state():
    acct = _make_account(500.0)
    acct.enter_position("AAPL", 100.0, 500.0, "earnings")
    acct.reset()
    assert acct.cash == 500.0
    assert acct.positions == {}
    assert acct.trades == []
    assert acct.daily_trade_count() == 0


def test_enter_position_deducts_cash():
    acct = _make_account(1000.0)
    pos = acct.enter_position("TSLA", 200.0, 400.0, "earnings")
    assert pos is not None
    assert pos.symbol == "TSLA"
    assert pos.entry_price == 200.0
    assert abs(pos.shares - 2.0) < 1e-9
    assert abs(pos.cost_basis - 400.0) < 1e-9
    assert abs(acct.cash - 600.0) < 1e-9


def test_enter_position_capped_by_available_cash():
    acct = _make_account(100.0)
    # max_size_usd > available cash — should be capped at cash
    pos = acct.enter_position("AMD", 50.0, 500.0, "sector_news")
    assert pos is not None
    assert abs(pos.cost_basis - 100.0) < 1e-9
    assert abs(acct.cash) < 1e-9


def test_enter_position_increments_daily_trade_count():
    acct = _make_account(1000.0)
    assert acct.daily_trade_count() == 0
    acct.enter_position("AAPL", 100.0, 200.0, "earnings")
    assert acct.daily_trade_count() == 1


def test_take_profit_exit():
    acct = _make_account(1000.0)
    pos = acct.enter_position("NVDA", 100.0, 200.0, "product_launch")
    assert pos is not None
    # Price up 1% — simulate take-profit exit
    exit_price = 101.0
    trade = acct.exit_position("NVDA", exit_price, "take_profit")
    assert trade is not None
    assert isinstance(trade, ClosedTrade)
    assert trade.exit_reason == "take_profit"
    assert trade.pnl > 0
    assert trade.exit_price == exit_price
    assert "NVDA" not in acct.positions
    # Cash should be restored + profit
    assert acct.cash > 1000.0


def test_stop_loss_exit():
    acct = _make_account(1000.0)
    pos = acct.enter_position("META", 100.0, 200.0, "earnings")
    assert pos is not None
    # Price down — simulate stop-loss exit
    exit_price = 99.0
    trade = acct.exit_position("META", exit_price, "stop_loss")
    assert trade is not None
    assert trade.exit_reason == "stop_loss"
    assert trade.pnl < 0
    assert "META" not in acct.positions
    # Cash restored but at a loss
    assert acct.cash < 1000.0


def test_exit_nonexistent_position_returns_none():
    acct = _make_account(1000.0)
    result = acct.exit_position("FAKE", 100.0, "stop_loss")
    assert result is None


def test_max_positions_enforced():
    acct = _make_account(1000.0)
    max_pos = 2
    # Fill up to max
    acct.enter_position("AAPL", 50.0, 100.0, "earnings")
    acct.enter_position("MSFT", 50.0, 100.0, "earnings")
    ok, reason = acct.can_enter("NVDA", max_pos, 100)
    assert not ok
    assert "max positions" in reason


def test_max_trades_per_day_enforced():
    acct = _make_account(1000.0)
    max_trades = 3
    acct.enter_position("AAPL", 10.0, 50.0, "earnings")
    acct.exit_position("AAPL", 11.0, "take_profit")
    acct.enter_position("MSFT", 10.0, 50.0, "earnings")
    acct.exit_position("MSFT", 11.0, "take_profit")
    acct.enter_position("NVDA", 10.0, 50.0, "earnings")
    acct.exit_position("NVDA", 11.0, "take_profit")
    ok, reason = acct.can_enter("TSLA", 10, max_trades)
    assert not ok
    assert "max daily trades" in reason


def test_already_in_position_blocked():
    acct = _make_account(1000.0)
    acct.enter_position("AAPL", 100.0, 200.0, "earnings")
    ok, reason = acct.can_enter("AAPL", 10, 100)
    assert not ok
    assert "already in position" in reason


def test_equity_includes_open_positions():
    acct = _make_account(1000.0)
    acct.enter_position("AAPL", 100.0, 200.0, "earnings")
    # Price up to 110 → position worth 220 (was 200)
    equity = acct.get_equity({"AAPL": 110.0})
    assert equity > 1000.0


def test_realized_pnl_accumulates():
    acct = _make_account(1000.0)
    acct.enter_position("AAPL", 100.0, 200.0, "earnings")
    acct.exit_position("AAPL", 110.0, "take_profit")
    assert acct.get_realized_pnl() > 0


def test_enter_position_zero_price_returns_none():
    acct = _make_account(1000.0)
    result = acct.enter_position("AAPL", 0.0, 200.0, "earnings")
    assert result is None


# ── API endpoint auth tests ──────────────────────────────────────────────────

_TOKEN = "test_admin_token_for_paper"

_PROTECTED_ENDPOINTS = [
    "/api/paper/start",
    "/api/paper/stop",
    "/api/paper/reset",
    "/api/paper/tick",
]

_PUBLIC_ENDPOINTS = [
    "/api/paper/status",
    "/api/paper/positions",
    "/api/paper/trades",
    "/api/paper/dashboard",
]


@pytest.fixture(autouse=True)
def set_admin_token(monkeypatch):
    from core import config
    monkeypatch.setattr(config.settings, "ADMIN_API_TOKEN", _TOKEN)


def test_public_paper_endpoints_no_auth(client):
    for path in _PUBLIC_ENDPOINTS:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"


def test_protected_endpoints_reject_missing_token(client):
    for path in _PROTECTED_ENDPOINTS:
        resp = client.post(path)
        assert resp.status_code in (401, 503), f"{path} returned {resp.status_code}"


def test_protected_endpoints_reject_wrong_token(client):
    for path in _PROTECTED_ENDPOINTS:
        resp = client.post(path, headers={"Authorization": "Bearer wrong_token"})
        assert resp.status_code == 401, f"{path} returned {resp.status_code}"


def test_protected_endpoints_accept_correct_token(client):
    # Patch all simulator state-changing functions so the auth test
    # never calls real Polygon or starts a real background task.
    _tick_stub = {
        "tick_at": "test",
        "symbols_evaluated": 0,
        "exits": [],
        "entries": [],
        "candidates": [],
        "errors": [],
    }
    with (
        patch("paper.simulator.start_simulator", new=AsyncMock()),
        patch("paper.simulator.stop_simulator", new=AsyncMock()),
        patch("paper.simulator.reset_simulator", new=AsyncMock()),
        patch("paper.simulator.run_tick", new=AsyncMock(return_value=_tick_stub)),
    ):
        for path in _PROTECTED_ENDPOINTS:
            resp = client.post(path, headers={"Authorization": f"Bearer {_TOKEN}"})
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"


# ── Safety invariant: no broker/order/AI in paper module ────────────────────

_BACKEND_DIR = pathlib.Path(__file__).parent.parent
_PAPER_DIR = _BACKEND_DIR / "paper"

_BROKER_PATTERNS = [
    r"\balpaca\b",
    r"\balpaca_trade_api\b",
    r"\bibkr\b",
    r"\bib_insync\b",
    r"\binteractive_brokers\b",
    r"\bschwab\b",
    r"\btd_ameritrade\b",
]

_ORDER_PATTERNS = [
    r'["\'/](?:place|submit|create|execute|send)[_-]?orders?["\'/]',
    r'\bplace_order\b',
    r'\bsubmit_order\b',
    r'\bcreate_order\b',
    r'\bexecute_order\b',
    r'\bsend_order\b',
]

_AI_PATTERNS = [
    r'^\s*import\s+openai\b',
    r'^\s*from\s+openai\b',
    r'^\s*import\s+anthropic\b',
    r'^\s*from\s+anthropic\b',
    r'^\s*import\s+langchain\b',
    r'^\s*from\s+langchain\b',
]


def _paper_sources() -> list[tuple[pathlib.Path, str]]:
    results = []
    for f in _PAPER_DIR.rglob("*.py"):
        if "__pycache__" not in str(f):
            results.append((f, f.read_text(encoding="utf-8")))
    return results


def test_paper_module_no_broker_imports():
    violations = []
    for path, text in _paper_sources():
        for pattern in _BROKER_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"{path.name}: '{pattern}'")
    assert not violations, "Broker SDK in paper module:\n" + "\n".join(violations)


def test_paper_module_no_order_execution():
    violations = []
    for path, text in _paper_sources():
        for pattern in _ORDER_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"{path.name}: '{pattern}'")
    assert not violations, "Order execution in paper module:\n" + "\n".join(violations)


def test_paper_module_no_ai_llm_imports():
    violations = []
    for path, text in _paper_sources():
        for pattern in _AI_PATTERNS:
            if re.search(pattern, text, re.MULTILINE):
                violations.append(f"{path.name}: '{pattern}'")
    assert not violations, "AI/LLM imports in paper module:\n" + "\n".join(violations)


# ── Persistence / snapshot field tests ──────────────────────────────────────

def test_status_snapshot_fields(client):
    resp = client.get("/api/paper/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "snapshot_storage" in data
    assert data["snapshot_storage"] in ("memory", "redis_best_effort")
    assert isinstance(data["state_restored_from_snapshot"], bool)
    assert isinstance(data["restart_persistent"], bool)
    assert data["restore_source"] in ("none", "redis", "db")
    assert "persistence" not in data


def test_dashboard_snapshot_fields(client):
    resp = client.get("/api/paper/dashboard")
    assert resp.status_code == 200
    s = resp.json()["status"]
    assert "snapshot_storage" in s
    assert isinstance(s["restart_persistent"], bool)
    assert s["restore_source"] in ("none", "redis", "db")


# ── /api/status global endpoint ──────────────────────────────────────────────

def test_global_status_paper_simulator_available(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paper_simulator_available"] is True
    assert data["paper_trading_real_broker"] is False
    assert data["live_trading_enabled"] is False
    assert data["broker_connected"] is False
    assert "fake-money" in data["message"]


# ── Dashboard disclaimer test ─────────────────────────────────────────────────

def test_dashboard_disclaimer_content(client):
    resp = client.get("/api/paper/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    disc = body.get("disclaimer", "")
    assert "fake-money" in disc.lower() or "no broker" in disc.lower()
    assert "no live trading" in disc.lower() or "no real orders" in disc.lower()


# ── Entry / exit price selection (via account directly) ──────────────────────

def test_entry_uses_ask_price():
    """When ask is available, entry_price == ask."""
    acct = _make_account(1000.0)
    ask = 150.25
    pos = acct.enter_position("AAPL", ask, 300.0, "earnings")
    assert pos is not None
    assert pos.entry_price == ask


def test_entry_fallback_to_last_trade_price():
    """Simulate ask-unavailable path: caller passes last_trade_price as entry_price."""
    acct = _make_account(1000.0)
    last_trade = 148.50
    pos = acct.enter_position("AAPL", last_trade, 300.0, "earnings")
    assert pos is not None
    assert pos.entry_price == last_trade


def test_entry_rejected_when_price_zero():
    acct = _make_account(1000.0)
    result = acct.enter_position("AAPL", 0.0, 300.0, "earnings")
    assert result is None


def test_exit_uses_bid_price():
    """When bid is available, exit_price == bid."""
    acct = _make_account(1000.0)
    acct.enter_position("MSFT", 100.0, 200.0, "earnings")
    bid = 100.80
    trade = acct.exit_position("MSFT", bid, "take_profit")
    assert trade is not None
    assert trade.exit_price == bid


def test_exit_fallback_to_last_trade_price():
    """Simulate bid-unavailable: caller passes last_trade_price as exit_price."""
    acct = _make_account(1000.0)
    acct.enter_position("MSFT", 100.0, 200.0, "earnings")
    last_trade = 99.50
    trade = acct.exit_position("MSFT", last_trade, "stop_loss")
    assert trade is not None
    assert trade.exit_price == last_trade


# ── Tick-level tests using mocked Polygon + quality + catalysts ──────────────


def _quality_pass(symbol: str, ask: float = 100.0, bid: float = 99.9,
                  change_pct: float = 1.0, spread_pct: float = 0.10,
                  volume_ratio: float = 1.2) -> dict:
    return {
        "symbol": symbol,
        "tradable": True,
        "ask": ask,
        "bid": bid,
        "last_trade_price": (ask + bid) / 2,
        "spread_percent": spread_pct,
        "change_percent": change_pct,
        "volume_ratio": volume_ratio,
        # day/prev volumes so time-adjusted gate passes (ta_ratio = 3x prev, always >= min 0.8)
        "day_volume": 3_000_000,
        "previous_day_volume": 1_000_000,
        "rejection_reasons": [],
    }


def _catalyst(symbol: str, event_type: str = "earnings") -> dict:
    return {
        "symbol": symbol,
        "title": f"{symbol} catalyst",
        "classified_event_type": event_type,
        "raw_relevance_hint": "direct",
    }



@pytest.fixture(autouse=False)
def reset_simulator_state():
    """Reset the global simulator account before and after each tick test."""
    import paper.simulator as sim
    sim._account.reset()
    sim._last_prices.clear()
    sim._state["last_candidates"] = []
    sim._state["last_tick_at"] = None
    sim._state["last_error"] = None
    yield
    sim._account.reset()
    sim._last_prices.clear()


@pytest.mark.asyncio
async def test_tick_take_profit_exits_position(reset_simulator_state):
    """Tick detects take-profit threshold and exits."""
    import paper.simulator as sim

    sym = "AAPL"
    entry_price = 100.0
    # Manually put a position in the account at entry_price
    sim._account.enter_position(sym, entry_price, 200.0, "earnings")
    sim._last_prices[sym] = entry_price

    # bid is above take-profit threshold
    tp_price = entry_price * (1 + sim.settings.PAPER_TAKE_PROFIT_PERCENT / 100) + 0.01
    q = _quality_pass(sym, ask=tp_price + 0.05, bid=tp_price)

    async def fake_snapshot(s):
        return {}

    async def fake_prev(s):
        return {}

    with (
        patch.object(sim.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(sim.polygon_client, "get_previous_close", side_effect=fake_prev),
        patch("paper.simulator.evaluate_market_quality", return_value=q),
        patch("paper.simulator.collect_news_for_symbols", new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
    ):
        result = await sim.run_tick()

    assert len(result["exits"]) == 1
    assert result["exits"][0]["exit_reason"] == "take_profit"
    assert sym not in sim._account.positions


@pytest.mark.asyncio
async def test_tick_stop_loss_exits_position(reset_simulator_state):
    """Tick detects stop-loss threshold and exits."""
    import paper.simulator as sim

    sym = "TSLA"
    entry_price = 200.0
    sim._account.enter_position(sym, entry_price, 200.0, "earnings")
    sim._last_prices[sym] = entry_price

    sl_price = entry_price * (1 - sim.settings.PAPER_STOP_LOSS_PERCENT / 100) - 0.01
    q = _quality_pass(sym, ask=sl_price + 0.05, bid=sl_price)

    async def fake_snapshot(s):
        return {}

    async def fake_prev(s):
        return {}

    with (
        patch.object(sim.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(sim.polygon_client, "get_previous_close", side_effect=fake_prev),
        patch("paper.simulator.evaluate_market_quality", return_value=q),
        patch("paper.simulator.collect_news_for_symbols", new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert len(result["exits"]) == 1
    assert result["exits"][0]["exit_reason"] == "stop_loss"


@pytest.mark.asyncio
async def test_tick_max_hold_time_exits_position(reset_simulator_state):
    """Tick detects max hold time exceeded and exits."""
    import paper.simulator as sim
    from paper.models import Position

    sym = "NVDA"
    entry_price = 150.0
    sim._account.enter_position(sym, entry_price, 200.0, "earnings")
    # Backdate the entry time to exceed max hold
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=sim.settings.PAPER_MAX_HOLD_MINUTES + 1)).isoformat()
    sim._account.positions[sym].entry_time = old_time
    sim._last_prices[sym] = entry_price

    q = _quality_pass(sym, ask=entry_price + 0.10, bid=entry_price)  # neutral price

    async def fake_snapshot(s):
        return {}

    async def fake_prev(s):
        return {}

    with (
        patch.object(sim.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(sim.polygon_client, "get_previous_close", side_effect=fake_prev),
        patch("paper.simulator.evaluate_market_quality", return_value=q),
        patch("paper.simulator.collect_news_for_symbols", new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert any(e["exit_reason"] == "max_hold_time" for e in result["exits"])


@pytest.mark.asyncio
async def test_tick_respects_max_positions(reset_simulator_state):
    """Tick does not open more positions than max_positions allows."""
    import paper.simulator as sim

    # Fill positions to the max with symbols from the default universe
    universe = sim.settings.paper_universe_list()
    for sym in universe[:sim.settings.PAPER_MAX_POSITIONS]:
        sim._account.enter_position(sym, 100.0, 50.0, "earnings")

    # Make every symbol in the universe look eligible
    def fake_evaluate(snap, prev):
        s = snap.get("_sym", "")
        return _quality_pass(s) if s else {"tradable": False, "rejection_reasons": ["no sym"]}

    async def fake_snapshot(s):
        return {"_sym": s}

    async def fake_prev(s):
        return {}

    all_cats = [_catalyst(s) for s in universe]

    with (
        patch.object(sim.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(sim.polygon_client, "get_previous_close", side_effect=fake_prev),
        patch("paper.simulator.evaluate_market_quality", side_effect=fake_evaluate),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": all_cats}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=None)),
        patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert len(result["entries"]) == 0


@pytest.mark.asyncio
async def test_tick_no_duplicate_position_same_symbol(reset_simulator_state):
    """Tick will not open a second position for a symbol already held."""
    import paper.simulator as sim

    sym = "AAPL"
    sim._account.enter_position(sym, 100.0, 200.0, "earnings")

    def fake_evaluate(snap, prev):
        s = snap.get("_sym", "")
        if s == sym:
            return _quality_pass(s)
        return {"tradable": False, "rejection_reasons": ["test-mock"]}

    async def fake_snapshot(s):
        return {"_sym": s}

    async def fake_prev(s):
        return {}

    with (
        patch.object(sim.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(sim.polygon_client, "get_previous_close", side_effect=fake_prev),
        patch("paper.simulator.evaluate_market_quality", side_effect=fake_evaluate),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": [_catalyst(sym)]}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert len(result["entries"]) == 0
    blocked = [c for c in result["candidates"] if c["symbol"] == sym]
    assert blocked and "blocked" in (blocked[0].get("action") or "")


# ── Background loop: no duplicate tasks ──────────────────────────────────────

@pytest.mark.asyncio
async def test_start_twice_no_duplicate_task(reset_simulator_state):
    """Calling start_simulator() twice should not spawn a second background task."""
    import paper.simulator as sim

    with patch("paper.simulator._loop", new=AsyncMock()):
        await sim.start_simulator()
        task_after_first = sim._simulator_task
        await sim.start_simulator()  # should be a no-op
        task_after_second = sim._simulator_task
        assert task_after_first is task_after_second
        await sim.stop_simulator()


@pytest.mark.asyncio
async def test_reset_while_running_stops_loop_and_clears_state(reset_simulator_state):
    """reset_simulator() stops the background loop and returns account to initial state."""
    import paper.simulator as sim

    with patch("paper.simulator._loop", new=AsyncMock()):
        await sim.start_simulator()
        assert sim._state["running"] is True

    # Enter a position so there's something to clear
    sim._account.enter_position("AAPL", 100.0, 200.0, "earnings")

    with patch("paper.simulator._save_state", new=AsyncMock()):
        await sim.reset_simulator()

    assert sim._state["running"] is False
    assert sim._account.positions == {}
    assert sim._account.cash == sim._account.starting_cash


# ── scoring.py unit tests ─────────────────────────────────────────────────────

from paper.scoring import score_candidate


def _full_quality(
    tradable: bool = True,
    spread_pct: float = 0.03,
    change_pct: float = 2.5,
    vol_ratio: float = 1.6,
) -> dict:
    return {
        "tradable": tradable,
        "spread_percent": spread_pct,
        "change_percent": change_pct,
        "volume_ratio": vol_ratio,
        "rejection_reasons": [] if tradable else ["low volume"],
    }


def test_scoring_high_quality_strong_catalyst_passes():
    """Tradable + tight spread + strong momentum + high-value catalyst => score >= 70."""
    q = _full_quality()
    cats = [{"classified_event_type": "earnings"}]
    result = score_candidate("AAPL", q, cats)
    assert result["score_pass"] is True
    assert result["total_score"] >= 70
    assert result["components"]["market_quality_score"] == 25
    assert result["components"]["catalyst_score"] == 20


def test_scoring_no_catalyst_gives_zero_catalyst_score():
    """No catalysts results in catalyst_score == 0 and a negative reason."""
    q = _full_quality()
    result = score_candidate("AAPL", q, [])
    assert result["components"]["catalyst_score"] == 0
    assert any("catalyst" in r for r in result["negative_reasons"])


def test_scoring_negative_change_fails_momentum_and_adds_penalty():
    """Negative change_percent => momentum_score == 0 and risk_penalty includes price-declining penalty."""
    q = _full_quality(change_pct=-1.0)
    cats = [{"classified_event_type": "earnings"}]
    result = score_candidate("AAPL", q, cats)
    assert result["components"]["momentum_score"] == 0
    assert result["components"]["risk_penalty"] <= -10
    assert any("declining" in r or "non-positive" in r for r in result["negative_reasons"])


def test_scoring_wide_spread_gives_zero_spread_score_and_penalty():
    """Spread > 0.50% => spread_score == 0 and risk_penalty includes spread penalty."""
    q = _full_quality(spread_pct=0.60)
    cats = [{"classified_event_type": "earnings"}]
    result = score_candidate("AAPL", q, cats)
    assert result["components"]["spread_score"] == 0
    assert result["components"]["risk_penalty"] <= -10
    assert any("spread" in r for r in result["negative_reasons"])


def test_scoring_untradable_gives_zero_market_quality_and_penalty():
    """Untradable quality => market_quality_score == 0 and risk_penalty includes untradable penalty."""
    q = _full_quality(tradable=False)
    cats = [{"classified_event_type": "earnings"}]
    result = score_candidate("AAPL", q, cats)
    assert result["components"]["market_quality_score"] == 0
    assert result["components"]["risk_penalty"] <= -10
    assert any("not tradable" in r for r in result["negative_reasons"])


def test_scoring_total_score_clamped_to_zero():
    """Worst-case all-bad inputs: raw total would be negative, clamped to 0."""
    q = {
        "tradable": False,
        "spread_percent": 0.80,
        "change_percent": -5.0,
        "volume_ratio": 0.3,
        "rejection_reasons": ["low volume"],
    }
    result = score_candidate("AAPL", q, [])
    assert result["total_score"] == 0
    assert result["score_pass"] is False


def test_scoring_returns_all_expected_keys():
    """score_candidate always returns the full expected schema."""
    result = score_candidate("MSFT", _full_quality(), [])
    for key in ("symbol", "total_score", "score_threshold", "score_pass",
                "components", "positive_reasons", "negative_reasons", "decision_reason"):
        assert key in result, f"Missing key: {key}"
    for comp in ("market_quality_score", "spread_score", "momentum_score",
                 "volume_score", "catalyst_score", "risk_penalty"):
        assert comp in result["components"], f"Missing component: {comp}"


# ── Simulator: score gate integration ────────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_score_below_threshold_does_not_enter(reset_simulator_state):
    """Symbol passes all hard gates but composite score < threshold => score_rejected, no entry."""
    import paper.simulator as sim

    sym = "AAPL"
    # Quality that passes all hard gates but yields a low score:
    # spread 0.40% (≤0.50 → hard gate ok, but spread_score=5)
    # change 0.30% (>0 → hard gate ok, but momentum_score=10)
    # vol_ratio 0.85 (≥0.8 → hard gate ok, but volume_score=5)
    # mid-value catalyst → catalyst_score=12
    # market_quality=25, risk_penalty=0 → total=57 < 70
    # day/prev volumes: ta_ratio = 0.85 at session end; always < 1.0 so volume_score ≤ 5
    q = {
        "tradable": True,
        "ask": 100.10,
        "bid": 99.70,
        "last_trade_price": 99.90,
        "spread_percent": 0.40,
        "change_percent": 0.30,
        "volume_ratio": 0.85,
        "day_volume": 850_000,
        "previous_day_volume": 1_000_000,
        "rejection_reasons": [],
    }
    cat = {"symbol": sym, "classified_event_type": "management_change"}

    def fake_evaluate(snap, prev):
        s = snap.get("_sym", "")
        return q if s == sym else {"tradable": False, "rejection_reasons": ["mock"]}

    async def fake_snapshot(s):
        return {"_sym": s}

    async def fake_prev(s):
        return {}

    with (
        patch.object(sim.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(sim.polygon_client, "get_previous_close", side_effect=fake_prev),
        patch("paper.simulator.evaluate_market_quality", side_effect=fake_evaluate),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": [cat]}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert len(result["entries"]) == 0
    aapl = next((c for c in result["candidates"] if c["symbol"] == sym), None)
    assert aapl is not None
    assert aapl["action"] == "score_rejected"
    assert aapl["score_pass"] is False
    assert aapl["total_score"] < sim.settings.PAPER_ENTRY_SCORE_THRESHOLD


@pytest.mark.asyncio
async def test_tick_score_above_threshold_enters_position(reset_simulator_state):
    """Symbol passes hard gates and composite score >= threshold => position entered."""
    import paper.simulator as sim

    sym = "AAPL"
    # Quality that passes hard gates with a high score:
    # tradable=True → 25; spread 0.03% → 15; change 2.5% → 20; vol_ratio 1.6 → 15
    # high-value catalyst (earnings) → 20; risk_penalty=0; total=95 >= 70
    q = {
        "tradable": True,
        "ask": 100.10,
        "bid": 100.00,
        "last_trade_price": 100.05,
        "spread_percent": 0.03,
        "change_percent": 2.5,
        "volume_ratio": 1.6,
        "day_volume": 1_600_000,
        "previous_day_volume": 1_000_000,
        "rejection_reasons": [],
    }
    cat = {"symbol": sym, "classified_event_type": "earnings"}

    def fake_evaluate(snap, prev):
        s = snap.get("_sym", "")
        return q if s == sym else {"tradable": False, "rejection_reasons": ["mock"]}

    async def fake_snapshot(s):
        return {"_sym": s}

    async def fake_prev(s):
        return {}

    with (
        patch.object(sim.polygon_client, "get_ticker_snapshot", side_effect=fake_snapshot),
        patch.object(sim.polygon_client, "get_previous_close", side_effect=fake_prev),
        patch("paper.simulator.evaluate_market_quality", side_effect=fake_evaluate),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": [cat]}})),
        patch("paper.simulator._save_state", new=AsyncMock()),
        patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert len(result["entries"]) == 1
    assert result["entries"][0]["symbol"] == sym
    assert sym in sim._account.positions
    aapl = next(c for c in result["candidates"] if c["symbol"] == sym)
    assert aapl["action"] == "entered"
    assert aapl["score_pass"] is True
    assert aapl["total_score"] >= sim.settings.PAPER_ENTRY_SCORE_THRESHOLD
