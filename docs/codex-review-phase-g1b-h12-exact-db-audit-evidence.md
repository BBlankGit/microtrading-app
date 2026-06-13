# Codex Review — Phase G1B-H12 Exact DB Audit Evidence

**Verdict: YELLOW / NEEDS FOLLOW-UP**

## 1. Executive summary

G1B-H12 makes meaningful progress on the final G1B-H11 caveats by adding a test-only scoped deep-status endpoint, a real-DB fixture test that inserts controlled rows, and regression/safety tests around wallet status, H3/H5 boundaries, and forbidden broker/paid-AI tokens.

However, I am not marking the patch PASS because several review requirements are only partially satisfied:

1. **The committed runtime evidence does not prove the deployed VM was running the H12 commit.** The evidence file's `git rev-parse HEAD` output is the parent H11 commit `772d7d8`, while the reviewed H12 patch is commit `3e6f31f` in this workspace.
2. **The raw evidence sidecar omits the exact DB pytest command/output and full G1B regression output.** Those appear summarized in the markdown file, but the raw sidecar only contains commit/status/wallet/dashboard excerpts.
3. **Dashboard evidence remains SSR/source-marker evidence, not browser/visual proof of hydrated dashboard state.** It does not show three hydrated account cards or three visible hydrated daily/analytics panels in a screenshot/DOM artifact.
4. **The exact DB test is valuable but does not assert every requested field exactly.** Notable gaps include exact `by_decision_reason`, exact timestamp min/max values, exact latest session source/date, `ai_shadow` WOULD_* counts, several extras family key lists, and direct production/default disabling beyond the default 403 check.

Freeze readiness should therefore wait for one follow-up evidence/test patch, not an application-logic rewrite.

## 2. Exact isolated DB test findings

### What passes

- G1B-H12 adds a clearly named exact DB test, `test_deep_status_exact_values_with_isolated_real_db`, which seeds rows through `asyncpg.connect(DATABASE_URL)`, calls the FastAPI endpoint, and asserts exact counts rather than lower bounds.
- The fixture creates a unique `h12_<uuid>` tick-id prefix, inserts controlled `paper_ticks`, `paper_candidates`, `paper_candidate_outcomes`, and `paper_trades_journal` rows, and cleans those rows up in teardown.
- The test asserts exact controlled values for candidate totals, extras coverage percent, action/catalyst/entry-mode buckets, tick join coverage, deterministic shadow counts, AI disabled/error/not_selected counts, outcomes status/resolved-at counts, horizon row coverage, trade event/wallet/timestamp anomaly counts, and readiness flags.
- This is **not** another mock-pool test when `DATABASE_URL` is available; it inserts real PostgreSQL rows and exercises the HTTP endpoint.

### Gaps

- The fixture uses `DATABASE_URL`, not a dedicated `TEST_DATABASE_URL`. This is acceptable only because the unique prefix plus teardown provides isolation, but it is weaker than a dedicated test DB and could leave residue if setup fails after partial insertion.
- The real-DB test skips when `DATABASE_URL` is unavailable. That skip behavior is clear, but local execution in this review skipped the DB-backed exact test because no DB URL was configured.
- The test does **not** assert all requested exact fields. Missing or partial assertions include:
  - exact `candidates.by_decision_reason` buckets;
  - exact `paper_ticks_started_at_min` and `paper_ticks_started_at_max` values;
  - exact `keys_found` values for extras families;
  - exact `ai_shadow.would_enter_count`, `watch_count`, and `would_reject_count` values;
  - exact `resolved_at_min` and `resolved_at_max` timestamps, beyond non-null/alias equality;
  - exact latest trade/candidate/outcome/latest session dates and exact `latest_session_date_source`;
  - exact opened/closed/created timestamp min/max values;
  - explicit `invalid_out_of_session_entry_flatten` bucket name in `by_exit_reason`;
  - exact warnings list, although `blocking_gaps == []` is asserted.

## 3. Test-only filter / test DB isolation safety findings

G1B-H12 implements the isolation through a test-only scoped endpoint, `/api/audit/persistence/deep-status-scoped`, rather than a temporary schema or dedicated `TEST_DATABASE_URL`.

Safety findings:

- The scoped endpoint is gated by `settings.AUDIT_TEST_FILTERS_ENABLED`, which defaults to `False` in normal settings.
- When the flag is false, the endpoint returns HTTP 403 with a disabled detail and reason `AUDIT_TEST_FILTERS_ENABLED=false`.
- The tests include `test_scoped_endpoint_disabled_in_production`, proving the default production-like client cannot use the scoped filter.
- The normal `/api/audit/persistence/deep-status` endpoint remains separate from the scoped endpoint.

Caveats:

- The guard is not tied to `APP_ENV=test`; any deployment that accidentally sets `AUDIT_TEST_FILTERS_ENABLED=true` would expose the scoped endpoint. The default is safe, but the safer pattern would require both test environment and the explicit flag.
- The filter is implemented as a public route name under `/api/audit`, not an internal-only test helper. This is acceptable with the default-false gate, but it deserves operational care.

## 4. Runtime evidence findings

G1B-H12 adds `docs/runtime-evidence-phase-g1b-h12.md` and `docs/runtime-evidence-phase-g1b-h12-raw.txt`.

Positive evidence:

- The markdown includes backend health output, scoped-endpoint default 403 output, wallet endpoint excerpts, a summarized exact DB pytest transcript, a summarized full G1B regression transcript, and SSR marker output.
- The wallet excerpt shows `DETERMINISTIC_SHADOW` active and `AI_SHADOW` inactive with `LLM_SHADOW_ENABLED=false`.
- The deep-status/exact-value table in the markdown records the requested families of exact endpoint values for the isolated test.

Caveats:

- The committed raw evidence says `git rev-parse HEAD` returned `772d7d8`, which is the prior H11 commit, not the reviewed H12 commit `3e6f31f`.
- The raw sidecar does not include the actual exact DB test command/output or the full G1B regression test command/output; those are only present as markdown summaries.
- The deep-status excerpt in the evidence is mostly a table of asserted test values, not raw JSON output from the endpoint.
- No secrets or tokens were visible in the reviewed evidence files.

## 5. Dashboard visual evidence findings

G1B-H12 does not add a screenshot artifact or Playwright browser screenshot. It adds SSR/source-marker evidence instead:

- SSR output contains `Engine Daily Reports`, `Engine Decision Analytics`, `Trading Activity`, and `Advanced diagnostics` markers.
- The evidence states dynamic account/performance sections render only after hydration and are source-verified.
- Tests/source checks confirm the key component names remain present and aggregate strings such as `All wallets cash` / `All accounts cash` are absent.

Caveat: this does **not** fully satisfy the requested browser/visual proof because it does not show hydrated three account cards, `DETERMINISTIC_SHADOW` active/no-trade state, `AI_SHADOW` inactive due to `LLM_SHADOW_ENABLED=false`, or three visible daily/analytics panels in a screenshot/DOM artifact.

## 6. Dashboard regression findings

Source/tests indicate the dashboard structure was not changed by H12 and prior structure remains:

- Three engine-section component markers are still expected by tests.
- `Trading Activity` remains present.
- Aggregate all-wallet cash/equity labels are checked absent.
- Wallet endpoint tests continue to verify deterministic shadow active by default and AI shadow inactive by default.

Caveat: because no hydrated browser artifact is committed, this is source/API confidence rather than a visual proof of rendered dashboard state.

## 7. H3/H5/H7/H8/H10/H11 regression findings

Reviewed regression coverage indicates:

- H3 weekend/closed-market gate still blocks entries.
- H5 invalid out-of-session trades remain excluded from adjusted normal performance metrics.
- H7/H8 dashboard source markers and aggregate-removal assertions remain covered.
- H10 wallet status/config fields and H11 `last_decision_at_source` exposure remain covered by wallet endpoint tests.
- The H12 diff does not touch scoring thresholds, normal entry/exit logic, TP/SL, max-hold logic, or simulator strategy logic.

Caveat: H10 resolved-at aliases and H11 persisted provenance are indirectly covered; the H12 focused tests do not exhaustively rerun every historical assertion with exact fixtures.

## 8. Safety findings

I did not find new broker/live-trading/real-order implementation in the H12 patch. The changed production code is limited to an audit endpoint and a default-false config flag. The added tests include forbidden-token checks against selected backend files.

Caveat: the H12 forbidden-token test scans only selected files (`api/audit.py`, `api/paper.py`, and `paper/shadow_wallets.py`), not the entire repository diff. My review also inspected the latest diff and did not find new order-execution logic.

## 9. AI safety findings

- `LLM_SHADOW_ENABLED` remains default `False`.
- The added scoped endpoint reads Postgres only and does not call any AI provider.
- The H12 tests check for common paid provider call tokens in selected files.
- Wallet tests/evidence keep `AI_SHADOW` inactive when LLM shadow is disabled.

Caveat: the token test does not scan all possible provider names requested by the review (DeepSeek/Groq/Mistral/Gemini/Ollama), but the reviewed H12 diff does not add provider-call code.

## 10. Evidence

Files reviewed:

- `backend/api/audit.py`
- `backend/core/config.py`
- `backend/tests/conftest.py`
- `backend/tests/test_phase_g1b_h12.py`
- `docs/runtime-evidence-phase-g1b-h12.md`
- `docs/runtime-evidence-phase-g1b-h12-raw.txt`

Commands run for this review:

```bash
git status --short
git log --oneline -5
git diff --stat HEAD~1..HEAD
git diff --name-only HEAD~1..HEAD
rg -n "G1B-H12|exact|TEST_DATABASE_URL|AUDIT_TEST|deep-status|runtime-evidence-phase-g1b-h12|screenshot|playwright|broker|Alpaca|place_order|submit_order|execute_order|send_order|LLM_SHADOW_ENABLED|OpenAI|DeepSeek|Groq|Mistral|Gemini|Ollama" . --glob '!node_modules' --glob '!venv' --glob '!*.png'
sed -n '1,220p' backend/core/config.py
rg -n "deep-status-scoped|AUDIT_TEST_FILTERS|scope_tick_id_prefix" backend -S
sed -n '1,520p' docs/runtime-evidence-phase-g1b-h12.md
cat docs/runtime-evidence-phase-g1b-h12-raw.txt
git diff HEAD~1..HEAD -- backend/api/audit.py backend/tests/test_phase_g1b_h12.py docs/runtime-evidence-phase-g1b-h12.md
pytest backend/tests/test_phase_g1b_h12.py -q
```

Local test result:

```text
12 passed, 1 skipped, 1 warning in 0.27s
```

The skip was the real DB exact test because this review environment did not have a configured `DATABASE_URL`.

## 11. Tests reviewed

H12 adds/reviews the following relevant tests:

- `test_scoped_endpoint_disabled_in_production`
- `test_scoped_endpoint_rejects_short_prefix`
- `test_deep_status_exact_values_with_isolated_real_db`
- `test_deterministic_shadow_active_by_default`
- `test_ai_shadow_inactive_by_default`
- `test_last_decision_at_source_remains_exposed`
- `test_h3_session_gate_still_blocks_weekends`
- `test_h5_oos_exclusion_still_works`
- `test_three_engine_dashboard_structure_unchanged`
- `test_no_aggregate_account_total_reintroduced`
- `test_no_broker_tokens_anywhere`
- `test_no_paid_ai_provider_calls`
- `test_dashboard_ssr_contains_three_engine_panels`

The fast tests still pass locally. The exact DB test is present and clearly named, but it skips without DB configuration.

## 12. Freeze-readiness judgment

**Not freeze-ready as a clean PASS yet.** The implementation is directionally correct and likely sufficient after one evidence/test tightening patch, but the committed evidence does not prove the H12 commit was deployed/run on the VM, and the dashboard proof remains non-visual/hydration-incomplete.

## 13. Required follow-up patches

1. Re-run and commit raw runtime evidence after deploying the actual H12 commit, including:
   - `git rev-parse HEAD` showing the H12 commit;
   - `git log --oneline -1` for the H12 commit;
   - raw exact DB pytest command/output;
   - raw full G1B regression command/output;
   - raw deep-status scoped JSON excerpt or captured output with readiness, timestamps, resolved-at, horizon, extras, deterministic shadow, and AI shadow sections.
2. Add Playwright/DOM or screenshot evidence proving the hydrated dashboard shows:
   - three account cards;
   - deterministic shadow active/no-trade or active-with-data;
   - AI shadow inactive due `LLM_SHADOW_ENABLED=false`;
   - daily reports, decision analytics, and wallet-tagged trading activity;
   - advanced diagnostics collapsed or outside the normal report;
   - no aggregate all-wallet cash/equity account.
3. Expand the exact DB test to assert the remaining requested exact values, especially `by_decision_reason`, exact timestamp min/max values, exact latest-session source/date, exact AI WOULD_* counts, and `keys_found` for extras families.
4. Consider strengthening the scoped endpoint gate so it requires both an explicit flag and a test environment (`APP_ENV=test`) before accepting `scope_tick_id_prefix`.
