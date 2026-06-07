# Data Sources

## Security Rule

**All API keys must be loaded from environment variables.**
**No secrets, tokens, or credentials may be committed to the repository.**

---

## Phase 1A — Polygon REST (Implemented)

The following Polygon REST endpoints are implemented in `backend/data/polygon_client.py`:

| Endpoint | Backend route | Description |
|---|---|---|
| `GET /v2/snapshot/locale/us/markets/stocks/tickers/{symbol}` | `/api/market/ticker/{symbol}/snapshot` | Real-time snapshot: price, volume, change |
| `GET /v2/aggs/ticker/{symbol}/prev` | `/api/market/ticker/{symbol}/previous-close` | Previous session OHLCV |
| `GET /v2/reference/news?ticker={symbol}` | `/api/market/ticker/{symbol}/news` | Recent news for a ticker |

A diagnostic endpoint is available at `/api/data/status` — it shows whether the Polygon key is configured, using a masked preview only. The full API key is never returned by any endpoint or log.

---

## Phase 1B — Polygon WebSocket (Implemented)

Real-time streaming via Polygon WebSocket is implemented in `backend/data/polygon_ws.py`.

| Channel | Event type | Redis key pattern | Status |
|---|---|---|---|
| `T.{symbol}` | Trade | `stream:latest:{symbol}:trade` | Implemented |
| `Q.{symbol}` | Quote | `stream:latest:{symbol}:quote` | Implemented |
| `AM.{symbol}` | Minute aggregate | `stream:latest:{symbol}:aggregate` | Planned — not currently subscribed |

Phase 1B intentionally subscribes only to trades and quotes. Minute aggregates are normalized by the code but not subscribed by default to avoid plan-tier issues.

**Constraints (Phase 1B):**
- Subscriptions are limited to a fixed test ticker list: AAPL, MSFT, NVDA, TSLA, AMD.
- Full-market streaming is not enabled.
- No trading decisions are made from streaming data. The stream is data-collection only.
- Stream does not start automatically on app boot — it must be started via `POST /api/stream/start`.

Raw WebSocket payloads are normalized by `backend/data/stream_normalizer.py` before storage.
The API key is never logged or returned by any endpoint.

---

## Phase 1E — Catalyst News Collection (Implemented)

Catalyst collection is implemented in `backend/catalysts/news_collector.py` and exposed via:

- `GET /api/catalysts/news/default` — collects news for the default 10-symbol universe (5 articles per symbol)
- `GET /api/catalysts/news/check?symbols=A,B,C&limit=N` — collects news for a custom symbol list (max 25 symbols, max 20 per symbol)

- Uses the Polygon REST news endpoint only (`/v2/reference/news`).
- Does not require WebSocket access.
- Symbols that fail API calls or validation appear in `errors` without stopping the batch.
- Latest result cached in Redis under `catalysts:latest` (TTL 300s, best-effort).

---

## Phase 1D — Tradable Universe Builder (Implemented)

The universe builder is implemented in `backend/data/universe.py` and exposed via:

- `GET /api/universe/default` — evaluates the default 10-symbol universe
- `GET /api/universe/check?symbols=A,B,C` — evaluates a custom symbol list (max 25)

- Uses Polygon REST snapshot and previous-close endpoints only.
- Uses the Phase 1C market quality gate for each symbol.
- Does not require WebSocket access.
- Symbols that fail API calls or validation appear in `errors` without stopping the batch.
- Latest result is cached in Redis under `universe:latest` (TTL 300s, best-effort).

---

## Phase 1C — Market Quality Gate (Implemented)

The market quality gate is implemented in `backend/data/market_quality.py` and exposed via `GET /api/quality/ticker/{symbol}`.

- Uses Polygon REST snapshot and previous-close endpoints only.
- Does not require WebSocket access.
- Evaluates spread, bid/ask validity, last trade price, current volume, and previous-day volume.
- Returns `tradable: true/false` and a list of `rejection_reasons`.
- Does not make buy/sell decisions.

---

## V1 Sources (Full Plan)

| Source | Type | Status |
|---|---|---|
| **Polygon REST API** | Market data | Implemented (Phase 1A) |
| **Polygon WebSocket API** | Real-time streaming | Implemented (Phase 1B) |
| **Polygon news endpoint** | Catalyst | Implemented (Phase 1A) |

---

## V2+ Sources

| Source | Type | Description |
|---|---|---|
| **SEC EDGAR filings** | Catalyst | Regulatory filings: 8-K, S-1, Form 4 insider transactions |
| **Insider transaction datasets** | Catalyst | Structured insider buy/sell records |
| **Reddit / social connectors** | Catalyst | Social sentiment from relevant communities |
| **Broker paper-trading API** | Execution | Simulated order management (paper only) |

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `POLYGON_API_KEY` | Polygon.io REST and WebSocket authentication |
| `OPENAI_API_KEY` | OpenAI API for AI/NLP catalyst interpretation (optional in Phase 0) |

All variables are defined in `.env.example`.
Copy to `.env` and populate before running the stack.
Never commit `.env`.
