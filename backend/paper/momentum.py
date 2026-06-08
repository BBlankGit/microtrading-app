"""
Momentum entry evaluation for the fake-money paper simulator.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. All logic is deterministic rule-based for research purposes only.

Momentum mode is DISABLED by default (PAPER_MOMENTUM_MODE_ENABLED=False).
It provides a second optional entry path for candidates that fail catalyst
gates but meet strict price-momentum, volume, spread, and regime criteria.

Catalyst-mode entries always take priority. Momentum is a fallback only.
"""

from paper.runtime_config import effective_value as _cfg


def evaluate_momentum_entry(
    symbol: str,
    quality: dict,
    regime: dict | None,
) -> dict:
    """
    Evaluate whether a candidate qualifies for momentum-mode entry.

    Called only when:
      - PAPER_MOMENTUM_MODE_ENABLED is True
      - The candidate was rejected from catalyst path for a no-catalyst reason
        (not tradable failures, bearish hard gates, or strong-bearish catalyst)

    Returns a dict with:
      eligible (bool), rejection_reason (str|None), momentum_score (int),
      momentum_score_threshold (int), gate_results (dict),
      positive_reasons (list[str]), negative_reasons (list[str])

    Never raises.
    """
    positive: list[str] = []
    negative: list[str] = []
    gates: dict[str, bool] = {}

    # ── Gate 1: mode enabled ──────────────────────────────────────────────────
    if not _cfg("PAPER_MOMENTUM_MODE_ENABLED"):
        return _rejected("momentum_mode_disabled", gates, positive, negative)

    # ── Gate 2: basic quality (tradable, price movement positive) ─────────────
    tradable = bool(quality.get("tradable"))
    gates["tradable"] = tradable
    if not tradable:
        reasons = quality.get("rejection_reasons", [])
        detail = reasons[0] if reasons else "failed quality gate"
        negative.append(f"not tradable: {detail}")
        return _rejected(f"not tradable: {detail}", gates, positive, negative)

    # ── Gate 3: spread ────────────────────────────────────────────────────────
    spread = quality.get("spread_percent")
    max_spread = _cfg("PAPER_MOMENTUM_MAX_SPREAD_PERCENT")
    spread_ok = spread is not None and spread <= max_spread
    gates["spread_ok"] = spread_ok
    if not spread_ok:
        msg = f"spread {spread}% > max {max_spread}%" if spread is not None else "spread unavailable"
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"tight spread {spread:.3f}%")

    # ── Gate 4: price momentum ────────────────────────────────────────────────
    change_pct = quality.get("change_percent")
    min_change = _cfg("PAPER_MOMENTUM_MIN_CHANGE_PERCENT")
    change_ok = change_pct is not None and change_pct >= min_change
    gates["price_momentum_ok"] = change_ok
    if not change_ok:
        msg = (f"change {change_pct:.2f}% < min {min_change}%"
               if change_pct is not None else "change_percent unavailable")
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"price momentum +{change_pct:.2f}%")

    # ── Gate 5: volume ratio ──────────────────────────────────────────────────
    vol_ratio = quality.get("volume_ratio")
    min_vol = _cfg("PAPER_MOMENTUM_MIN_VOLUME_RATIO")
    vol_ok = vol_ratio is not None and vol_ratio >= min_vol
    gates["volume_ratio_ok"] = vol_ok
    if not vol_ok:
        msg = (f"volume_ratio {vol_ratio:.2f}x < min {min_vol}x"
               if vol_ratio is not None else "volume_ratio unavailable")
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)
    positive.append(f"high volume ratio {vol_ratio:.2f}x")

    # ── Gate 6: market regime ─────────────────────────────────────────────────
    require_risk_on = _cfg("PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON")
    min_risk_score = _cfg("PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE")
    regime_score = None
    regime_name = None
    if regime:
        regime_score = regime.get("risk_on_score")
        regime_name = regime.get("regime")

    if require_risk_on:
        regime_ok = (
            regime_score is not None and regime_score >= min_risk_score
        )
        gates["regime_ok"] = regime_ok
        if not regime_ok:
            actual = regime_score if regime_score is not None else "unknown"
            msg = f"regime score {actual} < min {min_risk_score}"
            negative.append(msg)
            return _rejected(msg, gates, positive, negative)
        positive.append(f"regime risk_on score {regime_score}")
    else:
        gates["regime_ok"] = True

    # ── Score ─────────────────────────────────────────────────────────────────
    score = _compute_momentum_score(spread, change_pct, vol_ratio, regime_score, require_risk_on)
    threshold = _cfg("PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD")
    gates["score_pass"] = score >= threshold

    if score < threshold:
        msg = f"momentum score {score} < threshold {threshold}"
        negative.append(msg)
        return _rejected(msg, gates, positive, negative)

    positive.append(f"momentum score {score} >= {threshold}")

    return {
        "eligible": True,
        "rejection_reason": None,
        "momentum_score": score,
        "momentum_score_threshold": threshold,
        "gate_results": gates,
        "positive_reasons": positive,
        "negative_reasons": negative,
    }


def _compute_momentum_score(
    spread: float | None,
    change_pct: float | None,
    vol_ratio: float | None,
    regime_score: int | None,
    require_risk_on: bool,
) -> int:
    """
    Scoring formula (max 120 before cap, capped 0-100). Threshold 85.

    A candidate just meeting all minimum gates scores exactly 85:
      quality(25) + spread_at_max(5) + change_at_min(20) + vol_at_min(25) + regime_at_min(10) = 85
    """
    total = 0

    # Market quality always passes (gate already checked) → +25
    total += 25

    # Spread (gates ensured spread <= max_spread)
    if spread is not None:
        if spread <= 0.05:
            total += 15
        elif spread <= 0.10:
            total += 10
        elif spread <= 0.15:
            total += 8
        else:
            total += 5  # spread within max gate but not tight

    # Price momentum (gates ensured change_pct >= min_change)
    if change_pct is not None:
        if change_pct >= 4.0:
            total += 30
        elif change_pct >= 2.5:
            total += 25
        else:
            total += 20  # at minimum gate (1.5%)

    # Volume ratio (gates ensured vol_ratio >= min_vol)
    if vol_ratio is not None:
        if vol_ratio >= 5.0:
            total += 35
        elif vol_ratio >= 3.0:
            total += 30
        else:
            total += 25  # at minimum gate (2.0x)

    # Regime bonus (only when required; not penalized when not required)
    if require_risk_on and regime_score is not None:
        if regime_score >= 80:
            total += 15
        elif regime_score >= 70:
            total += 12
        else:
            total += 10  # at minimum gate (60)

    return max(0, min(100, total))


def _rejected(reason: str, gates: dict, positive: list, negative: list) -> dict:
    return {
        "eligible": False,
        "rejection_reason": reason,
        "momentum_score": 0,
        "momentum_score_threshold": _cfg("PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD"),
        "gate_results": gates,
        "positive_reasons": positive,
        "negative_reasons": negative,
    }
