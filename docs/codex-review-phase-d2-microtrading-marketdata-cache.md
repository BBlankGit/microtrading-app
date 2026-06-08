# Codex Review — Phase D2 Microtrading Shared Market-Data Cache Integration

Reviewed checkout: `6c23ce2` (`work` branch), latest visible patch in this repository.

Scope: review only whether the current Phase D2 work integrates the Phase D1 shared `marketdata` cache into the microtrading paper simulator and related monitoring surfaces. No code changes were made.

## Critical issues

1. **D2 cache-first simulator integration is not present in the latest checkout.**
   - `backend/paper/simulator.py` still fetches normal per-symbol market quality by calling `polygon_client.get_ticker_snapshot(sym)` and `polygon_client.get_previous_close(sym)` directly for every evaluated symbol, then passes the results to `evaluate_market_quality(...)`.
   - I found no simulator-side read from `marketdata.cache.read_symbol(...)`, no conversion from `marketdata.models.SymbolPayload` into the existing quality schema, and no fresh/stale decision before normal candidate evaluation.
   - Impact: requirement 1 is not satisfied; normal tick evaluation is not cache-first.

2. **Fresh cache hits cannot avoid direct Polygon calls because the simulator does not consult the cache.**
   - The Phase D1 cache layer can read Redis snapshots by symbol, but that read API is currently used by the marketdata API endpoints, not by the paper simulator tick path.
   - Impact: requirement 2 is not satisfied; even if Redis contains a fresh `market:snapshot:<symbol>` payload, the simulator still follows the existing direct Polygon REST path.

3. **Missing/stale cache fallback behavior is not implemented or observable in the simulator.**
   - There is no simulator configuration for “use cache first, then fallback to Polygon when stale/missing,” and no explicit fallback result state such as `cache_hit`, `cache_miss`, `cache_stale`, `fallback_polygon_success`, or `fallback_polygon_failed`.
   - Impact: requirement 3 is not satisfied; fallback continues to exist only because the old direct Polygon path remains the only path.

4. **Fresh-data enforcement cannot be proven.**
   - Because the simulator has no cache freshness check, no `fresh_required` gate, and no stale/missing metadata in the entry decision, stale or missing cache cannot be distinguished from direct Polygon success/failure.
   - If Polygon fallback fails, the current direct-call path records an error and skips that symbol, which prevents entries for that symbol. However, that is not a D2 fresh-data guarantee; it is the pre-existing exception path.
   - Impact: requirement 4 is only partially satisfied by existing error handling, not by explicit D2 stale-data controls.

5. **Candidate, monitoring, readiness, and journal/detail visibility is missing.**
   - Candidate output currently includes quality, catalyst, scoring, momentum, and daily-loss fields, but not `marketdata_source`, `marketdata_age_seconds`, `marketdata_stale`, cache hit/miss, or fallback status.
   - Monitoring status currently reports simulator/journal/tick freshness, market session, market regime, runtime config, momentum mode, and daily loss guard, but not marketdata cache hit/miss/fallback/stale status.
   - Readiness currently performs a direct cached-in-memory Polygon SPY check via `polygon_client.get_ticker_snapshot("SPY")`; it does not show shared Redis cache availability or D2 simulator cache/fallback status.
   - Journal candidate persistence has no marketdata source/age/stale/fallback columns or JSON detail fields in the current insert.
   - Impact: requirements 5 and 8 are not satisfied.

6. **No D2 tests are present for cache-first simulator behavior.**
   - Existing Phase D1 tests cover Redis serialization, collector health/metrics, and mocked Polygon collector behavior.
   - Existing Phase 2Q-Lite tests cover intrabar exit behavior with Polygon calls mocked.
   - I found no tests proving that fresh shared-cache hits suppress direct Polygon snapshot/previous-close calls during `paper.simulator.run_tick()`, no stale/missing fallback tests, no fallback-failure no-entry test, and no monitoring/readiness/journal visibility tests for marketdata source/age/stale state.
   - Impact: requirement 9 is not satisfied for D2-specific behavior, although existing tests generally mock Polygon for their own scopes.

## Non-blocking issues

- The Phase D1 marketdata cache payload already carries useful fields (`source`, `fetched_at`, `ttl_seconds`, prices, spread, day volume, volume ratio, change percent, previous close, and minute bar fields), so it should be feasible to adapt it into the simulator quality schema in D2.
- The cache read helper returns `None` on Redis/read/JSON failures, which is acceptable for a best-effort cache path, but D2 should expose whether that was a Redis miss/error versus a stale payload versus a configured fallback success.
- Readiness currently has its own 60-second in-memory cache for the direct SPY Polygon check. That is separate from the shared Redis marketdata cache and may confuse operators once D2 expects readiness to describe shared cache health.

## Cache-first simulator assessment

**Assessment: not implemented.**

The normal simulator tick path still performs the following sequence for each active symbol:

1. direct Polygon snapshot fetch;
2. direct Polygon previous-close fetch;
3. `evaluate_market_quality(snapshot, prev)`;
4. candidate scoring and entry logic.

There is no preceding shared-marketdata cache read and no fresh-cache short circuit. Therefore fresh shared cache hits do not reduce Polygon API pressure for normal candidate evaluation.

## Fallback/stale-data assessment

**Assessment: not implemented as D2 behavior.**

The current system has the old behavior: when the direct Polygon calls raise `PolygonError` or another exception, the symbol gets an error record and is absent from `quality_map`, so it is not entered later in the tick. That is safe as an exception fallback, but it does not meet D2’s cache-first contract because:

- stale cache is not detected;
- cache age is not calculated;
- fallback is not configurable as a second path after a cache miss/stale payload;
- fallback outcome is not recorded;
- no explicit “fresh data required” rejection reason is attached to candidate output.

If D2 requires fresh data before entries, the implementation still needs a clear guard: when cache is stale/missing and Polygon fallback is disabled or fails, the candidate must either be omitted with a tick error or emitted as ineligible with a precise rejection reason, but it must never enter.

## Intrabar exit assessment

**Assessment: currently safe and still works, but not integrated with shared cache.**

Intrabar exit detection remains limited to open positions. `run_tick()` snapshots currently open symbols and only calls `get_intrabar_data(...)` for those symbols. `get_intrabar_data(...)` then fetches recent minute bars and has an internal short TTL cache to avoid repeat aggregate calls inside nearby tick cycles.

The bracket evaluator remains conservative: if both take-profit and stop-loss are touched in the same intrabar interval, it exits at the stop-loss price. If intrabar data is unavailable, it falls back to the point-in-time bid or last-trade price.

This satisfies requirement 6 in the current checkout. Requirement 7 also remains satisfied for aggregate calls: the aggregate-minute path is not called for non-open-position candidates. However, the direct snapshot/previous-close calls for normal quality evaluation still occur for all evaluated symbols.

## Monitoring/readiness/dashboard assessment

**Assessment: D2 visibility missing.**

- Monitoring does not expose shared marketdata cache hit/miss/fallback/stale counters or recent simulator marketdata source state.
- Readiness does not check shared Redis marketdata freshness for symbols used by the simulator; it still performs/directly caches a Polygon SPY readiness probe.
- Paper tick API returns candidate data, but candidates do not include marketdata source/age/stale/fallback fields.
- Journal persistence does not store marketdata source/age/stale/fallback fields for later dashboard/details inspection.
- The marketdata API endpoints do expose collector health/symbols/metrics, but those endpoints are collector-oriented and do not prove the simulator consumed the cache first.

## Test coverage assessment

**Assessment: insufficient for D2.**

Existing tests are useful but do not cover the D2 acceptance criteria:

- no test where Redis has a fresh marketdata payload and simulator Polygon functions are asserted not called;
- no test where Redis payload is stale and configured Polygon fallback is asserted called;
- no test where Redis is missing/stale and fallback failure blocks entries with explicit stale/fresh-data metadata;
- no test that non-open-position candidates avoid aggregate calls while open positions still use intrabar data;
- no test that monitoring/readiness/journal/candidate output exposes `marketdata_source`, age, stale status, cache hit/miss, and fallback status;
- no D2 safety scan over changed D2 simulator/monitoring/readiness files because no D2 simulator integration files appear to be changed in this checkout.

The existing Phase D1 and Phase 2Q-Lite tests mock Polygon calls within their scopes, which is good, but D2 needs dedicated no-real-network sentinels around the new cache-first simulator path.

## Safety assessment

No broker integration, live trading, real order placement, real-money execution, AI/LLM path, Ollama, OpenAI, Anthropic, or LangChain integration was found in the reviewed simulator, marketdata, monitoring, readiness, or journal surfaces.

The simulator remains fake-money only. `get_status()` continues to report `live_trading_enabled: False` and `broker_connected: False`, and the simulator/module disclaimers continue to state no broker, no live trading, no real orders, and no real-money execution.

V5 appears untouched in this checkout; I did not find a D2 patch modifying a V5 integration path.

## Whether D2 is safe for fake-money monitoring

**No — not as Phase D2, because the D2 cache-first integration is missing.**

The current application remains safe in the narrower sense that it is fake-money only and does not add broker/live/AI/real-money execution risk. However, it is not safe to treat as completed D2 monitoring because operators would still see simulator behavior driven by direct Polygon calls and would not see whether the shared marketdata cache was fresh, stale, missed, or bypassed.

## Whether any patch is required before D3

**Yes. A D2 implementation patch is required before D3 V5 integration.**

Required before D3:

1. Add simulator cache-first reads from `marketdata.cache.read_symbol(...)` for normal tick quality evaluation.
2. Validate cache freshness using `fetched_at` and `ttl_seconds` or an explicit D2 max-age setting.
3. On fresh cache hit, avoid `polygon_client.get_ticker_snapshot(...)` and `polygon_client.get_previous_close(...)` for that symbol.
4. On missing/stale cache, optionally fall back to the existing Polygon path only when configured.
5. If fresh data is required and fallback is disabled or fails, ensure no entry is possible and expose a clear rejection/error state.
6. Add candidate, tick, monitoring, readiness, and journal/detail fields for marketdata source, age, stale state, cache hit/miss, and fallback outcome.
7. Preserve intrabar aggregate calls for open positions only.
8. Add D2 tests that mock Polygon and Redis and assert no real network calls.
9. Keep V5 untouched until D3 and preserve all fake-money/no-broker/no-real-order/no-AI safety invariants.
