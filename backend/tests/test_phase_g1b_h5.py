"""
Phase G1B-H5 — unified wallet trading activity and analytics.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.

Sections:
  A — legacy ENGINE-only sections removed from dashboard source.
  B — unified Trading Activity section exists with correct defaults.
  C — wallet filter routing (all / engine / det_shadow / ai_shadow).
  D — OOS trade exclusion from normal performance metrics.
  E — raw/audit OOS fields still exposed.
  F — bottom analytics section labelled ENGINE-only.
  I — boundary invariants (H3 gate, forbidden tokens, no scoring changes).
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


def _page_src() -> str:
    p = pathlib.Path(__file__).parents[2] / "frontend" / "dashboard" / "app" / "page.tsx"
    if not p.exists():
        pytest.skip("page.tsx not found — frontend not mounted")
    return p.read_text(encoding="utf-8")


# ── Section A — legacy ENGINE-only sections removed ──────────────────────────

def test_no_standalone_engine_positions_section():
    """'Open Positions — ENGINE' section must not appear as a standalone section."""
    src = _page_src()
    # The old section had a comment tag "Open positions — engine wallet (backward-compat)"
    assert "Open positions — engine wallet (backward-compat)" not in src


def test_no_standalone_engine_trades_section():
    """'Closed Trades — ENGINE' section must not appear as a standalone section."""
    src = _page_src()
    assert "Closed trades — engine wallet (backward-compat)" not in src


# ── Section B — unified Trading Activity section ─────────────────────────────

def test_trading_activity_section_exists():
    """Dashboard renders a unified 'Trading Activity' section."""
    src = _page_src()
    assert "Trading Activity" in src


def test_default_wallet_filter_is_all():
    """WalletExplorer default value is 'all' (All wallets)."""
    src = _page_src()
    # useState initialises to "all"
    assert 'useState<string>("all")' in src


def test_wallet_explorer_title_shows_filter_label():
    """WalletExplorer h3 titles include the dynamic filterLabel variable."""
    src = _page_src()
    assert "filterLabel" in src
    assert "Open Positions —" in src
    assert "Closed Trades —" in src


# ── Section C — wallet filter routing ────────────────────────────────────────

def test_all_wallets_positions_returns_all_three(client, monkeypatch):
    """No wallet_id filter → positions from engine + deterministic_shadow + ai_shadow."""
    from paper import simulator, shadow_wallets as sw
    monkeypatch.setattr(simulator, "get_positions", lambda: [
        {"position_id": "e1", "symbol": "ENG", "entry_time": "2026-06-12T14:00:00+00:00",
         "entry_price": 100.0, "current_price": 102.0, "shares": 1, "cost_basis": 100.0,
         "unrealized_pnl": 2.0, "unrealized_pnl_percent": 2.0, "entry_catalyst_type": "news"},
    ])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [
        {"position_id": "d1", "symbol": "DET", "entry_time": "2026-06-12T14:00:00+00:00",
         "wallet_id": wid, "strategy_id": wid, "entry_price": 50.0, "current_price": 51.0,
         "shares": 2, "cost_basis": 100.0, "unrealized_pnl": 2.0, "unrealized_pnl_percent": 2.0,
         "entry_catalyst_type": "news"},
    ])
    r = client.get("/api/paper/wallets/positions")
    assert r.status_code == 200
    symbols = [p["symbol"] for p in r.json()["positions"]]
    assert "ENG" in symbols
    assert "DET" in symbols  # from both shadow wallets


def test_engine_filter_returns_only_engine(client, monkeypatch):
    """wallet_id=engine returns only engine positions."""
    from paper import simulator, shadow_wallets as sw
    monkeypatch.setattr(simulator, "get_positions", lambda: [
        {"position_id": "e1", "symbol": "ENG", "entry_time": "2026-06-12T14:00:00+00:00",
         "entry_price": 100.0, "current_price": 101.0, "shares": 1, "cost_basis": 100.0,
         "unrealized_pnl": 1.0, "unrealized_pnl_percent": 1.0, "entry_catalyst_type": "news"},
    ])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [])
    r = client.get("/api/paper/wallets/positions?wallet_id=engine")
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_id"] == "engine"
    assert all(p.get("wallet_id") == "engine" for p in body["positions"])


def test_deterministic_shadow_filter(client, monkeypatch):
    """wallet_id=deterministic_shadow returns only deterministic_shadow positions."""
    from paper import shadow_wallets as sw
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [
        {"position_id": "d1", "symbol": "DET", "wallet_id": wid, "strategy_id": wid,
         "entry_time": "2026-06-12T14:00:00+00:00", "entry_price": 50.0, "current_price": 51.0,
         "shares": 1, "cost_basis": 50.0, "unrealized_pnl": 1.0, "unrealized_pnl_percent": 2.0,
         "entry_catalyst_type": "news"},
    ] if wid == sw.WALLET_DETERMINISTIC else [])
    r = client.get(f"/api/paper/wallets/positions?wallet_id={sw.WALLET_DETERMINISTIC}")
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_id"] == sw.WALLET_DETERMINISTIC
    assert len(body["positions"]) == 1
    assert body["positions"][0]["symbol"] == "DET"


def test_positions_include_wallet_id_and_strategy_id(client, monkeypatch):
    """Every position row includes wallet_id and strategy_id fields."""
    from paper import simulator, shadow_wallets as sw
    monkeypatch.setattr(simulator, "get_positions", lambda: [
        {"position_id": "e1", "symbol": "A", "entry_time": "2026-06-12T14:00:00+00:00",
         "entry_price": 10.0, "current_price": 10.0, "shares": 1, "cost_basis": 10.0,
         "unrealized_pnl": 0.0, "unrealized_pnl_percent": 0.0, "entry_catalyst_type": "news"},
    ])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [])
    r = client.get("/api/paper/wallets/positions")
    assert r.status_code == 200
    for p in r.json()["positions"]:
        assert "wallet_id" in p
        assert "strategy_id" in p


# ── Section D — OOS trade exclusion from normal metrics ──────────────────────

def test_oos_trades_excluded_from_realized_pnl(client, monkeypatch):
    """OOS trades (exit_reason==invalid_out_of_session_entry_flatten) excluded from realized_pnl."""
    from paper import simulator, shadow_wallets as sw, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    trades = [
        {"position_id": "t1", "symbol": "GOOD", "pnl": 10.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "exit_reason": "take_profit_intrabar"},
        {"position_id": "t2", "symbol": "BAD", "pnl": 5.0,
         "exit_time": "2026-06-12T16:30:00+00:00", "entry_time": "2026-06-11T02:00:00+00:00",
         "exit_reason": "invalid_out_of_session_entry_flatten"},
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
    # Only the valid trade (pnl=10.0) should be in realized_pnl
    assert eng["realized_pnl"] == 10.0
    assert eng["closed_trades_count"] == 1  # only valid trades
    assert eng["winning_trades_count"] == 1


def test_oos_trades_excluded_from_win_rate(client, monkeypatch):
    """OOS trades do not inflate win_rate numerator."""
    from paper import simulator, shadow_wallets as sw, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    trades = [
        {"position_id": "t1", "symbol": "LOSE", "pnl": -3.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "exit_reason": "stop_loss_intrabar"},
        {"position_id": "t2", "symbol": "OOS_WIN", "pnl": 20.0,
         "exit_time": "2026-06-12T16:30:00+00:00", "entry_time": "2026-06-11T02:00:00+00:00",
         "exit_reason": "invalid_out_of_session_entry_flatten"},
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
    # Only valid trade is the loss — win_rate should be 0.0, not inflated
    assert eng["win_rate"] == 0.0
    assert eng["winning_trades_count"] == 0
    assert eng["losing_trades_count"] == 1


# ── Section E — raw/audit OOS fields exposed ─────────────────────────────────

def test_raw_pnl_includes_oos_trades(client, monkeypatch):
    """raw_realized_pnl_including_invalid includes both valid and OOS trade PnL."""
    from paper import simulator, shadow_wallets as sw, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    trades = [
        {"position_id": "t1", "symbol": "GOOD", "pnl": 10.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "exit_reason": "take_profit_intrabar"},
        {"position_id": "t2", "symbol": "BAD", "pnl": 5.0,
         "exit_time": "2026-06-12T16:30:00+00:00", "entry_time": "2026-06-11T02:00:00+00:00",
         "exit_reason": "invalid_out_of_session_entry_flatten"},
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
    assert eng["raw_realized_pnl_including_invalid"] == 15.0  # 10 + 5
    assert eng["invalid_out_of_session_realized_pnl"] == 5.0
    assert "raw_total_pnl_including_invalid" in eng
    assert "raw_return_percent_including_invalid" in eng


def test_best_wallet_ranking_uses_adjusted_pnl(client, monkeypatch):
    """best_wallet_by_total_pnl is determined by OOS-excluded total_pnl."""
    from paper import simulator, shadow_wallets as sw, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    # Engine has a big OOS win that should not count toward ranking
    engine_trades = [
        {"position_id": "t1", "symbol": "OOS", "pnl": 1000.0,
         "exit_time": "2026-06-12T16:30:00+00:00", "entry_time": "2026-06-11T02:00:00+00:00",
         "exit_reason": "invalid_out_of_session_entry_flatten"},
    ]
    det_trades = [
        {"position_id": "d1", "symbol": "DET", "pnl": 50.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "wallet_id": sw.WALLET_DETERMINISTIC, "strategy_id": sw.WALLET_DETERMINISTIC,
         "exit_reason": "take_profit_intrabar"},
    ]
    monkeypatch.setattr(simulator, "get_trades", lambda: engine_trades)
    monkeypatch.setattr(simulator, "get_positions", lambda: [])
    monkeypatch.setattr(sw, "get_trades", lambda wid: det_trades if wid == sw.WALLET_DETERMINISTIC else [])
    monkeypatch.setattr(sw, "get_positions", lambda wid, quality_map=None: [])
    monkeypatch.setattr(sw, "snapshot", lambda quality_map=None: {
        sw.WALLET_DETERMINISTIC: {"status": "active", "inactive_reason": None, "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
        sw.WALLET_AI: {"status": "inactive", "inactive_reason": "llm_disabled", "starting_cash": 1000.0, "cash": 1000.0, "equity": 1000.0, "daily_pnl": 0.0},
    })
    r = client.get("/api/paper/wallets/performance?session_date=2026-06-12")
    assert r.status_code == 200
    body = r.json()
    # Engine adjusted total_pnl should be 0 (OOS excluded); det_shadow should be 50.0
    eng = next(w for w in body["wallets"] if w["wallet_id"] == "engine")
    det = next(w for w in body["wallets"] if w["wallet_id"] == sw.WALLET_DETERMINISTIC)
    assert eng["total_pnl"] == 0.0
    assert det["total_pnl"] == 50.0
    # Best wallet must be deterministic_shadow (50 > 0), NOT engine
    assert body["best_wallet_by_total_pnl"] == sw.WALLET_DETERMINISTIC


# ── Section F — bottom analytics labelled ENGINE-only ────────────────────────

def test_analytics_section_labelled_engine_only():
    """The Analytics section must be explicitly labelled as ENGINE-only."""
    src = _page_src()
    assert "ENGINE Analytics" in src


def test_journal_report_labelled_engine_only():
    """The Today/Session Report must be explicitly labelled as engine-only."""
    src = _page_src()
    assert "ENGINE Journal Report" in src


def test_latest_session_trades_use_ny_timezone(client, monkeypatch):
    """Closed trades with ?latest_session=true resolve to America/New_York session date."""
    from paper import simulator, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    trades = [
        {"position_id": "t1", "symbol": "A", "pnl": 5.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "exit_reason": "take_profit_intrabar", "wallet_id": "engine", "strategy_id": "engine"},
    ]
    monkeypatch.setattr(simulator, "get_trades", lambda: trades)
    r = client.get("/api/paper/wallets/trades?latest_session=true&wallet_id=engine")
    assert r.status_code == 200
    body = r.json()
    assert body["session_date"] == "2026-06-12"
    assert len(body["trades"]) == 1


# ── Section I — boundary invariants ──────────────────────────────────────────

def test_h3_session_gate_still_blocks_weekends(client):
    """H3 session gate: entries_blocked returns True on Saturday (regression guard)."""
    from paper import eod, session as s
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, reason = eod.entries_blocked(sat)
    assert blocked is True
    assert reason == "market_closed_weekend"


def test_no_broker_live_order_tokens_in_performance():
    """Forbidden tokens must not appear in the performance endpoint."""
    src = pathlib.Path(__file__).parents[1] / "api" / "paper.py"
    text = src.read_text(encoding="utf-8")
    start = text.find("async def paper_wallet_performance")
    end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    for token in ("alpaca", "broker", "live_trading", "real_order", "place_order"):
        assert token not in section, f"Forbidden token '{token}' in paper_wallet_performance"


def test_no_broker_live_tokens_in_page():
    """page.tsx must not use forbidden tokens in the wallet performance components."""
    src = _page_src()
    # Isolate the new component section (after the G1B-H4 marker)
    start = src.find("// ── Phase G1B-H4: WalletPerfCard")
    section = src[start:] if start != -1 else src
    for token in ("alpaca", "real_order", "place_order"):
        assert token not in section, f"Forbidden token '{token}' found in wallet performance components"
