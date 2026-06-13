"""
Phase G1B-H10 — close G1B-H9 Codex blockers.

Includes DB-seeded exact-value tests using a substring-routed mock pool,
plus tests for:
  - true deterministic last_decision_at independent of entries (Part C)
  - resolved_at_min / resolved_at_max aliases (Part D)
  - status/config fields exposed on all wallet APIs (Part B)
  - dashboard structure invariants
  - H3 session gate, H5 OOS exclusion (regression guards)
  - no broker / paid AI tokens.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.
"""
from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

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


# ════════════════════════════════════════════════════════════════════════════
# Substring-routed mock pool — used for DB-seeded exact-value tests.
# Maps SQL-substring → return value (or callable taking *params).
# ════════════════════════════════════════════════════════════════════════════

class _MockRow(dict):
    """asyncpg Record-like dict that supports both ['key'] and .get('key')."""
    def __getitem__(self, key):
        return super().__getitem__(key)


class _MockConn:
    def __init__(self, routes: dict):
        self.routes = routes

    def _route(self, sql: str, params):
        # Normalise whitespace once so route keys don't need to match exact
        # indentation. Then find the most-specific (longest) substring key.
        norm = re.sub(r"\s+", " ", sql).strip()
        matches = sorted(
            (k for k in self.routes if re.sub(r"\s+", " ", k).strip() in norm),
            key=lambda k: len(re.sub(r"\s+", " ", k).strip()),
            reverse=True,
        )
        if not matches:
            return None
        val = self.routes[matches[0]]
        return val(*params) if callable(val) else val

    async def fetchval(self, sql, *params):
        return self._route(sql, params)

    async def fetchrow(self, sql, *params):
        v = self._route(sql, params)
        return _MockRow(v) if isinstance(v, dict) else v

    async def fetch(self, sql, *params):
        v = self._route(sql, params)
        if v is None:
            return []
        return [_MockRow(r) if isinstance(r, dict) else r for r in v]


class _MockPoolAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _MockPool:
    def __init__(self, routes: dict):
        self.routes = routes

    def acquire(self):
        return _MockPoolAcquire(_MockConn(self.routes))


def _seeded_routes() -> dict:
    """Controlled DB fixture: 10 candidates, 1 tick, 5 outcomes across 2
    horizons, 3 trades (2 valid + 1 invalid_oos), 5 ticks total."""
    now = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)
    ny_today = "2026-06-13"
    ny_yest = "2026-06-12"
    return {
        # ── Candidate aggregates ─────────────────────────────────────
        "SELECT COUNT(*) FROM paper_candidates": 10,
        "SELECT COUNT(*) FROM paper_candidates WHERE extras_json IS NOT NULL": 8,
        "SELECT MIN(created_at) FROM paper_candidates": now - timedelta(hours=2),
        "SELECT MAX(created_at) FROM paper_candidates": now,
        "SELECT action, COUNT(*) AS n FROM paper_candidates GROUP BY action": [
            {"action": "enter", "n": 3},
            {"action": "reject", "n": 5},
            {"action": None, "n": 2},
        ],
        "SELECT rejection_reason, COUNT(*) AS n\n                      FROM paper_candidates\n                     GROUP BY rejection_reason": [
            {"rejection_reason": "score_below_threshold", "n": 4},
            {"rejection_reason": "fda_regulatory", "n": 1},
            {"rejection_reason": None, "n": 5},
        ],
        "SELECT marketdata_source, COUNT(*) AS n\n                      FROM paper_candidates\n                     GROUP BY marketdata_source": [
            {"marketdata_source": "polygon", "n": 10},
        ],
        "SELECT catalyst_type, COUNT(*) AS n\n                      FROM paper_candidates\n                     GROUP BY catalyst_type": [
            {"catalyst_type": "earnings", "n": 2},
            {"catalyst_type": "generic_news", "n": 3},
            {"catalyst_type": None, "n": 5},
        ],
        "SELECT entry_mode, COUNT(*) AS n\n                      FROM paper_candidates\n                     GROUP BY entry_mode": [
            {"entry_mode": "catalyst", "n": 4},
            {"entry_mode": "momentum_no_catalyst", "n": 2},
        ],
        "SELECT decision_reason, COUNT(*) AS n\n                      FROM paper_candidates\n                     GROUP BY decision_reason": [
            {"decision_reason": "score 65 < threshold 70", "n": 3},
        ],
        "SELECT COUNT(*) FROM paper_candidates WHERE tick_id IS NULL OR tick_id = ''": 0,
        "SELECT COUNT(*) FROM paper_candidates WHERE created_at IS NULL": 0,

        # ── paper_ticks ──────────────────────────────────────────────
        # The base "SELECT COUNT(*) FROM paper_ticks" matches BOTH the
        # total-count query AND the missing-started_at query, so we use a
        # longer (more specific) key for missing-started_at.
        "SELECT MIN(started_at) FROM paper_ticks": now - timedelta(hours=2),
        "SELECT MAX(started_at) FROM paper_ticks": now,
        "SELECT COUNT(*) FROM paper_ticks WHERE started_at IS NULL": 0,
        "SELECT COUNT(*) FROM paper_ticks": 5,
        "INNER JOIN paper_ticks t ON t.tick_id = c.tick_id": 10,

        # ── Outcomes ─────────────────────────────────────────────────
        "SELECT COUNT(*) FROM paper_candidate_outcomes": 5,
        "SELECT status, COUNT(*) AS n FROM paper_candidate_outcomes GROUP BY status": [
            {"status": "resolved", "n": 3},
            {"status": "pending", "n": 2},
        ],
        "SELECT horizon_minutes, status, COUNT(*) AS n\n                  FROM paper_candidate_outcomes\n                 GROUP BY horizon_minutes, status": [
            {"horizon_minutes": 5, "status": "resolved", "n": 2},
            {"horizon_minutes": 5, "status": "pending", "n": 1},
            {"horizon_minutes": 15, "status": "resolved", "n": 1},
            {"horizon_minutes": 15, "status": "pending", "n": 1},
        ],
        "SELECT source, COUNT(*) AS n\n                      FROM paper_candidate_outcomes\n                     GROUP BY source": [
            {"source": "marketdata_cache", "n": 3},
            {"source": None, "n": 2},
        ],
        "SELECT MIN(resolved_at) FROM paper_candidate_outcomes WHERE resolved_at IS NOT NULL":
            now - timedelta(hours=1),
        "SELECT MAX(resolved_at) FROM paper_candidate_outcomes WHERE resolved_at IS NOT NULL": now,
        "SELECT COUNT(*) FROM paper_candidate_outcomes WHERE resolved_at IS NULL": 2,
        "SELECT COUNT(*) FROM paper_candidate_outcomes WHERE resolved_at IS NOT NULL": 3,

        # ── Joinability ──────────────────────────────────────────────
        "SELECT COUNT(*) FROM paper_candidate_outcomes o\n                 INNER JOIN paper_candidates c ON c.id = o.candidate_id": 5,
        "SELECT COUNT(DISTINCT candidate_id) FROM paper_candidate_outcomes": 4,
        "HAVING COUNT(DISTINCT horizon_minutes) >= 5": 0,
        # Outcome rows present for horizon by EXISTS — use long unique key
        "WHERE EXISTS ( SELECT 1 FROM paper_candidate_outcomes": lambda h: {5: 3, 15: 2, 30: 0, 60: 0, 120: 0}.get(h, 0),
        # NOT EXISTS — missing horizon rows
        "WHERE NOT EXISTS ( SELECT 1 FROM paper_candidate_outcomes": lambda h: {5: 7, 15: 8, 30: 10, 60: 10, 120: 10}.get(h, 0),
        # Resolved-rows per horizon
        "WHERE horizon_minutes = $1 AND status = 'resolved'": lambda h: {5: 2, 15: 1, 30: 0, 60: 0, 120: 0}.get(h, 0),
        "WHERE horizon_minutes = $1 AND status = 'pending'": lambda h: {5: 1, 15: 1, 30: 0, 60: 0, 120: 0}.get(h, 0),
        "WHERE horizon_minutes = $1 AND status IN ('error','missing_data')": 0,
        # All required horizons present per candidate
        "HAVING COUNT(DISTINCT horizon_minutes) >= cardinality": 0,
        "WHERE status IN ('pending','missing_data','error')\n                 GROUP BY horizon_minutes": [
            {"horizon_minutes": 5, "n": 1},
            {"horizon_minutes": 15, "n": 1},
        ],

        # ── Trades ───────────────────────────────────────────────────
        "SELECT COUNT(*) FROM paper_trades_journal": 3,
        "SELECT event, COUNT(*) AS n FROM paper_trades_journal GROUP BY event": [
            {"event": "entry", "n": 1},
            {"event": "exit", "n": 2},
        ],
        "SELECT wallet_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY wallet_id": [
            {"wallet_id": "engine", "n": 2},
            {"wallet_id": "deterministic_shadow", "n": 1},
        ],
        "SELECT strategy_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY strategy_id": [
            {"strategy_id": "engine", "n": 2},
            {"strategy_id": "deterministic_shadow", "n": 1},
        ],
        "SELECT exit_reason, COUNT(*) AS n\n                      FROM paper_trades_journal\n                     WHERE event = 'exit'\n                     GROUP BY exit_reason": [
            {"exit_reason": "take_profit_intrabar", "n": 1},
            {"exit_reason": "invalid_out_of_session_entry_flatten", "n": 1},
        ],
        "SELECT COUNT(*) FROM paper_trades_journal WHERE wallet_id IS NULL OR wallet_id = ''": 0,
        "SELECT COUNT(*) FROM paper_trades_journal WHERE strategy_id IS NULL OR strategy_id = ''": 0,
        "WHERE event = 'entry' AND opened_at IS NULL": 0,
        "WHERE event = 'exit' AND closed_at IS NULL": 0,
        "WHERE exit_reason = 'invalid_out_of_session_entry_flatten'": 1,
        "SELECT MIN(created_at) FROM paper_trades_journal": now - timedelta(hours=1),
        "SELECT MAX(created_at) FROM paper_trades_journal": now,
        "SELECT MIN(opened_at) FROM paper_trades_journal WHERE opened_at IS NOT NULL": now - timedelta(hours=1, minutes=30),
        "SELECT MAX(opened_at) FROM paper_trades_journal WHERE opened_at IS NOT NULL": now - timedelta(minutes=30),
        "SELECT MIN(closed_at) FROM paper_trades_journal WHERE closed_at IS NOT NULL": now - timedelta(minutes=45),
        "SELECT MAX(closed_at) FROM paper_trades_journal WHERE closed_at IS NOT NULL": now,
        "WHERE opened_at > now() + interval '5 minutes'": 0,
        "WHERE closed_at > now() + interval '5 minutes'": 0,
        "WHERE opened_at IS NULL": 0,

        # ── NY session grouping ──────────────────────────────────────
        "FROM paper_trades_journal\n                     WHERE COALESCE(closed_at, opened_at, created_at) IS NOT NULL\n                     GROUP BY sd": [
            {"sd": ny_today, "n": 2},
            {"sd": ny_yest, "n": 1},
        ],
        "FROM paper_candidates\n                     WHERE created_at IS NOT NULL\n                     GROUP BY sd": [
            {"sd": ny_today, "n": 8},
            {"sd": ny_yest, "n": 2},
        ],
        "FROM paper_candidate_outcomes\n                     WHERE COALESCE(resolved_at, created_at) IS NOT NULL\n                     GROUP BY sd": [
            {"sd": ny_today, "n": 3},
            {"sd": ny_yest, "n": 2},
        ],

        # ── extras_json field-family probes ──────────────────────────
        # sample_size (recent 5K extras rows) — use simple substring after
        # whitespace normalisation
        "SELECT 1 FROM paper_candidates WHERE extras_json IS NOT NULL ORDER BY id DESC LIMIT 5000) s": 8,

        # Per-family OR check — return based on keys
        "ORDER BY id DESC LIMIT 5000 ) s WHERE extras_json ? $1::text OR": lambda *keys: (
            6 if "marketdata_source" in keys
            else 5 if "catalyst_type" in keys
            else 0 if "reddit_rank" in keys
            else 0 if "earnings_next_date" in keys
            else 0 if "insider_recent_buy_count" in keys
            else 4 if "market_trend_direction" in keys
            else 7 if "enhanced_shadow_decision" in keys
            else 6 if "llm_decision" in keys
            else 6 if "llm_status" in keys
            else 4 if "entry_mode" in keys
            else 5 if "score_components" in keys
            else 0
        ),
        # Single-key probe
        "ORDER BY id DESC LIMIT 5000 ) s WHERE extras_json ? $1::text": lambda k: {
            "marketdata_source": 6, "marketdata_age_seconds": 6,
            "catalyst_type": 5, "catalyst_sentiment": 4, "strongest_catalyst_title": 3,
            "reddit_rank": 0, "reddit_mentions": 0,
            "earnings_next_date": 0, "earnings_score_adjustment": 0,
            "insider_recent_buy_count": 0, "insider_score_adjustment": 0,
            "market_trend_direction": 4, "market_trend_strength": 3,
            "enhanced_shadow_decision": 7, "enhanced_shadow_score": 6,
            "llm_decision": 6, "llm_status": 6, "llm_error": 1,
            "entry_mode": 4, "candidate_sources": 3, "market_trend_path_name": 2,
            "score_components": 5, "total_score": 6, "final_score_after_intelligence_adjustments": 4,
        }.get(k, 0),

        # ── Shadow decision persistence (single fetchrow) ────────────
        "SELECT\n                    COUNT(*) AS sample_size,": {
            "sample_size": 8,
            "det_decision_rows": 7,
            "det_score_rows": 6,
            "det_would_enter": 2,
            "det_watch": 3,
            "det_would_reject": 2,
            "ai_decision_rows": 6,
            "ai_status_rows": 6,
            "ai_would_enter": 0,
            "ai_watch": 0,
            "ai_would_reject": 0,
            "ai_disabled": 6,
            "ai_error": 0,
            "ai_not_selected": 0,
        },
    }


@pytest.fixture
def seeded_deep_status(client, monkeypatch):
    """Wire the substring-routed mock pool into _db.get_pool, then call the
    endpoint and return the parsed body."""
    from paper import db as _db
    pool = _MockPool(_seeded_routes())
    monkeypatch.setattr(_db, "get_pool", AsyncMock(return_value=pool))
    r = client.get("/api/audit/persistence/deep-status")
    assert r.status_code == 200
    return r.json()


# ── Section A — DB-seeded exact-value assertions ───────────────────────────

def test_seeded_candidate_aggregates_exact(seeded_deep_status):
    body = seeded_deep_status
    assert body["ok"] is True
    cand = body["candidates"]
    assert cand["total"] == 10
    assert cand["with_extras_json"] == 8
    assert cand["extras_json_coverage_percent"] == 80.0
    assert cand["missing_tick_id"] == 0
    assert cand["missing_created_at"] == 0
    # by_action sums to 10 (3 enter + 5 reject + 2 None→"unknown")
    assert cand["by_action"]["enter"] == 3
    assert cand["by_action"]["reject"] == 5
    assert cand["by_action"].get("unknown", 0) == 2
    assert cand["by_catalyst_type"]["earnings"] == 2
    assert cand["by_entry_mode"]["catalyst"] == 4


def test_seeded_tick_ts_audit_exact(seeded_deep_status):
    body = seeded_deep_status
    audit = body["tick_ts_audit"]
    assert audit["tick_ts_persistence_status"] == "not_persisted_as_candidate_column"
    assert audit["paper_ticks_total"] == 5
    assert audit["paper_ticks_missing_started_at"] == 0
    assert audit["candidates_joinable_to_ticks_count"] == 10
    assert audit["candidates_joinable_to_ticks_coverage_percent"] == 100.0


def test_seeded_extras_family_coverage_exact(seeded_deep_status):
    body = seeded_deep_status
    cov = body["extras_json_field_family_coverage"]
    # Sample size = 8 (extras-bearing rows). Marketdata seeded as 6 present.
    assert cov["marketdata"]["sample_size"] == 8
    assert cov["marketdata"]["rows_present"] == 6
    assert cov["marketdata"]["coverage_percent"] == 75.0
    assert cov["marketdata"]["status"] == "collected"
    assert cov["marketdata"]["coverage_scope"] == "sampled"
    # Reddit/earnings/insider have 0 present → not_collected
    for family in ("reddit", "earnings", "insider"):
        assert cov[family]["rows_present"] == 0, family
        assert cov[family]["status"] == "not_collected", family
        assert cov[family]["coverage_percent"] == 0.0, family
    # Deterministic shadow: 7 present → collected
    assert cov["deterministic_shadow"]["rows_present"] == 7
    assert cov["deterministic_shadow"]["status"] == "collected"
    # ai_shadow: 6 present
    assert cov["ai_shadow"]["rows_present"] == 6
    # keys_found only contains actually-present keys
    assert "marketdata_source" in cov["marketdata"]["keys_found"]
    assert "reddit_rank" not in cov["reddit"]["keys_found"]


def test_seeded_deterministic_shadow_persistence_exact(seeded_deep_status):
    body = seeded_deep_status
    det = body["shadow_decision_persistence"]["deterministic_shadow"]
    assert det["sample_size"] == 8
    assert det["decision_field_present_rows"] == 7
    assert det["would_enter_count"] == 2
    assert det["watch_count"] == 3
    assert det["would_reject_count"] == 2
    assert det["missing_decision_count"] == 1  # 8 - 7
    assert det["evidence_based_separable"] is True
    assert det["status"] == "collected"


def test_seeded_ai_shadow_persistence_exact(seeded_deep_status):
    body = seeded_deep_status
    ai = body["shadow_decision_persistence"]["ai_shadow"]
    assert ai["sample_size"] == 8
    assert ai["decision_field_present_rows"] == 6
    assert ai["status_field_present_rows"] == 6
    assert ai["disabled_count"] == 6
    assert ai["error_count"] == 0
    assert ai["not_selected_count"] == 0
    assert ai["would_enter_count"] == 0
    assert ai["evidence_based_separable"] is True  # status field present
    assert ai["status"] == "collected"
    assert ai["no_paid_ai_calls"] is True


def test_seeded_outcomes_resolved_at_exact(seeded_deep_status):
    body = seeded_deep_status
    out = body["outcomes"]
    assert out["total"] == 5
    assert out["resolved_at_null_count"] == 2
    assert out["resolved_at_present_count"] == 3
    # Sum equals total
    assert out["resolved_at_null_count"] + out["resolved_at_present_count"] == out["total"]
    # Status-derived count is separate from direct null count
    assert out["status_derived_missing_resolved_at_count"] == 2
    # Resolved_at aliases (Part D)
    assert "resolved_at_min" in out
    assert "resolved_at_max" in out
    assert out["resolved_at_min"] == out["min_resolved_at"]
    assert out["resolved_at_max"] == out["max_resolved_at"]


def test_seeded_horizon_row_coverage_exact(seeded_deep_status):
    body = seeded_deep_status
    out = body["outcomes"]
    assert out["required_horizons"] == [5, 15, 30, 60, 120]
    cov = out["horizon_row_coverage"]
    # Seeded: horizon 5 has 3 candidates with row, 7 missing
    assert cov["5"]["candidates_with_row"] == 3
    assert cov["5"]["candidates_missing_row"] == 7
    assert cov["5"]["resolved_rows"] == 2
    assert cov["5"]["pending_rows"] == 1
    # Horizon 15: 2 present, 8 missing
    assert cov["15"]["candidates_missing_row"] == 8
    # Horizons 30/60/120 entirely missing
    assert cov["30"]["candidates_missing_row"] == 10
    assert cov["120"]["candidates_missing_row"] == 10
    assert out["candidates_with_all_required_horizons"] == 0


def test_seeded_latest_session_date_derivation_exact(seeded_deep_status):
    body = seeded_deep_status
    ng = body["ny_session_grouping"]
    assert ng["latest_trade_session_date"] == "2026-06-13"
    assert ng["latest_candidate_session_date"] == "2026-06-13"
    assert ng["latest_outcome_session_date"] == "2026-06-13"
    assert ng["latest_session_date"] == "2026-06-13"
    assert ng["latest_session_date_source"] in ("trades", "candidates", "outcomes")


def test_seeded_trade_aggregates_exact(seeded_deep_status):
    body = seeded_deep_status
    trd = body["trades"]
    assert trd["total"] == 3
    assert trd["by_wallet_id"]["engine"] == 2
    assert trd["by_wallet_id"]["deterministic_shadow"] == 1
    assert trd["missing_wallet_id"] == 0
    assert trd["missing_strategy_id"] == 0
    assert trd["invalid_out_of_session_count"] == 1
    assert trd["future_opened_at_count"] == 0
    assert trd["future_closed_at_count"] == 0
    # Column-mapping note exists
    assert "opened_at" in trd["column_mapping_note"]
    assert "closed_at" in trd["column_mapping_note"]


def test_seeded_readiness_flags_exact(seeded_deep_status):
    body = seeded_deep_status
    assert body["engine_analysis_ready"] is True
    assert body["deterministic_shadow_analysis_ready"] is True
    # AI shadow had llm_status rows seeded → ai_separable True
    assert body["ai_shadow_analysis_ready"] is True
    assert body["ai_shadow_status_note"] == "ai_shadow_data_collected"
    assert body["overall_freeze_audit_ready"] is True
    # No blocking gaps when everything separates
    assert body["blocking_gaps"] == []


def test_seeded_warnings_surface_legacy_horizon_gap(seeded_deep_status):
    body = seeded_deep_status
    # 10 candidates - 0 with all required horizons = 10 candidates missing any horizon
    assert "missing_outcome_rows_10_candidates" in body["warnings"]


# ── Section B — wallet API status/config consistency ───────────────────────

def test_performance_endpoint_includes_status_config_fields(client):
    r = client.get("/api/paper/wallets/performance")
    assert r.status_code == 200
    body = r.json()
    for w in body["wallets"]:
        # Required H10 Part B fields
        for key in (
            "wallet_id", "strategy_id", "status", "inactive_reason",
            "enabled", "active", "processing_enabled", "enabled_by_config",
            "depends_on_llm", "last_entry_at", "last_exit_at", "last_decision_at",
        ):
            assert key in w, f"{w.get('wallet_id')} missing {key}"


def test_analytics_endpoint_includes_status_config_fields(client):
    r = client.get("/api/paper/wallets/analytics")
    assert r.status_code == 200
    body = r.json()
    for wallet_key in ("engine", "deterministic_shadow", "ai_shadow"):
        obj = body[wallet_key]
        for key in (
            "status", "active", "inactive_reason",
            "enabled", "processing_enabled", "enabled_by_config",
            "depends_on_llm", "last_decision_at",
        ):
            assert key in obj, f"{wallet_key} analytics missing {key}"


def test_analytics_ai_shadow_no_paid_ai_calls(client):
    r = client.get("/api/paper/wallets/analytics")
    body = r.json()
    ai = body["ai_shadow"]
    assert ai["no_paid_ai_calls"] is True


# ── Section C — true deterministic last_decision_at ────────────────────────

def test_true_last_decision_at_updates_on_watch(monkeypatch):
    """A WATCH decision must update last_decision_at even without entries."""
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    assert sw.get_last_decision_at(sw.WALLET_DETERMINISTIC) is None
    sw._stamp_decision(sw.WALLET_DETERMINISTIC, [
        {"symbol": "X", "enhanced_shadow_decision": "WATCH"},
    ])
    assert sw.get_last_decision_at(sw.WALLET_DETERMINISTIC) is not None


def test_true_last_decision_at_updates_on_would_reject(monkeypatch):
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    sw._stamp_decision(sw.WALLET_DETERMINISTIC, [
        {"symbol": "Y", "enhanced_shadow_decision": "WOULD_REJECT"},
    ])
    assert sw.get_last_decision_at(sw.WALLET_DETERMINISTIC) is not None


def test_true_last_decision_at_updates_on_score_without_entry(monkeypatch):
    """A scored candidate without any decision still touches last_decision_at."""
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    sw._stamp_decision(sw.WALLET_DETERMINISTIC, [
        {"symbol": "Z", "enhanced_shadow_score": 42},
    ])
    assert sw.get_last_decision_at(sw.WALLET_DETERMINISTIC) is not None


def test_true_last_decision_at_does_not_touch_for_unrelated_candidates(monkeypatch):
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    sw._stamp_decision(sw.WALLET_DETERMINISTIC, [
        {"symbol": "U", "total_score": 50},  # no shadow fields
    ])
    assert sw.get_last_decision_at(sw.WALLET_DETERMINISTIC) is None


def test_wallet_snapshot_uses_true_last_decision_at(client, monkeypatch):
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    # Touch deterministic shadow
    sw._stamp_decision(sw.WALLET_DETERMINISTIC, [
        {"symbol": "A", "enhanced_shadow_decision": "WATCH"},
    ])
    r = client.get("/api/paper/wallets")
    det = r.json()["deterministic_shadow"]
    assert det["last_decision_at"] is not None


# ── Section D — resolved_at_min/resolved_at_max aliases ────────────────────

def test_resolved_at_aliases_present(client):
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    if body.get("ok"):
        out = body["outcomes"]
        assert "resolved_at_min" in out
        assert "resolved_at_max" in out
        # Legacy keys still there
        assert "min_resolved_at" in out
        assert "max_resolved_at" in out


# ── Section E — dashboard structure invariants ─────────────────────────────

def test_three_engine_dashboard_structure_unchanged():
    src = _page_src()
    for marker in (
        "EngineAccountsSection",
        "EngineDailyReportsSection",
        "EngineDecisionAnalyticsSection",
    ):
        assert marker in src


def test_no_aggregate_account_total_reintroduced():
    src = _page_src()
    assert "All wallets cash" not in src
    assert "All accounts cash" not in src
    assert "function WalletDailyAnalytics" not in src


# ── Section F — boundary invariants ────────────────────────────────────────

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


def test_no_broker_tokens_anywhere():
    for rel in ("api/audit.py", "api/paper.py", "paper/shadow_wallets.py"):
        text = (pathlib.Path(__file__).parents[1] / rel).read_text(encoding="utf-8")
        for token in ("alpaca", "real_order", "place_order"):
            assert token not in text, f"Forbidden token '{token}' in {rel}"


def test_no_paid_ai_provider_calls():
    for rel in ("api/audit.py", "api/paper.py", "paper/shadow_wallets.py"):
        text = (pathlib.Path(__file__).parents[1] / rel).read_text(encoding="utf-8")
        for token in ("OpenAI(", "Anthropic(", "openai.Client", "anthropic.Client"):
            assert token not in text, f"Paid AI provider call '{token}' in {rel}"
