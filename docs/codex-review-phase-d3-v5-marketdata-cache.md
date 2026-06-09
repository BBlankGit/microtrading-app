# Codex Review — Phase D3 V5 Shared Market-Data Cache Integration

Review date: 2026-06-09  
Review target: current checkout of `BBlankGit/stock-breakout-v5-dashboard` as provided at `/workspace/microtrading-app`  
Requested scope: only the latest Phase D3 patch

## Critical issues

1. **Blocking: the requested Phase D3 V5 patch is not present in this checkout.**
   - The current git history ends at a Phase D2-H1 review merge, and the latest implementation commits are Phase D2 cache-first paper-simulator changes, not a Phase D3 V5 integration.
   - I did not find any V5 scanner/dashboard implementation files in the checked-out tree. Searches for `V5`, `v5`, scanner naming, and Phase D3 references only found prior review documentation and external analysis, not a V5 code path.
   - Because the V5 code path is absent, I cannot verify that V5 market-data fetches read the shared microtrading cache/local API first, that V5 alerts use fresh data correctly, or that V5 source labels/telemetry are visible in the actual V5 UI.

2. **Blocking before V6: Phase D3 cannot be treated as complete until the actual V5 integration patch is available and reviewed.**
   - The current code demonstrates a cache-first path for the in-repo paper simulator, but that is Phase D2/D2-H1 behavior and is not evidence that V5 itself has been integrated.
   - Proceeding to V6 cache integration without first reviewing an actual V5 cache integration would leave the original D3 requirement unvalidated.

## Non-blocking issues

1. **Paper-simulator fallback telemetry counts fallback attempts, not confirmed fallback success.**
   - The simulator increments `fallbacks` immediately before calling Polygon on stale/missing cache data with fallback enabled. If Polygon then fails, `polygon_fallbacks_last_tick` still increments. This is acceptable if interpreted as “fallback attempted,” but a future metric split into `fallback_attempted` and `fallback_succeeded` would be clearer.

2. **Monitoring endpoint exposes cache counters, but the current dashboard monitoring panel does not render the `marketdata_cache` object.**
   - The backend includes `marketdata_cache.last_tick_stats` in `/api/monitoring/status`, but the frontend `MonitoringStatus` type and panel currently render backend/simulator/session/journal/tick freshness only.
   - Candidate rows can carry per-ticker source metadata in backend results and journal persistence, but dashboard type/rendering coverage for these fields was not found in this checkout.

3. **Readiness summarizes cache configuration/collector state but not last-tick counters.**
   - Readiness reports whether the shared cache is enabled, collector state, fallback configuration, and max age, but it does not include the per-tick hit/miss/stale/fallback counters that monitoring/status expose.

## Cache-first V5 assessment

**Result: not verifiable / fail for requested D3 scope because V5 code is absent.**

What is present:

- The in-repo paper simulator has a cache-first market-data path controlled by `PAPER_USE_MARKETDATA_CACHE`.
- `paper.marketdata_adapter.try_cache_for_quality()` reads `marketdata.cache.read_symbol()`, returns a quality dict on a fresh cache hit, labels the source as `cache`, marks it not stale, and documents that it never calls Polygon.
- The simulator calls `try_cache_for_quality()` before the Polygon snapshot/previous-close path. A fresh cache hit writes `quality_map`, increments hits, updates last price, and returns before the direct Polygon calls.

What is missing for D3/V5:

- No V5 `DataFetcher`, V5 scanner, V5 alert loop, or V5 dashboard code path was found in this checkout.
- Therefore there is no evidence that normal V5 ticker market-data fetches read the shared microtrading market-data cache/local API before Polygon.
- There is no V5-specific test proving “fresh cache hit skips Polygon.”

## Fallback/stale-data assessment

**Paper simulator: mostly pass. V5: not verifiable.**

Observed paper-simulator behavior:

- Fresh cache hit: cache data is used and Polygon is skipped.
- Stale cache with fallback enabled: the adapter returns no quality with source `stale`; the simulator labels the subsequent path `polygon_fallback` and calls the old Polygon quality path.
- Missing/unusable cache with fallback enabled: the adapter returns no quality with source `missing`/`cache_error`; the simulator falls through to Polygon.
- Stale/missing/unusable cache with fallback disabled: the adapter returns a `_no_fallback` source; the simulator records an error, does not call Polygon, does not populate `quality_map`, and excludes the symbol from candidate/entry processing.
- If `PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY` is enabled and stale-cache fallback data reaches the candidate stage, entries are blocked with `stale_marketdata_entry_blocked`.

Gaps for requested D3/V5:

- There is no V5 fallback configuration or V5 stale-data guard to inspect.
- There is no V5 alert-generation proof that stale/missing data cannot generate alerts when fresh data is required and fallback fails/disabled.

## Alert/rule-regression assessment

**V5: not verifiable. Paper-simulator rules appear preserved in the current checkout.**

- The cache adapter builds a quality dict in the same shape consumed by downstream paper-simulator scoring and gates.
- The paper simulator still applies the existing hard gates for tradability, spread, positive change, volume ratio, bearish-catalyst rejection, accepted catalysts, generic-only catalysts, and fresh-market-data blocking.
- The deterministic scoring thresholds and catalyst score weights are still defined in `paper.scoring`, with the configured `score_threshold` consumed from runtime config.
- No V5 alert/scoring/rule-threshold files were available for comparison, so I cannot certify that V5 thresholds were unchanged by D3.

## V5 intelligence preservation assessment

**Not verifiable for V5; current paper-simulator intelligence features appear preserved where present.**

Requested V5 intelligence features:

- insiders: **not found in the active in-repo paper-simulator path and not verifiable for V5**
- news: **present in paper simulator via Polygon news/catalyst collection, but V5 preservation is not verifiable**
- earnings: **event type exists in catalyst scoring/classification flow, but V5 preservation is not verifiable**
- premarket discovery: **market-wide discovery exists in the paper universe/discovery path, but V5 preservation is not verifiable**
- catalyst/ranking logic: **paper scoring and universe ranking are present, but V5 preservation is not verifiable**

Important nuance: absence of V5 files means I found no evidence that these V5 features were removed, but also no evidence that an actual V5 D3 cache integration preserved them.

## Telemetry/dashboard assessment

**Backend telemetry for the paper simulator: pass. Dashboard/source visibility for D3/V5: incomplete/not verifiable.**

Present backend telemetry:

- Per-tick counters include:
  - `cache_hits_last_tick`
  - `cache_misses_last_tick`
  - `cache_stale_last_tick`
  - `polygon_fallbacks_last_tick`
  - `polygon_direct_last_tick`
  - `missing_marketdata_last_tick`
- Paper status exposes `last_tick_marketdata`.
- Monitoring exposes `marketdata_cache.last_tick_stats` plus cache enablement, collector running state, max age, fallback setting, and fresh-entry requirement.
- Candidate records include per-symbol fields: `marketdata_source`, `marketdata_age_seconds`, `marketdata_fetched_at`, `marketdata_stale`, `marketdata_fallback_used`, and `marketdata_error`.
- Journal persistence includes the market-data source/stale/fallback/error fields.

Limitations:

- I did not find these cache telemetry fields rendered in the frontend monitoring panel.
- I did not find V5-specific telemetry or source-label UI because V5 code was absent.

## Test coverage assessment

**Paper-simulator cache tests: good. V5 D3 tests: absent/not verifiable.**

Present test coverage:

- Adapter tests mock `marketdata.cache.read_symbol()` for fresh, stale, missing, and no-fallback outcomes.
- Simulator tests mock both the shared cache adapter and Polygon client calls.
- A cache-hit test asserts Polygon snapshot and previous-close calls are not made on a fresh cache hit.
- No-fallback tests assert Polygon is not called and no quality is produced.
- Stale/fallback tests assert stale/fallback counters and stale-entry blocking behavior.
- Tests use `AsyncMock`/patching for cache, Polygon, catalysts, intrabar data, persistence, and runtime config, so these targeted tests avoid real network calls.

Missing for requested D3/V5:

- No V5 cache-first tests were found.
- No V5 alert/stale-data tests were found.
- No V5 source-label/dashboard tests were found.
- No V5 regression tests were found for insiders/news/earnings/premarket discovery/catalyst ranking preservation.

## Safety assessment

**Current checkout remains safe for research/fake-money monitoring, but the requested V5 D3 integration is not reviewable.**

- The reviewed in-repo paper-simulator cache path is explicitly research/fake-money only and contains no broker/live-order execution.
- Status hard-codes `live_trading_enabled: False` and `broker_connected: False` for the paper simulator.
- The cache adapter imports only logging, datetime/timezone, typing, and runtime config; it does not import broker/live trading/AI modules.
- Tests include safety checks that the cache adapter does not import broker/live/AI/Ollama/OpenAI/Anthropic/LangChain-style modules and that the simulator does not reference V5/V6 scanner modules.
- No new broker integration, live trading, real orders, real-money execution, Ollama, OpenAI, Anthropic, LangChain, or AI/LLM runtime calls were observed in the cache integration path.

## Whether D3 is safe for research monitoring

**No — not as a D3 V5 integration, because the D3 V5 patch is absent and therefore unvalidated.**

The existing D2/D2-H1 paper-simulator cache-first implementation appears safe for research/fake-money monitoring. However, the requested Phase D3 V5 integration cannot be called safe or complete until the actual V5 patch is present and reviewed against the requested checklist.

## Whether any patch is required before V6 integration

**Yes. A Phase D3 V5 patch/review is required before V6 cache integration.**

Required before V6:

1. Provide the actual V5 code path in this checkout or review the correct V5 repository/branch.
2. Implement/verify V5 cache-first reads against the shared microtrading market-data cache/local API before direct Polygon calls.
3. Prove fresh V5 cache hits skip Polygon for normal ticker market data.
4. Gate V5 Polygon fallback behind explicit configuration.
5. Prevent V5 alerts from stale/missing data when fresh data is required and fallback fails/disabled.
6. Preserve V5 alert/scoring/rule thresholds and unique intelligence features.
7. Expose V5 cache hit/miss/stale/fallback/timeout telemetry and source labels per ticker or scan.
8. Add V5 tests that mock shared cache/local API and Polygon and assert no real network calls.
9. Keep V6 untouched until D3 V5 is reviewed and accepted.
10. Continue blocking broker/live trading/real orders/AI/LLM additions in this phase.

## Commands used for this review

- `git log --oneline --decorate --graph -20 --all`
- `git show --stat --oneline --name-only HEAD`
- `git show --stat --oneline --name-only 5d12ae9`
- `git show --stat --oneline --name-only 1a15f58`
- `rg -n "v5|V5|phase d3|Phase D3|D3" backend frontend docs README.md .env.example infra -S --glob '!frontend/dashboard/node_modules/**'`
- `rg -n "scanner|DataFetcher|alert|insider|earnings|premarket|catalyst|ranking|news|V6|v6" --glob '!frontend/dashboard/node_modules/**' backend frontend docs README.md`
- `rg -n "marketdata_source|marketdata_fallback|marketdata_error|marketdata_stale|cache_hits|last_tick_marketdata" backend/paper backend/api frontend/dashboard/app/page.tsx -S`
- `sed`/`nl` inspections of `backend/paper/marketdata_adapter.py`, `backend/paper/simulator.py`, `backend/tests/test_phase_d2.py`, `backend/tests/test_phase_d2_h1.py`, `backend/api/monitoring.py`, `backend/api/readiness.py`, `backend/core/config.py`, `backend/paper/scoring.py`, `backend/paper/universe.py`, `backend/paper/discovery.py`, `backend/catalysts/news_collector.py`, and `frontend/dashboard/app/page.tsx`.
