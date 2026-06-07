# Codex Review — Phase 2E Persistent Paper Trade Journal

Review date: 2026-06-07

Scope reviewed: latest checked-out branch only, with focus on the requested Phase 2E persistent paper trade journal surface.

## Critical issues

1. **Phase 2E persistent journal is not present in this checkout.**
   - I found no `journal` module, no journal database repository, no PostgreSQL table-creation code, and no `/api/journal/*` router.
   - The backend still exposes only `/api/paper/*` paper simulator routes plus existing market/data/catalyst/quality/stream/universe routers.
   - `DATABASE_URL` exists as a setting and `.env.example` value, and `asyncpg` is installed, but there is no code that uses `DATABASE_URL` to initialize or write the requested journal tables.

2. **Requested read-only journal APIs are missing.**
   - The requested endpoints are not implemented:
     - `/api/journal/summary`
     - `/api/journal/ticks`
     - `/api/journal/candidates`
     - `/api/journal/trades`
     - `/api/journal/rejections`
     - `/api/journal/performance`
   - Because there is no journal router, the API safety/read-only assessment for these endpoints is a blocker: the endpoints cannot currently be used.

3. **The simulator does not persist a post-`run_tick()` journal record.**
   - `run_tick()` builds a tick result, processes exits and entries, saves only the best-effort Redis/latest-state snapshot, then updates in-memory `last_tick_at`, `last_error`, and `last_candidates`.
   - There is no second best-effort PostgreSQL journal write after tick completion.
   - As a result, historical ticks/candidates/trades/rejections/performance cannot survive process/container restart through a journal.

4. **The requested persistence tests are absent.**
   - Existing tests cover paper-account behavior, mocked tick behavior, analytics, dynamic universe behavior, API auth for paper controls, and no broker/order/AI safety scans.
   - They do not cover Phase 2E requirements such as DB initialization/table creation, empty DB response shapes, journal tick/candidate/trade persistence, journal API responses, or journal write failure isolation.

## Non-blocking issues

- Existing dashboard copy still says `Phase 2C`, and the visible dashboard has Open Positions, Closed Trades, Last Tick Candidate Decisions, Paper Universe, and Analytics sections, but no Journal/History section.
- Existing Redis snapshot copy accurately describes Redis as best-effort latest-state only, but that is not a substitute for the requested persistent journal.
- The Docker Compose file starts PostgreSQL before the backend via `depends_on`, but without health checks or application-level DB initialization, this does not currently validate database readiness for a future journal.

## Database/schema assessment

**Assessment: blocker for Phase 2E.**

- PostgreSQL exists in the Docker environment as `postgres:16-alpine`, with database/user/password configured and a named volume for persistence.
- The backend has `DATABASE_URL` in settings and `.env.example`, and `asyncpg` is listed in backend requirements.
- However, there is no database initialization path, no idempotent `CREATE TABLE IF NOT EXISTS` statements, no migrations, no journal schema, no indexes, and no table ownership around ticks/candidates/trades/rejections/performance.
- Because no schema exists, migration/schema risk is currently low in the narrow sense that nothing will mutate production data, but high for Phase 2E readiness because deploying a journal later will require a first schema introduction.

## Journal persistence assessment

**Assessment: not implemented.**

Requested data coverage:

| Requested data | Current state |
| --- | --- |
| ticks | Tick summary exists only as the `run_tick()` return value and latest in-memory state; not journaled. |
| candidates | Latest candidates are stored only in `_state["last_candidates"]`; not journaled. |
| fake entries | Entries are included in the current tick result and open positions; not journaled. |
| fake exits | Exits are included in the current tick result and closed trades list; not journaled. |
| universe snapshots | Current tick includes active universe fields; not journaled. |
| score details | Candidate dict includes score fields/components; not journaled. |
| rejection reasons | Candidate dict includes hard/scoring rejection reasons; not journaled. |
| P&L fields | Account status, positions, exits, and closed trades include P&L fields; not journaled. |

Journal write failure isolation cannot be verified because no journal write path exists. The existing simulator loop catches unexpected `run_tick()` exceptions, and `_save_state()` treats Redis snapshot failures as non-fatal, but that is not the requested PostgreSQL journal failure behavior.

## Simulator integration assessment

**Safety assessment: fake-money boundary remains intact. Phase 2E integration assessment: not implemented.**

- The simulator still states and behaves as a fake-money research simulator: no broker, no live trading, no real orders, and no real-money execution.
- Exits and entries remain in-memory `PaperAccount` operations only.
- The current `run_tick()` sequence is still: resolve active paper universe, fetch Polygon snapshots/previous closes, evaluate quality, collect catalysts, process fake exits, score/process fake entries, save latest state, then return the tick result.
- No broker integration, live trading, real order routing, external execution routing, or AI/LLM call path was found in the latest checkout.
- The requested “call journal persistence after `run_tick()` without changing trading logic” requirement is not satisfied because there is no journal persistence call.

## API assessment

**Existing API safety:** existing paper routes remain clearly paper-only.

- `/api/paper/status`, `/api/paper/positions`, `/api/paper/trades`, `/api/paper/universe`, `/api/paper/analytics`, and `/api/paper/dashboard` are GET/read endpoints over simulator state.
- `/api/paper/start`, `/api/paper/stop`, `/api/paper/reset`, `/api/paper/tick`, and `/api/paper/universe/refresh` remain token-protected POST controls for the fake-money simulator.
- Global `/api/status` still returns `execution_enabled: false`, `paper_trading_real_broker: false`, `live_trading_enabled: false`, and `broker_connected: false`.

**Requested Phase 2E journal API:** not implemented.

- No `/api/journal/*` routes exist, so read-only journal API behavior, response shapes, pagination/limits, and DB-empty handling cannot be validated.

## Dashboard assessment

**Existing dashboard safety:** safe, fake-money only.

- The dashboard displays an explicit research-only/fake-money warning and states no broker, no live trading, and no real orders.
- Existing controls call fake-money paper endpoints and require an admin token for state-changing actions.
- Existing tables/analytics are useful for current in-memory/latest-state monitoring.

**Requested Journal/History section:** not implemented.

- I found no Journal or History section in the dashboard.
- There is no UI that calls `/api/journal/*`, no persisted tick history table, no persisted rejection history, and no persisted performance history view.

## Test coverage assessment

Existing tests that remain useful:

- `pytest -q` passes: 124 tests passed with one third-party Starlette/httpx deprecation warning.
- Safety tests scan for broker SDK imports, order execution route/function patterns, and AI/LLM imports.
- Tick-level tests mock Polygon calls and patch simulator state persistence, so they avoid real Polygon calls in tests.
- Analytics and universe tests are documented as no-real-Polygon/no-real-order tests.

Requested Phase 2E coverage gaps:

- DB initialization/table creation: **missing**.
- Empty DB response shapes: **missing**.
- Tick persistence: **missing**.
- Candidate persistence: **missing**.
- Trade persistence: **missing**.
- Journal write failure does not crash simulator: **missing**.
- Journal APIs: **missing**.
- Explicit no-real-Polygon journal API tests: **missing** because journal APIs do not exist.
- No broker/order/AI imports: **covered for existing executable backend/paper surfaces**, but no Phase 2E journal module exists to scan.

## Operational/data-growth assessment

- Existing operational risk for tomorrow's current fake-money monitoring is bounded by current in-memory state plus best-effort Redis latest-state snapshot.
- Phase 2E historical data-growth concerns cannot be assessed from implementation details because there is no journal schema or queries.
- A future journal should include explicit retention, pagination/limits, indexes by tick time/session/symbol, and safeguards around unbounded candidate/tick accumulation before being used for full-day monitoring.
- Without Phase 2E persistence, tomorrow's monitoring cannot rely on historical journal data after backend restart or process failure.

## Fake-money / prohibited integration assessment

I did not find any added broker integration, live trading, real orders, real-money execution path, external execution routing, or AI/LLM calls in the latest checkout. The current application remains fake-money research-only.

## Safe to run tomorrow as fake-money simulation?

- **Yes, for the existing in-memory/best-effort Redis fake-money simulator**, assuming the same operational expectations as Phase 2D: it remains research-only, uses fake positions/trades, and does not route orders.
- **No, if the requirement is to run tomorrow with Phase 2E persistent journal/history**, because the requested PostgreSQL journal, journal APIs, persistence hooks, and dashboard Journal/History section are not implemented.

## Is any patch required before market hours?

- **Required if Phase 2E persistent journal/history is a market-hours requirement:** yes. A patch is required to add the DB schema/init path, best-effort journal writes after tick completion, read-only journal APIs, dashboard Journal/History UI, and tests.
- **Not required for safety of the existing fake-money simulator:** no broker/live/real-order/AI patch is needed; the current code remains within the fake-money research boundary.
