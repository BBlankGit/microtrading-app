# Codex Review — Phase D4 Shared Market-Data Collector Dynamic Universe Coverage

Date: 2026-06-09  
Scope: latest D4 patch only (`d7c77b9 Expand shared market data collector universe coverage`)  
Reviewer: Codex

## Executive Summary

Phase D4 is safe for research/fake-money monitoring and materially improves shared market-data coverage for the microtrading paper simulator. The collector now rebuilds its symbol list every cycle from a prioritized dynamic universe that includes open paper positions, the cached active paper universe, configured V5 symbols, base symbols, and extra symbols. Symbols are normalized, de-duplicated, priority-ordered, and capped with lower-priority tiers dropped before higher-priority tiers.

No broker/live-trading/real-order/AI/Ollama functionality was added. The D4 tests mock Polygon-facing behavior, and the collector still performs one bulk snapshot request per cycle attempt while the existing request-budget counter continues to cap actual Polygon HTTP attempts, including retries.

## Review Matrix

| # | Review Focus | Result | Evidence / Notes |
|---|---|---|---|
| 1 | Collector includes the actual microtrading active universe | Pass | `build_collector_universe()` includes Tier 1 from `paper.universe.get_cached_universe()["active_symbols"]` when `MARKETDATA_INCLUDE_PAPER_UNIVERSE` is enabled. This is the active universe the simulator uses after `get_active_paper_universe()` builds or refreshes it. The collector intentionally reads the cached universe only, so it does not trigger a universe rebuild or extra Polygon discovery work itself. |
| 2 | Collector can include the V5 symbol universe | Pass | D4 adds `MARKETDATA_INCLUDE_V5_UNIVERSE`, default-enabled `MARKETDATA_V5_SYMBOLS`, and `MARKETDATA_V5_SYMBOLS_FILE`; Tier 2 is populated from `settings.marketdata_v5_symbols_list()`. The file override gives an operational path to keep V5 coverage aligned without editing strategy code. |
| 3 | Symbols are de-duplicated and prioritized | Pass | Per-tier de-duplication happens first, then global de-duplication assigns the first/higher-priority occurrence to its tier. Final ordering is Tier 0 → Tier 1 → Tier 2 → Tier 3. |
| 4 | Bulk Polygon calls are still used efficiently | Pass | The collector updates `_symbols` from the dynamic universe, then calls `polygon_source.fetch_bulk_snapshots(self._symbols, ttl)` once per fetch attempt. The D4 test asserts exactly one bulk call for a 25-symbol expanded universe. |
| 5 | Request-budget limiting still caps actual Polygon attempts | Pass | `_polygon_attempt_ts` is appended immediately before each actual bulk call, `_has_budget()` gates both the cycle and every retry, and `polygon_attempts_last_minute` remains the exported actual-attempt metric. |
| 6 | Lower-priority symbols are skipped first under budget pressure | Pass | When symbol count exceeds `MARKETDATA_MAX_SYMBOLS_PER_CYCLE`, the builder drops Tier 3 first, then Tier 2, then Tier 1. Tier 0 open positions are intentionally never dropped. Within a tier, earlier symbols are retained and tail symbols are skipped. |
| 7 | Microtrading cache hits should materially increase and fallbacks decrease | Pass with deployment caveat | Because the collector now prefetches the active paper universe plus open positions, the simulator should see more fresh cache entries and fewer fallback Polygon calls. The improvement depends on the collector being enabled, the active universe cache having been built, Redis availability, and compatible TTL/poll intervals. |
| 8 | V5 strategy/rules/thresholds were not changed | Pass | The latest D4 patch changed config/collector/universe plumbing, API/health exposure, simulator open-position symbol export, and D4 tests only. No V5 strategy/rules/threshold implementation files were changed in the patch. |
| 9 | V6 was untouched | Pass | The latest D4 patch did not modify V6 files. The included D4 test also skips if the external V6 directory is absent and otherwise checks for D4 markers in `/opt/nasdaq-scanner-v6/src/*.js`. |
| 10 | Tests avoid real Polygon calls | Pass | D4 tests patch `marketdata.polygon_source.fetch_bulk_snapshots` with `AsyncMock` for collector-cycle tests and assert the universe builder does not call the Polygon client. |
| 11 | No broker/live trading/real orders/AI/Ollama were added | Pass | New D4 code contains explicit safety comments and imports only config/logging/typing plus paper-universe access for cached symbols. The D4 test statically rejects broker/execution/AI/LLM/Ollama-related imports in `universe_builder.py`. |
| 12 | D4 is safe for research/fake-money monitoring | Pass | The patch is read-only market-data orchestration for Redis-backed monitoring and paper-simulator cache warming. It does not place orders, connect to a broker, or change strategy decision logic. |

## Detailed Findings

### 1. Active Microtrading Universe Coverage

The new universe builder includes four priority tiers:

1. Tier 0: currently open fake-money paper positions.
2. Tier 1: cached paper-simulator `active_symbols`.
3. Tier 2: configured V5 symbols.
4. Tier 3: market-data base symbols plus operator-specified extra symbols.

This addresses the prior coverage gap where the shared collector could remain limited to a static base list while the paper simulator traded or evaluated a broader dynamic universe. Since Tier 1 uses `get_cached_universe()` rather than `get_active_paper_universe()`, the collector will not independently discover/build the universe; it will mirror the latest universe already built by the paper simulator. That is the right safety tradeoff for D4 because it avoids introducing extra discovery-side Polygon calls in the collector.

### 2. V5 Universe Inclusion

The D4 patch supports V5 coverage through a default configured symbol list and an optional file override. This is sufficient for the collector to include the V5 symbol universe without importing or mutating V5 strategy code. The main operational caution is that the hard-coded default list should be kept in sync with the canonical V5 universe, or deployments should point `MARKETDATA_V5_SYMBOLS_FILE` at a maintained symbol file.

### 3. Prioritization, De-duplication, and Budget Behavior

The builder de-duplicates within each tier and then globally across tiers. Higher tiers claim duplicate symbols first. Under symbol-budget pressure, D4 skips lower-priority tiers first in this order:

1. Tier 3: base/extra symbols.
2. Tier 2: V5 symbols.
3. Tier 1: cached paper active universe.
4. Tier 0: open positions are never dropped.

This is aligned with the D4 intent: preserve open positions and active microtrading symbols before lower-priority watchlist coverage. One intentional consequence is that if Tier 0 alone exceeds `MARKETDATA_MAX_SYMBOLS_PER_CYCLE`, the returned final list can exceed the configured symbol cap. That preserves open-position monitoring, and the actual Polygon request-attempt budget is still enforced separately.

### 4. Polygon Efficiency and Attempt Budget

D4 does not regress bulk-call efficiency. The collector rebuilds `_symbols` once per cycle and then passes the complete list into the existing bulk snapshot source. It still counts each actual Polygon HTTP attempt, including retries, immediately before calling the source. If the request budget is exhausted, the cycle is skipped before fetching, or retries are skipped before making another attempt.

This means the symbol universe can expand substantially while the number of Polygon HTTP attempts remains bounded by `MARKETDATA_MAX_REQUESTS_PER_MINUTE`.

### 5. Cache-Hit Impact

D4 should materially improve paper-simulator cache hit rates because the shared collector now warms Redis for the symbols most likely to be consumed by the simulator:

- open fake-money positions that need monitoring;
- the active paper universe selected for the current microtrading tick;
- V5 symbols when enabled;
- configured base/extra symbols.

Expected impact: more `marketdata_cache_hits`, fewer `marketdata_cache_misses`, and fewer fallback Polygon requests from the simulator, assuming the collector is enabled and running frequently enough relative to `MARKETDATA_CACHE_TTL_SECONDS` and `PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS`.

### 6. Safety Review

No evidence was found that D4 added broker integrations, live trading, real order placement, real-money execution, AI, LLM, or Ollama code paths. The patch is confined to shared market-data collection and observability, plus a read-only helper exposing paper-simulator open-position symbols.

The paper simulator's V5 strategy/rules/threshold logic was not changed by the latest D4 patch, and V6 files were not modified.

## Tests / Checks Run

- `pytest backend/tests/test_phase_d4.py -q`
  - Result: `20 passed, 1 skipped, 1 warning in 0.26s`.
  - The skip is expected when `/opt/nasdaq-scanner-v6/src` is not present in the local environment.

## Review Conclusion

Phase D4 passes review for shared market-data collector dynamic universe coverage. It should increase cache coverage for the actual microtrading universe and V5 symbols while preserving bulk Polygon efficiency and actual-attempt rate limiting. It remains appropriate for research/fake-money monitoring and does not introduce broker/live-order/AI/Ollama behavior.
