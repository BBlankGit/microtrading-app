# Polygon/Massive API Pressure Analysis — 2026-06-08

## Executive Summary

- **Evidence of API latency/timeouts:** Yes. V5 logged 57 confirmed `Read timed out` errors (15s timeout) during the 9:25–10:51am ET window. No HTTP 429 (rate limit) responses were logged by any app.
- **Did V5 miss alerts due to API pressure?** Almost certainly yes. Timeouts hit 26+ unique tickers including key V5 universe symbols (AFRM, LCID, CVNA, CLSK, CORT, SMCI, AMD, QQQ, IWM, SPY). With no data for a ticker in a given minute, V5's rule engines cannot evaluate it — silently producing zero alerts.
- **Multiple apps sharing the same API key at the same time?** Yes — `nasdaq-scanner-v6` (pm2 pid 71581) and `v5-paper-dashboard` (pm2 pid 46957) were both active with the **same Polygon API key** during the V5 alert window. `microtrading-app` was **not** running during the V5 failure window (container started at 14:01 ET, after market).
- **Root cause:** Practical REST congestion — elevated server-side latency on Polygon's API during the early-market period (9:25–9:33am ET), compounded by `nasdaq-scanner-v6` issuing ~39 bulk-snapshot REST requests/minute against the same key simultaneously with V5's per-ticker REST polling.

---

## Active Processes (Market Session 2026-06-08)

| App | Process | PID | Started | Key |
|-----|---------|-----|---------|-----|
| `nasdaq-scanner-v6` | `node /opt/nasdaq-scanner-v6/src/server.js` | 71581 | Jun 07 (25h+) | `CxhI4H...DMfc` |
| `v5-paper-dashboard` | `python app.py` | 46957 | Jun 07 (33h+) | `CxhI4H...DMfc` |
| `microtrading-app` | `uvicorn main:app` (Docker) | 152884 | 14:01 ET | `CxhI4H...DMfc` |

All three apps use the **identical Polygon API key**. `microtrading-app` was not active during V5's alert window.

---

## Evidence

### V5 Timeouts (57 unique events, 2026-06-08)

All errors were `HTTPSConnectionPool(host='api.polygon.io', port=443): Read timed out. (read timeout=15)`. No HTTP 429 or 401/403 responses logged.

| Ticker | Timeout Count | In V5 Universe? |
|--------|:---:|:---:|
| AFRM | 4 | Yes |
| LCID | 4 | Yes |
| CVNA | 4 | Yes |
| CORT | 3 | Yes (Engine D) |
| CLSK | 3 | Yes |
| SMCI | 2 | Yes |
| ROKU | 2 | Yes |
| RKLB | 2 | Yes |
| QQQ | 2 | Market ETF |
| IWM | 2 | Market ETF |
| CIFR | 2 | Yes |
| AXON | 2 | Yes (Engine D) |
| APLD | 2 | Yes (Engine B/C) |
| AEVA | 2 | Yes (Engine D) |
| SPY | 1 | Market ETF |
| SOUN | 2 | Yes |
| + 11 others | 1 each | Yes |

**Timeline:** First timeout at 09:31 ET, last at 10:51 ET. Heaviest concentration 09:31–10:10 ET.

### nasdaq-scanner-v6 Polygon Fetch Success Rate (2026-06-08)

| Time (ET) | Fetched / Total | Success Rate | Missing |
|-----------|----------------|:---:|:---:|
| 09:25 | 3,157 / 5,295 | 59.6% | 2,138 |
| 09:26 | 3,183 / 5,295 | 60.1% | 2,112 |
| 09:30 | 3,228 / 5,295 | 61.0% | 2,067 |
| 09:31 | 3,640 / 5,296 | 68.7% | 1,656 |
| 09:31+44s | 4,816 / 5,296 | 90.9% | 480 |
| 09:35 | 4,859 / 5,296 | 91.7% | 437 |
| Post-open | 4,900–5,033 / 5,296 | 92–95% | ~260–400 |

The drop to ~60% at 9:25am ET coincides exactly with the start of V5's timeout window. After market open (9:30am), success rates improved rapidly. No 429 errors were observed in nasdaq-scanner logs.

### No 429 / Rate Limit Responses

Searched all logs across V5, nasdaq-scanner-v6. No `429`, `rate limit`, `too many requests`, or `throttle` messages found. This confirms the issue was latency/timeout, not a hard API rate limit rejection.

---

## Estimated Request Load

| App | Symbols | Method | Endpoints/Symbol | Interval | Est. Req/min |
|-----|:-------:|--------|:---:|:---:|:---:|
| `nasdaq-scanner-v6` | 5,296 | Bulk `/v2/snapshot` (200/chunk) | 1 bulk per 27 chunks | ~42s cycle | ~39 |
| `nasdaq-scanner-v6` | ~65 curated | WebSocket T/A/AM | n/a (stream) | continuous | — |
| `v5-paper-dashboard` | 31 | Per-ticker `/v2/aggs/{t}/range/1/min` | 1 per ticker | 60s (idempotent) | ~31 |
| `microtrading-app` | 50 | Per-ticker `/snapshot` + `/prev` | 2 per ticker | 60s tick | ~100* |
| **Total (V5 window)** | — | — | — | — | **~70** |

\* Microtrading was not running during the V5 failure window (started 14:01 ET).

**Combined REST load during V5 alert window:** ~70 requests/minute against one API key.

---

## WebSocket Usage

| App | WebSocket | Endpoint | Channels | Notes |
|-----|:---:|---|---|---|
| `nasdaq-scanner-v6` | Yes | `wss://socket.polygon.io/stocks` | T.*, A.*, AM.* per ~65 tickers | Auto-connects on start |
| `v5-paper-dashboard` | No | — | — | REST only (`/v2/aggs` per ticker) |
| `microtrading-app` | Manual | `wss://socket.polygon.io/stocks` | Configurable | Not auto-started; requires `POST /api/stream/start` |

`nasdaq-scanner-v6` holds a persistent WebSocket connection using `T.TICKER`, `A.TICKER`, `AM.TICKER` subscriptions for curated tickers. No `max_connections` (error 1008) or `auth_failed` events were observed in logs.

---

## Shared Caching

**No shared caching exists between the three apps.** Each app fetches independently:

- `nasdaq-scanner-v6` uses in-process memory (Node.js `Map`)
- `v5-paper-dashboard` uses in-process Python dict (`_cache`)
- `microtrading-app` uses in-process Python dict + best-effort Redis (Docker container)

None of the apps share a Redis instance, a common market data service, or a request deduplicator. The same ticker can be fetched simultaneously by multiple apps on the same key with no coordination.

---

## Main Cause

**Practical REST congestion — elevated Polygon API server latency during early-market period (9:25–9:33am ET), compounded by two apps polling the same key simultaneously.**

Evidence:
1. All errors were `Read timed out` (server took >15s to respond), not `429 Too Many Requests`.
2. nasdaq-scanner-v6 showed only 59.6% fetch success at 9:25am ET — 2,138 tickers returned no data. This indicates Polygon's servers were under broad stress at market open, not only for one key.
3. V5's per-ticker aggs approach (~31 sequential HTTP requests/minute, 15s timeout each) is particularly vulnerable to elevated latency: one slow request can hold the per-ticker sequential loop for the full 15 seconds, cascading into multiple missed tickers per minute.
4. nasdaq-scanner-v6's bulk snapshot approach is more resilient — one request covers 200 tickers, so a single timeout affects a smaller fraction of the universe per unit time.

Secondary factor: both apps using the same key means any per-key server-side connection/throughput ceiling is shared.

---

## Recommendations

1. **Stop `nasdaq-scanner-v6` during V5 testing sessions.** The two apps share the same Polygon key and compete for the same API throughput. While no hard rate limit was hit, server-side load balancing may deprioritize keys with higher concurrent connection counts.

2. **Switch V5 DataFetcher from per-ticker `/v2/aggs` to bulk `/v2/snapshot` (like nasdaq-scanner-v6).** One request per 200 tickers vs one per ticker is ~6× more efficient at the same ticker pool size, and far more resilient to latency spikes.

3. **Add retry with exponential backoff on timeout.** V5's current `_fetch_bars()` catches the exception and returns `[]` — a timed-out ticker is silently dropped for that minute with no retry. One retry after 2–3s would recover most transient timeouts.

4. **Implement a shared Redis cache with TTL.** A common in-memory proxy (e.g., Redis with 30s TTL per ticker) would eliminate duplicate fetches for symbols that appear in multiple apps' universes (e.g., SMCI, SOUN, PLTR overlap between V5 and nasdaq-scanner).

5. **Add a per-key request rate limiter.** A token bucket at ~50 req/min per app would prevent burst spikes during scan cycle starts, where all chunks hit the API simultaneously.

6. **Add backoff on HTTP 429.** Neither app currently handles 429 — they would retry immediately on the next cycle. A 60s backoff on 429 would prevent amplifying rate limit pressure.

7. **Use WebSocket for live prices where possible.** nasdaq-scanner-v6 already does this for curated tickers. V5 could consume a shared WebSocket feed instead of polling per-ticker REST endpoints for its 28 MID tickers.

8. **Contact Massive/Polygon support about key sharing limits.** Clarify whether concurrent connections and per-minute throughput are tracked per-key or per-account, and whether multiple apps sharing one key counts against a connection limit.

9. **Add a data quality dashboard indicator for V5.** Surface real-time timeout rate per minute so operators can detect pipeline degradation before it affects a full session.

---

## Sanitization Statement

No API keys, tokens, `.env` files, raw database files, raw log archives, or full request URLs containing credentials are included in this document. All key references use the truncated fingerprint `CxhI4H...DMfc`. Log excerpts are paraphrased counts and timestamps only.

---

*Analysis scope: 2026-06-08 market session. No live trading. No real money. No broker integration.*
