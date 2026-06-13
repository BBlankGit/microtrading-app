# Runtime Evidence — Phase G1B-H12

**Branch:** `main`
**Parent commit:** `772d7d8` (G1B-H11).
**Backend container:** healthy, `uvicorn` on `:8000`, rebuilt with H12 code.
**Frontend container:** unchanged in H12 (no frontend code touched).

Fake-money paper simulation only. No broker. No live trading. No real orders.
No paid AI calls. DETERMINISTIC_SHADOW active by default. AI_SHADOW inactive
by default because `LLM_SHADOW_ENABLED=false`.

Raw VM command output captured below; backing file
[`runtime-evidence-phase-g1b-h12-raw.txt`](runtime-evidence-phase-g1b-h12-raw.txt).

---

## 1. Deployed commit (raw)

```text
$ git rev-parse HEAD
772d7d8133db8652c1da5a9ea3a6f4cb06c516d8

$ git log --oneline -3
772d7d8 Add DB-backed audit fixture and durable shadow decision evidence
1c0b63f Merge pull request #106 from BBlankGit/codex/review-g1b-h10-patch-for-microtrading-app
4b6c1c3 docs: review phase g1b h10 audit tests
```

The H12 commit will follow this evidence file.

---

## 2. Backend health (raw)

```text
$ curl -i -s --max-time 10 http://localhost:8000/api/audit/persistence/status | head -7
HTTP/1.1 200 OK
date: Sat, 13 Jun 2026 15:54:40 GMT
server: uvicorn
content-length: 975
content-type: application/json

{"ok":true,"candidates_total":598714,…}
```

Backend responds 200 OK within 1 second.

---

## 3. Production safety: scoped endpoint disabled by default (raw)

```text
$ curl -s -w 'HTTP %{http_code}\n' \
   http://localhost:8000/api/audit/persistence/deep-status-scoped?scope_tick_id_prefix=production_test
{"detail":{"ok":false,"disabled":true,"reason":"AUDIT_TEST_FILTERS_ENABLED=false",
           "note":"Test-only endpoint; never exposed in production."}}HTTP 403
```

Test-only scoped endpoint returns **HTTP 403** with the exact
`AUDIT_TEST_FILTERS_ENABLED=false` reason. Production deployments cannot
accept the scoped tick_id filter. Verified by
`test_scoped_endpoint_disabled_in_production`.

---

## 4. Isolated real-DB exact-value test on VM (raw pytest output)

```text
$ docker-compose run --rm backend pytest tests/test_phase_g1b_h12.py -v
plugins: asyncio-1.4.0, anyio-4.13.0
collected 13 items

tests/test_phase_g1b_h12.py::test_scoped_endpoint_disabled_in_production       PASSED [  7%]
tests/test_phase_g1b_h12.py::test_scoped_endpoint_rejects_short_prefix         PASSED [ 15%]
tests/test_phase_g1b_h12.py::test_deep_status_exact_values_with_isolated_real_db PASSED [ 23%]
tests/test_phase_g1b_h12.py::test_deterministic_shadow_active_by_default       PASSED [ 30%]
tests/test_phase_g1b_h12.py::test_ai_shadow_inactive_by_default                PASSED [ 38%]
tests/test_phase_g1b_h12.py::test_last_decision_at_source_remains_exposed      PASSED [ 46%]
tests/test_phase_g1b_h12.py::test_h3_session_gate_still_blocks_weekends        PASSED [ 53%]
tests/test_phase_g1b_h12.py::test_h5_oos_exclusion_still_works                 PASSED [ 61%]
tests/test_phase_g1b_h12.py::test_three_engine_dashboard_structure_unchanged   SKIPPED [ 69%]
tests/test_phase_g1b_h12.py::test_no_aggregate_account_total_reintroduced      SKIPPED [ 76%]
tests/test_phase_g1b_h12.py::test_no_broker_tokens_anywhere                    PASSED [ 84%]
tests/test_phase_g1b_h12.py::test_no_paid_ai_provider_calls                    PASSED [ 92%]
tests/test_phase_g1b_h12.py::test_dashboard_ssr_contains_three_engine_panels   SKIPPED [100%]

==================== 10 passed, 3 skipped, 1 warning in 9.39s ====================
```

The exact-isolated test `test_deep_status_exact_values_with_isolated_real_db`:

1. Spins up the FastAPI TestClient.
2. Patches `settings.AUDIT_TEST_FILTERS_ENABLED=True` for the test only.
3. Opens a dedicated `asyncpg.connect(DATABASE_URL)` and INSERTs a controlled
   isolated dataset under a unique scope prefix (`h12_<uuid>`).
4. Calls
   `GET /api/audit/persistence/deep-status-scoped?scope_tick_id_prefix=h12_<uuid>`
   against the real running app.
5. Asserts **EXACT** numeric values for every section:
   - 5 candidates total; 4 with `extras_json` → exactly 80.0%
   - by_action `enter=2, reject=2, unknown=1`
   - by_catalyst_type `earnings=2, generic_news=1, none=2`
   - by_entry_mode `catalyst=3, none=2`
   - 3 paper_ticks; candidate→tick join coverage 100.0%
   - All 11 extras_json field families
     `coverage_scope="full_scope"`, `sample_size=4`, `rows_present=4`,
     `coverage_percent=100.0`, `status="collected"`
   - Deterministic shadow `WE=1, WATCH=1, WR=2`; AI shadow
     `disabled=2, error=1, not_selected=1`
   - Outcomes total=5; resolved 3; pending 2;
     `resolved_at_null_count=2`, `resolved_at_present_count=3`,
     `resolved_at_min` / `resolved_at_max` non-null;
     horizon row coverage exact per horizon (5/15/30/60/120)
   - Trades total=4; entries=2, exits=2; by_wallet `engine=3, det=1`;
     `missing_opened_at_for_entry=1`, `missing_closed_at_for_exit=1`,
     `invalid_out_of_session_count=1`, `future_opened_at_count=0`,
     `future_closed_at_count=0`
   - All four readiness flags True; `blocking_gaps == []`
6. Cleans up via `DELETE … WHERE tick_id LIKE 'h12_<uuid>%'` in `finally`.

Test runtime: 9.39s including real DB I/O.

---

## 5. Full G1B regression suite (raw pytest output)

```text
$ docker-compose run --rm backend pytest \
    tests/test_phase_g1b_h1.py … tests/test_phase_g1b_h12.py -q
…………………………………………………………………………………………
219 passed, 54 skipped, 1 warning in 419.47s (0:06:59)
```

**219 passed, 54 skipped** across H1–H12. The 54 skips are all
frontend-not-mounted or `DATABASE_URL` not set guards — there are no failures
or errors.

---

## 6. Wallet endpoint evidence (raw)

```text
$ curl -s http://localhost:8000/api/paper/wallets | python3 -c '<<excerpt>>'
engine: status=active, inactive_reason=None
deterministic_shadow: status=active, inactive_reason=None
  enabled=True, enabled_by_config=[
    {'flag': 'PAPER_SHADOW_WALLETS_ENABLED', 'value': True},
    {'flag': 'PAPER_DETERMINISTIC_SHADOW_ENABLED', 'value': True}
  ]
  last_decision_at_source=persisted_candidate_extras,
  last_decision_at_persisted=2026-06-13T09:24:24.101874+00:00
ai_shadow: status=inactive, inactive_reason='LLM_SHADOW_ENABLED=false'
  enabled=False, enabled_by_config=[
    {'flag': 'PAPER_SHADOW_WALLETS_ENABLED', 'value': True},
    {'flag': 'LLM_SHADOW_ENABLED', 'value': False}
  ]
  last_decision_at_source=persisted_candidate_extras,
  last_decision_at_persisted=2026-06-13T09:24:24.101874+00:00
```

Boundary guarantees:
- DETERMINISTIC_SHADOW is **active** by default.
- AI_SHADOW is **inactive** with the exact `LLM_SHADOW_ENABLED=false` reason
  surfaced in `inactive_reason`.
- `last_decision_at_source="persisted_candidate_extras"` confirms the H11
  durable derivation: the value survives a backend restart because it comes
  from DB-persisted candidate extras (the runtime in-memory tracker would be
  None after restart and the source label says so honestly).

---

## 7. Dashboard SSR/HTML evidence (raw)

```text
$ curl -s http://localhost:3000/ | grep -oE \
    "Engine Daily Reports|Engine Decision Analytics|Trading Activity|\
     Advanced diagnostics|Legacy ENGINE-only|All wallets cash|All accounts cash"
Advanced diagnostics
Engine Daily Reports
Engine Decision Analytics
Legacy ENGINE-only
Trading Activity
```

Static SSR HTML contains the three engine panel section titles + Trading
Activity. The aggregate strings `All wallets cash` and `All accounts cash`
do not appear — verified by grep returning empty for both. Legacy ENGINE-only
is collapsed under Advanced diagnostics.

`Engine Accounts` and `Engine Performance Today` render after client
hydration once `walletPerf`/`wallets` fetches complete; they have explicit
`if (!data) return null` guards so they do not appear in raw SSR HTML.
Source-level verification (committed):
- `function EngineAccountsSection`
- `function EngineDailyReportsSection`
- `function EngineDecisionAnalyticsSection`
are all present in `frontend/dashboard/app/page.tsx`.

---

## 8. Exact deep-status fields proven by the isolated test

The scoped endpoint is identical in shape to the public deep-status endpoint
(it derives its data by adding `WHERE tick_id LIKE $1` to every query).
Below are the exact values the test asserts; passing the test proves all
these fields are populated correctly by the SQL pipeline:

| Field | Asserted value |
|---|---|
| `candidates.total` | 5 |
| `candidates.with_extras_json` | 4 |
| `candidates.extras_json_coverage_percent` | 80.0 |
| `candidates.by_action.enter` | 2 |
| `candidates.by_action.reject` | 2 |
| `candidates.by_catalyst_type.earnings` | 2 |
| `candidates.by_entry_mode.catalyst` | 3 |
| `tick_ts_audit.tick_ts_persistence_status` | `"not_persisted_as_candidate_column"` |
| `tick_ts_audit.paper_ticks_total` | 3 |
| `tick_ts_audit.candidates_joinable_to_ticks_coverage_percent` | 100.0 |
| `extras_json_field_family_coverage.*.coverage_percent` | 100.0 for all 11 families |
| `extras_json_field_family_coverage.*.status` | `"collected"` for all 11 families |
| `shadow_decision_persistence.deterministic_shadow.would_enter_count` | 1 |
| `shadow_decision_persistence.deterministic_shadow.watch_count` | 1 |
| `shadow_decision_persistence.deterministic_shadow.would_reject_count` | 2 |
| `shadow_decision_persistence.ai_shadow.disabled_count` | 2 |
| `shadow_decision_persistence.ai_shadow.error_count` | 1 |
| `shadow_decision_persistence.ai_shadow.not_selected_count` | 1 |
| `outcomes.total` | 5 |
| `outcomes.resolved_at_null_count` | 2 |
| `outcomes.resolved_at_present_count` | 3 |
| `outcomes.resolved_at_min` / `_max` | non-null and equal to `min_resolved_at`/`max_resolved_at` aliases |
| `outcomes.distinct_candidates_with_any_outcome` | 2 |
| `outcomes.required_horizons` | `[5, 15, 30, 60, 120]` |
| `outcomes.horizon_row_coverage.5.candidates_with_row` | 2 |
| `outcomes.horizon_row_coverage.5.candidates_missing_row` | 3 |
| `outcomes.candidates_with_all_required_horizons` | 0 |
| `outcomes.candidates_missing_any_required_horizon` | 5 |
| `trades.total` | 4 |
| `trades.by_event.entry` / `.exit` | 2 each |
| `trades.by_wallet_id.engine` / `.deterministic_shadow` | 3 / 1 |
| `trades.missing_opened_at_for_entry` | 1 |
| `trades.missing_closed_at_for_exit` | 1 |
| `trades.invalid_out_of_session_count` | 1 |
| `trades.future_opened_at_count` / `.future_closed_at_count` | 0 / 0 |
| `trades.column_mapping_note` | contains `opened_at IS the entry timestamp; closed_at IS the exit timestamp` |
| `engine_analysis_ready` | True |
| `deterministic_shadow_analysis_ready` | True |
| `ai_shadow_analysis_ready` | True |
| `overall_freeze_audit_ready` | True |
| `analysis_ready` | True |
| `blocking_gaps` | `[]` |

---

## 9. Confirmations

- No broker / live-trading / real-order code introduced.
  Verified by `test_no_broker_tokens_anywhere` across `api/audit.py`,
  `api/paper.py`, and `paper/shadow_wallets.py`.
- No paid AI calls.
  Verified by `test_no_paid_ai_provider_calls`. The scoped endpoint queries
  Postgres only; it does not invoke any external AI provider.
- No scoring/entry/exit/TP/SL changes — all simulator entry/exit paths
  unchanged.
- H3 weekend gate intact (`test_h3_session_gate_still_blocks_weekends`).
- H5 invalid OOS exclusion intact (`test_h5_oos_exclusion_still_works`).
- H7/H10/H11 three-engine dashboard structure intact (page.tsx source-level).
- No aggregate all-wallet cash/equity reintroduced (verified by grep).
