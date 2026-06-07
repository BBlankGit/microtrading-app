"""
Tests for Phase 2F: daily session report and monitoring status.

No broker. No real orders. Research-only fake-money simulation.
No real Polygon API calls.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stopped_sim_status(**kw) -> dict:
    base = {
        "running": False,
        "last_tick_at": None,
        "last_error": None,
        "open_position_count": 0,
        "closed_trade_count": 0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "total_pnl_percent": 0.0,
        "cash": 1000.0,
        "equity": 1000.0,
    }
    return {**base, **kw}


def _disable_pool(monkeypatch):
    from paper import db as _db
    monkeypatch.setattr(_db, "_pool", None)
    async def _no_pool():
        return None
    monkeypatch.setattr(_db, "get_pool", _no_pool)


# ── Safety: no broker/AI imports ─────────────────────────────────────────────

def test_monitoring_no_broker_imports():
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "api" / "monitoring.py"
    text = src.read_text()
    for forbidden in ("alpaca", "broker", "execute_order", "place_order",
                       "openai", "anthropic", "langchain"):
        assert forbidden not in text.lower(), f"Forbidden import '{forbidden}' found in monitoring.py"


def test_journal_today_no_broker_imports():
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "api" / "journal.py"
    text = src.read_text()
    for forbidden in ("alpaca", "broker", "execute_order", "place_order",
                       "openai", "anthropic", "langchain"):
        assert forbidden not in text.lower(), f"Forbidden import '{forbidden}' found in journal.py"


# ── _perf_stats unit tests ────────────────────────────────────────────────────

def test_perf_stats_empty():
    from api.journal import _perf_stats
    r = _perf_stats([])
    assert r["win_rate_today"] is None
    assert r["average_win_today"] is None
    assert r["average_loss_today"] is None
    assert r["profit_factor_today"] is None


def test_perf_stats_all_wins():
    from api.journal import _perf_stats
    r = _perf_stats([5.0, 3.0])
    assert r["win_rate_today"] == 100.0
    assert r["profit_factor_today"] is None  # no losses


def test_perf_stats_mixed():
    from api.journal import _perf_stats
    r = _perf_stats([10.0, -5.0])
    assert abs(r["win_rate_today"] - 50.0) < 0.01
    assert abs(r["profit_factor_today"] - 2.0) < 0.01
    assert abs(r["average_win_today"] - 10.0) < 0.01
    assert abs(r["average_loss_today"] - (-5.0)) < 0.01


def test_perf_stats_only_losses():
    from api.journal import _perf_stats
    r = _perf_stats([-3.0, -2.0])
    assert r["win_rate_today"] == 0.0
    assert r["profit_factor_today"] is None
    assert r["average_win_today"] is None


# ── _tick_age unit tests ──────────────────────────────────────────────────────

def test_tick_age_none_for_none():
    from api.journal import _tick_age
    assert _tick_age(None) is None


def test_tick_age_recent():
    from api.journal import _tick_age
    recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    age = _tick_age(recent)
    assert age is not None
    assert 25 <= age <= 40


def test_tick_age_invalid():
    from api.journal import _tick_age
    assert _tick_age("not-a-date") is None


# ── _today_range unit test ────────────────────────────────────────────────────

def test_today_range_returns_three_tuple():
    from api.journal import _today_range
    start, end, date_str = _today_range()
    assert end > start
    assert (end - start).total_seconds() == 86400.0
    assert len(date_str) == 10  # "YYYY-MM-DD"


# ── Monitoring status: structure ──────────────────────────────────────────────

def test_monitoring_status_returns_200(client):
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200


def test_monitoring_status_has_required_keys(client):
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    for key in ("backend_ok", "paper_running", "journal_enabled",
                "journal_database_connected", "journal_tables_ready",
                "last_tick_at", "last_tick_age_seconds", "last_tick_fresh",
                "last_journal_ok", "last_error", "market_session", "warnings"):
        assert key in data, f"Missing key: {key}"


def test_monitoring_status_backend_ok_always_true(client):
    resp = client.get("/api/monitoring/status")
    assert resp.json()["backend_ok"] is True


def test_monitoring_status_market_session_has_keys(client):
    resp = client.get("/api/monitoring/status")
    ms = resp.json()["market_session"]
    for key in ("timezone", "is_regular_session_now", "regular_open",
                "regular_close", "note"):
        assert key in ms


def test_monitoring_status_warnings_is_list(client):
    resp = client.get("/api/monitoring/status")
    assert isinstance(resp.json()["warnings"], list)


# ── Monitoring: freshness logic ───────────────────────────────────────────────

def test_monitoring_fresh_when_stopped(client, monkeypatch):
    import paper.simulator as sim
    monkeypatch.setattr(sim, "get_status", lambda: _stopped_sim_status())
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert data["paper_running"] is False
    assert data["last_tick_fresh"] is True


def test_monitoring_fresh_when_running_no_tick_yet(client, monkeypatch):
    import paper.simulator as sim
    monkeypatch.setattr(sim, "get_status", lambda: _stopped_sim_status(
        running=True, last_tick_at=None
    ))
    resp = client.get("/api/monitoring/status")
    assert resp.json()["last_tick_fresh"] is True


def test_monitoring_stale_tick_adds_warning(client, monkeypatch):
    import paper.simulator as sim
    from core.config import settings
    stale_at = (datetime.now(timezone.utc) - timedelta(
        seconds=2 * settings.PAPER_POLL_INTERVAL_SECONDS + 60
    )).isoformat()
    monkeypatch.setattr(sim, "get_status", lambda: _stopped_sim_status(
        running=True, last_tick_at=stale_at
    ))
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert data["last_tick_fresh"] is False
    assert any("stale" in w.lower() for w in data["warnings"])


def test_monitoring_fresh_tick_no_stale_warning(client, monkeypatch):
    import paper.simulator as sim
    fresh_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    monkeypatch.setattr(sim, "get_status", lambda: _stopped_sim_status(
        running=True, last_tick_at=fresh_at
    ))
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert data["last_tick_fresh"] is True
    assert not any("stale" in w.lower() for w in data["warnings"])


# ── Monitoring: journal-disabled warning ─────────────────────────────────────

def test_monitoring_warning_when_journal_disabled(client, monkeypatch):
    from paper import journal
    monkeypatch.setattr(journal, "_journal_enabled", False)
    resp = client.get("/api/monitoring/status")
    data = resp.json()
    assert data["journal_enabled"] is False
    assert any("disabled" in w.lower() for w in data["warnings"])


# ── Today endpoints: structure when DB available ──────────────────────────────

def test_today_summary_returns_200(client):
    resp = client.get("/api/journal/today/summary")
    assert resp.status_code == 200


def test_today_summary_has_required_keys(client):
    resp = client.get("/api/journal/today/summary")
    data = resp.json()
    if "error" in data:
        return  # journal disabled in this test run
    for key in ("trading_date", "total_ticks_today", "total_candidates_today",
                "total_entries_today", "total_exits_today",
                "unique_symbols_seen_today", "open_positions_current",
                "closed_trades_today", "realized_pnl_today",
                "win_rate_today", "profit_factor_today",
                "first_tick_at", "last_tick_at", "last_tick_age_seconds",
                "journal_healthy", "notes"):
        assert key in data, f"Missing key: {key}"


def test_today_summary_trading_date_format(client):
    resp = client.get("/api/journal/today/summary")
    data = resp.json()
    if "error" not in data:
        assert len(data["trading_date"]) == 10
        assert data["trading_date"][4] == "-"


def test_today_summary_journal_healthy_is_bool(client):
    resp = client.get("/api/journal/today/summary")
    data = resp.json()
    if "error" not in data:
        assert isinstance(data["journal_healthy"], bool)


def test_today_summary_notes_is_list(client):
    resp = client.get("/api/journal/today/summary")
    data = resp.json()
    if "error" not in data:
        assert isinstance(data["notes"], list)


def test_today_rejections_returns_list_or_error(client):
    resp = client.get("/api/journal/today/rejections")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or "error" in data


def test_today_rejections_items_have_reason_and_count(client):
    resp = client.get("/api/journal/today/rejections")
    data = resp.json()
    if isinstance(data, list):
        for item in data:
            assert "reason" in item
            assert "count" in item


def test_today_catalysts_returns_list_or_error(client):
    resp = client.get("/api/journal/today/catalysts")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or "error" in data


def test_today_catalysts_items_have_required_fields(client):
    resp = client.get("/api/journal/today/catalysts")
    data = resp.json()
    if isinstance(data, list):
        for item in data:
            for key in ("type", "candidate_count", "entries", "exits"):
                assert key in item


def test_today_symbols_returns_list_or_error(client):
    resp = client.get("/api/journal/today/symbols")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or "error" in data


def test_today_symbols_items_have_required_fields(client):
    resp = client.get("/api/journal/today/symbols")
    data = resp.json()
    if isinstance(data, list):
        for item in data:
            for key in ("symbol", "candidate_count", "entries",
                        "exits", "avg_score", "last_seen_at"):
                assert key in item


def test_today_symbols_limit_param(client):
    resp = client.get("/api/journal/today/symbols?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    if isinstance(data, list):
        assert len(data) <= 5


def test_today_report_returns_200(client):
    resp = client.get("/api/journal/today/report")
    assert resp.status_code == 200


def test_today_report_has_all_sections(client):
    resp = client.get("/api/journal/today/report")
    data = resp.json()
    if "error" not in data:
        for key in ("summary", "top_rejections", "catalysts",
                    "symbols", "latest_ticks"):
            assert key in data, f"Missing section: {key}"


def test_today_report_sections_are_correct_types(client):
    resp = client.get("/api/journal/today/report")
    data = resp.json()
    if "error" not in data:
        assert isinstance(data["top_rejections"], list)
        assert isinstance(data["catalysts"], list)
        assert isinstance(data["symbols"], list)
        assert isinstance(data["latest_ticks"], list)


# ── Today endpoints: CSV ──────────────────────────────────────────────────────

def test_today_report_csv_returns_200(client):
    resp = client.get("/api/journal/today/report.csv")
    assert resp.status_code == 200


def test_today_report_csv_content_type(client):
    resp = client.get("/api/journal/today/report.csv")
    assert "text/csv" in resp.headers.get("content-type", "")


def test_today_report_csv_has_header_row(client):
    resp = client.get("/api/journal/today/report.csv")
    text = resp.text
    first_line = text.splitlines()[0] if text.strip() else ""
    if not first_line.startswith("error"):
        assert "symbol" in first_line
        assert "trading_date" in first_line


# ── Disabled-state behavior ───────────────────────────────────────────────────

def test_today_summary_disabled_returns_error(client, monkeypatch):
    _disable_pool(monkeypatch)
    resp = client.get("/api/journal/today/summary")
    assert resp.status_code == 200
    assert "error" in resp.json()


def test_today_rejections_disabled_returns_error(client, monkeypatch):
    _disable_pool(monkeypatch)
    resp = client.get("/api/journal/today/rejections")
    assert "error" in resp.json()


def test_today_catalysts_disabled_returns_error(client, monkeypatch):
    _disable_pool(monkeypatch)
    resp = client.get("/api/journal/today/catalysts")
    assert "error" in resp.json()


def test_today_symbols_disabled_returns_error(client, monkeypatch):
    _disable_pool(monkeypatch)
    resp = client.get("/api/journal/today/symbols")
    assert "error" in resp.json()


def test_today_report_disabled_returns_error(client, monkeypatch):
    _disable_pool(monkeypatch)
    resp = client.get("/api/journal/today/report")
    assert "error" in resp.json()


# ── last_persist_ok tracking ──────────────────────────────────────────────────

def test_journal_status_includes_last_persist_ok(client):
    resp = client.get("/api/journal/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "last_persist_ok" in data


async def test_persist_sets_last_persist_ok_true(monkeypatch):
    from paper import journal, db as _db
    monkeypatch.setattr(journal, "_journal_enabled", True)

    tick_written = {}

    class FakeConn:
        async def execute(self, *a, **kw): pass
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
        def acquire(self):
            return FakePoolCtx()

    monkeypatch.setattr(_db, "get_pool", lambda: FakePool())

    # Make get_pool async
    async def async_get_pool():
        return FakePool()
    monkeypatch.setattr(_db, "get_pool", async_get_pool)

    await journal.persist_tick_result(
        {"tick_at": "2026-01-01T10:00:00+00:00", "symbols_evaluated": 0,
         "entries": [], "exits": [], "candidates": [], "errors": [],
         "entries_made": 0, "exits_made": 0, "universe_active_count": 0,
         "universe_refresh_reason": "test"},
        {"cash": 1000, "equity": 1000, "realized_pnl": 0,
         "unrealized_pnl": 0, "total_pnl": 0, "total_pnl_percent": 0},
        None,
    )
    assert journal._last_persist_ok is True
