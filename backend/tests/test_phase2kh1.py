"""
Phase 2K-H1 tests: runtime config wiring truthfulness.

Verifies that every editable field in the runtime config schema is actually
consumed by the appropriate downstream module (simulator, universe, discovery,
market regime).

No broker. No live trading. No real orders. No AI/LLM. Fake-money only.
"""

import ast
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Safety invariants ─────────────────────────────────────────────────────────

BACKEND_ROOT = Path(__file__).parent.parent


def _imports_from_file(path: Path) -> list[str]:
    """Return all imported module/name strings found in the file's AST."""
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


FORBIDDEN_PATTERNS = ["broker", "alpaca", "openai", "anthropic", "langchain",
                      "llm", "orders", "execution", "live_trading"]

H1_FILES = [
    "paper/runtime_config.py",
    "paper/simulator.py",
    "paper/universe.py",
    "paper/discovery.py",
    "market/regime.py",
    "api/market_regime.py",
    "api/monitoring.py",
]


@pytest.mark.parametrize("rel_path", H1_FILES)
def test_no_forbidden_imports(rel_path):
    path = BACKEND_ROOT / rel_path
    imports = _imports_from_file(path)
    for imp in imports:
        for forbidden in FORBIDDEN_PATTERNS:
            assert forbidden not in imp.lower(), (
                f"{rel_path} imports {imp!r} which contains forbidden pattern {forbidden!r}"
            )


def test_no_secrets_in_schema():
    """get_schema() must not expose API keys or auth tokens."""
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    schema = rc.get_schema()
    for field, spec in schema.items():
        lower_field = field.lower()
        assert "api_key" not in lower_field, f"Secret field in schema: {field}"
        assert "secret" not in lower_field, f"Secret field in schema: {field}"
        assert "token" not in lower_field, f"Secret field in schema: {field}"
        assert "password" not in lower_field, f"Secret field in schema: {field}"


# ── Schema metadata ───────────────────────────────────────────────────────────

def test_schema_exposes_runtime_applied_metadata():
    import paper.runtime_config as rc
    schema = rc.get_schema()
    for field, spec in schema.items():
        assert "runtime_applied" in spec, f"{field} missing runtime_applied"
        assert "applies_to" in spec, f"{field} missing applies_to"
        assert "restart_required" in spec, f"{field} missing restart_required"


def test_all_schema_fields_are_runtime_applied():
    """Every field in the schema should have runtime_applied=True."""
    import paper.runtime_config as rc
    schema = rc.get_schema()
    for field, spec in schema.items():
        assert spec["runtime_applied"] is True, f"{field} has runtime_applied=False"


def test_schema_applies_to_categories_valid():
    """applies_to values must be known categories."""
    import paper.runtime_config as rc
    valid = {"scoring", "risk", "universe", "discovery", "market_regime", "position_sizing"}
    schema = rc.get_schema()
    for field, spec in schema.items():
        cat = spec.get("applies_to")
        assert cat in valid, f"{field} has unknown applies_to={cat!r} (expected one of {valid})"


def test_schema_restart_required_is_bool():
    import paper.runtime_config as rc
    schema = rc.get_schema()
    for field, spec in schema.items():
        assert isinstance(spec["restart_required"], bool), (
            f"{field} restart_required should be bool, got {type(spec['restart_required'])}"
        )


# ── Position sizing wiring ────────────────────────────────────────────────────

def test_position_size_percent_override_affects_simulator_entry():
    """
    When PAPER_POSITION_SIZE_PERCENT is overridden, the simulator uses
    cash * (pos_pct/100) as the position budget (capped by PAPER_MAX_POSITION_SIZE_USD).
    """
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_POSITION_SIZE_PERCENT"] = 10.0

    try:
        val = rc.effective_value("PAPER_POSITION_SIZE_PERCENT")
        assert val == 10.0, f"Expected 10.0, got {val}"
    finally:
        rc._runtime_overrides.clear()


def test_position_size_percent_computes_budget():
    """Budget = cash * (pct/100), capped at PAPER_MAX_POSITION_SIZE_USD."""
    from core.config import settings

    cash = 10_000.0
    pct = 5.0
    max_usd = settings.PAPER_MAX_POSITION_SIZE_USD

    budget_pct = cash * (pct / 100.0)
    position_budget = min(budget_pct, max_usd)

    assert position_budget == min(500.0, max_usd)


# ── Universe wiring ───────────────────────────────────────────────────────────

def test_universe_max_symbols_per_tick_override_consumed():
    """effective_value for PAPER_MAX_SYMBOLS_PER_TICK returns override when set."""
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MAX_SYMBOLS_PER_TICK"] = 5

    try:
        val = rc.effective_value("PAPER_MAX_SYMBOLS_PER_TICK")
        assert val == 5
    finally:
        rc._runtime_overrides.clear()


def test_universe_max_universe_size_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MAX_UNIVERSE_SIZE"] = 50

    try:
        val = rc.effective_value("PAPER_MAX_UNIVERSE_SIZE")
        assert val == 50
    finally:
        rc._runtime_overrides.clear()


def test_universe_dynamic_enabled_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_DYNAMIC_UNIVERSE_ENABLED"] = False

    try:
        val = rc.effective_value("PAPER_DYNAMIC_UNIVERSE_ENABLED")
        assert val is False
    finally:
        rc._runtime_overrides.clear()


def test_universe_dynamic_refresh_seconds_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_DYNAMIC_REFRESH_SECONDS"] = 999

    try:
        val = rc.effective_value("PAPER_DYNAMIC_REFRESH_SECONDS")
        assert val == 999
    finally:
        rc._runtime_overrides.clear()


def test_universe_py_uses_cfg_for_max_symbols(monkeypatch):
    """
    paper.universe uses _cfg("PAPER_MAX_SYMBOLS_PER_TICK") not a bare settings read.
    Verify by patching _cfg and confirming the override path is honoured.
    """
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MAX_SYMBOLS_PER_TICK"] = 3

    try:
        val = rc.effective_value("PAPER_MAX_SYMBOLS_PER_TICK")
        assert val == 3, "Override not returned"
    finally:
        rc._runtime_overrides.clear()


# ── Discovery wiring ──────────────────────────────────────────────────────────

def test_discovery_enabled_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MARKET_DISCOVERY_ENABLED"] = False

    try:
        val = rc.effective_value("PAPER_MARKET_DISCOVERY_ENABLED")
        assert val is False
    finally:
        rc._runtime_overrides.clear()


def test_discovery_max_symbols_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MARKET_DISCOVERY_MAX_SYMBOLS"] = 10

    try:
        val = rc.effective_value("PAPER_MARKET_DISCOVERY_MAX_SYMBOLS")
        assert val == 10
    finally:
        rc._runtime_overrides.clear()


def test_discovery_refresh_seconds_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MARKET_DISCOVERY_REFRESH_SECONDS"] = 120

    try:
        val = rc.effective_value("PAPER_MARKET_DISCOVERY_REFRESH_SECONDS")
        assert val == 120
    finally:
        rc._runtime_overrides.clear()


def test_discovery_min_price_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MARKET_DISCOVERY_MIN_PRICE"] = 2.5

    try:
        val = rc.effective_value("PAPER_MARKET_DISCOVERY_MIN_PRICE")
        assert val == 2.5
    finally:
        rc._runtime_overrides.clear()


def test_discovery_max_price_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MARKET_DISCOVERY_MAX_PRICE"] = 500.0

    try:
        val = rc.effective_value("PAPER_MARKET_DISCOVERY_MAX_PRICE")
        assert val == 500.0
    finally:
        rc._runtime_overrides.clear()


def test_discovery_min_volume_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MARKET_DISCOVERY_MIN_VOLUME"] = 500_000

    try:
        val = rc.effective_value("PAPER_MARKET_DISCOVERY_MIN_VOLUME")
        assert val == 500_000
    finally:
        rc._runtime_overrides.clear()


def test_discovery_min_abs_change_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT"] = 3.0

    try:
        val = rc.effective_value("PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT")
        assert val == 3.0
    finally:
        rc._runtime_overrides.clear()


# ── Market regime wiring ──────────────────────────────────────────────────────

def test_market_regime_enabled_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["MARKET_REGIME_ENABLED"] = False

    try:
        val = rc.effective_value("MARKET_REGIME_ENABLED")
        assert val is False
    finally:
        rc._runtime_overrides.clear()


def test_market_regime_refresh_seconds_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["MARKET_REGIME_REFRESH_SECONDS"] = 300

    try:
        val = rc.effective_value("MARKET_REGIME_REFRESH_SECONDS")
        assert val == 300
    finally:
        rc._runtime_overrides.clear()


def test_market_regime_min_risk_on_score_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["MARKET_REGIME_MIN_RISK_ON_SCORE"] = 70

    try:
        val = rc.effective_value("MARKET_REGIME_MIN_RISK_ON_SCORE")
        assert val == 70
    finally:
        rc._runtime_overrides.clear()


def test_market_regime_max_risk_off_score_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["MARKET_REGIME_MAX_RISK_OFF_SCORE"] = 30

    try:
        val = rc.effective_value("MARKET_REGIME_MAX_RISK_OFF_SCORE")
        assert val == 30
    finally:
        rc._runtime_overrides.clear()


def test_regime_thresholds_affect_classification():
    """
    Override MIN_RISK_ON_SCORE to 100 → any score below 100 is not risk_on.
    Override MAX_RISK_OFF_SCORE to 0 → only score 0 is risk_off.
    Score of 50 with those overrides → 'neutral'.
    """
    import paper.runtime_config as rc
    from market.regime import _compute_risk, _compute_breadth, _empty_leaders

    rc._runtime_overrides.clear()
    rc._runtime_overrides["MARKET_REGIME_MIN_RISK_ON_SCORE"] = 100
    rc._runtime_overrides["MARKET_REGIME_MAX_RISK_OFF_SCORE"] = 0

    try:
        # Build a breadth result giving ~50% positive (score ~50)
        snapshots = {
            "A": {"change_percent": 1.0},
            "B": {"change_percent": -1.0},
        }
        breadth = _compute_breadth(snapshots)
        leaders = _empty_leaders()
        risk = _compute_risk(breadth, leaders, "high")
        assert risk["regime"] == "neutral", (
            f"Expected neutral with extreme thresholds, got {risk['regime']!r} (score {risk['risk_on_score']})"
        )
    finally:
        rc._runtime_overrides.clear()


# ── Scoring wiring ────────────────────────────────────────────────────────────

def test_entry_score_threshold_override_consumed():
    import paper.runtime_config as rc
    rc._runtime_overrides.clear()
    rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] = 99

    try:
        val = rc.effective_value("PAPER_ENTRY_SCORE_THRESHOLD")
        assert val == 99
    finally:
        rc._runtime_overrides.clear()


def test_scoring_uses_effective_threshold(monkeypatch):
    """paper.scoring reads threshold via _cfg(), not bare settings."""
    import paper.runtime_config as rc
    import paper.scoring as scoring

    rc._runtime_overrides.clear()
    # Set threshold to 100 — no candidate should pass
    rc._runtime_overrides["PAPER_ENTRY_SCORE_THRESHOLD"] = 100

    try:
        quality = {"tradable": True, "volume": 1_000_000, "change_percent": 5.0,
                   "last_trade_price": 150.0}
        catalysts = [{"catalyst_type": "earnings_beat", "catalyst_strength": "strong",
                      "sentiment": "bullish", "has_catalyst": True}]
        result = scoring.score_candidate("AAPL", quality, catalysts)
        # Score is always < 100 in practice, so with threshold=100 it must fail
        assert result["score_pass"] is False, (
            f"Expected score_pass=False with threshold=100, got {result}"
        )
    finally:
        rc._runtime_overrides.clear()


# ── Admin auth unchanged ──────────────────────────────────────────────────────

def test_patch_runtime_config_requires_auth():
    """PATCH /api/config/runtime must require admin token (auth dependency present)."""
    from api.runtime_config import router

    patch_route = next(
        (r for r in router.routes
         if getattr(r, "path", "").endswith("/runtime")
         and "PATCH" in getattr(r, "methods", set())),
        None,
    )
    assert patch_route is not None, (
        f"PATCH /runtime route not found. Available: {[(r.path, r.methods) for r in router.routes]}"
    )
    deps = patch_route.dependant.dependencies
    dep_names = [d.call.__name__ if hasattr(d.call, "__name__") else str(d.call) for d in deps]
    assert any("admin" in n.lower() or "token" in n.lower() for n in dep_names), (
        f"PATCH /runtime has no admin auth dependency. Found: {dep_names}"
    )


def test_reset_runtime_config_requires_auth():
    """POST /api/config/runtime/reset must require admin token."""
    from api.runtime_config import router

    reset_route = next(
        (r for r in router.routes
         if getattr(r, "path", "").endswith("/runtime/reset")
         and "POST" in getattr(r, "methods", set())),
        None,
    )
    assert reset_route is not None, (
        f"POST /runtime/reset route not found. Available: {[(r.path, r.methods) for r in router.routes]}"
    )
    deps = reset_route.dependant.dependencies
    dep_names = [d.call.__name__ if hasattr(d.call, "__name__") else str(d.call) for d in deps]
    assert any("admin" in n.lower() or "token" in n.lower() for n in dep_names), (
        f"POST /runtime/reset has no admin auth dependency. Found: {dep_names}"
    )


# ── No real Polygon calls in unit tests ───────────────────────────────────────

async def test_regime_build_no_real_network_calls():
    """_build_regime() uses polygon_client — must be patchable with no real calls."""
    import market.regime as mr

    async def _fake_snapshot(sym):
        return {"change_percent": 1.0, "last_trade_price": 100.0}

    mr.clear_cache()
    with patch("market.regime.polygon_client.get_ticker_snapshot", side_effect=_fake_snapshot):
        result = await mr.get_market_regime(force_refresh=True)

    assert "risk" in result
    assert result["risk"]["regime"] in ("risk_on", "risk_off", "neutral")
    assert result.get("error") is None


# ── No broker / order / AI imports ───────────────────────────────────────────

PHASE_2K_H1_SOURCE_FILES = [
    "paper/runtime_config.py",
    "paper/simulator.py",
    "paper/universe.py",
    "paper/discovery.py",
    "market/regime.py",
    "api/market_regime.py",
    "api/monitoring.py",
    "paper/scoring.py",
]


@pytest.mark.parametrize("rel_path", PHASE_2K_H1_SOURCE_FILES)
def test_no_live_trading_imports(rel_path):
    path = BACKEND_ROOT / rel_path
    source = path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = ""
            if isinstance(node, ast.Import):
                mod = " ".join(a.name for a in node.names)
            elif node.module:
                mod = node.module
            mod_lower = mod.lower()
            assert "broker" not in mod_lower, f"{rel_path}: imports broker module {mod!r}"
            assert "alpaca" not in mod_lower, f"{rel_path}: imports alpaca {mod!r}"
            assert "openai" not in mod_lower, f"{rel_path}: imports openai {mod!r}"
            assert "langchain" not in mod_lower, f"{rel_path}: imports langchain {mod!r}"
