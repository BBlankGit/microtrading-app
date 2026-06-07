"""
Rule-based catalyst sentiment and materiality analysis.

No broker. No live trading. No real orders. No AI/LLM calls.
All analysis is deterministic rule-based logic for research purposes only.
sentiment_method = "rules_v1"
"""

from typing import Any

# ---------------------------------------------------------------------------
# Bullish phrases: (phrase, weight)
# weight = approximate materiality level (0.4–0.9)
# Matched against lowercased combined title + description.
# ---------------------------------------------------------------------------

_BULLISH_PHRASES: list[tuple[str, float]] = [
    # High materiality (0.9)
    ("fda approval", 0.9),
    ("fda approved", 0.9),
    ("regulatory approval", 0.9),
    ("receives approval", 0.9),
    ("approved by fda", 0.9),
    ("receives fda", 0.9),
    ("raises guidance", 0.9),
    ("raises its guidance", 0.9),
    ("raises outlook", 0.9),
    ("raises its outlook", 0.9),
    ("increases forecast", 0.9),
    ("raises forecast", 0.9),
    ("raises full-year", 0.9),
    ("raises full year", 0.9),
    ("beats estimates", 0.9),
    ("beats expectations", 0.9),
    ("beat estimates", 0.9),
    ("beat expectations", 0.9),
    ("revenue beat", 0.9),
    ("eps beat", 0.9),
    ("profit beat", 0.9),
    ("record revenue", 0.9),
    ("record earnings", 0.9),
    ("record profit", 0.9),
    ("acquisition by", 0.9),
    ("buyout offer", 0.9),
    ("merger agreement", 0.9),
    ("to be acquired", 0.9),
    ("acquired by", 0.9),
    ("takeover bid", 0.9),
    ("takeover offer", 0.9),
    ("going-private", 0.9),
    # Medium materiality (0.7)
    ("contract award", 0.7),
    ("wins contract", 0.7),
    ("awarded contract", 0.7),
    ("government contract", 0.7),
    ("defense contract", 0.7),
    ("multi-year contract", 0.7),
    ("strategic partnership", 0.7),
    ("partnership agreement", 0.7),
    ("joint venture", 0.7),
    ("collaboration agreement", 0.7),
    ("upgraded to buy", 0.7),
    ("upgraded to outperform", 0.7),
    ("upgraded to strong buy", 0.7),
    ("upgrade to buy", 0.7),
    ("upgrade to outperform", 0.7),
    ("price target raised", 0.7),
    ("price target increased", 0.7),
    ("raises price target", 0.7),
    ("increases price target", 0.7),
    ("target raised", 0.7),
    ("target increased", 0.7),
    ("initiates with buy", 0.7),
    ("initiates coverage with buy", 0.7),
    ("strong buy", 0.7),
    # Lower materiality (0.5)
    ("strong demand", 0.5),
    ("signs contract", 0.5),
    ("signs agreement", 0.5),
    ("launches product", 0.5),
    ("product launch", 0.5),
    ("new product", 0.5),
    ("expands partnership", 0.5),
    ("expands into", 0.5),
    ("new platform", 0.5),
    ("new model", 0.5),
    # Mild bullish (0.4)
    ("secures funding", 0.4),
    ("funding round", 0.4),
    ("raises capital", 0.4),
]

# ---------------------------------------------------------------------------
# Bearish phrases: (phrase, weight)
# ---------------------------------------------------------------------------

_BEARISH_PHRASES: list[tuple[str, float]] = [
    # High materiality (0.9)
    ("fda rejection", 0.9),
    ("fda rejected", 0.9),
    ("fda denied", 0.9),
    ("complete response letter", 0.9),
    ("clinical hold", 0.9),
    ("lowers guidance", 0.9),
    ("cuts guidance", 0.9),
    ("reduces guidance", 0.9),
    ("reduces outlook", 0.9),
    ("lowers outlook", 0.9),
    ("lowers its guidance", 0.9),
    ("cuts its guidance", 0.9),
    ("misses estimates", 0.9),
    ("misses expectations", 0.9),
    ("miss estimates", 0.9),
    ("miss expectations", 0.9),
    ("revenue miss", 0.9),
    ("eps miss", 0.9),
    ("wider loss", 0.9),
    ("bankruptcy", 0.9),
    ("going concern", 0.9),
    ("chapter 11", 0.9),
    ("delisting", 0.9),
    ("delisted", 0.9),
    # Medium materiality (0.7)
    ("public offering", 0.7),
    ("stock offering", 0.7),
    ("secondary offering", 0.7),
    ("follow-on offering", 0.7),
    ("registered direct offering", 0.7),
    ("registered direct", 0.7),
    ("at-the-market offering", 0.7),
    ("at-the-market", 0.7),
    ("atm offering", 0.7),
    ("shelf offering", 0.7),
    ("private placement", 0.7),
    ("dilution", 0.7),
    ("dilutive", 0.7),
    ("ceo resigns", 0.7),
    ("ceo resigned", 0.7),
    ("cfo resigns", 0.7),
    ("cfo resigned", 0.7),
    ("steps down as ceo", 0.7),
    ("downgraded to sell", 0.7),
    ("downgraded to underperform", 0.7),
    ("downgraded to underweight", 0.7),
    ("downgrade to sell", 0.7),
    ("downgrade to underperform", 0.7),
    ("price target cut", 0.7),
    ("price target reduced", 0.7),
    ("price target lowered", 0.7),
    ("cuts price target", 0.7),
    ("lowers price target", 0.7),
    ("reduces price target", 0.7),
    ("sec investigation", 0.7),
    ("sec charges", 0.7),
    ("class action", 0.7),
    ("subpoena", 0.7),
    # Lower materiality (0.5)
    ("investigation", 0.5),
    ("lawsuit", 0.5),
    ("weak demand", 0.5),
    ("product recall", 0.5),
    ("recall notice", 0.5),
    ("downgrade", 0.5),
    ("downgraded", 0.5),
]

# ---------------------------------------------------------------------------
# Sentinel phrases for offering/financing event types (when no phrase matched)
# Used only when classified_event_type is "offering" and no bearish phrase hit.
# ---------------------------------------------------------------------------

_OFFERING_EVENT_SENTINEL = ("stock_offering_event_type", 0.6)


def _build_text(catalyst: dict) -> str:
    """Combine title + description into lowercased text."""
    parts: list[str] = []
    for field in ("title", "description"):
        v = catalyst.get(field)
        if v:
            parts.append(str(v))
    return " ".join(parts).lower()


def _match_phrases(
    text: str, phrase_list: list[tuple[str, float]]
) -> list[tuple[str, float]]:
    """Return (phrase, weight) pairs for all matching phrases."""
    return [(phrase, weight) for phrase, weight in phrase_list if phrase in text]


def _event_type_materiality_default(event_type: str) -> float:
    """Fallback materiality when no strong phrase matched."""
    _DEFAULTS = {
        "fda_regulatory": 0.5,
        "earnings": 0.4,
        "guidance": 0.5,
        "analyst_rating": 0.4,
        "m_and_a": 0.5,
        "offering": 0.5,
        "contract_award": 0.4,
        "partnership": 0.3,
        "product_launch": 0.3,
        "management_change": 0.3,
        "financing": 0.3,
        "legal_regulatory": 0.4,
        "insider_transaction": 0.2,
        "macro": 0.2,
        "sector_news": 0.1,
        "generic_news": 0.1,
    }
    return _DEFAULTS.get(event_type, 0.1)


def analyze_catalyst_sentiment(catalyst: dict) -> dict[str, Any]:
    """
    Analyze a normalized catalyst dict for directional sentiment and materiality.

    Returns:
        sentiment: bullish | bearish | mixed | neutral | unknown
        sentiment_score: -1.0 to 1.0  (positive = bullish, negative = bearish)
        materiality_score: 0.0 to 1.0 (strength/importance of the catalyst)
        sentiment_method: "rules_v1"
        sentiment_reasons: list[str]
        bearish_flags: list[str]
        bullish_flags: list[str]

    No AI. No ML. No LLM. Deterministic rule-based only. Research use only.
    No broker. No live trading. No real orders.
    """
    text = _build_text(catalyst)
    event_type: str = (
        catalyst.get("classified_event_type")
        or catalyst.get("event_type")
        or ""
    )

    bullish_matches = _match_phrases(text, _BULLISH_PHRASES)
    bearish_matches = _match_phrases(text, _BEARISH_PHRASES)

    # Event-type prior: offering with no bearish phrase match → add sentinel
    if event_type == "offering" and not bearish_matches:
        bearish_matches = [_OFFERING_EVENT_SENTINEL]

    bull_max = max((w for _, w in bullish_matches), default=0.0)
    bear_max = max((w for _, w in bearish_matches), default=0.0)

    # Sum contributions capped at 1.0 per side (prevent pile-up)
    bull_sum = min(sum(w for _, w in bullish_matches), 1.0)
    bear_sum = min(sum(w for _, w in bearish_matches), 1.0)

    # Sentiment score: net bullish, clamped [-1, 1]
    net = bull_sum - bear_sum
    sentiment_score = round(max(-1.0, min(1.0, net)), 3)

    # Materiality: highest single-signal strength
    materiality = max(bull_max, bear_max)
    if materiality < 0.3:
        materiality = max(materiality, _event_type_materiality_default(event_type))
    materiality = round(materiality, 3)

    # Collect flag lists
    bullish_flags = [phrase for phrase, _ in bullish_matches]
    # Exclude the internal sentinel from public bearish_flags
    bearish_flags = [
        phrase for phrase, _ in bearish_matches
        if phrase != _OFFERING_EVENT_SENTINEL[0]
    ]

    # Sentiment label and reasons
    sentiment_reasons: list[str] = []

    if bull_max >= 0.4 and bear_max >= 0.4:
        sentiment = "mixed"
        top_bull = max(bullish_matches, key=lambda x: x[1])
        top_bear = max(bearish_matches, key=lambda x: x[1])
        sentiment_reasons.append(
            f"Both bullish and bearish signals present: "
            f"'{top_bull[0]}' vs '{top_bear[0]}'"
        )
    elif bull_max >= 0.4:
        sentiment = "bullish"
        top = max(bullish_matches, key=lambda x: x[1])
        sentiment_reasons.append(f"Bullish signal: '{top[0]}'")
    elif bear_max >= 0.4:
        sentiment = "bearish"
        top = max(bearish_matches, key=lambda x: x[1])
        # Exclude sentinel from reason text
        phrase_label = (
            f"offering event type prior"
            if top[0] == _OFFERING_EVENT_SENTINEL[0]
            else f"'{top[0]}'"
        )
        sentiment_reasons.append(f"Bearish signal: {phrase_label}")
    elif bull_max > 0 or bear_max > 0:
        sentiment = "neutral"
        sentiment_reasons.append("Weak directional signals only")
    else:
        sentiment = "unknown"
        sentiment_reasons.append("No directional sentiment rule matched")

    return {
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "materiality_score": materiality,
        "sentiment_method": "rules_v1",
        "sentiment_reasons": sentiment_reasons,
        "bearish_flags": bearish_flags,
        "bullish_flags": bullish_flags,
    }
