# V6 Intelligence Feature Audit
**Date:** 2026-06-10  
**Scope:** `/opt/nasdaq-scanner-v6/` — Node.js scanner running on port 3002  
**Purpose:** Document V6's intelligence implementations for migration planning into the microtrading paper-trading stack.

---

## 1. Executive Summary

V6 ("Stock Signal Scanner") is a production Node.js/Express signal scanner running 24/7 on a Hetzner VPS. It combines five intelligence data layers — Reddit social sentiment, earnings calendar, insider transactions, multi-source news, and sector heatmap — with a real-time price engine (Polygon WebSocket + REST). The engine has been in production since mid-2025 and completed six iterative sessions of improvements.

**Key migration takeaways:**
- All intelligence features are in well-isolated modules (`intel.js`, `finnhub.js`, `news.js`, `indicators.js`) and can be ported individually.
- The PRE/POST gap scanner and sector heatmap are the most architecturally mature features — suitable for direct migration.
- Reddit via ApeWisdom is free and keyless; earnings/insiders via Finnhub are free-tier.
- **Three API keys are embedded in plaintext** in production source files — see §9 (Secrets).
- The FDA calendar is non-functional (requires Finnhub premium, ~$12/month).
- V7 engine spec (`ENGINE_V7_SPEC.md`) exists as a formal design document for the scoring system.

---

## 2. Project Overview

| Attribute | Value |
|---|---|
| Path | `/opt/nasdaq-scanner-v6/` |
| Language | Node.js (CommonJS) |
| Framework | Express 4 |
| Port | 3002 |
| Database | SQLite (`data/scanner.db`) via `better-sqlite3` |
| Process manager | pm2 |
| Auth | HMAC stateless tokens, 12h TTL |
| Key dependencies | `express`, `better-sqlite3`, `node-cron`, `node-fetch`, `ws` |

**Source files:**

| File | Lines | Role |
|---|---|---|
| `src/server.js` | 916 | Express entry point, all API routes, cron jobs |
| `src/scanner.js` | 1573 | Core scan engine, gap scanner, scoring, calibration |
| `src/db.js` | 410 | SQLite schema and all read/write operations |
| `src/intel.js` | 89 | Reddit/ApeWisdom + macro placeholder |
| `src/finnhub.js` | 280 | Earnings, insiders, FDA, ticker news |
| `src/news.js` | 414 | NewsAPI + EDGAR, scoring, sentiment |
| `src/polygon_ws.js` | 187 | Polygon real-time WebSocket client |
| `src/indicators.js` | 116 | VWAP, Bollinger, MACD, RSI, momentum, sector heatmap |
| `public/index.html` | ~4000 | Single-page dashboard (12 tabs) |

---

## 3. PRE/POST Gap Scanner

**Module:** `src/scanner.js` — `runGapScan()`  
**API endpoint:** `GET /api/gaps` → `{ gaps: [...], sectors: {...}, session, updatedAt, isLive }`  
**Refresh:** Every 60 seconds during pre-market and after-hours via `startFastLoop()`

### 3.1 How It Works

The gap scanner covers three stock groups:
1. **Curated** (~90 stocks across MEGA/DEV/MID lists)
2. **Watchlist** (user-pinned stocks, always shown/pinned to top)
3. **Dynamic** (~5,200 US common-stock universe from Polygon)

**Data source:** Polygon REST bulk snapshot (`/v2/snapshot`) in chunks of 200 tickers, with Polygon WebSocket overlay for curated stocks.

**Session-aware gap calculation:**
- **Pre-market:** `gapPct = (extPrice − prevDay.c) / prevDay.c` (overnight gap vs yesterday's close)
- **After-hours:** `gapPct = (extPrice − regClose) / regClose` (move since 4pm bell); `dayPct` also carried

```javascript
// from scanner.js
if (isAfterHours && regClose > 0) {
  livePrice = extPrice;
  gapPct    = ((extPrice - regClose) / regClose) * 100;   // after-hours move
  dayPct    = ((regClose - prevClose) / prevClose) * 100; // today's regular change
} else {
  livePrice = extPrice || snap.day.c;
  gapPct    = ((livePrice - prevClose) / prevClose) * 100; // pre-market gap
}
```

**Display thresholds:**
- Watchlist stocks: always shown (regardless of gap size)
- Curated stocks: `|gapPct| ≥ 1%`
- Dynamic (universe) stocks: `|gapPct| ≥ 3%` and price ≥ $3

**Telegram alerts (curated + watchlist only, never dynamic):**
- `STRONG` (≥5%) or `HUGE` (≥10%): once per ticker per calendar day
- Acceleration (gap grew ≥5% in one 60s scan): re-alerts at each new 5% threshold

**Acceleration detection:**
```javascript
const prevGapPct = new Map(); // ticker → gapPct from last scan
const acceleration = prev !== undefined ? +(gapPct - prev).toFixed(2) : 0;
const isAccelerating = Math.abs(acceleration) >= 5
                    && Math.sign(acceleration) === Math.sign(gapPct);
```

**Frozen state:** When the session ends (closed/weekend), `gapData` freezes at last scan; frontend shows a "FROZEN" banner with capture timestamp. Sector data is also persisted to `settings.gap_sectors_cache` in SQLite so it survives restarts.

**Intraday price history:** `_priceHistory` Map (ticker → `[{p, t}]`), 35-minute rolling window, ~7MB peak for full universe.

### 3.2 Migration Relevance

The pre/post gap scanner is the most mature and complete feature. Core logic is portable with these dependencies:
- Polygon REST bulk snapshot (already used in microtrading)
- SQLite for sector cache persistence
- A session-detection function (the V6 `isEDT()` / `getMarketSession()` pattern is correct UTC-based)

---

## 4. Reddit Ranking (ApeWisdom)

**Module:** `src/intel.js` — `fetchReddit()`  
**API:** `GET https://apewisdom.io/api/v1.0/filter/all-stocks/page/1`  
**API endpoint (V6):** `GET /api/reddit` → `{ results: [...], spikes: [...] }`  
**Refresh:** Every 15 minutes  
**Key required:** None (free, no auth)

### 4.1 How It Works

Fetches top 100 tickers from ApeWisdom page 1. ApeWisdom aggregates Reddit mentions across r/WallStreetBets and ~50 investing subreddits.

**Fields returned per ticker:**
- `ticker`: symbol
- `mentions`: total mention count in window
- `rank`: ranking position (1 = most mentioned)
- `upvotes`: associated upvote count
- `rank_24h_ago`: ApeWisdom's own 24h delta (built into API response)
- `mentions_24h_ago`: 24h delta mentions (built into API response)

**Spike detection (15-min):**
```javascript
// Compares current mentions to previous DB snapshot
const ratio = m.mentions / prevMentions;
if (ratio >= 3) {
  redditSpikes.push({ ticker, ratio, mentions });
  notify('reddit_spike', ...); // → Telegram alert
}
```

**DB storage:** `reddit_mentions` table — `(ticker, mentions, rank, upvotes, sentiment, rank_24h_ago, mentions_24h_ago, fetched_at)`. Primary key is `(ticker, fetched_at)` so every 15-min snapshot is preserved.

**Previous snapshot for delta:** `db.getPrevReddit()` fetches the second-most-recent `fetched_at` batch for comparison.

**Telegram alert:** Fires when any ticker's 15-min mentions jump ≥3×, via server.js listener:
```javascript
intel.addListener((type, data) => {
  if (type === 'reddit_spike') telegram.sendRedditAlert(data);
});
```

### 4.2 Limitations

- ApeWisdom free tier has no sentiment field (API returns it but V6 stores `0` for sentiment).
- Top 100 only — tickers ranked >100 are invisible unless on the watchlist (which shows rank even if >50 per CONTEXT.md).
- No historical spike data beyond the last two DB snapshots for delta.

### 4.3 Migration Relevance

The ApeWisdom integration is extremely simple (one `fetch` call, no auth). The 15-min spike detection pattern (3× ratio vs previous snapshot) is directly portable. The microtrading catalyst layer could incorporate Reddit rank as a social-confirmation signal.

---

## 5. Earnings Calendar

**Module:** `src/finnhub.js` — `fetchEarnings()` and `fetchEarningsFor(ticker)`  
**API:** Finnhub `/calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD`  
**API endpoint (V6):** `GET /api/earnings` → upcoming earnings from DB  
**Refresh:** Every 2 hours (batch); on-demand `fetchEarningsFor` for auto-enrich  
**Key required:** Finnhub free tier (60 calls/min)

### 5.1 How It Works

**Curated watchlist** (~84 tickers in `EARNINGS_WATCHLIST`) plus dynamically discovered tickers from news auto-enrich.

Fetch window: today → +30 days. Filters to watchlist members. Stores confirmed dates with EPS estimates.

```javascript
const earnings = (data.earningsCalendar || [])
  .filter(e => EARNINGS_WATCHLIST.includes(e.symbol))
  .map(e => ({
    ticker, date, epsEst, epsActual, revenueEst, surprise, confirmed: true, source: 'finnhub'
  }));
db.upsertEarnings(earnings);
```

**Earnings-proximity penalty in signal scoring:**
```javascript
// from scanner.js getEarningsPenalty()
// ≤1 day away: -10 pts; 2 days: -5 pts; 3 days: -3 pts
const days = Math.round((new Date(row.report_date) - new Date(today)) / 86400000);
return days <= 1 ? 10 : days === 2 ? 5 : days === 3 ? 3 : 0;
```

**Telegram alert:** 3d/2d/1d before confirmed date, once per ticker+date+today (DB key guard).

**DB deduplication:** `getUpcomingEarnings()` uses a `SELECT MIN(report_date)` subquery to keep only the earliest date when Finnhub returns two dates for the same ticker.

**Auto-enrich:** When a news article is high-impact and mentions a ticker not in the watchlist, `fetchEarningsFor(ticker)` is called immediately to backfill.

### 5.2 Limitations

- Finnhub free tier: 60 calls/min ceiling. The batch cycle calls one endpoint per `EARNINGS_WATCHLIST` member at 200ms spacing — ~17 seconds for 84 tickers.
- Just-reported earnings (today's beats/misses) do NOT appear in the forward calendar; they're only visible in the news feed.
- Actual EPS/revenue fields (`epsActual`, `surprise`) are populated after the report, not before.

### 5.3 Migration Relevance

The `earnings_proximity_penalty` pattern is directly relevant to the microtrading catalyst guard — stocks near earnings should be treated with caution. The Finnhub `/calendar/earnings` call is simple and free.

---

## 6. Insider Buys/Sells

**Module:** `src/finnhub.js` — `fetchInsiders()` and `fetchInsidersFor(ticker)`  
**API:** Finnhub `/stock/insider-transactions?symbol=TICKER`  
**API endpoint (V6):** `GET /api/insiders?ticker=X` → recent insider transactions  
**Refresh:** Every 30 minutes (batch); on-demand `fetchInsidersFor` for auto-enrich  
**Watchlist:** 24 key tickers in `INSIDER_WATCHLIST`

### 6.1 How It Works

Fetches 5 most recent transactions per ticker. SEC Form 4 transaction codes are properly classified:

| Code | Type | Alert? |
|---|---|---|
| P | Open Market Purchase | ✅ if ≥$50k within 3 days |
| M | Option Exercise | ✅ if ≥$50k within 3 days |
| S | Open Market Sale | No |
| A | Stock Award (compensation) | No |
| G | Gift/charitable transfer | No |
| F | Auto Tax Withholding | No |
| D | Auto Disposition | No |
| X | Auto Exercise & Sale | No |

```javascript
const isRealBuy = code === 'P' || code === 'M';
// Alert if: real buy, value ≥$50k, within 3 days of transaction date
if (isRealBuy && row.value >= 50000) { ... telegram.sendInsiderAlert(row); }
```

**Value calculation:** `price × shares` — with a known data-quality issue where some rows have `price=0` or `shares=0` (e.g., "$0 purchase" or "$1.56B sale") due to aggregate/multi-leg transactions in Finnhub's raw data.

**DB storage:** `insider_transactions` — `(id, ticker, name, title, trans_type, shares, price, value, trans_date, fetched_at)`.

**DB dedup:** `INSERT OR REPLACE` with id = `ticker-date-name` prevents duplicate inserts on re-fetch.

### 6.2 Limitations

- Value calculation is unreliable when Finnhub omits `transactionPrice` — "$1.56B CRWD sale" is a known artifact.
- Title field (executive role) is always empty — Finnhub free tier doesn't return `position` in the response.
- No 10b5-1 plan detection (scheduled vs discretionary distinction).
- 24-ticker watchlist is narrow; auto-enrich expands it for news-flagged tickers.

### 6.3 Migration Relevance

Insider buying within 3 days at $50k+ threshold is a strong catalyst signal. The SEC Form 4 code mapping is production-validated and correct. The `fetchInsidersFor` on-demand pattern is useful for event-driven enrichment.

---

## 7. News & Intel Engine

**Modules:** `src/news.js` (NewsAPI + EDGAR), `src/finnhub.js` (ticker-specific news)  
**API endpoints (V6):**
- `GET /api/news` → recent news articles (up to 500)
- `GET /api/news/high` → high-impact + macro items  
**Refresh:** NewsAPI + EDGAR every 5 minutes; Finnhub ticker news every 30 minutes

### 7.1 Data Sources

| Source | Endpoint | Cost | Interval |
|---|---|---|---|
| NewsAPI | `newsapi.org/v2/everything` | Free (100 req/day) | 15 min |
| SEC EDGAR 8-K | `efts.sec.gov/LATEST/search-index` | Free | 10 min |
| Finnhub company news | `/company-news?symbol=TICKER` | Free (60/min) | 30 min |

**NewsAPI query covers:** NVDA, AAPL, MSFT, AMD, TSLA, PLTR, OKLO, RKLB, SOUN, MU, IONQ, SMCI, COIN, CRWD, NVAX, META, AMZN — plus earnings/FDA/acquisition/macro keywords. Sources restricted to: reuters.com, bloomberg.com, cnbc.com, marketwatch.com, finance.yahoo.com, seekingalpha.com, benzinga.com, thestreet.com, investors.com, fool.com.

**EDGAR:** 8-K filings from last 24h; entity name matched against `extractTickers()` to find relevant tickers.

### 7.2 Ticker Extraction

Three-layer recognition:
1. `$TICKER` cashtag format — validated against `WATCHLIST_TICKERS` set
2. Company name matching via `NAME_TO_TICKER` dict (~50 well-known names)
3. Plain word match — only for tickers ≥4 chars not in `SHORT_TICKERS` (avoids false matches for S, T, C, etc.)

```javascript
// SHORT_TICKERS — only match via $TICKER format, never plain word
const SHORT_TICKERS = new Set(['S','U','X','BE','PL','V','T','F','C','K','M','N','P','R','W','AI','OPEN','RDW','FORM']);
```

### 7.3 Article Scoring and Sentiment

**Impact scoring** (`scoreArticle()`):
- HIGH (score ≥6): `earnings`, `beat`, `fda approval`, `acquisition`, `merger`, `ceo resign`, `contract award`, `bankruptcy`, etc. (+3 pts each)
- MEDIUM (score ≥3): `analyst`, `rating`, `forecast`, `expansion`, `deal` (+1 pt each)
- LOW: everything else

**Sentiment** — weighted voting on title only (preferred), falls back to full text:
- Strong negative keywords (weight 3): `crash`, `plunge`, `collapse`, `bankrupt`, `fraud`, `scandal`, `lawsuit`, `default`, `ceo fired`
- Strong positive keywords (weight 3): `beat`, `beats`, `approval`, `approved`, `breakthrough`, `record high`, `upgrade`, `surge`
- Net score → `positive` / `negative` / `neutral`

**Keep filter:** article kept if: has watchlist ticker OR is macro OR is SEC filing OR impact score ≥3.

### 7.4 Macro Detection

Keyword matching in headline + description against `MACRO_KEYWORDS`:
```
federal reserve, fed rate, fomc, interest rate decision, rate hike/cut,
cpi report, ppi report, non-farm payroll, jobs report,
gdp report, recession, tariff, trade war, treasury yield, sec crackdown
```

Macro articles tagged with `isMacro=true` and `macroEvent` field; tickers set to `[]` (macro = market-wide, not ticker-specific).

### 7.5 News Signal Integration with Scanner

The scanner uses news signals as a scoring component (+25 pts max) and as a quality gate relaxation for dynamic universe stocks:

```javascript
// from scanner.js updateNewsSignal() → getNewsScore()
const score = hasNews ? Math.min(25, high * 15 + medium * 5) : 0;
const isStrong = high >= minHigh; // "strong" = meets high-impact bar
// Strong news: relaxes dynamic universe quality gates ($0.10 floor vs $2 normally)
```

**News cache:** In-memory `newsSignalMap` (ticker → `{bullishHigh, bullishMedium, lastUpdated}`), 6-hour expiry. Pre-seeded from DB on startup.

### 7.6 Auto-Enrich

When a high-impact (or medium+bullish) article mentions tickers beyond the curated lists:
1. `recognizeUniverseTickers()` scans full universe name index (~3,398 company names)
2. `notifyEnrich(ticker)` fires (deduped once/ticker/6h)
3. Server adds ticker to `EARNINGS_WATCHLIST`, `INSIDER_WATCHLIST`, news tracking
4. `finnhub.fetchEarningsFor(ticker)` + `fetchInsidersFor(ticker)` called immediately
5. Persisted in `settings.discovered_tickers` (JSON, 14-day prune)

### 7.7 Restart Resilience

- `SEEN_URLS` pre-seeded from last 24h of DB entries → no Telegram re-spam on restart
- `newsLog` pre-seeded from DB (500 most recent articles) → dashboard populated immediately

### 7.8 Migration Relevance

The news scoring/sentiment pipeline is the most reusable component. Specific value for microtrading:
- Catalyst classification (`HIGH`/`MEDIUM`/`LOW` impact levels) maps directly to the existing catalyst type framework
- The `SHORT_TICKERS` pattern solves a real problem with false ticker matches
- Auto-enrich demonstrates an event-driven ticker discovery pattern

---

## 8. Sector Heatmap

**Module:** `src/scanner.js` (`runGapScan` → `gapSectors`), `src/indicators.js` (`getSectorHeatmap`)  
**API:** Included in `GET /api/gaps` response as `sectors` key  
**Two implementations exist (different purposes):**

### 8.1 Gap Scan Heatmap (Primary — market-wide, stable)

Built inside `runGapScan()` during each 60s pre/post scan. Covers the full scanned universe (~5,200 stocks).

**Algorithm:**
```
For each scanned stock:
  1. Resolve sector: sectorCache (from DB ticker_sectors) → thematic tag → "Other"
  2. Accumulate gapPct into sectorAgg[sector]
  3. Track: vals[], up count, down count, members list

Post-scan:
  4. For each sector with ≥3 *trading* (non-zero) stocks:
     - breadthPct = (up / active) * 100
     - median = median of non-zero gapPcts
     - movers = sorted list of (ticker, move%) for hover tooltip
```

**Sector resolution:** Lazily enriched from Polygon SIC codes via `sicToSector()` — SIC ranges mapped to GICS-like sectors (Technology, Health Care, Financials, etc.). Cache stored in DB table `ticker_sectors`. Falls back to curated thematic tag (AI/NUCLEAR/SPACE) until SIC is known.

**Stability fix:** Heatmap uses ALL scanned stocks (before the ≥1% display filter) so membership is stable. Without this, stocks crossing the 1% line would change the sector average each scan.

**Flats excluded:** Stocks with exactly 0% move (not trading pre/post) excluded from breadth and median calculations.

**Persisted:** `db.setSetting('gap_sectors_cache', JSON.stringify(...))` after each scan — survives restart.

### 8.2 Signal Scan Heatmap (Secondary — market-hours only, signal-filtered)

Built inside `runScanCycle()` via `ind.updateSector()` / `ind.getSectorHeatmap()`. Only covers stocks that passed the signal scoring gates (not the full universe). Less stable — resets each scan cycle. Exposed via `GET /api/status` → `sectorHeatmap`.

### 8.3 Migration Relevance

The `sicToSector()` SIC-to-GICS mapping (~70 SIC ranges) is ready-to-use. The breadth + median heatmap approach is statistically sound. The stability fix (use all members, not just movers) is a non-obvious design decision worth carrying forward.

---

## 9. API Inventory

### 9.1 REST Endpoints (server.js)

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | Scanner state, win rates, sector heatmap |
| GET | `/api/gaps` | Gap scan data + sector heatmap |
| GET | `/api/gaps/scan` | Trigger immediate gap scan |
| GET | `/api/signals` | Recent signals (last 300) |
| GET | `/api/signals/stats` | All-time aggregate performance |
| GET | `/api/performance` | Per-tab 3m/15m stats |
| GET | `/api/accuracy` | Per-tab win rate breakdown |
| GET | `/api/news` | Recent news articles |
| GET | `/api/news/high` | High-impact + macro only |
| GET | `/api/reddit` | Latest Reddit mentions + spikes |
| GET | `/api/earnings` | Upcoming earnings |
| GET | `/api/insiders` | Recent insider transactions |
| GET | `/api/fda` | FDA calendar (empty — needs premium) |
| GET | `/api/sectors` | Signal-scan sector heatmap |
| GET | `/api/watchlist` | User watchlist |
| POST | `/api/watchlist` | Add ticker to watchlist |
| DELETE | `/api/watchlist/:ticker` | Remove from watchlist |
| GET | `/api/thresholds` | Current scan thresholds |
| POST | `/api/thresholds` | Update thresholds |
| GET | `/api/settings/runtime` | Runtime settings |
| POST | `/api/settings/:key` | Update a setting |
| GET | `/api/daily-stats` | Historical daily stats (60 days) |
| GET | `/api/calibration/log` | Calibration history |
| POST | `/api/signals/:id/feedback` | Manual signal feedback |
| GET | `/health` | Health check |

### 9.2 Cron Jobs (server.js)

| Schedule | Job |
|---|---|
| `*/5 * * * *` | Outcome resolution (3m + 15m) + calibration |
| `0 7 * * 1-5` | Finnhub daily cycle (earnings + insiders + FDA) |
| `0 0 * * *` | US universe refresh (Nasdaq + NYSE + AMEX) |

### 9.3 External API Calls

| Service | Used in | Endpoint |
|---|---|---|
| Polygon REST | scanner.js, server.js | `/v2/snapshot`, `/v3/reference/tickers`, `/v3/reference/tickers/{T}` |
| Polygon WebSocket | polygon_ws.js | `wss://socket.polygon.io/stocks` |
| Finnhub | finnhub.js, scanner.js | `/quote`, `/calendar/earnings`, `/stock/insider-transactions`, `/company-news` |
| NewsAPI | news.js | `newsapi.org/v2/everything` |
| ApeWisdom | intel.js | `apewisdom.io/api/v1.0/filter/all-stocks` |
| SEC EDGAR | news.js | `efts.sec.gov/LATEST/search-index` |

---

## 10. Security Findings

> **⚠️ All secrets below are REDACTED. Do not log, commit, or expose the actual key values.**

### 10.1 Hardcoded Credentials in Source Files

**Finding 1 — Authentication password hardcoded**  
- File: `src/server.js`  
- Location: Login endpoint  
- Value: a plaintext password string  
- Risk: Anyone with read access to the source repository can authenticate to the scanner dashboard.

**Finding 2 — Polygon API key hardcoded (multiple locations)**  
- Files: `src/server.js` (test endpoints, lines ~732, 754), `src/scanner.js` (line 11), `src/intel.js` (line 6)  
- Risk: Key used for real-time WebSocket and REST. Exposure allows unauthorized API usage billed to the owner's Polygon account.

**Finding 3 — Finnhub API key hardcoded (multiple locations)**  
- Files: `src/server.js` (test endpoint, line ~765), `src/scanner.js` (line 261), `src/finnhub.js` (line 8)  
- Risk: Key used for earnings/insiders/news. Exposure allows unauthorized calls billed to the Finnhub account.

**Finding 4 — NewsAPI key hardcoded**  
- Files: `src/server.js` (test endpoint, line ~776), `src/news.js` (line 7)  
- Risk: Free tier has a 100-request/day limit. Exposure could exhaust daily quota.

**Finding 5 — Telegram bot token hardcoded**  
- File: `src/telegram.js`  
- Risk: Allows sending arbitrary messages to the owner's Telegram account.

**Finding 6 — Telegram chat ID hardcoded**  
- File: `src/telegram.js`  
- Risk: Low (destination, not credential) — combined with bot token it enables message injection.

### 10.2 Test Endpoints Expose Secrets in Response

`GET /api/test/polygon`, `GET /api/test/finnhub`, `GET /api/test/newsapi` in server.js construct URLs with API keys embedded and return raw JSON from the external API. An authenticated user can retrieve all three keys via HTTP.

### 10.3 Authentication Architecture

HMAC stateless tokens, 12-hour TTL. Password is hashed before use, but the plaintext source password is hardcoded (see Finding 1). No rate-limiting on the login endpoint.

### 10.4 Recommended Remediation (not in scope for migration, but worth noting)

1. Move all keys to environment variables or a `.env` file (never commit to git)
2. Remove or gate the `/api/test/*` endpoints
3. Replace hardcoded password with a hashed value in `.env`
4. Add rate-limiting to the login endpoint

---

## 11. Database Schema

SQLite at `/opt/nasdaq-scanner-v6/data/scanner.db`. 13 tables:

| Table | Rows (approx) | Purpose |
|---|---|---|
| `signals` | ~15k+ | Buy signals with score, indicators, outcomes |
| `calibrations` | ~10/session | Nightly calibration history |
| `thresholds` | 3 | Current price/vol/RSI thresholds per tab |
| `watchlist` | user-defined | Pinned stocks with optional price alerts |
| `news` | ~2k cap | Processed articles with impact/sentiment |
| `reddit_mentions` | 100/snapshot | ApeWisdom snapshots (all preserved) |
| `earnings_calendar` | ~100 | Confirmed earnings dates |
| `insider_transactions` | ~200 | SEC Form 4 transactions |
| `fda_calendar` | 0 | Empty — Finnhub premium required |
| `macro_events` | 0 | Placeholder — not populated |
| `inbox_messages` | user-defined | Contact form submissions |
| `settings` | ~30 key-value pairs | Runtime config, discovered tickers, gap cache |
| `daily_stats` | 1/session | Reports tab data (win rates, volumes) |
| `ticker_sectors` | ~330+ | SIC-based sector cache for heatmap |

**Notable schema patterns:**
- `signals` uses `INSERT OR REPLACE` — signal ID collision = overwrite, not duplicate
- `reddit_mentions` keeps every 15-min snapshot: `PRIMARY KEY (ticker, fetched_at)`
- `settings` is a `key TEXT PRIMARY KEY, value TEXT` KV store — persists JSON blobs for complex state
- Schema migrations use `ALTER TABLE ADD COLUMN` wrapped in try/catch (safe to re-run)

---

## 12. Signal Scoring Engine (V7)

**Module:** `src/scanner.js` — `evaluateSnapshot()`  
**Spec:** `/opt/nasdaq-scanner-v6/ENGINE_V7_SPEC.md`

V7 is the current production engine, merging V6 (multi-source intelligence) with V4.3 (entry quality filtering). Key design:

### 12.1 Hard Gates (any failure = no signal)

1. No alerts before 09:45 ET (pre-open warmup)
2. RVOL minimum: MEGA 1.2×, MID 1.5×, DEV 1.8×, Dynamic 2.0×
3. Price above VWAP
4. RSI not exhausted (MEGA ≤92, others ≤90)
5. 10-min intraday climb minimum (DEV/Dynamic ≥1.0%, MID ≥0.6%, MEGA ≥0.15%)
6. Momentum acceleration gate (MID/DEV only — not MEGA)
7. Recent fade gate (reject if -0.6%+ in last 30 min, outside open drive)
8. Candle quality: upper wick ≤35% (DEV), ≤45% (MID), ≤50% (MEGA); close position ≥75% (DEV), ≥60% (MID)
9. 3-min path volatility: DEV ≤6%, MID ≤4.5%, MEGA ≤3%

### 12.2 Scoring Components

| Component | Max Points | Notes |
|---|---|---|
| Momentum | 35 | Ratio-based vs threshold |
| RVOL sweet-spot | 45 (DEV) / 20 (MID) / 25 (MEGA) | Non-linear; very high RVOL penalized |
| Intraday Climb | 25 | 10-min window, ratio-based |
| Momentum Acceleration | 25 (DEV) / 18 (MID) / 10 (MEGA) | change_3m minus prior_9m |
| VWAP | 20 (MEGA) / 10 (MID/DEV) | Distance-based |
| Bollinger breakout | 20 | DEV exempt |
| Candle quality | 10 (DEV) / 8 (MID) / 5 (MEGA) | Close position + wick |
| Multi-day streak | 25 flat | Not category-multiplied |
| News | 25 flat | Not category-multiplied |
| RSI | 3 (MEGA) / 1 (MID) / 0 (DEV) | Only 15–35 oversold zone |
| MACD proxy | 2 (MEGA) / 1 (MID) / 0 (DEV) | Momentum acceleration vs yesterday |
| Volume acceleration | 5 | Last 5 bars vs prior 5 bars |
| Behavior seed | ±12 | Backtested per-ticker adjustments |
| Time-of-day | +5 to -5 | Open drive prime / power hour |
| Sector sympathy | +5 | Same sector signal within 30 min |
| Earnings proximity penalty | -3 to -10 | 1–3 days before earnings |

### 12.3 Alert Classification

| Level | Score Range | Meaning |
|---|---|---|
| `NO_ALERT` | Below threshold | Not shown |
| `WATCH` | 70–94 | Early watch signal |
| `STRONG_WATCH` | 95–104 (DEV only) | Elevated confidence |
| `TRADE_CANDIDATE` | 95+ (MEGA/MID), 105+ (DEV) | Highest confidence setup |
| `EXTENDED_WATCH` | >105 (MID) | Potentially overextended |

**Alert thresholds:** MEGA ≥70, DEV ≥70, MID ≥80.

### 12.4 Outcome Resolution

- **3-minute resolution:** WIN if `change_3m ≥ m3_threshold` (MEGA 0.35%, MID 0.75%, DEV 1.5%)
- **15-minute resolution:** WIN if `change_15m ≥ m15_threshold` (MEGA 0.75%, MID 2.0%, DEV 3.0%)
- Both stored in `signals` table (`outcome_3m`, `outcome`)
- >24h without price data → automatic LOSS (stuck-signal fallback)

### 12.5 Auto-Calibration

Nightly (00:00 UTC + 5-min resolution loop, only for completed UTC days):
- Per-ticker averaging (prevents one volatile ticker dominating calibration)
- Rolling 3-day win rate smoothing
- Density gate: only raises threshold if indicator fires ≥20% of raw signals
- Sample size gate: minimum 10 resolved tickers before acting
- Adjusts `price_min` and `vol_min` thresholds in DB

---

## 13. Frontend Tabs

`public/index.html` (~4000 lines, single-page app). 12 tabs:

| Tab | Key | Data source |
|---|---|---|
| 🌗 PRE/POST | `pre` | `/api/gaps` |
| 💎 SIGNALS (MEGA/DEV/MID dropdown) | `mega`/`dev`/`mid` | `/api/signals` |
| 🎯 WATCHLIST | `watchlist` | `/api/watchlist` + `/api/signals` |
| 🔔 ALERTS | `alerts` | `/api/signals` |
| 📅 EARNINGS | `earnings` | `/api/earnings` |
| 🚀 REDDIT | `reddit` | `/api/reddit` |
| 👔 INSIDERS | `insiders` | `/api/insiders` |
| 🧬 FDA | `fda` | `/api/fda` |
| 📊 PERFORMANCES | `perf` | `/api/performance` |
| 📈 REPORTS | `reports` | `/api/daily-stats` |
| 📰 NEWS | `news` | `/api/news` |
| 📬 INBOX | `inbox` | `/api/inbox` |

**Sidebar:** signal thresholds sliders (read-only, set by calibration), news signal count settings, Telegram toggle per alert type, watchlist input.

**Refresh:** 10-second polling interval for most tabs.

---

## 14. Known Limitations and Gaps

| Issue | Impact | Notes |
|---|---|---|
| FDA calendar empty | 🧬 FDA tab useless | Finnhub premium ~$12/month required |
| RSI is single-candle approximation | Score noise | Needs 14-candle OHLCV for proper RSI |
| Polygon REST 15-min delay pre/post | Gap prices slightly stale | WebSocket is real-time during market only |
| Insider value field unreliable | Some records show $0 or billions | Missing `transactionPrice` in Finnhub raw data |
| Title column empty in insider_transactions | Can't show executive role | Finnhub free doesn't return `position` |
| NewsAPI free: 100 req/day | ~12 fetch cycles/day | Bloomberg/WSJ have 24h delay on free tier |
| `guide.html` text outdated | Minor | Still says "Nasdaq", "30-min resolution", "Finnhub free tier" |
| Calibration on first day only | Week 1 thresholds are seeds | Real tuning requires 1–2 weeks of market data |
| `macro_events` table empty | Placeholder only | `checkMacro()` in intel.js is a stub |
| No 10b5-1 plan detection | Insider alerts may be noisy | Scheduled vs discretionary sales indistinguishable |

---

## 15. Migration Plan

### 15.1 Priority Order

**P0 — Immediate value, low complexity:**
1. **ApeWisdom Reddit** (`intel.js:fetchReddit`) — single fetch call, no auth, returns rank + mentions + 24h delta. Candidate signal enrichment.
2. **News scoring pipeline** (`news.js:scoreArticle`, `extractTickers`, `detectMacro`) — standalone functions, no external state. Sentiment/impact for news catalysts.
3. **Earnings proximity penalty** (`scanner.js:getEarningsPenalty`) — pure DB lookup + math. Already partially addressed by catalyst type guard.

**P1 — Moderate complexity, high value:**
4. **Finnhub earnings calendar** (`finnhub.js:fetchEarnings`) — 30-60 min to wire up. Provides confirmed dates + EPS estimates for scoring.
5. **Finnhub insider transactions** (`finnhub.js:fetchInsiders`) — same complexity. Real discretionary buys as a catalyst signal.
6. **PRE/POST gap scanner** (`scanner.js:runGapScan`) — session-aware gap logic with WebSocket overlay. Gap size and direction as overnight catalyst.

**P2 — Significant complexity, contextual value:**
7. **Sector heatmap** — requires SIC enrichment queue + DB sector cache. More relevant for market-context display than individual candidate scoring.
8. **News auto-enrich** — ticker discovery + backfill pipeline. Useful for dynamic universe but adds complexity.

### 15.2 What to Avoid/Adapt

- **Do not import the authentication system** — V6's hardcoded password is a security regression.
- **Do not import test API endpoints** — they expose keys in HTTP responses.
- **Secret management:** all V6 API keys must be moved to environment variables or the microtrading secrets store before any migration.
- **SQLite**: V6 uses SQLite directly; microtrading uses Redis + SQLite. Adapt DB layer accordingly.
- **V7 scoring engine** is tightly coupled to V6's data model (Polygon snapshots, price history Map, WebSocket bars). Port selectively — the hard gate logic and scoring weights are valuable, but the full engine is ~600 lines of entangled state.

### 15.3 Suggested Migration Interfaces

```python
# Microtrading side: wrap V6 intelligence as enrichment sources

class RedditEnrichment:
    """ApeWisdom top-100 snapshot, 15-min TTL."""
    def get_rank(ticker: str) -> Optional[int]
    def get_24h_delta(ticker: str) -> Optional[float]

class EarningsEnrichment:
    """Finnhub forward calendar, 2h TTL."""
    def days_until_earnings(ticker: str) -> Optional[int]
    def get_eps_estimate(ticker: str) -> Optional[float]

class InsiderEnrichment:
    """Finnhub Form 4, 30-min TTL."""
    def recent_buys(ticker: str, days: int = 30) -> List[InsiderBuy]

class NewsEnrichment:
    """NewsAPI + EDGAR, 15-min TTL."""
    def get_impact(ticker: str) -> Literal["high", "medium", "low", "none"]
    def get_sentiment(ticker: str) -> Literal["positive", "negative", "neutral"]
```

---

## 16. Appendix — Key Constants Reference

### Signal Scoring (scanner.js)

```javascript
// RVOL minimum thresholds
const rvolMin = isDynamic ? 2.00 : isDev ? 1.80 : isMid ? 1.50 : 1.20;

// Alert score thresholds
const alertThreshold = isDynamic ? 75 : resolvedTab === 'mid' ? 80 : 70;

// Earnings proximity penalty
// ≤1 day: -10pts, 2 days: -5pts, 3 days: -3pts, >3 days: 0

// Sector sympathy bonus: +5 pts if same sector fired within 30 min
// Earnings proximity penalty: -3 to -10 pts based on days to report
```

### News Scoring (news.js)

```javascript
// Impact thresholds
const impactLevel = score >= 6 ? 'high' : score >= 3 ? 'medium' : 'low';

// HIGH_IMPACT keywords include: 'earnings','beat','miss','guidance','revenue',
//   'acquisition','merger','fda approval','fda reject','contract award',
//   'bankruptcy','ceo resign','layoffs','clinical trial','sec charges'

// Sentiment: net weight from STRONG_POS(+3) + MOD_POS(+2) - STRONG_NEG(-3) - MOD_NEG(-2)
// Falls back to full text if title gives no signal
```

### WIN Thresholds (scanner.js DEFAULT_WIN_THRESHOLDS)

```javascript
mega: { m3: 0.35, m15: 0.75 },
mid:  { m3: 0.75, m15: 2.0  },
dev:  { m3: 1.5,  m15: 3.0  },
```

### Background Loop Intervals

```
Gap scan (pre/post):    60 seconds
Signal scan (market):   30 seconds
News fetch:             5 minutes
Reddit fetch:           15 minutes
Finnhub cycle:          30 minutes
Outcome resolution:     5 minutes (cron)
Universe refresh:       Daily midnight (cron)
Finnhub daily (EOD):    07:00 UTC weekdays (cron)
```

---

*Audit produced 2026-06-10. V6 repo state as-read; no code was modified during this audit.*
