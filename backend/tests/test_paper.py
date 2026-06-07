"""
Tests for the Phase 2A paper simulator.

All tests use in-memory state only. No broker. No real orders.
No real money. Research-only fake-money simulation.
"""
import pathlib
import re

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
