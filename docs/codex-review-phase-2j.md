# Codex Review — Phase 2J Market-Wide Movers Discovery

Date: 2026-06-07  
Scope reviewed: latest commit only (`e07eb9c Implement Phase 2J market-wide movers discovery`).  
Review mode: code review only; no feature or strategy changes made.

## Critical issues

None found.

Phase 2J does not add broker integration, live trading, real orders, real-money execution, or AI/LLM calls. The new discovery layer is REST-data-only and feeds symbols into the existing paper universe path.

## Non-blocking issues

1. **Manual dashboard discovery refresh can make the discovery endpoint fresher than the cached universe panel.**
   - The dashboard button posts to `POST /api/paper/discovery/refresh`, then refreshes the dashboard data.
   - The dashboard source for the Market Discovery panel is `dashboard.universe.discovery`, and `/api/paper/dashboard` uses `get_cached_universe()` rather than rebuilding the universe.
   - Result: the button may successfully refresh discovery but the panel may continue to show the old universe-embedded discovery metadata until a universe refresh or simulator tick rebuilds the universe.
   - This is a display freshness issue, not a trading-safety issue.

2. **API load is higher than prior phases when discovery is enabled.**
   - A cold universe build can fetch gainers and losers, then fetch snapshot and previous-close data for up to `PAPER_MAX_UNIVERSE_SIZE` symbols.
   - With defaults, this is up to 2 discovery calls plus 300 quality calls before the active universe is capped to 50 symbols, followed by tick-time quality calls for active symbols.
   - The TTL/cache behavior makes this acceptable for fake-money monitoring if manual refreshes are used sparingly, but it is worth watching Polygon plan limits and request latency during market open.

3. **Discovered movers are prioritized ahead of base symbols before the merged candidate pool cap.**
   - The merge order is discovered symbols first, then `PAPER_BASE_UNIVERSE`, deduplicated, then capped by `PAPER_MAX_UNIVERSE_SIZE`.
   - This is safe because all candidates still pass quality filtering and the active tick universe remains capped, but with many discovered symbols it can push later base symbols out of the pre-filter candidate pool.

## Discovery implementation assessment

- **Disabled mode:** safe. When `PAPER_MARKET_DISCOVERY_ENABLED` is false, discovery returns an explicit disabled payload with empty sources and empty symbols.
- **Endpoint failures:** safe. `PolygonError` failures for gainers/losers are caught per-source and recorded in the returned `errors` list. Unexpected exceptions are also caught and recorded.
- **404/permission handling:** safe. Polygon HTTP 403 and 404 responses are converted into `PolygonError`, and discovery catches those errors rather than crashing.
- **Cache/TTL:** safe. Discovery uses module-level `_cache` / `_cache_time` and returns cached results while within `PAPER_MARKET_DISCOVERY_REFRESH_SECONDS` unless force refresh is requested.
- **Force refresh:** safe. Force refresh bypasses the discovery cache only when called explicitly through `force_refresh=True`, which is wired to protected refresh paths.
- **No broker/order/AI behavior:** safe. The discovery file imports config, Polygon REST client, logging, regex/time/date utilities only; no broker or AI/LLM imports were added.
- **Most active:** acceptable. The implementation does not call a nonexistent Polygon most-active endpoint; it emits a warning when most-active is enabled.

## Universe integration assessment

- Discovery expands the candidate pool by merging discovered movers with `PAPER_BASE_UNIVERSE`; it does not directly create positions.
- Symbols are deduplicated during discovery source merge and again during universe candidate-pool merge.
- The merged pool still goes through existing quality fetches, eligibility filters, ranking, and active-symbol capping.
- `active_symbols` remains capped by `PAPER_MAX_SYMBOLS_PER_TICK`.
- Existing entry logic still applies score thresholding, catalyst requirements, bearish catalyst rejection, account `can_enter` checks, max positions, and max trades per day.
- Take-profit, stop-loss, max-hold, and paper position sizing logic were not changed by Phase 2J.

## API assessment

- `GET /api/paper/discovery` exists and returns cached/stale-aware discovery data without requiring admin auth.
- `POST /api/paper/discovery/refresh` exists and is protected by `require_admin_token`.
- `POST /api/paper/tick` remains protected by `require_admin_token` and returns discovery metadata inside the tick result.
- `GET /api/paper/universe` includes a `discovery` summary object.
- `GET /api/paper/dashboard` includes universe data from the universe cache, including discovery metadata when the universe has been built.

## Dashboard assessment

- The new Market Discovery section is clear and explicitly states that discovery expands the candidate pool only and does not bypass quality gates, scoring, sentiment checks, or fake-money limits.
- It displays enabled/disabled status, refresh reason, discovered count, error count, warning count, and discovered symbols.
- It exposes a manual refresh button that requires the admin token entered in the dashboard UI.
- Non-blocking clarity issue: after manual discovery refresh, the dashboard panel can lag because it reads discovery metadata from the cached universe rather than directly from the discovery refresh response or `GET /api/paper/discovery`.

## Test coverage assessment

Covered by Phase 2J tests:

- Discovery disabled shape.
- Discovery cache reuse.
- Force refresh bypassing cache.
- Gainers endpoint failure fallback.
- Most-active warning path.
- Discovery deduplication.
- Universe merge behavior.
- Universe result includes discovery metadata.
- API routes for `GET /api/paper/discovery` and `POST /api/paper/discovery/refresh`.
- Refresh auth dependency presence.
- Normalization for mover snapshots.
- Static safety checks against broker/order imports in discovery.
- Mocked Polygon calls in tests; no real Polygon calls were required for the reviewed test run.

Coverage gaps / weaknesses:

- The simulator tick discovery metadata test is weak; it effectively asserts only that status is a dict and does not execute `run_tick()` under a mocked universe-discovery failure scenario.
- There is no direct test that `POST /api/paper/tick` response includes discovery metadata.
- There is no direct test for dashboard refresh staleness or display behavior.
- No exact regression test compares take-profit / stop-loss / max-hold / position sizing code paths before and after Phase 2J, though the Phase 2J diff does not alter those paths.

## Operational/API-load assessment

- API-load risk is acceptable for tomorrow's fake-money monitoring if the simulator is run with default TTLs and manual refreshes are limited.
- The largest load risk is universe refresh: discovery can increase the quality-fetch candidate pool up to `PAPER_MAX_UNIVERSE_SIZE`, and each candidate currently triggers both snapshot and previous-close calls.
- The active tick universe remains capped to `PAPER_MAX_SYMBOLS_PER_TICK`, which bounds recurring tick evaluation after universe selection.
- Discovery TTL prevents repeated gainers/losers bursts from normal reads.
- Endpoint failures degrade to empty discovery/errors instead of crashing the simulator, so Polygon permission issues should not block fake-money operation.

## Safety assessment

- No broker integration was added.
- No live trading path was added.
- No real order path was added.
- No AI/LLM path was added.
- Strategy execution logic is unchanged in the reviewed Phase 2J diff:
  - no real order path;
  - no broker path;
  - no take-profit / stop-loss / max-hold changes;
  - no position sizing changes.
- Discovery does not bypass quality gates, scoring, catalyst sentiment checks, account limits, max positions, or max trades per day.
- All Phase 2J data-fetch failures reviewed are non-fatal to paper simulation.

## Safe to run tomorrow as fake-money simulation?

Yes. Phase 2J is safe to run tomorrow as a fake-money simulation, assuming the team monitors Polygon request counts/latency and avoids repeatedly pressing force-refresh endpoints during market open.

## Patch required before market hours?

No blocking patch is required before market hours.

Recommended optional follow-ups after market monitoring:

1. Improve the simulator tick resilience test so it actually runs `run_tick()` with mocked universe/discovery conditions.
2. Add an API test asserting `POST /api/paper/tick` includes discovery metadata.
3. Consider making the dashboard Market Discovery refresh display the returned refresh payload immediately, or fetch `GET /api/paper/discovery` directly, so the panel is not tied to cached universe metadata.
4. Consider adding lightweight request counters/timing logs around universe refresh during the first monitored session.
