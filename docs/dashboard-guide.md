# Dashboard Guide

## What is this?

The Microtrading Research Dashboard is a **fake-money simulation** interface for
observing how a rule-based candidate scoring system behaves against live Polygon REST
market data. It is **not** a trading platform.

**Nothing here executes real trades. There is no broker connection. No real money
changes hands. All P&L, positions, and trades are virtual.**

---

## What the admin token controls

The `ADMIN_API_TOKEN` (set in `.env`) is required to call state-changing endpoints:

| Endpoint | Requires token | Purpose |
|---|---|---|
| `POST /api/paper/start` | Yes | Start background polling loop |
| `POST /api/paper/stop` | Yes | Stop background polling loop |
| `POST /api/paper/reset` | Yes | Reset account to starting cash |
| `POST /api/paper/tick` | Yes | Run one evaluation tick manually |
| `POST /api/paper/universe/refresh` | Yes | Force-rebuild active universe |

Read-only endpoints (`GET /api/paper/*`) require no token.

---

## Dashboard sections

### Session Readiness

Shows at-a-glance readiness before a market session:

- **Simulator status** — whether the background loop is running
- **Market session** — whether U.S. regular hours (09:30–16:00 ET, weekdays only) are currently active. Best-effort clock; does not account for market holidays.
- **Last tick** — timestamp of the most recent evaluation tick
- **Active universe** — how many symbols are in the current evaluation pool
- **Universe errors** — how many symbols failed to fetch data this cycle

### Account

Real-time virtual account state: cash, equity, P&L, open positions, closed trades, daily trade count.

### Controls

All state-changing actions. Requires `ADMIN_API_TOKEN` in the token input field.

- **▶ Start** — starts the 60-second background polling loop
- **■ Stop** — stops the loop
- **↺ Reset** — resets the account to starting cash, clears all positions and trades
- **⚡ Tick** — runs one evaluation tick manually
- **🌐 Universe** — force-rebuilds the active universe from Polygon data

### Open Positions / Closed Trades

All positions and trades are virtual. Entry price uses the ask price (or last trade price as fallback). Exit price uses the bid price (or last trade price as fallback).

### Last Tick — Candidate Decisions

Shows every symbol that was evaluated in the most recent tick, with:

- **Score** — composite 0–100 score and threshold
- **Components** — breakdown of how the score was computed (max values in parentheses)
  - Qual=Quality(25) — tradable market quality gate
  - Sprd=Spread(15) — bid/ask spread tightness
  - Mom=Momentum(20) — intraday change percent
  - Vol=Volume(15) — volume ratio vs prior day
  - Cat=Catalyst(20) — catalyst event type quality
  - Risk=penalty(-20) — risk deductions
- **Action** — what happened to this symbol
- **Decision/Rejection** — the reason for the outcome

### Paper Universe

The dynamic universe shows which symbols are actively being evaluated. It is rebuilt from Polygon REST data every 5 minutes (configurable via `PAPER_DYNAMIC_REFRESH_SECONDS`).

### Analytics

#### P&L

Session-level virtual profit/loss metrics. All dollar amounts are fake money.

#### Performance

Win/loss statistics across all closed virtual trades in this session:

- **Win rate** — wins ÷ (wins + losses) × 100
- **Profit factor** — sum of winning P&L ÷ sum of losing P&L magnitude. >1 means wins outweigh losses.
- **Average hold** — mean hold time in minutes across all closed trades

#### Candidate Funnel (last tick)

How the candidate pool was filtered in the most recent tick:

```
Total candidates
  → hard_rejected   (failed market quality gate, spread, change, volume, catalyst gates)
  → score_rejected  (passed hard gates but composite score < threshold)
  → blocked         (score passed but can_enter returned False: max positions or already held)
  → entered         (position successfully opened)
  → entry_failed    (rare: score + can_enter passed but price unavailable)
```

#### Score Distribution (last tick)

How scores were distributed across all candidates in the last tick:

- **Above threshold** — symbols at or above `PAPER_ENTRY_SCORE_THRESHOLD` (default 70)
- **80+** — high-confidence candidates
- **70–79** — at or just above threshold
- **50–69** — below threshold but not completely eliminated
- **Below 50** — weak candidates

#### Catalyst Breakdown

Counts of catalyst event types seen across both the current tick candidates and all closed trades this session.

High-value types (full catalyst score): `earnings`, `guidance`, `analyst_rating`, `contract_award`, `partnership`, `product_launch`, `fda_regulatory`, `m_and_a`

Mid-value types (partial score): `management_change`, `financing`, `legal_regulatory`, `sector_news`

Generic (`generic_news`) — counted but not sufficient for entry.

#### Top Rejection Reasons

The most frequent rejection reasons from the last tick. Useful for diagnosing why the universe is not triggering entries.

#### Universe Health

Summary of the most recent universe build: active symbol count, errors, and refresh reason.

---

## What the dynamic universe does

1. Reads `PAPER_BASE_UNIVERSE` (100 symbols by default)
2. Fetches a Polygon snapshot for each symbol concurrently
3. Applies eligibility filters: price range, minimum day volume, minimum absolute change, maximum spread
4. Ranks by: tradable first → abs change_percent desc → volume_ratio desc → spread_percent asc
5. Takes the top `PAPER_MAX_SYMBOLS_PER_TICK` (50) symbols as the active universe for the next tick
6. Caches for `PAPER_DYNAMIC_REFRESH_SECONDS` (300s)

If all symbols fail or dynamic mode is disabled, falls back to the first N base symbols.

---

## How entries are decided

Each tick, for every symbol in the active universe:

1. **Market quality gate** — Polygon snapshot must show valid bid/ask, last trade price, sufficient volume, and acceptable spread
2. **Hard gates** — tradable=True, spread ≤ 0.50%, change_percent > 0, volume_ratio ≥ 0.8, at least one non-generic catalyst
3. **Composite score** — must reach `PAPER_ENTRY_SCORE_THRESHOLD` (default 70/100)
4. **Account capacity** — must not already hold the symbol, must not exceed `PAPER_MAX_POSITIONS`, must not exceed `PAPER_MAX_TRADES_PER_DAY`
5. **Entry** — buy at ask price, position size up to `PAPER_MAX_POSITION_SIZE_USD`

---

## How exits are decided

Each tick, for every open position:

1. **Take-profit** — bid ≥ entry_price × (1 + PAPER_TAKE_PROFIT_PERCENT / 100)
2. **Stop-loss** — bid ≤ entry_price × (1 − PAPER_STOP_LOSS_PERCENT / 100)
3. **Max hold time** — position open longer than PAPER_MAX_HOLD_MINUTES

Exit price = bid price (or last trade price if bid unavailable).

---

## Why individual ticker fetch errors are non-fatal

The universe builder and tick evaluator run all symbol fetches concurrently via
`asyncio.gather`. A Polygon error for one symbol (e.g., 404, timeout, rate limit) is
caught per-symbol, recorded in the `errors` list, and the rest of the universe continues
processing. A single bad ticker never aborts the tick.

**SQ → XYZ example:** Block Inc. changed its stock ticker from `SQ` to `XYZ` in 2024.
The old `SQ` ticker was returning Polygon 404 errors. It has been removed from
`PAPER_BASE_UNIVERSE` and replaced with `XYZ`. This is a routine maintenance task:
when a ticker is delisted, renamed, or consistently erroring, update the base universe
and the error will no longer appear.

---

## State persistence

All simulator state is in-memory only. Redis is used for best-effort snapshot storage
(the latest state is saved after each tick). **State is lost on container restart.**
`state_restored_from_snapshot: false` always — snapshots are saved but not currently
loaded on startup.

---

## What is not implemented yet

- Holiday calendar for market session detection
- Multi-day trade history across restarts
- Position sizing based on Kelly or volatility
- Partial exits or trailing stop-loss
- Sector filters or correlation limits
- Broker paper trading integration (out of scope for this research tool)
- Live trading (permanently out of scope)

---

## Next planned improvements

- Phase 2D: Dashboard observability and trade analytics (this phase)
- Phase 2E: Session journal — persist tick logs and daily summaries to PostgreSQL
- Phase 2F: Signal review — flag the best-scoring candidates from each session for offline review
