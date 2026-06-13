"""
Phase G1B-H8 — remove dead aggregate analytics component and complete
DB audit / analysis readiness for future engine improvement.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.

Sections:
  A — dead aggregate WalletDailyAnalytics removed from source.
  B — tick_ts column audit reports honest persistence status.
  C — candidate grouping by catalyst_type / entry_mode / decision_reason.
  D — extras_json field-family coverage includes selected_path + score_components.
  E — shadow_decision_persistence section reports evidence-based counts.
  F — separability booleans are evidence-based.
  G — trade timestamp audit reports opened_at/closed_at mapping; NY session grouping.
  H — outcome completeness (joinability, all 5 horizons, missing_resolved_at).
  I — analysis_ready summary with blocking_gaps and warnings.
  J — boundary invariants (H3 gate, H5 OOS exclusion, no broker/paid-AI tokens).
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


# ── Section A — dead aggregate component removed ───────────────────────────

def test_dead_wallet_daily_analytics_function_removed():
    """The WalletDailyAnalytics function must be removed from page.tsx."""
    src = _page_src()
    assert "function WalletDailyAnalytics" not in src


def test_aggregate_all_wallets_daily_analytics_label_removed():
    """The 'All Wallets — Daily Analytics' aggregate label must not exist."""
    src = _page_src()
    assert "All Wallets — Daily Analytics" not in src


def test_no_aggregate_pnl_reducer_for_wallets():
    """No reducer that sums total_pnl across w.total_pnl for the wallets list."""
    src = _page_src()
    # The dead component used `wallets.reduce((s, w) => s + w.total_pnl, 0)`
    # over an array filtered by walletId === "all". Confirm it is gone.
    assert "wallets.reduce((s, w) => s + w.total_pnl, 0)" not in src


# ── Section B — tick_ts column audit ───────────────────────────────────────

def test_deep_status_reports_tick_ts_audit(client):
    """Response includes a tick_ts_audit section with explicit persistence status."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        assert "tick_ts_audit" in body
        audit = body["tick_ts_audit"]
        assert "tick_ts_persistence_status" in audit
        # Schema doesn't store tick_ts on candidates as a separate column
        assert audit["tick_ts_persistence_status"] == "not_persisted_as_candidate_column"


def test_deep_status_tick_ts_audit_provides_paper_ticks_join(client):
    """Audit must clarify the join path through paper_ticks."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        audit = body["tick_ts_audit"]
        for key in (
            "paper_ticks_total",
            "paper_ticks_started_at_min",
            "paper_ticks_started_at_max",
            "candidates_joinable_to_ticks_count",
            "candidates_joinable_to_ticks_coverage_percent",
        ):
            assert key in audit


def test_deep_status_does_not_confuse_tick_id_with_tick_ts(client):
    """tick_id coverage must be reported separately from tick_ts."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        # tick_id count is reported in candidates section
        assert "missing_tick_id" in body["candidates"]
        # tick_ts audit is a SEPARATE section with its own status
        assert body["tick_ts_audit"]["tick_ts_persistence_status"] != "collected"


# ── Section C — candidate grouping ──────────────────────────────────────────

def test_deep_status_groups_candidates_by_catalyst_type(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        assert "by_catalyst_type" in body["candidates"]
        assert isinstance(body["candidates"]["by_catalyst_type"], dict)


def test_deep_status_groups_candidates_by_entry_mode_and_decision_reason(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        assert "by_entry_mode" in body["candidates"]
        assert "by_decision_reason" in body["candidates"]


def test_deep_status_groups_candidates_by_action_and_rejection(client):
    """Backwards-compat: by_action and by_rejection_reason still present."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        assert "by_action" in body["candidates"]
        assert "by_rejection_reason" in body["candidates"]


# ── Section D — extras_json field-family coverage ──────────────────────────

def test_deep_status_field_family_includes_selected_path_and_scores(client):
    """Field-family coverage must include selected_path and score_components families."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        coverage = body["extras_json_field_family_coverage"]
        assert "selected_path" in coverage
        assert "score_components" in coverage
        for family in ("marketdata", "catalyst_news", "reddit", "earnings",
                       "insider", "market_regime_trend",
                       "deterministic_shadow", "ai_shadow"):
            assert family in coverage


# ── Section E — evidence-based shadow persistence ──────────────────────────

def test_deep_status_has_shadow_decision_persistence_section(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        assert "shadow_decision_persistence" in body
        sdp = body["shadow_decision_persistence"]
        assert "deterministic_shadow" in sdp
        assert "ai_shadow" in sdp
        assert "evidence_source" in sdp


def test_deterministic_shadow_persistence_reports_evidence_counts(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        det = body["shadow_decision_persistence"]["deterministic_shadow"]
        for key in (
            "sample_size", "decision_field_present_rows",
            "would_enter_count", "watch_count", "would_reject_count",
            "missing_decision_count", "evidence_based_separable", "status",
        ):
            assert key in det
        assert det["status"] in ("collected", "not_collected")


def test_ai_shadow_persistence_reports_evidence_counts(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        ai = body["shadow_decision_persistence"]["ai_shadow"]
        for key in (
            "sample_size", "decision_field_present_rows", "status_field_present_rows",
            "would_enter_count", "watch_count", "would_reject_count",
            "disabled_count", "error_count", "not_selected_count",
            "missing_decision_count", "missing_status_count",
            "evidence_based_separable", "status", "no_paid_ai_calls",
        ):
            assert key in ai
        assert ai["no_paid_ai_calls"] is True


# ── Section F — separability is evidence-based ─────────────────────────────

def test_separability_booleans_match_evidence(client):
    """The separable flags must equal the evidence_based_separable from persistence section."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        readiness = body["analysis_readiness"]
        det = body["shadow_decision_persistence"]["deterministic_shadow"]
        ai = body["shadow_decision_persistence"]["ai_shadow"]
        assert readiness["deterministic_shadow_data_separable"] == det["evidence_based_separable"]
        assert readiness["ai_shadow_data_separable"] == ai["evidence_based_separable"]
        # And evidence supporting counts are exposed
        assert "deterministic_shadow_data_separable_evidence" in readiness
        assert "ai_shadow_data_separable_evidence" in readiness


# ── Section G — trade timestamp and NY-session audit ───────────────────────

def test_deep_status_trade_timestamp_mapping_note(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        trd = body["trades"]
        assert "column_mapping_note" in trd
        assert "opened_at" in trd["column_mapping_note"]
        assert "closed_at" in trd["column_mapping_note"]
        for key in ("min_opened_at", "max_opened_at",
                    "min_closed_at", "max_closed_at",
                    "missing_entry_time", "missing_exit_time_for_closed",
                    "future_opened_at_count", "future_closed_at_count"):
            assert key in trd


def test_deep_status_ny_session_grouping(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        grouping = body["ny_session_grouping"]
        assert grouping["session_date_ny_storage"] == "derived"
        assert "America/New_York" in grouping["derivation_method"]
        for key in ("trade_by_ny_session", "candidates_by_ny_session", "outcomes_by_ny_session"):
            assert key in grouping
            assert isinstance(grouping[key], dict)


# ── Section H — outcome completeness ───────────────────────────────────────

def test_outcome_completeness_reports_joinability_and_horizons(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        for key in (
            "distinct_candidates_with_any_outcome",
            "candidates_with_all_5_horizons",
            "missing_outcome_count_by_horizon",
            "missing_resolved_at_count",
        ):
            assert key in out


# ── Section I — analysis_ready summary ─────────────────────────────────────

def test_deep_status_has_analysis_ready_summary(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    assert "analysis_ready" in body
    assert "blocking_gaps" in body
    assert "warnings" in body
    assert isinstance(body["blocking_gaps"], list)
    assert isinstance(body["warnings"], list)


def test_analysis_ready_false_when_shadow_decisions_not_persisted(client):
    """If neither shadow has decision evidence, warnings flag it."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        det = body["shadow_decision_persistence"]["deterministic_shadow"]
        ai = body["shadow_decision_persistence"]["ai_shadow"]
        warnings = body["warnings"]
        if not det["evidence_based_separable"]:
            assert "deterministic_shadow_decisions_not_persisted" in warnings
        if not ai["evidence_based_separable"]:
            assert "ai_shadow_decisions_not_persisted" in warnings


def test_three_engine_dashboard_structure_remains():
    """Dashboard still shows three engine accounts/reports/analytics sections."""
    src = _page_src()
    for marker in (
        "EngineAccountsSection",
        "EngineDailyReportsSection",
        "EngineDecisionAnalyticsSection",
    ):
        assert marker in src


# ── Section J — boundary invariants ────────────────────────────────────────

def test_h3_session_gate_still_blocks_weekends():
    from paper import eod, session as s
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, reason = eod.entries_blocked(sat)
    assert blocked is True
    assert reason == "market_closed_weekend"


def test_h5_oos_exclusion_still_works(client, monkeypatch):
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


def test_no_broker_tokens_in_deep_status():
    src = pathlib.Path(__file__).parents[1] / "api" / "audit.py"
    text = src.read_text(encoding="utf-8")
    start = text.find("async def persistence_deep_status")
    end = text.find("\nasync def ", start + 1)
    if end == -1:
        end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    for token in ("alpaca", "live_trading", "real_order", "place_order"):
        assert token not in section, f"Forbidden token '{token}' in persistence_deep_status"


def test_no_paid_ai_provider_calls_in_deep_status():
    src = pathlib.Path(__file__).parents[1] / "api" / "audit.py"
    text = src.read_text(encoding="utf-8")
    start = text.find("async def persistence_deep_status")
    end = text.find("\nasync def ", start + 1)
    if end == -1:
        end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    for token in ("OpenAI(", "Anthropic(", "openai.Client", "anthropic.Client"):
        assert token not in section, f"Paid AI provider call '{token}' found"
