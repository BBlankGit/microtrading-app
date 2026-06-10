# Codex Review — Phase I4-B Full-Market Movers Candidate Injection and Tick Telemetry Repair

Review target: latest Phase I4-B patch on `BBlankGit/microtrading-app`, commit `5d51ba7` (`Inject full-market movers into candidate universe (Phase I4-B)`).

Review scope: review only. No code changes were made.

## Executive Summary

**Phase I4-B is mostly safe for fake-money monitoring, but I found one material implementation issue that should be fixed before relying on the injected full-market mover universe in unattended paper monitoring:** injected mover symbols are read from the cached full-universe snapshot, but once appended to the paper tick symbol list they flow through the normal market-quality fetch path, which can call Polygon on cache miss/stale fallback. That violates the stated requirement that candidate injection must not add new Polygon calls in the paper tick/candidate injection path.

The patch otherwise preserves fake-money boundaries, exposes the requested telemetry/metadata, keeps shadow scoring diagnostic-only, does not change TP/SL/exit behavior, and updates the user-facing mover tab labels to be session-aware.

## Findings

### 1. Material issue — injected mover symbols can trigger new Polygon calls during the same paper tick

**Status: Needs follow-up.**

The injection step itself calls `intelligence.full_premarket.get_snapshot()` and does not directly fetch Polygon. However, qualifying mover symbols are appended to `symbols`, and the subsequent `_fetch_quality()` pass runs over all entries in `symbols`. If the market-data cache misses, is stale with fallback enabled, or cache usage is disabled, `_fetch_quality()` calls `polygon_client.get_ticker_snapshot(sym)` and `polygon_client.get_previous_close(sym)` for the injected symbol.

Relevant flow:

- Step 0c reads the snapshot and appends injected symbols to `symbols`.
- Step 1 evaluates market quality for every symbol in `symbols`.
- The market-quality path falls through to direct Polygon calls on cache miss/stale fallback/direct mode.

This means the Phase I4-B candidate injection can increase per-tick Polygon call volume by up to the injected top-N count under normal defaults, because `PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED` defaults to true.

**Why it matters:** the review scope explicitly asks whether no new Polygon calls were added in the paper tick/candidate injection path. The implementation currently does add potential calls indirectly through the existing quality-evaluation path.

**Suggested fix direction:** for injected full-market mover symbols, require an already-cached market-quality record or otherwise mark them as missing/stale without fallbacking to Polygon. In other words, make injected mover evaluation cache-only unless the symbol was already part of the active universe for non-injection reasons.

**Test coverage gap:** `test_no_polygon_calls_in_candidate_injection()` verifies only the lookup/snapshot helper path, not `run_tick()` with injected symbols and cache misses. A regression test should execute `run_tick()` with an injected symbol, force cache miss/stale behavior, mock Polygon, and assert no additional Polygon calls happen for injection-only symbols.

## Checklist Review

| # | Review item | Result | Notes |
|---|---|---|---|
| 1 | Tick/status telemetry fixed: `last_tick`, `tick_age_seconds`, `symbols_evaluated`, cache hits/misses/fallbacks update after every tick | Pass | `get_status()` now flattens last tick time, age, symbol count, and market-data counters. `run_tick()` updates market-data counters after quality evaluation and updates `last_tick_at`/`last_tick_symbols_evaluated` before returning. One caveat: if `run_tick()` returns early due to a future exception before these assignments, telemetry would not update, but the current function is not structured around broad early returns. |
| 2 | Full-universe movers are safely merged into candidate universe | Mostly pass | Symbols are uppercased, deduped across mover lists, filtered, and appended only when not already present. They still pass through normal quality/scoring/entry gates. The material caveat is the Polygon-call issue above. |
| 3 | Candidate injection uses cached full-universe movers snapshot only | Pass for the injection read | The injection source is `full_premarket.get_snapshot()`. No scanner refresh is invoked in the injection block. |
| 4 | No new Polygon calls added in paper tick/candidate injection path | **Fail / needs follow-up** | Injection-only symbols can fall through the normal market-quality path and call Polygon on cache miss/stale fallback/direct mode. |
| 5 | Candidate source metadata exposed | Pass | Candidates expose `candidate_sources`, `market_mover_rank`, `market_mover_gap_percent`, `market_mover_session`, and `market_mover_mode`; monitoring also exposes a source breakdown. |
| 6 | Top-N, min gap, max gap, and dedup logic correct | Mostly pass | Top-N is enforced on added symbols, gaps use absolute percent with min/max bounds, and symbol dedup across `top_gainers`, `top_movers`, and `top_losers` is present. Note that `injected_count` counts all filtered mover metadata, including movers already in the base universe, while `added_to_universe` counts only newly appended symbols; this is reasonable but should remain clearly documented. |
| 7 | Full-market mover injected candidates still subject to existing real engine gates | Pass | After injection, symbols use the same tradability, spread, change, volume, catalyst, stale-data, score, daily-loss, position, and trade-count gates as existing candidates. |
| 8 | Shadow score still does not control `eligible`/`action`/`entry_mode` | Pass | Shadow scoring is appended after real decision paths and does not feed the decision branches. |
| 9 | No TP/SL/exit behavior changed | Pass | Phase I4-B did not alter the exit evaluation path. The diff changes are in telemetry, universe injection, runtime config, tests, monitoring, and dashboard labels. |
| 10 | Dashboard/user-facing labels are session-aware and not misleadingly PRE-only | Pass | The tab label now says “Full-Market Movers,” and the tab title changes for premarket, regular, after-hours, and closed sessions. |
| 11 | Tab labeled Full-Market Movers and shows Premarket/Regular/After-Hours/Closed context | Pass | The frontend has the requested label and session title mapping. |
| 12 | No broker/live trading/real orders/AI/LLM/Ollama added | Pass | Review found no new broker/live-order/LLM integrations in the Phase I4-B patch; wording remains fake-money/read-only where relevant. |
| 13 | No V6 hardcoded keys/auth/test endpoints copied | Pass | Review found no V6 key/auth/test endpoint patterns in the touched Phase I4-B areas. |
| 14 | Tests and frontend build pass | Pass | Targeted Phase I4-B tests, full backend pytest suite, and frontend Next build all passed in this container. |
| 15 | Phase I4-B safe for fake-money monitoring | Mostly pass | Safe from a broker/live-order/AI/auth perspective. The Polygon-call issue should be fixed before considering the injection path fully compliant with the stated operational constraints. |

## Additional Notes

- The new runtime configuration defaults enable candidate injection by default with top-N 50, min gap 2%, max gap 40%, and full-universe mode required. Those settings are appropriately scoped to fake-money paper simulation.
- The dashboard copy is improved: the intelligence tab no longer implies PRE-only data when regular-session movers are shown.
- The tests added in `backend/tests/test_phase_i4b.py` are useful smoke/contract checks, but several tests reimplement or inspect helper logic rather than exercising `run_tick()` end-to-end. The no-new-Polygon-calls requirement needs an end-to-end test because the indirect call happens after injection, during market-quality evaluation.

## Verification Commands

- `cd backend && pytest tests/test_phase_i4b.py -q` — passed: `14 passed, 1 warning`.
- `cd backend && pytest -q` — passed: `1019 passed, 2 skipped, 2 warnings`.
- `cd frontend/dashboard && npm run build` — passed. NPM emitted an environment warning about unknown `http-proxy` config, but the Next.js production build completed successfully.
- `rg -n "broker|live_trading|real order|ollama|openai|anthropic|langchain|v6|V6|hardcoded|test endpoint|auth" backend/paper/simulator.py backend/api/monitoring.py backend/core/config.py backend/paper/runtime_config.py backend/tests/test_phase_i4b.py frontend/dashboard/app/page.tsx` — reviewed output for forbidden additions; no new unsafe integration or V6 hardcoded-key/auth/test endpoint copy was found in the Phase I4-B patch.
