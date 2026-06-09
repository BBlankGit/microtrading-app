# Codex Review — Phase D3 V5 Shared Market-Data Cache Integration

Review date: 2026-06-09
Requested repository: `BBlankGit/stock-breakout-v5-dashboard`
Local checkout reviewed: `/workspace/microtrading-app`
Requested implementation commit: `0dbb8ea — Route V5 market data through shared cache first`
Scope: latest Phase D3 V5 cache patch only

## Critical issues

1. **Blocking: the requested Phase D3 V5 implementation commit is not available in this checkout.**
   - `git cat-file -t 0dbb8ea` reports that `0dbb8ea` is not a valid object in the local repository.
   - The local history currently ends at a prior review merge (`d6fab47`) and earlier D2/D2-H1 cache work; it does not contain the requested `0dbb8ea` implementation commit.
   - Because the actual V5 patch is absent, this review cannot certify the requested D3 outcomes against V5 code.

2. **Blocking: no V5 scanner/alert code path is present in the local tree.**
   - `rg --files | rg -i 'v5|v6|scanner|alert|insider|earnings|premarket'` found no V5 implementation files; the only V5-named review file is this document.
   - The existing backend is a paper-simulator/microtrading codebase, so its cache-first behavior is relevant background only, not proof that V5 was integrated.

3. **Blocking before V6: Phase D3 V5 must be reviewed on the branch that actually contains `0dbb8ea`.**
   - Proceeding to V6 cache integration from this checkout would skip validation of the V5 cache-first contract, stale-data alert guards, telemetry, and threshold-preservation requirements.

## Non-blocking issues

1. **Paper-simulator fallback telemetry counts fallback attempts, not confirmed fallback success.**
   - The simulator increments its fallback counter before calling Polygon after stale/missing cache data. If Polygon then fails, `polygon_fallbacks_last_tick` still reflects an attempted fallback. That is acceptable if interpreted as “fallback attempted,” but future telemetry would be clearer with separate attempted/succeeded/failed counters.

2. **Monitoring exposes backend cache counters, but the frontend dashboard does not appear to render them in this checkout.**
   - `/api/monitoring/status` returns `marketdata_cache.last_tick_stats`, but I did not find corresponding frontend rendering for those specific cache counters.

3. **Timeout telemetry requested for D3/V5 is not present in the reviewed paper-simulator counters.**
   - The available counters cover hit/miss/stale/fallback/direct/missing outcomes, but there is no distinct timeout counter in the paper-simulator telemetry. Since the V5 patch is absent, V5 timeout telemetry is unverified.

## Cache-first V5 assessment

**Verdict: not verifiable / fail for D3 scope.**

The requested V5 integration cannot be evaluated because the V5 implementation commit and V5 files are absent from the local checkout.

What is present as background:

- `paper.marketdata_adapter.try_cache_for_quality()` reads the shared `marketdata.cache.read_symbol()` path, classifies fresh/stale/missing/error cache outcomes, and documents that it never calls Polygon.
- On a fresh cache hit, the adapter returns a quality dict with `marketdata_source == "cache"` and `marketdata_stale == False`.
- The paper simulator calls the adapter before the Polygon snapshot/previous-close path when `PAPER_USE_MARKETDATA_CACHE` is enabled.
- Existing tests assert that a fresh paper-simulator cache hit avoids Polygon snapshot and previous-close calls.

What remains unproved for D3/V5:

- V5 normal ticker market-data fetches reading the shared microtrading market-data cache/local API first.
- Fresh V5 cache hits avoiding direct Polygon calls.
- V5 per-ticker or per-scan source labels.
- V5 dashboard visibility of cache source and counters.

## Fallback/stale-data assessment

**Verdict: paper-simulator background mostly passes; V5 not verifiable.**

Observed in the available paper-simulator path:

- Cache fallback is controlled by `PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED`.
- Fresh cache hit: returns cached quality and skips Polygon.
- Stale/missing/error with fallback enabled: falls through to the old Polygon path and labels the source as `polygon_fallback`.
- Stale/missing/error with fallback disabled: records missing/stale market-data errors, does not call Polygon, and does not add quality for the symbol.
- When `PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY` is enabled, stale market-data metadata can block new entries via `stale_marketdata_entry_blocked`.

D3/V5 gaps:

- No V5 fallback configuration was available to inspect.
- No V5 alert loop was available to prove stale/missing data cannot generate alerts when fresh data is required and fallback fails or is disabled.
- No V5 test was available to assert direct Polygon is used only under the configured fallback condition.

## Alert/rule-regression assessment

**Verdict: V5 not verifiable.**

- The available paper-simulator path preserves its existing hard gates and deterministic scoring flow, but that is not the V5 alert engine.
- No V5 alert/scoring/rule-threshold files are present in the local tree, so I cannot confirm that D3 left V5 thresholds unchanged.
- A review on the actual `0dbb8ea` branch must diff V5 scoring/rules against the parent commit and confirm that only market-data routing/source-label/telemetry behavior changed.

## V5 intelligence preservation assessment

**Verdict: not verifiable because V5 is absent.**

Requested V5 features:

- **Insiders:** no V5 insider pipeline found in this checkout.
- **News:** backend paper-simulator news/catalyst collection exists, but no V5-specific news integration was available.
- **Earnings:** paper-simulator scoring recognizes earnings catalysts, but V5 earnings preservation cannot be evaluated.
- **Premarket discovery:** paper-simulator market-wide discovery exists, but no V5 premarket discovery code path was available.
- **Catalyst/ranking logic:** paper-simulator scoring/ranking exists, but V5 catalyst/ranking preservation cannot be certified.

The absence of V5 files means there is no evidence these features were removed in the local checkout, but also no evidence that the D3 V5 cache integration preserved them.

## Telemetry/dashboard assessment

**Verdict: paper-simulator backend telemetry partially passes; V5 telemetry/dashboard not verifiable.**

Available paper-simulator telemetry:

- `cache_hits_last_tick`
- `cache_misses_last_tick`
- `cache_stale_last_tick`
- `polygon_fallbacks_last_tick`
- `polygon_direct_last_tick`
- `missing_marketdata_last_tick`
- Candidate-level source metadata: `marketdata_source`, `marketdata_age_seconds`, `marketdata_fetched_at`, `marketdata_stale`, `marketdata_fallback_used`, and `marketdata_error`
- Monitoring status includes `marketdata_cache.last_tick_stats`.

Limitations relative to D3:

- No distinct timeout counter was found in the available paper-simulator telemetry.
- No V5 telemetry fields were available.
- No V5 dashboard/source-label rendering was available.

## Test coverage assessment

**Verdict: paper-simulator tests are good; V5 D3 tests are absent.**

Available paper-simulator test coverage:

- Tests mock shared cache reads with `AsyncMock`.
- Tests mock Polygon snapshot/previous-close calls rather than using real network calls.
- Fresh cache-hit tests assert Polygon is not called.
- Cache-miss and stale-cache tests assert fallback counters and source labels.
- No-fallback tests assert Polygon is not called and quality is not produced.
- Candidate metadata and monitoring-status tests cover source/error/fallback fields and last-tick stats.

Missing for D3/V5:

- No V5 cache-first tests.
- No V5 stale/missing/fallback-disabled alert-blocking tests.
- No V5 source-label or dashboard telemetry tests.
- No V5 intelligence-regression tests for insiders/news/earnings/premarket discovery/catalyst ranking.
- No test evidence for V5 timeout counters.

## Safety assessment

**Verdict: the local paper-simulator cache path appears safe for research/fake-money monitoring; D3/V5 safety cannot be certified from this checkout.**

- The available market-data adapter explicitly states that it has no broker, live trading, real orders, or real-money execution behavior.
- The paper-simulator tests include safety checks for forbidden broker/live/AI/Ollama/OpenAI/Anthropic/LangChain-style imports in the cache path.
- Searches did not reveal new broker integration, live trading, real orders, AI/LLM, Ollama, OpenAI, Anthropic, LangChain, or real-money execution additions in this local checkout.
- However, because the requested V5 patch is not available, the D3 V5 implementation itself remains unreviewed.

## Whether D3 is safe for research monitoring

**No — not yet as a D3 V5 integration.**

The available paper-simulator cache-first implementation appears safe for fake-money research monitoring, but D3 cannot be accepted as safe/complete for V5 until the actual `0dbb8ea` branch is available and passes the requested V5-specific checks.

## Whether any patch is required before V6 integration

**Yes. A patch or branch correction is required before V6 cache integration.**

Required before V6:

1. Provide the branch/checkout containing `0dbb8ea — Route V5 market data through shared cache first`, or re-apply that patch here.
2. Verify V5 reads the shared microtrading market-data cache/local API before Polygon for normal ticker market data.
3. Add/verify tests proving fresh V5 cache hits avoid direct Polygon calls.
4. Gate V5 Polygon fallback behind explicit configuration.
5. Prove stale/missing/unusable data cannot generate V5 alerts when fresh data is required and fallback fails or is disabled.
6. Confirm V5 alert/scoring/rule thresholds are unchanged from the parent commit.
7. Confirm V5 insiders/news/earnings/premarket discovery/catalyst-ranking features remain intact.
8. Expose V5 cache hits/misses/stale/fallback/timeout telemetry and per-ticker or per-scan source labels.
9. Ensure tests mock both the shared cache/local API and Polygon and avoid real network calls.
10. Keep the microtrading repo, V6 code, broker/live trading, real orders, AI/LLM, and real-money execution untouched.

## Commands used for this review

- `git status --short`
- `git log --oneline --all --decorate --max-count=20`
- `git cat-file -t 0dbb8ea`
- `git ls-remote https://github.com/BBlankGit/stock-breakout-v5-dashboard.git | head -20` (network blocked by 403 in this environment)
- `rg --files | rg -i 'v5|v6|scanner|alert|insider|earnings|premarket'`
- `rg -n "insider|earnings|premarket|v5|v6|scanner|alert" backend frontend docs README.md -S --glob '!frontend/dashboard/node_modules/**'`
- `nl -ba backend/paper/marketdata_adapter.py | sed -n '1,240p'`
- `nl -ba backend/paper/simulator.py | sed -n '220,340p'`
- `nl -ba backend/paper/simulator.py | sed -n '584,700p'`
- `nl -ba backend/api/monitoring.py | sed -n '180,260p'`
- `nl -ba backend/core/config.py | sed -n '125,145p'`
- `nl -ba backend/tests/test_phase_d2.py | sed -n '1,130p'`
- `nl -ba backend/tests/test_phase_d2.py | sed -n '220,420p'`
- `nl -ba backend/tests/test_phase_d2_h1.py | sed -n '110,245p'`
