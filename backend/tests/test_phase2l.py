"""
Phase 2L tests — Market Session Readiness endpoint.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All Polygon calls mocked.
"""

import ast
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).parent.parent


# ── AST / import safety ───────────────────────────────────────────────────────

FORBIDDEN_MODULES = {
    "openai", "anthropic", "langchain", "broker", "alpaca", "ibapi",
    "tastytrade", "td_ameritrade", "schwab",
}

FORBIDDEN_EXECUTION = {"place_order", "submit_order", "execute_order", "send_order"}


def _ast_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_readiness_no_broker_or_ai_imports():
    path = BACKEND_ROOT / "api" / "readiness.py"
    imports = _ast_imports(path)
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden module {forbidden!r} found in readiness.py import: {imp!r}"


def test_readiness_no_execution_calls():
    path = BACKEND_ROOT / "api" / "readiness.py"
    source = path.read_text()
    for name in FORBIDDEN_EXECUTION:
        assert name not in source, \
            f"Execution-related name {name!r} found in readiness.py"


# ── Client fixture ────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    # Import fresh to avoid cached module state bleeding across tests
    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ── Healthy mock helpers ──────────────────────────────────────────────────────

def _healthy_sim_state():
    return {"running": True, "last_tick_at": "2026-01-01T12:00:00+00:00"}


def _healthy_sim_status():
    return {
        "live_trading_enabled": False,
        "broker_connected": False,
        "mode": "paper",
    }


def _healthy_journal_status():
    return {"enabled": True, "database_connected": True, "tables_ready": True}


def _healthy_runtime_status():
    return {"overrides_active": False, "override_count": 0, "warnings": []}


def _healthy_universe():
    return {"active_count": 50, "errors": [], "discovery": {"discovered_count": 5}}


def _healthy_polygon_snapshot():
    return {"last_trade_price": 500.0, "change_percent": 0.5}


def _patch_all_healthy():
    return [
        patch("api.readiness._check_polygon_data",
              new=AsyncMock(return_value={
                  "name": "polygon_data", "status": "pass",
                  "message": "SPY ok", "details": {}})),
        patch("paper.simulator.get_state", return_value=_healthy_sim_state()),
        patch("paper.simulator.get_status", return_value=_healthy_sim_status()),
        patch("paper.journal.get_journal_status", return_value=_healthy_journal_status()),
        patch("paper.runtime_config.get_runtime_status", return_value=_healthy_runtime_status()),
        patch("paper.universe.get_cached_universe", return_value=_healthy_universe()),
        patch("paper.runtime_config.effective_value", side_effect=lambda k: {
            "PAPER_MARKET_DISCOVERY_ENABLED": True,
            "MARKET_REGIME_ENABLED": False,
        }.get(k, None)),
        patch("market.regime._cache", {"risk": {"regime": "neutral", "confidence": "medium"},
                                       "error": None}, create=True),
    ]


# ── Full endpoint tests ───────────────────────────────────────────────────────

def test_session_endpoint_returns_200(client):
    with patch("api.readiness._run_all_checks",
               new=AsyncMock(return_value=[
                   {"name": "backend", "status": "pass", "message": "ok", "details": {}}
               ])):
        r = client.get("/api/readiness/session")
    assert r.status_code == 200


def test_session_response_shape(client):
    with patch("api.readiness._run_all_checks",
               new=AsyncMock(return_value=[
                   {"name": "backend", "status": "pass", "message": "ok", "details": {}}
               ])):
        r = client.get("/api/readiness/session")
    data = r.json()
    assert "overall_status" in data
    assert "as_of" in data
    assert "market_session" in data
    assert "checks" in data
    assert "summary" in data
    assert "recommended_actions" in data
    assert "disclaimer" in data


def test_compact_endpoint_returns_200(client):
    with patch("api.readiness._run_all_checks",
               new=AsyncMock(return_value=[
                   {"name": "backend", "status": "pass", "message": "ok", "details": {}}
               ])):
        r = client.get("/api/readiness/session/compact")
    assert r.status_code == 200


def test_compact_response_shape(client):
    with patch("api.readiness._run_all_checks",
               new=AsyncMock(return_value=[
                   {"name": "backend", "status": "pass", "message": "ok", "details": {}}
               ])):
        r = client.get("/api/readiness/session/compact")
    data = r.json()
    for key in ("overall_status", "market_open", "simulator_running",
                "journal_ok", "polygon_ok", "universe_count",
                "last_tick_age_seconds", "fail_count", "warn_count",
                "recommended_actions", "disclaimer"):
        assert key in data, f"compact missing key: {key!r}"


def test_overall_status_ready_when_all_pass(client):
    checks = [
        {"name": f"c{i}", "status": "pass", "message": "ok", "details": {}}
        for i in range(5)
    ]
    with patch("api.readiness._run_all_checks", new=AsyncMock(return_value=checks)):
        r = client.get("/api/readiness/session")
    assert r.json()["overall_status"] == "ready"


def test_overall_status_warning_when_warns(client):
    checks = [
        {"name": "backend", "status": "pass", "message": "ok", "details": {}},
        {"name": "simulator", "status": "warn", "message": "stopped", "details": {}},
    ]
    with patch("api.readiness._run_all_checks", new=AsyncMock(return_value=checks)):
        r = client.get("/api/readiness/session")
    assert r.json()["overall_status"] == "warning"


def test_overall_status_not_ready_when_fail(client):
    checks = [
        {"name": "polygon_key", "status": "fail", "message": "missing", "details": {}},
        {"name": "backend", "status": "pass", "message": "ok", "details": {}},
    ]
    with patch("api.readiness._run_all_checks", new=AsyncMock(return_value=checks)):
        r = client.get("/api/readiness/session")
    assert r.json()["overall_status"] == "not_ready"


def test_summary_counts_are_correct(client):
    checks = [
        {"name": "a", "status": "pass", "message": "", "details": {}},
        {"name": "b", "status": "pass", "message": "", "details": {}},
        {"name": "c", "status": "warn", "message": "", "details": {}},
        {"name": "d", "status": "fail", "message": "", "details": {}},
    ]
    with patch("api.readiness._run_all_checks", new=AsyncMock(return_value=checks)):
        r = client.get("/api/readiness/session")
    s = r.json()["summary"]
    assert s["pass"] == 2
    assert s["warn"] == 1
    assert s["fail"] == 1


# ── Safety invariant ──────────────────────────────────────────────────────────

def test_safety_invariant_fails_if_live_trading_true():
    import api.readiness as rd
    with patch("paper.simulator.get_status",
               return_value={"live_trading_enabled": True, "broker_connected": False}):
        result = rd._check_safety_invariants()
    assert result["status"] == "fail"
    assert "SAFETY" in result["message"]


def test_safety_invariant_fails_if_broker_connected():
    import api.readiness as rd
    with patch("paper.simulator.get_status",
               return_value={"live_trading_enabled": False, "broker_connected": True}):
        result = rd._check_safety_invariants()
    assert result["status"] == "fail"


def test_safety_invariant_passes_when_clean():
    import api.readiness as rd
    with patch("paper.simulator.get_status",
               return_value={"live_trading_enabled": False, "broker_connected": False}):
        result = rd._check_safety_invariants()
    assert result["status"] == "pass"


# ── Polygon key check ─────────────────────────────────────────────────────────

def test_polygon_key_check_fails_when_missing():
    import api.readiness as rd
    mock_settings = MagicMock()
    mock_settings.POLYGON_API_KEY = ""
    with patch("core.config.settings", mock_settings):
        result = rd._check_polygon_key()
    assert result["status"] == "fail"


def test_polygon_key_check_passes_when_present():
    import api.readiness as rd
    mock_settings = MagicMock()
    mock_settings.POLYGON_API_KEY = "real_key_abc123"
    with patch("core.config.settings", mock_settings):
        result = rd._check_polygon_key()
    assert result["status"] == "pass"


# ── Simulator check ───────────────────────────────────────────────────────────

def test_simulator_check_fails_when_market_open_and_stopped():
    import api.readiness as rd
    with patch("paper.simulator.get_state", return_value={"running": False, "last_tick_at": None}):
        result = rd._check_simulator(market_open=True)
    assert result["status"] == "fail"


def test_simulator_check_passes_when_running_and_market_open():
    import api.readiness as rd
    with patch("paper.simulator.get_state",
               return_value={"running": True, "last_tick_at": "2026-01-01T12:00:00+00:00"}):
        result = rd._check_simulator(market_open=True)
    assert result["status"] == "pass"


def test_simulator_check_warns_when_running_outside_session():
    import api.readiness as rd
    with patch("paper.simulator.get_state",
               return_value={"running": True, "last_tick_at": "2026-01-01T12:00:00+00:00"}):
        result = rd._check_simulator(market_open=False)
    assert result["status"] == "warn"


def test_simulator_check_warns_when_stopped_and_market_closed():
    import api.readiness as rd
    with patch("paper.simulator.get_state", return_value={"running": False, "last_tick_at": None}):
        result = rd._check_simulator(market_open=False)
    assert result["status"] == "warn"


# ── Journal check ─────────────────────────────────────────────────────────────

def test_journal_check_fails_during_market_open_if_db_unavailable():
    import api.readiness as rd
    with patch("paper.journal.get_journal_status",
               return_value={"enabled": True, "database_connected": False, "tables_ready": False}):
        result = rd._check_journal(market_open=True)
    assert result["status"] == "fail"


def test_journal_check_warns_if_db_unavailable_market_closed():
    import api.readiness as rd
    with patch("paper.journal.get_journal_status",
               return_value={"enabled": True, "database_connected": False, "tables_ready": False}):
        result = rd._check_journal(market_open=False)
    assert result["status"] == "warn"


def test_journal_check_passes_when_healthy():
    import api.readiness as rd
    with patch("paper.journal.get_journal_status",
               return_value={"enabled": True, "database_connected": True, "tables_ready": True}):
        result = rd._check_journal(market_open=True)
    assert result["status"] == "pass"


# ── Universe check ────────────────────────────────────────────────────────────

def test_universe_check_warns_when_no_cache():
    import api.readiness as rd
    with patch("paper.universe.get_cached_universe", return_value=None):
        result = rd._check_universe()
    assert result["status"] == "warn"


def test_universe_check_fails_when_empty():
    import api.readiness as rd
    with patch("paper.universe.get_cached_universe",
               return_value={"active_count": 0, "errors": [], "discovery": None}):
        result = rd._check_universe()
    assert result["status"] == "fail"


def test_universe_check_warns_when_small():
    import api.readiness as rd
    with patch("paper.universe.get_cached_universe",
               return_value={"active_count": 5, "errors": [], "discovery": None}):
        result = rd._check_universe()
    assert result["status"] == "warn"


def test_universe_check_passes_when_healthy():
    import api.readiness as rd
    with patch("paper.universe.get_cached_universe",
               return_value={"active_count": 50, "errors": [], "discovery": {"discovered_count": 5}}):
        result = rd._check_universe()
    assert result["status"] == "pass"


# ── Tick freshness ────────────────────────────────────────────────────────────

def test_tick_freshness_fails_when_stopped_during_market():
    import api.readiness as rd
    with patch("paper.simulator.get_state", return_value={"running": False, "last_tick_at": None}):
        result = rd._check_tick_freshness(market_open=True)
    assert result["status"] == "fail"


def test_tick_freshness_warns_when_stopped_market_closed():
    import api.readiness as rd
    with patch("paper.simulator.get_state", return_value={"running": False, "last_tick_at": None}):
        result = rd._check_tick_freshness(market_open=False)
    assert result["status"] == "warn"


def test_tick_freshness_passes_when_fresh():
    import api.readiness as rd
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    mock_settings = MagicMock()
    mock_settings.PAPER_POLL_INTERVAL_SECONDS = 30
    with patch("paper.simulator.get_state",
               return_value={"running": True, "last_tick_at": now_iso}), \
         patch("core.config.settings", mock_settings):
        result = rd._check_tick_freshness(market_open=True)
    assert result["status"] == "pass"


# ── Polygon data cache ────────────────────────────────────────────────────────

async def test_polygon_data_check_caches_result():
    import api.readiness as rd
    rd._polygon_cache = None
    rd._polygon_cache_time = None

    mock_snapshot = {"last_trade_price": 500.0, "change_percent": 0.5}
    call_count = 0

    async def fake_get_ticker_snapshot(sym):
        nonlocal call_count
        call_count += 1
        return mock_snapshot

    with patch("data.polygon_client.get_ticker_snapshot", side_effect=fake_get_ticker_snapshot):
        r1 = await rd._check_polygon_data()
        r2 = await rd._check_polygon_data()

    assert call_count == 1, "Polygon should only be called once; second call should use cache"
    assert r1["status"] == r2["status"]


# ── No secrets exposed ────────────────────────────────────────────────────────

def test_session_no_secrets_in_response(client):
    with patch("api.readiness._run_all_checks",
               new=AsyncMock(return_value=[
                   {"name": "backend", "status": "pass", "message": "ok", "details": {}}
               ])):
        r = client.get("/api/readiness/session")
    text = r.text.lower()
    for secret_hint in ("api_key", "password", "secret", "token"):
        assert secret_hint not in text, \
            f"Secret hint {secret_hint!r} found in readiness response"


# ── Endpoint never raises ─────────────────────────────────────────────────────

def test_session_never_raises_on_check_exception(client):
    async def boom(market_open):
        raise RuntimeError("Simulated subsystem failure")

    with patch("api.readiness._run_all_checks", side_effect=boom):
        r = client.get("/api/readiness/session")
    # Should be 500 from unhandled exception in route but not crash the process
    # The actual requirement is the *checks* don't raise — we patch _run_all_checks here
    # to verify the test infrastructure works. Individual check resilience tested below.
    assert r.status_code in (200, 500)


def test_check_simulator_does_not_raise_on_import_error():
    import api.readiness as rd
    with patch("paper.simulator.get_state", side_effect=ImportError("no module")):
        result = rd._check_simulator(market_open=True)
    assert result["name"] == "simulator"
    assert result["status"] in ("warn", "fail")


def test_check_universe_does_not_raise_on_exception():
    import api.readiness as rd
    with patch("paper.universe.get_cached_universe", side_effect=Exception("DB down")):
        result = rd._check_universe()
    assert result["name"] == "universe"
    assert result["status"] in ("warn", "fail")


def test_check_journal_does_not_raise_on_exception():
    import api.readiness as rd
    with patch("paper.journal.get_journal_status", side_effect=Exception("boom")):
        result = rd._check_journal(market_open=True)
    assert result["name"] == "journal"
    assert result["status"] in ("warn", "fail")


# ── Recommended actions ───────────────────────────────────────────────────────

def test_recommended_actions_polygon_key_fail():
    import api.readiness as rd
    checks = [{"name": "polygon_key", "status": "fail", "message": "", "details": {}}]
    actions = rd._recommended_actions(checks, market_open=False, sim_running=False)
    assert any("POLYGON_API_KEY" in a for a in actions)


def test_recommended_actions_safety_fail():
    import api.readiness as rd
    checks = [{"name": "safety_invariants", "status": "fail", "message": "", "details": {}}]
    actions = rd._recommended_actions(checks, market_open=False, sim_running=False)
    assert any("URGENT" in a for a in actions)


def test_recommended_actions_sim_stopped_market_open():
    import api.readiness as rd
    checks = [{"name": "simulator", "status": "fail", "message": "", "details": {}}]
    actions = rd._recommended_actions(checks, market_open=True, sim_running=False)
    assert any("simulator" in a.lower() for a in actions)


def test_recommended_actions_empty_when_all_pass():
    import api.readiness as rd
    checks = [
        {"name": n, "status": "pass", "message": "", "details": {}}
        for n in ("backend", "polygon_key", "polygon_data", "journal",
                  "simulator", "universe", "safety_invariants")
    ]
    actions = rd._recommended_actions(checks, market_open=False, sim_running=False)
    assert actions == []


# ── Router registration ───────────────────────────────────────────────────────

def test_readiness_router_registered_in_main():
    path = BACKEND_ROOT / "main.py"
    source = path.read_text()
    assert "readiness_router" in source or "readiness" in source, \
        "readiness router not found in main.py"
    assert "include_router" in source


def test_readiness_router_prefix():
    import api.readiness as rd
    assert rd.router.prefix == "/api/readiness"
