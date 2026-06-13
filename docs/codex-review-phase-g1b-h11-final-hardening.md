# Codex Review — Phase G1B-H11 Final Hardening

**Verdict: PASS WITH CAVEATS**

## 1. Executive summary

G1B-H11 materially improves the G1B-H10 caveats. The patch adds a real DB-backed integration test, latest-session fallback tests, a negative readiness fixture, AI shadow `error`/`not_selected` coverage, exact timestamp integrity assertions, and durable deterministic-shadow `last_decision_at` provenance. The runtime implementation keeps the app fake-money/paper-only and does not introduce broker, live-order, or paid-AI behavior.

The main caveat is that the new real DB-backed integration test is real in the sense that it inserts into the actual Postgres tables and calls the real endpoint, but it does **not** assert exact endpoint values from an isolated inserted-row fixture. Because `/api/audit/persistence/deep-status` reports aggregate totals over the whole database, the test asserts lower bounds (`>= 1`) and collected statuses rather than exact values. This closes the “not only mock-pool” gap, but it does not fully satisfy the requested “asserts exact returned values” standard for the real inserted-row fixture.

## 2. Real DB fixture test findings

**Finding: Mostly pass, with exactness caveat.**

The test fixture opens a dedicated `asyncpg` connection from `DATABASE_URL`, generates a unique `tick_id`, and inserts rows into the real `paper_ticks`, `paper_candidates`, `paper_candidate_outcomes`, and `paper_trades_journal` tables. It cleans up all inserted rows by `tick_id` in teardown. The endpoint test then calls `GET /api/audit/persistence/deep-status`. This is a true inserted-row DB fixture, not merely another mock-pool test.

Caveat: assertions are aggregate/lower-bound assertions, not exact inserted-row endpoint assertions. The test asserts `body["candidates"]["total"] >= 1`, `paper_ticks_total >= 1`, per-family `rows_present >= 1`, and AI status collected. It does not isolate the endpoint to a transaction/test schema or assert exact totals/min-max values for only the inserted rows.

## 3. Latest-session fallback findings

**Finding: Pass.**

The endpoint chooses latest session date from trades, candidates, and outcomes, then records the matching source. The G1B-H11 tests directly cover no-trades fallback to candidates and no-trades/no-candidates fallback to outcomes.

## 4. Negative readiness findings

**Finding: Pass.**

The negative fixture makes candidates exist while removing extras/shadow evidence and candidate-outcome joins, with trades missing attribution. It asserts false readiness for engine, deterministic shadow, AI shadow, overall freeze audit, and legacy `analysis_ready`, plus expected blocking gaps and warnings.

## 5. AI shadow error/not_selected findings

**Finding: Pass.**

The seeded AI fixture covers disabled, error, not-selected, would-enter, and watch counts, and asserts `status == "collected"` plus `no_paid_ai_calls is True`. No paid AI call is needed to produce the test data.

## 6. Trade timestamp integrity findings

**Finding: Pass.**

The endpoint now returns exact timestamp integrity fields for missing opened/closed timestamps, min/max created/opened/closed timestamps, future opened/closed anomalies, and a column-mapping note documenting that `opened_at` is the entry timestamp and `closed_at` is the exit timestamp. G1B-H11 tests assert exact counts for the controlled mock-pool fixture.

## 7. Durable last_decision_at findings

**Finding: Pass.**

The shadow-wallet layer now keeps a TTL-cached persisted `last_decision_at` derived from `paper_candidates.extras_json` markers for deterministic and AI shadow decisions. Snapshot resolution prioritizes runtime, then persisted candidate extras, then a clearly labeled `last_entry_fallback`, then none. The wallet, performance, and analytics API paths expose `last_decision_at_runtime`, `last_decision_at_persisted`, and `last_decision_at_source`.

Caveat: the persisted derivation uses `MAX(created_at)` from `paper_candidates`, not a more specific tick timestamp, but this matches the requested acceptable candidate timestamp derivation.

## 8. Runtime evidence findings

**Finding: Pass with evidence-document caveats.**

`docs/runtime-evidence-phase-g1b-h11.md` exists and states deployed/backend health, unchanged frontend, test results, real DB fixture behavior, deep-status excerpts, wallet provenance excerpts, and dashboard confirmations. Caveats: the evidence document reports VM results, but it does not include raw terminal logs, container IDs, screenshots, or a live browser screenshot of the dashboard. It also reports AI `error: 0` and `not_selected: 0` in the runtime DB excerpt, while the positive `error`/`not_selected` behavior is demonstrated by tests rather than captured from live runtime data.

## 9. Dashboard regression findings

**Finding: Pass based on code/test review.**

G1B-H11 did not touch frontend code. The regression tests assert the dashboard still contains the three engine account/report/analytics section markers and that the dead aggregate daily analytics component and aggregate account-cash labels remain absent.

## 10. H3/H5/H7/H8/H10 regression findings

**Finding: Pass based on targeted tests and code review.**

G1B-H11 includes tests for the H3 weekend/closed-session gate, H5 invalid out-of-session exclusion from performance metrics, H7 three-engine dashboard structure, H8 aggregate removal, and H10 status/config/last-decision propagation. The patch does not touch normal engine entry/exit, scoring thresholds, TP/SL, or max-hold code.

## 11. Safety findings

**Finding: Pass.**

I did not find new broker/live/order implementation in the G1B-H11 patch. The changed runtime code is limited to audit/wallet provenance fields and DB reads of persisted candidate extras. The new tests include safety scans over changed backend modules for broker/order and paid-AI provider call tokens.

AI remains disabled by default through `LLM_SHADOW_ENABLED: bool = False`, and AI shadow remains inactive when LLM is disabled. No OpenAI, DeepSeek, Groq, Mistral, Gemini, or Ollama call path was added by this patch.

## 12. Evidence

- Real DB fixture inserts actual rows into `paper_ticks`, `paper_candidates`, `paper_candidate_outcomes`, and `paper_trades_journal`, then deletes by unique `tick_id` in teardown.
- The real DB endpoint test calls `/api/audit/persistence/deep-status` but asserts lower bounds/collected status instead of exact isolated values.
- Candidate/outcome latest-session fallback tests assert `latest_session_date_source == "candidates"` and `"outcomes"`.
- Negative readiness tests assert false readiness flags plus blocking gaps/warnings.
- AI shadow tests assert disabled/error/not-selected counts.
- Timestamp tests assert exact missing/future counts and mapping note.
- Runtime evidence documents VM test results and endpoint excerpts.

## 13. Tests reviewed

I ran:

```bash
pytest backend/tests/test_phase_g1b_h11.py -q
```

Result in this review environment: `18 passed, 1 skipped, 1 warning in 0.35s`. The skipped test was the real DB integration path because this environment did not have the configured database available; the VM runtime evidence states that the DB-backed test ran there.

## 14. Freeze-readiness judgment

**PASS WITH CAVEATS for G1B-H11.**

The phase is safe for continued fake-money/paper monitoring and addresses the substantive G1B-H10 hardening gaps. The only remaining material caveat is test strength: the real DB-backed fixture is real but still aggregate-based, so it does not prove exact endpoint values against an isolated inserted-row dataset.

## 15. Required follow-up patches, if any

No application safety patch is required before fake-money monitoring continues.

Recommended follow-up before declaring the audit test suite fully hardened:

1. Add an isolated real-DB deep-status test mode, transaction, temporary schema, or test-only filter that allows exact endpoint assertions for the inserted rows.
2. Add raw VM command output or CI artifact links to future runtime evidence docs, especially for DB-backed integration tests.
3. If dashboard visual evidence is required for a phase, capture and attach a screenshot rather than relying solely on static source-marker tests.
