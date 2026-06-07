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

## Polygon WebSocket — Planned (Phase 1B)

Real-time streaming via Polygon WebSocket is **not yet implemented**.
It is planned for Phase 1B to support live quote and trade streaming.

---

## V1 Sources (Full Plan)

| Source | Type | Status |
|---|---|---|
| **Polygon REST API** | Market data | Implemented (Phase 1A) |
| **Polygon WebSocket API** | Real-time streaming | Planned (Phase 1B) |
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
