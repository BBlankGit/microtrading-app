from typing import Any

# ---------------------------------------------------------------------------
# Priority-ordered rule table.
# Each entry: (event_type, confidence_tier, keyword_sets)
# keyword_sets is a list of frozensets; a rule matches if ALL tokens in ANY
# one frozenset appear in the combined text (title + description + keywords).
# Earlier rules in the list take priority over later ones when multiple match.
# ---------------------------------------------------------------------------

_CONFIDENCE = {"high": 0.80, "medium": 0.60, "low": 0.40}

_RULES: list[tuple[str, str, list[frozenset[str]]]] = [
    # --- FDA / clinical / regulatory (beats generic legal) ---
    ("fda_regulatory", "high", [
        frozenset(["fda"]),
        frozenset(["pdufa"]),
        frozenset(["nda"]),
        frozenset(["bla"]),
        frozenset(["clinical trial"]),
        frozenset(["phase 1"]),
        frozenset(["phase 2"]),
        frozenset(["phase 3"]),
        frozenset(["fda approval"]),
        frozenset(["fda clearance"]),
    ]),

    # --- Earnings / quarterly results ---
    ("earnings", "high", [
        frozenset(["quarterly results"]),
        frozenset(["q1 results"]),
        frozenset(["q2 results"]),
        frozenset(["q3 results"]),
        frozenset(["q4 results"]),
        frozenset(["fiscal year results"]),
        frozenset(["beats earnings"]),
        frozenset(["misses earnings"]),
        frozenset(["reports earnings"]),
        frozenset(["earnings per share"]),
        frozenset(["earnings", "eps"]),
        frozenset(["earnings", "revenue"]),
    ]),

    # --- Forward guidance ---
    ("guidance", "high", [
        frozenset(["raises guidance"]),
        frozenset(["lowers guidance"]),
        frozenset(["raises outlook"]),
        frozenset(["lowers outlook"]),
        frozenset(["full-year outlook"]),
        frozenset(["full year outlook"]),
        frozenset(["guidance", "outlook"]),
        frozenset(["guidance", "forecast"]),
    ]),

    # --- Analyst ratings ---
    ("analyst_rating", "high", [
        frozenset(["price target"]),
        frozenset(["upgraded to"]),
        frozenset(["downgraded to"]),
        frozenset(["initiates coverage"]),
        frozenset(["overweight"]),
        frozenset(["underweight"]),
        frozenset(["buy rating"]),
        frozenset(["sell rating"]),
        frozenset(["analyst", "upgrade"]),
        frozenset(["analyst", "downgrade"]),
        frozenset(["analyst", "rating"]),
    ]),

    # --- M&A ---
    ("m_and_a", "high", [
        frozenset(["acquisition"]),
        frozenset(["merger"]),
        frozenset(["acquire"]),
        frozenset(["acquired by"]),
        frozenset(["takeover"]),
        frozenset(["buyout"]),
        frozenset(["to acquire"]),
        frozenset(["deal to buy"]),
    ]),

    # --- Public / private offerings ---
    ("offering", "high", [
        frozenset(["public offering"]),
        frozenset(["private placement"]),
        frozenset(["registered direct"]),
        frozenset(["shelf offering"]),
        frozenset(["atm offering"]),
        frozenset(["at-the-market"]),
        frozenset(["secondary offering"]),
        frozenset(["follow-on offering"]),
    ]),

    # --- Debt / financing ---
    ("financing", "high", [
        frozenset(["credit facility"]),
        frozenset(["debt facility"]),
        frozenset(["term loan"]),
        frozenset(["revolving credit"]),
        frozenset(["financing", "loan"]),
        frozenset(["financing", "debt"]),
        frozenset(["funding round"]),
        frozenset(["raises capital"]),
    ]),

    # --- Contract / government awards ---
    ("contract_award", "high", [
        frozenset(["contract award"]),
        frozenset(["awarded contract"]),
        frozenset(["purchase order"]),
        frozenset(["selected by", "contract"]),
        frozenset(["wins contract"]),
        frozenset(["government contract"]),
        frozenset(["defense contract"]),
    ]),

    # --- Product launches ---
    ("product_launch", "high", [
        frozenset(["product launch"]),
        frozenset(["launches new"]),
        frozenset(["unveils new"]),
        frozenset(["announces new product"]),
        frozenset(["product release"]),
        frozenset(["new model"]),
        frozenset(["new platform"]),
    ]),

    # --- Partnerships / alliances ---
    ("partnership", "high", [
        frozenset(["strategic alliance"]),
        frozenset(["strategic partnership"]),
        frozenset(["partnership agreement"]),
        frozenset(["partners with"]),
        frozenset(["collaboration agreement"]),
        frozenset(["joint venture"]),
    ]),

    # --- Management changes ---
    ("management_change", "medium", [
        frozenset(["appoints ceo"]),
        frozenset(["appoints cfo"]),
        frozenset(["ceo resigns"]),
        frozenset(["cfo resigns"]),
        frozenset(["steps down"]),
        frozenset(["board of directors", "appoints"]),
        frozenset(["names new ceo"]),
        frozenset(["names new cfo"]),
        frozenset(["executive change"]),
        frozenset(["management change"]),
    ]),

    # --- Insider transactions ---
    ("insider_transaction", "medium", [
        frozenset(["insider buying"]),
        frozenset(["insider selling"]),
        frozenset(["form 4"]),
        frozenset(["director bought"]),
        frozenset(["ceo bought"]),
        frozenset(["insider", "transaction"]),
        frozenset(["insider", "purchase"]),
    ]),

    # --- Legal / regulatory (lower priority than fda_regulatory) ---
    ("legal_regulatory", "medium", [
        frozenset(["lawsuit"]),
        frozenset(["class action"]),
        frozenset(["sec charges"]),
        frozenset(["subpoena"]),
        frozenset(["investigation"]),
        frozenset(["settlement"]),
        frozenset(["regulatory compliance"]),
        frozenset(["regulatory violation"]),
    ]),

    # --- Macro indicators ---
    ("macro", "medium", [
        frozenset(["federal reserve"]),
        frozenset(["interest rates"]),
        frozenset(["inflation"]),
        frozenset(["cpi"]),
        frozenset(["jobs report"]),
        frozenset(["treasury yield"]),
        frozenset(["fed funds"]),
        frozenset(["rate hike"]),
        frozenset(["rate cut"]),
    ]),

    # --- Sector-level commentary ---
    ("sector_news", "low", [
        frozenset(["chip stocks"]),
        frozenset(["ai stocks"]),
        frozenset(["ev stocks"]),
        frozenset(["bank stocks"]),
        frozenset(["energy stocks"]),
        frozenset(["sector outlook"]),
        frozenset(["industry outlook"]),
        frozenset(["sector", "rotation"]),
    ]),
]

_FALLBACK_EVENT = "generic_news"
_FALLBACK_CONFIDENCE = "low"


def _build_text(catalyst: dict) -> str:
    parts: list[str] = []
    for field in ("title", "description"):
        v = catalyst.get(field)
        if v:
            parts.append(str(v))
    kw = catalyst.get("keywords")
    if isinstance(kw, list):
        parts.append(" ".join(str(k) for k in kw))
    return " ".join(parts).lower()


def classify_catalyst_event(catalyst: dict) -> dict:
    """
    Classify a single normalized catalyst record by event type.

    Adds fields: classified_event_type, event_confidence, matched_rules,
    classification_method.  Never modifies the original dict.
    No AI, no sentiment, no trade recommendation.
    """
    text = _build_text(catalyst)

    matched_event: str = _FALLBACK_EVENT
    matched_confidence: str = _FALLBACK_CONFIDENCE
    matched_rules: list[str] = []

    for event_type, confidence, keyword_sets in _RULES:
        hits: list[str] = []
        for kset in keyword_sets:
            if all(token in text for token in kset):
                hits.append(" + ".join(sorted(kset)))
        if hits:
            matched_event = event_type
            matched_confidence = confidence
            matched_rules = hits
            break  # first match wins (highest priority)

    return {
        **catalyst,
        "classified_event_type": matched_event,
        "event_confidence": _CONFIDENCE[matched_confidence],
        "matched_rules": matched_rules,
        "classification_method": "rules_v1",
    }


def classify_catalysts(catalysts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Classify a list of normalized catalyst records.

    Returns a summary dict with classified records and a type breakdown.
    """
    classified = [classify_catalyst_event(c) for c in catalysts]

    breakdown: dict[str, int] = {}
    for c in classified:
        evt = c["classified_event_type"]
        breakdown[evt] = breakdown.get(evt, 0) + 1

    return {
        "total_classified": len(classified),
        "event_type_breakdown": breakdown,
        "catalysts": classified,
    }
