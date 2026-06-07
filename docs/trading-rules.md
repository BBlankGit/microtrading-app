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

## Position Lifecycle

```
Entry conditions met → Risk-manager approval → Paper order placed
        ↓
Monitoring loop: check stop loss, take profit, trailing exit, max time
        ↓
Exit triggered (stop / target / time / EOD) → Paper order closed → P&L recorded
```
