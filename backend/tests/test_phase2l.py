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


# ── Endpoint never raises (route-level crash-proof) ───────────────────────────

def test_session_never_raises_on_check_exception(client):
    async def boom(market_open):
        raise RuntimeError("boom apiKey=SECRET123")

    with patch("api.readiness._run_all_checks", side_effect=boom):
        r = client.get("/api/readiness/session")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data["overall_status"] == "not_ready"
    checks_by_name = {c["name"]: c for c in data["checks"]}
    assert "readiness_internal" in checks_by_name, \
        "Fallback check 'readiness_internal' missing from response"
    assert "SECRET123" not in r.text, "Secret leaked in runner-failure response"


def test_compact_never_raises_on_runner_failure(client):
    async def boom(market_open):
        raise RuntimeError("compact runner exploded token=LEAKSECRET")

    with patch("api.readiness._run_all_checks", side_effect=boom):
        r = client.get("/api/readiness/session/compact")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data["overall_status"] == "not_ready"
    assert data["fail_count"] >= 1
    assert "LEAKSECRET" not in r.text


# ── Route assembly crash (outer try/except) ───────────────────────────────────

def test_session_route_assembly_crash(client):
    """_overall_status raising after _run_all_checks succeeds still returns 200."""
    good_checks = [{"name": "backend", "status": "pass", "message": "ok", "details": {}}]

    with patch("api.readiness._run_all_checks", new=AsyncMock(return_value=good_checks)), \
         patch("api.readiness._overall_status",
               side_effect=RuntimeError("assembly crash password=SECRETVAL")):
        r = client.get("/api/readiness/session")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data["overall_status"] == "not_ready"
    checks_by_name = {c["name"]: c for c in data["checks"]}
    assert "readiness_internal" in checks_by_name
    assert "SECRETVAL" not in r.text


def test_compact_route_assembly_crash(client):
    """_recommended_actions raising after _run_all_checks succeeds still returns 200."""
    good_checks = [{"name": "backend", "status": "pass", "message": "ok", "details": {}}]

    with patch("api.readiness._run_all_checks", new=AsyncMock(return_value=good_checks)), \
         patch("api.readiness._recommended_actions",
               side_effect=RuntimeError("actions crash client_secret=SECRETVAL2")):
        r = client.get("/api/readiness/session/compact")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data["overall_status"] == "not_ready"
    assert data["fail_count"] >= 1
    assert "SECRETVAL2" not in r.text


# ── Malformed check sanitization ──────────────────────────────────────────────

def test_sanitize_checks_handles_non_dict():
    import api.readiness as rd
    result = rd._sanitize_checks(["not_a_dict", 42, None])
    assert all(isinstance(c, dict) for c in result)
    assert all(c["status"] == "fail" for c in result)
    assert all(c["name"] == "malformed_check" for c in result)


def test_sanitize_checks_fixes_missing_status():
    import api.readiness as rd
    raw = [{"name": "x", "message": "m", "details": {}}]
    result = rd._sanitize_checks(raw)
    assert result[0]["status"] == "fail"
    assert result[0]["name"] == "x"


def test_sanitize_checks_fixes_missing_name():
    import api.readiness as rd
    raw = [{"status": "pass", "message": "m", "details": {}}]
    result = rd._sanitize_checks(raw)
    assert result[0]["name"] == "unknown_check"


def test_sanitize_checks_passes_valid_checks():
    import api.readiness as rd
    raw = [{"name": "backend", "status": "pass", "message": "ok", "details": {"x": 1}}]
    result = rd._sanitize_checks(raw)
    assert result[0] == {"name": "backend", "status": "pass", "message": "ok", "details": {"x": 1}}


# ── redact_sensitive_error unit tests ────────────────────────────────────────

def test_redact_removes_api_key_pattern():
    import api.readiness as rd
    result = rd.redact_sensitive_error("https://example.com?apiKey=MY_SECRET_KEY_XYZ")
    assert "MY_SECRET_KEY_XYZ" not in result
    assert "[REDACTED]" in result


def test_redact_removes_token_pattern():
    import api.readiness as rd
    result = rd.redact_sensitive_error("token=ABCDEF12345")
    assert "ABCDEF12345" not in result
    assert "[REDACTED]" in result


def test_redact_removes_bearer_pattern():
    import api.readiness as rd
    result = rd.redact_sensitive_error("Authorization: Bearer MYSECRETTOKEN99")
    assert "MYSECRETTOKEN99" not in result
    assert "[REDACTED]" in result


def test_redact_removes_password_pattern():
    import api.readiness as rd
    result = rd.redact_sensitive_error("connection failed: password=hunter2secret")
    assert "hunter2secret" not in result
    assert "[REDACTED]" in result


def test_redact_truncates_to_200():
    import api.readiness as rd
    long_err = "x" * 500
    result = rd.redact_sensitive_error(long_err)
    assert len(result) <= 200


def test_redact_polygon_key_from_settings():
    import api.readiness as rd
    mock_settings = MagicMock()
    mock_settings.POLYGON_API_KEY = "ACTUAL_POLYGON_KEY_ABC"
    with patch("core.config.settings", mock_settings):
        result = rd.redact_sensitive_error("Error calling https://api.polygon.io?apiKey=ACTUAL_POLYGON_KEY_ABC")
    assert "ACTUAL_POLYGON_KEY_ABC" not in result


def test_redact_safe_with_no_secrets():
    import api.readiness as rd
    result = rd.redact_sensitive_error("Connection timeout after 30s")
    assert result == "Connection timeout after 30s"


# ── Colon / JSON-style redaction ──────────────────────────────────────────────

def test_redact_colon_bare_password():
    import api.readiness as rd
    result = rd.redact_sensitive_error("password: hunter2")
    assert "hunter2" not in result
    assert "[REDACTED]" in result


def test_redact_colon_json_password():
    import api.readiness as rd
    result = rd.redact_sensitive_error('"password": "hunter2"')
    assert "hunter2" not in result
    assert "[REDACTED]" in result


def test_redact_colon_single_quote_password():
    import api.readiness as rd
    result = rd.redact_sensitive_error("'password': 'hunter2'")
    assert "hunter2" not in result
    assert "[REDACTED]" in result


def test_redact_colon_client_secret():
    import api.readiness as rd
    result = rd.redact_sensitive_error("client_secret: abc123")
    assert "abc123" not in result
    assert "[REDACTED]" in result


def test_redact_colon_json_client_secret():
    import api.readiness as rd
    result = rd.redact_sensitive_error('"client_secret": "abc123"')
    assert "abc123" not in result
    assert "[REDACTED]" in result


def test_redact_colon_refresh_token():
    import api.readiness as rd
    result = rd.redact_sensitive_error('"refresh_token": "rt123"')
    assert "rt123" not in result
    assert "[REDACTED]" in result


def test_redact_colon_api_key():
    import api.readiness as rd
    result = rd.redact_sensitive_error("apiKey: pk_test_XYZ")
    assert "pk_test_XYZ" not in result
    assert "[REDACTED]" in result


def test_redact_colon_json_api_key():
    import api.readiness as rd
    result = rd.redact_sensitive_error('"api_key": "pk_test_XYZ"')
    assert "pk_test_XYZ" not in result
    assert "[REDACTED]" in result


# ── Polygon error redaction in _check_polygon_data ───────────────────────────

async def test_polygon_error_redacts_secrets():
    import api.readiness as rd
    import json as _json

    rd._polygon_cache = None
    rd._polygon_cache_time = None

    secret_msg = (
        "https://api.polygon.io/v2/snapshot?apiKey=SECRET123 "
        "token=ABC Authorization: Bearer XYZ password=hunter2"
    )

    async def raise_with_secrets(sym):
        raise RuntimeError(secret_msg)

    with patch("data.polygon_client.get_ticker_snapshot", side_effect=raise_with_secrets):
        result = await rd._check_polygon_data()

    result_text = _json.dumps(result)
    for secret in ("SECRET123", "ABC", "XYZ", "hunter2"):
        assert secret not in result_text, \
            f"Secret {secret!r} leaked in polygon check result: {result_text[:300]}"
    assert "[REDACTED]" in result_text, "Expected [REDACTED] marker in polygon check result"


async def test_polygon_error_redacts_mixed_forms():
    """Polygon check redacts secrets in both equal-sign and colon/JSON forms."""
    import api.readiness as rd
    import json as _json

    rd._polygon_cache = None
    rd._polygon_cache_time = None

    mixed_msg = (
        'apiKey=SECRET1 password: hunter2 '
        '"client_secret": "SECRET2" Authorization: Bearer SECRET3'
    )

    async def raise_mixed(sym):
        raise RuntimeError(mixed_msg)

    with patch("data.polygon_client.get_ticker_snapshot", side_effect=raise_mixed):
        result = await rd._check_polygon_data()

    result_text = _json.dumps(result)
    for secret in ("SECRET1", "hunter2", "SECRET2", "SECRET3"):
        assert secret not in result_text, \
            f"Secret {secret!r} leaked in mixed-form polygon check: {result_text[:300]}"
    assert "[REDACTED]" in result_text


# ── No real Polygon calls guard ───────────────────────────────────────────────

def test_readiness_no_real_polygon_calls_needed(client):
    """Endpoint returns 200 even when Polygon is completely unreachable."""
    import api.readiness as rd
    rd._polygon_cache = None
    rd._polygon_cache_time = None

    async def unreachable_polygon(sym):
        raise ConnectionError("No network — Polygon unreachable")

    with patch("data.polygon_client.get_ticker_snapshot", side_effect=unreachable_polygon), \
         patch("paper.simulator.get_state",
               return_value={"running": False, "last_tick_at": None}), \
         patch("paper.simulator.get_status",
               return_value={"live_trading_enabled": False, "broker_connected": False}), \
         patch("paper.journal.get_journal_status",
               return_value={"enabled": True, "database_connected": True, "tables_ready": True}), \
         patch("paper.runtime_config.get_runtime_status",
               return_value={"overrides_active": False, "override_count": 0, "warnings": []}), \
         patch("paper.universe.get_cached_universe",
               return_value={"active_count": 50, "errors": [], "discovery": None}), \
         patch("paper.runtime_config.effective_value",
               side_effect=lambda k: {"PAPER_MARKET_DISCOVERY_ENABLED": False,
                                      "MARKET_REGIME_ENABLED": False}.get(k)):
        r = client.get("/api/readiness/session")

    assert r.status_code == 200
    data = r.json()
    assert data["overall_status"] in ("ready", "warning", "not_ready")
    poly_check = next((c for c in data["checks"] if c["name"] == "polygon_data"), None)
    assert poly_check is not None, "polygon_data check missing from response"
    assert poly_check["status"] in ("warn", "fail"), \
        "Unreachable Polygon should produce warn or fail, not pass"


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
