"""
Phase G1B-H9 — close G1B-H8 audit caveats and verify DETERMINISTIC_SHADOW
activation.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.

Sections:
  A — DETERMINISTIC_SHADOW active by default; AI_SHADOW inactive until LLM enabled.
  C — extras_json field-family coverage has coverage_scope, status, keys_found.
  D — outcomes section reports direct resolved_at_null_count.
  E — outcomes section reports true missing-horizon-row counts.
  F — latest_session_date derived from trade/candidate/outcome sources.
  H — separate per-engine and overall freeze-audit readiness flags.
  I — dashboard surfaces enabled/processing/last_decision_at fields.
  J — boundary invariants (H3 gate, H5 OOS exclusion, dashboard structure,
       no broker/paid-AI tokens).
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


# ── Section A — DETERMINISTIC_SHADOW activation ─────────────────────────────

def test_paper_shadow_wallets_enabled_default_is_true():
    """Phase G1B-H9 Part A: master shadow switch defaults to True."""
    from core.config import settings
    assert settings.PAPER_SHADOW_WALLETS_ENABLED is True


def test_deterministic_shadow_specific_flag_exists_and_defaults_true():
    from core.config import settings
    assert settings.PAPER_DETERMINISTIC_SHADOW_ENABLED is True


def test_deterministic_shadow_active_by_default(client):
    """The deterministic shadow wallet is active in /api/paper/wallets by default."""
    r = client.get("/api/paper/wallets")
    body = r.json()
    det = body["deterministic_shadow"]
    assert det["status"] == "active"
    assert det["inactive_reason"] is None


def test_ai_shadow_inactive_due_llm_disabled_by_default(client):
    """AI_SHADOW remains inactive while LLM_SHADOW_ENABLED=false."""
    r = client.get("/api/paper/wallets")
    body = r.json()
    ai = body["ai_shadow"]
    assert ai["status"] == "inactive"
    assert ai["inactive_reason"] == "LLM_SHADOW_ENABLED=false"


def test_deterministic_shadow_does_not_depend_on_llm(client, monkeypatch):
    """Even when LLM is disabled, deterministic shadow is active."""
    from core.config import settings
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    r = client.get("/api/paper/wallets")
    det = r.json()["deterministic_shadow"]
    assert det["status"] == "active"
    assert det.get("depends_on_llm") is False


def test_deterministic_shadow_disabled_by_own_flag(client, monkeypatch):
    """Setting PAPER_DETERMINISTIC_SHADOW_ENABLED=false produces specific reason."""
    from core.config import settings
    monkeypatch.setattr(settings, "PAPER_DETERMINISTIC_SHADOW_ENABLED", False)
    r = client.get("/api/paper/wallets")
    det = r.json()["deterministic_shadow"]
    assert det["status"] == "inactive"
    assert det["inactive_reason"] == "PAPER_DETERMINISTIC_SHADOW_ENABLED=false"


def test_shadow_wallet_exposes_enabled_processing_config_fields(client):
    """Each shadow wallet snapshot includes enabled/processing/config fields."""
    r = client.get("/api/paper/wallets")
    body = r.json()
    for key in ("deterministic_shadow", "ai_shadow"):
        snap = body[key]
        assert "enabled" in snap
        assert "processing_enabled" in snap
        assert "enabled_by_config" in snap
        assert "last_entry_at" in snap
        assert "last_exit_at" in snap
        assert "last_decision_at" in snap
        assert isinstance(snap["enabled_by_config"], list)
        for entry in snap["enabled_by_config"]:
            assert "flag" in entry and "value" in entry


def test_ai_shadow_snapshot_carries_no_paid_ai_calls_flag(client):
    r = client.get("/api/paper/wallets")
    body = r.json()
    assert body["ai_shadow"].get("no_paid_ai_calls") is True


# ── Section C — coverage_scope and status on every field-family ────────────

def test_field_family_coverage_includes_scope_and_status(client):
    """Every field-family coverage object includes coverage_scope, status, keys_found."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        coverage = body["extras_json_field_family_coverage"]
        for family, obj in coverage.items():
            assert "coverage_scope" in obj, f"{family} missing coverage_scope"
            assert obj["coverage_scope"] in ("sampled", "full_table")
            assert "status" in obj
            assert obj["status"] in ("collected", "not_collected")
            assert "rows_present" in obj
            assert "keys_found" in obj
            assert isinstance(obj["keys_found"], list)


def test_field_family_coverage_status_matches_present_count(client):
    """status='collected' iff rows_present > 0; 'not_collected' otherwise."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        for family, obj in body["extras_json_field_family_coverage"].items():
            expected = "collected" if obj["rows_present"] > 0 else "not_collected"
            assert obj["status"] == expected, f"{family}: status mismatch"


# ── Section D — direct resolved_at_null_count ──────────────────────────────

def test_outcomes_include_direct_resolved_at_counts(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        assert "resolved_at_null_count" in out
        assert "resolved_at_present_count" in out
        # Their sum equals total
        assert out["resolved_at_null_count"] + out["resolved_at_present_count"] == out["total"]


def test_status_derived_missing_separate_from_direct(client):
    """Status-derived missing count is reported separately from direct null count."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        assert "status_derived_missing_resolved_at_count" in out
        assert "resolved_at_null_count" in out


# ── Section E — true missing horizon row detection ─────────────────────────

def test_outcomes_required_horizons_field(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        assert "required_horizons" in out
        assert isinstance(out["required_horizons"], list)
        assert len(out["required_horizons"]) >= 5


def test_outcomes_missing_horizon_row_detection(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        assert "missing_horizon_row_count_by_horizon" in out
        assert "horizon_row_coverage" in out
        for h_str, row in out["horizon_row_coverage"].items():
            assert "candidates_with_row" in row
            assert "candidates_missing_row" in row
            assert "resolved_rows" in row
            assert "pending_rows" in row


def test_outcomes_all_required_horizons_summary(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        assert "candidates_with_all_required_horizons" in out
        assert "candidates_missing_any_required_horizon" in out


# ── Section F — latest_session_date derivation ─────────────────────────────

def test_ny_session_has_per_source_latest_dates(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        ng = body["ny_session_grouping"]
        for key in (
            "latest_trade_session_date",
            "latest_candidate_session_date",
            "latest_outcome_session_date",
            "latest_session_date",
            "latest_session_date_source",
        ):
            assert key in ng


def test_latest_session_date_is_max_across_sources(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        ng = body["ny_session_grouping"]
        candidates = [
            ng["latest_trade_session_date"],
            ng["latest_candidate_session_date"],
            ng["latest_outcome_session_date"],
        ]
        available = [d for d in candidates if d]
        if available:
            assert ng["latest_session_date"] == max(available)
            assert ng["latest_session_date_source"] in ("trades", "candidates", "outcomes")
        else:
            assert ng["latest_session_date"] is None
            assert ng["latest_session_date_source"] == "no_data"


# ── Section H — separate per-engine readiness flags ────────────────────────

def test_separate_readiness_flags_present(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    assert "engine_analysis_ready" in body
    assert "deterministic_shadow_analysis_ready" in body
    assert "ai_shadow_analysis_ready" in body
    assert "overall_freeze_audit_ready" in body
    assert "ai_shadow_status_note" in body


def test_overall_ready_is_strict(client):
    """overall_freeze_audit_ready is True only when engine AND deterministic shadow AND no blocking gaps."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        overall = body["overall_freeze_audit_ready"]
        engine_ready = body["engine_analysis_ready"]
        det_ready = body["deterministic_shadow_analysis_ready"]
        blocking = body["blocking_gaps"]
        if overall:
            assert engine_ready and det_ready and not blocking


def test_ai_shadow_status_note_describes_state(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        note = body["ai_shadow_status_note"]
        assert note in (
            "ai_shadow_data_collected",
            "ai_shadow_inactive_or_decisions_not_persisted",
        )


# ── Section I — dashboard surfaces new fields ──────────────────────────────

def test_dashboard_account_card_supports_no_trades_state():
    """EngineAccountCard renders 'active — no trades this session' when active and empty."""
    src = _page_src()
    assert "active — no trades this session" in src


def test_dashboard_account_card_surfaces_disabled_config_reason():
    """When wallet is inactive, the card shows 'disabled by config:' reason."""
    src = _page_src()
    assert "disabled by config" in src


def test_walletsnapshot_interface_includes_new_h9_fields():
    src = _page_src()
    for key in (
        "enabled?: boolean",
        "processing_enabled?: boolean",
        "enabled_by_config?:",
        "depends_on_llm?: boolean",
        "last_entry_at?: string | null",
        "last_decision_at?: string | null",
    ):
        assert key in src


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


def test_three_engine_dashboard_structure_unchanged():
    src = _page_src()
    for marker in (
        "EngineAccountsSection",
        "EngineDailyReportsSection",
        "EngineDecisionAnalyticsSection",
    ):
        assert marker in src
    # No aggregate WalletDailyAnalytics resurrection
    assert "function WalletDailyAnalytics" not in src


def test_no_aggregate_account_total_reintroduced():
    """No primary aggregate cash/equity total across wallets."""
    src = _page_src()
    assert "All wallets cash" not in src
    assert "All accounts cash" not in src
    assert "wallets.reduce((s, w) => s + w.total_pnl, 0)" not in src


def test_no_broker_tokens_in_audit_or_shadow_modules():
    for rel in ("api/audit.py", "paper/shadow_wallets.py"):
        text = (pathlib.Path(__file__).parents[1] / rel).read_text(encoding="utf-8")
        for token in ("alpaca", "real_order", "place_order"):
            assert token not in text, f"Forbidden token '{token}' in {rel}"


def test_no_paid_ai_provider_calls():
    for rel in ("api/audit.py", "api/paper.py", "paper/shadow_wallets.py"):
        text = (pathlib.Path(__file__).parents[1] / rel).read_text(encoding="utf-8")
        for token in ("OpenAI(", "Anthropic(", "openai.Client", "anthropic.Client"):
            assert token not in text, f"Paid AI call '{token}' found in {rel}"
