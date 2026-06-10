# Codex Review — Phase S1-V1-H2 Time-Adjusted Volume Propagation

Review date: 2026-06-10

Scope reviewed: latest S1-V1-H2 patch only (`2b6d590 Complete time-adjusted volume propagation and UI clarity`).

## Verdict

**Conditionally safe for fake-money monitoring.** The patch correctly propagates computed time-adjusted relative volume into the scoring and entry evaluators, keeps raw `volume_ratio` visible separately, safely rejects missing adjusted-volume inputs during the regular session, avoids adding a Polygon call path for the new adjusted-volume logic, clears auto-resume telemetry on reset, and improves override/gate clarity in the dashboard.

One non-blocking hardening gap remains: Redis-loaded Reddit rows are **validated** but not fully **normalized** before being trusted. The current validator rejects `Company N` fixtures and missing fields, but it can still accept valid-looking rows with unnormalized numeric/string types because `ensure_loaded()` stores the filtered Redis rows directly instead of running them through the canonical row normalizer. For fake-money monitoring this is acceptable because the path is read-only intelligence/shadow context, but it should be tightened in the next hardening pass.

## Checklist Results

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Adjusted `q` / time-adjusted volume is passed into `score_candidate()`, `evaluate_momentum_entry()`, and `evaluate_no_catalyst_entry()` | Pass | `run_tick()` builds `_q_for_paths` with `volume_ratio` replaced by `_ta_ratio` when adjusted mode is active and computable, then passes `_q_for_paths` to all three functions. |
| 2 | Raw `volume_ratio` remains exposed separately | Pass | Candidate output still stores raw `q.get("volume_ratio")`, while separate fields expose `time_adjusted_volume_ratio`, `volume_gate_type`, and `volume_gate_ratio_used`. |
| 3 | Missing/invalid adjusted volume rejects safely when adjusted mode is enabled during regular session | Pass | `_ta_vol_missing` is set when adjusted mode is configured for regular session but `_tv_ratio()` returns `None`, and the hard-gate rejection becomes `missing_time_adjusted_volume` before any raw-volume fallback can pass. |
| 4 | No new Polygon calls were added in paper tick path | Pass | The patch only changes adjusted-volume computation from already available quality fields. The helper module has no Polygon dependency, and the existing market-data fetch/fallback path is unchanged. |
| 5 | Reddit Redis-loaded rows are normalized/validated before being trusted | Partial | Rows are validated before trust, but not fully normalized; `ensure_loaded()` assigns filtered Redis row dictionaries directly to `_current`. |
| 6 | Test-like cached rows such as `Company 0` / `Company 1` are rejected | Pass | `_TEST_NAME_RE` rejects `Company N` fixture names, and `ensure_loaded()` fetches fresh if all cached rows fail validation. |
| 7 | Valid ApeWisdom rows still load and refresh correctly | Pass | Valid cached rows load without forced refresh and are marked half-expired so the normal refresh cadence resumes soon. Fresh API fetches still run through `_normalize_rows()`. |
| 8 | Reset clears auto-resume telemetry appropriately | Pass | `reset_simulator()` clears `desired_running`, `auto_resumed`, `auto_resumed_at`, `auto_resume_attempted`, `auto_resume_source`, and `auto_resume_warning`. |
| 9 | Dashboard distinguishes changed override vs stored override equal to base vs default | Pass | The dashboard computes changed vs same-as-base override counts and uses separate labels/border colors for changed overrides, stored base-equivalent overrides, and no overrides. |
| 10 | Dashboard explains `PAPER_MIN_VOLUME_RATIO=0.8`, `PAPER_NO_CATALYST_MIN_VOLUME_RATIO=1.5`, and `PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN=0.8` as separate gates | Pass | The Time-Adjusted Volume Gate panel explicitly documents the catalyst/standard raw gate, no-catalyst raw gate, and regular-session adjusted gate separately. |
| 11 | TP/SL/exit behavior was not changed | Pass | The S1-V1-H2 diff does not touch the exit module or the simulator exit section; changed simulator lines are reset telemetry and entry-volume handling only. |
| 12 | Shadow score still does not execute trades | Pass | Shadow scoring is appended after entry decisions and candidate/account mutations, and the aggregate disclaimer remains diagnostic-only. |
| 13 | No broker/live trading/real orders/AI/LLM/Ollama were added | Pass | No new integrations of that kind appear in the patch; touched files retain fake-money/no-broker language. |
| 14 | Tests and frontend build pass | Pass | `pytest -q` passed with 1083 passed, 2 skipped, 2 warnings. `npm run build` passed for the dashboard. |
| 15 | S1-V1-H2 is safe for fake-money monitoring | Conditional pass | Safe for fake-money monitoring with the Reddit Redis normalization caveat above. No evidence of live execution, broker integration, or shadow-score trading side effects. |

## Detailed Findings

### 1. Time-adjusted volume propagation

`run_tick()` now computes `_ta_ratio` from `day_volume`, `previous_day_volume`, the per-tick session elapsed ratio, and the configured floor. When adjusted volume is enabled during the regular session and `_ta_ratio` is available, `_q_for_paths` is built as `dict(q, volume_ratio=_ta_ratio)`. That adjusted quality view is then passed into:

- `score_candidate(sym, _q_for_paths, cats)`
- `evaluate_momentum_entry(sym, _q_for_paths, _tick_regime)`
- `evaluate_no_catalyst_entry(sym, _q_for_paths, scoring, _tick_regime)`

This is the right propagation model because the existing scoring/evaluator functions all read `quality["volume_ratio"]` for their volume component/gates. Raw quality data is not mutated globally; only the downstream entry/scoring view receives the adjusted value.

### 2. Raw volume remains visible

The candidate payload still exposes raw `volume_ratio` from `q`, not `_q_for_paths`. The patch adds separate adjusted-volume telemetry:

- `time_adjusted_volume_enabled`
- `time_adjusted_volume_ratio`
- `expected_volume_now`
- `prev_day_volume`
- `session_elapsed_ratio`
- `volume_gate_type`
- `volume_gate_ratio_used`
- `volume_gate_threshold_used`

This cleanly separates raw market-quality telemetry from the effective gate ratio used for decisions.

### 3. Missing adjusted volume safety

When adjusted mode is enabled during regular session but `_tv_ratio()` cannot produce a finite ratio, `_ta_vol_missing` is set and the candidate hard-rejects with `missing_time_adjusted_volume`. This prevents silent fallback to the raw `PAPER_MIN_VOLUME_RATIO` gate in the regular-session adjusted mode.

`paper.time_adjusted_volume.time_adjusted_volume_ratio()` already returns `None` for missing, non-numeric, non-finite, negative day volume, or non-positive previous-day volume inputs, so invalid adjusted-volume inputs are treated as unavailable rather than allowed through.

### 4. Polygon call surface

The S1-V1-H2 changes do not introduce a new data fetch. Adjusted volume is derived from fields already present in each symbol's market-quality `q`. The existing paper tick path still has the same Polygon fallback/direct fetch logic, and the new time-adjusted-volume helper does not import or call Polygon.

### 5. Reddit Redis cache validation

The patch improves Redis cache safety by adding `_is_valid_cached_row()` and applying it inside `ensure_loaded()` before accepting cached rows. This rejects missing/invalid tickers, missing `rank`/`mentions`, and `Company N` fixture names.

However, the validation function's docstring says rows without numeric rank/mentions are rejected, while the implementation only checks that `rank` and `mentions` are not `None`. Also, accepted Redis rows are assigned directly to `_current` without passing through `_normalize_rows()`. That means a cached row such as `{"ticker": " nvda ", "rank": "1", "mentions": "5000"}` can be trusted in a partially unnormalized form if it passes the current regex/non-`None` checks.

Recommendation for the next patch: normalize Redis-loaded `cached` and `prev` rows through the same canonical normalization path used for fresh ApeWisdom results, then validate the normalized rows and reject rows whose `rank`/`mentions` cannot be converted to numbers.

### 6. Override UI and gate clarity

The dashboard now distinguishes:

- no stored overrides / base config only,
- stored overrides equal to base values, and
- changed overrides that actually alter behavior.

It also adds a clear Time-Adjusted Volume Gate note explaining that:

- `PAPER_MIN_VOLUME_RATIO` is the catalyst/standard raw gate, default `0.8`,
- `PAPER_NO_CATALYST_MIN_VOLUME_RATIO` is the no-catalyst raw gate, default `1.5`, and
- `PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN` is the adjusted regular-session gate, default `0.8`.

This resolves the main UI ambiguity from the S1-V1-H2 scope.

### 7. Exit, shadow, and execution safety

No TP/SL/max-hold exit behavior was changed by the S1-V1-H2 patch. Shadow scoring remains post-decision diagnostic metadata and still does not mutate `eligible`, `action`, `entry_mode`, account state, or order-entry paths. No broker, live-trading, real-order, AI/LLM, or Ollama integration was added.

## Tests / Builds Run

- `pytest -q` from `backend/`: passed — 1083 passed, 2 skipped, 2 warnings.
- `npm install` from `frontend/dashboard/`: completed; dependencies were already up to date. NPM emitted a warning about unknown env config `http-proxy`.
- `npm run build` from `frontend/dashboard/`: passed.

## Final Safety Assessment

S1-V1-H2 is **safe for fake-money monitoring**. The adjusted-volume entry logic now uses one effective volume view consistently across catalyst scoring, legacy momentum fallback, and no-catalyst momentum. Missing adjusted-volume inputs fail closed during regular-session adjusted mode. The UI is clearer about override semantics and the three separate volume gates.

The only follow-up I recommend is tightening Reddit Redis cache normalization so cached data has exactly the same canonical schema as freshly fetched ApeWisdom data before it is trusted.
