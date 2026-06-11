# Codex Review — Phase M1-H3 Final Market Trend Path Telemetry

## Scope

Reviewed the latest checkout for the requested Phase M1-H3 final market trend path telemetry behavior. This review is documentation-only; no application code was changed.

Primary files reviewed:

- `backend/paper/simulator.py`
- `backend/market/trend.py`
- `frontend/dashboard/app/page.tsx`
- `backend/tests/test_phase_m1_h2.py`
- Safety-adjacent backend/frontend code via repository-wide searches for broker/live-order, LLM, futures/provider, and TP/SL/exit changes.

## Overall conclusion

**M1-H3 is not fully safe to approve as final audit telemetry.** The fake-money and safety boundaries still look intact, and backend tests plus the frontend build pass, but the path-name telemetry is still derived before the final entry/evaluation branch is selected. That leaves at least two important audit-label mismatches:

1. A catalyst-pass candidate that also has `momentum_eval["eligible"] == true` is still labeled `legacy_momentum`, even though the actual decision branch takes the catalyst path first.
2. A no-catalyst rejection that later enters through the legacy momentum fallback is still labeled `no_catalyst`, because the path classifier catches every no-catalyst rejection before checking the actual legacy momentum branch.

Those two issues mean `market_trend_path_name`, `market_trend_consumed_by_path`, and `market_trend_regime_used` are not consistently final-branch telemetry yet. They remain pre-branch approximation telemetry in some cases.

## Findings by requested focus area

| # | Focus area | Result | Notes |
|---|---|---|---|
| 1 | `market_trend_path_name` derived from final selected entry/evaluation branch | **Fail** | The classifier runs before the entry decision block. Its ordering is similar to decision precedence, but it does not observe the branch ultimately selected after score pass, no-catalyst, market-mover, and momentum checks. |
| 2 | Catalyst-pass candidates with `_mm_meta` and momentum eligible are labeled catalyst/raw/not consumed | **Fail** | `_mm_meta` alone no longer forces market-mover, but `momentum_eval["eligible"]` still forces `legacy_momentum` for catalyst-pass candidates before the classifier reaches `catalyst`. |
| 3 | No-catalyst candidates that ultimately enter via legacy momentum are labeled `legacy_momentum` | **Fail** | Any `is_no_catalyst_rejection` that is not market-mover eligible is labeled `no_catalyst` before the classifier can account for the later legacy momentum fallback branch. |
| 4 | Actual `market_mover_no_catalyst` entries are labeled `market_mover_no_catalyst` | **Pass** | The classifier labels market-mover only when this is a no-catalyst rejection, `_mm_meta` exists, and `_mm_entry_eligible` is true; this matches the Path D eligibility predicate closely. |
| 5 | Actual `no_catalyst` entries are labeled `no_catalyst` | **Pass for no-catalyst evaluator entries; incomplete for final telemetry overall** | Path C entries satisfy the broad no-catalyst classifier label. The issue is that the same broad label also covers candidates that can fall through to legacy momentum. |
| 6 | Hard rejections before path evaluation remain `rejected_before_path` | **Pass** | Non-no-catalyst hard rejections are labeled `rejected_before_path`, with raw/not consumed regime telemetry. |
| 7 | `_mm_meta`/source metadata alone cannot force market-mover label | **Pass** | The classifier requires both no-catalyst rejection and `_mm_entry_eligible`; `_mm_meta` alone is not sufficient. |
| 8 | Shadow telemetry remains correct | **Pass** | Shadow telemetry remains separate from real entry decisions and uses `_regime_for(_trend_apply_shadow)`. It is appended after the real decision fields and does not drive entries. |
| 9 | Raw/adjusted/used regime labels remain exposed | **Pass** | Candidate rows still expose before/after regime labels and the used label; the dashboard still renders raw/adjusted path usage. |
| 10 | Catalyst path remains not hard-blocked by trend | **Pass** | Catalyst entries are still governed by `hard_rejection is None and scoring["score_pass"]`; market trend is telemetry/consumer-controlled and does not add a catalyst hard block in the reviewed code. |
| 11 | No TP/SL/exit behavior changed | **Pass** | The reviewed market-trend telemetry area does not alter the exit loop or TP/SL calculations. |
| 12 | No broker/live trading/real orders added | **Pass** | The simulator continues to declare fake-money/no-broker boundaries, and repository searches found no new live-order integration in this scope. |
| 13 | No OpenAI/Anthropic/Ollama/LLM calls added | **Pass** | Repository searches found only existing safety comments/tests, not new LLM client usage in this scope. |
| 14 | No futures/provider dependency added | **Pass** | Market trend still advertises ETF proxy mode and explicitly reports futures unavailable. |
| 15 | Backend tests and frontend build pass | **Pass** | `pytest` passed: 1188 passed, 2 skipped. The dashboard production build also passed. |
| 16 | M1-H3 safe for fake-money monitoring and audit telemetry | **Not approved for audit telemetry** | Safe as fake-money monitoring in the narrow execution-safety sense, but not safe to rely on for final path audit labels until items 1–3 are fixed. |

## Detailed evidence

### 1. Path telemetry is still computed before the final branch decision

The simulator computes `_trend_path_name`, `_trend_path_consumed`, and `_trend_path_regime_used` before constructing the candidate row and before the actual entry-decision `if`/`elif` chain. The code comments say the order matches simulator decision precedence, but the values are still selected before the branch is known.

The actual entry branch chain appears later:

- Path A: catalyst entry when `hard_rejection is None and scoring["score_pass"]`.
- Path D: `market_mover_no_catalyst` when no-catalyst rejection and `_mm_eval["eligible"]`.
- Path C: no-catalyst momentum when no-catalyst rejection and `nc_eval["eligible"]`.
- Path B: legacy momentum fallback when no-catalyst rejection and `momentum_eval["eligible"]`.

Because telemetry is calculated earlier, it cannot reliably know which later branch ultimately wins after actual score-pass and fallback evaluation.

### 2. Catalyst + `_mm_meta` + momentum eligible remains mislabeled

The market-mover source metadata bug is partially addressed: a catalyst candidate with `_mm_meta` is not labeled `market_mover_no_catalyst` unless it is also a no-catalyst rejection and market-mover entry eligible.

However, the classifier then checks `momentum_eval and momentum_eval.get("eligible")` before the catalyst fallback. For a catalyst-pass candidate where `hard_rejection is None`, `scoring["score_pass"]` is true, and `momentum_eval["eligible"]` is also true, actual Path A takes the catalyst entry branch. The pre-branch classifier labels the same candidate `legacy_momentum` and may report the legacy consumer's raw/adjusted usage instead of catalyst raw/not consumed defaults.

This fails the requested M1-H3 requirement that catalyst-pass candidates with `_mm_meta` and momentum eligibility be labeled catalyst/raw/not consumed.

### 3. No-catalyst legacy momentum fallback remains mislabeled

The classifier labels any no-catalyst rejection as either `market_mover_no_catalyst` or `no_catalyst` before considering the later legacy momentum fallback. The actual decision chain includes Path B after Path C, allowing a no-catalyst rejection to enter through legacy momentum when market-mover and no-catalyst momentum do not enter but `momentum_eval["eligible"]` is true.

Therefore, no-catalyst candidates that ultimately enter via legacy momentum can still be labeled `no_catalyst`. This fails the requested requirement that such candidates be labeled `legacy_momentum`.

### 4. Market-mover and ordinary no-catalyst labeling

For actual market-mover no-catalyst candidates, the classifier's requirements line up closely with Path D: `is_no_catalyst_rejection`, `_mm_meta is not None`, and `_mm_entry_eligible`. This prevents source metadata alone from forcing the market-mover label and supports correct labels for actual Path D entries.

For actual Path C no-catalyst momentum entries, the broad `is_no_catalyst_rejection` label reports `no_catalyst`. The caveat is that the same broad bucket is too early/too broad when Path C is not selected and Path B later handles the candidate.

### 5. Hard rejections before path evaluation

Hard rejections that are not the no-catalyst rejection class are assigned `rejected_before_path`, `market_trend_consumed_by_path = false`, and `market_trend_regime_used = "raw"`. This is consistent with a candidate that never reaches a path consumer.

### 6. Shadow telemetry

Shadow telemetry remains independent from real trading decisions. The candidate starts with real decision fields, the real decision branch executes, and then shadow scoring is appended afterward. The shadow scorer receives `_regime_for(_trend_apply_shadow)`, and candidate telemetry exposes whether shadow consumed the trend-adjusted regime.

### 7. Raw/adjusted/used regime labels and dashboard exposure

Candidate rows still carry:

- `market_regime_label_before_trend`
- `market_regime_label_after_trend`
- `market_trend_regime_label_used`
- `market_trend_regime_used`
- `market_trend_path_name`

The dashboard type includes the path/used fields and the trend table cell title exposes `regime_used` plus `path`. The cell also renders `[adj]` vs `[raw]` from `market_trend_regime_used`.

### 8. Catalyst trend behavior

The catalyst branch remains the first actual entry branch and is keyed off accepted catalysts plus score pass. The reviewed trend code exposes `MARKET_TREND_APPLY_TO_CATALYST` as a consumer flag; it does not add a hard block to catalyst entries. With the current default behavior observed in the code/tests, catalyst path telemetry is expected to remain raw/not consumed unless the catalyst consumer flag is explicitly enabled and an adjusted regime exists.

### 9. Safety boundaries

I found no evidence in the reviewed scope of new TP/SL/exit changes, broker/live trading/real-order integration, OpenAI/Anthropic/Ollama/LLM calls, or futures/provider dependency. Market trend still reports ETF proxy mode with `futures_available = false`, and the simulator remains fake-money/no-broker.

## Test and build results

- `pytest` from `backend/`: **passed** — 1188 passed, 2 skipped, 2 warnings.
- `cat package.json && (npm ci || npm install) && npm run build` from `frontend/dashboard/`: **passed**. `npm ci` installed the dashboard dependencies from the lockfile, and the Next.js production build completed successfully.

## Recommendation

Do not approve M1-H3 as final audit telemetry yet. The next patch should move final market-trend path telemetry assignment into, or immediately after, the actual selected branch so the telemetry is written from final branch truth rather than inferred from pre-branch predicates.

A safe implementation shape would be:

1. Initialize telemetry to a conservative hard-rejection/default value.
2. In each actual branch, assign the path name and regime-consumer fields from that branch's consumer flag:
   - catalyst → `catalyst`
   - market mover Path D → `market_mover_no_catalyst`
   - no-catalyst Path C → `no_catalyst`
   - legacy momentum Path B → `legacy_momentum`
   - non-path hard rejection → `rejected_before_path`
3. After the branch chain, compute `market_trend_regime_label_used` from the final `market_trend_regime_used` value.
4. Keep shadow telemetry as a separate diagnostic consumer after real decisions are finalized.

Until that change is made, M1-H3 is safe for fake-money execution boundaries but not safe for precise final-path audit telemetry.
