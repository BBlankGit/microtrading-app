"""
Phase G1B-H4 — wallet-scoped dashboard analytics and engine comparison.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.

Sections:
  A — GET /api/paper/wallets/performance structure and fields.
  B — session date behaviour (default → latest, explicit date filter).
  C — metric calculations (P&L, win-rate).
  D — dashboard source contains required types and fetch function.
  I — boundary invariants (forbidden tokens, best-wallet ranking).
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch(
        "paper.simulator.restore_paper_session",
        new=AsyncMock(return_value={"source": "none"}),
    ), patch(
        "paper.simulator._save_state",
        new=AsyncMock(return_value=None),
    ), patch(
        "marketdata.service.start_collector",
        new=AsyncMock(return_value={"started": True, "symbols": []}),
    ), patch(
        "intelligence.reddit.ensure_loaded",
        new=AsyncMock(return_value=None),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


# ── Section A — API endpoint structure ──────────────────────────────────────

def test_wallet_performance_returns_three_wallets(client):
    """Response contains exactly 3 wallets: engine, deterministic_shadow, ai_shadow."""
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    body = r.json()
    ids = [w["wallet_id"] for w in body["wallets"]]
    assert "engine" in ids
    assert "deterministic_shadow" in ids
    assert "ai_shadow" in ids
    assert len(body["wallets"]) == 3


def test_wallet_performance_required_fields(client):
    """Each wallet dict contains all required analytics fields."""
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    required = {
        "wallet_id", "strategy_id", "display_name", "status",
        "session_date", "starting_cash", "realized_pnl", "unrealized_pnl",
        "total_pnl", "return_percent", "open_positions_count",
        "closed_trades_count", "winning_trades_count", "losing_trades_count",
        "win_rate", "avg_trade_pnl", "best_trade_pnl", "worst_trade_pnl",
        "invalid_out_of_session_count", "eod_flatten_count",
    }
    for w in r.json()["wallets"]:
        missing = required - set(w.keys())
        assert not missing, f"{w['wallet_id']} missing fields: {missing}"


def test_wallet_performance_aggregate_fields(client):
    """Response includes aggregate comparison and session status fields."""
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    body = r.json()
    assert "best_wallet_by_total_pnl" in body
    assert "best_wallet_by_win_rate" in body
    assert "best_wallet_by_return_percent" in body
    assert "wallets_ranked_by_total_pnl" in body
    assert "market_session_open" in body
    assert "entries_allowed" in body
    assert "session_status" in body
    assert isinstance(body["wallets_ranked_by_total_pnl"], list)
    assert len(body["wallets_ranked_by_total_pnl"]) == 3


def test_wallet_performance_session_latest_param(client):
    """?session_date=latest is accepted and returns a non-empty session_date."""
    r = client.get("/api/paper/wallets/performance?session_date=latest")
    assert r.status_code == 200
    body = r.json()
    assert body["session_date"]
    assert len(body["session_date"]) == 10  # YYYY-MM-DD


# ── Section B — session date behaviour ──────────────────────────────────────

def test_wallet_performance_default_uses_latest_session(client, monkeypatch):
    """Omitting session_date resolves to latest_session_date_ny()."""
    from paper import session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    assert r.json()["session_date"] == "2026-06-12"


def test_wallet_performance_custom_session_date_filters_trades(client, monkeypatch):
    """Explicit session_date filters trades to that session only."""
    from paper import simulator, shadow_wallets as sw, session as s
    fake_trade = {
        "position_id": "t1",
        "symbol": "FAKE",
        "entry_time": "2026-06-11T14:00:00+00:00",
        "exit_time": "2026-06-11T15:00:00+00:00",
        "pnl": 5.0,
        "exit_reason": "take_profit_intrabar",
        "wallet_id": "engine",
        "strategy_id": "engine",
    }
    monkeypatch.setattr(simulator, "get_trades", lambda: [fake_trade])
    monkeypatch.setattr(simulator, "get_positions", lambda: [])
    monkeypatch.setattr(sw, "get_trades", lambda wid: [])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [])
    monkeypatch.setattr(sw, "snapshot", lambda quality_map=None: {
        sw.WALLET_DETERMINISTIC: {"status": "active", "inactive_reason": None, "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
        sw.WALLET_AI: {"status": "inactive", "inactive_reason": "llm_disabled", "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
    })
    # Trade is on 2026-06-11 → querying 2026-06-12 should give 0 trades
    r = client.get("/api/paper/wallets/performance?session_date=2026-06-12")
    assert r.status_code == 200
    engine_data = next(w for w in r.json()["wallets"] if w["wallet_id"] == "engine")
    assert engine_data["closed_trades_count"] == 0


# ── Section C — metric calculations ─────────────────────────────────────────

def test_wallet_performance_total_pnl_equals_realized_plus_unrealized(client, monkeypatch):
    """total_pnl == realized_pnl + unrealized_pnl for each wallet."""
    from paper import simulator, shadow_wallets as sw
    monkeypatch.setattr(simulator, "get_trades", lambda: [])
    monkeypatch.setattr(simulator, "get_positions", lambda: [
        {"position_id": "p1", "symbol": "X", "unrealized_pnl": 3.5, "entry_time": "2026-06-13T14:00:00+00:00"}
    ])
    monkeypatch.setattr(sw, "get_trades", lambda wid: [])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [])
    monkeypatch.setattr(sw, "snapshot", lambda quality_map=None: {
        sw.WALLET_DETERMINISTIC: {"status": "active", "inactive_reason": None, "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
        sw.WALLET_AI: {"status": "inactive", "inactive_reason": "llm_disabled", "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
    })
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    for w in r.json()["wallets"]:
        expected = round(w["realized_pnl"] + w["unrealized_pnl"], 4)
        assert abs(w["total_pnl"] - expected) < 1e-4, f"{w['wallet_id']}: total_pnl mismatch"


def test_wallet_performance_win_rate_calculation(client, monkeypatch):
    """win_rate = wins / total * 100 when trades present."""
    from paper import simulator, shadow_wallets as sw, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    trades = [
        {"position_id": "t1", "symbol": "A", "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00", "pnl": 10.0, "exit_reason": "take_profit_intrabar"},
        {"position_id": "t2", "symbol": "B", "exit_time": "2026-06-12T15:10:00+00:00", "entry_time": "2026-06-12T14:10:00+00:00", "pnl": -5.0, "exit_reason": "stop_loss_intrabar"},
        {"position_id": "t3", "symbol": "C", "exit_time": "2026-06-12T15:20:00+00:00", "entry_time": "2026-06-12T14:20:00+00:00", "pnl": 8.0, "exit_reason": "take_profit_intrabar"},
        {"position_id": "t4", "symbol": "D", "exit_time": "2026-06-12T15:30:00+00:00", "entry_time": "2026-06-12T14:30:00+00:00", "pnl": -2.0, "exit_reason": "stop_loss_intrabar"},
    ]
    monkeypatch.setattr(simulator, "get_trades", lambda: trades)
    monkeypatch.setattr(simulator, "get_positions", lambda: [])
    monkeypatch.setattr(sw, "get_trades", lambda wid: [])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [])
    monkeypatch.setattr(sw, "snapshot", lambda quality_map=None: {
        sw.WALLET_DETERMINISTIC: {"status": "active", "inactive_reason": None, "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
        sw.WALLET_AI: {"status": "inactive", "inactive_reason": "llm_disabled", "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
    })
    r = client.get("/api/paper/wallets/performance?session_date=2026-06-12")
    assert r.status_code == 200
    eng = next(w for w in r.json()["wallets"] if w["wallet_id"] == "engine")
    assert eng["closed_trades_count"] == 4
    assert eng["winning_trades_count"] == 2
    assert eng["losing_trades_count"] == 2
    assert eng["win_rate"] == 50.0


def test_wallet_performance_no_trades_gives_null_win_rate(client, monkeypatch):
    """win_rate is null when closed_trades_count == 0."""
    from paper import simulator, shadow_wallets as sw
    monkeypatch.setattr(simulator, "get_trades", lambda: [])
    monkeypatch.setattr(simulator, "get_positions", lambda: [])
    monkeypatch.setattr(sw, "get_trades", lambda wid: [])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [])
    monkeypatch.setattr(sw, "snapshot", lambda quality_map=None: {
        sw.WALLET_DETERMINISTIC: {"status": "active", "inactive_reason": None, "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
        sw.WALLET_AI: {"status": "inactive", "inactive_reason": "llm_disabled", "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
    })
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    for w in r.json()["wallets"]:
        if w["closed_trades_count"] == 0:
            assert w["win_rate"] is None


# ── Section D — dashboard source ────────────────────────────────────────────

def _read_frontend_page() -> str:
    p = pathlib.Path(__file__).parents[2] / "frontend" / "dashboard" / "app" / "page.tsx"
    if not p.exists():
        pytest.skip("page.tsx not found — frontend not mounted")
    return p.read_text(encoding="utf-8")


def test_dashboard_has_wallet_perf_response_type():
    """page.tsx defines WalletPerfResponse interface."""
    src = _read_frontend_page()
    assert "interface WalletPerfResponse" in src, "WalletPerfResponse type missing from page.tsx"
    assert "interface WalletPerf " in src or "interface WalletPerf\n" in src or "interface WalletPerf{" in src or "WalletPerf {" in src


def test_dashboard_has_fetch_wallet_performance():
    """page.tsx defines fetchWalletPerformance function."""
    src = _read_frontend_page()
    assert "fetchWalletPerformance" in src, "fetchWalletPerformance missing from page.tsx"
    assert "/api/paper/wallets/performance" in src


def test_dashboard_has_engine_performance_section():
    """page.tsx renders EnginePerformanceSection component."""
    src = _read_frontend_page()
    assert "EnginePerformanceSection" in src


def test_dashboard_has_wallet_daily_analytics():
    """page.tsx renders WalletDailyAnalytics component."""
    src = _read_frontend_page()
    assert "WalletDailyAnalytics" in src


# ── Section I — boundary invariants ─────────────────────────────────────────

def test_no_forbidden_tokens_in_performance_endpoint():
    """The new performance endpoint must not mention broker/live/real-order tokens."""
    src = pathlib.Path(__file__).parents[1] / "api" / "paper.py"
    text = src.read_text(encoding="utf-8")
    # Isolate just the performance function (between the two @router.get markers)
    start = text.find("async def paper_wallet_performance")
    end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    for token in ("alpaca", "broker", "live_trading", "real_order", "place_order"):
        assert token not in section, f"Forbidden token '{token}' found in paper_wallet_performance"


def test_best_wallet_by_total_pnl_is_highest(client, monkeypatch):
    """best_wallet_by_total_pnl must point to the wallet with the highest total_pnl."""
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    body = r.json()
    best_id = body["best_wallet_by_total_pnl"]
    wallets = body["wallets"]
    best_pnl = max(w["total_pnl"] for w in wallets)
    best_wallet = next(w for w in wallets if w["wallet_id"] == best_id)
    assert best_wallet["total_pnl"] == best_pnl
