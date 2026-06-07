# Catalyst Intelligence

## Purpose

The catalyst layer collects and normalizes external information that may
explain or anticipate short-term price movement in U.S. equities.

A catalyst is any external event or signal that, when combined with
market confirmation, may justify evaluating a trade opportunity.

Catalysts are scored, not acted upon directly. The engine and risk manager
make the final decision.

---

## Initial Sources (V1)

| Source | Description |
|---|---|
| **Polygon news** | Real-time and recent news articles tied to specific tickers via the Polygon news endpoint |
| **SEC filings** | Regulatory filings (8-K, S-1, etc.) that may indicate material events |
| **Insider transaction context** | Form 4 filings; large insider buys or sells as contextual signals |

---

## Planned Sources (V2+)

| Source | Description |
|---|---|
| Reddit / social sentiment | Unusual activity on relevant subreddits or social platforms |
| Earnings calendars | Pre/post earnings setups and surprise potential |
| Analyst upgrades / downgrades | Rating changes from major institutions |
| FDA / regulatory calendars | Approval dates, PDUFA dates, and binary event tracking |
| Unusual options activity | Large or unusual options flow as a directional signal |

---

## Output Requirements

All catalyst records produced by this layer must be **normalized structured records** containing at minimum:

- `ticker` — the affected equity symbol
- `source` — origin of the information
- `event_type` — classification (news, filing, insider, earnings, etc.)
- `headline` or `summary` — brief description of the event
- `raw_text` — original source text (where available)
- `collected_at` — UTC timestamp of collection
- `relevance_score` — initial relevance signal (0.0–1.0)

Downstream AI and scoring modules consume these records.
Raw or unstructured data must not pass through to the engine.
