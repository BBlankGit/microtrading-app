# Catalyst Intelligence

## Purpose

The catalyst layer collects and normalizes external information that may
explain or anticipate short-term price movement in U.S. equities.

A catalyst is any external event or signal that, when combined with
market confirmation, may justify evaluating a trade opportunity.

Catalysts are scored, not acted upon directly. The engine and risk manager
make the final decision.

---

## Phase 1E — Polygon News Collection (Implemented)

Polygon news collection is implemented in `backend/catalysts/news_collector.py`.

- News articles are fetched from the Polygon REST news endpoint for a configured list of symbols.
- Each article is normalized into a structured catalyst record by `backend/catalysts/schemas.py`.
- Catalyst records include: `catalyst_id`, `symbol`, `source`, `event_type`, `title`, `description`, `publisher`, `author`, `article_url`, `published_utc`, `collected_at`, `tickers`, `keywords`, and `raw_relevance_hint`.
- No AI interpretation is applied at this stage.
- No catalyst score is computed.
- No trading action is taken or recommended.
- Latest result is cached in Redis under `catalysts:latest` (TTL 300s, best-effort).

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
