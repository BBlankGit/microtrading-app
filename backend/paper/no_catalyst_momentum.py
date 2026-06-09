"""
No-catalyst momentum entry evaluation for the fake-money paper simulator.
Phase 2R.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All logic is deterministic rule-based for research purposes only.

No-catalyst mode is DISABLED by default (PAPER_NO_CATALYST_ENTRY_ENABLED=False).
It provides a strictly-gated second entry path for candidates where no accepted
catalyst is present but price momentum, volume, spread, regime, and composite
scoring criteria are all met.

Entry path priority:
  Path A (catalyst) → Path C (no-catalyst, Phase 2R) → Path B (momentum, Phase 2M)
"""

from __future__ import annotations

from paper.runtime_config import effective_value as _cfg


def evaluate_no_catalyst_entry(
    symbol: str,
    quality: dict,
    scoring: dict,
    regime: dict | None,
) -> dict:
    """
    Evaluate whether a candidate qualifies for the no-catalyst momentum entry path.

    Called only when is_no_catalyst_rejection=True (candidate rejected from the
    catalyst path because no accepted catalysts or only generic_news catalysts were
    present).

    Returns a dict with:
      eligible (bool), rejection_reason (str|None), gate_results (dict),
      config_snapshot (dict|None), positive_reasons (list[str]),
      negative_reasons (list[str])

    Never raises.
    """
    positive: list[str] = []
    negative: list[str] = []
    gates: dict[str, bool] = {}

    # ── Gate 1: feature enabled ───────────────────────────────────────────────
    if not _cfg("PAPER_NO_CATALYST_ENTRY_ENABLED"):
        return _rejected("no_catalyst_entry_disabled", gates, positive, negative)

    # ── Gate 2: bearish catalyst block ────────────────────────────────────────
    if _cfg("PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH"):
        if scoring.get("catalyst_sentiment") == "bearish":
            return _rejected("bearish_catalyst_present", gates, positive, negative)
    gates["no_bearish_block"] = True

    # ── Gate 3: overall composite score ──────────────────────────────────────
    total_score = scoring.get("total_score", 0)
    min_score = _cfg("PAPER_NO_CATALYST_MIN_SCORE")
    score_ok = total_score >= min_score
    gates["score_ok"] = score_ok
    if not score_ok:
        msg = f"score {total_score} < min {min_score}"
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"score {total_score} >= {min_score}")

    # ── Gate 4: momentum_score component ─────────────────────────────────────
    momentum_component = (scoring.get("components") or {}).get("momentum_score", 0)
    min_momentum = _cfg("PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE")
    momentum_ok = momentum_component >= min_momentum
    gates["momentum_component_ok"] = momentum_ok
    if not momentum_ok:
        msg = f"momentum_score component {momentum_component} < min {min_momentum}"
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"momentum component {momentum_component} >= {min_momentum}")

    # ── Gate 5: price change percent ──────────────────────────────────────────
    change_pct = quality.get("change_percent")
    min_change = _cfg("PAPER_NO_CATALYST_MIN_CHANGE_PERCENT")
    change_ok = change_pct is not None and change_pct >= min_change
    gates["change_ok"] = change_ok
    if not change_ok:
        msg = (
            f"change_percent {change_pct:.2f}% < min {min_change}%"
            if change_pct is not None else "change_percent unavailable"
        )
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"price change +{change_pct:.2f}%")

    # ── Gate 6: volume ratio ──────────────────────────────────────────────────
    vol_ratio = quality.get("volume_ratio")
    min_vol = _cfg("PAPER_NO_CATALYST_MIN_VOLUME_RATIO")
    vol_ok = vol_ratio is not None and vol_ratio >= min_vol
    gates["volume_ok"] = vol_ok
    if not vol_ok:
        msg = (
            f"volume_ratio {vol_ratio:.2f}x < min {min_vol}x"
            if vol_ratio is not None else "volume_ratio unavailable"
        )
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"volume ratio {vol_ratio:.2f}x")

    # ── Gate 7: spread ────────────────────────────────────────────────────────
    spread = quality.get("spread_percent")
    max_spread = _cfg("PAPER_NO_CATALYST_MAX_SPREAD_PERCENT")
    spread_ok = spread is not None and spread <= max_spread
    gates["spread_ok"] = spread_ok
    if not spread_ok:
        msg = (
            f"spread {spread:.3f}% > max {max_spread}%"
            if spread is not None else "spread unavailable"
        )
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"spread {spread:.3f}%")

    # ── Gate 8: market regime ─────────────────────────────────────────────────
    require_risk_on = _cfg("PAPER_NO_CATALYST_REQUIRE_RISK_ON")
    min_risk_score = _cfg("PAPER_NO_CATALYST_MIN_RISK_SCORE")
    regime_score = None
    if regime:
        regime_score = regime.get("risk_on_score")

    if require_risk_on:
        regime_ok = regime_score is not None and regime_score >= min_risk_score
        gates["regime_ok"] = regime_ok
        if not regime_ok:
            actual = regime_score if regime_score is not None else "unknown"
            msg = f"regime score {actual} < min {min_risk_score}"
            negative.append(msg)
            return _rejected(msg, gates, positive, negative)
        positive.append(f"regime risk_on score {regime_score}")
    else:
        gates["regime_ok"] = True

    config_snapshot = {
        "enabled": True,
        "block_if_any_bearish": _cfg("PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH"),
        "min_score": min_score,
        "min_momentum_score": min_momentum,
        "min_change_percent": min_change,
        "min_volume_ratio": min_vol,
        "max_spread_percent": max_spread,
        "require_risk_on": require_risk_on,
        "min_risk_score": min_risk_score if require_risk_on else None,
        "position_size_multiplier": _cfg("PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER"),
        "max_trades_per_day": _cfg("PAPER_NO_CATALYST_MAX_TRADES_PER_DAY"),
    }

    return {
        "eligible": True,
        "rejection_reason": None,
        "gate_results": gates,
        "config_snapshot": config_snapshot,
        "positive_reasons": positive,
        "negative_reasons": negative,
    }


def _rejected(reason: str, gates: dict, positive: list, negative: list) -> dict:
    return {
        "eligible": False,
        "rejection_reason": reason,
        "gate_results": gates,
        "config_snapshot": None,
        "positive_reasons": positive,
        "negative_reasons": negative,
    }
