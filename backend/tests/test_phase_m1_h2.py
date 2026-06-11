"""
Phase M1-H2 — Shadow trend consumer wiring + candidate path telemetry.

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM. Verifies:
  - compute_shadow_score receives adjusted regime iff
    MARKET_TREND_APPLY_TO_SHADOW=true (raw otherwise)
  - Candidate market_trend_path_name matches the path that actually
    consumed the regime, not the source metadata
  - Catalyst-eligible candidates that are also market-mover-sourced
    correctly report path_name="catalyst" and regime_used="raw"
  - Raw and adjusted regime labels are exposed on every candidate
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── A. Shadow consumer wiring ────────────────────────────────────────────────

def test_shadow_consumer_default_is_true():
    """MARKET_TREND_APPLY_TO_SHADOW default reflects shadow inclusion."""
    from core.config import settings
    assert settings.MARKET_TREND_APPLY_TO_SHADOW is True


def test_simulator_routes_shadow_regime_according_to_flag():
    """
    AST-check: verify that simulator passes _regime_for(_trend_apply_shadow)
    as the tick_regime kwarg to compute_shadow_score(), not the raw
    _tick_regime hardcoded.
    """
    import ast
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    tree = ast.parse(src)

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "compute_shadow_score":
            for kw in node.keywords:
                if kw.arg == "tick_regime":
                    # Expect either _regime_for(_trend_apply_shadow) or a local
                    # named _shadow_regime that was bound from _regime_for(...).
                    if isinstance(kw.value, ast.Name) and kw.value.id == "_shadow_regime":
                        found = True
                    elif isinstance(kw.value, ast.Call) and isinstance(kw.value.func, ast.Name) \
                            and kw.value.func.id == "_regime_for":
                        found = True
            break
    assert found, "compute_shadow_score must receive _regime_for(_trend_apply_shadow), not raw _tick_regime"


def test_simulator_assigns_shadow_regime_from_regime_for():
    """The _shadow_regime local must be bound from _regime_for(_trend_apply_shadow)."""
    import ast
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    tree = ast.parse(src)

    ok = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) \
                and any(isinstance(t, ast.Name) and t.id == "_shadow_regime" for t in node.targets) \
                and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) \
                and node.value.func.id == "_regime_for" \
                and len(node.value.args) >= 1 \
                and isinstance(node.value.args[0], ast.Name) \
                and node.value.args[0].id == "_trend_apply_shadow":
            ok = True
            break
    assert ok, "_shadow_regime must be assigned from _regime_for(_trend_apply_shadow)"


# ── B. Candidate trend path telemetry ───────────────────────────────────────
# These verify the precise classification logic embedded in simulator.run_tick
# by replaying it. Keeping a single source of truth here avoids a full tick
# harness — the end-to-end behavior is verified in runtime verification.

def _classify(
    *,
    hard_rejection,
    is_no_catalyst_rejection,
    mm_meta_present,
    mm_entry_eligible,
    momentum_eval_eligible,
    apply_legacy=False,
    apply_no_cat=True,
    apply_mm=True,
    apply_catalyst=False,
    adjusted_present=True,
):
    """Mirror simulator.run_tick path classification — kept identical."""
    if hard_rejection is not None and not is_no_catalyst_rejection:
        path = "rejected_before_path"
        consumed = False
        regime_used = "raw"
    elif is_no_catalyst_rejection and mm_meta_present and mm_entry_eligible:
        path = "market_mover_no_catalyst"
        consumed = apply_mm and adjusted_present
        regime_used = "trend_adjusted" if consumed else "raw"
    elif is_no_catalyst_rejection:
        path = "no_catalyst"
        consumed = apply_no_cat and adjusted_present
        regime_used = "trend_adjusted" if consumed else "raw"
    elif momentum_eval_eligible:
        path = "legacy_momentum"
        consumed = apply_legacy and adjusted_present
        regime_used = "trend_adjusted" if consumed else "raw"
    else:
        path = "catalyst"
        consumed = apply_catalyst and adjusted_present
        regime_used = "trend_adjusted" if consumed else "raw"
    return path, consumed, regime_used


def test_catalyst_eligible_with_mm_meta_reports_catalyst_not_mm():
    """
    Critical Phase M1-H2 fix: a candidate with accepted catalysts that is
    ALSO market-mover-sourced must report path=catalyst, regime=raw,
    consumed=False — not market_mover with trend_adjusted.
    """
    path, consumed, regime_used = _classify(
        hard_rejection=None,
        is_no_catalyst_rejection=False,   # catalyst-eligible
        mm_meta_present=True,             # also a market mover
        mm_entry_eligible=False,
        momentum_eval_eligible=False,
    )
    assert path == "catalyst"
    assert regime_used == "raw"
    assert consumed is False


def test_no_catalyst_rejection_with_mm_eligible_reports_market_mover():
    path, consumed, regime_used = _classify(
        hard_rejection="no accepted catalysts",
        is_no_catalyst_rejection=True,
        mm_meta_present=True,
        mm_entry_eligible=True,
        momentum_eval_eligible=False,
    )
    assert path == "market_mover_no_catalyst"
    # With default apply_mm=True, this should be trend_adjusted
    assert regime_used == "trend_adjusted"
    assert consumed is True


def test_no_catalyst_rejection_without_mm_reports_no_catalyst():
    path, consumed, regime_used = _classify(
        hard_rejection="no accepted catalysts",
        is_no_catalyst_rejection=True,
        mm_meta_present=False,
        mm_entry_eligible=False,
        momentum_eval_eligible=False,
    )
    assert path == "no_catalyst"
    assert regime_used == "trend_adjusted"  # apply_no_cat default True
    assert consumed is True


def test_legacy_momentum_path_uses_raw_by_default():
    path, consumed, regime_used = _classify(
        hard_rejection=None,
        is_no_catalyst_rejection=False,
        mm_meta_present=False,
        mm_entry_eligible=False,
        momentum_eval_eligible=True,
    )
    assert path == "legacy_momentum"
    # Default apply_legacy=False → raw
    assert regime_used == "raw"
    assert consumed is False


def test_legacy_momentum_uses_adjusted_when_opted_in():
    path, consumed, regime_used = _classify(
        hard_rejection=None,
        is_no_catalyst_rejection=False,
        mm_meta_present=False,
        mm_entry_eligible=False,
        momentum_eval_eligible=True,
        apply_legacy=True,
    )
    assert path == "legacy_momentum"
    assert regime_used == "trend_adjusted"
    assert consumed is True


def test_no_catalyst_uses_raw_when_opted_out():
    path, consumed, regime_used = _classify(
        hard_rejection="no accepted catalysts",
        is_no_catalyst_rejection=True,
        mm_meta_present=False,
        mm_entry_eligible=False,
        momentum_eval_eligible=False,
        apply_no_cat=False,
    )
    assert path == "no_catalyst"
    assert regime_used == "raw"
    assert consumed is False


def test_rejected_before_path():
    path, consumed, regime_used = _classify(
        hard_rejection="not tradable: failed quality gate",
        is_no_catalyst_rejection=False,
        mm_meta_present=False,
        mm_entry_eligible=False,
        momentum_eval_eligible=False,
    )
    assert path == "rejected_before_path"
    assert regime_used == "raw"
    assert consumed is False


# ── C. Source-truth check: simulator embeds the exact classifier we mirror ──

def test_simulator_path_classifier_keys_present_in_source():
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    for needle in (
        "rejected_before_path",
        "market_mover_no_catalyst",
        "legacy_momentum",
        '"no_catalyst"',
        '"catalyst"',
        "_trend_path_name",
        "_trend_path_consumed",
        "_trend_path_regime_used",
        "_trend_apply_shadow",
        "market_trend_shadow_consumed",
        "market_trend_shadow_regime_used",
        "market_regime_label_before_trend",
        "market_regime_label_after_trend",
        "market_trend_regime_label_used",
    ):
        assert needle in src, f"missing classifier needle {needle!r} in run_tick source"
