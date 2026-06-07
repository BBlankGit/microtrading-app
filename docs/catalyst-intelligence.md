# Catalyst Intelligence

## Purpose

The catalyst layer collects and normalizes external information that may
explain or anticipate short-term price movement in U.S. equities.

A catalyst is any external event or signal that, when combined with
market confirmation, may justify evaluating a trade opportunity.

Catalysts are scored, not acted upon directly. The engine and risk manager
make the final decision.

---

## Phase 1G — Catalyst Event-Type Classifier (Implemented)

Deterministic event-type classification is implemented in `backend/catalysts/event_classifier.py`.

Classification operates on normalized catalyst records (Phase 1E) and is compatible with filtered results (Phase 1F). It is opt-in via `?classify_events=true`.

Each classified record gains:
- `classified_event_type` — one of the supported types below
- `event_confidence` — `0.80` (high), `0.60` (medium), or `0.40` (low / generic)
- `matched_rules` — list of keyword strings that triggered the classification
- `classification_method` — `"rules_v1"`

**Supported event types** (priority order — first match wins):

| Event type | Examples |
|---|---|
| `fda_regulatory` | FDA approval, PDUFA, NDA, BLA, clinical trial |
| `earnings` | Quarterly results, EPS, beats/misses earnings |
| `guidance` | Raises/lowers guidance, full-year outlook, forecast |
| `analyst_rating` | Price target, upgraded/downgraded, overweight/underweight |
| `m_and_a` | Acquisition, merger, takeover, buyout |
| `offering` | Public offering, private placement, ATM, registered direct |
| `financing` | Credit facility, debt facility, funding round |
| `contract_award` | Contract award, purchase order, government/defense contract |
| `product_launch` | Launches new product, unveils, product release |
| `partnership` | Strategic alliance, partnership agreement, joint venture |
| `management_change` | CEO/CFO appoints or resigns, board appointment |
| `insider_transaction` | Form 4, insider buying/selling, director/CEO purchase |
| `legal_regulatory` | Lawsuit, class action, SEC charges, investigation, settlement |
| `macro` | Federal Reserve, interest rates, CPI, jobs report |
| `sector_news` | Chip stocks, AI stocks, sector/industry outlook |
| `generic_news` | No rule matched — fallback |

- No AI interpretation.
- No sentiment scoring.
- No trading action.

---

## Phase 1F — Catalyst Filtering Layer (Implemented)

Deterministic catalyst filtering is implemented in `backend/catalysts/filters.py`.

Filter rules applied in order:
1. **Deduplication** — reject second+ occurrences of the same `catalyst_id`.
2. **Title** — reject if `title` is missing or empty.
3. **Published timestamp** — reject if `published_utc` is missing or unparseable.
4. **Freshness** — reject if age exceeds `max_age_hours` (default 24h).
5. **Relevance hint** — reject if `raw_relevance_hint` is not `"direct"`.

Accepted records gain: `freshness_age_hours` (float, 2dp) and `filter_status = "accepted"`.

Filtering is opt-in via `?apply_filter=true`. `max_age_hours` is configurable (1–168h).

- No AI interpretation.
- No sentiment scoring.
- No trading action.

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

- `symbol` — the affected equity symbol
- `source` — origin of the information
- `event_type` — classification (news, filing, insider, earnings, etc.)
- `title` — headline of the event
- `description` — extended summary (where available)
- `collected_at` — UTC timestamp of collection
- `raw_relevance_hint` — initial relevance signal (`"direct"` or `"related"`)

Downstream AI and scoring modules consume these records.
Raw or unstructured data must not pass through to the engine.
