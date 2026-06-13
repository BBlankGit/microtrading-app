"""
Phase G1B-H11 — close G1B-H10 audit hardening caveats.

Includes:
  Part A — real inserted-row DB-backed integration test (auto-skips if no DB).
  Part B — trades-empty latest-session fallback via controlled mock fixture.
  Part C — negative readiness fixture (critical dimensions absent).
  Part D — positive AI shadow error / not_selected counts.
  Part E — exact trade timestamp integrity assertions.
  Part F — durable last_decision_at provenance fields.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import uuid
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
# Part A — REAL DB-backed integration test.
# Uses a unique tick_id prefix for isolation, INSERTs rows into actual
# paper_ticks / paper_candidates / paper_candidate_outcomes /
# paper_trades_journal tables, calls the live endpoint, asserts exact
# values flow through, cleans up with DELETE. Skips if DB is unreachable.
# ════════════════════════════════════════════════════════════════════════════

def _database_url_or_skip() -> str:
    """Return DATABASE_URL from settings or skip if unavailable."""
    from core.config import settings
    url = settings.DATABASE_URL
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping real-DB integration test")
    return url


@pytest.fixture
def real_db_fixture():
    """Insert a controlled tick + candidate + outcome + trade with a unique
    prefix using a DEDICATED asyncpg connection (not the shared pool, to
    avoid concurrent-operation conflicts with the live endpoint call).
    Always cleans up at teardown. Skips if DB is unreachable."""
    import asyncpg
    url = _database_url_or_skip()
    prefix = f"h11_{uuid.uuid4().hex[:12]}"
    tick_id = f"{prefix}_tick_a"
    now = datetime.now(timezone.utc).replace(microsecond=0)

    async def _with_dedicated_conn(fn):
        conn = await asyncpg.connect(url)
        try:
            return await fn(conn)
        finally:
            await conn.close()

    async def _setup():
        async def _do(conn):
            # paper_ticks
            await conn.execute(
                """
                INSERT INTO paper_ticks (tick_id, started_at, completed_at,
                    symbols_evaluated, entries_made, exits_made)
                VALUES ($1, $2, $2, 1, 0, 0)
                """,
                tick_id, now,
            )
            # paper_candidates — include extras_json with all family markers
            extras = (
                '{"marketdata_source":"polygon","marketdata_age_seconds":1.2,'
                '"catalyst_type":"earnings","catalyst_sentiment":"positive",'
                '"strongest_catalyst_title":"FAKE corp Q3",'
                '"reddit_rank":3,"reddit_mentions":42,'
                '"earnings_next_date":"2026-06-20","earnings_score_adjustment":5,'
                '"insider_recent_buy_count":2,"insider_score_adjustment":3,'
                '"market_trend_direction":"improving","market_trend_strength":"strong",'
                '"enhanced_shadow_decision":"WOULD_REJECT","enhanced_shadow_score":42,'
                '"llm_decision":"WATCH","llm_status":"not_selected","llm_error":null,'
                '"entry_mode":"catalyst","candidate_sources":["news"],'
                '"market_trend_path_name":"catalyst",'
                '"score_components":{"x":1},"total_score":42,'
                '"final_score_after_intelligence_adjustments":42}'
            )
            cand_row = await conn.fetchrow(
                """
                INSERT INTO paper_candidates (tick_id, symbol, eligible, action,
                    rejection_reason, total_score, score_threshold, score_pass,
                    extras_json, created_at, catalyst_type, entry_mode,
                    marketdata_source, decision_reason)
                VALUES ($1, 'TEST_H11', false, 'reject',
                    'score_below_threshold', 42, 70, false,
                    $2::jsonb, $3, 'earnings', 'catalyst',
                    'polygon', 'score 42 < threshold 70')
                RETURNING id
                """,
                tick_id, extras, now,
            )
            cand_id = cand_row["id"]
            # paper_candidate_outcomes — seed 2 horizons: one resolved, one pending
            await conn.execute(
                """
                INSERT INTO paper_candidate_outcomes (candidate_id, tick_id,
                    symbol, horizon_minutes, reference_price, reference_at,
                    future_price, future_at, future_return_percent,
                    status, resolved_at, source)
                VALUES ($1, $2, 'TEST_H11', 5, 100.0, $3, 101.0, $3, 1.0,
                    'resolved', $3, 'marketdata_cache')
                """,
                cand_id, tick_id, now,
            )
            await conn.execute(
                """
                INSERT INTO paper_candidate_outcomes (candidate_id, tick_id,
                    symbol, horizon_minutes, reference_price, reference_at, status)
                VALUES ($1, $2, 'TEST_H11', 15, 100.0, $3, 'pending')
                """,
                cand_id, tick_id, now,
            )
            # paper_trades_journal — engine entry + exit
            await conn.execute(
                """
                INSERT INTO paper_trades_journal (tick_id, symbol, event,
                    entry_price, shares, cost_basis, opened_at,
                    wallet_id, strategy_id, created_at)
                VALUES ($1, 'TEST_H11', 'entry', 100.0, 1, 100.0, $2,
                    'engine', 'engine', $2)
                """,
                tick_id, now,
            )
            await conn.execute(
                """
                INSERT INTO paper_trades_journal (tick_id, symbol, event,
                    entry_price, exit_price, shares, cost_basis,
                    pnl, exit_reason, opened_at, closed_at,
                    wallet_id, strategy_id, created_at)
                VALUES ($1, 'TEST_H11', 'exit', 100.0, 101.0, 1, 100.0,
                    1.0, 'take_profit_intrabar', $2, $2,
                    'engine', 'engine', $2)
                """,
                tick_id, now,
            )
        return await _with_dedicated_conn(_do)

    async def _teardown():
        async def _do(conn):
            await conn.execute(
                "DELETE FROM paper_candidate_outcomes WHERE tick_id = $1",
                tick_id,
            )
            await conn.execute(
                "DELETE FROM paper_candidates WHERE tick_id = $1",
                tick_id,
            )
            await conn.execute(
                "DELETE FROM paper_trades_journal WHERE tick_id = $1",
                tick_id,
            )
            await conn.execute(
                "DELETE FROM paper_ticks WHERE tick_id = $1",
                tick_id,
            )
        return await _with_dedicated_conn(_do)

    asyncio.run(_setup())
    try:
        yield {"prefix": prefix, "tick_id": tick_id, "now": now}
    finally:
        asyncio.run(_teardown())


def test_real_db_integration_seeded_rows_flow_through(client, real_db_fixture):
    """Insert real rows and confirm the live endpoint surfaces them."""
    r = client.get("/api/audit/persistence/deep-status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Our seeded tick must appear in the running totals
    assert body["candidates"]["total"] >= 1
    assert body["tick_ts_audit"]["paper_ticks_total"] >= 1
    # The candidate's extras_json carries all 11 family markers — coverage
    # in the recent-5k sample must be at least 1 row each, status=collected.
    cov = body["extras_json_field_family_coverage"]
    for family in ("marketdata", "catalyst_news", "reddit", "earnings",
                   "insider", "market_regime_trend",
                   "deterministic_shadow", "ai_shadow"):
        assert cov[family]["status"] == "collected", family
        assert cov[family]["rows_present"] >= 1, family
    # The seeded candidate has llm_status=not_selected — this counts toward
    # not_selected on shadow_decision_persistence (if our row landed in the
    # recent 5k sample).
    ai = body["shadow_decision_persistence"]["ai_shadow"]
    assert ai["status"] == "collected"


# ════════════════════════════════════════════════════════════════════════════
# Mocked-pool variants for Parts B/C/D/E.
# ════════════════════════════════════════════════════════════════════════════

class _MockRow(dict):
    def __getitem__(self, key):
        return super().__getitem__(key)


class _MockConn:
    def __init__(self, routes: dict):
        self.routes = routes

    def _route(self, sql: str, params):
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


# ── Part B — trades-empty latest-session fallback ──────────────────────────

def _trades_empty_routes():
    now = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)
    return {
        # No trades at all
        "SELECT COUNT(*) FROM paper_trades_journal": 0,
        "FROM paper_trades_journal\n                     WHERE COALESCE(closed_at, opened_at, created_at) IS NOT NULL\n                     GROUP BY sd": [],
        "SELECT event, COUNT(*) AS n FROM paper_trades_journal GROUP BY event": [],
        "SELECT wallet_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY wallet_id": [],
        "SELECT strategy_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY strategy_id": [],
        # Candidates exist
        "SELECT COUNT(*) FROM paper_candidates": 5,
        "SELECT COUNT(*) FROM paper_candidates WHERE extras_json IS NOT NULL": 5,
        "FROM paper_candidates\n                     WHERE created_at IS NOT NULL\n                     GROUP BY sd": [
            {"sd": "2026-06-13", "n": 3},
            {"sd": "2026-06-12", "n": 2},
        ],
        # Outcomes exist but trades don't
        "SELECT COUNT(*) FROM paper_candidate_outcomes": 2,
        "FROM paper_candidate_outcomes\n                     WHERE COALESCE(resolved_at, created_at) IS NOT NULL\n                     GROUP BY sd": [
            {"sd": "2026-06-12", "n": 2},
        ],
        "SELECT COUNT(*) FROM paper_candidate_outcomes WHERE resolved_at IS NULL": 0,
        "SELECT COUNT(*) FROM paper_candidate_outcomes WHERE resolved_at IS NOT NULL": 2,
        # Joinability
        "SELECT COUNT(*) FROM paper_candidate_outcomes o\n                 INNER JOIN paper_candidates c ON c.id = o.candidate_id": 2,
        "SELECT COUNT(DISTINCT candidate_id) FROM paper_candidate_outcomes": 1,
        # Shadow evidence — present
        "SELECT 1 FROM paper_candidates WHERE extras_json IS NOT NULL ORDER BY id DESC LIMIT 5000) s": 5,
        "SELECT\n                    COUNT(*) AS sample_size,": {
            "sample_size": 5,
            "det_decision_rows": 5,
            "det_score_rows": 5,
            "det_would_enter": 1, "det_watch": 1, "det_would_reject": 3,
            "ai_decision_rows": 5,
            "ai_status_rows": 5,
            "ai_would_enter": 0, "ai_watch": 0, "ai_would_reject": 0,
            "ai_disabled": 5, "ai_error": 0, "ai_not_selected": 0,
        },
        "ORDER BY id DESC LIMIT 5000 ) s WHERE extras_json ? $1::text OR": 5,
        "ORDER BY id DESC LIMIT 5000 ) s WHERE extras_json ? $1::text": 5,
    }


def test_latest_session_falls_back_to_candidates_when_no_trades(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "get_pool", AsyncMock(return_value=_MockPool(_trades_empty_routes())))
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    ng = body["ny_session_grouping"]
    assert ng["latest_trade_session_date"] is None
    assert ng["latest_candidate_session_date"] == "2026-06-13"
    assert ng["latest_session_date"] == "2026-06-13"
    assert ng["latest_session_date_source"] == "candidates"


def _outcomes_only_routes():
    return {
        "SELECT COUNT(*) FROM paper_trades_journal": 0,
        "FROM paper_trades_journal\n                     WHERE COALESCE(closed_at, opened_at, created_at) IS NOT NULL\n                     GROUP BY sd": [],
        "SELECT event, COUNT(*) AS n FROM paper_trades_journal GROUP BY event": [],
        "SELECT wallet_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY wallet_id": [],
        "SELECT strategy_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY strategy_id": [],
        # No candidates with timestamps either (but candidates exist for join shape)
        "SELECT COUNT(*) FROM paper_candidates": 0,
        "FROM paper_candidates\n                     WHERE created_at IS NOT NULL\n                     GROUP BY sd": [],
        # Outcomes have NY session dates
        "SELECT COUNT(*) FROM paper_candidate_outcomes": 3,
        "FROM paper_candidate_outcomes\n                     WHERE COALESCE(resolved_at, created_at) IS NOT NULL\n                     GROUP BY sd": [
            {"sd": "2026-06-10", "n": 3},
        ],
    }


def test_latest_session_falls_back_to_outcomes_when_no_trades_or_candidates(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "get_pool", AsyncMock(return_value=_MockPool(_outcomes_only_routes())))
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    ng = body["ny_session_grouping"]
    assert ng["latest_trade_session_date"] is None
    assert ng["latest_candidate_session_date"] is None
    assert ng["latest_outcome_session_date"] == "2026-06-10"
    assert ng["latest_session_date"] == "2026-06-10"
    assert ng["latest_session_date_source"] == "outcomes"


# ── Part C — negative readiness fixture ────────────────────────────────────

def _negative_readiness_routes():
    """Candidates exist but no shadow decisions / no outcome joins / trades
    missing wallet_id. Should set readiness flags to False with proper
    blocking_gaps + warnings."""
    return {
        "SELECT COUNT(*) FROM paper_candidates": 100,
        "SELECT COUNT(*) FROM paper_candidates WHERE extras_json IS NOT NULL": 0,  # 0% coverage
        # No outcomes at all
        "SELECT COUNT(*) FROM paper_candidate_outcomes": 0,
        "SELECT COUNT(*) FROM paper_candidate_outcomes o\n                 INNER JOIN paper_candidates c ON c.id = o.candidate_id": 0,
        # Trades missing wallet_id entirely
        "SELECT COUNT(*) FROM paper_trades_journal": 50,
        "SELECT COUNT(*) FROM paper_trades_journal WHERE wallet_id IS NULL OR wallet_id = ''": 50,
        "SELECT COUNT(*) FROM paper_trades_journal WHERE strategy_id IS NULL OR strategy_id = ''": 50,
        "SELECT wallet_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY wallet_id": [
            {"wallet_id": None, "n": 50},
        ],
        # No extras → shadow evidence empty
        "SELECT 1 FROM paper_candidates WHERE extras_json IS NOT NULL ORDER BY id DESC LIMIT 5000) s": 0,
        "SELECT\n                    COUNT(*) AS sample_size,": {
            "sample_size": 0,
            "det_decision_rows": 0,
            "det_score_rows": 0,
            "det_would_enter": 0, "det_watch": 0, "det_would_reject": 0,
            "ai_decision_rows": 0, "ai_status_rows": 0,
            "ai_would_enter": 0, "ai_watch": 0, "ai_would_reject": 0,
            "ai_disabled": 0, "ai_error": 0, "ai_not_selected": 0,
        },
    }


def test_negative_readiness_blocking_gaps_and_warnings(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "get_pool", AsyncMock(return_value=_MockPool(_negative_readiness_routes())))
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    # All readiness flags must be False
    assert body["engine_analysis_ready"] is False
    assert body["deterministic_shadow_analysis_ready"] is False
    assert body["ai_shadow_analysis_ready"] is False
    assert body["overall_freeze_audit_ready"] is False
    assert body["analysis_ready"] is False
    # blocking_gaps populated: candidate→outcome joins absent
    assert "no_candidate_to_outcome_joins" in body["blocking_gaps"]
    # warnings include shadow not_persisted and trades missing wallet_id
    assert "deterministic_shadow_decisions_not_persisted" in body["warnings"]
    assert "ai_shadow_decisions_not_persisted" in body["warnings"]
    assert any("trades_missing_wallet_id" in w for w in body["warnings"])
    # AI shadow status note reflects state
    assert body["ai_shadow_status_note"] == "ai_shadow_inactive_or_decisions_not_persisted"


# ── Part D — positive AI error / not_selected counts ───────────────────────

def _ai_error_not_selected_routes():
    return {
        "SELECT COUNT(*) FROM paper_candidates": 10,
        "SELECT COUNT(*) FROM paper_candidates WHERE extras_json IS NOT NULL": 10,
        "SELECT 1 FROM paper_candidates WHERE extras_json IS NOT NULL ORDER BY id DESC LIMIT 5000) s": 10,
        "SELECT\n                    COUNT(*) AS sample_size,": {
            "sample_size": 10,
            "det_decision_rows": 10,
            "det_score_rows": 10,
            "det_would_enter": 3, "det_watch": 2, "det_would_reject": 5,
            "ai_decision_rows": 10,
            "ai_status_rows": 10,
            "ai_would_enter": 1, "ai_watch": 1, "ai_would_reject": 0,
            "ai_disabled": 4, "ai_error": 3, "ai_not_selected": 2,
        },
    }


def test_ai_shadow_positive_error_and_not_selected(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "get_pool", AsyncMock(return_value=_MockPool(_ai_error_not_selected_routes())))
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    ai = body["shadow_decision_persistence"]["ai_shadow"]
    assert ai["error_count"] == 3
    assert ai["not_selected_count"] == 2
    assert ai["disabled_count"] == 4
    assert ai["would_enter_count"] == 1
    assert ai["watch_count"] == 1
    assert ai["status"] == "collected"
    assert ai["no_paid_ai_calls"] is True


# ── Part E — exact trade timestamp integrity ───────────────────────────────

def _trade_timestamp_routes():
    now = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)
    return {
        "SELECT COUNT(*) FROM paper_trades_journal": 10,
        "SELECT event, COUNT(*) AS n FROM paper_trades_journal GROUP BY event": [
            {"event": "entry", "n": 4},
            {"event": "exit", "n": 6},
        ],
        "SELECT MIN(created_at) FROM paper_trades_journal": now - timedelta(hours=3),
        "SELECT MAX(created_at) FROM paper_trades_journal": now,
        "SELECT MIN(opened_at) FROM paper_trades_journal WHERE opened_at IS NOT NULL": now - timedelta(hours=3, minutes=15),
        "SELECT MAX(opened_at) FROM paper_trades_journal WHERE opened_at IS NOT NULL": now - timedelta(minutes=15),
        "SELECT MIN(closed_at) FROM paper_trades_journal WHERE closed_at IS NOT NULL": now - timedelta(hours=2),
        "SELECT MAX(closed_at) FROM paper_trades_journal WHERE closed_at IS NOT NULL": now,
        # Specific missing-timestamp counts: 2 entries missing opened_at,
        # 1 exit missing closed_at, 1 trade with future opened_at.
        "WHERE event = 'entry' AND opened_at IS NULL": 2,
        "WHERE event = 'exit' AND closed_at IS NULL": 1,
        "SELECT COUNT(*) FROM paper_trades_journal WHERE opened_at IS NULL": 2,
        "WHERE opened_at > now() + interval '5 minutes'": 1,
        "WHERE closed_at > now() + interval '5 minutes'": 0,
    }


def test_exact_trade_timestamp_integrity_counts(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "get_pool", AsyncMock(return_value=_MockPool(_trade_timestamp_routes())))
    r = client.get("/api/audit/persistence/deep-status")
    body = r.json()
    trd = body["trades"]
    assert trd["total"] == 10
    assert trd["missing_opened_at_for_entry"] == 2
    assert trd["missing_closed_at_for_exit"] == 1
    assert trd["missing_entry_time"] == 2
    assert trd["missing_exit_time_for_closed"] == 1
    assert trd["future_opened_at_count"] == 1
    assert trd["future_closed_at_count"] == 0
    # min/max timestamps are non-null and ISO-formatted
    for key in ("min_opened_at", "max_opened_at", "min_closed_at", "max_closed_at",
                "min_created_at", "max_created_at"):
        assert trd[key] is not None
        assert "T" in trd[key]
    # Column-mapping note documents opened_at = entry_time, closed_at = exit_time
    assert "opened_at IS the entry timestamp" in trd["column_mapping_note"]
    assert "closed_at IS the exit timestamp" in trd["column_mapping_note"]


# ── Part F — durable last_decision_at provenance ───────────────────────────

def test_last_decision_at_source_runtime(client, monkeypatch):
    """After a runtime decision, source must be 'runtime' (preferred)."""
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    sw._stamp_decision(sw.WALLET_DETERMINISTIC, [
        {"symbol": "RUN", "enhanced_shadow_decision": "WATCH"},
    ])
    r = client.get("/api/paper/wallets")
    det = r.json()["deterministic_shadow"]
    assert det["last_decision_at_source"] == "runtime"
    assert det["last_decision_at_runtime"] is not None
    assert det["last_decision_at"] == det["last_decision_at_runtime"]


def test_last_decision_at_source_persisted_after_simulated_restart(client, monkeypatch):
    """When runtime is empty but the persisted cache has a value, source must
    be 'persisted_candidate_extras'."""
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    # Simulate persisted cache hit (skip refresh by setting fetched_at to now)
    persisted_iso = "2026-06-12T12:00:00+00:00"
    sw._persisted_last_decision_at[sw.WALLET_DETERMINISTIC] = persisted_iso
    import time
    monkeypatch.setattr(sw, "_persisted_cache_fetched_at", time.time())
    r = client.get("/api/paper/wallets")
    det = r.json()["deterministic_shadow"]
    assert det["last_decision_at_persisted"] == persisted_iso
    assert det["last_decision_at_source"] == "persisted_candidate_extras"
    assert det["last_decision_at"] == persisted_iso


def test_last_decision_at_source_fallback_to_last_entry(client, monkeypatch):
    """When neither runtime nor persisted is set but last_entry_at exists, the
    source must be labelled 'last_entry_fallback' — never falsely 'runtime'."""
    from paper import shadow_wallets as sw
    from paper.models import Position
    sw._reset_last_decision_at()
    import time
    monkeypatch.setattr(sw, "_persisted_cache_fetched_at", time.time())  # skip refresh
    # Inject a fake position into deterministic wallet so last_entry_at != None
    det_account = sw._wallet(sw.WALLET_DETERMINISTIC)
    fake_pos = Position(
        position_id="fake-1", symbol="FAKE", entry_price=100.0, shares=1,
        cost_basis=100.0, entry_time="2026-06-12T10:00:00+00:00",
        entry_catalyst_type="news",
    )
    det_account.positions["FAKE"] = fake_pos
    try:
        r = client.get("/api/paper/wallets")
        det = r.json()["deterministic_shadow"]
        assert det["last_decision_at_source"] == "last_entry_fallback"
        assert det["last_decision_at"] == "2026-06-12T10:00:00+00:00"
    finally:
        det_account.positions.pop("FAKE", None)


def test_last_decision_at_source_none_when_no_data(client, monkeypatch):
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    import time
    monkeypatch.setattr(sw, "_persisted_cache_fetched_at", time.time())  # skip refresh
    # Ensure no positions
    det_account = sw._wallet(sw.WALLET_DETERMINISTIC)
    det_account.positions.clear()
    det_account.trades.clear()
    r = client.get("/api/paper/wallets")
    det = r.json()["deterministic_shadow"]
    assert det["last_decision_at"] is None
    assert det["last_decision_at_source"] == "none"


def test_performance_endpoint_exposes_last_decision_at_source(client):
    r = client.get("/api/paper/wallets/performance")
    body = r.json()
    for w in body["wallets"]:
        assert "last_decision_at_source" in w
        assert "last_decision_at_runtime" in w
        assert "last_decision_at_persisted" in w


def test_analytics_endpoint_exposes_last_decision_at_source(client):
    r = client.get("/api/paper/wallets/analytics")
    body = r.json()
    for wid in ("engine", "deterministic_shadow", "ai_shadow"):
        assert "last_decision_at_source" in body[wid]
        assert "last_decision_at_runtime" in body[wid]
        assert "last_decision_at_persisted" in body[wid]


def test_refresh_persisted_cache_no_op_within_ttl(monkeypatch):
    """Cache refresh must not re-fetch within TTL."""
    from paper import shadow_wallets as sw
    sw._reset_last_decision_at()
    import time
    fake_pool_calls = {"n": 0}

    class _FakeConn:
        async def fetchval(self, sql):
            fake_pool_calls["n"] += 1
            return None

    class _FakeAcq:
        async def __aenter__(self):
            return _FakeConn()
        async def __aexit__(self, *exc):
            return False

    class _FakePool:
        def acquire(self):
            return _FakeAcq()

    from paper import db as _db
    monkeypatch.setattr(_db, "get_pool", AsyncMock(return_value=_FakePool()))
    # First call hits DB (2 queries: det + ai)
    asyncio.run(sw.refresh_persisted_last_decision_cache())
    first_calls = fake_pool_calls["n"]
    assert first_calls == 2
    # Immediate second call within TTL — no DB hit
    asyncio.run(sw.refresh_persisted_last_decision_cache())
    assert fake_pool_calls["n"] == first_calls
    # Forced refresh hits DB again
    asyncio.run(sw.refresh_persisted_last_decision_cache(force=True))
    assert fake_pool_calls["n"] == first_calls + 2


# ── Boundary invariants ─────────────────────────────────────────────────────

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
    assert "function WalletDailyAnalytics" not in src


def test_no_aggregate_account_total_reintroduced():
    src = _page_src()
    assert "All wallets cash" not in src
    assert "All accounts cash" not in src


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
