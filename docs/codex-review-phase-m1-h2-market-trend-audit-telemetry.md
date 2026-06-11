# Codex Review: Phase M1-H2 Market Trend Audit Telemetry

Review date: 2026-06-11

Scope reviewed: latest M1-H2 patch only (`2e9f811 Fix market trend audit telemetry`), which modifies:

- `backend/paper/simulator.py`
- `backend/tests/test_phase_m1_h2.py`

## Executive summary

M1-H2 is **mostly safe for fake-money monitoring** because the patch is limited to simulator telemetry/shadow-scoring regime routing plus tests, and it does not add broker/live trading, real orders, LLM calls, futures/provider dependencies, or TP/SL/exit changes.

However, the candidate path telemetry is **not fully correct** yet. The new classifier is computed before the final entry-decision branches and does not exactly mirror actual path precedence for legacy momentum fallback. In particular:

1. A catalyst-pass candidate with `momentum_eval["eligible"] == True` can be labeled `legacy_momentum` even though actual entry logic takes the catalyst path first.
2. A no-catalyst candidate with market-mover ineligible, no-catalyst ineligible, and legacy momentum eligible can be labeled `no_catalyst` even though actual entry logic later takes `legacy_momentum`.

Because of this, M1-H2 is safe from a trading-behavior perspective, but **not safe to rely on as fully accurate audit telemetry** until the path label is aligned with the actual final entry branch or updated after the branch is resolved.

## Detailed review against requested focus areas

### 1. `MARKET_TREND_APPLY_TO_SHADOW` wiring to `compute_shadow_score`

**Verdict: Pass.**

The patch reads `_trend_apply_shadow = bool(_cfg("MARKET_TREND_APPLY_TO_SHADOW"))` once per tick and then sets `_shadow_regime = _regime_for(_trend_apply_shadow)` immediately before calling `compute_shadow_score`. The `tick_regime` argument passed into `compute_shadow_score` is `_shadow_regime`, so the flag is actually wired into the scorer input.

### 2. Shadow true/false config versus raw/adjusted regime input

**Verdict: Pass.**

`_regime_for()` returns `_tick_regime_adjusted` only when the consumer flag is true and an adjusted regime exists; otherwise it returns raw `_tick_regime`. Therefore:

- `MARKET_TREND_APPLY_TO_SHADOW=true` + available adjusted regime -> shadow receives adjusted regime.
- `MARKET_TREND_APPLY_TO_SHADOW=false` -> shadow receives raw regime.
- no adjusted regime available -> shadow receives raw regime even if the flag is true.

The candidate telemetry mirrors this with `market_trend_shadow_consumed` and `market_trend_shadow_regime_used`.

### 3. `trend_consumers.shadow` reflects actual behavior

**Verdict: Pass.**

The trend overlay exposes `trend_consumers["shadow"]` from `settings.MARKET_TREND_APPLY_TO_SHADOW`, while the simulator reads the same logical config via `_cfg("MARKET_TREND_APPLY_TO_SHADOW")` and uses it for `_regime_for(_trend_apply_shadow)`. This means `trend_consumers.shadow` reflects the intended configured behavior, with the normal caveat that actual consumption still requires `_tick_regime_adjusted` to exist.

### 4. Candidate trend path telemetry derives from actual path logic, not merely `_mm_meta` / source metadata

**Verdict: Partial fail.**

The patch improves the previous metadata-derived behavior by no longer labeling every `_mm_meta` candidate as market mover. Catalyst candidates with market-mover metadata now fall through to `catalyst` unless an actual no-catalyst market-mover path is eligible.

But the new classifier is still not fully derived from actual final path logic because it runs before the final entry-decision branch and its ordering differs from the entry branches:

- Actual decision order is catalyst, market-mover no-catalyst, no-catalyst momentum, then legacy momentum fallback.
- The new telemetry classifier checks broad `is_no_catalyst_rejection` before legacy momentum and checks `momentum_eval["eligible"]` outside the actual legacy branch conditions.

This can mislabel legacy/catalyst cases as described in the executive summary.

### 5. Catalyst candidates with market-mover metadata are labeled catalyst/raw/not consumed

**Verdict: Pass for the intended default catalyst case.**

The new classifier only labels `market_mover_no_catalyst` when there is a no-catalyst rejection, market-mover metadata, and market-mover entry eligibility. A catalyst-eligible candidate with market-mover metadata therefore labels as `catalyst`; with default `MARKET_TREND_APPLY_TO_CATALYST=false`, it reports raw/not consumed.

### 6. `market_mover_no_catalyst` candidates are labeled correctly

**Verdict: Pass.**

For no-catalyst rejections where market-mover metadata is present and `_mm_entry_eligible` is true, the telemetry labels `market_mover_no_catalyst`, consumes trend according to `MARKET_TREND_APPLY_TO_MARKET_MOVER`, and reports `trend_adjusted` when an adjusted regime exists and the consumer flag is enabled.

### 7. `no_catalyst` candidates are labeled correctly

**Verdict: Partial pass / edge-case fail.**

A no-catalyst candidate that is not market-mover eligible and is handled by the no-catalyst evaluator is labeled `no_catalyst`, which matches the intended path.

However, if a no-catalyst candidate is not accepted by the market-mover/no-catalyst path but later qualifies for legacy momentum fallback, the current classifier still labels it `no_catalyst` because the broad `elif is_no_catalyst_rejection` branch runs before the legacy momentum check.

### 8. `legacy_momentum` candidates are labeled correctly

**Verdict: Fail.**

The telemetry classifier does not match the actual legacy momentum branch conditions. Actual legacy momentum fallback only runs when `hard_rejection is not None`, `is_no_catalyst_rejection` is true, and earlier market-mover/no-catalyst branches did not enter. The classifier instead:

- labels `legacy_momentum` for any candidate with `momentum_eval["eligible"]` after non-no-catalyst cases, including catalyst-pass candidates; and
- never reaches `legacy_momentum` for no-catalyst candidates because the earlier `elif is_no_catalyst_rejection` catches them first.

This is the primary correctness issue in the patch.

### 9. Rejected-before-path candidates are labeled correctly

**Verdict: Pass.**

Hard rejections that are not no-catalyst rejections are labeled `rejected_before_path`, with `consumed=false` and `regime_used=raw`. This matches the fact that these candidates do not proceed into an entry path that should consume trend-adjusted regime.

### 10. Raw/adjusted/used regime labels exposed in candidate output

**Verdict: Pass.**

The candidate output now includes:

- `market_regime_label_before_trend`
- `market_regime_label_after_trend`
- `market_trend_regime_label_used`

These expose raw, adjusted, and path-used regime labels.

### 11. Catalyst path remains not hard-blocked by trend

**Verdict: Pass.**

`MARKET_TREND_APPLY_TO_CATALYST` is read for telemetry/regime-used reporting, but the catalyst entry branch still depends on the existing `hard_rejection is None and scoring["score_pass"]` condition. No trend hard block was added to catalyst entry.

### 12. No TP/SL/exit behavior changed

**Verdict: Pass.**

The latest patch does not modify the exit loop or `evaluate_virtual_bracket_exit` call sites. The changed simulator lines are in trend consumer flag reading, candidate telemetry, and shadow scoring regime routing.

### 13. No broker/live trading/real orders added

**Verdict: Pass.**

The patch does not add broker imports, live-trading paths, or real order placement. Existing comments continue to state fake-money/no-broker/no-real-orders for the relevant simulator/test surfaces.

### 14. No OpenAI/Anthropic/Ollama/LLM calls added

**Verdict: Pass.**

No OpenAI, Anthropic, Ollama, or LLM calls are introduced by the latest patch. The added tests explicitly describe the scope as no AI/LLM.

### 15. No futures/provider dependency added

**Verdict: Pass.**

The latest patch does not add futures or provider dependencies. The existing trend overlay still reports ETF proxy status and `futures_available: False`.

### 16. Backend tests and frontend build pass

**Verdict: Pass.**

Commands run:

- `python -m pytest` from `backend`: **1188 passed, 2 skipped, 2 warnings**.
- `npm run build` from `frontend/dashboard`: **passed**.

### 17. M1-H2 safe for fake-money monitoring

**Verdict: Conditionally safe.**

M1-H2 is safe for fake-money monitoring from an execution-risk perspective: it does not add live trading, real orders, exit changes, futures/provider dependencies, or LLM calls. Shadow scoring remains diagnostic and is appended after real decisions are finalized.

But the audit telemetry should not yet be treated as fully reliable for path attribution because legacy momentum path labeling is inconsistent with the actual entry-branch logic. I would treat this as **safe to run in fake-money monitoring**, but **not safe as final audit telemetry** until the classifier is corrected or moved to update candidate telemetry from the final selected branch.

## Recommended follow-up

Fix candidate path telemetry by deriving `market_trend_path_name`, `market_trend_consumed_by_path`, and `market_trend_regime_used` from the final entry-decision path, not from a pre-branch approximation. A low-risk approach is:

1. initialize these telemetry fields to `rejected_before_path` or `catalyst` defaults before branch evaluation;
2. set/update them inside each actual branch (`catalyst`, `market_mover_no_catalyst`, `momentum_no_catalyst`, `legacy_momentum`, and final hard rejection); and
3. add runtime tests for the two legacy edge cases rather than only mirroring classifier logic in a helper.
