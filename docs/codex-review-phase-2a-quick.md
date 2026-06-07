# Codex Review — Phase 2A-Quick Research Paper Simulator MVP

Review target: latest Phase 2A changes in `BBlankGit/microtrading-app`.

Review scope: paper simulator MVP only. This review does not add features, broker integration, live trading, real orders, AI/LLM calls, or new strategy scoring.

## Executive conclusion

Phase 2A-Quick appears safe to run as a fake-money research simulation. The implementation is explicitly virtual-account based, has no broker SDK integration, has no live-trading enablement path, has no real order-execution path, and uses deterministic catalyst classification rather than AI/LLM calls.

No critical issue requiring a patch before market-hours fake-money operation was found.

The main follow-up work is test depth and operational clarity around Redis persistence. The current tests validate core account math and API auth, but they do not yet cover the full tick decision loop, Redis fallback/reporting, bid/ask price selection, or exit-trigger behavior at the simulator level.

## Critical issues

None found for the Phase 2A fake-money simulator MVP.

Specific safety-critical checks reviewed:

- The paper account is documented and implemented as an in-memory virtual account with no broker, no real orders, and no real money.
- The paper simulator module states that it is fake-money only and has no broker, no live trading, no real orders, and no real-money execution.
- State-changing paper endpoints are protected by `require_admin_token`.
- The dashboard and paper dashboard API both label the system as research-only fake-money simulation.
- No broker SDK import, live-trading path, real order submission path, or AI/LLM import was found in the new `backend/paper` implementation.

## Important non-blocking issues

### 1. Redis persistence is best-effort write-only, not restore-on-start

The simulator saves a JSON snapshot to Redis after reset/tick, and reports `persistence: redis` when the save succeeds. However, there is no corresponding state-load path on process startup. The Phase 2A docs correctly state that state is lost on container restart, but an operator seeing `persistence: redis` in `/api/paper/status` may reasonably assume Redis is durable simulator persistence rather than a best-effort latest-state export.

Safety impact: low. Losing fake-money paper state is not a real-money risk. Clarity impact: medium.

Recommendation: before a later phase, rename/report this more explicitly, such as `snapshot_storage: redis_best_effort` and/or `restored_from_persistence: false`, or add explicit startup restore if that becomes a requirement.

### 2. Read-only endpoints expose paper state publicly

The read-only endpoints are unauthenticated by design and only return virtual cash, virtual positions, virtual trades, candidate decisions, and explicit fake-money disclaimers. That is safe from a trading/execution perspective.

Safety impact: low. Operational/privacy impact: low-to-medium if deployed publicly, because the public can view research candidates and simulated P&L.

Recommendation: acceptable for this MVP if intentional. If deployed beyond a private/research environment, consider read auth or network-level restriction in a future phase.

### 3. State reads are not consistently lock-protected

State mutations in the tick processing section are protected by a module-level asyncio lock, and account reset also mutates under the lock. However, `get_status`, `get_positions`, `get_trades`, and `get_state` read module-level state without acquiring that lock. In a single-process FastAPI event loop this is unlikely to create dangerous behavior, and the consequence is limited to occasionally inconsistent fake-money snapshots.

Safety impact: low. Understandability/debugging impact: low-to-medium.

Recommendation: acceptable for MVP; consider a single snapshot helper under lock in a later cleanup if inconsistent dashboard reads appear.

### 4. The global `/api/status` message still says paper trading is not implemented

The Phase 2A router is included, but the generic `/api/status` response still says paper trading is not implemented and reports `paper_trading_enabled: false`. This is conservative and safe, but may confuse operators because the Phase 2A paper simulator endpoints now exist.

Safety impact: low. Clarity impact: medium.

Recommendation: in a future documentation/status cleanup, distinguish `paper_trading_enabled` from `paper_simulator_available` or update the message while still clearly saying fake-money only.

## Safety assessment

### Fake-money only

Pass. The new implementation keeps all positions and trades inside `PaperAccount` as virtual state. Cash, positions, trades, P&L, shares, and proceeds are computed in memory and stored as dataclasses. No code path sends orders to a broker or external execution system.

### No broker integration, live trading, real orders, AI/LLM calls, or real-money path

Pass. The new paper simulator calls Polygon REST data for market snapshots/news and uses existing deterministic catalyst filtering/classification. It does not import broker SDKs, does not create/submit/place/execute orders, and does not import OpenAI/Anthropic/LangChain in the paper module. The catalyst classifier explicitly documents that it uses no AI, no sentiment, and no trade recommendation.

One safe external-data dependency remains: Polygon market/news data. This is data retrieval only, not execution.

### ADMIN_API_TOKEN protection for state-changing endpoints

Pass. All four state-changing paper endpoints use `Depends(require_admin_token)`:

- `POST /api/paper/start`
- `POST /api/paper/stop`
- `POST /api/paper/reset`
- `POST /api/paper/tick`

The dependency rejects unconfigured admin tokens with HTTP 503, rejects missing/malformed bearer headers with HTTP 401, and compares supplied tokens using `hmac.compare_digest`.

### Read-only paper endpoints

Pass for trading safety. The following endpoints do not mutate simulator state directly and are unauthenticated:

- `GET /api/paper/status`
- `GET /api/paper/positions`
- `GET /api/paper/trades`
- `GET /api/paper/dashboard`

They expose virtual simulator state only. The dashboard API returns an explicit disclaimer: research-only fake-money simulation, no broker, no live trading, no real orders.

### Dashboard clarity

Pass. The dashboard has a prominent warning banner saying research-only fake-money simulation, no broker, no live trading, no real orders, all P&L is virtual, and not financial advice. Its footer also shows the API disclaimer, research-paper mode, `live_trading: false`, and `broker: false`.

### Anything that could be mistaken as real trading

No high-risk wording or UI path was found in the Phase 2A simulator/dashboard changes. The terms “positions” and “trades” are used, but they are repeatedly framed as paper/fake-money/virtual. The Start/Stop/Tick controls could look operational, but they require `ADMIN_API_TOKEN` and affect only simulator state.

## Paper simulator state management assessment

Overall: safe and understandable for an MVP.

Positive findings:

- Account state is simple: starting cash, cash, open positions keyed by symbol, closed trades, and daily entry count.
- Reset stops the background loop, clears positions/trades/prices/candidates/errors, resets persistence state, and saves a snapshot.
- The background loop runs periodic ticks and honors a stop event.
- Tick processing evaluates exits before entries, which is understandable and avoids holding stale positions longer than necessary.
- Account mutations during exit/entry processing occur under a lock.
- Redis write failures are caught and downgrade the status to memory fallback instead of failing the simulator.

Caveats:

- Redis is not used to restore state after restart.
- Public read helpers do not take the lock.
- `_last_prices` and `_state` are partially updated outside the account mutation lock, which can produce transiently inconsistent dashboard snapshots but not real-money risk.

## P&L and long-only logic assessment

Pass for long-only fake-money positions.

- Entry creates a long-only position by spending virtual cash and computing `shares = size_usd / entry_price`.
- Exit computes virtual proceeds as `shares * exit_price`.
- Realized P&L is `proceeds - cost_basis`.
- P&L percent is `pnl / cost_basis * 100`.
- Open-position unrealized P&L is `(current_price - entry_price) * shares`.
- Equity is virtual cash plus current virtual position value.

No shorting, margin, borrowing, options, crypto, or real-money cash movement was introduced.

## Bid/ask behavior assessment

Pass.

- Entry uses `ask` when available and falls back to `last_trade_price` only if ask is unavailable.
- Exit uses `bid` when available and falls back to `last_trade_price` or the last known price if bid is unavailable.
- `_last_prices` are tracked from bid/last-trade data, which is conservative for valuing long positions.

## Rule enforcement assessment

Pass for MVP rule enforcement.

- Take-profit is enforced when current exit price reaches `entry_price * (1 + PAPER_TAKE_PROFIT_PERCENT / 100)`.
- Stop-loss is enforced when current exit price reaches `entry_price * (1 - PAPER_STOP_LOSS_PERCENT / 100)`.
- Max-hold-time is enforced when hold minutes exceed or equal `PAPER_MAX_HOLD_MINUTES`.
- Max positions is enforced before entry.
- Max trades per day is enforced as max entries per UTC calendar day.
- Duplicate positions in the same symbol are blocked.
- Entry size is capped by both `PAPER_MAX_POSITION_SIZE_USD` and available virtual cash.

Not in scope for this MVP: end-of-day liquidation, risk-manager approval, cooldown after losses, trailing stops, partial fills, slippage modeling, commissions, or full strategy scoring.

## Redis fallback / in-memory persistence behavior

Safe but should be clearer.

- Default state starts as `memory`.
- Every reset/tick attempts a best-effort Redis JSON snapshot.
- If Redis write succeeds, status reports `redis`.
- If Redis write fails, status reports `memory` and simulator operation continues.
- State is still fundamentally in-memory and is lost on container restart.

This is safe for fake-money simulation. The only concern is operator interpretation of `persistence: redis` as durable restart recovery.

## Test coverage assessment

### What is covered well

- Paper account reset behavior.
- Entry cash deduction and available-cash cap.
- Daily trade-count incrementing.
- Basic profitable and losing exits.
- Nonexistent-position exit behavior.
- Max positions.
- Max daily trades.
- Duplicate-symbol position blocking.
- Equity and realized P&L basics.
- Zero-price entry rejection.
- Public read endpoints returning HTTP 200 without auth.
- Protected state-changing endpoints rejecting missing/wrong tokens and accepting correct tokens.
- Paper module safety invariants for broker imports, order-execution patterns, and AI/LLM imports.

### Important gaps

The MVP test suite should eventually add simulator-level tests for:

- Entry uses ask when present and last trade only as fallback.
- Exit uses bid when present and last trade/last known price only as fallback.
- `run_tick` enforces take-profit, stop-loss, and max-hold-time end-to-end.
- `run_tick` enforces max positions and max trades per day end-to-end when multiple candidates are eligible.
- Redis success/failure reporting and memory fallback behavior.
- Reset semantics while the loop is running.
- No duplicate background tasks on repeated start.
- Dashboard disclaimer presence, or at least API dashboard disclaimer presence.

### Test commands run during review

- `timeout 60 pytest -q backend/tests/test_paper.py` — passed: 20 tests passed, with warnings about Starlette/httpx deprecation and unknown `asyncio_mode` config.
- `timeout 120 pytest -q` — failed for three pre-existing async Redis status tests because the environment lacks a suitable async pytest plugin; 49 tests passed and 3 failed due to test-environment/plugin limitation.

## Safe to run tomorrow as fake-money simulation?

Yes. Phase 2A-Quick is safe to run tomorrow as a fake-money research simulation, provided operators understand that:

- It is not real trading.
- It does not place real orders.
- It has no broker connection.
- All P&L, cash, positions, and trades are virtual.
- Redis is only a best-effort snapshot target and does not restore state after restart.
- A properly configured `ADMIN_API_TOKEN` is required for Start/Stop/Reset/Tick.

## Is any patch required before running during market hours?

No patch is required before market-hours fake-money operation.

Recommended non-blocking follow-ups before broader or longer-running use:

1. Add simulator-level tick tests for bid/ask behavior and exit/limit enforcement.
2. Clarify Redis status wording so `persistence: redis` cannot be mistaken for restart-safe restoration.
3. Consider auth or network restriction for read-only endpoints if deployed publicly.
4. Update the generic `/api/status` wording to acknowledge that a fake-money paper simulator exists, without implying live trading or broker execution.
