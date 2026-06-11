"""
Transparent candidate scoring for the fake-money paper simulator.

No broker. No live trading. No real orders. No AI/LLM calls.
All scoring is deterministic rule-based logic for research purposes only.
"""

from typing import Any

from core.config import settings
from paper.runtime_config import effective_value as _cfg

# Catalyst event types that carry full catalyst_score weight
_HIGH_VALUE_EVENT_TYPES = frozenset({
    "earnings",
    "guidance",
    "analyst_rating",
    "contract_award",
    "partnership",
    "product_launch",
    "fda_regulatory",
    "m_and_a",
})

# Catalyst event types that carry partial catalyst_score weight
_MID_VALUE_EVENT_TYPES = frozenset({
    "management_change",
    "financing",
    "legal_regulatory",
    "sector_news",
})


def score_candidate(
    symbol: str,
    quality: dict,
    catalysts: list[dict],
    earnings_info: dict[str, Any] | None = None,
    insider_info: dict[str, Any] | None = None,
) -> dict:
    """
    Score a candidate ticker for paper simulator entry evaluation.

    Returns a transparent scoring dict with components, reasons, and
    a pass/fail decision against the configured threshold.

    Phase I6 adds optional earnings_info / insider_info inputs that produce
    transparent score adjustments applied on top of the base 0..100 score.
    Both are no-ops when None or when their respective enabled flags are
    false, so this is safe to call without intelligence wiring.

    No buy/sell recommendation. No AI. No broker. Research-only.
    """
    positive_reasons: list[str] = []
    negative_reasons: list[str] = []

    # ── A. Market quality score (max 25) ──────────────────────────────────────
    tradable = quality.get("tradable", False)
    if tradable:
        market_quality_score = 25
        positive_reasons.append("tradable: passed quality gate")
    else:
        market_quality_score = 0
        reasons = quality.get("rejection_reasons", [])
        detail = reasons[0] if reasons else "failed quality gate"
        negative_reasons.append(f"not tradable: {detail}")

    # ── B. Spread score (max 15) ──────────────────────────────────────────────
    spread = quality.get("spread_percent")
    if spread is None:
        spread_score = 0
        negative_reasons.append("spread unavailable")
    elif spread <= 0.05:
        spread_score = 15
        positive_reasons.append(f"tight spread {spread:.3f}%")
    elif spread <= 0.15:
        spread_score = 10
        positive_reasons.append(f"good spread {spread:.3f}%")
    elif spread <= 0.30:
        spread_score = 5
        positive_reasons.append(f"acceptable spread {spread:.3f}%")
    else:
        spread_score = 0
        negative_reasons.append(f"wide spread {spread:.3f}%")

    # ── C. Momentum score (max 20) ────────────────────────────────────────────
    change_pct = quality.get("change_percent")
    if change_pct is None:
        momentum_score = 0
        negative_reasons.append("change_percent unavailable")
    elif change_pct >= 2.0:
        momentum_score = 20
        positive_reasons.append(f"strong momentum +{change_pct:.2f}%")
    elif change_pct >= 1.0:
        momentum_score = 15
        positive_reasons.append(f"good momentum +{change_pct:.2f}%")
    elif change_pct > 0:
        momentum_score = 10
        positive_reasons.append(f"positive momentum +{change_pct:.2f}%")
    else:
        momentum_score = 0
        negative_reasons.append(f"non-positive change {change_pct:.2f}%")

    # ── D. Volume score (max 15) ──────────────────────────────────────────────
    vol_ratio = quality.get("volume_ratio")
    if vol_ratio is None:
        volume_score = 0
    elif vol_ratio >= 1.5:
        volume_score = 15
        positive_reasons.append(f"high volume ratio {vol_ratio:.2f}x")
    elif vol_ratio >= 1.0:
        volume_score = 10
        positive_reasons.append(f"normal volume ratio {vol_ratio:.2f}x")
    elif vol_ratio >= 0.8:
        volume_score = 5
        positive_reasons.append(f"acceptable volume ratio {vol_ratio:.2f}x")
    else:
        volume_score = 0
        negative_reasons.append(f"low volume ratio {vol_ratio:.2f}x")

    # ── E. Catalyst score (max 20) ────────────────────────────────────────────
    catalyst_sentiment: str | None = None
    catalyst_sentiment_score: float | None = None
    catalyst_materiality_score: float | None = None
    catalyst_sentiment_reasons: list[str] = []
    bullish_flags: list[str] = []
    bearish_flags: list[str] = []
    strongest_catalyst_title: str | None = None
    strongest_catalyst_sentiment: str | None = None
    bearish_catalyst_penalty = 0

    if not catalysts:
        catalyst_score = 0
        negative_reasons.append("no accepted catalysts")
    else:
        best = max(
            catalysts,
            key=lambda c: (
                c.get("materiality_score") or 0.0,
                abs(c.get("sentiment_score") or 0.0),
            ),
        )
        if best.get("sentiment"):
            sentiment = best.get("sentiment", "unknown")
            materiality = best.get("materiality_score") or 0.0
            ss = best.get("sentiment_score") or 0.0

            catalyst_sentiment = sentiment
            catalyst_sentiment_score = ss
            catalyst_materiality_score = materiality
            catalyst_sentiment_reasons = best.get("sentiment_reasons") or []
            bullish_flags = best.get("bullish_flags") or []
            bearish_flags = best.get("bearish_flags") or []
            strongest_catalyst_title = best.get("title")
            strongest_catalyst_sentiment = sentiment

            if sentiment == "bullish":
                if materiality >= 0.7:
                    catalyst_score = 20
                elif materiality >= 0.4:
                    catalyst_score = 16
                else:
                    catalyst_score = 10
                positive_reasons.append(
                    f"bullish catalyst (materiality {materiality:.2f})"
                )
            elif sentiment == "mixed":
                if materiality >= 0.7:
                    catalyst_score = 12
                elif materiality >= 0.4:
                    catalyst_score = 10
                else:
                    catalyst_score = 8
                reason = (
                    catalyst_sentiment_reasons[0]
                    if catalyst_sentiment_reasons
                    else "conflicting signals"
                )
                negative_reasons.append(f"Mixed catalyst sentiment: {reason}")
            elif sentiment in ("neutral", "unknown"):
                catalyst_score = 5
                negative_reasons.append("Weak/unknown catalyst sentiment")
            elif sentiment == "bearish":
                catalyst_score = 0
                bearish_catalyst_penalty = -15
                label = bearish_flags[0] if bearish_flags else "bearish signal"
                negative_reasons.append(f"Bearish catalyst: {label}")
            else:
                catalyst_score = 5
        else:
            # Fallback: event-type based scoring (no sentiment fields present)
            event_types = {c.get("classified_event_type") for c in catalysts}
            if event_types & _HIGH_VALUE_EVENT_TYPES:
                catalyst_score = 20
                matched = sorted(event_types & _HIGH_VALUE_EVENT_TYPES)
                positive_reasons.append(f"high-value catalyst: {matched[0]}")
            elif event_types & _MID_VALUE_EVENT_TYPES:
                catalyst_score = 12
                matched = sorted(event_types & _MID_VALUE_EVENT_TYPES)
                positive_reasons.append(f"mid-value catalyst: {matched[0]}")
            else:
                catalyst_score = 5
                negative_reasons.append("only generic_news catalysts")

    # ── F. Risk penalty (min -20) ─────────────────────────────────────────────
    risk_penalty = 0
    if spread is not None and spread > 0.50:
        risk_penalty -= 10
        negative_reasons.append(f"spread risk: {spread:.3f}% > 0.50%")
    if change_pct is not None and change_pct < 0:
        risk_penalty -= 10
        negative_reasons.append(f"price declining: {change_pct:.2f}%")
    if not tradable:
        risk_penalty -= 10
    if vol_ratio is not None and vol_ratio < 0.8:
        risk_penalty -= 5
        negative_reasons.append(f"volume risk: ratio {vol_ratio:.2f}x < 0.8")
    risk_penalty += bearish_catalyst_penalty
    risk_penalty = max(risk_penalty, -20)

    # ── Base score (before intelligence adjustments) ──────────────────────────
    raw_base = (
        market_quality_score
        + spread_score
        + momentum_score
        + volume_score
        + catalyst_score
        + risk_penalty
    )
    base_score_before_intelligence_adjustments = max(0, min(100, raw_base))

    # ── G. Earnings proximity (Phase I6) ──────────────────────────────────────
    earnings_adj = 0
    earnings_blocked = False
    earnings_next_date = None
    earnings_days_until = None
    earnings_reason = "earnings scoring disabled"
    earnings_scoring_enabled = False
    if earnings_info is not None:
        earnings_scoring_enabled = bool(earnings_info.get("enabled"))
        earnings_adj = int(earnings_info.get("earnings_score_adjustment") or 0)
        earnings_blocked = bool(earnings_info.get("earnings_blocked"))
        earnings_next_date = earnings_info.get("earnings_next_date")
        earnings_days_until = earnings_info.get("earnings_days_until")
        earnings_reason = earnings_info.get("earnings_reason") or earnings_reason
        if earnings_adj < 0:
            negative_reasons.append(f"earnings adj {earnings_adj}: {earnings_reason}")

    # ── H. Insider activity (Phase I6) ────────────────────────────────────────
    insider_adj = 0
    insider_reason = "insider scoring disabled"
    insider_recent_buy_count = 0
    insider_recent_buy_value = 0.0
    insider_latest_transaction_date = None
    insider_transaction_codes: list[str] = []
    insider_scoring_enabled = False
    if insider_info is not None:
        insider_scoring_enabled = bool(insider_info.get("enabled"))
        insider_adj = int(insider_info.get("insider_score_adjustment") or 0)
        insider_reason = insider_info.get("insider_reason") or insider_reason
        insider_recent_buy_count = int(insider_info.get("insider_recent_buy_count") or 0)
        insider_recent_buy_value = float(insider_info.get("insider_recent_buy_value") or 0.0)
        insider_latest_transaction_date = insider_info.get("insider_latest_transaction_date")
        insider_transaction_codes = list(insider_info.get("insider_transaction_codes") or [])
        if insider_adj > 0:
            positive_reasons.append(f"insider adj +{insider_adj}: {insider_reason}")
        elif insider_adj < 0:
            negative_reasons.append(f"insider adj {insider_adj}: {insider_reason}")

    intelligence_score_adjustment = earnings_adj + insider_adj
    final_score_after_intelligence_adjustments = max(
        0,
        min(100, base_score_before_intelligence_adjustments + intelligence_score_adjustment),
    )

    # ── Total score (final, after adjustments) ────────────────────────────────
    total_score = final_score_after_intelligence_adjustments

    threshold = _cfg("PAPER_ENTRY_SCORE_THRESHOLD")
    score_pass = total_score >= threshold and not earnings_blocked

    if earnings_blocked:
        decision_reason = (
            f"score {total_score} hard-blocked by earnings proximity: {earnings_reason}"
        )
    elif score_pass:
        decision_reason = f"score {total_score} >= threshold {threshold}"
    else:
        top_negative = negative_reasons[0] if negative_reasons else "low composite score"
        decision_reason = f"score {total_score} < threshold {threshold}: {top_negative}"

    return {
        "symbol": symbol,
        "total_score": total_score,
        "score_threshold": threshold,
        "score_pass": score_pass,
        "components": {
            "market_quality_score": market_quality_score,
            "spread_score": spread_score,
            "momentum_score": momentum_score,
            "volume_score": volume_score,
            "catalyst_score": catalyst_score,
            "risk_penalty": risk_penalty,
        },
        "positive_reasons": positive_reasons,
        "negative_reasons": negative_reasons,
        "decision_reason": decision_reason,
        "catalyst_sentiment": catalyst_sentiment,
        "catalyst_sentiment_score": catalyst_sentiment_score,
        "catalyst_materiality_score": catalyst_materiality_score,
        "catalyst_sentiment_reasons": catalyst_sentiment_reasons,
        "bullish_flags": bullish_flags,
        "bearish_flags": bearish_flags,
        "strongest_catalyst_title": strongest_catalyst_title,
        "strongest_catalyst_sentiment": strongest_catalyst_sentiment,
        # Phase I6: transparent intelligence adjustments
        "base_score_before_intelligence_adjustments": base_score_before_intelligence_adjustments,
        "intelligence_score_adjustment": intelligence_score_adjustment,
        "final_score_after_intelligence_adjustments": final_score_after_intelligence_adjustments,
        "earnings_scoring_enabled": earnings_scoring_enabled,
        "earnings_next_date": earnings_next_date,
        "earnings_days_until": earnings_days_until,
        "earnings_score_adjustment": earnings_adj,
        "earnings_reason": earnings_reason,
        "earnings_blocked": earnings_blocked,
        "insider_scoring_enabled": insider_scoring_enabled,
        "insider_recent_buy_count": insider_recent_buy_count,
        "insider_recent_buy_value": insider_recent_buy_value,
        "insider_score_adjustment": insider_adj,
        "insider_reason": insider_reason,
        "insider_latest_transaction_date": insider_latest_transaction_date,
        "insider_transaction_codes": insider_transaction_codes,
    }
