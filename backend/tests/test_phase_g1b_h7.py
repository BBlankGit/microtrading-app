"""
Phase G1B-H7 — redesign dashboard around three separate engine accounts
and strengthen DB analysis readiness.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.

Sections:
  A — three account cards, no aggregate cash/equity account.
  B — three same-structure daily reports.
  C — three same-structure decision analytics.
  D — Trading Activity remains wallet-tagged.
  E — Wallet comparison ranks by OOS-adjusted metrics.
  F — Legacy ENGINE diagnostics moved/labelled clearly.
  G — deep-status field-family + per-engine separability extensions.
  I — boundary invariants (H3 gate, H5 OOS exclusion, forbidden tokens).
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


# ── Section A — three account cards, no aggregate ───────────────────────────

def test_engine_accounts_section_exists():
    """Dashboard must render an 'Engine Accounts' section with three cards."""
    src = _page_src()
    assert "Engine Accounts" in src
    assert "EngineAccountsSection" in src


def test_no_primary_aggregate_account_section():
    """The old single 'Account' section header must be gone."""
    src = _page_src()
    # The single Account section had this exact heading shape
    # ("<h2 className=\"text-xl font-semibold\">Account</h2>")
    assert ">Account<" not in src.replace(" ", "")


def test_engine_account_card_has_required_fields():
    """EngineAccountCard component renders all required fields."""
    src = _page_src()
    required = [
        "EngineAccountCard",
        "Cash", "Equity", "Realized P&amp;L", "Unrealized P&amp;L",
        "Total P&amp;L", "Daily P&amp;L", "Return %",
        "Open positions", "Closed trades", "Win rate",
        "Avg trade P&amp;L", "Best trade", "Worst trade",
        "Invalid OOS count", "Last update",
    ]
    for token in required:
        assert token in src, f"Engine account card missing field: {token}"


def test_engine_accounts_renders_all_three_wallets():
    """Engine Accounts section passes engine, deterministic_shadow, ai_shadow."""
    src = _page_src()
    # Each card is instantiated with its wallet_id
    for wid in ('walletId="engine"', 'walletId="deterministic_shadow"', 'walletId="ai_shadow"'):
        assert wid in src


def test_ai_shadow_inactive_reason_surface():
    """Inactive reason is shown on the account card when wallet is inactive."""
    src = _page_src()
    assert "snapshot?.inactive_reason" in src or "inactive_reason}" in src


def test_no_combined_cash_equity_total():
    """No primary stat aggregating cash/equity across all three engines."""
    src = _page_src()
    # The phrase "All wallets cash" / "All accounts shared" must not appear
    assert "All wallets cash" not in src
    assert "All accounts shared" not in src
    assert "All accounts cash" not in src
    # And the explicit independence label must be present
    assert "No combined cash/equity total" in src or "independent of other engines" in src


# ── Section B — three same-structure daily reports ─────────────────────────

def test_engine_daily_reports_section_exists():
    src = _page_src()
    assert "Engine Daily Reports" in src
    assert "EngineDailyReportsSection" in src


def test_daily_report_card_has_required_fields():
    src = _page_src()
    required = [
        "Trades closed", "Wins / Losses", "Win rate",
        "Realized P&amp;L", "Unrealized P&amp;L", "Total P&amp;L",
        "Return %", "Avg trade P&amp;L", "Best trade", "Worst trade",
        "Current open", "EOD flatten", "Invalid OOS", "Last trade",
    ]
    for token in required:
        assert token in src, f"Daily report card missing field: {token}"


def test_daily_report_shows_no_trades_state():
    """When a wallet has no trades, the report must say so explicitly."""
    src = _page_src()
    assert "No trades for this session" in src


# ── Section C — three same-structure decision analytics ─────────────────────

def test_engine_decision_analytics_section_exists():
    src = _page_src()
    assert "Engine Decision Analytics" in src
    assert "EngineDecisionAnalyticsSection" in src


def test_wallets_analytics_endpoint_returns_three_engines(client):
    """GET /api/paper/wallets/analytics returns engine + 2 shadows with same shape."""
    r = client.get("/api/paper/wallets/analytics")
    assert r.status_code == 200
    body = r.json()
    for key in ("engine", "deterministic_shadow", "ai_shadow"):
        assert key in body
        assert body[key]["wallet_id"] == key
        assert body[key]["strategy_id"] == key
        assert "candidate_pool_size" in body[key]


def test_ai_shadow_analytics_marked_no_paid_ai(client):
    """AI shadow analytics object explicitly flags no_paid_ai_calls."""
    r = client.get("/api/paper/wallets/analytics")
    body = r.json()
    ai = body["ai_shadow"]
    assert ai["no_paid_ai_calls"] is True
    assert "provider_note" in ai
    assert "openai" not in ai["provider_note"].lower()
    assert "anthropic" not in ai["provider_note"].lower()


def test_deterministic_shadow_analytics_has_decision_counts(client):
    """Deterministic shadow analytics has WOULD_ENTER/WATCH/WOULD_REJECT counts."""
    r = client.get("/api/paper/wallets/analytics")
    body = r.json()
    det = body["deterministic_shadow"]
    for key in ("would_enter_count", "watch_count", "would_reject_count", "average_score"):
        assert key in det


def test_analytics_section_does_not_silently_use_engine_for_shadows():
    """Shadow/AI analytics cards must not reference engine's funnel."""
    src = _page_src()
    # The card variants explicitly switch on `kind` and shadow/AI branches
    # have their own structure (not candidate_funnel from engine analytics)
    assert 'kind === "deterministic_shadow"' in src
    assert 'kind === "ai_shadow"' in src


# ── Section D — Trading Activity wallet-tagged ──────────────────────────────

def test_trading_activity_remains_wallet_tagged():
    src = _page_src()
    assert "Trading Activity" in src
    # The inner table headers include Wallet and Strategy columns
    assert '"Wallet"' in src and '"Strategy"' in src


# ── Section E — wallet comparison ranks by OOS-adjusted ─────────────────────

def test_best_wallet_ranking_excludes_oos_trades(client, monkeypatch):
    """Wallet comparison uses OOS-excluded total_pnl for ranking (regression of H5)."""
    from paper import simulator, shadow_wallets as sw, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
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
    body = r.json()
    assert body["best_wallet_by_total_pnl"] == sw.WALLET_DETERMINISTIC


# ── Section F — Legacy ENGINE diagnostics moved to bottom ──────────────────

def test_legacy_engine_diagnostics_at_bottom():
    src = _page_src()
    assert "Legacy ENGINE-only diagnostics" in src
    assert "Advanced diagnostics" in src
    # And it's still inside a details element (collapsed)
    idx = src.find("Legacy ENGINE-only diagnostics")
    detail_open = src.rfind("<details", 0, idx)
    assert detail_open != -1


# ── Section G — deep-status field-family + per-engine separability ─────────

def test_deep_status_reports_field_family_coverage(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        coverage = body.get("extras_json_field_family_coverage")
        assert isinstance(coverage, dict)
        for family in (
            "marketdata", "catalyst_news", "reddit", "earnings",
            "insider", "market_regime_trend",
            "deterministic_shadow", "ai_shadow", "ai_shadow_disabled_state",
        ):
            assert family in coverage, f"missing field family: {family}"
            assert "coverage_percent" in coverage[family]
            assert "sample_size" in coverage[family]


def test_deep_status_reports_per_engine_separability(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        readiness = body["analysis_readiness"]
        assert "per_engine_trade_counts" in readiness
        counts = readiness["per_engine_trade_counts"]
        for key in ("engine", "deterministic_shadow", "ai_shadow", "unattributed_missing_wallet_id"):
            assert key in counts
        assert "engine_data_separable" in readiness
        assert "deterministic_shadow_data_separable" in readiness
        assert "ai_shadow_data_separable" in readiness


def test_deep_status_reports_outcome_joinability_by_horizon(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        readiness = body["analysis_readiness"]
        assert "distinct_candidates_with_any_outcome" in readiness
        assert "candidates_with_all_5_horizons" in readiness
        assert "missing_outcome_count_by_horizon" in readiness


def test_deep_status_reports_candidate_tick_and_missing(client):
    """Deep status reports candidate created_at min/max and missing tick_id count."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        cand = body["candidates"]
        assert "min_created_at" in cand
        assert "max_created_at" in cand
        assert "missing_tick_id" in cand


def test_deep_status_reports_trade_wallet_completeness(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        trd = body["trades"]
        assert "by_wallet_id" in trd
        assert "by_strategy_id" in trd
        assert "missing_wallet_id" in trd
        assert "missing_strategy_id" in trd


# ── Section I — boundary invariants ─────────────────────────────────────────

def test_h3_session_gate_still_blocks_weekends():
    from paper import eod, session as s
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, reason = eod.entries_blocked(sat)
    assert blocked is True
    assert reason == "market_closed_weekend"


def test_h5_oos_exclusion_still_works(client, monkeypatch):
    """OOS trades remain excluded from realized_pnl (regression guard for H5)."""
    from paper import simulator, shadow_wallets as sw, session as s
    monkeypatch.setattr(s, "latest_session_date_ny", lambda: "2026-06-12")
    trades = [
        {"position_id": "t1", "symbol": "GOOD", "pnl": 10.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "exit_reason": "take_profit_intrabar"},
        {"position_id": "t2", "symbol": "BAD", "pnl": 99.0,
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
    eng = next(w for w in r.json()["wallets"] if w["wallet_id"] == "engine")
    assert eng["realized_pnl"] == 10.0


def test_no_broker_tokens_in_analytics_endpoint():
    """Forbidden tokens must not appear in the new analytics endpoint."""
    src = pathlib.Path(__file__).parents[1] / "api" / "paper.py"
    text = src.read_text(encoding="utf-8")
    start = text.find("async def paper_wallet_analytics")
    end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    for token in ("alpaca", "broker_connected", "live_trading", "real_order", "place_order"):
        assert token not in section, f"Forbidden token '{token}' in paper_wallet_analytics"


def test_no_paid_ai_calls_in_analytics_endpoint():
    """Paid AI providers must not appear in the analytics endpoint code."""
    src = pathlib.Path(__file__).parents[1] / "api" / "paper.py"
    text = src.read_text(encoding="utf-8")
    start = text.find("async def paper_wallet_analytics")
    end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    # The endpoint references "no_paid_ai_calls" flag — but must not invoke
    # any paid provider library. Check for client invocation patterns.
    for token in ("openai.Client", "openai_client", "OpenAI(", "Anthropic("):
        assert token not in section, f"Paid AI provider call '{token}' found"
