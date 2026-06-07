# Codex Review — Phase 2E Persistent Paper Journal Final

Reviewed commit: `0bb43d9ad6ca7a2df838b36873aa080c82c6c777` on the local `work` branch, which matches the user-provided `origin/main` target commit `0bb43d9`.

Review scope: current Phase 2E persistent paper journal implementation only. No code changes, feature additions, broker integration, live trading, real orders, strategy changes, or AI/LLM calls were made during this review.

## Executive conclusion

Phase 2E is now implemented. The repository contains a PostgreSQL-backed, best-effort persistent paper journal with idempotent table creation, simulator integration, read-only `/api/journal/*` endpoints, dashboard visibility, and broad tests. It is safe enough to run tomorrow as a fake-money simulation if `DATABASE_URL` points to the intended Postgres database and operators confirm `/api/journal/status` reports `enabled: true` and `tables_ready: true` before relying on the persisted history.

No blocking patch is required before market hours for fake-money monitoring. The main remaining risks are operational/data-quality issues rather than live-money safety risks.

## Critical issues

None found for the requested fake-money Phase 2E scope.

I did not find broker integration, live trading, real order execution, external execution routing, or AI/LLM calls added as part of this phase. The implementation continues to label the simulator and journal as research-only/fake-money and the safety tests still pass.

## Non-blocking issues

1. **Historical performance breakdowns will lose catalyst/score attribution for exits.** Entry journal rows store `catalyst_type` and `total_score`, but exit rows do not populate those fields. The `/api/journal/performance` endpoint calculates catalyst-type and score-bucket P&L from exit rows only, so the buckets will likely collapse into `unknown` / `no_score` even when entry candidates had score details. This does not block raw trade/P&L persistence, but it limits tomorrow's analysis quality.

2. **Postgres startup race can leave the journal disabled until app restart.** `init_journal()` runs at FastAPI startup and sets the module-level enabled flag from `init_tables()`. If Postgres is temporarily unavailable during startup, later writes remain disabled unless the app restarts or code explicitly reinitializes the journal. Docker `depends_on` orders containers but does not guarantee Postgres readiness.

3. **Disabled/error response shapes are not fully uniform across read endpoints.** Normal list endpoints return arrays, while disabled/error states return `{"error": ...}`. The dashboard tolerates this for the subset it calls, and tests allow either list or error shapes, but API clients need to handle both.

4. **No retention policy exists.** This is acceptable for a short fake-money run, but long-running monitoring will accumulate ticks, candidates, trades, and universe snapshots indefinitely.

5. **Some high-volume query paths may degrade over time.** See the operational/data-growth section for index and limit details.

## Database/schema assessment

The persistent journal schema exists in `backend/paper/db.py` and creates four tables with `CREATE TABLE IF NOT EXISTS`:

- `paper_ticks`
- `paper_candidates`
- `paper_trades_journal`
- `paper_universe_snapshots`

Initialization is idempotent because table and index DDL use `IF NOT EXISTS`. It is non-fatal because `get_pool()` and `init_tables()` catch exceptions and return `None`/`False` instead of raising.

`DATABASE_URL`/Postgres usage is correct at a basic level:

- `settings.DATABASE_URL` is defined as an environment-backed setting.
- `asyncpg` is included in backend requirements.
- `get_pool()` reads `settings.DATABASE_URL` and returns `None` with `DATABASE_URL not configured` if absent.
- `.env.example` includes a Postgres URL.
- Docker Compose includes a Postgres service and backend dependency on Postgres.

Schema coverage is sufficient for the requested Phase 2E journal:

- Ticks: yes, including tick timings, counts, universe count/reason, errors count, account cash/equity, realized/unrealized/total P&L, and total P&L percent.
- Candidates: yes, including symbol, eligibility, action, rejection reason, market-quality attributes, catalyst fields, score threshold/pass, score component JSON, positive/negative reason JSON, and decision reason.
- Trades: yes, entry and exit events, virtual long side, entry/exit prices, shares/cost basis for entries, P&L/P&L percent/exit reason for exits, and timestamps.
- Universe snapshots: yes, including active count, max symbols per tick, refresh reason, active symbol JSON, and errors JSON.

Schema risks:

- There is no explicit foreign key from candidates/trades/universe snapshots to `paper_ticks.tick_id`. This avoids write coupling and is acceptable for best-effort logging, but it means referential integrity is not enforced.
- Exit trade rows omit `shares`, `cost_basis`, `catalyst_type`, and `total_score`, which limits historical performance attribution.
- Candidate ordering by `created_at DESC` has no dedicated created-at index; trades/ticks/universe do.
- Rejection aggregation scans candidate rows with non-null `rejection_reason`; there is no rejection-reason index.
- Performance reads all exit rows without a date range or limit.

## Journal persistence assessment

The persistent paper journal is actually implemented in `backend/paper/journal.py`.

Persistence coverage:

- **Ticks:** persisted to `paper_ticks` with counts, universe metadata, error count, cash/equity, and P&L fields.
- **Candidates:** persisted to `paper_candidates` with rejection reason, action, market quality, catalyst type/count, score details, and decision explanations.
- **Fake entries:** persisted to `paper_trades_journal` as `event='entry'` with entry price, shares, cost basis, catalyst type, total score, and opened timestamp.
- **Fake exits:** persisted to `paper_trades_journal` as `event='exit'` with entry price, exit price, P&L, P&L percent, exit reason, and closed timestamp.
- **Universe snapshots:** persisted to `paper_universe_snapshots` when a universe object is provided.
- **Score details:** persisted on candidates as scalar score fields and JSON score/reason fields; entry rows also include total score.
- **Rejection reasons:** persisted on candidate rows.
- **P&L fields:** persisted on tick rows and exit trade rows.

Best-effort safety is implemented:

- If the journal is disabled, writes return a skipped result.
- If the pool is missing, writes return a skipped result.
- Write exceptions are caught, logged as warnings, and returned as `{"ok": false, "error": ...}`.
- The simulator wraps journal persistence in an additional `try`/`except`, so journal failures cannot crash `run_tick()`.

The write is transactional per tick. That preserves consistency across the tick's journal rows, but also means one malformed row can roll back all journal rows for that tick. Because the exception is caught, this is a data-completeness risk, not a simulator-crash risk.

## Simulator integration assessment

`run_tick()` now includes journal support without changing core strategy logic:

- The result dictionary is initialized with the same simulation fields and later receives a `journal` field.
- Universe resolution, market-quality fetching, catalyst collection, exit logic, scoring, and entry logic remain upstream of the journal write.
- The state save and `last_tick_at`/`last_candidates` updates occur before journal persistence.
- Journal persistence is called after tick completion with `result`, `get_status()`, and `get_cached_universe()`.
- Journal persistence is wrapped in `try`/`except` and writes only to the returned `result["journal"]` object on failure.

This satisfies the requirement that journal persistence runs after tick completion and does not alter entry/exit strategy decisions.

## API assessment

All requested read-only endpoints exist under `backend/api/journal.py`:

- `GET /api/journal/status`
- `GET /api/journal/summary`
- `GET /api/journal/ticks`
- `GET /api/journal/candidates`
- `GET /api/journal/trades`
- `GET /api/journal/rejections`
- `GET /api/journal/performance`

The API router is included in FastAPI startup wiring. The endpoint module exposes only `@router.get(...)` handlers; no journal POST/PUT/DELETE mutation endpoints were added.

Endpoint behavior is generally appropriate for tomorrow's fake-money monitoring:

- Status reports enabled/database/tables/error state.
- Summary reports counts and first/last tick timestamps.
- Ticks, candidates, trades, and rejections use bounded limits.
- Candidates support `tick_id` and `symbol` filters.
- Performance returns an empty-shape object when there are no closed trades.

Read-only API concerns:

- Disabled state returns a dict with `error`, while success for list endpoints returns a list.
- Performance has no time range or hard cap and will scan all exit rows.
- Performance attribution by catalyst type and score bucket is weakened by missing `catalyst_type`/`total_score` on exit rows.

## Dashboard assessment

The dashboard has a visible Journal/History section. It fetches journal status, summary, recent ticks, and performance, then renders:

- journal enabled/disabled status,
- DB connected/not-connected status,
- last journal error,
- session summary counts,
- historical performance when closed trades exist,
- recent tick history with symbols, universe size, entries, exits, errors, cash, and P&L.

This is sufficient to see whether the persistent journal is enabled and whether ticks are being recorded during tomorrow's fake-money run.

## Test coverage assessment

The backend test suite passes: `161 passed, 1 warning` from `python -m pytest` in `backend`.

Coverage present:

- Journal helper conversion/date parsing tests.
- Journal disabled/skipped write behavior.
- No-pool skipped write behavior.
- Journal status shape tests.
- API endpoint tests for all requested `/api/journal/*` endpoints.
- Disabled-state API tests for representative endpoints.
- Limit/filter behavior tests for ticks, candidates, trades, and rejections.
- DB helper state tests.
- Simulator `run_tick()` tests elsewhere mock Polygon calls rather than making real Polygon requests.
- Safety invariant tests scan for broker SDK imports, order execution routes/functions, and AI/LLM SDK imports.

Coverage gaps against the requested list:

- There is no in-repo Postgres integration test that actually creates the tables and verifies `init_tables()` DDL against a live empty database. The implementation exists and is idempotent by inspection, but the automated tests mostly cover module behavior and API shapes without requiring a database.
- There is no direct test that a journal write failure after pool acquisition does not raise to the simulator, although `persist_tick_result()` and `run_tick()` both visibly catch exceptions.
- There is no direct test that `persist_tick_result()` writes tick/candidate/trade/universe rows into a real database and reads them back.
- There is no direct test asserting `run_tick()` result contains a `journal` field; current run-tick tests exercise the function but do not specifically assert that field.
- Empty DB response shapes are partially covered by endpoint structure tests when no DB is available or when queries return empty lists, but not by a controlled live empty Postgres fixture.

## Operational/data-growth assessment

For one day of fake-money monitoring, data volume should be manageable: with a 60-second polling interval and up to 50 symbols per tick, a regular 6.5-hour session is roughly 390 tick rows, up to about 19,500 candidate rows, plus trade and universe snapshot rows. This is well within Postgres capacity.

Data-growth concerns if the simulator runs for many days:

- No retention/deletion/archive strategy.
- No partitioning by date.
- No index on `paper_candidates.created_at`, although `/api/journal/candidates` orders by created time when unfiltered.
- No composite index on `paper_candidates(symbol, created_at DESC)` or `paper_candidates(tick_id, created_at DESC)` for filtered recent candidate queries.
- No index on `paper_candidates(rejection_reason)` for rejection aggregation.
- No index on `paper_trades_journal(event, created_at DESC)` or `paper_trades_journal(event)` for exit-only performance queries.
- `/api/journal/performance` has no date range and reads all closed exits.
- Universe snapshots store full active symbol arrays every tick. This is fine for 150 symbols/day-scale usage, but it is repetitive storage.

These are not market-hours blockers for tomorrow's fake-money simulation, but they should be addressed before longer unattended retention or higher-frequency polling.

## Whether Phase 2E is now implemented

Yes. Phase 2E is now implemented in the repository:

- PostgreSQL/`DATABASE_URL` backed async pool management exists.
- Idempotent schema creation exists.
- Persistent journal writes exist for ticks, candidates, fake entries, fake exits, and universe snapshots.
- Score details, rejection reasons, and P&L fields are captured in the relevant tables.
- Writes are best-effort and non-fatal.
- `run_tick()` integrates persistence after simulation work and exposes journal status in the tick result.
- Read-only journal API endpoints exist.
- The dashboard exposes Journal/History.
- Tests cover most API and safety behavior.

## Whether Phase 2E is safe to run tomorrow as fake-money simulation

Yes, with operational verification.

Before market open, verify:

1. `DATABASE_URL` points to the expected Postgres database.
2. Backend startup logs show the paper journal initialized, or `GET /api/journal/status` returns `enabled: true`, `database_connected: true`, and `tables_ready: true`.
3. After a manual fake-money tick, `GET /api/journal/summary` shows `total_ticks` incrementing and the dashboard Journal/History panel shows recent tick rows.

If those checks fail, the simulator should still continue in memory/Redis-best-effort mode, but persistent journal history will not be reliable until Postgres initialization succeeds.

## Whether any patch is required before market hours

No patch is required before market hours for fake-money simulation.

Recommended follow-up after tomorrow's run:

1. Preserve catalyst/score attribution on exit rows or join exits to their corresponding entry/candidate records for performance calculations.
2. Add a live Postgres integration test for `init_tables()` and `persist_tick_result()` round-trips.
3. Add an explicit `run_tick()` journal-field assertion test.
4. Add candidate/trade indexes and date-range filters for longer retention.
5. Add an operational readiness check or retry path so Postgres startup races do not leave the journal disabled until restart.
