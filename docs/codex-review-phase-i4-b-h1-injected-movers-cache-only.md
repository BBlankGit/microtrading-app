# Codex Review — Phase I4-B-H1 Injected Movers Cache-Only Fix

Date: 2026-06-10

Reviewed patch: `a79cb65` (`Make injected market movers cache-only (Phase I4-B-H1)`)

## Scope

Only the latest Phase I4-B-H1 patch was reviewed. The review covered:

- `backend/paper/simulator.py`
- `backend/tests/test_phase_i4b_h1.py`

No production code changes were made by this review.

## Verdict

**Approved / safe for fake-money monitoring and Polygon pressure reduction.**

The patch correctly makes symbols that are added only by full-market mover injection cache-only during paper tick market-quality evaluation. Fresh cache hits continue through the existing fake-money paper gates. Cache miss, stale-cache, and cache-disabled paths reject injected-only symbols before the Polygon fallback/direct section can run. Symbols already present in the base universe are not classified as injection-only and retain normal existing marketdata behavior.

## Review Findings

No blocking findings were identified.

## Detailed Checklist

### 1. Injection-only symbols are cache-only during paper tick evaluation

Pass. The patch defines `_injection_only_symbols` from `_movers_added`, which is populated only when a mover symbol is appended to the active paper universe and was not already present. This makes the cache-only restriction apply to mover-added symbols only.

### 2. Injection-only cache miss/stale cases do not call Polygon fallback/direct methods

Pass. In the cache-enabled branch, stale or missing injected-only symbols return before the Polygon fallback metadata and Polygon call section. In the cache-disabled branch, injected-only symbols also return before `polygon_direct` is incremented and before either Polygon client method is called.

### 3. Symbols already present in the base universe can still follow normal existing marketdata behavior

Pass. A symbol already in `symbols` receives mover metadata but is not appended to `_movers_added`, so it is not in `_injection_only_symbols`. It therefore continues through the existing cache miss/stale fallback behavior when fallback is enabled, including Polygon fallback/direct behavior where configured.

### 4. Injected candidates are safely rejected/skipped when fresh cache is unavailable

Pass. Fresh cache misses, stale cache responses, and cache-disabled scenarios for injection-only symbols produce an error entry, increment missing marketdata accounting, and return without adding quality data. Because no `quality_map` entry is produced, those symbols are skipped by later candidate/entry evaluation for that tick.

### 5. `candidate_sources` metadata remains correct

Pass. Mover metadata is still stored in `_mover_meta_map` for accepted mover snapshot rows, and candidate construction tags any symbol with mover metadata as `full_market_movers`. If no mover metadata is present, the candidate source falls back to `dynamic`.

### 6. `run_tick` end-to-end tests prove no Polygon calls for injection-only symbols

Pass. The new test suite includes direct end-to-end `run_tick()` coverage with mocked Polygon methods that assert injection-only symbols do not appear in `get_ticker_snapshot` or `get_previous_close` call arguments for cache miss, stale cache, and cache-disabled paths. It also verifies that base-universe symbols still can call Polygon.

### 7. Existing real engine gates still decide eligible/action/entry_mode

Pass. The patch does not change the existing quality, catalyst, score, momentum, no-catalyst, daily-loss, account-capacity, or entry-mode decision branches. Injection-only symbols that have fresh cache data proceed into those existing branches; injection-only symbols without fresh marketdata never receive quality data and therefore cannot enter.

### 8. Shadow score still does not control entries

Pass. Shadow scoring remains appended after real decision fields are finalized. The H1 tests also assert that `compute_shadow_score()` does not emit `eligible`, `action`, `entry_mode`, or `rejection_reason` keys.

### 9. No TP/SL/exit behavior changed

Pass. The latest patch only changes injection-only marketdata handling and adds H1 tests. Runtime TP/SL/max-hold config reads and existing exit sections were not changed by the patch.

### 10. No broker/live trading/real orders/AI/LLM/Ollama were added

Pass. The simulator patch remains in fake-money paper simulation code and adds no broker/live-order integrations. The new test suite includes a forbidden-import AST check for broker/live trading and common AI/LLM packages in `paper/simulator.py`.

### 11. No V6 hardcoded keys/auth/test endpoints were copied

Pass. The reviewed patch does not add keys, auth code, test endpoints, or endpoint registration. It only adds local paper simulator control flow and tests.

### 12. Tests and frontend build pass

Pass.

Commands run:

```bash
pytest backend/tests/test_phase_i4b_h1.py
pytest backend/tests
(cd frontend/dashboard && npm run build)
```

Results:

- `pytest backend/tests/test_phase_i4b_h1.py`: 10 passed, 1 warning.
- `pytest backend/tests`: 1029 passed, 2 skipped, 2 warnings.
- `npm run build` in `frontend/dashboard`: passed. npm emitted an `Unknown env config "http-proxy"` warning before the Next.js build; the build completed successfully.

### 13. Safety for fake-money monitoring and Polygon pressure

Pass. The fix is safe for fake-money monitoring and should reduce Polygon pressure from full-market mover injection because mover-only candidates can no longer trigger per-symbol Polygon calls when cache is stale, missing, or disabled. Existing base-universe symbols retain the prior behavior, preserving monitoring continuity and avoiding a broad marketdata behavior change.

## Notes / Non-blocking Observations

- When cache fallback is disabled and the cache adapter returns an existing `_no_fallback` source, the pre-existing no-fallback branch rejects before the new injection-only branch. This still satisfies the no-Polygon requirement; the error key remains the generic cache no-fallback error rather than the H1 injected-mover-specific error key in that configuration.
- The H1 test helper imports `MagicMock` but does not use it. This is harmless and non-blocking.
- The full backend test run reports an existing `RuntimeWarning` from `unittest.mock` during one H1 test, but all tests pass.
