# Codex Review — Phase M1-H4 Final Branch Market Trend Telemetry

Date: 2026-06-11  
Branch reviewed: `work`  
Latest patch reviewed: `d345e15 Set trend telemetry from final branch`

## Scope

Reviewed only the latest M1-H4 patch, which changes:

- `backend/paper/simulator.py`
- `backend/tests/test_phase_m1_h4.py`

No application code changes were made as part of this review.

## Verdict

**PASS — no blocking findings.**

M1-H4 correctly moves final `market_trend_path_name` and related final audit telemetry to be derived from the actual selected entry branch rather than the earlier pre-branch predicate classifier. The patch is safe for fake-money monitoring and final audit telemetry.

## Detailed Review

### 1. Final `market_trend_path_name` comes from the actual selected branch

Pass. The patch introduces `_final_selected_path`, initializes it to `"rejected_before_path"` immediately before the entry decision chain, assigns it inside each actual branch, and writes final telemetry only after that branch chain via `_trend_usage_for_path(_final_selected_path, ...)`.

- Default before branch selection: `rejected_before_path`.
- Path A sets `catalyst`.
- Path D sets `market_mover_no_catalyst`.
- Path C sets `no_catalyst`.
- Path B sets `legacy_momentum`.
- Final candidate telemetry is overwritten after the branch chain from `_final_selected_path`.

### 2. Pre-branch classifier removed / no longer drives final telemetry

Pass. The M1-H2/M1-H3 pre-branch `if/elif` classifier that inferred `_trend_path_name` from broad predicates was removed. The remaining pre-branch initialization is conservative only and is overwritten after the branch chain.

### 3. Catalyst-pass candidates with `_mm_meta` and momentum eligibility

Pass. Catalyst remains first in the branch order. A candidate with `hard_rejection is None` and `scoring["score_pass"]` selects Path A before market-mover, no-catalyst, or legacy momentum fallbacks can run, so final telemetry is `catalyst`.

Because `MARKET_TREND_APPLY_TO_CATALYST` defaults to `False`, catalyst path telemetry remains raw / not consumed unless explicitly opted in by configuration.

### 4. No-catalyst candidates that enter via legacy momentum

Pass. Legacy momentum fallback is reached only after market-mover and no-catalyst branches do not select. When it does select, `_final_selected_path` is set to `legacy_momentum`, so final telemetry reports the actual legacy branch rather than a no-catalyst inference.

### 5. Actual `market_mover_no_catalyst` entries

Pass. The market-mover no-catalyst branch assigns `_final_selected_path = "market_mover_no_catalyst"` before its entry logic. Final telemetry is therefore labeled `market_mover_no_catalyst` for this selected branch.

### 6. Actual `no_catalyst` entries

Pass. The no-catalyst branch assigns `_final_selected_path = "no_catalyst"` before its entry logic. Final telemetry is therefore labeled `no_catalyst` for this selected branch.

### 7. Actual `legacy_momentum` entries

Pass. The legacy momentum fallback branch assigns `_final_selected_path = "legacy_momentum"` before its entry logic. Final telemetry is therefore labeled `legacy_momentum` for this selected branch.

### 8. Hard rejections before path evaluation

Pass. `_final_selected_path` defaults to `rejected_before_path`. Candidates that hit the hard-rejection fallback without selecting a path leave that default intact, so final telemetry remains conservatively `rejected_before_path`.

### 9. `_mm_meta` / source metadata alone cannot force market-mover label

Pass. `_mm_meta` only participates in market-mover evaluation and branch eligibility. It no longer assigns `market_trend_path_name` directly. The market-mover label can only appear if the actual Path D branch is selected and `_final_selected_path` is assigned there.

### 10. Momentum eligibility alone cannot force `legacy_momentum` if catalyst wins

Pass. Since Path A runs first and sets `_final_selected_path = "catalyst"`, a catalyst-pass candidate that is also momentum eligible remains labeled `catalyst`. Momentum eligibility only labels final telemetry as `legacy_momentum` if the actual legacy fallback branch is selected.

### 11. `is_no_catalyst_rejection` alone cannot force `no_catalyst` if legacy branch wins

Pass. The old inference path labeled any no-catalyst rejection as `no_catalyst` too early. M1-H4 now labels `no_catalyst` only inside the actual no-catalyst branch. If that branch does not select and legacy momentum does, the final label is `legacy_momentum`.

### 12. Shadow telemetry remains separate

Pass. Shadow telemetry still uses its independent `MARKET_TREND_APPLY_TO_SHADOW` path and `_regime_for(_trend_apply_shadow)` for shadow scoring. The final path helper does not feed shadow scoring, and shadow fields remain separate from `market_trend_path_name`.

### 13. Raw / adjusted / used regime labels remain exposed

Pass. Candidate telemetry still exposes:

- `market_regime_label_before_trend`
- `market_regime_label_after_trend`
- `market_trend_regime_label_used`

The helper returns the used label from the adjusted regime only when the selected path actually consumes trend-adjusted regime; otherwise it returns the raw regime label.

### 14. Catalyst path remains not hard-blocked by trend

Pass. The catalyst path still uses the existing `hard_rejection is None and scoring["score_pass"]` branch condition. The patch does not add a trend-regime hard block to catalyst entry. The catalyst trend consumer default remains disabled.

### 15. No TP / SL / exit behavior changed

Pass. The latest patch changes only trend-path telemetry and tests. No TP, SL, bracket-exit, intrabar-exit, or account exit logic was modified.

### 16. No broker / live trading / real orders added

Pass. No broker, live-trading, or real-order integration was added. The simulator remains documented as fake-money / no broker / no real orders.

### 17. No OpenAI / Anthropic / Ollama / LLM calls added

Pass. The patch adds a pure telemetry helper, branch-local string assignments, and tests only. No OpenAI, Anthropic, Ollama, or LLM calls were added.

### 18. No futures / provider dependency added

Pass. No dependency file was changed, and no futures/provider dependency was added.

### 19. Backend tests and frontend build

Pass.

Commands run:

```bash
cd backend && pytest tests/test_phase_m1_h4.py
cd backend && pytest
cd frontend/dashboard && npm run build
```

Results:

- `pytest tests/test_phase_m1_h4.py`: 14 passed, 1 warning.
- `pytest`: 1202 passed, 2 skipped, 2 warnings.
- `npm run build`: passed.

### 20. Safe for fake-money monitoring and final audit telemetry

Pass. The final audit fields now reflect selected branch truth rather than pre-branch inference, while preserving raw/adjusted/used labels and shadow separation. No trading semantics or external execution pathways were changed.

## Notes on Test Coverage

The added `test_phase_m1_h4.py` coverage checks the pure helper behavior and AST-level wiring invariants:

- canonical path names;
- raw vs trend-adjusted consumption per consumer flag;
- unknown paths falling back to `rejected_before_path`;
- `_final_selected_path` initialization and branch assignments;
- final helper call using `_final_selected_path`;
- removal of direct `_trend_path_name = "<branch>"` assignments from `run_tick`.

This is appropriate for the patch because the change is intentionally narrow: final telemetry derivation, not entry semantics.

## Final Finding

No changes requested. M1-H4 satisfies the requested final-branch trend telemetry contract.
