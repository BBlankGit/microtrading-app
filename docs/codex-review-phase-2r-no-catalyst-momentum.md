# Codex Review — Phase 2R No-Catalyst Momentum Entry Path

Review date: 2026-06-09  
Scope reviewed: latest patch only, `9edd994 Add no-catalyst momentum paper entry path`  
Repository: `BBlankGit/microtrading-app`  
Review artifact only: no application code changed.

## Executive verdict

Phase 2R is directionally safe as a disabled-by-default fake-money feature, and it does not add broker integration, live trading, real orders, AI/LLM calls, or real-money execution.

However, I would **not enable `PAPER_NO_CATALYST_ENTRY_ENABLED` during market monitoring without a small follow-up patch**. Two gating/observability gaps remain:

1. **Fresh-marketdata blocking is not applied to no-catalyst rejections.** The existing stale-data guard only runs when `hard_rejection is None`; no-catalyst candidates necessarily have `hard_rejection` set to `"no accepted catalysts"` or `"only generic_news catalysts"`, so stale fallback metadata can still reach Path C.
2. **The default no-catalyst score/volume thresholds are not strictly stronger than the existing catalyst/global gates.** In particular, the Phase 2R tests intentionally prove a no-catalyst entry at `total_score=65` while the standard catalyst score threshold is `70`, and `PAPER_NO_CATALYST_MIN_VOLUME_RATIO=0.5` is below the existing hard volume default of `0.8`.

A third, lower-severity audit gap: dashboard/live candidates identify the no-catalyst mode and blockers, but the persistent journal/API candidate views do not persist or return the Phase 2R blocker fields.

## Files inspected in the Phase 2R patch

- `backend/core/config.py`
- `backend/paper/runtime_config.py`
- `backend/paper/no_catalyst_momentum.py`
- `backend/paper/simulator.py`
- `backend/api/monitoring.py`
- `backend/tests/test_phase_2r.py`
- `backend/tests/test_phase2kh1.py`

## Findings

### 1. Catalyst entry behavior remains unchanged when Path A is reached

**Status: Pass.**

The patch inserts Path C only after the existing catalyst Path A branch. Catalyst entries still require `hard_rejection is None and scoring["score_pass"]`, still use the normal `PAPER_POSITION_SIZE_PERCENT` budget capped by `PAPER_MAX_POSITION_SIZE_USD`, still pass `entry_mode="catalyst"`, and still append `entry_mode: "catalyst"` to entry output.

The only shared-path additions are computed metadata (`nc_eval`, no-catalyst candidate fields, counters) and do not alter the Path A budget or account call.

### 2. No-catalyst momentum entry exists and is disabled by default

**Status: Pass.**

Phase 2R adds `backend/paper/no_catalyst_momentum.py` with `evaluate_no_catalyst_entry()`. The first gate returns ineligible when `PAPER_NO_CATALYST_ENTRY_ENABLED` is false.

The default config sets:

```python
PAPER_NO_CATALYST_ENTRY_ENABLED: bool = False
```

Runtime config also exposes the same flag as a boolean, runtime-applied `no_catalyst` setting.

### 3. Strict no-catalyst gates exist, but score/volume defaults are not stricter than existing gates

**Status: Needs patch before enabling if “stricter” is required literally.**

Phase 2R adds explicit gates for:

- feature enabled
- bearish catalyst block
- overall score
- scoring `momentum_score` component
- `change_percent`
- `volume_ratio`
- `spread_percent`
- market-regime risk score

The implementation is deterministic and conservative in several places (`change >= 2.0%`, `spread <= 0.20%`, risk-on score default `>= 60`). But the default score and volume thresholds are not strictly stronger than current existing gates:

- `PAPER_NO_CATALYST_MIN_SCORE = 60`, while `PAPER_ENTRY_SCORE_THRESHOLD = 70`.
- The simulator can therefore enter Path C with `score_pass=False`; the new test uses `total_score=65` and `score_threshold=70` to prove the entry path.
- `PAPER_NO_CATALYST_MIN_VOLUME_RATIO = 0.5`, while the pre-existing hard volume gate default is `PAPER_MIN_VOLUME_RATIO = 0.8` and the Phase 2M momentum default is `2.0`.
- Because the simulator hard-gate runs first, the effective no-catalyst default volume floor is usually `0.8`, not `0.5`; still, it is not stricter than the existing global volume gate.

Recommended patch before enabling:

- Raise `PAPER_NO_CATALYST_MIN_SCORE` above or at least equal to the standard catalyst threshold. A conservative value would be `75` or `80`.
- Raise `PAPER_NO_CATALYST_MIN_VOLUME_RATIO` above the global hard gate. If this path is intended to be momentum-like, consider `>= 1.5` or `>= 2.0`.
- Add tests proving a candidate with `total_score < PAPER_ENTRY_SCORE_THRESHOLD` cannot enter no-catalyst mode, unless product intent explicitly allows a lower catalyst score because catalyst score is absent.

### 4. Bearish / strong-bearish catalysts still block entry

**Status: Pass.**

Strong bearish catalysts still set `hard_rejection = "strong_bearish_catalyst"` before no-catalyst eligibility is marked. Since Path C requires `is_no_catalyst_rejection`, strong bearish catalysts do not reach no-catalyst entry.

Phase 2R also adds a no-catalyst-specific block when `PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH` is true and scoring reports `catalyst_sentiment == "bearish"`.

### 5. Stale/missing marketdata cannot produce entries — missing is safe, stale fallback needs a patch

**Status: Needs patch before enabling.**

Missing/no-fallback cache data is safe: the cache fetch path returns early without adding quality data, so the entry loop has no candidate to enter.

The stale fallback case is weaker. The existing fresh-entry guard is:

```python
if hard_rejection is None and PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY and marketdata_stale:
    hard_rejection = "stale_marketdata_entry_blocked"
```

No-catalyst candidates necessarily have `hard_rejection` already set to `"no accepted catalysts"` or `"only generic_news catalysts"`, so this stale guard does not run for the Path C use case. If a symbol has stale cache metadata and Polygon fallback is allowed, the simulator can keep `marketdata_stale=True`, then still evaluate Path C from the no-catalyst hard rejection.

Recommended patch before enabling:

- Apply the stale/fresh-entry block before no-catalyst classification, or independently of `hard_rejection is None`.
- Ensure stale marketdata is not treated as a no-catalyst rejection eligible for Path C.
- Add a Phase 2R test where `PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY=True`, cache metadata reports stale, catalysts are empty, no-catalyst mode is enabled, and the expected result is no entry with `rejection_reason="stale_marketdata_entry_blocked"` (or equivalent blocker).

### 6. No-catalyst position-size multiplier applies only to `momentum_no_catalyst`

**Status: Pass.**

Path C computes normal budget, then multiplies by `PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER`, and enters with `entry_mode="momentum_no_catalyst"`.

Catalyst Path A still uses the unmultiplied normal budget. Momentum Path B still uses `PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER`. The two multipliers are separate.

### 7. Candidate/dashboard/monitoring/journal identify entry mode and blockers — partial

**Status: Partial; patch recommended for journal audit clarity.**

What is good:

- Runtime candidate dictionaries include `entry_mode`, `no_catalyst_momentum_eligible`, `no_catalyst_momentum_reasons`, `no_catalyst_momentum_blockers`, `no_catalyst_config_snapshot`, and `catalyst_required`.
- `/api/paper/dashboard` returns `last_candidates` directly from simulator state, so the dashboard payload inherits those fields.
- `/api/monitoring/status` now includes `no_catalyst_mode`, config values, fake-money disclaimer, and a warning when enabled.
- Entry/trade journal rows include `entry_mode`, so actual no-catalyst entries can be distinguished from catalyst and momentum entries.

Gap:

- `paper.journal.persist_tick_result()` does not persist the new no-catalyst candidate fields (`no_catalyst_momentum_eligible`, reasons, blockers, config snapshot, catalyst_required).
- `/api/journal/candidates` does not return even the existing candidate `entry_mode` field, nor the Phase 2R blocker fields.

Recommended patch before extended monitoring/audit use:

- Add idempotent DB columns or JSON fields for no-catalyst candidate eligibility/blockers/config snapshot, or include them in a generic candidate-details JSON column.
- Update journal persistence and `/api/journal/candidates` to return `entry_mode` and Phase 2R blocker fields.

### 8. Marketdata cache-first behavior remains intact

**Status: Pass.**

The Phase 2R patch does not change the cache-first fetch path. Fresh cache hits still skip Polygon entirely. Stale/missing with fallback disabled still return early and record missing/error counters. Stale/missing with fallback enabled still fall through to Polygon fallback. Existing D2/D2-H1 tests continue to pass.

### 9. Tests avoid real Polygon calls

**Status: Pass for Phase 2R tests.**

The simulator-level Phase 2R tests patch:

- `paper.simulator.polygon_client.get_ticker_snapshot`
- `paper.simulator.polygon_client.get_previous_close`
- `paper.simulator.evaluate_market_quality`
- `paper.simulator.collect_news_for_symbols`
- persistence/save-state helpers

Unit tests for `evaluate_no_catalyst_entry()` do not call Polygon at all.

### 10. No forbidden broker/live/AI/LLM/real-money execution added

**Status: Pass.**

The added implementation is deterministic and fake-money only. The patch adds explicit disclaimers in the no-catalyst evaluator, config comments, and monitoring output. A diff scan found no added broker/AI execution integration; forbidden words only appear in safety disclaimers and test deny-lists.

### 11. Phase 2R safety for fake-money monitoring

**Status: Safe while disabled; not ready to enable without the follow-up patch above.**

With `PAPER_NO_CATALYST_ENTRY_ENABLED=False` (the default), Phase 2R is safe for fake-money monitoring. It adds observability metadata and config schema without activating new entries.

When enabled, it remains fake-money only, but I recommend patching the stale-marketdata guard and tightening score/volume thresholds first.

### 12. Is any patch required before enabling?

**Yes.** Recommended minimum patch before enabling:

1. Block stale marketdata before Path C can evaluate/enter.
2. Make no-catalyst defaults demonstrably stricter than standard catalyst/global gates, especially score and volume.
3. Persist/return Phase 2R blocker fields in journal candidate output for post-run auditability.

## Verification commands run

```bash
git show --stat --oneline --decorate HEAD
git diff HEAD^ HEAD -- backend/paper/simulator.py backend/core/config.py backend/paper/runtime_config.py backend/api/monitoring.py
PYTHONPATH=backend pytest -q backend/tests/test_phase_2r.py backend/tests/test_phase2kh1.py
PYTHONPATH=backend pytest -q backend/tests/test_phase_d2.py backend/tests/test_phase_d2_h1.py backend/tests/test_phase2m.py backend/tests/test_phase_2r.py
PYTHONPATH=backend pytest -q backend/tests
git diff HEAD^ HEAD -- . | rg -n "^\\+.*(openai|anthropic|langchain|ollama|alpaca|ibapi|tastytrade|schwab|place_order|submit_order|execute_order|send_order|broker|live trading|real orders|real-money)" -i || true
```

## Test results

- `backend/tests/test_phase_2r.py backend/tests/test_phase2kh1.py`: 77 passed, 1 warning.
- `backend/tests/test_phase_d2.py backend/tests/test_phase_d2_h1.py backend/tests/test_phase2m.py backend/tests/test_phase_2r.py`: 92 passed, 1 warning.
- Full backend test suite: 774 passed, 1 skipped, 1 warning.
