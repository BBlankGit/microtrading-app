# Data Sources

## Security Rule

**All API keys must be loaded from environment variables.**
**No secrets, tokens, or credentials may be committed to the repository.**

---

## V1 Sources

| Source | Type | Description |
|---|---|---|
| **Polygon REST API** | Market data | OHLCV bars, snapshots, ticker details, reference data |
| **Polygon WebSocket API** | Real-time | Streaming trades, quotes, and aggregate bars |
| **Polygon news endpoint** | Catalyst | News articles associated with specific tickers |

Polygon API key is loaded from `POLYGON_API_KEY` environment variable.

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
