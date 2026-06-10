"""
Phase 2T tests — Catalyst type performance guard.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All fake-money simulation only.
"""

import ast
import asyncio
import sys
from contextlib import contextmanager
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


@contextmanager
def _override(overrides: dict):
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        rc._runtime_overrides.update(overrides)
        yield
    finally:
        rc._runtime_overrides = old


def _base_overrides(blocked: str = "fda_regulatory", guard_enabled: bool = True) -> dict:
    return {
        "PAPER_BLOCKED_CATALYST_TYPES": blocked,
        "PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES": guard_enabled,
        "PAPER_ENTRY_SCORE_THRESHOLD": 70,
        "PAPER_TAKE_PROFIT_PERCENT": 0.60,
        "PAPER_STOP_LOSS_PERCENT": 0.35,
        "PAPER_MAX_HOLD_MINUTES": 15,
        "PAPER_MAX_OPEN_POSITIONS": 5,
        "PAPER_MAX_TRADES_PER_DAY": 100,
        "PAPER_POSITION_SIZE_PERCENT": 25.0,
        "PAPER_REJECT_STRONG_BEARISH_CATALYST": False,
        "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
        "MARKET_REGIME_ENABLED": False,
        "PAPER_MOMENTUM_MODE_ENABLED": False,
        "PAPER_NO_CATALYST_ENTRY_ENABLED": False,
        "PAPER_USE_MARKETDATA_CACHE": False,
        "PAPER_MIN_VOLUME_RATIO": 0.0,
        "PAPER_DAILY_MAX_LOSS_ENABLED": False,
    }


def _quality_passing() -> dict:
    return {
        "tradable": True,
        "bid": 50.0,
        "ask": 50.05,
        "last_trade_price": 50.02,
        "spread_percent": 0.10,
        "change_percent": 3.5,
        "volume_ratio": 2.0,
        "rejection_reasons": [],
    }


def _catalyst(symbol: str, event_type: str) -> list[dict]:
    return [{
        "symbol": symbol,
        "classified_event_type": event_type,
        "title": f"Test {event_type} news",
        "sentiment": "bullish",
    }]


def _score_passing() -> dict:
    return {
        "total_score": 85,
        "score_threshold": 70,
        "score_pass": True,
        "components": {"market_quality_score": 25, "spread_score": 10,
                       "momentum_score": 15, "volume_score": 10,
                       "catalyst_score": 25, "risk_penalty": 0},
        "positive_reasons": ["tradable: passed quality gate"],
        "negative_reasons": [],
        "decision_reason": "pass",
        "catalyst_sentiment": "bullish",
        "catalyst_sentiment_score": 0.8,
        "catalyst_materiality_score": 0.8,
        "catalyst_sentiment_reasons": [],
        "bullish_flags": [],
        "bearish_flags": [],
        "strongest_catalyst_title": "Test news",
        "strongest_catalyst_sentiment": "bullish",
    }


def _run_tick_for_symbol(symbol: str, cat_type: str, overrides: dict | None = None) -> dict:
    """Run one tick with a single symbol + single catalyst type. Returns the candidate dict."""
    import paper.simulator as sim
    from paper.account import PaperAccount

    ovr = overrides if overrides is not None else _base_overrides()
    quality = _quality_passing()
    cats = _catalyst(symbol, cat_type)

    old_account = sim._account
    old_prices = dict(sim._last_prices)
    from paper import runtime_config as rc
    old_overrides = dict(rc._runtime_overrides)

    sim._account = PaperAccount(1000.0)
    sim._last_prices.clear()
    rc._runtime_overrides.update(ovr)

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={
                      "active_symbols": [symbol],
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
                  return_value={"filter": {"accepted": cats}}),
            patch("paper.simulator.score_candidate", return_value=_score_passing()),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    cands = result.get("candidates", [])
    assert len(cands) == 1
    return cands[0]


# ── 1. Config defaults ────────────────────────────────────────────────────────

def test_blocked_catalyst_types_default_is_fda_regulatory():
    from core.config import settings
    assert settings.PAPER_BLOCKED_CATALYST_TYPES == "fda_regulatory"


def test_block_strong_negative_catalyst_types_default_true():
    from core.config import settings
    assert settings.PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES is True


def test_paper_blocked_catalyst_types_list_helper():
    from core.config import settings
    blocked = settings.paper_blocked_catalyst_types_list()
    assert "fda_regulatory" in blocked


# ── 2. Runtime config schema ──────────────────────────────────────────────────

def test_blocked_catalyst_fields_in_schema():
    from paper.runtime_config import _SCHEMA
    assert "PAPER_BLOCKED_CATALYST_TYPES" in _SCHEMA
    assert "PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES" in _SCHEMA


def test_blocked_catalyst_schema_types():
    from paper.runtime_config import _SCHEMA
    assert _SCHEMA["PAPER_BLOCKED_CATALYST_TYPES"]["type"] == "str"
    assert _SCHEMA["PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES"]["type"] == "bool"


def test_blocked_catalyst_schema_category():
    from paper.runtime_config import _SCHEMA
    assert _SCHEMA["PAPER_BLOCKED_CATALYST_TYPES"]["category"] == "catalyst"
    assert _SCHEMA["PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES"]["category"] == "catalyst"


# ── 3. Runtime config accepts and exposes PAPER_BLOCKED_CATALYST_TYPES ────────

def test_runtime_config_accepts_blocked_catalyst_types():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_BLOCKED_CATALYST_TYPES": "fda_regulatory,earnings"})
    assert ok, f"Validation failed: {errors}"


def test_runtime_config_blocked_catalyst_types_must_be_str():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_BLOCKED_CATALYST_TYPES": 123})
    assert not ok
    assert any("str" in e for e in errors)


def test_blocked_catalyst_types_list_reads_runtime_override():
    from paper.runtime_config import blocked_catalyst_types_list
    with _override({"PAPER_BLOCKED_CATALYST_TYPES": "fda_regulatory,clinical_trial"}):
        result = blocked_catalyst_types_list()
    assert "fda_regulatory" in result
    assert "clinical_trial" in result


def test_blocked_catalyst_types_list_normalizes_whitespace():
    from paper.runtime_config import blocked_catalyst_types_list
    with _override({"PAPER_BLOCKED_CATALYST_TYPES": "  fda_regulatory ,  earnings  "}):
        result = blocked_catalyst_types_list()
    assert result == ["fda_regulatory", "earnings"]


def test_blocked_catalyst_types_list_empty_string_returns_empty():
    from paper.runtime_config import blocked_catalyst_types_list
    with _override({"PAPER_BLOCKED_CATALYST_TYPES": ""}):
        result = blocked_catalyst_types_list()
    assert result == []


def test_effective_config_exposes_blocked_catalyst_types():
    from paper.runtime_config import get_effective_config
    with _override({"PAPER_BLOCKED_CATALYST_TYPES": "fda_regulatory"}):
        cfg = get_effective_config()
    assert cfg.get("PAPER_BLOCKED_CATALYST_TYPES") == "fda_regulatory"


# ── 4. Catalyst type guard: fda_regulatory blocked ───────────────────────────

def test_fda_regulatory_candidate_is_blocked():
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert cand["eligible"] is False
    assert "catalyst_type_blocked:fda_regulatory" in (cand.get("rejection_reason") or "")


def test_fda_regulatory_catalyst_type_blocked_flag_true():
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert cand.get("catalyst_type_blocked") is True


def test_fda_regulatory_catalyst_type_field_populated():
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert cand.get("catalyst_type") == "fda_regulatory"


def test_blocked_rejection_reason_format_stable():
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert cand.get("rejection_reason") == "catalyst_type_blocked:fda_regulatory"


def test_blocked_catalyst_entry_mode_is_null():
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert cand.get("entry_mode") is None


def test_blocked_catalyst_action_is_null():
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert cand.get("action") is None


def test_blocked_catalyst_no_entry_made():
    import paper.simulator as sim
    from paper.account import PaperAccount
    from paper import runtime_config as rc

    ovr = _base_overrides()
    quality = _quality_passing()
    symbol = "AAPL"
    cats = _catalyst(symbol, "fda_regulatory")

    old_account = sim._account
    old_prices = dict(sim._last_prices)
    old_overrides = dict(rc._runtime_overrides)

    sim._account = PaperAccount(1000.0)
    sim._last_prices.clear()
    rc._runtime_overrides.update(ovr)

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [symbol], "active_count": 1,
                                "last_refreshed_at": None, "refresh_reason": "test",
                                "discovery": {"enabled": False, "discovered_count": 0, "errors": []}}),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": cats}}),
            patch("paper.simulator.score_candidate", return_value=_score_passing()),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    assert result["entries_made"] == 0
    assert result["entries"] == []


# ── 5. Block fires even when score passes ─────────────────────────────────────

def test_blocked_catalyst_cannot_enter_even_if_score_passes():
    """score_pass=True but fda_regulatory is blocked — no entry must be made."""
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert cand["eligible"] is False
    assert cand.get("action") is None
    assert cand.get("rejection_reason") == "catalyst_type_blocked:fda_regulatory"


# ── 6. earnings and m_and_a remain allowed ───────────────────────────────────

def test_earnings_candidate_is_not_blocked():
    cand = _run_tick_for_symbol("AAPL", "earnings")
    assert cand.get("catalyst_type_blocked") is False
    assert cand.get("rejection_reason") != "catalyst_type_blocked:earnings"
    # With score_pass=True and no guard triggered, candidate should be eligible
    assert cand["eligible"] is True


def test_m_and_a_candidate_is_not_blocked():
    cand = _run_tick_for_symbol("AAPL", "m_and_a")
    assert cand.get("catalyst_type_blocked") is False
    assert cand.get("rejection_reason") != "catalyst_type_blocked:m_and_a"
    assert cand["eligible"] is True


# ── 7. Guard disabled: fda_regulatory is no longer blocked ───────────────────

def test_guard_disabled_fda_regulatory_not_blocked():
    ovr = _base_overrides(blocked="fda_regulatory", guard_enabled=False)
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory", overrides=ovr)
    assert cand.get("catalyst_type_blocked") is False
    assert "catalyst_type_blocked" not in (cand.get("rejection_reason") or "")


# ── 8. No-catalyst path cannot bypass blocked catalyst ────────────────────────

def test_no_catalyst_path_cannot_bypass_blocked_catalyst():
    """
    When a candidate has an fda_regulatory catalyst (hard-blocked), the no-catalyst
    entry path must NOT fire — is_no_catalyst_rejection is False for blocked catalysts.
    """
    import paper.simulator as sim
    from paper.account import PaperAccount
    from paper import runtime_config as rc

    ovr = _base_overrides()
    ovr["PAPER_NO_CATALYST_ENTRY_ENABLED"] = True
    ovr["PAPER_NO_CATALYST_MIN_SCORE"] = 50
    ovr["PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE"] = 0
    ovr["PAPER_NO_CATALYST_MIN_CHANGE_PERCENT"] = 0.0
    ovr["PAPER_NO_CATALYST_MIN_VOLUME_RATIO"] = 0.0
    ovr["PAPER_NO_CATALYST_MAX_SPREAD_PERCENT"] = 5.0
    ovr["PAPER_NO_CATALYST_REQUIRE_RISK_ON"] = False
    ovr["PAPER_NO_CATALYST_MAX_TRADES_PER_DAY"] = 100
    ovr["PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER"] = 0.5

    symbol = "AAPL"
    quality = _quality_passing()
    cats = _catalyst(symbol, "fda_regulatory")

    old_account = sim._account
    old_prices = dict(sim._last_prices)
    old_overrides = dict(rc._runtime_overrides)

    sim._account = PaperAccount(1000.0)
    sim._last_prices.clear()
    rc._runtime_overrides.update(ovr)

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [symbol], "active_count": 1,
                                "last_refreshed_at": None, "refresh_reason": "test",
                                "discovery": {"enabled": False, "discovered_count": 0, "errors": []}}),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": cats}}),
            patch("paper.simulator.score_candidate", return_value={
                **_score_passing(),
                "score_pass": False,  # catalyst score fails — would normally allow no-catalyst
            }),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    assert result["entries_made"] == 0, \
        "No-catalyst path must not bypass a blocked catalyst type"
    cand = result["candidates"][0]
    assert cand["eligible"] is False
    assert "catalyst_type_blocked:fda_regulatory" in (cand.get("rejection_reason") or "")


# ── 9. Multiple blocked types ─────────────────────────────────────────────────

def test_multiple_blocked_types_all_blocked():
    ovr = _base_overrides(blocked="fda_regulatory,clinical_trial")
    for cat_type in ("fda_regulatory", "clinical_trial"):
        cand = _run_tick_for_symbol("AAPL", cat_type, overrides=ovr)
        assert cand.get("catalyst_type_blocked") is True, f"{cat_type} should be blocked"
        assert f"catalyst_type_blocked:{cat_type}" in (cand.get("rejection_reason") or "")


def test_multiple_blocked_types_unblocked_still_allowed():
    ovr = _base_overrides(blocked="fda_regulatory,clinical_trial")
    cand = _run_tick_for_symbol("AAPL", "earnings", overrides=ovr)
    assert cand.get("catalyst_type_blocked") is False
    assert cand["eligible"] is True


# ── 10. Existing protections unaffected ──────────────────────────────────────

def test_bearish_catalyst_reject_still_active():
    """Strong-bearish rejection must still fire independently of catalyst-type guard."""
    import paper.simulator as sim
    from paper.account import PaperAccount
    from paper import runtime_config as rc

    ovr = _base_overrides()
    ovr["PAPER_REJECT_STRONG_BEARISH_CATALYST"] = True
    ovr["PAPER_BEARISH_CATALYST_REJECT_MATERIALITY"] = 0.5

    symbol = "AAPL"
    quality = _quality_passing()
    cats = _catalyst(symbol, "earnings")

    old_account = sim._account
    old_prices = dict(sim._last_prices)
    old_overrides = dict(rc._runtime_overrides)

    sim._account = PaperAccount(1000.0)
    sim._last_prices.clear()
    rc._runtime_overrides.update(ovr)

    bearish_score = {
        **_score_passing(),
        "score_pass": True,
        "catalyst_sentiment": "bearish",
        "catalyst_materiality_score": 0.9,
    }

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [symbol], "active_count": 1,
                                "last_refreshed_at": None, "refresh_reason": "test",
                                "discovery": {"enabled": False, "discovered_count": 0, "errors": []}}),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": cats}}),
            patch("paper.simulator.score_candidate", return_value=bearish_score),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    assert result["entries_made"] == 0
    cand = result["candidates"][0]
    assert cand["rejection_reason"] == "strong_bearish_catalyst"


# ── 11. No marketdata cache or exit logic changes ────────────────────────────

def test_no_marketdata_cache_logic_changes():
    """Verify Phase 2T added no cache-related fields or logic."""
    sim_path = BACKEND_ROOT / "paper" / "simulator.py"
    text = sim_path.read_text()
    # Phase 2T block check is the specific new line; cache logic is unchanged
    assert "catalyst_type_blocked" in text
    assert "PAPER_USE_MARKETDATA_CACHE" in text  # pre-existing, still present

    # Catalyst type guard must not affect exit logic
    exits_path = BACKEND_ROOT / "paper" / "exits.py"
    exits_text = exits_path.read_text()
    assert "catalyst_type_blocked" not in exits_text
    assert "blocked_catalyst" not in exits_text


def test_no_tp_sl_exit_logic_changes():
    """Verify exits.py is unmodified by Phase 2T."""
    exits_path = BACKEND_ROOT / "paper" / "exits.py"
    exits_text = exits_path.read_text()
    assert "fda_regulatory" not in exits_text
    assert "PAPER_BLOCKED_CATALYST" not in exits_text


# ── 12. No broker / live / AI imports ────────────────────────────────────────

def test_simulator_no_broker_or_ai_imports():
    sim_path = BACKEND_ROOT / "paper" / "simulator.py"
    imports = _ast_imports(sim_path)
    for module in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in module.lower(), \
                f"Forbidden module {forbidden!r} found in import: {module!r}"


def test_config_no_broker_or_ai_imports():
    config_path = BACKEND_ROOT / "core" / "config.py"
    imports = _ast_imports(config_path)
    for module in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in module.lower(), \
                f"Forbidden module {forbidden!r} found in import: {module!r}"


def test_runtime_config_no_broker_or_ai_imports():
    rc_path = BACKEND_ROOT / "paper" / "runtime_config.py"
    imports = _ast_imports(rc_path)
    for module in imports:
        for forbidden in FORBIDDEN_MODULES:
            assert forbidden not in module.lower(), \
                f"Forbidden module {forbidden!r} found in import: {module!r}"


def test_simulator_no_live_trading_flag():
    """live_trading_enabled must be hardcoded False in simulator."""
    import paper.simulator as sim
    status = sim.get_status()
    assert status.get("live_trading_enabled") is False
    assert status.get("broker_connected") is False


def test_simulator_mode_is_research_paper():
    import paper.simulator as sim
    status = sim.get_status()
    assert status.get("mode") == "research_paper_simulation"


# ── Phase 2T-H1: multi-catalyst and validation tests ─────────────────────────

def _run_tick_with_cat_list(
    symbol: str,
    cat_type_list: list[str],
    overrides: dict | None = None,
    score_override: dict | None = None,
) -> dict:
    """Run one tick with a symbol and a list of catalyst types. Returns candidate dict."""
    import paper.simulator as sim
    from paper.account import PaperAccount
    from paper import runtime_config as rc

    ovr = overrides if overrides is not None else _base_overrides()
    quality = _quality_passing()
    cats = [{"symbol": symbol, "classified_event_type": ct,
             "title": f"Test {ct}", "sentiment": "bullish"}
            for ct in cat_type_list]
    score = score_override if score_override is not None else _score_passing()

    old_account = sim._account
    old_prices = dict(sim._last_prices)
    old_overrides = dict(rc._runtime_overrides)

    sim._account = PaperAccount(1000.0)
    sim._last_prices.clear()
    rc._runtime_overrides.update(ovr)

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [symbol], "active_count": 1,
                                "last_refreshed_at": None, "refresh_reason": "test",
                                "discovery": {"enabled": False, "discovered_count": 0, "errors": []}}),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": cats}}),
            patch("paper.simulator.score_candidate", return_value=score),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    assert len(result.get("candidates", [])) == 1
    return result["candidates"][0]


# ── H1-1. Multi-catalyst: blocked when fda_regulatory is second ──────────────

def test_multi_cat_earnings_then_fda_blocked():
    cand = _run_tick_with_cat_list("AAPL", ["earnings", "fda_regulatory"])
    assert cand["eligible"] is False
    assert cand.get("catalyst_type_blocked") is True
    assert cand.get("blocked_catalyst_type") == "fda_regulatory"
    assert cand.get("rejection_reason") == "catalyst_type_blocked:fda_regulatory"


def test_multi_cat_m_and_a_then_fda_blocked():
    cand = _run_tick_with_cat_list("AAPL", ["m_and_a", "fda_regulatory"])
    assert cand["eligible"] is False
    assert cand.get("catalyst_type_blocked") is True
    assert cand.get("blocked_catalyst_type") == "fda_regulatory"
    assert cand.get("rejection_reason") == "catalyst_type_blocked:fda_regulatory"


def test_multi_cat_fda_first_then_earnings_blocked():
    cand = _run_tick_with_cat_list("AAPL", ["fda_regulatory", "earnings"])
    assert cand["eligible"] is False
    assert cand.get("catalyst_type_blocked") is True
    assert cand.get("blocked_catalyst_type") == "fda_regulatory"


# ── H1-2. Multi-catalyst: unblocked when none in blocked set ─────────────────

def test_multi_cat_earnings_and_m_and_a_not_blocked():
    cand = _run_tick_with_cat_list("AAPL", ["earnings", "m_and_a"])
    assert cand.get("catalyst_type_blocked") is False
    assert cand.get("blocked_catalyst_type") is None
    assert cand["eligible"] is True


def test_multi_cat_macro_and_sector_news_not_blocked():
    cand = _run_tick_with_cat_list("AAPL", ["macro", "sector_news"])
    assert cand.get("catalyst_type_blocked") is False
    assert cand.get("blocked_catalyst_type") is None


# ── H1-3. blocked_catalyst_type field always present ─────────────────────────

def test_blocked_catalyst_type_field_present_when_blocked():
    cand = _run_tick_for_symbol("AAPL", "fda_regulatory")
    assert "blocked_catalyst_type" in cand
    assert cand["blocked_catalyst_type"] == "fda_regulatory"


def test_blocked_catalyst_type_field_none_when_not_blocked():
    cand = _run_tick_for_symbol("AAPL", "earnings")
    assert "blocked_catalyst_type" in cand
    assert cand["blocked_catalyst_type"] is None


# ── H1-4. Score pass irrelevant when second catalyst is blocked ───────────────

def test_blocked_second_catalyst_score_pass_still_blocked():
    """[earnings, fda_regulatory] — score passes but fda_regulatory is second → blocked."""
    score = {**_score_passing(), "score_pass": True, "total_score": 95}
    cand = _run_tick_with_cat_list("AAPL", ["earnings", "fda_regulatory"],
                                   score_override=score)
    assert cand["eligible"] is False
    assert cand.get("rejection_reason") == "catalyst_type_blocked:fda_regulatory"


# ── H1-5. No-catalyst path cannot bypass blocked second catalyst ──────────────

def test_no_catalyst_cannot_bypass_blocked_second_catalyst():
    """
    cats=[earnings, fda_regulatory], score_pass=False, no-catalyst enabled.
    fda_regulatory appears second; block must still fire, no-catalyst path silent.
    """
    import paper.simulator as sim
    from paper.account import PaperAccount
    from paper import runtime_config as rc

    ovr = _base_overrides()
    ovr["PAPER_NO_CATALYST_ENTRY_ENABLED"] = True
    ovr["PAPER_NO_CATALYST_MIN_SCORE"] = 50
    ovr["PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE"] = 0
    ovr["PAPER_NO_CATALYST_MIN_CHANGE_PERCENT"] = 0.0
    ovr["PAPER_NO_CATALYST_MIN_VOLUME_RATIO"] = 0.0
    ovr["PAPER_NO_CATALYST_MAX_SPREAD_PERCENT"] = 5.0
    ovr["PAPER_NO_CATALYST_REQUIRE_RISK_ON"] = False
    ovr["PAPER_NO_CATALYST_MAX_TRADES_PER_DAY"] = 100
    ovr["PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER"] = 0.5

    symbol = "AAPL"
    quality = _quality_passing()
    cats = [
        {"symbol": symbol, "classified_event_type": "earnings", "title": "Earnings", "sentiment": "bullish"},
        {"symbol": symbol, "classified_event_type": "fda_regulatory", "title": "FDA", "sentiment": "bullish"},
    ]

    old_account = sim._account
    old_prices = dict(sim._last_prices)
    old_overrides = dict(rc._runtime_overrides)
    sim._account = PaperAccount(1000.0)
    sim._last_prices.clear()
    rc._runtime_overrides.update(ovr)

    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [symbol], "active_count": 1,
                                "last_refreshed_at": None, "refresh_reason": "test",
                                "discovery": {"enabled": False, "discovered_count": 0, "errors": []}}),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=quality),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=quality),
            patch("paper.simulator.collect_news_for_symbols", new_callable=AsyncMock,
                  return_value={"filter": {"accepted": cats}}),
            patch("paper.simulator.score_candidate", return_value={
                **_score_passing(), "score_pass": False,
            }),
            patch("paper.simulator._persist_journal_tick", new_callable=AsyncMock,
                  return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        sim._last_prices.clear()
        sim._last_prices.update(old_prices)
        rc._runtime_overrides = old_overrides

    assert result["entries_made"] == 0
    cand = result["candidates"][0]
    assert cand["eligible"] is False
    assert cand.get("rejection_reason") == "catalyst_type_blocked:fda_regulatory"
    assert cand.get("blocked_catalyst_type") == "fda_regulatory"


# ── H1-6. Runtime validation: accepts mixed-case with normalization ───────────

def test_runtime_validation_accepts_mixed_case():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_BLOCKED_CATALYST_TYPES": " FDA_REGULATORY , m_and_a "})
    assert ok, f"Validation failed: {errors}"


def test_runtime_coerce_normalizes_to_lowercase():
    """update_runtime_config must lowercase and strip tokens."""
    import asyncio as _aio
    from unittest.mock import patch as _patch
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        with _patch.object(rc, "_persist_to_db", new=AsyncMock()):
            _aio.run(rc.update_runtime_config(
                {"PAPER_BLOCKED_CATALYST_TYPES": " FDA_REGULATORY , M_AND_A "},
                updated_by="test",
            ))
        stored = rc._runtime_overrides.get("PAPER_BLOCKED_CATALYST_TYPES", "")
        assert stored == "fda_regulatory,m_and_a", f"Expected normalized, got {stored!r}"
    finally:
        rc._runtime_overrides = old


def test_runtime_coerce_deduplicates():
    import asyncio as _aio
    from unittest.mock import patch as _patch
    from paper import runtime_config as rc
    old = dict(rc._runtime_overrides)
    try:
        with _patch.object(rc, "_persist_to_db", new=AsyncMock()):
            _aio.run(rc.update_runtime_config(
                {"PAPER_BLOCKED_CATALYST_TYPES": "fda_regulatory,fda_regulatory,earnings"},
                updated_by="test",
            ))
        stored = rc._runtime_overrides.get("PAPER_BLOCKED_CATALYST_TYPES", "")
        assert stored == "fda_regulatory,earnings", f"Expected deduped, got {stored!r}"
    finally:
        rc._runtime_overrides = old


# ── H1-7. Runtime validation: rejects invalid token characters ───────────────

def test_runtime_rejects_hyphen_in_token():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_BLOCKED_CATALYST_TYPES": "fda-regulatory"})
    assert not ok
    assert any("invalid token" in e.lower() for e in errors)


def test_runtime_rejects_space_inside_token():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_BLOCKED_CATALYST_TYPES": "fda regulatory"})
    assert not ok
    assert any("invalid token" in e.lower() for e in errors)


def test_runtime_rejects_special_chars():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_BLOCKED_CATALYST_TYPES": "fda!regulatory"})
    assert not ok
    assert any("invalid token" in e.lower() for e in errors)


# ── H1-8. Runtime validation: empty string allowed ────────────────────────────

def test_runtime_accepts_empty_string_to_disable():
    from paper.runtime_config import validate_runtime_config
    ok, errors = validate_runtime_config({"PAPER_BLOCKED_CATALYST_TYPES": ""})
    assert ok, f"Empty string should be allowed to disable blocking: {errors}"


# ── H1-9. Frontend: rejection_reason rendered before decision_reason ─────────

def test_frontend_renders_rejection_reason_before_decision_reason():
    """Fix 2: page.tsx must prioritize rejection_reason over decision_reason."""
    frontend_path = BACKEND_ROOT.parent / "frontend" / "dashboard" / "app" / "page.tsx"
    if not frontend_path.exists():
        pytest.skip("frontend not mounted in this build context")
    text = frontend_path.read_text()
    # rejection_reason must appear before decision_reason in the render expression
    idx_rejection = text.find("c.rejection_reason || c.decision_reason")
    idx_wrong = text.find("c.decision_reason || c.rejection_reason")
    assert idx_rejection != -1, "rejection_reason || decision_reason not found in page.tsx"
    assert idx_wrong == -1, "Old decision_reason || rejection_reason order still present"


# ── H1-10. No restore/session integrity logic changes ────────────────────────

def test_no_session_restore_logic_changes():
    """Phase 2T must not touch session_restore.py."""
    restore_path = BACKEND_ROOT / "paper" / "session_restore.py"
    text = restore_path.read_text()
    assert "catalyst_type_blocked" not in text
    assert "blocked_catalyst" not in text
    assert "fda_regulatory" not in text
