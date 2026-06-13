# Codex Review — Phase G1B-H8 DB Audit Readiness

**Verdict: PASS WITH CAVEATS**

## 1. Executive summary

G1B-H8 resolves the two largest G1B-H7 follow-up items: the dead aggregate `WalletDailyAnalytics` implementation has been removed from the dashboard source, and `/api/audit/persistence/deep-status` is now a much more complete, evidence-oriented audit endpoint.

The endpoint now reports explicit candidate tick timestamp persistence status, candidate grouping, extras JSON field-family coverage, evidence-based deterministic/AI shadow persistence counts, trade timestamp integrity, derived New York session grouping, outcome completeness fields, and top-level `analysis_ready` / `blocking_gaps` / `warnings` fields.

I am marking this **PASS WITH CAVEATS**, not a clean PASS, because several aspects remain intentionally sampled or approximate rather than full-table proof:

- extras JSON family coverage and shadow persistence evidence use the most recent 5,000 candidate rows with `extras_json`, not the full table;
- the endpoint documents that candidate `tick_ts` is not stored as a candidate column and uses `paper_ticks.started_at` via `tick_id` as the derivable tick timestamp;
- `analysis_ready` is global engine-analysis readiness and can still be true while shadow/AI decision persistence warnings exist;
- outcome `missing_resolved_at_count` is derived from statuses (`pending`, `missing_data`, `error`) rather than directly counting `resolved_at IS NULL`.

These caveats are visible in the response shape and do not block the G1B-H8 patch from satisfying the requested follow-up at the source-review level.

## 2. Dashboard regression findings

**Pass.** The dead aggregate daily analytics component is gone. The latest patch leaves only a comment documenting that the aggregate component was removed and that per-engine reports live in `EngineDailyReportsSection` without summing across engines.

The dashboard still renders three independent account cards via explicit `EngineAccountCard` instances for `engine`, `deterministic_shadow`, and `ai_shadow`, and the header states there is no combined balance.

The dashboard still renders three same-structure daily report cards via explicit `EngineDailyReportCard` calls for the same three wallet IDs.

The dashboard still renders three decision analytics panels via explicit `EngineDecisionAnalyticsCard` calls for `engine`, `deterministic_shadow`, and `ai_shadow`.

Trading Activity remains wallet-tagged and continues to render `WalletExplorer` with `walletId` and `onWalletChange`.

No primary all-wallet account cash/equity metric was reintroduced. The Simulator Status section explicitly says there is no combined cash/equity total across engines.

## 3. DB audit/readiness findings

**Mostly pass.** `/api/audit/persistence/deep-status` was substantially expanded.

### Candidate tick timestamp audit

The endpoint explicitly states that `tick_ts` is not persisted as a candidate column, explains that the tick start time is in `paper_ticks.started_at`, and reports joinability from candidates to ticks through `tick_id`. This satisfies the “do not confuse `tick_id` with `tick_ts`” requirement.

Caveat: because `tick_ts` is not persisted on `paper_candidates`, the endpoint does not report candidate-column `tick_ts_min`, `tick_ts_max`, `missing_tick_ts_count`, or `tick_ts_coverage_percent`. It instead reports equivalent derived support under `paper_ticks_started_at_min`, `paper_ticks_started_at_max`, `paper_ticks_missing_started_at`, and candidate-to-tick join coverage.

### Candidate grouping

The endpoint reports candidates by action, rejection reason, marketdata/source, catalyst type, entry mode, and decision reason. This covers the requested action/rejection/source/catalyst/path-style grouping dimensions where persisted.

Caveat: the new engine/decision grouping is represented primarily through `entry_mode`, `decision_reason`, and the separate shadow-decision persistence section, rather than a single consolidated “engine decision type” grouping.

### Extras JSON field-family coverage

The endpoint now includes family probes for marketdata, catalyst/news, Reddit, earnings, insider, market regime/trend, deterministic shadow, AI shadow, AI disabled/error-style state, selected path, and score components.

Caveat: this is sampled over the most recent 5,000 rows with `extras_json`, and each family reports `sample_size`, `present`, `coverage_percent`, and keys. It does not add an explicit `coverage_scope: sampled` field or a `not_collected` string when `present == 0`; status must be inferred from `present == 0` and `coverage_percent == 0.0`.

### Outcome completeness

The endpoint reports total outcomes, outcome rows by status/horizon/source, resolved-at min/max, distinct candidates with any outcome, candidates with all five horizons, and a missing-by-horizon map.

Caveat: `missing_outcome_count_by_horizon` counts outcome rows in `pending`, `missing_data`, or `error` statuses by horizon; it does not directly compute “candidates missing each required horizon row entirely.” Also, `missing_resolved_at_count` is status-derived rather than a direct `resolved_at IS NULL` count.

## 4. Shadow/AI persistence findings

**Pass with sampling caveat.** G1B-H8 replaces unconditional separability booleans with evidence-based values.

The deterministic shadow audit counts rows with `enhanced_shadow_decision`, rows with score, `WOULD_ENTER`, `WATCH`, `WOULD_REJECT`, missing decisions, and returns `status: collected` or `not_collected` based on actual sampled rows.

The AI shadow audit counts rows with `llm_decision`, rows with `llm_status`, `WOULD_ENTER`, `WATCH`, `WOULD_REJECT`, `disabled`, `error`, `not_selected`, missing decision/status, and returns `status: collected` or `not_collected` based on sampled rows.

The old unconditional `deterministic_shadow_data_separable: True` and `ai_shadow_data_separable: True` values are now tied to sampled evidence and include supporting counts in `analysis_readiness`.

Caveat: deterministic/AI persistence evidence is sampled from the most recent 5,000 rows with `extras_json`; it is not full-table proof.

## 5. Timestamp/session-date findings

**Pass with caveats.** Trade timestamp auditing is now explicit.

The endpoint reports missing entry/open timestamp counts, missing exit/closed timestamp counts, created/opened/closed min/max, future opened/closed anomaly counts, and explicitly documents the mapping: `opened_at` is entry time and `closed_at` is exit time.

The endpoint also derives NY session dates for trades, candidates, and outcomes using Postgres `AT TIME ZONE 'America/New_York'`, reports `session_date_ny_storage: derived`, includes the derivation method, grouping counts, latest session date, and weekend/after-close derivation support.

Caveat: `latest_session_date` is taken from the first trade grouping key, so when there are no trades it can be null even if candidates or outcomes exist.

## 6. Regression findings

**Pass.** The latest G1B-H8 patch touches only `backend/api/audit.py`, `backend/tests/test_phase_g1b_h8.py`, and `frontend/dashboard/app/page.tsx`. I did not find application-code changes to normal scoring thresholds, Engine entry/exit logic, TP/SL/max-hold logic, historical data deletion, or broker/live execution paths.

The test file includes explicit regression coverage for the H3 weekend session gate and H5 invalid out-of-session exclusion from adjusted wallet performance metrics.

## 7. Safety findings

**Pass.** The patch remains fake-money / paper simulation only.

The reviewed endpoint includes a research-only disclaimer stating fake-money paper simulation, no broker data, and no live orders. The G1B-H8 safety tests scan the deep-status implementation for broker/live/real-order and paid-provider client tokens.

I did not find new code in the latest patch implementing broker integration, live trading, real orders, real-money execution, Alpaca, IBKR, Robinhood, `place_order`, `submit_order`, `execute_order`, or `send_order`.

For AI safety, the new endpoint does not add OpenAI, DeepSeek, Groq, Mistral, Gemini, or Ollama calls. Existing LLM modules remain outside the G1B-H8 patch scope, and G1B-H8 only reports persisted AI shadow status/counts.

## 8. Evidence

- Latest reviewed commit: `6c53030 Complete DB audit readiness for engine analysis`.
- Changed files in the latest patch: `backend/api/audit.py`, `backend/tests/test_phase_g1b_h8.py`, and `frontend/dashboard/app/page.tsx`.
- The dashboard source documents removal of the dead aggregate `WalletDailyAnalytics` component and routes per-engine daily reports through `EngineDailyReportsSection`.
- The three account cards are explicitly rendered for `engine`, `deterministic_shadow`, and `ai_shadow`.
- The three daily reports are explicitly rendered for `engine`, `deterministic_shadow`, and `ai_shadow`.
- The three decision analytics cards are explicitly rendered for `engine`, `deterministic_shadow`, and `ai_shadow`.
- Deep-status now builds extras JSON family probes for the requested field families, including selected path and score components.
- Deep-status now reports candidate tick timestamp persistence status as not persisted on candidate rows and reports the join to `paper_ticks.started_at` through `tick_id`.
- Deep-status now samples persisted deterministic/AI shadow decision/status fields and computes evidence-based separability.
- Deep-status now reports trade timestamp min/max/missing/future checks and NY-session groupings.
- Deep-status now returns top-level `analysis_ready`, `blocking_gaps`, and `warnings`.

## 9. Tests reviewed

The new `backend/tests/test_phase_g1b_h8.py` covers:

- removal of `function WalletDailyAnalytics` and the `All Wallets — Daily Analytics` aggregate label;
- absence of the old aggregate total-PnL reducer;
- tick timestamp persistence status and candidate-to-tick join evidence;
- separation of `tick_id` coverage from tick timestamp status;
- candidate grouping by catalyst type, entry mode, decision reason, action, and rejection reason;
- extras JSON field-family coverage keys;
- deterministic and AI shadow decision persistence count fields;
- evidence-based separability booleans;
- trade timestamp mapping and NY-session grouping fields;
- outcome completeness fields;
- top-level analysis readiness fields;
- three dashboard section markers;
- H3 weekend session gate;
- H5 invalid out-of-session exclusion;
- no broker/live/order tokens in `persistence_deep_status`;
- no paid AI provider client calls in `persistence_deep_status`.

Test caveat: these are mostly shape/source tests. They do not seed a Postgres database to prove exact aggregate values for full-table coverage, each required horizon missing entirely, or direct `resolved_at IS NULL` counting.

## 10. Runtime evidence reviewed

No Claude runtime evidence was present in the repo/context I reviewed. I did not review deployed backend health output, deployed `/api/audit/persistence/deep-status` JSON, deployed dashboard screenshots, or live VM confirmation of three engine account/daily-report/analytics panels.

Local unit evidence reviewed:

```text
PYTHONPATH=backend pytest -q backend/tests/test_phase_g1b_h8.py
24 passed, 1 warning in 0.20s
```

## 11. Freeze-readiness judgment

**Freeze readiness: PASS WITH CAVEATS.**

G1B-H8 is ready to proceed as an audit-readiness follow-up because it removes the lingering aggregate dashboard component and substantially upgrades deep-status to produce honest, evidence-based persistence/readiness signals.

The remaining caveats are not application safety issues. They are audit precision limits: sampled extras/shadow evidence, derived candidate tick timestamp rather than a candidate `tick_ts` column, status-derived missing-resolved counts, and outcome missing-horizon counts that do not fully prove absent rows per candidate/horizon.

## 12. Required follow-up patches, if any

No blocking follow-up patch is required for G1B-H8.

Recommended non-blocking follow-ups:

1. Add explicit `coverage_scope: "sampled"` and `not_collected` status fields to each extras JSON field-family coverage object.
2. Add a direct `resolved_at IS NULL` count for outcomes instead of relying only on status-derived missing-resolved counts.
3. Add a true “candidates missing each required horizon row entirely” query in addition to the current unresolved/error/missing-data rows by horizon.
4. Consider deriving `latest_session_date` from the maximum of trade/candidate/outcome session dates, not only the first trade grouping key.
5. Add DB-seeded tests for exact deep-status aggregate values so future patches cannot satisfy only response-shape assertions.
