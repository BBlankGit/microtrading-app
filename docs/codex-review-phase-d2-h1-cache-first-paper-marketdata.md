# Codex Review — Phase D2-H1 Cache-First Paper Market Data

Review scope: latest Phase D2-H1 patch only, comparing the current `HEAD` against the pre-D2-H1 baseline at `f401837`.

## Critical issues

No critical issues found.

## Non-blocking issues

1. **Readiness does not surface last-tick hit/miss/stale/fallback counters.** The monitoring endpoint exposes `marketdata_cache.last_tick_stats`, but readiness only reports configuration/collector state. This is operator-visibility useful but not a safety blocker because status/monitoring still expose the counters and readiness does warn when cache fallback is active or unavailable.
2. **Monitoring warnings are configuration/collector based, not counter-threshold based.** Monitoring warns when the collector is stopped while cache is enabled, but it does not additionally warn when recent counters show high stale/miss/fallback rates despite the collector being marked running. This can be deferred until D3 observability hardening.
3. **No candidate row is emitted for no-fallback cache miss/stale symbols.** This is safer than producing an entry, and the tick records `errors` plus `missing_marketdata_last_tick`, but it means per-symbol candidate visibility is absent for rejected no-data symbols. If operators want a complete rejected-candidate audit trail, add synthetic non-eligible candidate records later.
4. **Polygon fallback counter increments before fallback success.** `polygon_fallbacks_last_tick` currently means “fallback attempted” rather than “fallback succeeded.” This is acceptable if documented, but a future split into `fallback_attempted` and `fallback_succeeded` would make monitoring clearer.

## Cache-first simulator assessment

Pass. Normal paper-simulator quality evaluation checks the shared Redis-backed market-data cache first when `PAPER_USE_MARKETDATA_CACHE` is enabled. The simulator calls `try_cache_for_quality()` before any Polygon calls, accepts a non-`None` cached quality dict as a fresh cache hit, stores it in `quality_map`, increments the hit counter, updates the last price, and returns from the per-symbol fetch path before reaching Polygon snapshot or previous-close calls.

The adapter itself is cache-only by design: it reads `marketdata.cache.read_symbol()`, computes age from `fetched_at`, returns a quality dict only for `raw_status == "ok"` with age at or below the configured max age, and explicitly documents that it never calls Polygon.

The test suite covers this critical path with patched cache and Polygon clients: `test_tick_cache_hit_skips_polygon()` asserts both `get_ticker_snapshot` and `get_previous_close` are not called on a fresh cache hit.

## Fallback/stale-data assessment

Pass.

- Fresh cache hits avoid direct Polygon snapshot and previous-close calls.
- Cache misses, stale cache entries, cache errors, or unusable entries return no quality from the adapter.
- With fallback enabled, those non-fresh cache paths fall through to the existing direct Polygon snapshot plus previous-close quality path and mark source metadata as `polygon_fallback`.
- With fallback disabled, stale/missing/error cache states use `_no_fallback` source variants, the simulator records an error, increments missing/no-data counters, returns before Polygon calls, and does not place anything in `quality_map`; therefore those symbols cannot become candidates or entries through the normal entry loop.
- With `PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY` enabled, stale fallback data can still produce a visible candidate but is blocked from entry with `stale_marketdata_entry_blocked`.

One nuance: when cache was stale but Polygon fallback succeeds, the simulator intentionally keeps `marketdata_stale=True` to signal pipeline lag and allow fresh-for-entry blocking. When cache was missing or errored but Polygon succeeds, it clears the stale flag and treats Polygon as authoritative.

## Candidate/journal visibility assessment

Pass with the no-fallback visibility caveat above.

Candidate output includes the requested market-data fields for symbols that reach candidate construction:

- `marketdata_source`
- `marketdata_age_seconds`
- `marketdata_fetched_at`
- `marketdata_stale`
- `marketdata_fallback_used`
- `marketdata_error`

The journal schema adds candidate columns for source, age, stale, fallback-used, and error, and journal writes persist those candidate fields. That satisfies the D2-H1 requirement to preserve market-data source/freshness data in persistent details for evaluated candidates.

No-fallback cache miss/stale symbols do not become candidate rows because no quality dict is produced; they are represented in tick `errors` and aggregate counters instead. This is safe but less complete for per-symbol audit visibility.

## Monitoring/readiness assessment

Pass for monitoring/status; partial pass for readiness.

- Simulator status exposes `last_tick_marketdata` after a tick.
- Tick results expose canonical last-tick counters: cache hits, misses, stale, Polygon fallbacks, Polygon direct calls, and missing market data.
- Monitoring exposes those counters under `marketdata_cache.last_tick_stats` and warns when the cache is enabled but the collector is not running, distinguishing fallback enabled vs fallback disabled.
- Readiness checks cache enablement, collector-running state, fallback setting, and max age, and emits pass/warn/fail outcomes for those operational states.

Readiness does not currently include the last-tick hit/miss/stale/fallback counters. Because monitoring and status expose them, this is not a D3 blocker, but adding those counters to readiness details would close the visibility gap.

## Intrabar exit assessment

Pass. The D2-H1 changes leave intrabar exit detection bounded to currently open positions. The simulator snapshots `_account.positions.keys()` and only calls `get_intrabar_data()` for that open-position set; candidate symbols that are not open positions do not trigger aggregate calls. Intrabar results remain used only for virtual bracket exit checks, with no broker/order behavior added.

## Test coverage assessment

Pass, with a small non-blocking caveat.

Coverage includes:

- Adapter fresh-hit, stale, miss, fallback-enabled, and fallback-disabled behavior with mocked Redis/cache reads.
- Simulator fresh cache hit skipping Polygon snapshot and previous-close calls.
- Cache miss/stale with fallback calling mocked Polygon paths.
- No-fallback missing cache producing no Polygon calls and no quality entries.
- Candidate metadata fields for fallback/error visibility.
- Monitoring `last_tick_stats` exposure.
- Simulator status `last_tick_marketdata` exposure.
- Intrabar aggregate calls limited to open positions.
- Safety scans for forbidden broker/live/AI/Ollama-style imports in the cache path and scanner references in the simulator.

Caveat: `test_monitoring_status_includes_last_tick_stats()` uses a real `TestClient(app)` call without comprehensively patching all monitoring dependencies. In this code path it should not hit external network under default cached/disabled conditions, but a stricter no-network test could patch market-regime and market-data service calls explicitly.

## V5 untouched

Pass. No files with V5/scanner naming appear in the Phase D2-H1 diff, and the simulator safety test checks for V5 scanner references.

## V6 untouched

Pass. No files with V6/scanner naming appear in the Phase D2-H1 diff, and the simulator safety test checks for V6 scanner references.

## Safety assessment

Pass. The reviewed patch remains fake-money/research-only:

- No broker integration was added.
- No live trading enablement was added.
- No real order submission/execution path was added.
- No real-money execution path was added.
- No AI/LLM/Ollama/OpenAI/Anthropic/LangChain integration was added.
- Simulator status still reports `live_trading_enabled=False` and `broker_connected=False`.
- New and touched market-data/paper modules continue to include explicit no-broker/no-real-orders disclaimers.

## Whether D2-H1 is safe for fake-money monitoring

Yes. D2-H1 is safe for fake-money monitoring. The normal simulator path is cache-first, fresh cache hits bypass direct Polygon calls, no-fallback stale/missing cache cannot create entries, stale fallback data is entry-blocked when freshness is required, and operational counters/metadata are available for monitoring and status.

## Whether any patch is required before D3

No required patch before D3.

Recommended but non-blocking D3-adjacent improvements:

1. Add last-tick cache counters to readiness details, not just monitoring/status.
2. Add warning thresholds for elevated stale/miss/fallback rates even when the collector reports running.
3. Consider synthetic rejected candidate records for no-fallback no-data symbols if complete per-symbol auditability is required.
4. Split fallback-attempt and fallback-success counters if operators need exact fallback success rate.
