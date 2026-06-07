# Trading Rules

## Scope

- **V1 is paper trading only.** No real money. No broker connection.
- **U.S. equities only.** No options, futures, crypto, or foreign instruments.
- **Intraday only.** All positions are closed within the same trading session.
- **No overnight positions.** Any open position at market close is force-closed.

## Broker and Execution

- No broker connection is active in Phase 0 or V1.
- No live orders are placed.
- All execution is simulated through the paper execution layer.

## Tradable Universe

The tradable universe builder is implemented in `backend/data/universe.py`. It is a batch application of the market quality gate across a configured list of symbols.

- A ticker must pass the universe builder before future strategy or catalyst logic can consider it.
- Universe classification checks each symbol individually using the market quality gate (spread, bid/ask, volume, last trade price).
- If a single symbol fails or errors, the remaining symbols continue to be evaluated.
- Universe classification does not decide direction. It does not create trades.

---

## Market Quality Gate

Before any ticker can be evaluated by future strategy logic, it must pass the market quality gate implemented in `backend/data/market_quality.py`.

The gate checks:
- **Spread** — bid/ask spread must be within the acceptable threshold
- **Bid/ask availability** — bid and ask must be present, non-zero, and ask > bid
- **Trade availability** — a valid last trade price must be present and non-zero
- **Current session volume** — day volume must meet the minimum threshold
- **Previous-day volume** — prior session volume must meet the minimum threshold
- **Basic price sanity** — last trade price must be greater than zero

A ticker is marked `tradable: true` only when all gates pass. If any gate fails, the ticker is marked `tradable: false` and all failing reasons are returned as a list.

This gate does not decide direction. It does not create trades. It is a data quality and liquidity pre-filter only.

---

## Entry Requirements

A position may only be evaluated for entry if ALL of the following conditions are met:

1. **Tradable ticker** — symbol is a valid U.S. equity, not halted or restricted
2. **Liquidity** — sufficient average daily volume and intraday volume
3. **Spread** — bid/ask spread within acceptable threshold
4. **Catalyst score** — a valid catalyst with AI-scored urgency and sentiment above threshold
5. **Technical/market confirmation** — price action and volume confirm the catalyst direction
6. **Risk-manager approval** — the risk manager has evaluated and approved the opportunity

No entry proceeds if any requirement is not satisfied.

## Exit Requirements

Every open position must have all of the following defined before entry:

- **Stop loss** — maximum loss level; position is closed if price hits this level
- **Take profit or trailing exit** — target or dynamic exit as price moves in favor
- **Maximum holding time** — position is closed after a defined time window regardless of outcome
- **Forced end-of-day close** — all positions are force-closed before market close

---

## Phase 2A — Research Paper Simulator

**This is fake-money simulation only. No broker. No real orders. No real money.**

The paper simulator runs an in-memory account with configurable virtual starting cash
(default $1,000). It uses Polygon REST data only.

### Account limits (configurable via `.env`)

| Setting | Default | Description |
|---|---|---|
| `PAPER_STARTING_CASH` | 1000.0 | Virtual starting cash |
| `PAPER_MAX_POSITIONS` | 2 | Max simultaneous open positions |
| `PAPER_MAX_TRADES_PER_DAY` | 20 | Max trades (entries) per calendar day |
| `PAPER_MAX_POSITION_SIZE_USD` | 250.0 | Max position size in virtual USD |
| `PAPER_TAKE_PROFIT_PERCENT` | 0.60 | Exit at +0.60% gain |
| `PAPER_STOP_LOSS_PERCENT` | 0.35 | Exit at -0.35% loss |
| `PAPER_MAX_HOLD_MINUTES` | 15 | Force-exit after 15 minutes |
| `PAPER_POLL_INTERVAL_SECONDS` | 60 | Background polling interval |
| `PAPER_DEFAULT_UNIVERSE` | 10 large-cap tickers | Symbols evaluated each tick |

### Candidate eligibility (evaluated each tick)

A symbol is eligible for a simulated entry only when ALL conditions pass:

1. `tradable: true` from the market quality gate
2. Spread ≤ 0.50%
3. Change percent > 0 (price is up on the day)
4. Volume ratio ≥ 0.8 vs prior day (if data is available)
5. At least one accepted (filtered + classified) catalyst exists for the symbol
6. Not all catalysts are classified as `generic_news`

Entry price = ask price (falls back to last trade price if ask is unavailable).

### Exit triggers (evaluated each tick for open positions)

Exit is triggered when ANY condition is met:

1. **Take-profit**: current bid ≥ entry price × (1 + PAPER_TAKE_PROFIT_PERCENT / 100)
2. **Stop-loss**: current bid ≤ entry price × (1 - PAPER_STOP_LOSS_PERCENT / 100)
3. **Max hold**: position has been open longer than PAPER_MAX_HOLD_MINUTES

Exit price = bid price (falls back to last trade price if bid is unavailable).

### State persistence

All state is in-memory only. State is saved to Redis as best-effort JSON on each tick
(does not affect operation if Redis is unavailable). State is lost on container restart.

---

## Phase 2B — Candidate Scoring Layer

**Fake-money research simulation only. No broker. No real orders. No AI/LLM calls.**

Each tick, every symbol in the universe receives a transparent deterministic score (0–100).
Scoring is purely rule-based — no AI, no ML. The score is always computed and returned in
the candidate record for observability, even when hard gates reject the symbol first.

### Score components

| Component | Max | Condition |
|---|---|---|
| `market_quality_score` | 25 | `tradable: true` passes quality gate |
| `spread_score` | 15 | ≤0.05% → 15; ≤0.15% → 10; ≤0.30% → 5; else 0 |
| `momentum_score` | 20 | ≥2.0% → 20; ≥1.0% → 15; >0% → 10; else 0 |
| `volume_score` | 15 | ≥1.5x → 15; ≥1.0x → 10; ≥0.8x → 5; else 0 |
| `catalyst_score` | 20 | High-value event type → 20; mid-value → 12; generic_news only → 5; none → 0 |
| `risk_penalty` | −20 | −10 if spread >0.50%; −10 if change_percent <0; −10 if untradable; −5 if vol_ratio <0.8 |

**Total** = sum of components, clamped to [0, 100].

### High-value catalyst event types

`earnings`, `guidance`, `analyst_rating`, `contract_award`, `partnership`,
`product_launch`, `fda_regulatory`, `m_and_a`

### Mid-value catalyst event types

`management_change`, `financing`, `legal_regulatory`, `sector_news`

### Entry score gate (configurable via `.env`)

| Setting | Default | Description |
|---|---|---|
| `PAPER_ENTRY_SCORE_THRESHOLD` | 70 | Minimum composite score required to attempt entry |

A symbol that passes all hard eligibility gates (see Phase 2A) but scores below the
threshold is marked `action: score_rejected` and does not enter. A symbol that exceeds
the threshold proceeds to the account capacity check (`can_enter`).

---

## Position Lifecycle

```
Entry conditions met → Risk-manager approval → Paper order placed
        ↓
Monitoring loop: check stop loss, take profit, trailing exit, max time
        ↓
Exit triggered (stop / target / time / EOD) → Paper order closed → P&L recorded
```
