# AI Layer

## Role

The AI layer interprets external information collected by the catalyst layer.
It reads normalized catalyst records and produces structured scoring objects
that the engine uses when evaluating trade opportunities.

**The AI layer does not place trades.**
**The AI layer does not generate orders.**
**The AI layer does not communicate with any broker.**

---

## Output Schema

Every AI interpretation must produce a JSON-compatible object with the following fields:

```json
{
  "ticker": "string — equity symbol",
  "event_type": "string — news | filing | insider | earnings | social | options | other",
  "sentiment": "string — bullish | bearish | neutral",
  "sentiment_score": "float — -1.0 (strongly bearish) to 1.0 (strongly bullish)",
  "urgency_score": "float — 0.0 (low) to 1.0 (high urgency)",
  "confidence_score": "float — 0.0 (low) to 1.0 (high confidence in interpretation)",
  "expected_impact_window": "string — e.g. '1h', '4h', 'intraday', 'multi-day'",
  "summary": "string — one or two sentence plain-language summary of the catalyst",
  "positive_factors": ["list of strings — factors supporting a bullish view"],
  "negative_factors": ["list of strings — factors supporting a bearish view or risk"],
  "risk_flags": ["list of strings — any concerns that may invalidate the signal"],
  "recommended_action": "string — evaluate | monitor | ignore"
}
```

---

## Recommended Action Values

| Value | Meaning |
|---|---|
| `evaluate` | Engine should assess this opportunity against its entry criteria |
| `monitor` | Signal is noted but not yet actionable; continue watching |
| `ignore` | Signal does not meet minimum quality or relevance threshold |

---

## Constraint

AI may recommend that the engine **evaluate** an opportunity.
AI may **not** recommend **direct order execution**.

The recommended_action field must never contain order instructions such as
"buy", "sell", "short", or "enter position". Those decisions belong
exclusively to the engine and risk manager.
