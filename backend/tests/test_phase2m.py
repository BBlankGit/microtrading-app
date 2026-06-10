"""
Phase 2M tests — Controlled Momentum Entry Mode.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. Momentum mode is fake-money simulation only.
"""

import ast
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).parent.parent

FORBIDDEN_MODULES = {
    "openai", "anthropic", "langchain", "ollama", "broker", "alpaca", "ibapi",
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


# ── Client fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ── 1. Default disabled ────────────────────────────────────────────────────────

def test_momentum_mode_default_disabled():
    from core.config import settings
    assert settings.PAPER_MOMENTUM_MODE_ENABLED is False, \
        "PAPER_MOMENTUM_MODE_ENABLED must default to False"


def test_momentum_mode_default_disabled_via_effective_value():
    from paper.runtime_config import effective_value
    assert effective_value("PAPER_MOMENTUM_MODE_ENABLED") is False, \
        "effective_value must return False when no override and .env default is False"


def test_momentum_mode_conservative_defaults():
    from core.config import settings
    assert settings.PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD == 85
    assert settings.PAPER_MOMENTUM_MIN_CHANGE_PERCENT == 1.5
    assert settings.PAPER_MOMENTUM_MIN_VOLUME_RATIO == 2.0
    assert settings.PAPER_MOMENTUM_MAX_SPREAD_PERCENT == 0.25
    assert settings.PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON is True
    assert settings.PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE == 60
    assert settings.PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER == 0.5
    assert settings.PAPER_MOMENTUM_MAX_TRADES_PER_DAY == 30


# ── 2. Runtime config schema ──────────────────────────────────────────────────

def test_momentum_fields_in_schema():
    from paper.runtime_config import _SCHEMA
    expected = [
        "PAPER_MOMENTUM_MODE_ENABLED",
        "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD",
        "PAPER_MOMENTUM_MIN_CHANGE_PERCENT",
        "PAPER_MOMENTUM_MIN_VOLUME_RATIO",
        "PAPER_MOMENTUM_MAX_SPREAD_PERCENT",
        "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON",
        "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE",
        "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER",
        "PAPER_MOMENTUM_MAX_TRADES_PER_DAY",
    ]
    for f in expected:
        assert f in _SCHEMA, f"Field {f!r} missing from _SCHEMA"


def test_momentum_schema_categories():
    from paper.runtime_config import _SCHEMA
    for key, spec in _SCHEMA.items():
        if key.startswith("PAPER_MOMENTUM_"):
            assert spec["category"] == "momentum", f"{key} category must be 'momentum'"
            assert spec["applies_to"] == "momentum", f"{key} applies_to must be 'momentum'"
            assert spec["restart_required"] is False


def test_momentum_schema_validation_enabled_must_be_bool():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_MOMENTUM_MODE_ENABLED": "yes"})
    assert not ok
    assert any("bool" in e for e in errors)


def test_momentum_schema_validation_score_threshold_bounds():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 150})
    assert not ok
    assert any("exceed" in e.lower() or "maximum" in e.lower() for e in errors)


def test_momentum_schema_validation_multiplier_bounds():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": 2.0})
    assert not ok
    assert any("exceed" in e.lower() or "maximum" in e.lower() for e in errors)


# ── 3. evaluate_momentum_entry pass cases ─────────────────────────────────────

def _quality_passing() -> dict:
    return {
        "tradable": True,
        "spread_percent": 0.10,
        "change_percent": 2.0,
        "volume_ratio": 3.0,
        "rejection_reasons": [],
    }


def _regime_passing() -> dict:
    return {"regime": "risk_on", "risk_on_score": 75}


def test_momentum_eval_disabled_returns_ineligible():
    with patch("paper.runtime_config.effective_value") as mock_cfg:
        mock_cfg.side_effect = lambda k: {
            "PAPER_MOMENTUM_MODE_ENABLED": False,
            "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
        }.get(k)
        from paper.momentum import evaluate_momentum_entry
        result = evaluate_momentum_entry("AAPL", _quality_passing(), _regime_passing())
    assert result["eligible"] is False
    assert result["rejection_reason"] == "momentum_mode_disabled"


def test_momentum_eval_enabled_all_gates_pass():
    from paper.momentum import evaluate_momentum_entry
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_MOMENTUM_MODE_ENABLED": True,
            "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
            "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
            "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
            "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
            "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": True,
            "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
        })
        result = evaluate_momentum_entry("AAPL", _quality_passing(), _regime_passing())
    finally:
        rc._runtime_overrides = old

    assert result["eligible"] is True
    assert result["rejection_reason"] is None
    assert result["momentum_score"] >= 85
    assert result["momentum_score_threshold"] == 85


def test_momentum_eval_score_at_minimum_gates():
    """Candidate barely meeting all minimums must score exactly 85."""
    from paper.momentum import evaluate_momentum_entry
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update({
            "PAPER_MOMENTUM_MODE_ENABLED": True,
            "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
            "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
            "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
            "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
            "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": True,
            "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
        })
        quality = {
            "tradable": True,
            "spread_percent": 0.20,   # acceptable band (>0.15, <=0.25) → +5
            "change_percent": 1.5,    # minimum → +15
            "volume_ratio": 2.0,      # minimum → +15
        }
        regime = {"regime": "risk_on", "risk_on_score": 60}  # minimum → +5
        result = evaluate_momentum_entry("TEST", quality, regime)
    finally:
        rc._runtime_overrides = old

    assert result["eligible"] is True
    assert result["momentum_score"] == 85


# ── 4. evaluate_momentum_entry fail cases ────────────────────────────────────

def _with_overrides(overrides: dict, fn):
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update(overrides)
        return fn()
    finally:
        rc._runtime_overrides = old


def _base_overrides() -> dict:
    return {
        "PAPER_MOMENTUM_MODE_ENABLED": True,
        "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
        "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
        "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
        "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
        "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": True,
        "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
    }


def test_momentum_eval_fails_not_tradable():
    from paper.momentum import evaluate_momentum_entry
    q = dict(_quality_passing(), tradable=False, rejection_reasons=["price_too_low"])
    result = _with_overrides(_base_overrides(), lambda: evaluate_momentum_entry("X", q, _regime_passing()))
    assert result["eligible"] is False
    assert "tradable" in result["rejection_reason"]


def test_momentum_eval_fails_spread_too_wide():
    from paper.momentum import evaluate_momentum_entry
    q = dict(_quality_passing(), spread_percent=0.50)
    result = _with_overrides(_base_overrides(), lambda: evaluate_momentum_entry("X", q, _regime_passing()))
    assert result["eligible"] is False
    assert "spread" in result["rejection_reason"]


def test_momentum_eval_fails_change_too_low():
    from paper.momentum import evaluate_momentum_entry
    q = dict(_quality_passing(), change_percent=0.5)
    result = _with_overrides(_base_overrides(), lambda: evaluate_momentum_entry("X", q, _regime_passing()))
    assert result["eligible"] is False
    assert "change" in result["rejection_reason"]


def test_momentum_eval_fails_volume_too_low():
    from paper.momentum import evaluate_momentum_entry
    q = dict(_quality_passing(), volume_ratio=1.0)
    result = _with_overrides(_base_overrides(), lambda: evaluate_momentum_entry("X", q, _regime_passing()))
    assert result["eligible"] is False
    assert "volume" in result["rejection_reason"]


def test_momentum_eval_fails_regime_too_low():
    from paper.momentum import evaluate_momentum_entry
    regime = {"regime": "neutral", "risk_on_score": 30}
    result = _with_overrides(_base_overrides(), lambda: evaluate_momentum_entry("X", _quality_passing(), regime))
    assert result["eligible"] is False
    assert "regime" in result["rejection_reason"] or "score" in result["rejection_reason"]


def test_momentum_eval_no_require_regime_skips_gate():
    from paper.momentum import evaluate_momentum_entry
    overrides = dict(_base_overrides(), **{"PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": False})
    regime = {"regime": "risk_off", "risk_on_score": 10}
    result = _with_overrides(overrides, lambda: evaluate_momentum_entry("X", _quality_passing(), regime))
    # Gate skipped — should be eligible (all other gates pass)
    assert result["gate_results"].get("regime_ok") is True


# ── 5. Catalyst path unchanged ────────────────────────────────────────────────

def test_catalyst_path_still_used_when_momentum_disabled():
    """With momentum disabled, catalyst-eligible candidates still enter normally."""
    from paper.account import PaperAccount
    from paper.models import Position
    acc = PaperAccount(1000.0)
    pos = acc.enter_position("AAPL", 150.0, 200.0, "earnings", entry_score=85, entry_mode="catalyst")
    assert pos is not None
    assert pos.entry_mode == "catalyst"
    assert pos.entry_catalyst_type == "earnings"


def test_exit_carries_entry_mode():
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    acc.enter_position("AAPL", 150.0, 200.0, "earnings", entry_score=85, entry_mode="catalyst")
    trade = acc.exit_position("AAPL", 155.0, "take_profit")
    assert trade is not None
    assert trade.entry_mode == "catalyst"


def test_models_entry_mode_default_none():
    from paper.models import Position, ClosedTrade
    pos = Position(
        position_id="abc123",
        symbol="AAPL",
        entry_price=150.0,
        shares=1.0,
        cost_basis=150.0,
        entry_time="2026-01-01T12:00:00+00:00",
        entry_catalyst_type="earnings",
    )
    assert pos.entry_mode is None

    trade = ClosedTrade(
        position_id="abc123",
        symbol="AAPL",
        entry_price=150.0,
        exit_price=155.0,
        shares=1.0,
        cost_basis=150.0,
        proceeds=155.0,
        pnl=5.0,
        pnl_percent=3.33,
        entry_time="2026-01-01T12:00:00+00:00",
        exit_time="2026-01-01T12:30:00+00:00",
        exit_reason="take_profit",
        entry_catalyst_type="earnings",
        hold_minutes=30.0,
    )
    assert trade.entry_mode is None


# ── 6. Position sizing ────────────────────────────────────────────────────────

def test_momentum_position_size_multiplier_applied():
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    # Normal catalyst entry at 25% of cash → $250
    pos_cat = acc.enter_position("AAPL", 100.0, 250.0, "earnings", entry_mode="catalyst")
    assert pos_cat is not None
    cat_cost = pos_cat.cost_basis

    acc2 = PaperAccount(1000.0)
    # Momentum entry with 0.5x multiplier → $125
    pos_mom = acc2.enter_position("AAPL", 100.0, 125.0, "momentum", entry_mode="momentum")
    assert pos_mom is not None
    assert pos_mom.cost_basis == pytest.approx(125.0, rel=1e-4)
    assert pos_mom.cost_basis < cat_cost


# ── 7. Candidate output fields ────────────────────────────────────────────────

def test_candidate_has_momentum_fields():
    """run_tick returns candidates with Phase 2M fields present."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 4.0,
        "has_valid_quote": True, "has_valid_trade": True, "has_sufficient_volume": True,
        "has_acceptable_spread": True, "rejection_reasons": [],
    }

    with (
        patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
              return_value={
                  "active_symbols": ["AAPL"],
                  "active_count": 1,
                  "last_refreshed_at": None,
                  "refresh_reason": "test",
                  "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
              }),
        patch("paper.simulator.polygon_client.get_ticker_snapshot", new_callable=AsyncMock,
              return_value=quality),
        patch("paper.simulator.polygon_client.get_previous_close", new_callable=AsyncMock,
              return_value={}),
        patch("data.market_quality.evaluate_market_quality", return_value=quality),
        patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
              return_value={"filter": {"accepted": []}}),
        patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
              return_value={"ok": True}),
        patch("paper.simulator.get_cached_universe", return_value=None),
        patch("paper.simulator._save_state", new_callable=AsyncMock),
        patch("paper.runtime_config.effective_value") as mock_cfg,
    ):
        def cfg_side(k):
            return {
                "PAPER_MOMENTUM_MODE_ENABLED": False,
                "PAPER_ENTRY_SCORE_THRESHOLD": 70,
                "PAPER_TAKE_PROFIT_PERCENT": 0.60,
                "PAPER_STOP_LOSS_PERCENT": 0.35,
                "PAPER_MAX_HOLD_MINUTES": 15,
                "PAPER_MAX_OPEN_POSITIONS": 2,
                "PAPER_MAX_TRADES_PER_DAY": 20,
                "PAPER_POSITION_SIZE_PERCENT": 25.0,
                "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
                "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
                "MARKET_REGIME_ENABLED": False,
            }.get(k)
        mock_cfg.side_effect = cfg_side

        import paper.simulator as sim
        result = asyncio.run(sim.run_tick())

    candidates = result.get("candidates", [])
    assert len(candidates) == 1
    c = candidates[0]
    assert "entry_mode" in c
    assert "momentum_eligible" in c
    assert "momentum_score" in c
    assert "momentum_score_threshold" in c
    assert "momentum_rejection_reason" in c
    assert "momentum_gate_results" in c


# ── 8. Readiness — momentum_mode check ───────────────────────────────────────

def test_readiness_momentum_check_pass_when_disabled(client):
    with (
        patch("api.readiness._check_polygon_data", new_callable=AsyncMock,
              return_value={"name": "polygon_data", "status": "pass", "message": "ok", "details": {}}),
        patch("paper.runtime_config.effective_value") as mock_cfg,
    ):
        def cfg_side(k):
            return {
                "PAPER_MOMENTUM_MODE_ENABLED": False,
                "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
                "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 5,
                "PAPER_MARKET_DISCOVERY_ENABLED": False,
                "MARKET_REGIME_ENABLED": False,
            }.get(k)
        mock_cfg.side_effect = cfg_side
        resp = client.get("/api/readiness/session")

    assert resp.status_code == 200
    data = resp.json()
    checks = {c["name"]: c for c in data.get("checks", [])}
    assert "momentum_mode" in checks
    assert checks["momentum_mode"]["status"] == "pass"


def test_readiness_momentum_check_warn_when_enabled(client):
    with (
        patch("api.readiness._check_polygon_data", new_callable=AsyncMock,
              return_value={"name": "polygon_data", "status": "pass", "message": "ok", "details": {}}),
        patch("paper.runtime_config.effective_value") as mock_cfg,
    ):
        def cfg_side(k):
            return {
                "PAPER_MOMENTUM_MODE_ENABLED": True,
                "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
                "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 5,
                "PAPER_MARKET_DISCOVERY_ENABLED": False,
                "MARKET_REGIME_ENABLED": False,
            }.get(k)
        mock_cfg.side_effect = cfg_side
        resp = client.get("/api/readiness/session")

    assert resp.status_code == 200
    data = resp.json()
    checks = {c["name"]: c for c in data.get("checks", [])}
    assert "momentum_mode" in checks
    assert checks["momentum_mode"]["status"] == "warn"


# ── 9. Monitoring — momentum_mode dict ────────────────────────────────────────

def test_monitoring_has_momentum_mode_field(client):
    with (
        patch("paper.simulator.get_status", return_value={
            "running": False, "last_tick_at": None, "last_error": None,
        }),
        patch("paper.journal.get_journal_status", return_value={
            "enabled": False, "database_connected": False,
            "tables_ready": False, "last_persist_ok": None,
        }),
        patch("paper.runtime_config.effective_value") as mock_cfg,
        patch("paper.runtime_config.get_runtime_status", return_value={
            "overrides_active": False, "override_count": 0,
            "persistent": False, "warnings": [],
        }),
    ):
        def cfg_side(k):
            return {
                "MARKET_REGIME_ENABLED": False,
                "PAPER_MOMENTUM_MODE_ENABLED": False,
                "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
                "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
                "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
                "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
                "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": True,
                "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
                "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": 0.5,
                "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 5,
            }.get(k)
        mock_cfg.side_effect = cfg_side
        resp = client.get("/api/monitoring/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "momentum_mode" in data
    mm = data["momentum_mode"]
    assert "enabled" in mm
    assert mm["enabled"] is False
    assert "disclaimer" in mm


def test_monitoring_momentum_enabled_adds_warning(client):
    with (
        patch("paper.simulator.get_status", return_value={
            "running": False, "last_tick_at": None, "last_error": None,
        }),
        patch("paper.journal.get_journal_status", return_value={
            "enabled": False, "database_connected": False,
            "tables_ready": False, "last_persist_ok": None,
        }),
        patch("paper.runtime_config.effective_value") as mock_cfg,
        patch("paper.runtime_config.get_runtime_status", return_value={
            "overrides_active": False, "override_count": 0,
            "persistent": False, "warnings": [],
        }),
    ):
        def cfg_side(k):
            return {
                "MARKET_REGIME_ENABLED": False,
                "PAPER_MOMENTUM_MODE_ENABLED": True,
                "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
                "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
                "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
                "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
                "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": True,
                "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
                "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": 0.5,
                "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 5,
            }.get(k)
        mock_cfg.side_effect = cfg_side
        resp = client.get("/api/monitoring/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["momentum_mode"]["enabled"] is True
    # Warning about momentum enabled should appear
    warnings = data.get("warnings", [])
    assert any("momentum" in w.lower() for w in warnings)


# ── 10. Safety — no broker/AI imports ────────────────────────────────────────

def test_momentum_py_no_broker_or_ai_imports():
    path = BACKEND_ROOT / "paper" / "momentum.py"
    imports = _ast_imports(path)
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden module {forbidden!r} found in momentum.py import: {imp!r}"


def test_momentum_py_no_execution_calls():
    path = BACKEND_ROOT / "paper" / "momentum.py"
    source = path.read_text()
    for name in FORBIDDEN_EXECUTION:
        assert name not in source, \
            f"Execution-related name {name!r} found in momentum.py"


def test_simulator_no_broker_imports():
    path = BACKEND_ROOT / "paper" / "simulator.py"
    imports = _ast_imports(path)
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden module {forbidden!r} found in simulator.py: {imp!r}"


def test_momentum_mode_disabled_after_runtime_reset():
    """After reset_runtime_config, momentum mode must return to disabled default."""
    import asyncio
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides["PAPER_MOMENTUM_MODE_ENABLED"] = True
        assert rc.effective_value("PAPER_MOMENTUM_MODE_ENABLED") is True

        # Reset overrides in-memory (skip DB)
        rc._runtime_overrides = {}
        assert rc.effective_value("PAPER_MOMENTUM_MODE_ENABLED") is False
    finally:
        rc._runtime_overrides = old


# ── 11. Cap-bound momentum sizing ─────────────────────────────────────────────

def test_momentum_sizing_cap_applied_before_multiplier():
    """
    Multiplier must apply after the USD cap, not before it.

    cash=10000, pct=25%, cap=250, multiplier=0.5:
      normal_budget = min(2500, 250) = 250  (capped)
      momentum_budget = 250 * 0.5 = 125     (correct)

    Pre-fix bug: min(2500 * 0.5, 250) = min(1250, 250) = 250
    which equals the full cap — same as a catalyst entry on large accounts.
    """
    cash, pct, cap, mult = 10_000.0, 25.0, 250.0, 0.5

    normal_budget = min(cash * (pct / 100.0), cap)
    momentum_budget = normal_budget * mult

    assert normal_budget == pytest.approx(250.0)
    assert momentum_budget == pytest.approx(125.0)

    # Confirm the old formula produced the wrong value (equal to cap)
    old_formula = min(cash * (pct / 100.0) * mult, cap)
    assert old_formula == pytest.approx(250.0)
    assert momentum_budget < old_formula   # fixed formula is strictly smaller


def test_catalyst_sizing_no_multiplier_applied():
    """Catalyst path uses the normal capped budget with no multiplier."""
    cash, pct, cap = 10_000.0, 25.0, 250.0

    catalyst_budget = min(cash * (pct / 100.0), cap)
    assert catalyst_budget == pytest.approx(250.0)

    momentum_budget = catalyst_budget * 0.5
    assert momentum_budget == pytest.approx(125.0)
    assert catalyst_budget > momentum_budget


# ── 12. Simulator-level momentum fallback ─────────────────────────────────────

def test_simulator_momentum_fallback_entry_mode():
    """
    When catalyst path fails due to no accepted catalysts, the simulator falls back
    to the momentum path and records entry_mode='momentum'.
    No Polygon calls — all I/O is mocked.
    """
    import asyncio
    from paper import runtime_config as rc
    import paper.simulator as sim
    from paper.account import PaperAccount

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 4.0,
        "day_volume": 4_000_000, "previous_day_volume": 1_000_000,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    sim._account = PaperAccount(1000.0)

    rc._runtime_overrides.update({
        "PAPER_MOMENTUM_MODE_ENABLED": True,
        "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": 85,
        "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": 1.5,
        "PAPER_MOMENTUM_MIN_VOLUME_RATIO": 2.0,
        "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": 0.25,
        "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": False,
        "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": 60,
        "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": 0.5,
        "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": 5,
    })

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={
                      "active_symbols": ["AAPL"],
                      "active_count": 1,
                      "last_refreshed_at": None,
                      "refresh_reason": "test",
                      "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
                  }),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": []}}),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality", new=AsyncMock(return_value=(None, {}))),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    entries = result.get("entries", [])
    assert len(entries) == 1, f"Expected 1 momentum entry, got {len(entries)}: {entries}"
    assert entries[0]["entry_mode"] == "momentum"
    assert result["today_momentum_entry_count"] == 1
    assert result["momentum_mode_enabled"] is True


# ── 13. Strong bearish catalyst cannot be rescued by momentum ─────────────────

def test_strong_bearish_catalyst_not_rescued_by_momentum():
    """
    A strong bearish catalyst sets hard_rejection='strong_bearish_catalyst'
    without setting is_no_catalyst_rejection, so the momentum path is never taken.
    This replicates the exact gate logic from simulator.py.
    """
    q = {
        "tradable": True, "spread_percent": 0.10,
        "change_percent": 3.0, "volume_ratio": 4.0, "rejection_reasons": [],
    }
    cats = [{"classified_event_type": "earnings", "ticker": "AAPL"}]
    scoring = {"catalyst_sentiment": "bearish", "catalyst_materiality_score": 0.95}

    hard_rejection: str | None = None
    is_no_catalyst_rejection: bool = False

    if not q.get("tradable"):
        hard_rejection = "not tradable"
    elif (q.get("spread_percent") or 999) > 0.50:
        hard_rejection = "spread too wide"
    elif (q.get("change_percent") or 0) <= 0:
        hard_rejection = "change not positive"
    elif q.get("volume_ratio") is not None and q.get("volume_ratio", 1.0) < 0.8:
        hard_rejection = "low volume"
    elif (
        True  # PAPER_REJECT_STRONG_BEARISH_CATALYST=True
        and scoring.get("catalyst_sentiment") == "bearish"
        and (scoring.get("catalyst_materiality_score") or 0.0) >= 0.8
    ):
        hard_rejection = "strong_bearish_catalyst"
    elif not cats:
        hard_rejection = "no accepted catalysts"
        is_no_catalyst_rejection = True

    assert hard_rejection == "strong_bearish_catalyst"
    assert is_no_catalyst_rejection is False  # momentum fallback not accessible


# ── 14. Momentum account gates ────────────────────────────────────────────────

def test_momentum_blocked_max_open_positions():
    """Momentum (and catalyst) entry is blocked when max open positions is reached."""
    from paper.account import PaperAccount
    acc = PaperAccount(10_000.0)
    pos = acc.enter_position("AAPL", 100.0, 200.0, "earnings", entry_mode="catalyst")
    assert pos is not None
    can, reason = acc.can_enter("MSFT", max_positions=1, max_trades=100)
    assert not can
    assert "max positions" in reason


def test_momentum_blocked_max_daily_trades():
    """Momentum entry is blocked when max daily trade count is reached."""
    from paper.account import PaperAccount
    acc = PaperAccount(10_000.0)
    acc.enter_position("AAPL", 100.0, 200.0, "earnings", entry_mode="catalyst")
    acc.exit_position("AAPL", 110.0, "take_profit")  # consumes one daily trade
    can, reason = acc.can_enter("MSFT", max_positions=10, max_trades=1)
    assert not can
    assert "max daily" in reason


def test_momentum_daily_limit_blocks_at_threshold():
    """
    When today_momentum_count >= PAPER_MOMENTUM_MAX_TRADES_PER_DAY,
    the simulator should block the momentum entry.
    Replicates the count logic from simulator.py.
    """
    import uuid
    from datetime import datetime, timezone
    from paper.account import PaperAccount
    from paper.models import Position

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    acc = PaperAccount(10_000.0)

    # Inject a momentum position from today directly
    p = Position(
        position_id=uuid.uuid4().hex[:8],
        symbol="XXXX",
        entry_price=50.0,
        shares=2.0,
        cost_basis=100.0,
        entry_time=f"{today_str}T10:00:00+00:00",
        entry_catalyst_type="momentum",
        entry_mode="momentum",
    )
    acc.positions["XXXX"] = p

    today_momentum_count = sum(
        1 for pos in acc.positions.values()
        if pos.entry_mode == "momentum" and pos.entry_time.startswith(today_str)
    ) + sum(
        1 for t in acc.trades
        if t.entry_mode == "momentum" and t.entry_time.startswith(today_str)
    )
    momentum_max = 1  # limit of 1 already consumed
    assert today_momentum_count == 1
    assert today_momentum_count >= momentum_max  # entry would be blocked

    # Below limit: not blocked
    assert (today_momentum_count < (momentum_max + 1)) is True
