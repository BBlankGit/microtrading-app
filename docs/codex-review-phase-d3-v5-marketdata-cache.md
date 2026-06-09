# Codex Review — Phase D3 V5 Shared Market-Data Cache Integration

Review date: 2026-06-09
Requested repository: `BBlankGit/stock-breakout-v5-dashboard`
Local checkout provided: `/workspace/microtrading-app`
Requested implementation commit: `0dbb8ea — Route V5 market data through shared cache first`
Scope requested: latest Phase D3 V5 patch only

## Critical issues

1. **Blocking: the requested implementation commit is not present in the provided checkout.**
   - `git cat-file -t 0dbb8ea` returns `fatal: Not a valid object name 0dbb8ea`.
   - `git show --stat --oneline 0dbb8ea` also fails because the object is unknown locally.
   - The local branch is `work`, and the visible history contains prior microtrading review/implementation work rather than the requested V5 implementation commit.
   - Because the Phase D3 implementation object is unavailable, this review cannot certify the actual latest V5 patch.

2. **Blocking: the provided checkout is the microtrading app, not the requested V5 dashboard repository.**
   - The repository root is `/workspace/microtrading-app`.
   - The tree contains `backend/marketdata`, `backend/paper`, `backend/api`, and other microtrading modules.
   - I did not find V5 scanner/alert implementation files for the requested `stock-breakout-v5-dashboard` scope.

3. **Blocking: network access to the requested GitHub repository is unavailable from this environment.**
   - `git ls-remote https://github.com/BBlankGit/stock-breakout-v5-dashboard.git` fails with `CONNECT tunnel failed, response 403`.
   - I therefore could not fetch `0dbb8ea` or compare it against its parent commit.

4. **Blocking before V6: D3 cannot be accepted as reviewed until the real V5 patch is available.**
   - The D3 requirements are specifically about V5 alert/scanner behavior, threshold preservation, intelligence preservation, and dashboard telemetry.
   - Those properties must be reviewed in the branch containing `0dbb8ea`, not inferred from the microtrading cache implementation.

## Non-blocking issues

1. **The available microtrading paper-simulator fallback counter is named as if fallback succeeded, but it is incremented before the Polygon call.**
   - In the local background implementation, `fallbacks` is incremented when stale/missing cache data falls through to Polygon.
   - If Polygon later fails, the counter still records a fallback attempt.
   - This is acceptable if documented as “fallback attempted,” but future telemetry would be clearer with separate attempted/succeeded/failed counters.

2. **The local microtrading backend exposes cache counters, but V5 dashboard rendering is not available to inspect.**
   - The provided checkout can show backend-style cache stats for the microtrading paper simulator.
   - It cannot prove that V5 displays source labels per ticker or per scan.

3. **Timeout telemetry is not proven for V5.**
   - The local paper-simulator counters cover hits, misses, stale entries, Polygon fallbacks, Polygon direct calls, and missing market data.
   - I did not find V5 timeout telemetry because V5 files are absent.

## Cache-first V5 assessment

**Verdict: not verifiable / not accepted for D3.**

The requested V5 cache-first integration cannot be assessed from the provided checkout because `0dbb8ea` and the V5 implementation files are absent.

Background evidence from the local microtrading implementation only:

- The local paper market-data adapter reads `marketdata.cache.read_symbol(sym)` and documents that it is cache-only and never calls Polygon.
- It classifies fresh cache hits as `marketdata_source == "cache"` and stale/missing/error cache outcomes as fallback-eligible or no-fallback outcomes.
- The local paper simulator checks the cache path before direct Polygon calls when its cache setting is enabled.
- Fresh local cache hits return before the Polygon snapshot/previous-close path.

Unverified for the requested V5 D3 patch:

- Whether normal V5 ticker market-data fetches read the shared microtrading marketdata cache/local API first.
- Whether fresh V5 cache hits avoid all direct Polygon calls for normal ticker market data.
- Whether V5 uses the local API, direct Redis access, or another shared-cache adapter.
- Whether V5 source labels are visible per ticker or per scan.

## Fallback/stale-data assessment

**Verdict: not verifiable for V5; local microtrading background mostly matches the intended behavior.**

Observed in the local microtrading paper path:

- Fallback is controlled by configuration.
- A fresh cache hit skips Polygon.
- A stale/missing/error cache result with fallback enabled falls through to the previous Polygon path.
- A stale/missing/error cache result with fallback disabled rejects the symbol for that tick and does not call Polygon.
- A fresh-data-for-entry gate exists in the local paper simulator and can block entry creation when market data is stale.

Unverified for V5:

- Whether V5 fallback is gated by an explicit configuration flag.
- Whether V5 calls the old Polygon path only for missing/stale/unusable cache when fallback is enabled.
- Whether V5 blocks alerts when fresh data is required and cache is stale/missing/unusable while fallback fails or is disabled.
- Whether V5 distinguishes stale data from missing or cache-error data in telemetry and source labels.

## Alert/rule-regression assessment

**Verdict: not verifiable.**

I cannot confirm whether V5 alert, scoring, and rule thresholds were unchanged because the requested V5 patch and parent commit are unavailable locally.

Required review once `0dbb8ea` is available:

- Diff V5 alert/scoring/rules/config files against the parent commit.
- Confirm all threshold constants and defaults are unchanged unless the patch only adds market-data source/freshness metadata.
- Confirm cache source/freshness checks do not loosen entry/alert gates.
- Confirm stale/missing data cannot produce an alert when the system requires fresh market data.

## V5 intelligence preservation assessment

**Verdict: not verifiable.**

The following V5-specific features cannot be certified from this checkout:

- **Insiders:** no requested V5 insider implementation was available to diff.
- **News:** local microtrading catalyst/news modules exist, but they do not prove V5 news preservation.
- **Earnings:** local scoring mentions earnings-style catalyst data, but no V5 earnings path was available.
- **Premarket discovery:** local paper discovery exists, but no V5 premarket discovery path was available.
- **Catalyst/ranking logic:** local deterministic scoring/ranking exists, but no V5 ranking patch could be inspected.

There is no evidence in the provided checkout that these V5 features were removed, but there is also no evidence that `0dbb8ea` preserved them.

## Telemetry/dashboard assessment

**Verdict: not verifiable for V5; local background telemetry is partial.**

Local microtrading background telemetry includes:

- `cache_hits_last_tick`
- `cache_misses_last_tick`
- `cache_stale_last_tick`
- `polygon_fallbacks_last_tick`
- `polygon_direct_last_tick`
- `missing_marketdata_last_tick`
- Candidate metadata such as `marketdata_source`, `marketdata_age_seconds`, `marketdata_fetched_at`, `marketdata_stale`, `marketdata_fallback_used`, and `marketdata_error`

Unverified for V5:

- Hit, miss, stale, fallback, timeout, and fallback-failure counters.
- Per-ticker source labels.
- Per-scan aggregate source labels.
- Dashboard/UI rendering of cache status.
- Alert payload inclusion of data source/freshness metadata.

## Test coverage assessment

**Verdict: not verifiable for V5.**

Local microtrading background tests show the desired pattern for the paper simulator:

- Cache reads are mocked.
- Polygon snapshot and previous-close calls are mocked.
- Fresh cache-hit tests assert Polygon is not called.
- No-fallback tests assert Polygon is not called when cache data is missing/stale and fallback is disabled.
- Candidate metadata and cache counters are asserted.

Missing for D3/V5:

- Tests proving V5 shared-cache/local-API reads happen before Polygon.
- Tests proving fresh V5 cache hits avoid Polygon for normal ticker market data.
- Tests proving stale/missing/unusable cache falls back only when configured.
- Tests proving alerts are not emitted when fresh data is required and fallback fails or is disabled.
- Tests proving insiders/news/earnings/premarket discovery/catalyst ranking were preserved.
- Tests proving V5 telemetry and dashboard/source labels.
- Tests proving all network paths are mocked and no real Polygon/shared-cache network calls occur in unit tests.

## Safety assessment

**Verdict: local checkout remains research/fake-money only; V5 D3 safety is not certified.**

Local microtrading safety background:

- The reviewed local cache and paper-simulator modules describe no broker, no live trading, no real orders, and no real-money execution.
- Searches did not show a new broker/live-order/real-money execution implementation added by this review activity.
- Existing local modules are framed as research/fake-money simulation.

Unverified for V5:

- Whether `0dbb8ea` added any broker integration, live trading, real orders, real-money execution, AI/LLM, Ollama, OpenAI, Anthropic, or LangChain usage.
- Whether V5 remains safe to run as research/fake-money monitoring after the Phase D3 patch.

## Whether D3 is safe for research monitoring

**No decision / not accepted yet.**

The local microtrading implementation appears consistent with research/fake-money monitoring, but the requested D3 V5 implementation is absent. D3 should not be treated as reviewed or accepted for research monitoring until the actual V5 patch at `0dbb8ea` is available and passes the cache-first, stale-data, threshold-regression, intelligence-preservation, telemetry, and safety checks.

## Whether any patch is required before V6 integration

**Yes: a branch/review correction is required before V6 integration.**

Before V6 cache integration, one of the following must happen:

1. Provide a checkout containing `0dbb8ea — Route V5 market data through shared cache first`, then re-run this D3 V5 review against that commit; or
2. Re-apply the D3 V5 implementation patch to the available repository/branch, then re-run the review.

The minimum acceptance checks before V6 are:

- V5 normal ticker market-data fetches read the shared microtrading marketdata cache/local API first.
- Fresh V5 cache hits skip Polygon.
- Stale/missing/unusable cache falls back to Polygon only when explicitly configured.
- Stale/missing/unusable data cannot generate alerts when fresh data is required and fallback fails or is disabled.
- V5 alert/scoring/rule thresholds are unchanged.
- V5 insiders, news, earnings, premarket discovery, and catalyst/ranking logic are preserved.
- V5 telemetry exposes hit/miss/stale/fallback/timeout/failure counts.
- V5 source labels are visible per ticker or per scan.
- V5 tests mock shared cache/local API and Polygon and avoid real network calls.
- Microtrading implementation code is not modified by the V5 phase except for any explicitly intended shared API contract changes.
- V6 remains untouched.
- No broker integration, live trading, real orders, AI/LLM, Ollama, OpenAI, Anthropic, LangChain, or real-money execution is added.

## Commands used for this review

- `pwd`
- `find .. -name AGENTS.md -print`
- `git status --short`
- `git branch --show-current`
- `git log --oneline --all --decorate --max-count=30`
- `git show --stat --oneline --decorate 0dbb8ea`
- `git cat-file -t 0dbb8ea`
- `git ls-remote https://github.com/BBlankGit/stock-breakout-v5-dashboard.git | head -20`
- `rg --files | rg -i '(^|/)(v5|v6)|scanner|alert|insider|earnings|premarket'`
- `rg -n "shared|marketdata|cache|V5|v5|Polygon|polygon|fallback|stale|telemetry" -S . -g '!node_modules' -g '!vendor' -g '!dist' -g '!build' -g '!*.png' -g '!*.jpg'`
- `rg -n "Ollama|OpenAI|Anthropic|LangChain|broker|real orders|live trading|real-money|order" backend frontend docs README.md -S -g '!frontend/dashboard/node_modules/**'`
- `nl -ba backend/paper/marketdata_adapter.py | sed -n '1,260p'`
- `nl -ba backend/paper/simulator.py | sed -n '250,345p'`
- `nl -ba backend/paper/simulator.py | sed -n '610,690p'`
- `nl -ba backend/api/monitoring.py | sed -n '210,245p'`
- `nl -ba backend/tests/test_phase_d2.py | sed -n '250,365p'`
- `nl -ba backend/tests/test_phase_d2.py | sed -n '430,560p'`
