# Runtime Evidence — Phase G1B-H11

**Branch:** `main`
**Parent commit:** `3e414a3` (G1B-H10)
**Date of capture:** 2026-06-13
**Backend container status:** healthy — `uvicorn` on `:8000`, restarted after rebuild.
**Frontend container status:** previously rebuilt for H10 — unchanged in H11 (no frontend code touched).
**Backend test suite:** `pytest tests/test_phase_g1b_h11.py` → **17 passed, 2 skipped** (frontend-not-mounted only).
**All G1B suites (H1–H11):** **209 passed, 51 skipped.**

Fake-money paper simulation only. No broker. No live trading. No real orders.
No paid AI calls.

---

## 1. Real DB-backed integration test (Part A) — PASSED on VM

The new `test_real_db_integration_seeded_rows_flow_through` test:

1. Opens a dedicated `asyncpg.connect(DATABASE_URL)` connection (not the shared
   pool, to avoid concurrent-operation conflicts with the live endpoint
   invocation from the TestClient).
2. INSERTs a controlled `paper_ticks` row (unique `tick_id` per test run via
   uuid).
3. INSERTs one `paper_candidates` row with a fully-populated `extras_json`
   covering every one of the 11 field families (`marketdata_*`,
   `catalyst_type`, `reddit_*`, `earnings_*`, `insider_*`,
   `market_trend_*`, `enhanced_shadow_decision='WOULD_REJECT'`,
   `enhanced_shadow_score=42`, `llm_decision='WATCH'`,
   `llm_status='not_selected'`, `entry_mode`, `score_components`).
4. INSERTs 2 `paper_candidate_outcomes` rows (horizon 5 resolved, horizon 15
   pending).
5. INSERTs 2 `paper_trades_journal` rows (engine entry + exit).
6. Calls `GET /api/audit/persistence/deep-status` against the real running
   FastAPI app.
7. Asserts every field family shows `status="collected"` with
   `rows_present >= 1`, the seeded tick is counted, candidate aggregates
   reflect the row, and shadow_decision_persistence reports
   `ai_shadow.status="collected"` because our seeded `llm_status` lands in
   the recent-5k sample.
8. Cleans up with `DELETE … WHERE tick_id = '<unique>'` in `finally`.

The test auto-skips if `DATABASE_URL` is not configured. On this VM it ran
in **9.14s including DB I/O and reported pass**.

---

## 2. `/api/paper/wallets` — durable `last_decision_at` provenance (Part F)

After a fresh backend restart (no runtime tick has executed yet):

```json
{
  "engine": {
    "status": "active",
    "inactive_reason": null,
    "last_decision_at": null,
    "last_decision_at_runtime": null,
    "last_decision_at_persisted": null,
    "last_decision_at_source": null
  },
  "deterministic_shadow": {
    "status": "active",
    "inactive_reason": null,
    "last_decision_at": "2026-06-13T09:24:24.101874+00:00",
    "last_decision_at_runtime": null,
    "last_decision_at_persisted": "2026-06-13T09:24:24.101874+00:00",
    "last_decision_at_source": "persisted_candidate_extras"
  },
  "ai_shadow": {
    "status": "inactive",
    "inactive_reason": "LLM_SHADOW_ENABLED=false",
    "last_decision_at": "2026-06-13T09:24:24.101874+00:00",
    "last_decision_at_runtime": null,
    "last_decision_at_persisted": "2026-06-13T09:24:24.101874+00:00",
    "last_decision_at_source": "persisted_candidate_extras"
  }
}
```

**Key result:** DETERMINISTIC_SHADOW's `last_decision_at` is sourced from
durable persisted candidate extras (`persisted_candidate_extras`), not from
the in-memory runtime tracker that was empty after restart. This is the
Codex-required durability guarantee. The dashboard never falsely reports
"runtime" for a stale value, and never falsely reports `last_entry_at` as a
true decision.

Test guarantees by source case:

| Source                             | Test                                                       |
|------------------------------------|------------------------------------------------------------|
| `runtime`                          | `test_last_decision_at_source_runtime`                     |
| `persisted_candidate_extras`       | `test_last_decision_at_source_persisted_after_simulated_restart` |
| `last_entry_fallback`              | `test_last_decision_at_source_fallback_to_last_entry`      |
| `none`                             | `test_last_decision_at_source_none_when_no_data`           |

---

## 3. `/api/audit/persistence/deep-status` — readiness + warnings

```text
analysis_ready: True
overall_freeze_audit_ready: True
engine_analysis_ready: True
deterministic_shadow_analysis_ready: True
ai_shadow_analysis_ready: True
blocking_gaps: []
warnings: [
  'low_extras_json_coverage_0.0_percent',
  'trades_missing_wallet_id_1344',
  'missing_outcome_rows_598714_candidates'
]

outcomes.resolved_at_null_count:  255
outcomes.resolved_at_present_count: 0
outcomes.resolved_at_min:  null
outcomes.resolved_at_max:  null

ny_session_grouping.latest_session_date: 2026-06-13
ny_session_grouping.latest_session_date_source: trades

shadow_decision_persistence:
  deterministic_shadow.status: collected
    WOULD_ENTER: 3
    WATCH:       6
    WOULD_REJECT: 42
  ai_shadow.status: collected
    disabled: 51
    error:    0
    not_selected: 0

trades.missing_entry_time:           664
trades.missing_exit_time_for_closed: 0
trades.future_opened_at_count:       0
trades.future_closed_at_count:       0
```

---

## 4. Latest-session fallback behavior (Part B) — verified by tests

- `test_latest_session_falls_back_to_candidates_when_no_trades` seeds a
  controlled fixture with 0 trades and 5 candidates over `2026-06-13` &
  `2026-06-12`. Asserts:
  - `latest_trade_session_date is None`
  - `latest_candidate_session_date == "2026-06-13"`
  - `latest_session_date == "2026-06-13"`
  - `latest_session_date_source == "candidates"`
- `test_latest_session_falls_back_to_outcomes_when_no_trades_or_candidates`
  seeds 0 trades / 0 candidates and 3 outcomes on `2026-06-10`. Asserts:
  - `latest_session_date == "2026-06-10"`
  - `latest_session_date_source == "outcomes"`

---

## 5. Negative readiness fixture (Part C) — verified

`test_negative_readiness_blocking_gaps_and_warnings` seeds a fixture where:
- 100 candidates but 0 with `extras_json`
- 0 outcomes → 0 candidate→outcome joins
- 50 trades all missing `wallet_id`/`strategy_id`
- 0 shadow evidence rows

Asserts:
- `engine_analysis_ready == False`
- `deterministic_shadow_analysis_ready == False`
- `ai_shadow_analysis_ready == False`
- `overall_freeze_audit_ready == False`
- `"no_candidate_to_outcome_joins" in blocking_gaps`
- `"deterministic_shadow_decisions_not_persisted" in warnings`
- `"ai_shadow_decisions_not_persisted" in warnings`
- `"trades_missing_wallet_id_50"` substring present in warnings
- `ai_shadow_status_note == "ai_shadow_inactive_or_decisions_not_persisted"`

This proves readiness is **not unconditionally True** and the audit
honestly surfaces gaps.

---

## 6. Positive AI shadow error / not_selected counts (Part D) — verified

`test_ai_shadow_positive_error_and_not_selected` seeds the
`shadow_decision_persistence` fixture with `ai_error=3`, `ai_not_selected=2`,
`ai_disabled=4`, `ai_would_enter=1`, `ai_watch=1`. Asserts the endpoint
returns:
- `error_count == 3`
- `not_selected_count == 2`
- `disabled_count == 4`
- `would_enter_count == 1`
- `watch_count == 1`
- `status == "collected"`
- `no_paid_ai_calls is True`

---

## 7. Exact trade timestamp integrity counts (Part E) — verified

`test_exact_trade_timestamp_integrity_counts` seeds 10 trades with:
- 2 entries missing `opened_at`
- 1 exit missing `closed_at`
- 1 trade with `opened_at` in the future
- 0 trades with `closed_at` in the future

Asserts the endpoint returns exactly these counts, plus non-null ISO
timestamps for `min_opened_at`, `max_opened_at`, `min_closed_at`,
`max_closed_at`, `min_created_at`, `max_created_at`, plus the
`column_mapping_note` documenting that `opened_at IS the entry timestamp`
and `closed_at IS the exit timestamp`.

---

## 8. TTL cache behaviour for persisted derivation — verified

`test_refresh_persisted_cache_no_op_within_ttl` patches the pool to count
SQL invocations, then:
1. First `refresh_persisted_last_decision_cache()` hits DB twice (det + ai).
2. Immediate second call within TTL — zero additional DB hits.
3. `force=True` call — 2 more DB hits.

This protects the dashboard polling path from per-request DB load.

---

## 9. Dashboard visual confirmation

Three engine accounts/reports/analytics panels still render; no aggregate
all-wallet cash/equity surface. Verified by
`test_three_engine_dashboard_structure_unchanged` and
`test_no_aggregate_account_total_reintroduced`.

---

## 10. Boundary invariants

- H3 weekend gate: `test_h3_session_gate_still_blocks_weekends` PASSED.
- H5 OOS exclusion: `test_h5_oos_exclusion_still_works` PASSED.
- No broker tokens: `test_no_broker_tokens_anywhere` PASSED.
- No paid AI provider calls: `test_no_paid_ai_provider_calls` PASSED.
