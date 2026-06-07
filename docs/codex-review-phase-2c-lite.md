# Codex Review — Phase 2C-Lite Dynamic Paper Universe

Review scope: latest Phase 2C-Lite changes only, introduced by commit `9c9d8e9` (`Implement Phase 2C Lite dynamic paper universe`).

## Critical issues

None found.

The Phase 2C-Lite changes keep the system inside the fake-money paper simulator boundary. I did not find broker integration, live trading, real order placement, real-money execution, external execution routing, AI/LLM calls, or any added path that can execute outside the research simulator.

## Non-blocking issues

- Polygon REST concurrency is intentionally simple for an MVP, but it is unbounded: a universe refresh starts one snapshot request and one previous-close request per base symbol concurrently, and a tick starts the same two-request pattern for up to `PAPER_MAX_SYMBOLS_PER_TICK` active symbols. This is acceptable for a small fake-money MVP if the configured Polygon plan tolerates the burst, but it is the main operational risk to watch.
- `GET /api/paper/universe` is public and can trigger a dynamic rebuild on cold start or TTL expiry. This matches the requested endpoint shape, and the protected manual refresh endpoint is correctly admin-gated, but public cold/TTL rebuilds can still consume Polygon REST quota.
- The dashboard universe panel is safe and clear, but it only shows the first 50 active symbols and a capped list of 10 fetch errors. That is acceptable for readability; the API response still contains the full active list and full error array.
- Frontend linting remains unavailable in a non-interactive way because the Next.js lint script prompts for initial ESLint setup in this repository. I did not treat that as a Phase 2C-Lite blocker.

## Universe builder assessment

The universe builder satisfies the Phase 2C-Lite requirements.

- It uses `PAPER_BASE_UNIVERSE` rather than the old 10-symbol `PAPER_DEFAULT_UNIVERSE` as the base list for dynamic selection.
- The default base universe expands to 100 configured symbols before caps, so the simulator is no longer limited to the old 10-symbol list.
- Base parsing uppercases, strips, deduplicates in first-seen order, and applies `PAPER_MAX_UNIVERSE_SIZE`.
- Dynamic selection caps active symbols with `PAPER_MAX_SYMBOLS_PER_TICK`.
- Refresh behavior supports TTL reuse, TTL rebuild, and explicit manual refresh through `force_refresh=True`.
- Safe fallback behavior is present when dynamic building is disabled, all Polygon fetches fail, no symbols survive filtering, or the simulator catches an unexpected universe-resolution exception.
- Ranking is deterministic and matches the requested ordering: tradable first, then absolute `change_percent` descending, then `volume_ratio` descending, then tighter `spread_percent` first.
- The builder records per-symbol fetch errors without failing the whole universe when at least one symbol succeeds.

## REST/API-load assessment

The REST load is acceptable for a Phase 2C-Lite MVP, with one important operational caveat.

Expected load pattern:

- Universe refresh: up to `2 * len(PAPER_BASE_UNIVERSE capped by PAPER_MAX_UNIVERSE_SIZE)` Polygon REST calls, because each symbol fetches snapshot and previous close.
- With defaults, that is approximately 200 REST calls per universe build for the 100-symbol default base universe.
- Tick market-quality fetch: up to `2 * PAPER_MAX_SYMBOLS_PER_TICK` Polygon REST calls, which is approximately 100 REST calls per tick with the default active cap of 50.
- News/catalyst collection may add more Polygon REST calls for tradable active symbols; that behavior predates this phase but becomes more visible with a larger active universe.
- TTL caching prevents rebuilding the 100-symbol dynamic universe every tick when `PAPER_DYNAMIC_REFRESH_SECONDS` remains at the default 300 seconds.

Concurrency/rate-limit risk:

- The implementation uses `asyncio.gather()` without a semaphore, so refreshes and ticks can burst many concurrent HTTP requests at once.
- There is no explicit Polygon 429 backoff, rate limiter, or shared HTTP client connection pool in this phase.
- For tomorrow's fake-money simulation, this is not a financial safety issue because failures are caught and result in skipped/fallback fake evaluation. It is an availability/quota risk only.
- If the configured Polygon plan has tight per-minute or concurrent-connection limits, reduce `PAPER_MAX_UNIVERSE_SIZE`, reduce `PAPER_MAX_SYMBOLS_PER_TICK`, increase `PAPER_DYNAMIC_REFRESH_SECONDS`, or avoid manual refresh spam during market hours.

## Simulator integration assessment

The simulator now uses the active dynamic universe.

- `run_tick()` resolves `get_active_paper_universe()` before fetching per-symbol market quality.
- If universe resolution fails unexpectedly, `run_tick()` falls back to the first `PAPER_MAX_SYMBOLS_PER_TICK` symbols from the deduplicated `PAPER_BASE_UNIVERSE` list, not the old 10-symbol default list.
- Tick results include universe metadata: active count, active symbols, last refreshed timestamp, and refresh reason.
- Entries and exits remain fake `PaperAccount` operations only. No broker, order routing, live trading, real-money execution, AI/LLM call, or external execution path was added.

## API endpoint assessment

The Phase 2C-Lite API endpoints are correct.

- `GET /api/paper/universe` returns the active universe and may build or refresh it according to the same cache/TTL behavior as the simulator.
- `POST /api/paper/universe/refresh` calls `build_dynamic_universe(force_refresh=True)` and is protected with `ADMIN_API_TOKEN` via the existing `require_admin_token` dependency.
- `/api/paper/dashboard` exposes the cached universe without forcing a rebuild, which keeps dashboard polling from continuously triggering Polygon refresh work.
- Existing admin paper controls (`start`, `stop`, `reset`, `tick`) remain protected.

## Dashboard assessment

The dashboard universe section is safe and clear for Phase 2C-Lite.

- The top-level disclaimer still states research-only fake-money simulation, no broker, no live trading, and no real orders.
- The page subtitle/footer still exposes fake-money mode and broker/live-trading false status.
- The universe section labels the feature as dynamic, ranked by movement, and fake-money only.
- The manual universe refresh button reuses the existing password-style `ADMIN_API_TOKEN` field and sends only an admin POST to the protected refresh endpoint.
- Server-provided symbols and errors are rendered as React text, not raw HTML.
- The panel presents active count, max per tick, refresh reason, error count, last refreshed time, active symbols, and expandable fetch errors.

## Test coverage assessment

Phase 2C-Lite backend test coverage is good.

Covered:

- base universe parsing, whitespace handling, uppercasing, and deduplication;
- `PAPER_MAX_UNIVERSE_SIZE` cap;
- dynamic-disabled fallback to the base universe;
- active universe cap via `PAPER_MAX_SYMBOLS_PER_TICK`;
- ranking preference for larger absolute change;
- ranking preference for tradable symbols over non-tradable symbols;
- eligibility filtering for low day volume and low absolute change;
- TTL cache reuse;
- force/manual refresh bypassing cache;
- `get_cached_universe()` behavior before and after build;
- per-symbol failure handling;
- simulator tick universe metadata;
- public `GET /api/paper/universe` response shape;
- protected refresh endpoint rejecting missing/wrong tokens and accepting the correct token;
- dashboard universe field presence.

No real Polygon calls were required by these tests. Dynamic tests patch `get_ticker_snapshot` and `get_previous_close`; endpoint tests disable dynamic building where necessary; simulator tests patch universe resolution and market-data dependencies.

Coverage gaps are non-blocking:

- There is no direct test for spread tie-break ranking or volume-ratio tie-break ranking, although the implementation is straightforward.
- There is no explicit test asserting that `GET /api/paper/universe` can trigger TTL refresh after expiration.
- There is no test for 429/backoff behavior because no rate limiter/backoff exists in this MVP phase.

Commands run:

- `python -m pytest tests/test_universe.py` from `backend/`: passed (`20 passed`, `1 warning`).
- `python -m pytest backend/tests/test_universe.py` from `backend/`: failed because the path was wrong for that working directory; rerun with `tests/test_universe.py` passed.

## Safe to run tomorrow as fake-money simulation?

Yes. Phase 2C-Lite appears safe to run tomorrow as fake-money research simulation.

The simulator now evaluates a larger dynamic universe while preserving the research-only boundary. Failures in dynamic universe construction degrade to bounded fake-money fallback evaluation, not to live execution. No broker integration, live trading, real orders, real-money execution, external execution path, or AI/LLM call was introduced.

This conclusion applies only to fake-money simulation. It is not approval for live trading or real-money execution.

## Is any patch required before market hours?

No blocking patch is required before market hours for fake-money simulation.

Operational recommendation: before market hours, confirm the configured Polygon plan can tolerate the default burst pattern. If not, use environment configuration to lower `PAPER_MAX_UNIVERSE_SIZE` and/or `PAPER_MAX_SYMBOLS_PER_TICK`, and avoid repeated manual refreshes. That is configuration/operations hygiene, not a required safety patch.
