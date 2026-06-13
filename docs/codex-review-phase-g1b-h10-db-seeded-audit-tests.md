# Codex Review — Phase G1B-H10 DB-Seeded Audit Tests

**Verdict: PASS WITH CAVEATS**

## 1. Executive summary

G1B-H10 materially closes the G1B-H9 follow-up list. The patch adds a dedicated H10 regression suite, extends the wallet performance and analytics APIs with the common status/config fields, adds `resolved_at_min` / `resolved_at_max` aliases while preserving legacy names, records deterministic-shadow `last_decision_at` separately from entries, and commits a runtime-evidence artifact.

The fake-money safety boundaries remain intact in the reviewed diff: I found no new broker/live/real-order implementation, no paid AI provider call, no default LLM enablement, and no scoring/entry/exit/TP/SL/max-hold logic changes in the latest patch.

The review is **PASS WITH CAVEATS** rather than a clean PASS because the new exact-value tests use a substring-routed mock async pool instead of inserting real rows into a test database, and several requested negative/fallback scenarios are still only partially covered. The tests do exercise the actual deep-status endpoint SQL call sites with controlled exact return values, so they are much stronger than response-shape/source-string tests, but they are not full DB fixture tests in the strictest sense.

## 2. DB-seeded exact-value test findings

### What passed

The new `backend/tests/test_phase_g1b_h10.py` file adds a controlled `_MockPool` / `_MockConn` fixture and routes deep-status SQL substrings to deterministic values before calling `/api/audit/persistence/deep-status`. The fixture models candidates, ticks, candidate outcomes, trades, extras JSON coverage families, deterministic shadow decisions, AI shadow statuses, NY session grouping, and invalid out-of-session trades.

Exact assertions now cover:

- candidate totals, extras coverage percent, missing tick IDs, missing `created_at`, actions, catalyst types, and entry modes;
- paper tick total, missing `started_at`, candidate-to-tick join count, and join coverage percent;
- extras JSON family `sample_size`, `rows_present`, `coverage_percent`, `status`, `coverage_scope`, and `keys_found` checks for marketdata/reddit/earnings/insider/deterministic shadow/AI shadow;
- deterministic shadow `WOULD_ENTER`, `WATCH`, `WOULD_REJECT`, missing decision, separability, and collected status counts;
- AI shadow disabled/error/not-selected/decision counts, status rows, collected status, and `no_paid_ai_calls`;
- direct `resolved_at` null/present counts and alias parity;
- horizon-row coverage with exact candidates-with-row / candidates-missing-row / resolved / pending counts;
- latest session date fields across trade/candidate/outcome sources;
- trade totals, wallet counts, missing wallet/strategy IDs, invalid OOS count, future timestamp anomaly counts, and column-mapping note;
- readiness flags and blocking-gap behavior for the all-present fixture.

### Caveats

1. **The tests are mock-pool seeded, not true inserted-row DB fixtures.** They monkeypatch `paper.db.get_pool()` to return controlled async fetch values. This still exercises the endpoint code and exact aggregation contracts, but it does not validate database schema compatibility, real inserts, JSONB operators, timezone casts, or actual joins against persisted rows.
2. **AI shadow error and not-selected are asserted as exact zero values, not as positive seeded cases.** The requested coverage mentioned disabled/error/not_selected fields; disabled is seeded positively, while error and not-selected remain zero-count paths.
3. **Latest-session fallback without trades is not directly tested.** The main test validates all latest-session fields when trades, candidates, and outcomes exist, but it does not seed a trades-empty fixture and assert fallback to candidates/outcomes.
4. **Readiness false/warning behavior is only partially covered.** The all-present fixture asserts readiness true and no blocking gaps, while a warning for missing outcome rows is asserted. A controlled critical-dimension-absent fixture that forces readiness false/blocking gaps is still missing.
5. **Trade timestamp integrity is not fully exact.** The test checks invalid OOS, future opened/closed anomalies, and column mapping, but it does not assert exact missing entry/opened and missing exit/closed counts as explicitly as requested.

These caveats are follow-up quality gaps, not evidence that the H10 patch regressed runtime behavior.

## 3. Wallet API status/config findings

The preferred Option 1 is implemented: `/api/paper/wallets/performance` and `/api/paper/wallets/analytics` now expose status/config fields that align with the canonical `/api/paper/wallets` data model.

For `/api/paper/wallets/performance`, each wallet response includes `wallet_id`, `strategy_id`, `status`, `inactive_reason`, `enabled`, `active`, `processing_enabled`, `enabled_by_config`, `depends_on_llm`, `last_entry_at`, `last_exit_at`, `last_decision_at`, and `no_paid_ai_calls` where populated. Engine status/config symmetry is explicitly added with always-active config metadata.

For `/api/paper/wallets/analytics`, the endpoint adds engine and shadow status blocks containing the same status/config family, including `active`, `enabled`, `processing_enabled`, `enabled_by_config`, `depends_on_llm`, timestamps, and `no_paid_ai_calls` where applicable.

The H10 tests assert the required fields exist in both `/performance` and `/analytics`, and the runtime evidence includes JSON excerpts for all three wallet endpoints.

## 4. Deterministic shadow `last_decision_at` findings

G1B-H10 adds an in-memory per-shadow-wallet `_last_decision_at` map and stamps it from `_stamp_decision()` whenever deterministic shadow candidates include `enhanced_shadow_decision` or `enhanced_shadow_score`. `process_tick()` calls the deterministic stamp before entries/exits, so WATCH, WOULD_REJECT, and scored/no-entry evaluations can update the timestamp independently of actual entries.

The wallet snapshot now returns `_last_decision_at[wallet_id]` before falling back to `last_entry_at`. The fallback is documented in code and avoids blank values immediately after restart, but it means a restarted process with historical entries and no in-memory decision tick can still report `last_entry_at` as a best-effort `last_decision_at`. That is acceptable as documented fallback, but persistent true last-decision history remains out of scope.

Tests cover WATCH, WOULD_REJECT, score-without-entry, unrelated-candidate non-touch, and `/api/paper/wallets` surfacing of the true timestamp.

## 5. `resolved_at` alias findings

Deep status now returns the requested `resolved_at_min` and `resolved_at_max` aliases while preserving `min_resolved_at` and `max_resolved_at`. The H10 tests assert the alias keys exist and match the legacy values.

## 6. Runtime evidence findings

The patch adds `docs/runtime-evidence-phase-g1b-h10.md`. It includes:

- deployed branch/parent/date context;
- backend and frontend container health statements;
- backend H10 suite, all-G1B suite, and frontend build results;
- `/api/paper/wallets` excerpt showing deterministic shadow active and AI shadow inactive due `LLM_SHADOW_ENABLED=false`;
- `/api/paper/wallets/performance` and `/api/paper/wallets/analytics` excerpts showing status/config fields;
- `/api/audit/persistence/deep-status` excerpts for readiness flags, blocking gaps, warnings, resolved-at counts/aliases, missing horizon rows, latest-session derivation, extras coverage, deterministic shadow persistence, and AI shadow persistence;
- dashboard confirmation that the three-engine/account dashboard still renders, deterministic shadow is active/no-trades, AI shadow is inactive due LLM disabled, and aggregate all-wallet cash/equity is absent.

One minor mismatch: the committed evidence says `pytest tests/test_phase_g1b_h10.py` produced `24 passed, 2 skipped`, while my local run in this environment produced `26 passed`. This is not a functional blocker; it likely reflects frontend-mounted skip differences or environment differences, but future evidence should avoid stale test counts.

## 7. Dashboard regression findings

No frontend application file was modified by the H10 patch. The H10 tests still scan `frontend/dashboard/app/page.tsx` for the three-engine dashboard sections and assert that aggregate wallet cash strings / dead aggregate component markers were not reintroduced.

The committed runtime evidence reports dashboard visual confirmation for three account cards, deterministic shadow active/no-trades state, AI shadow inactive due `LLM_SHADOW_ENABLED=false`, Trading Activity, Engine Daily Reports, Engine Decision Analytics, and no aggregate all-wallet cash/equity account.

## 8. H3/H5/H7/H8 regression findings

The H10 patch preserves the prior phase boundaries:

- H3 regular-session gate: test coverage confirms Saturday entries remain blocked with `market_closed_weekend`.
- H5 invalid OOS exclusion: performance endpoint test confirms `invalid_out_of_session_entry_flatten` trades are excluded from adjusted realized PnL and remain separable.
- H7 three-engine dashboard structure: source markers for Engine Accounts, Engine Daily Reports, and Engine Decision Analytics remain present.
- H8 aggregate removal: the dead aggregate wallet analytics component and aggregate cash strings were not reintroduced.
- H8 deep-status readiness: the endpoint still returns readiness flags, blocking gaps, warnings, and analysis-ready structure, with H10 adding exact mock-pool tests over those fields.

## 9. Safety findings

The latest patch is confined to audit aliases, wallet API status/config fields, shadow-wallet decision timestamp metadata, tests, and documentation. I found no new broker integration, live trading path, real-order implementation, real-money execution path, Alpaca/IBKR/Robinhood integration, or order-placement function in the latest diff.

The latest patch also does not add OpenAI, DeepSeek, Groq, Mistral, Gemini, Ollama, or other paid AI call paths. `LLM_SHADOW_ENABLED` remains default false, and AI shadow remains inactive when LLM shadow is disabled.

I did not find scoring-threshold, normal Engine entry/exit, TP/SL, max-hold, or H3 entry-gate logic changes in the latest diff.

## 10. Evidence

Reviewed commit: `3e414a3 Add DB-seeded audit tests and shadow status evidence`.

Key evidence from the patch:

- `backend/tests/test_phase_g1b_h10.py` adds the controlled mock-pool fixture and exact H10 assertions.
- `backend/api/paper.py` adds common status/config fields to `/api/paper/wallets/performance` and `/api/paper/wallets/analytics`.
- `backend/paper/shadow_wallets.py` adds `_last_decision_at`, `_stamp_decision()`, tests accessors, and snapshot output using true decision timestamps before `last_entry_at` fallback.
- `backend/api/audit.py` adds `resolved_at_min` and `resolved_at_max` aliases.
- `docs/runtime-evidence-phase-g1b-h10.md` provides committed runtime evidence.

Review commands run:

```bash
git status --short
git log --oneline -5
git diff --stat HEAD~1..HEAD
git diff --name-only HEAD~1..HEAD
sed -n '1,260p' backend/tests/test_phase_g1b_h10.py
sed -n '260,680p' backend/tests/test_phase_g1b_h10.py
git diff HEAD~1..HEAD -- backend/api/paper.py backend/api/audit.py backend/paper/shadow_wallets.py
sed -n '1,420p' docs/runtime-evidence-phase-g1b-h10.md
pytest -q backend/tests/test_phase_g1b_h10.py
git diff HEAD~1..HEAD -U0 | rg -n "broker|live trading|live_trading|real_order|real-money|Alpaca|IBKR|Robinhood|place_order|submit_order|execute_order|send_order|OpenAI\(|DeepSeek|Groq|Mistral|Gemini|Ollama|openai\.Client|anthropic\.Client|LLM_SHADOW_ENABLED|threshold|take_profit|stop_loss|max_hold|entries_blocked|regular_session" -i || true
rg -n "LLM_SHADOW_ENABLED.*False|LLM_SHADOW_ENABLED.*false|PAPER_DETERMINISTIC_SHADOW_ENABLED" backend/core backend/paper backend/api .env* -S || true
```

## 11. Tests reviewed

I reviewed and ran the dedicated H10 suite:

- `pytest -q backend/tests/test_phase_g1b_h10.py` → **26 passed, 1 warning** in this environment.

Coverage reviewed in the suite:

- exact candidate/tick derivation;
- exact extras JSON family coverage;
- exact deterministic shadow persistence counts;
- exact AI shadow disabled/error/not-selected/decision counts;
- exact direct `resolved_at` null/present counts and aliases;
- exact missing horizon-row counts;
- latest session date derivation;
- trade aggregate/integrity counts;
- invalid OOS separability;
- readiness flags and warnings;
- wallet status/config field symmetry across APIs;
- true deterministic `last_decision_at` for WATCH/WOULD_REJECT/no-entry-like score touches;
- dashboard structure and no aggregate reintroduction;
- H3/H5 boundary regressions;
- no broker/live/order tokens and no paid AI provider calls in changed backend files.

## 12. Freeze-readiness judgment

**Freeze-readiness: acceptable with caveats.**

G1B-H10 satisfies the practical intent of the G1B-H9 follow-up: exact audit fields now have deterministic tests, wallet API status/config consistency is fixed, deterministic shadow decision timestamps are no longer merely entry timestamps during the active process, resolved-at aliases are present, and runtime evidence is committed.

The remaining caveats should be handled before treating the audit suite as a full database-integration proof, but they do not block fake-money monitoring continuation because the runtime evidence and endpoint-level tests support the intended behavior and the safety boundaries remain preserved.

## 13. Required follow-up patches, if any

No application-code follow-up is required for fake-money safety.

Recommended hardening follow-ups:

1. Add at least one true inserted-row database fixture test for `/api/audit/persistence/deep-status`, using a temporary test database/schema and real `paper_ticks`, `paper_candidates`, `paper_candidate_outcomes`, and trade-journal rows.
2. Add a trades-empty latest-session fallback fixture that proves `latest_session_date_source` becomes `candidates` or `outcomes` when no trades exist.
3. Add a negative readiness fixture where critical dimensions are absent and assert exact `engine_analysis_ready`, `deterministic_shadow_analysis_ready`, `ai_shadow_analysis_ready`, `overall_freeze_audit_ready`, `blocking_gaps`, and `warnings` false/warning behavior.
4. Add positive AI shadow `error` and `not_selected` seeded cases rather than only exact zero counts.
5. Add exact missing entry/opened and missing exit/closed timestamp count assertions for trade timestamp integrity.
6. If durable `last_decision_at` is desired across restarts, persist the shadow decision timestamp or derive it from persisted candidate extras instead of relying on in-memory state plus `last_entry_at` fallback.
