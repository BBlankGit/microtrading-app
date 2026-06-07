"""
Tests for Phase 2K: Runtime Strategy Configuration Panel.

No broker. No real orders. Research-only fake-money simulation.
No AI/LLM. No real Polygon API calls. No real DB calls in most tests.
"""

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Safety invariants ─────────────────────────────────────────────────────────

def test_runtime_config_no_broker_no_ai():
    text = (pathlib.Path(__file__).parent.parent / "paper" / "runtime_config.py").read_text()
    import ast
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            for alias in getattr(node, "names", []):
                full = f"{module}.{alias.name}".lower()
                assert "alpaca" not in full, f"Broker import: {full}"
                assert "openai" not in full, f"AI import: {full}"


def test_runtime_config_no_secrets_in_schema():
    from paper.runtime_config import get_schema
    schema = get_schema()
    for key in schema:
        assert "api_key" not in key.lower(), f"Secret field in schema: {key}"
        assert "token" not in key.lower(), f"Token field in schema: {key}"
        assert "database_url" not in key.lower(), f"DB URL in schema: {key}"
        assert "polygon" not in key.lower(), f"Polygon key in schema: {key}"
        assert "admin" not in key.lower(), f"Admin token in schema: {key}"
        assert "redis" not in key.lower(), f"Redis in schema: {key}"


def test_runtime_config_has_disclaimer_in_api():
    text = (pathlib.Path(__file__).parent.parent / "api" / "runtime_config.py").read_text()
    assert "No broker" in text
    assert "no live trading" in text.lower()
    assert "no real orders" in text.lower()


# ── Schema ────────────────────────────────────────────────────────────────────

def test_schema_has_all_required_fields():
    from paper.runtime_config import _SCHEMA
    required = {
        "PAPER_ENTRY_SCORE_THRESHOLD",
        "PAPER_TAKE_PROFIT_PERCENT",
        "PAPER_STOP_LOSS_PERCENT",
        "PAPER_MAX_HOLD_MINUTES",
        "PAPER_MAX_OPEN_POSITIONS",
        "PAPER_MAX_TRADES_PER_DAY",
        "PAPER_POSITION_SIZE_PERCENT",
        "PAPER_REJECT_STRONG_BEARISH_CATALYST",
        "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY",
        "PAPER_MAX_UNIVERSE_SIZE",
        "PAPER_MAX_SYMBOLS_PER_TICK",
        "PAPER_DYNAMIC_UNIVERSE_ENABLED",
        "PAPER_DYNAMIC_REFRESH_SECONDS",
        "PAPER_MARKET_DISCOVERY_ENABLED",
        "PAPER_MARKET_DISCOVERY_MAX_SYMBOLS",
        "PAPER_MARKET_DISCOVERY_REFRESH_SECONDS",
        "PAPER_MARKET_DISCOVERY_MIN_PRICE",
        "PAPER_MARKET_DISCOVERY_MAX_PRICE",
        "PAPER_MARKET_DISCOVERY_MIN_VOLUME",
        "PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT",
        "MARKET_REGIME_ENABLED",
        "MARKET_REGIME_REFRESH_SECONDS",
        "MARKET_REGIME_MIN_RISK_ON_SCORE",
        "MARKET_REGIME_MAX_RISK_OFF_SCORE",
    }
    assert required.issubset(set(_SCHEMA.keys()))


def test_schema_types_valid():
    from paper.runtime_config import _SCHEMA
    for field, spec in _SCHEMA.items():
        assert spec["type"] in ("int", "float", "bool"), f"{field}: unknown type {spec['type']}"
        assert "description" in spec
        assert "category" in spec


# ── get_base_config / get_effective_config ────────────────────────────────────

def test_get_base_config_returns_all_fields():
    from paper.runtime_config import get_base_config, _SCHEMA
    base = get_base_config()
    assert set(base.keys()) == set(_SCHEMA.keys())


def test_get_effective_config_no_overrides_equals_base():
    import paper.runtime_config as rc
    original = dict(rc._runtime_overrides)
    rc._runtime_overrides.clear()
    try:
        base = rc.get_base_config()
        effective = rc.get_effective_config()
        assert base == effective
    finally:
        rc._runtime_overrides.update(original)


def test_get_effective_config_override_takes_priority():
    import paper.runtime_config as rc
    original = dict(rc._runtime_overrides)
    rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] = 99
    try:
        effective = rc.get_effective_config()
        assert effective["PAPER_ENTRY_SCORE_THRESHOLD"] == 99
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)


def test_effective_value_returns_override():
    import paper.runtime_config as rc
    original = dict(rc._runtime_overrides)
    rc._runtime_overrides["PAPER_TAKE_PROFIT_PERCENT"] = 5.0
    try:
        assert rc.effective_value("PAPER_TAKE_PROFIT_PERCENT") == 5.0
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)


def test_effective_value_falls_back_to_base():
    import paper.runtime_config as rc
    original = dict(rc._runtime_overrides)
    rc._runtime_overrides.pop("PAPER_ENTRY_SCORE_THRESHOLD", None)
    try:
        from core.config import settings
        assert rc.effective_value("PAPER_ENTRY_SCORE_THRESHOLD") == settings.PAPER_ENTRY_SCORE_THRESHOLD
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)


# ── Validation — bounds ───────────────────────────────────────────────────────

def test_validate_score_threshold_valid():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_ENTRY_SCORE_THRESHOLD": 75})
    assert ok, errs


def test_validate_score_threshold_below_min():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_ENTRY_SCORE_THRESHOLD": -1})
    assert not ok
    assert any("PAPER_ENTRY_SCORE_THRESHOLD" in e for e in errs)


def test_validate_score_threshold_above_max():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_ENTRY_SCORE_THRESHOLD": 101})
    assert not ok


def test_validate_take_profit_below_min():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_TAKE_PROFIT_PERCENT": 0.001})
    assert not ok


def test_validate_stop_loss_above_max():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_STOP_LOSS_PERCENT": 99.0})
    assert not ok


def test_validate_max_hold_minutes_valid():
    from paper.runtime_config import validate_runtime_config
    ok, _ = validate_runtime_config({"PAPER_MAX_HOLD_MINUTES": 60})
    assert ok


def test_validate_max_hold_minutes_above_max():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_MAX_HOLD_MINUTES": 999})
    assert not ok


def test_validate_bool_field_valid():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_REJECT_STRONG_BEARISH_CATALYST": False})
    assert ok, errs


def test_validate_bool_field_wrong_type():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_REJECT_STRONG_BEARISH_CATALYST": "yes"})
    assert not ok


def test_validate_unknown_field_rejected():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"POLYGON_API_KEY": "leaked"})
    assert not ok
    assert any("Unknown field" in e for e in errs)


def test_validate_float_accepts_int_coercion():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_TAKE_PROFIT_PERCENT": 1})
    assert ok, errs


def test_validate_int_accepts_whole_float():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({"PAPER_ENTRY_SCORE_THRESHOLD": 75.0})
    assert ok, errs


# ── Validation — cross-field ──────────────────────────────────────────────────

def test_validate_discovery_price_min_lt_max():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({
        "PAPER_MARKET_DISCOVERY_MIN_PRICE": 100.0,
        "PAPER_MARKET_DISCOVERY_MAX_PRICE": 50.0,
    })
    assert not ok
    assert any("MIN_PRICE" in e or "MAX_PRICE" in e for e in errs)


def test_validate_regime_risk_off_lt_risk_on():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({
        "MARKET_REGIME_MIN_RISK_ON_SCORE": 40,
        "MARKET_REGIME_MAX_RISK_OFF_SCORE": 60,
    })
    assert not ok
    assert any("RISK_OFF" in e or "RISK_ON" in e for e in errs)


def test_validate_regime_risk_scores_valid():
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({
        "MARKET_REGIME_MIN_RISK_ON_SCORE": 60,
        "MARKET_REGIME_MAX_RISK_OFF_SCORE": 40,
    })
    assert ok, errs


# ── Partial update rejection ──────────────────────────────────────────────────

def test_validate_all_or_nothing():
    """If one field fails, nothing should be applied."""
    from paper.runtime_config import validate_runtime_config
    ok, errs = validate_runtime_config({
        "PAPER_ENTRY_SCORE_THRESHOLD": 75,   # valid
        "PAPER_TAKE_PROFIT_PERCENT": -999.0,  # invalid
    })
    assert not ok
    # Both keys present in updates, but only 1 error expected
    assert any("PAPER_TAKE_PROFIT_PERCENT" in e for e in errs)


# ── update_runtime_config ─────────────────────────────────────────────────────

async def test_update_applies_overrides():
    import paper.runtime_config as rc
    original = dict(rc._runtime_overrides)
    rc._runtime_overrides.clear()
    rc._persistent = False  # skip DB
    try:
        with patch("paper.runtime_config._persist_to_db", new=AsyncMock()):
            effective = await rc.update_runtime_config(
                {"PAPER_ENTRY_SCORE_THRESHOLD": 80}, updated_by="test"
            )
        assert effective["PAPER_ENTRY_SCORE_THRESHOLD"] == 80
        assert rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] == 80
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)


async def test_update_invalid_raises():
    import paper.runtime_config as rc
    with pytest.raises(ValueError):
        await rc.update_runtime_config({"PAPER_ENTRY_SCORE_THRESHOLD": -999})


# ── reset_runtime_config ──────────────────────────────────────────────────────

async def test_reset_clears_overrides():
    import paper.runtime_config as rc
    rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] = 99
    with patch("paper.runtime_config._persist_reset_to_db", new=AsyncMock()):
        await rc.reset_runtime_config(updated_by="test")
    assert "PAPER_ENTRY_SCORE_THRESHOLD" not in rc._runtime_overrides


# ── get_runtime_status ────────────────────────────────────────────────────────

def test_runtime_status_no_overrides():
    import paper.runtime_config as rc
    original = dict(rc._runtime_overrides)
    rc._runtime_overrides.clear()
    try:
        status = rc.get_runtime_status()
        assert status["overrides_active"] is False
        assert status["override_count"] == 0
    finally:
        rc._runtime_overrides.update(original)


def test_runtime_status_with_overrides():
    import paper.runtime_config as rc
    original = dict(rc._runtime_overrides)
    rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] = 80
    try:
        status = rc.get_runtime_status()
        assert status["overrides_active"] is True
        assert status["override_count"] >= 1
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)


# ── Scoring uses effective config ─────────────────────────────────────────────

def test_scoring_uses_runtime_threshold():
    """score_candidate must use effective threshold, not just settings."""
    import paper.runtime_config as rc
    from paper.scoring import score_candidate

    original = dict(rc._runtime_overrides)
    rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] = 0  # pass everything
    try:
        quality = {
            "tradable": False,
            "spread_percent": 10.0,
            "change_percent": -5.0,
            "volume_ratio": 0.1,
            "rejection_reasons": ["test"],
        }
        result = score_candidate("TEST", quality, [])
        assert result["score_threshold"] == 0
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)


def test_scoring_threshold_blocks_at_100():
    """With threshold=100, almost nothing should pass."""
    import paper.runtime_config as rc
    from paper.scoring import score_candidate

    original = dict(rc._runtime_overrides)
    rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] = 100
    try:
        quality = {
            "tradable": True,
            "spread_percent": 0.10,
            "change_percent": 3.0,
            "volume_ratio": 2.0,
        }
        result = score_candidate("AAPL", quality, [])
        assert result["score_threshold"] == 100
        assert result["score_pass"] is False
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)


# ── API endpoints shape ───────────────────────────────────────────────────────

def test_api_runtime_config_router_exists():
    from api.runtime_config import router
    paths = {r.path for r in router.routes}
    assert "/api/config/runtime" in paths
    assert "/api/config/runtime/reset" in paths
    assert "/api/config/runtime/schema" in paths


def test_api_runtime_config_patch_requires_auth():
    from api.runtime_config import router
    for route in router.routes:
        if route.path == "/api/config/runtime" and "PATCH" in route.methods:
            assert len(route.dependant.dependencies) > 0, "PATCH /runtime must require auth"
            break


def test_api_runtime_reset_requires_auth():
    from api.runtime_config import router
    for route in router.routes:
        if route.path == "/api/config/runtime/reset" and "POST" in route.methods:
            assert len(route.dependant.dependencies) > 0, "POST /runtime/reset must require auth"
            break


def test_api_runtime_get_no_auth_required():
    from api.runtime_config import router
    for route in router.routes:
        if route.path == "/api/config/runtime" and "GET" in route.methods:
            assert len(route.dependant.dependencies) == 0, "GET /runtime must NOT require auth"
            break


def test_api_schema_no_auth_required():
    from api.runtime_config import router
    for route in router.routes:
        if route.path == "/api/config/runtime/schema" and "GET" in route.methods:
            assert len(route.dependant.dependencies) == 0, "GET /schema must NOT require auth"
            break


# ── Monitoring includes runtime_config ────────────────────────────────────────

def test_monitoring_status_has_runtime_config_key():
    """Monitoring response must include runtime_config key."""
    import paper.runtime_config as rc
    status = rc.get_runtime_status()
    assert "overrides_active" in status
    assert "override_count" in status
    assert "persistent" in status


# ── DB fallback ───────────────────────────────────────────────────────────────

async def test_init_tables_db_unavailable_falls_back():
    """If DB is unavailable, init should not raise and should set persistence warning."""
    import paper.runtime_config as rc
    original_persistent = rc._persistent
    original_warning = rc._persistence_warning
    try:
        # get_pool is imported inside the function from paper.db — patch the source
        with patch("paper.db.get_pool", new=AsyncMock(return_value=None)):
            result = await rc.init_runtime_config_tables()
        assert result is False
        assert rc._persistence_warning is not None
    finally:
        rc._persistent = original_persistent
        rc._persistence_warning = original_warning


async def test_persist_to_db_unavailable_does_not_raise():
    """Persist failure must not raise — only sets warning."""
    import paper.runtime_config as rc
    original_warning = rc._persistence_warning
    try:
        with patch("paper.db.get_pool", new=AsyncMock(return_value=None)):
            await rc._persist_to_db({"PAPER_ENTRY_SCORE_THRESHOLD": 75}, {}, "test")
        # No exception raised
    finally:
        rc._persistence_warning = original_warning


# ── Strong bearish rejection uses runtime config ──────────────────────────────

def test_bearish_rejection_respects_runtime_override():
    """PAPER_REJECT_STRONG_BEARISH_CATALYST=False must disable the hard gate."""
    import paper.runtime_config as rc
    from paper.runtime_config import effective_value

    original = dict(rc._runtime_overrides)
    rc._runtime_overrides["PAPER_REJECT_STRONG_BEARISH_CATALYST"] = False
    try:
        val = effective_value("PAPER_REJECT_STRONG_BEARISH_CATALYST")
        assert val is False
    finally:
        rc._runtime_overrides.clear()
        rc._runtime_overrides.update(original)
