"""
Tests for the Phase 2E paper journal.

No broker. No real orders. Research-only fake-money simulation.
Integration tests use the real database when available;
unit tests are pure computation with no external calls.
"""

import pytest


# ── Helper builders ───────────────────────────────────────────────────────────

def _tick_result(
    entries=None,
    exits=None,
    candidates=None,
    symbols_evaluated=5,
    universe_active_count=10,
) -> dict:
    return {
        "tick_at": "2026-01-01T10:00:00+00:00",
        "symbols_evaluated": symbols_evaluated,
        "entries": entries or [],
        "exits": exits or [],
        "candidates": candidates or [],
        "errors": [],
        "universe_active_count": universe_active_count,
        "universe_refresh_reason": "ttl",
        "entries_made": len(entries or []),
        "exits_made": len(exits or []),
    }


def _account_status() -> dict:
    return {
        "cash": 800.0,
        "equity": 850.0,
        "realized_pnl": 10.0,
        "unrealized_pnl": 40.0,
        "total_pnl": 50.0,
        "total_pnl_percent": 5.0,
    }


def _universe() -> dict:
    return {
        "active_symbols": ["AAPL", "MSFT"],
        "active_count": 2,
        "max_symbols_per_tick": 50,
        "last_refreshed_at": "2026-01-01T09:00:00+00:00",
        "refresh_reason": "ttl",
        "errors": [],
    }


# ── Unit tests: helpers ───────────────────────────────────────────────────────

def test_float_helper_handles_none():
    from paper.journal import _float
    assert _float(None) is None


def test_float_helper_handles_string():
    from paper.journal import _float
    assert abs(_float("3.14") - 3.14) < 1e-6  # type: ignore[operator]


def test_float_helper_handles_int():
    from paper.journal import _float
    assert _float(42) == 42.0


def test_float_helper_handles_invalid():
    from paper.journal import _float
    assert _float("not_a_number") is None


def test_int_helper_handles_none():
    from paper.journal import _int
    assert _int(None) is None


def test_int_helper_handles_float():
    from paper.journal import _int
    assert _int(3.7) == 3


def test_bool_helper_handles_none():
    from paper.journal import _bool
    assert _bool(None) is None


def test_bool_helper_truthy():
    from paper.journal import _bool
    assert _bool(True) is True
    assert _bool(1) is True


def test_parse_dt_handles_iso():
    from paper.journal import _parse_dt
    dt = _parse_dt("2026-01-01T10:00:00+00:00")
    assert dt is not None
    assert dt.year == 2026


def test_parse_dt_handles_none():
    from paper.journal import _parse_dt
    assert _parse_dt(None) is None


def test_parse_dt_handles_empty_string():
    from paper.journal import _parse_dt
    assert _parse_dt("") is None


def test_parse_dt_handles_invalid():
    from paper.journal import _parse_dt
    assert _parse_dt("not_a_date") is None


# ── Unit tests: persist_tick_result when disabled ─────────────────────────────

async def test_persist_skipped_when_journal_disabled():
    from paper import journal
    original = journal._journal_enabled
    journal._journal_enabled = False
    try:
        result = await journal.persist_tick_result({}, {}, None)
        assert result["ok"] is False
        assert result["skipped"] is True
        assert result["reason"] == "journal disabled"
    finally:
        journal._journal_enabled = original


async def test_persist_skipped_when_no_pool(monkeypatch):
    from paper import journal, db as _db
    monkeypatch.setattr(journal, "_journal_enabled", True)
    monkeypatch.setattr(_db, "_pool", None)
    # Also patch get_pool to return None so it doesn't try to reconnect
    async def _no_pool():
        return None
    monkeypatch.setattr(_db, "get_pool", _no_pool)
    result = await journal.persist_tick_result({}, {}, None)
    assert result["ok"] is False
    assert result["skipped"] is True


# ── Unit tests: get_journal_status ────────────────────────────────────────────

def test_journal_status_structure():
    from paper.journal import get_journal_status
    status = get_journal_status()
    assert "enabled" in status
    assert "database_connected" in status
    assert "tables_ready" in status
    assert "last_error" in status


def test_journal_status_returns_bool_for_enabled():
    from paper.journal import get_journal_status
    status = get_journal_status()
    assert isinstance(status["enabled"], bool)
    assert isinstance(status["tables_ready"], bool)


# ── API integration tests ─────────────────────────────────────────────────────

def test_journal_status_endpoint_returns_200(client):
    resp = client.get("/api/journal/status")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("enabled", "database_connected", "tables_ready"):
        assert key in data


def test_journal_summary_endpoint_returns_200(client):
    resp = client.get("/api/journal/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


def test_journal_summary_has_expected_keys_when_enabled(client):
    resp = client.get("/api/journal/summary")
    assert resp.status_code == 200
    data = resp.json()
    if "error" not in data:
        for key in ("total_ticks", "total_candidates", "total_entries",
                    "total_exits", "total_closed_trades"):
            assert key in data


def test_journal_ticks_returns_list(client):
    resp = client.get("/api/journal/ticks")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or "error" in data


def test_journal_ticks_limit_param(client):
    resp = client.get("/api/journal/ticks?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, list):
        assert len(data) <= 3


def test_journal_candidates_returns_list(client):
    resp = client.get("/api/journal/candidates")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or "error" in data


def test_journal_candidates_limit_param(client):
    resp = client.get("/api/journal/candidates?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, list):
        assert len(data) <= 5


def test_journal_candidates_symbol_filter(client):
    resp = client.get("/api/journal/candidates?symbol=AAPL&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, list):
        for row in data:
            assert row["symbol"] == "AAPL"


def test_journal_candidates_tick_id_filter(client):
    resp = client.get("/api/journal/candidates?tick_id=nonexistent-tick-id")
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, list):
        assert len(data) == 0


def test_journal_trades_returns_list(client):
    resp = client.get("/api/journal/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or "error" in data


def test_journal_trades_limit_param(client):
    resp = client.get("/api/journal/trades?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, list):
        assert len(data) <= 10


def test_journal_rejections_returns_list(client):
    resp = client.get("/api/journal/rejections")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or "error" in data


def test_journal_rejections_limit_param(client):
    resp = client.get("/api/journal/rejections?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, list):
        assert len(data) <= 5


def test_journal_performance_returns_200(client):
    resp = client.get("/api/journal/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


def test_journal_performance_structure(client):
    resp = client.get("/api/journal/performance")
    data = resp.json()
    if "error" not in data:
        for key in ("total_trades", "win_rate", "avg_win", "avg_loss",
                    "profit_factor", "best_trade", "worst_trade",
                    "pnl_by_catalyst_type", "pnl_by_score_bucket"):
            assert key in data


# ── API: disabled-state behavior ──────────────────────────────────────────────

def test_journal_summary_disabled_returns_error_key(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_pool", None)
    async def _no_pool():
        return None
    monkeypatch.setattr(_db, "get_pool", _no_pool)
    resp = client.get("/api/journal/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_journal_ticks_disabled_returns_error_key(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_pool", None)
    async def _no_pool():
        return None
    monkeypatch.setattr(_db, "get_pool", _no_pool)
    resp = client.get("/api/journal/ticks")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_journal_performance_disabled_returns_error_key(client, monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_pool", None)
    async def _no_pool():
        return None
    monkeypatch.setattr(_db, "get_pool", _no_pool)
    resp = client.get("/api/journal/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


# ── db module tests ───────────────────────────────────────────────────────────

def test_db_pool_exists_false_when_no_pool(monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_pool", None)
    assert _db.pool_exists() is False


def test_db_is_ready_reflects_tables_ready(monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_tables_ready", False)
    assert _db.is_ready() is False


def test_db_last_error_returns_none_when_none(monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_init_error", None)
    assert _db.last_error() is None
