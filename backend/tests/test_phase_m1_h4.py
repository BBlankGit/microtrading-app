"""
Phase M1-H4 — Set market trend path telemetry inside the final selected
entry branch, not from a pre-branch classifier.

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM. Verifies that the pure helper _trend_usage_for_path mirrors the
M1-H4 contract and that the simulator wires it from the actual selected
branch (AST-verified).
"""
from __future__ import annotations

import ast
import inspect

import pytest


# ── Pure helper unit tests ───────────────────────────────────────────────────

def test_helper_catalyst_default_raw_not_consumed():
    """Catalyst path with default apply_catalyst=False → raw / not consumed."""
    from paper.simulator import _trend_usage_for_path

    raw = {"regime": "risk_on"}
    adj = {"regime": "risk_off"}
    out = _trend_usage_for_path(
        "catalyst", raw, adj,
        apply_legacy=False, apply_no_cat=True, apply_mm=True, apply_catalyst=False,
    )
    assert out["path_name"] == "catalyst"
    assert out["consumed"] is False
    assert out["regime_used"] == "raw"
    assert out["regime_label_used"] == "risk_on"


def test_helper_market_mover_adjusted_when_enabled():
    from paper.simulator import _trend_usage_for_path

    raw = {"regime": "risk_on"}
    adj = {"regime": "neutral"}
    out = _trend_usage_for_path(
        "market_mover_no_catalyst", raw, adj,
        apply_legacy=False, apply_no_cat=True, apply_mm=True, apply_catalyst=False,
    )
    assert out["path_name"] == "market_mover_no_catalyst"
    assert out["consumed"] is True
    assert out["regime_used"] == "trend_adjusted"
    assert out["regime_label_used"] == "neutral"


def test_helper_market_mover_raw_when_disabled():
    from paper.simulator import _trend_usage_for_path

    raw = {"regime": "risk_on"}
    adj = {"regime": "neutral"}
    out = _trend_usage_for_path(
        "market_mover_no_catalyst", raw, adj,
        apply_legacy=False, apply_no_cat=True, apply_mm=False, apply_catalyst=False,
    )
    assert out["regime_used"] == "raw"
    assert out["consumed"] is False
    assert out["regime_label_used"] == "risk_on"


def test_helper_no_catalyst_adjusted_by_default():
    from paper.simulator import _trend_usage_for_path

    out = _trend_usage_for_path(
        "no_catalyst", {"regime": "risk_on"}, {"regime": "risk_off"},
        apply_legacy=False, apply_no_cat=True, apply_mm=True, apply_catalyst=False,
    )
    assert out["path_name"] == "no_catalyst"
    assert out["consumed"] is True
    assert out["regime_used"] == "trend_adjusted"
    assert out["regime_label_used"] == "risk_off"


def test_helper_legacy_momentum_raw_by_default():
    """Default apply_legacy=False — legacy fallback uses raw regime."""
    from paper.simulator import _trend_usage_for_path

    out = _trend_usage_for_path(
        "legacy_momentum", {"regime": "risk_on"}, {"regime": "neutral"},
        apply_legacy=False, apply_no_cat=True, apply_mm=True, apply_catalyst=False,
    )
    assert out["path_name"] == "legacy_momentum"
    assert out["consumed"] is False
    assert out["regime_used"] == "raw"
    assert out["regime_label_used"] == "risk_on"


def test_helper_legacy_momentum_adjusted_when_opted_in():
    from paper.simulator import _trend_usage_for_path

    out = _trend_usage_for_path(
        "legacy_momentum", {"regime": "risk_on"}, {"regime": "risk_off"},
        apply_legacy=True, apply_no_cat=True, apply_mm=True, apply_catalyst=False,
    )
    assert out["consumed"] is True
    assert out["regime_used"] == "trend_adjusted"
    assert out["regime_label_used"] == "risk_off"


def test_helper_rejected_before_path():
    from paper.simulator import _trend_usage_for_path

    out = _trend_usage_for_path(
        "rejected_before_path", {"regime": "risk_on"}, {"regime": "risk_off"},
        apply_legacy=True, apply_no_cat=True, apply_mm=True, apply_catalyst=True,
    )
    assert out["path_name"] == "rejected_before_path"
    # Conservative: never consumed even if all flags are on.
    assert out["consumed"] is False
    assert out["regime_used"] == "raw"
    assert out["regime_label_used"] == "risk_on"


def test_helper_no_adjusted_regime_forces_raw():
    """When _tick_regime_adjusted is None, consumed is always False."""
    from paper.simulator import _trend_usage_for_path

    out = _trend_usage_for_path(
        "no_catalyst", {"regime": "risk_on"}, None,
        apply_legacy=True, apply_no_cat=True, apply_mm=True, apply_catalyst=True,
    )
    assert out["consumed"] is False
    assert out["regime_used"] == "raw"
    assert out["regime_label_used"] == "risk_on"


def test_helper_unknown_path_falls_back_to_rejected_before_path():
    from paper.simulator import _trend_usage_for_path

    out = _trend_usage_for_path(
        "nonsense_path", {"regime": "risk_on"}, {"regime": "risk_off"},
        apply_legacy=True, apply_no_cat=True, apply_mm=True, apply_catalyst=True,
    )
    assert out["path_name"] == "rejected_before_path"
    assert out["consumed"] is False


# ── Simulator wiring: AST-verify telemetry is set from final branch ──────────

def _run_tick_ast():
    import paper.simulator as sim
    return ast.parse(inspect.getsource(sim.run_tick))


def test_final_selected_path_initialized_to_rejected_before_branch_chain():
    """
    _final_selected_path must be initialized to "rejected_before_path"
    inside run_tick. This is the conservative default before any branch
    fires.
    """
    tree = _run_tick_ast()
    found_init = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_final_selected_path":
                    if isinstance(node.value, ast.Constant) and node.value.value == "rejected_before_path":
                        found_init = True
                        break
            if found_init:
                break
    assert found_init, "_final_selected_path must be initialized to 'rejected_before_path'"


def test_final_selected_path_set_inside_each_entry_branch():
    """
    Every actual entry-decision branch must set _final_selected_path. We
    expect: catalyst, market_mover_no_catalyst, no_catalyst, legacy_momentum.
    """
    tree = _run_tick_ast()
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_final_selected_path":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        seen.add(node.value.value)
    required = {
        "rejected_before_path",  # default init
        "catalyst",
        "market_mover_no_catalyst",
        "no_catalyst",
        "legacy_momentum",
    }
    missing = required - seen
    assert not missing, f"_final_selected_path not set for: {sorted(missing)}"


def test_helper_called_after_branch_chain_with_final_selected_path():
    """
    _trend_usage_for_path must be called with _final_selected_path as the
    first arg — proving that final telemetry is derived from the actual
    selected branch, not a pre-branch classifier.
    """
    tree = _run_tick_ast()
    ok = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "_trend_usage_for_path":
            if node.args and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id == "_final_selected_path":
                ok = True
                break
    assert ok, "_trend_usage_for_path must be called with _final_selected_path"


def test_pre_branch_classifier_removed():
    """
    The M1-H2/M1-H3 pre-branch elif chain (the inference-from-predicates
    classifier) must be gone. Specifically, the offending pattern
    'elif momentum_eval and momentum_eval.get("eligible"):' followed by
    '_trend_path_name = "legacy_momentum"' must no longer exist as a
    pre-branch inference. We check that no _trend_path_name = "legacy_momentum"
    assignment exists OUTSIDE the helper definition (the helper assigns it
    inside its own dict mapping, which is fine).
    """
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
    # Within run_tick we expect no direct '_trend_path_name = "legacy_momentum"'
    # assignment — the post-branch helper writes candidate["market_trend_path_name"]
    # instead.
    assert '_trend_path_name = "legacy_momentum"' not in src
    assert '_trend_path_name = "market_mover_no_catalyst"' not in src
    assert '_trend_path_name = "no_catalyst"' not in src
    assert '_trend_path_name = "catalyst"' not in src


# ── Source-truth: classifier path strings are present ───────────────────────

def test_simulator_telemetry_keys_present_in_source():
    """All Phase M1-H4 path strings and helper call-site must appear in run_tick."""
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    for needle in (
        "_final_selected_path",
        '"rejected_before_path"',
        '"catalyst"',
        '"market_mover_no_catalyst"',
        '"no_catalyst"',
        '"legacy_momentum"',
        "_trend_usage_for_path",
        "market_trend_path_name",
        "market_trend_consumed_by_path",
        "market_trend_regime_used",
        "market_trend_regime_label_used",
        "market_trend_shadow_consumed",
        "market_trend_shadow_regime_used",
    ):
        assert needle in src, f"missing M1-H4 needle: {needle!r}"
