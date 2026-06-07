# Codex Review — Phase 2E Correction Patch

Review date: 2026-06-07

Scope reviewed: latest checked-out `BBlankGit/microtrading-app` workspace after the stated Phase 2E correction request. I reviewed only the Phase 2E persistent paper journal requirements and did not change application code.

## Critical issues

1. **Phase 2E persistent paper journal is still not implemented in this checkout.**
   - I found no journal persistence module, no PostgreSQL repository/service, no journal database models, and no `paper_journal` or equivalent package.
   - `DATABASE_URL` exists only as a setting and `.env.example` value, and `asyncpg` is present in requirements, but no backend code uses `DATABASE_URL` for journal initialization, reads, or writes.
   - `backend/database/__init__.py` is empty, so there is no database initialization hook there.

2. **Database initialization/table creation is missing.**
   - There are no `CREATE TABLE`, `CREATE INDEX`, migration, or idempotent schema-init statements for ticks, candidates, trades, rejections, universe snapshots, score details, or performance/P&L history.
   - PostgreSQL exists in Docker Compose, but the backend currently only depends on the service; it does not wait for readiness, initialize schemas, or expose journal DB status.

3. **The requested `/api/journal/*` read-only endpoints are missing.**
   - I found no `/api/journal/status`, `/api/journal/summary`, `/api/journal/ticks`, `/api/journal/candidates`, `/api/journal/trades`, `/api/journal/rejections`, or `/api/journal/performance` routes.
   - `backend/main.py` includes only the existing catalysts, data status, market, paper, quality, stream, and universe routers.

4. **`run_tick()` does not expose a journal field and does not call journal persistence after tick completion.**
   - `run_tick()` returns tick metadata, exits, entries, candidates, errors, and universe fields, but no `journal` status/object.
   - After processing the tick, it calls only `_save_state()` for the existing best-effort Redis/latest-state snapshot, then updates in-memory state.
   - Because no journal write is attempted, there is no post-tick persistent history and no visible journal success/failure signal.

5. **Requested Phase 2E test coverage is absent.**
   - Existing tests still pass, but they cover the pre-existing simulator/account/universe/analytics/safety behavior, not a persistent paper journal.
   - There are no tests for DB init/table creation, journal-disabled behavior when `DATABASE_URL` is missing, best-effort journal write failures, tick/candidate/trade/universe persistence, empty DB API shapes, journal API endpoints, or a `run_tick()` journal field.

## Non-blocking issues

- The dashboard still labels the simulator as `Phase 2C`, despite later phase work.
- The dashboard has useful account, controls, positions, closed trades, last-tick candidates, paper universe, and analytics sections, but no visible Journal/History section.
- Docker Compose provides a PostgreSQL service and persistent volume, but without application schema initialization or journal endpoints it is unused by Phase 2E.
- The existing Redis snapshot behavior is explicitly best-effort latest-state only; it should not be mistaken for the requested durable historical journal.

## Database/schema assessment

**Assessment: not implemented / blocking for Phase 2E.**

- `DATABASE_URL` is defined in settings, `.env.example` provides a PostgreSQL-style URL, and `asyncpg` is included in backend requirements.
- I found no actual database connection code, pool lifecycle, startup/shutdown DB hook, table creation function, or migration path.
- I found no tables for:
  - ticks
  - candidates
  - fake entries
  - fake exits
  - universe snapshots
  - score details
  - rejection reasons
  - P&L/performance fields
- Idempotency cannot be validated because there is no table-creation implementation.
- Schema/indexing risk remains unresolved. A future implementation should define bounded retention, pagination-friendly indexes, and at minimum time/session/symbol indexes before full-day fake-money monitoring.

## Journal persistence assessment

**Assessment: not implemented.**

| Requested journal data | Current state in this checkout |
| --- | --- |
| ticks | Present only in the `run_tick()` return object; not persisted to PostgreSQL. |
| candidates | Present only in the current tick result and `_state["last_candidates"]`; not persisted. |
| fake entries | Present in the tick result and in-memory/Redis account snapshot; not journaled. |
| fake exits | Present in the tick result and account trades; not journaled. |
| universe snapshots | Active universe metadata is attached to the tick result; not journaled. |
| score details | Candidate score fields/components are generated; not journaled. |
| rejection reasons | Candidate hard/scoring rejection reasons are generated; not journaled. |
| P&L fields | Status, positions, exits, and trades compute virtual P&L; no historical DB persistence. |

Best-effort write isolation for a PostgreSQL journal cannot be validated because no journal write path exists. The existing Redis `_save_state()` catches failures and falls back to memory state, but that only covers the latest-state snapshot and does not satisfy the requested persistent journal behavior.

## Simulator integration assessment

**Assessment: existing simulator remains fake-money safe; Phase 2E integration is missing.**

- The simulator remains explicitly research-only and fake-money only: no broker, no live trading, no real orders, and no real-money execution.
- Strategy flow appears unchanged from the existing simulator: resolve universe, fetch market quality, collect catalysts for tradable symbols, process fake exits, score/process fake entries, save state, and return the tick result.
- Candidate objects still include score details and rejection reasons, and entry/exit result objects include basic trade/P&L fields.
- However, `run_tick()` does not include a `journal` field and does not perform a best-effort persistent journal write after the tick.
- Because no Phase 2E persistence hook exists, there is no evidence that the correction patch was applied in this checkout.

## API assessment

**Existing API:** safe within the fake-money simulator boundary.

- Existing `/api/paper/*` routes remain the only paper-simulator surface.
- Read-only paper endpoints expose current status, positions, trades, universe, analytics, and dashboard data.
- State-changing fake-money controls remain token-protected POST routes.
- Global `/api/status` still reports execution disabled, paper real-broker trading disabled, live trading disabled, and broker disconnected.

**Requested Phase 2E journal API:** not implemented.

| Endpoint | Present? | Assessment |
| --- | --- | --- |
| `/api/journal/status` | No | Missing. |
| `/api/journal/summary` | No | Missing. |
| `/api/journal/ticks` | No | Missing. |
| `/api/journal/candidates` | No | Missing. |
| `/api/journal/trades` | No | Missing. |
| `/api/journal/rejections` | No | Missing. |
| `/api/journal/performance` | No | Missing. |

Read-only behavior, empty-DB response shapes, pagination/limits, and DB error handling cannot be validated until these endpoints exist.

## Dashboard assessment

**Assessment: no visible Journal/History section.**

- The dashboard remains fake-money safe and includes a prominent no-broker/no-live/no-real-orders disclaimer.
- The visible sections are Session Readiness, Account, Controls, Open Positions, Closed Trades, Last Tick Candidate Decisions, Paper Universe, Analytics, and footer status text.
- I found no Journal/History section, no persisted history table, and no frontend fetches for `/api/journal/*`.

## Test coverage assessment

`pytest -q` passes for the existing backend test suite, but the requested Phase 2E coverage is missing.

| Required test area | Covered? | Notes |
| --- | --- | --- |
| DB init/table creation | No | No DB init/schema code or tests found. |
| journal disabled when `DATABASE_URL` missing | No | No journal module/status behavior exists. |
| journal write failure does not raise | No | Existing Redis failure handling is not journal-specific. |
| tick persistence | No | No persistent tick table/write test. |
| candidate persistence | No | No persistent candidate table/write test. |
| trade persistence | No | No persistent fake entry/exit table/write test. |
| universe persistence | No | No persisted universe snapshot test. |
| empty DB response shapes | No | No `/api/journal/*` endpoints exist. |
| journal API endpoints | No | Endpoints missing. |
| simulator `run_tick()` journal field | No | Field missing. |
| no real Polygon calls | Partially | Existing tick/universe tests mock Polygon paths; no journal-specific tests exist. |
| no broker/order/AI imports | Yes for current scanned surfaces | Existing safety tests scan backend API/catalyst/core/data/main code; no new Phase 2E journal code exists to scan. |

## Operational/data-growth assessment

**Assessment: not ready for Phase 2E historical monitoring.**

- Existing fake-money monitoring can still use in-memory state plus best-effort Redis latest-state snapshot, but historical journal data will not survive backend restart because it is not written.
- Since no schema exists, there are no indexes, query limits, partitioning/retention strategy, or table-growth controls.
- For tomorrow's fake-money monitoring, this means:
  - safe from a real-money execution standpoint,
  - usable for current-state observation,
  - not reliable for durable tick/candidate/trade/rejection/performance history.
- A proper journal implementation should cap endpoint limits, index by `tick_at`/session/symbol/action, store compact JSON details where appropriate, and define a retention/export plan before extended monitoring.

## Prohibited integration assessment

I did not find broker integration, live trading, real orders, real-money execution, external execution routing, or AI/LLM calls added by the current checkout. The app remains inside the fake-money research simulator boundary.

## Whether Phase 2E is now implemented

**No. Phase 2E is not implemented in this checkout.**

The missing persistent paper journal remains missing: no PostgreSQL schema/init, no journal write service, no best-effort post-tick persistence, no journal field on `run_tick()`, no `/api/journal/*` endpoints, no dashboard Journal/History section, and no Phase 2E-specific tests.

## Whether Phase 2E is safe to run tomorrow as fake-money simulation

- **Safe as the existing fake-money simulator:** yes. I found no broker, live trading, real order, external routing, or AI/LLM execution path.
- **Safe as a Phase 2E persistent-journal simulation:** no. The journal is absent, so tomorrow's run would not produce durable historical journal data.

## Whether any patch is required before market hours

- **Required if Phase 2E journal/history is required before market hours:** yes. A patch is required to implement idempotent PostgreSQL schema initialization, best-effort journal writes, read-only journal APIs, dashboard Journal/History visibility, and the requested tests.
- **Not required for fake-money safety alone:** no. The current simulator remains fake-money only and does not add prohibited execution integrations.
