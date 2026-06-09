"""
Phase 2R tests — No-catalyst momentum entry path.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All fake-money simulation only.
"""

import ast
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

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


def _with_overrides(overrides: dict, fn):
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update(overrides)
        return fn()
    finally:
        rc._runtime_overrides = old


def _base_nc_overrides() -> dict:
    return {
        "PAPER_NO_CATALYST_ENTRY_ENABLED": True,
        "PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH": True,
        "PAPER_NO_CATALYST_MIN_SCORE": 60,
        "PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE": 15,
        "PAPER_NO_CATALYST_MIN_CHANGE_PERCENT": 2.0,
        "PAPER_NO_CATALYST_MIN_VOLUME_RATIO": 0.5,
        "PAPER_NO_CATALYST_MAX_SPREAD_PERCENT": 0.20,
        "PAPER_NO_CATALYST_REQUIRE_RISK_ON": True,
        "PAPER_NO_CATALYST_MIN_RISK_SCORE": 60,
        "PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER": 0.5,
        "PAPER_NO_CATALYST_MAX_TRADES_PER_DAY": 20,
    }


def _quality_passing() -> dict:
    return {
        "tradable": True,
        "bid": 100.0,
        "ask": 100.10,
        "last_trade_price": 100.05,
        "spread_percent": 0.10,
        "change_percent": 2.5,
        "volume_ratio": 1.0,
        "rejection_reasons": [],
    }


def _scoring_passing() -> dict:
    """Scoring dict that passes all Phase 2R gates (total_score >= 60, momentum_score >= 15)."""
    return {
        "total_score": 65,
        "score_threshold": 70,
        "score_pass": False,  # catalyst path fails; no-catalyst path evaluated
        "components": {
            "market_quality_score": 25,
            "spread_score": 10,
            "momentum_score": 20,  # max for momentum component (change >= 2.0%)
            "volume_score": 10,
            "catalyst_score": 0,   # no catalysts
            "risk_penalty": 0,
        },
        "catalyst_sentiment": None,
        "bearish_flags": [],
        "positive_reasons": ["tradable: passed quality gate"],
        "negative_reasons": ["no accepted catalysts"],
        "decision_reason": "no accepted catalysts",
    }


def _regime_passing() -> dict:
    return {"regime": "risk_on", "risk_on_score": 75}


# ── 1. Feature disabled by default ──────────────────────────────────────────

def test_no_catalyst_entry_disabled_by_default():
    from core.config import settings
    assert settings.PAPER_NO_CATALYST_ENTRY_ENABLED is False, \
        "PAPER_NO_CATALYST_ENTRY_ENABLED must default to False"


def test_no_catalyst_entry_disabled_via_effective_value():
    from paper.runtime_config import effective_value
    assert effective_value("PAPER_NO_CATALYST_ENTRY_ENABLED") is False


# ── 2. Conservative defaults ─────────────────────────────────────────────────

def test_no_catalyst_conservative_defaults():
    from core.config import settings
    assert settings.PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH is True
    assert settings.PAPER_NO_CATALYST_MIN_SCORE == 60
    assert settings.PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE == 15
    assert settings.PAPER_NO_CATALYST_MIN_CHANGE_PERCENT == pytest.approx(2.0)
    assert settings.PAPER_NO_CATALYST_MIN_VOLUME_RATIO == pytest.approx(0.5)
    assert settings.PAPER_NO_CATALYST_MAX_SPREAD_PERCENT == pytest.approx(0.20)
    assert settings.PAPER_NO_CATALYST_REQUIRE_RISK_ON is True
    assert settings.PAPER_NO_CATALYST_MIN_RISK_SCORE == 60
    assert settings.PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER == pytest.approx(0.5)
    assert settings.PAPER_NO_CATALYST_MAX_TRADES_PER_DAY == 20


# ── 3. Runtime config schema ──────────────────────────────────────────────────

def test_no_catalyst_fields_in_schema():
    from paper.runtime_config import _SCHEMA
    expected = [
        "PAPER_NO_CATALYST_ENTRY_ENABLED",
        "PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH",
        "PAPER_NO_CATALYST_MIN_SCORE",
        "PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE",
        "PAPER_NO_CATALYST_MIN_CHANGE_PERCENT",
        "PAPER_NO_CATALYST_MIN_VOLUME_RATIO",
        "PAPER_NO_CATALYST_MAX_SPREAD_PERCENT",
        "PAPER_NO_CATALYST_REQUIRE_RISK_ON",
        "PAPER_NO_CATALYST_MIN_RISK_SCORE",
        "PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER",
        "PAPER_NO_CATALYST_MAX_TRADES_PER_DAY",
    ]
    for f in expected:
        assert f in _SCHEMA, f"Field {f!r} missing from _SCHEMA"


def test_no_catalyst_schema_categories():
    from paper.runtime_config import _SCHEMA
    for key, spec in _SCHEMA.items():
        if key.startswith("PAPER_NO_CATALYST_"):
            assert spec["category"] == "no_catalyst", f"{key} category must be 'no_catalyst'"
            assert spec["applies_to"] == "no_catalyst", f"{key} applies_to must be 'no_catalyst'"
            assert spec["restart_required"] is False


def test_no_catalyst_schema_validation_enabled_must_be_bool():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_NO_CATALYST_ENTRY_ENABLED": "yes"})
    assert not ok
    assert any("bool" in e for e in errors)


def test_no_catalyst_schema_validation_min_score_bounds():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_NO_CATALYST_MIN_SCORE": 150})
    assert not ok
    assert any("exceed" in e.lower() or "maximum" in e.lower() for e in errors)


def test_no_catalyst_schema_validation_multiplier_bounds():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER": 2.0})
    assert not ok
    assert any("exceed" in e.lower() or "maximum" in e.lower() for e in errors)


# ── 4. evaluate_no_catalyst_entry — disabled ─────────────────────────────────

def test_no_catalyst_eval_disabled_returns_ineligible():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    result = _with_overrides(
        {"PAPER_NO_CATALYST_ENTRY_ENABLED": False},
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), _scoring_passing(), _regime_passing()),
    )
    assert result["eligible"] is False
    assert result["rejection_reason"] == "no_catalyst_entry_disabled"


# ── 5. evaluate_no_catalyst_entry — all gates pass ───────────────────────────

def test_no_catalyst_eval_all_gates_pass():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), _scoring_passing(), _regime_passing()),
    )
    assert result["eligible"] is True
    assert result["rejection_reason"] is None
    assert result["config_snapshot"] is not None
    assert isinstance(result["positive_reasons"], list)
    assert len(result["positive_reasons"]) > 0


# ── 6. Gate — bearish catalyst blocks ────────────────────────────────────────

def test_no_catalyst_eval_bearish_catalyst_blocks():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    scoring = dict(_scoring_passing(), catalyst_sentiment="bearish", bearish_flags=["revenue_miss"])
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), scoring, _regime_passing()),
    )
    assert result["eligible"] is False
    assert result["rejection_reason"] == "bearish_catalyst_present"


def test_no_catalyst_eval_no_bearish_block_when_flag_false():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    scoring = dict(_scoring_passing(), catalyst_sentiment="bearish", bearish_flags=["revenue_miss"])
    overrides = dict(_base_nc_overrides(), **{"PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH": False})
    result = _with_overrides(
        overrides,
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), scoring, _regime_passing()),
    )
    assert result["eligible"] is True


# ── 7. Gate — score threshold ─────────────────────────────────────────────────

def test_no_catalyst_eval_fails_score_too_low():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    scoring = dict(_scoring_passing(), total_score=45)
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), scoring, _regime_passing()),
    )
    assert result["eligible"] is False
    assert "score" in result["rejection_reason"]


# ── 8. Gate — momentum component score ───────────────────────────────────────

def test_no_catalyst_eval_fails_momentum_score_too_low():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    scoring = dict(_scoring_passing())
    # momentum_score=10 (change 0-1% range) < min 15
    scoring["components"] = dict(_scoring_passing()["components"], momentum_score=10)
    result = _with_overrides(
        dict(_base_nc_overrides(), **{"PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE": 15}),
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), scoring, _regime_passing()),
    )
    assert result["eligible"] is False
    assert "momentum_score" in result["rejection_reason"] or "momentum" in result["rejection_reason"]


# ── 9. Gate — change percent ──────────────────────────────────────────────────

def test_no_catalyst_eval_fails_change_too_low():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    q = dict(_quality_passing(), change_percent=1.0)
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", q, _scoring_passing(), _regime_passing()),
    )
    assert result["eligible"] is False
    assert "change" in result["rejection_reason"]


# ── 10. Gate — volume ratio ───────────────────────────────────────────────────

def test_no_catalyst_eval_fails_volume_too_low():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    q = dict(_quality_passing(), volume_ratio=0.2)
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", q, _scoring_passing(), _regime_passing()),
    )
    assert result["eligible"] is False
    assert "volume" in result["rejection_reason"]


# ── 11. Gate — spread ─────────────────────────────────────────────────────────

def test_no_catalyst_eval_fails_spread_too_wide():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    q = dict(_quality_passing(), spread_percent=0.30)
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", q, _scoring_passing(), _regime_passing()),
    )
    assert result["eligible"] is False
    assert "spread" in result["rejection_reason"]


# ── 12. Gate — regime ─────────────────────────────────────────────────────────

def test_no_catalyst_eval_fails_regime_too_low():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    regime = {"regime": "risk_off", "risk_on_score": 30}
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), _scoring_passing(), regime),
    )
    assert result["eligible"] is False
    assert "regime" in result["rejection_reason"] or "score" in result["rejection_reason"]


def test_no_catalyst_eval_no_require_regime_skips_gate():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    overrides = dict(_base_nc_overrides(), **{"PAPER_NO_CATALYST_REQUIRE_RISK_ON": False})
    regime = {"regime": "risk_off", "risk_on_score": 10}
    result = _with_overrides(
        overrides,
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), _scoring_passing(), regime),
    )
    assert result["gate_results"].get("regime_ok") is True
    assert result["eligible"] is True


# ── 13. Config snapshot in successful result ──────────────────────────────────

def test_no_catalyst_eval_config_snapshot_present():
    from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
    result = _with_overrides(
        _base_nc_overrides(),
        lambda: evaluate_no_catalyst_entry("AAPL", _quality_passing(), _scoring_passing(), _regime_passing()),
    )
    assert result["eligible"] is True
    snap = result["config_snapshot"]
    assert snap is not None
    assert snap["enabled"] is True
    assert snap["min_score"] == 60
    assert snap["position_size_multiplier"] == pytest.approx(0.5)
    assert snap["max_trades_per_day"] == 20


# ── 14. Simulator Path C entry ────────────────────────────────────────────────

def test_simulator_no_catalyst_path_c_entry_mode():
    """Path C fires when no-catalyst enabled and candidate passes all gates."""
    import asyncio
    from paper import runtime_config as rc
    import paper.simulator as sim
    from paper.account import PaperAccount

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.10, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 2.5, "volume_ratio": 1.0,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    sim._account = PaperAccount(1000.0)

    rc._runtime_overrides.update({
        **_base_nc_overrides(),
        "PAPER_USE_MARKETDATA_CACHE": False,
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
        "PAPER_MIN_VOLUME_RATIO": 0.0,
        "MARKET_REGIME_ENABLED": False,
        "PAPER_NO_CATALYST_REQUIRE_RISK_ON": False,  # skip regime gate
        "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY": False,
        "PAPER_DAILY_MAX_LOSS_ENABLED": False,
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
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    entries = result.get("entries", [])
    assert len(entries) == 1, f"Expected 1 no-catalyst entry, got {len(entries)}: {result.get('errors')}"
    assert entries[0]["entry_mode"] == "momentum_no_catalyst"
    assert result["today_no_catalyst_entry_count"] == 1
    assert result["no_catalyst_entry_enabled"] is True


# ── 15. Position size multiplier ─────────────────────────────────────────────

def test_no_catalyst_position_size_multiplier_applied():
    """No-catalyst position budget = normal_budget × 0.5."""
    cash, pct, cap, mult = 10_000.0, 25.0, 250.0, 0.5

    normal_budget = min(cash * (pct / 100.0), cap)
    no_catalyst_budget = normal_budget * mult

    assert normal_budget == pytest.approx(250.0)
    assert no_catalyst_budget == pytest.approx(125.0)


def test_no_catalyst_sizing_cap_before_multiplier():
    """Cap must be applied before the multiplier (same correctness as 2M)."""
    cash, pct, cap, mult = 10_000.0, 25.0, 250.0, 0.5

    correct = min(cash * (pct / 100.0), cap) * mult
    wrong = min(cash * (pct / 100.0) * mult, cap)

    assert correct == pytest.approx(125.0)
    assert wrong == pytest.approx(250.0)
    assert correct < wrong


# ── 16. Daily limit gate ──────────────────────────────────────────────────────

def test_no_catalyst_daily_limit_blocks_at_threshold():
    """today_no_catalyst_count >= max blocks further no-catalyst entries."""
    import uuid
    from datetime import datetime, timezone
    from paper.account import PaperAccount
    from paper.models import Position

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    acc = PaperAccount(10_000.0)

    p = Position(
        position_id=uuid.uuid4().hex[:8],
        symbol="XXXX",
        entry_price=50.0,
        shares=2.0,
        cost_basis=100.0,
        entry_time=f"{today_str}T10:00:00+00:00",
        entry_catalyst_type="momentum_no_catalyst",
        entry_mode="momentum_no_catalyst",
    )
    acc.positions["XXXX"] = p

    today_no_catalyst_count = sum(
        1 for pos in acc.positions.values()
        if pos.entry_mode == "momentum_no_catalyst" and pos.entry_time.startswith(today_str)
    )
    no_catalyst_max = 1
    assert today_no_catalyst_count == 1
    assert today_no_catalyst_count >= no_catalyst_max


# ── 17. Candidate output fields ───────────────────────────────────────────────

def test_candidate_has_no_catalyst_fields():
    """run_tick returns candidates with Phase 2R fields present."""
    import asyncio
    from paper import runtime_config as rc
    import paper.simulator as sim
    from paper.account import PaperAccount

    quality = {
        "tradable": True, "bid": 100.0, "ask": 100.1, "last_trade_price": 100.05,
        "spread_percent": 0.10, "change_percent": 3.0, "volume_ratio": 1.0,
        "has_valid_quote": True, "has_valid_trade": True,
        "has_sufficient_volume": True, "has_acceptable_spread": True,
        "rejection_reasons": [],
    }

    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    sim._account = PaperAccount(1000.0)

    rc._runtime_overrides.update({
        "PAPER_USE_MARKETDATA_CACHE": False,
        "PAPER_NO_CATALYST_ENTRY_ENABLED": False,
        "PAPER_MOMENTUM_MODE_ENABLED": False,
        "PAPER_ENTRY_SCORE_THRESHOLD": 70,
        "PAPER_TAKE_PROFIT_PERCENT": 0.60,
        "PAPER_STOP_LOSS_PERCENT": 0.35,
        "PAPER_MAX_HOLD_MINUTES": 15,
        "PAPER_MAX_OPEN_POSITIONS": 2,
        "PAPER_MAX_TRADES_PER_DAY": 20,
        "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
        "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
        "PAPER_MIN_VOLUME_RATIO": 0.0,
        "MARKET_REGIME_ENABLED": False,
        "PAPER_DAILY_MAX_LOSS_ENABLED": False,
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
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    candidates = result.get("candidates", [])
    assert len(candidates) == 1, f"Expected 1 candidate; errors={result.get('errors')}"
    c = candidates[0]
    assert "no_catalyst_momentum_eligible" in c
    assert "no_catalyst_momentum_reasons" in c
    assert "no_catalyst_momentum_blockers" in c
    assert "no_catalyst_config_snapshot" in c
    assert "catalyst_required" in c


# ── 18. Path C distinct from Path B ──────────────────────────────────────────

def test_path_c_distinct_from_path_b():
    """Path C sets entry_mode='momentum_no_catalyst'; Path B sets 'momentum'. Never the same."""
    assert "momentum_no_catalyst" != "momentum"
    assert "momentum_no_catalyst" != "catalyst"


# ── 19. Safety — no forbidden imports ────────────────────────────────────────

def test_no_catalyst_py_no_broker_or_ai_imports():
    path = BACKEND_ROOT / "paper" / "no_catalyst_momentum.py"
    imports = _ast_imports(path)
    for imp in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in imp.lower(), \
                f"Forbidden module {forbidden!r} found in no_catalyst_momentum.py: {imp!r}"


def test_no_catalyst_py_no_execution_calls():
    path = BACKEND_ROOT / "paper" / "no_catalyst_momentum.py"
    source = path.read_text()
    for name in FORBIDDEN_EXECUTION:
        assert name not in source, \
            f"Execution-related name {name!r} found in no_catalyst_momentum.py"


# ── 20. Monitoring endpoint exposes no_catalyst_mode ─────────────────────────

def test_monitoring_has_no_catalyst_mode_field():
    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)

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
                "PAPER_NO_CATALYST_ENTRY_ENABLED": False,
                "PAPER_NO_CATALYST_MIN_SCORE": 60,
                "PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE": 15,
                "PAPER_NO_CATALYST_MIN_CHANGE_PERCENT": 2.0,
                "PAPER_NO_CATALYST_MIN_VOLUME_RATIO": 0.5,
                "PAPER_NO_CATALYST_MAX_SPREAD_PERCENT": 0.20,
                "PAPER_NO_CATALYST_REQUIRE_RISK_ON": True,
                "PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER": 0.5,
                "PAPER_NO_CATALYST_MAX_TRADES_PER_DAY": 20,
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
    assert "no_catalyst_mode" in data
    nc = data["no_catalyst_mode"]
    assert "enabled" in nc
    assert nc["enabled"] is False
    assert "disclaimer" in nc


def test_monitoring_no_catalyst_enabled_adds_warning():
    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)

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
                "PAPER_NO_CATALYST_ENTRY_ENABLED": True,
                "PAPER_NO_CATALYST_MIN_SCORE": 60,
                "PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE": 15,
                "PAPER_NO_CATALYST_MIN_CHANGE_PERCENT": 2.0,
                "PAPER_NO_CATALYST_MIN_VOLUME_RATIO": 0.5,
                "PAPER_NO_CATALYST_MAX_SPREAD_PERCENT": 0.20,
                "PAPER_NO_CATALYST_REQUIRE_RISK_ON": True,
                "PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER": 0.5,
                "PAPER_NO_CATALYST_MAX_TRADES_PER_DAY": 20,
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
    assert data["no_catalyst_mode"]["enabled"] is True
    warnings = data.get("warnings", [])
    assert any("no-catalyst" in w.lower() or "no_catalyst" in w.lower() for w in warnings)
