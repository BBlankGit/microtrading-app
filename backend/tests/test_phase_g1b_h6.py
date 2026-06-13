"""
Phase G1B-H6 — wallet-aware journal/analytics cleanup and DB audit assurance.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.

Sections:
  A — legacy ENGINE-only journal/report/analytics sections renamed
      and grouped under collapsed "Legacy ENGINE diagnostics".
  B — deep persistence audit endpoint exists and reports required fields.
  C — DB audit response shape (candidate/outcome/trade/wallet/integrity).
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


# ── Section A — legacy ENGINE sections renamed/grouped ──────────────────────

def test_journal_history_renamed_to_legacy_engine():
    """Journal / History must be labelled as legacy ENGINE-only, not generic."""
    src = _page_src()
    assert "Legacy ENGINE Journal / History" in src
    # And the generic "Journal / History" label must not appear as a top-level h2 anymore
    # (renamed inside details element)
    assert ">Journal / History<" not in src.replace(" ", "")


def test_engine_journal_report_renamed_to_legacy():
    """ENGINE Journal Report must now be labelled 'Legacy ENGINE Journal Report'."""
    src = _page_src()
    assert "Legacy ENGINE Journal Report" in src


def test_engine_analytics_renamed_to_legacy():
    """ENGINE Analytics must now be labelled 'Legacy ENGINE Analytics'."""
    src = _page_src()
    assert "Legacy ENGINE Analytics" in src


def test_legacy_engine_diagnostics_group_exists():
    """Legacy ENGINE sections must be grouped under a collapsible details element."""
    src = _page_src()
    assert "Legacy ENGINE diagnostics" in src
    # The details element wraps them
    idx = src.find("Legacy ENGINE diagnostics")
    detail_open = src.rfind("<details", 0, idx)
    assert detail_open != -1, "Legacy ENGINE diagnostics must be inside a <details> element"


def test_no_silent_generic_analytics_section():
    """Generic unfiltered 'Analytics' h2 must not appear at top level."""
    src = _page_src()
    # An h2 with just "Analytics" as label
    assert "h2 className=\"text-lg font-semibold mb-3\">\n          Analytics\n" not in src


def test_no_silent_generic_today_session_report():
    """Generic 'Today / Session Report' h2 must not appear at top level."""
    src = _page_src()
    assert "Today / Session Report" not in src


# ── Section B — deep persistence audit endpoint exists ──────────────────────

def test_deep_status_endpoint_responds(client):
    """GET /api/audit/persistence/deep-status returns 200."""
    r = client.get("/api/audit/persistence/deep-status")
    assert r.status_code == 200


def test_deep_status_reports_candidate_coverage(client):
    """Deep audit reports candidate count and extras_json coverage."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    # Even with no DB pool, structure must be present (skipped path) OR full keys
    assert "ok" in body
    if body.get("ok"):
        assert "candidates" in body
        cand = body["candidates"]
        assert "total" in cand
        assert "with_extras_json" in cand
        assert "extras_json_coverage_percent" in cand


def test_deep_status_reports_outcome_breakdown(client):
    """Deep audit reports outcomes by horizon, status, source."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        assert "total" in out
        assert "by_status" in out
        assert "by_horizon" in out
        assert "by_source" in out


def test_deep_status_reports_trade_wallet_strategy_counts(client):
    """Deep audit reports trade counts by wallet_id and strategy_id."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        trd = body["trades"]
        assert "by_wallet_id" in trd
        assert "by_strategy_id" in trd
        assert isinstance(trd["by_wallet_id"], dict)


def test_deep_status_detects_missing_wallet_or_strategy(client):
    """Deep audit exposes counts of trade rows missing wallet_id or strategy_id."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        trd = body["trades"]
        assert "missing_wallet_id" in trd
        assert "missing_strategy_id" in trd
        assert isinstance(trd["missing_wallet_id"], int)


def test_deep_status_reports_timestamp_integrity(client):
    """Deep audit reports min/max timestamps and future-timestamp flag."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        # min/max present on candidates and trades
        assert "min_created_at" in body["candidates"]
        assert "max_created_at" in body["candidates"]
        assert "future_max_created_at" in body["candidates"]
        assert "min_created_at" in body["trades"]
        assert "future_max_created_at" in body["trades"]
        assert "timestamps" in body
        assert body["timestamps"]["stored_as"] == "TIMESTAMPTZ (UTC)"


def test_deep_status_confirms_candidate_outcome_joinable(client):
    """Deep audit confirms candidate → outcome joinability."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        readiness = body["analysis_readiness"]
        assert readiness.get("candidate_to_outcome_join_supported") is True
        assert "candidate_to_outcome_joinable_rows" in readiness


def test_deep_status_confirms_trade_wallet_separability(client):
    """Deep audit confirms trade rows can be separated by wallet/strategy."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        readiness = body["analysis_readiness"]
        assert "trade_to_wallet_separable" in readiness
        assert "trade_to_strategy_separable" in readiness
        assert readiness.get("wallet_breakdown_supported") == [
            "engine", "deterministic_shadow", "ai_shadow"
        ]


def test_deep_status_confirms_ny_session_filter(client):
    """Deep audit advertises NY session-date filtering support."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        readiness = body["analysis_readiness"]
        assert readiness.get("ny_session_filter_supported") is True
        assert "session_date_for" in readiness.get("ny_session_filter_note", "")


def test_deep_status_separates_invalid_out_of_session_trades(client):
    """Deep audit exposes the count of invalid out-of-session trades separately."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        trd = body["trades"]
        assert "invalid_out_of_session_count" in trd
        assert body["analysis_readiness"].get(
            "invalid_out_of_session_separable_via_exit_reason"
        ) is True


def test_deep_status_exposes_wallet_snapshots(client):
    """Deep audit reports current wallet snapshots (engine + 2 shadows)."""
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        snaps = body["wallet_snapshots"]
        ids = {s["wallet_id"] for s in snaps}
        assert "engine" in ids
        assert "deterministic_shadow" in ids
        assert "ai_shadow" in ids
        # Each snapshot has wallet_id + strategy_id
        for s in snaps:
            assert "wallet_id" in s and "strategy_id" in s


# ── Section C — trade row tagging guarantee ─────────────────────────────────

def test_wallet_trades_rows_include_wallet_id_and_strategy_id(client, monkeypatch):
    """Every row returned from /api/paper/wallets/trades includes wallet_id and strategy_id."""
    from paper import simulator, shadow_wallets as sw
    monkeypatch.setattr(simulator, "get_trades", lambda: [
        {"position_id": "t1", "symbol": "A", "pnl": 1.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "exit_reason": "take_profit_intrabar"},
    ])
    monkeypatch.setattr(sw, "get_trades", lambda wid: [
        {"position_id": "s1", "symbol": "B", "pnl": 2.0,
         "exit_time": "2026-06-12T15:00:00+00:00", "entry_time": "2026-06-12T14:00:00+00:00",
         "exit_reason": "take_profit_intrabar", "wallet_id": wid, "strategy_id": wid},
    ] if wid == sw.WALLET_DETERMINISTIC else [])
    r = client.get("/api/paper/wallets/trades")
    assert r.status_code == 200
    for t in r.json()["trades"]:
        assert "wallet_id" in t
        assert "strategy_id" in t


# ── Section I — boundary invariants ─────────────────────────────────────────

def test_h3_session_gate_still_blocks_weekends():
    """H3 session gate must still block weekends."""
    from paper import eod, session as s
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, reason = eod.entries_blocked(sat)
    assert blocked is True
    assert reason == "market_closed_weekend"


def test_no_broker_tokens_in_deep_status():
    """Forbidden tokens must not appear in the new deep-status endpoint code."""
    src = pathlib.Path(__file__).parents[1] / "api" / "audit.py"
    text = src.read_text(encoding="utf-8")
    start = text.find("async def persistence_deep_status")
    end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    for token in ("alpaca", "live_trading", "real_order", "place_order"):
        assert token not in section, f"Forbidden token '{token}' in persistence_deep_status"


def test_no_paid_ai_calls_in_deep_status():
    """Deep status must not invoke any paid AI providers."""
    src = pathlib.Path(__file__).parents[1] / "api" / "audit.py"
    text = src.read_text(encoding="utf-8")
    start = text.find("async def persistence_deep_status")
    end = text.find("\n@router.", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    for token in ("openai", "anthropic", "OpenAI", "Anthropic"):
        assert token.lower() not in section.lower(), f"Paid AI provider '{token}' referenced"
