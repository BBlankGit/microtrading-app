"""
Tests for Phase 2G: journal hardening, attribution, indexes, and DB readiness recovery.

No broker. No real orders. Research-only fake-money simulation.
No real Polygon API calls.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _disable_pool(monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_pool", None)
    monkeypatch.setattr(_db, "_tables_ready", False)
    async def _no_pool():
        return None
    monkeypatch.setattr(_db, "get_pool", _no_pool)


# ── Safety: no broker/AI imports ─────────────────────────────────────────────

def test_db_no_broker_imports():
    import pathlib
    text = (pathlib.Path(__file__).parent.parent / "paper" / "db.py").read_text()
    for f in ("alpaca", "execute_order", "place_order", "openai", "anthropic", "langchain"):
        assert f not in text.lower(), f"Forbidden '{f}' in db.py"


def test_journal_no_broker_imports():
    import pathlib
    text = (pathlib.Path(__file__).parent.parent / "paper" / "journal.py").read_text()
    for f in ("alpaca", "execute_order", "place_order", "openai", "anthropic", "langchain"):
        assert f not in text.lower(), f"Forbidden '{f}' in journal.py"


# ── New indexes present in _CREATE_TABLES ─────────────────────────────────────

def test_new_indexes_in_create_tables():
    from paper.db import _CREATE_TABLES
    expected = [
        "idx_paper_candidates_created_at",
        "idx_paper_candidates_symbol_created_at",
        "idx_paper_candidates_tick_created_at",
        "idx_paper_candidates_rejection_reason",
        "idx_paper_trades_event_created_at",
        "idx_paper_trades_event_symbol_created_at",
    ]
    for idx in expected:
        assert idx in _CREATE_TABLES, f"Missing index: {idx}"


def test_all_indexes_use_if_not_exists():
    from paper.db import _CREATE_TABLES
    import re
    # Every CREATE INDEX must use IF NOT EXISTS
    indexes = re.findall(r"CREATE INDEX\b.*", _CREATE_TABLES, re.IGNORECASE)
    for line in indexes:
        assert "IF NOT EXISTS" in line.upper(), f"Index missing IF NOT EXISTS: {line}"


# ── Config values ─────────────────────────────────────────────────────────────

def test_journal_retry_seconds_in_config():
    from core.config import settings
    assert hasattr(settings, "JOURNAL_RETRY_SECONDS")
    assert settings.JOURNAL_RETRY_SECONDS > 0


def test_journal_retention_days_in_config():
    from core.config import settings
    assert hasattr(settings, "JOURNAL_RETENTION_DAYS")
    assert settings.JOURNAL_RETENTION_DAYS > 0


# ── models.py: entry_score field ─────────────────────────────────────────────

def test_position_has_entry_score():
    from paper.models import Position
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Position)}
    assert "entry_score" in fields


def test_closed_trade_has_entry_score():
    from paper.models import ClosedTrade
    import dataclasses
    fields = {f.name for f in dataclasses.fields(ClosedTrade)}
    assert "entry_score" in fields


def test_position_entry_score_defaults_none():
    from paper.models import Position
    p = Position(
        position_id="x", symbol="TEST", entry_price=10.0,
        shares=5.0, cost_basis=50.0, entry_time="2026-01-01T00:00:00+00:00",
        entry_catalyst_type="news",
    )
    assert p.entry_score is None


def test_position_entry_score_set():
    from paper.models import Position
    p = Position(
        position_id="x", symbol="TEST", entry_price=10.0,
        shares=5.0, cost_basis=50.0, entry_time="2026-01-01T00:00:00+00:00",
        entry_catalyst_type="news", entry_score=85,
    )
    assert p.entry_score == 85


# ── PaperAccount: entry_score flows through ──────────────────────────────────

def test_account_enter_position_stores_entry_score():
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    pos = acc.enter_position("TEST", 10.0, 100.0, "news", entry_score=77)
    assert pos is not None
    assert pos.entry_score == 77


def test_account_exit_position_preserves_entry_score():
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    acc.enter_position("TEST", 10.0, 100.0, "news", entry_score=77)
    trade = acc.exit_position("TEST", 12.0, "take_profit")
    assert trade is not None
    assert trade.entry_score == 77
    assert trade.entry_catalyst_type == "news"


def test_account_exit_without_score_is_none():
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    acc.enter_position("TEST", 10.0, 100.0, "gap_up")
    trade = acc.exit_position("TEST", 11.0, "take_profit")
    assert trade is not None
    assert trade.entry_score is None


# ── persist_tick_result: exit rows carry attribution ─────────────────────────

async def test_persist_exit_row_carries_attribution(monkeypatch):
    from paper import journal, db as _db
    monkeypatch.setattr(journal, "_journal_enabled", True)

    written_exits = []

    class FakeConn:
        async def execute(self, query, *args, **kw):
            if "event" in query and "'exit'" in query:
                written_exits.append(args)
        async def executemany(self, *a, **kw): pass
        def transaction(self): return FakeTx()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class FakeTx:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class FakePoolCtx:
        async def __aenter__(self): return FakeConn()
        async def __aexit__(self, *a): pass

    class FakePool:
        def acquire(self): return FakePoolCtx()

    async def async_get_pool(): return FakePool()
    monkeypatch.setattr(_db, "get_pool", async_get_pool)

    await journal.persist_tick_result(
        {
            "tick_at": "2026-01-01T10:00:00+00:00",
            "symbols_evaluated": 1,
            "entries": [],
            "exits": [{
                "symbol": "TEST",
                "exit_reason": "take_profit",
                "entry_price": 10.0,
                "exit_price": 12.0,
                "pnl": 2.0,
                "pnl_percent": 20.0,
                "hold_minutes": 5.0,
                "catalyst_type": "news",
                "total_score": 85,
            }],
            "candidates": [],
            "errors": [],
            "entries_made": 0,
            "exits_made": 1,
            "universe_active_count": 1,
            "universe_refresh_reason": "test",
        },
        {"cash": 1000, "equity": 1000, "realized_pnl": 2,
         "unrealized_pnl": 0, "total_pnl": 2, "total_pnl_percent": 0.2},
        None,
    )
    # We should have at least one exit row written
    assert len(written_exits) >= 1
    # The args to execute for exit row must include catalyst_type and total_score
    exit_args = written_exits[0]
    assert "news" in exit_args, f"catalyst_type 'news' not in exit args: {exit_args}"
    assert 85 in exit_args, f"total_score 85 not in exit args: {exit_args}"


# ── Journal retry / DB recovery ──────────────────────────────────────────────

async def test_try_reinit_sets_enabled_on_success(monkeypatch):
    from paper import journal, db as _db
    monkeypatch.setattr(journal, "_journal_enabled", False)
    monkeypatch.setattr(journal, "_last_retry_at", None)

    async def mock_init_tables():
        return True
    monkeypatch.setattr(_db, "init_tables", mock_init_tables)

    result = await journal.try_reinit()
    assert result is True
    assert journal._journal_enabled is True


async def test_try_reinit_cooldown_prevents_retry(monkeypatch):
    import time
    from paper import journal, db as _db
    monkeypatch.setattr(journal, "_journal_enabled", False)
    monkeypatch.setattr(journal, "_last_retry_at", time.monotonic())  # just retried

    call_count = {"n": 0}
    async def mock_init_tables():
        call_count["n"] += 1
        return True
    monkeypatch.setattr(_db, "init_tables", mock_init_tables)

    result = await journal.try_reinit()
    assert result is False
    assert call_count["n"] == 0  # cooldown prevented call


async def test_try_reinit_does_not_raise_on_db_error(monkeypatch):
    from paper import journal, db as _db
    monkeypatch.setattr(journal, "_journal_enabled", False)
    monkeypatch.setattr(journal, "_last_retry_at", None)

    async def mock_init_tables():
        raise RuntimeError("simulated DB failure")
    monkeypatch.setattr(_db, "init_tables", mock_init_tables)

    result = await journal.try_reinit()
    assert result is False
    assert journal._journal_enabled is False


async def test_persist_skips_reinit_when_no_database_url(monkeypatch):
    """No DATABASE_URL → reinit must NOT be attempted (avoids noisy reconnects)."""
    import core.config as _cfg
    from unittest.mock import MagicMock
    from paper import journal

    monkeypatch.setattr(journal, "_journal_enabled", False)
    monkeypatch.setattr(journal, "_last_retry_at", None)

    fake_settings = MagicMock()
    fake_settings.DATABASE_URL = ""
    fake_settings.JOURNAL_RETRY_SECONDS = 30
    monkeypatch.setattr(_cfg, "settings", fake_settings)

    reinit_called = {"n": 0}
    async def mock_reinit():
        reinit_called["n"] += 1
        return False
    monkeypatch.setattr(journal, "try_reinit", mock_reinit)

    result = await journal.persist_tick_result(
        {"tick_at": "2026-01-01T10:00:00+00:00", "symbols_evaluated": 0,
         "entries": [], "exits": [], "candidates": [], "errors": [],
         "entries_made": 0, "exits_made": 0, "universe_active_count": 0,
         "universe_refresh_reason": "test"},
        {"cash": 1000, "equity": 1000, "realized_pnl": 0,
         "unrealized_pnl": 0, "total_pnl": 0, "total_pnl_percent": 0},
        None,
    )
    assert result.get("skipped") is True
    assert reinit_called["n"] == 0, "reinit must not be called when DATABASE_URL is empty"


async def test_persist_attempts_reinit_when_database_url_configured(monkeypatch):
    """Non-empty DATABASE_URL → reinit IS attempted once when journal is disabled."""
    import core.config as _cfg
    from unittest.mock import MagicMock
    from paper import journal

    monkeypatch.setattr(journal, "_journal_enabled", False)
    monkeypatch.setattr(journal, "_last_retry_at", None)

    fake_settings = MagicMock()
    fake_settings.DATABASE_URL = "postgresql://dummy:dummy@localhost/testdb"
    fake_settings.JOURNAL_RETRY_SECONDS = 30
    monkeypatch.setattr(_cfg, "settings", fake_settings)

    reinit_called = {"n": 0}
    async def mock_reinit():
        reinit_called["n"] += 1
        return False  # fails — no real DB needed
    monkeypatch.setattr(journal, "try_reinit", mock_reinit)

    result = await journal.persist_tick_result(
        {"tick_at": "2026-01-01T10:00:00+00:00", "symbols_evaluated": 0,
         "entries": [], "exits": [], "candidates": [], "errors": [],
         "entries_made": 0, "exits_made": 0, "universe_active_count": 0,
         "universe_refresh_reason": "test"},
        {"cash": 1000, "equity": 1000, "realized_pnl": 0,
         "unrealized_pnl": 0, "total_pnl": 0, "total_pnl_percent": 0},
        None,
    )
    assert result.get("skipped") is True
    assert reinit_called["n"] == 1, "reinit must be attempted once when DATABASE_URL is set"


# ── Journal status endpoint ───────────────────────────────────────────────────

def test_journal_status_has_retention_fields(client):
    resp = client.get("/api/journal/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "retention_days" in data
    assert "auto_cleanup_enabled" in data
    assert data["auto_cleanup_enabled"] is False
    assert isinstance(data["retention_days"], int)


def test_journal_status_has_last_retry_at(client):
    resp = client.get("/api/journal/status")
    data = resp.json()
    assert "last_retry_at" in data


# ── Retention status endpoint ─────────────────────────────────────────────────

def test_retention_status_returns_200(client):
    resp = client.get("/api/journal/retention/status")
    assert resp.status_code == 200


def test_retention_status_has_required_keys(client):
    resp = client.get("/api/journal/retention/status")
    data = resp.json()
    for key in ("retention_days", "auto_cleanup_enabled",
                "total_ticks", "total_candidates",
                "oldest_tick_at", "newest_tick_at"):
        assert key in data, f"Missing key: {key}"


def test_retention_status_auto_cleanup_false(client):
    resp = client.get("/api/journal/retention/status")
    assert resp.json()["auto_cleanup_enabled"] is False


def test_retention_status_retention_days_positive(client):
    resp = client.get("/api/journal/retention/status")
    assert resp.json()["retention_days"] > 0


def test_retention_status_disabled_returns_nulls(client, monkeypatch):
    _disable_pool(monkeypatch)
    resp = client.get("/api/journal/retention/status")
    data = resp.json()
    assert data["total_ticks"] is None
    assert data["total_candidates"] is None


# ── Monitoring warnings ───────────────────────────────────────────────────────

def test_monitoring_warns_on_last_journal_ok_false(client, monkeypatch):
    from paper import journal
    monkeypatch.setattr(journal, "_last_persist_ok", False)
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert any("last journal write failed" in w.lower() for w in data["warnings"])


def test_monitoring_no_write_failed_warning_when_ok(client, monkeypatch):
    from paper import journal
    monkeypatch.setattr(journal, "_last_persist_ok", True)
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert not any("last journal write failed" in w.lower() for w in data["warnings"])


def test_monitoring_no_write_failed_warning_when_none(client, monkeypatch):
    from paper import journal
    monkeypatch.setattr(journal, "_last_persist_ok", None)
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert not any("last journal write failed" in w.lower() for w in data["warnings"])


# ── get_journal_status includes last_retry_at ────────────────────────────────

def test_get_journal_status_has_last_retry_at():
    from paper.journal import get_journal_status
    j = get_journal_status()
    assert "last_retry_at" in j


# ── Performance attribution grouping ─────────────────────────────────────────

async def test_performance_groups_by_catalyst_and_score_when_attribution_present(monkeypatch):
    """Exit rows that carry catalyst_type and total_score produce correct buckets."""
    from paper import db as _db

    exit_rows = [
        {"pnl": 10.0, "catalyst_type": "news",    "total_score": 85},
        {"pnl": -5.0, "catalyst_type": "gap_up",  "total_score": 75},
        {"pnl":  3.0, "catalyst_type": "news",    "total_score": 62},
    ]

    class FakeConn:
        async def fetch(self, *a, **kw): return exit_rows
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class FakePoolCtx:
        async def __aenter__(self): return FakeConn()
        async def __aexit__(self, *a): pass

    class FakePool:
        def acquire(self): return FakePoolCtx()

    async def async_get_pool(): return FakePool()
    monkeypatch.setattr(_db, "get_pool", async_get_pool)

    from api.journal import journal_performance
    result = await journal_performance()

    assert result["total_trades"] == 3

    cats = {r["type"]: r for r in result["pnl_by_catalyst_type"]}
    assert "news" in cats, "news catalyst should be present"
    assert "gap_up" in cats, "gap_up catalyst should be present"
    assert cats["news"]["count"] == 2
    assert abs(cats["news"]["total_pnl"] - 13.0) < 0.01
    assert "unknown" not in cats, "unknown catalyst must not appear when attribution is present"

    buckets = {r["bucket"]: r for r in result["pnl_by_score_bucket"]}
    assert "80+" in buckets,    "score 85 → 80+ bucket"
    assert "70-79" in buckets,  "score 75 → 70-79 bucket"
    assert "50-69" in buckets,  "score 62 → 50-69 bucket"
    assert "no_score" not in buckets, "no_score bucket absent when all exits have scores"


# ── Monitoring: high candidate count warning ──────────────────────────────────

def test_monitoring_warns_high_candidate_count(client, monkeypatch):
    """Monitoring warns when candidate row count exceeds the implemented threshold."""
    from paper import db as _db, journal as _journal

    monkeypatch.setattr(_journal, "_journal_enabled", True)

    class FakeConn:
        async def fetchval(self, *a, **kw): return 200_000
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    class FakePoolCtx:
        async def __aenter__(self): return FakeConn()
        async def __aexit__(self, *a): pass

    class FakePool:
        def acquire(self): return FakePoolCtx()

    fake_pool = FakePool()
    monkeypatch.setattr(_db, "_pool", fake_pool)

    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert any("candidate" in w.lower() for w in data["warnings"]), \
        f"Expected high-candidate warning, got: {data['warnings']}"
