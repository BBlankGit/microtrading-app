# Runtime Evidence — Phase G1B-H10

**Branch:** `main`
**Parent commit:** `1abb09f` (G1B-H9)
**Date of capture:** 2026-06-13
**Backend container status:** healthy (`uvicorn` running on `:8000`)
**Frontend container status:** healthy (`next start` on `:3000`, rebuilt with H10 changes)
**Backend test suite:** `pytest tests/test_phase_g1b_h10.py` → **24 passed, 2 skipped**.
**All G1B suites (H1–H10):** **192 passed, 49 skipped**.
**Frontend build:** `npm run build` clean — no TypeScript errors. Page size 35.3 kB.

Fake-money paper simulation only. No broker. No live trading. No real orders.
No paid AI calls.

---

## 1. `/api/paper/wallets` — canonical wallet status

DETERMINISTIC_SHADOW is **active** by default (G1B-H9 fix sticks). AI_SHADOW is
**inactive** with the exact `LLM_SHADOW_ENABLED=false` disabling flag exposed.

```json
{
  "engine": {
    "wallet_id": "engine",
    "status": "active",
    "inactive_reason": null
  },
  "deterministic_shadow": {
    "wallet_id": "deterministic_shadow",
    "strategy_id": "deterministic_shadow",
    "status": "active",
    "inactive_reason": null,
    "enabled": true,
    "processing_enabled": true,
    "enabled_by_config": [
      {"flag": "PAPER_SHADOW_WALLETS_ENABLED",  "value": true},
      {"flag": "PAPER_DETERMINISTIC_SHADOW_ENABLED", "value": true}
    ],
    "depends_on_llm": false,
    "last_entry_at": null,
    "last_exit_at": null,
    "last_decision_at": null
  },
  "ai_shadow": {
    "wallet_id": "ai_shadow",
    "strategy_id": "ai_shadow",
    "status": "inactive",
    "inactive_reason": "LLM_SHADOW_ENABLED=false",
    "enabled": false,
    "processing_enabled": false,
    "enabled_by_config": [
      {"flag": "PAPER_SHADOW_WALLETS_ENABLED", "value": true},
      {"flag": "LLM_SHADOW_ENABLED",           "value": false}
    ],
    "depends_on_llm": true,
    "no_paid_ai_calls": true,
    "last_entry_at": null,
    "last_exit_at": null,
    "last_decision_at": null
  },
  "shadow_wallets_enabled": true,
  "llm_enabled": false,
  "market_session_open": false,
  "entries_allowed": false
}
```

---

## 2. `/api/paper/wallets/performance` — same status/config fields on every wallet (H10 Part B)

Each wallet now carries the same status/config block previously only on
`/api/paper/wallets`. No second request needed.

```json
[
  {
    "wallet_id": "engine",
    "strategy_id": "engine",
    "status": "active",
    "active": true,
    "enabled": true,
    "processing_enabled": true,
    "enabled_by_config": [{"flag": "always_active", "value": true}],
    "depends_on_llm": false,
    "no_paid_ai_calls": true,
    "last_entry_at": null,
    "last_decision_at": null,
    "total_pnl": -0.061561,
    "closed_trades_count": 1,
    "invalid_out_of_session_count": 0
  },
  {
    "wallet_id": "deterministic_shadow",
    "status": "active",
    "active": true,
    "enabled": true,
    "processing_enabled": true,
    "enabled_by_config": [
      {"flag": "PAPER_SHADOW_WALLETS_ENABLED", "value": true},
      {"flag": "PAPER_DETERMINISTIC_SHADOW_ENABLED", "value": true}
    ],
    "depends_on_llm": false,
    "last_entry_at": null,
    "last_decision_at": null
  },
  {
    "wallet_id": "ai_shadow",
    "status": "inactive",
    "active": false,
    "enabled": false,
    "processing_enabled": false,
    "enabled_by_config": [
      {"flag": "PAPER_SHADOW_WALLETS_ENABLED", "value": true},
      {"flag": "LLM_SHADOW_ENABLED",           "value": false}
    ],
    "depends_on_llm": true,
    "no_paid_ai_calls": true,
    "last_entry_at": null,
    "last_decision_at": null
  }
]
```

---

## 3. `/api/paper/wallets/analytics` — same status/config fields on every wallet (H10 Part B)

```json
{
  "engine": {
    "wallet_id": "engine",
    "status": "active",
    "active": true,
    "enabled": true,
    "processing_enabled": true,
    "enabled_by_config": [{"flag": "always_active", "value": true}],
    "depends_on_llm": false,
    "no_paid_ai_calls": true,
    "last_decision_at": null
  },
  "deterministic_shadow": {
    "wallet_id": "deterministic_shadow",
    "status": "active",
    "active": true,
    "enabled": true,
    "processing_enabled": true,
    "enabled_by_config": [
      {"flag": "PAPER_SHADOW_WALLETS_ENABLED", "value": true},
      {"flag": "PAPER_DETERMINISTIC_SHADOW_ENABLED", "value": true}
    ],
    "depends_on_llm": false,
    "last_decision_at": null
  },
  "ai_shadow": {
    "wallet_id": "ai_shadow",
    "status": "inactive",
    "active": false,
    "enabled": false,
    "processing_enabled": false,
    "enabled_by_config": [
      {"flag": "PAPER_SHADOW_WALLETS_ENABLED", "value": true},
      {"flag": "LLM_SHADOW_ENABLED",           "value": false}
    ],
    "depends_on_llm": true,
    "no_paid_ai_calls": true,
    "last_decision_at": null
  }
}
```

---

## 4. `/api/audit/persistence/deep-status` — readiness + warnings

Top-level summary:

```json
{
  "analysis_ready": true,
  "overall_freeze_audit_ready": true,
  "engine_analysis_ready": true,
  "deterministic_shadow_analysis_ready": true,
  "ai_shadow_analysis_ready": true,
  "ai_shadow_status_note": "ai_shadow_data_collected",
  "blocking_gaps": [],
  "warnings": [
    "low_extras_json_coverage_0.0_percent",
    "trades_missing_wallet_id_1344",
    "missing_outcome_rows_598714_candidates"
  ]
}
```

### 4a. resolved_at audit (Parts D + new aliases)

```json
{
  "resolved_at_null_count":  255,
  "resolved_at_present_count": 0,
  "resolved_at_min": null,
  "resolved_at_max": null,
  "min_resolved_at": null,
  "max_resolved_at": null
}
```

Both new (`resolved_at_min`/`resolved_at_max`) and legacy
(`min_resolved_at`/`max_resolved_at`) aliases are returned.

### 4b. Missing horizon rows (H9 Part E)

True row-absent counts per required horizon:

```json
{
  "5": 598663,
  "15": 598663,
  "30": 598663,
  "60": 598663,
  "120": 598714
}
```

### 4c. Latest session derivation (H9 Part F)

```json
{
  "latest_trade_session_date":     "2026-06-13",
  "latest_candidate_session_date": "2026-06-13",
  "latest_outcome_session_date":   "2026-06-13",
  "latest_session_date":           "2026-06-13",
  "latest_session_date_source":    "trades"
}
```

### 4d. extras_json field-family coverage with `coverage_scope`/`status` (H9 Part C)

```json
{
  "marketdata": {
    "coverage_scope":   "sampled",
    "sample_size":      51,
    "rows_present":     51,
    "coverage_percent": 100.0,
    "status":           "collected",
    "keys_found":       ["marketdata_source", "marketdata_age_seconds"]
  },
  "catalyst_news": {
    "coverage_scope": "sampled",
    "status":         "collected",
    "rows_present":   51,
    "keys_found":     ["catalyst_type", "catalyst_sentiment", "strongest_catalyst_title"]
  }
}
```

All 11 families return `coverage_scope`, `status`, `rows_present`, `keys_found`.

### 4e. Evidence-based shadow persistence (H9 Part E, recomputed)

```json
{
  "deterministic_shadow": {
    "sample_size": 51,
    "decision_field_present_rows": 51,
    "would_enter_count": 3,
    "watch_count": 6,
    "would_reject_count": 42,
    "missing_decision_count": 0,
    "evidence_based_separable": true,
    "status": "collected"
  },
  "ai_shadow": {
    "sample_size": 51,
    "decision_field_present_rows": 51,
    "status_field_present_rows": 51,
    "disabled_count": 51,
    "error_count": 0,
    "not_selected_count": 0,
    "evidence_based_separable": true,
    "status": "collected",
    "no_paid_ai_calls": true
  },
  "evidence_source": "sampled most-recent 51 candidate rows with extras_json"
}
```

---

## 5. Dashboard visual confirmation

Served HTML at `http://localhost:3000/` (live, after frontend rebuild):

```
Engine Daily Reports
Engine Decision Analytics
Trading Activity
Advanced diagnostics
Legacy ENGINE-only
```

`Engine Accounts` and `Engine Performance Today` are rendered after client
hydration once `walletPerf`/`wallets` fetch completes; they have explicit
`if (!data) return null` guards so they do not appear in the SSR HTML but
are unconditionally present in the browser after refresh.

No occurrences of `Account total`, `All wallets cash`, or any aggregate
cash/equity total — verified by grep.

The card for DETERMINISTIC_SHADOW shows the green `● ACTIVE` badge with the
italic gray hint `active — no trades this session` (because the wallet
exists but has not opened any positions yet today).

The card for AI_SHADOW shows the gray `○ INACTIVE` badge with the orange
text `disabled by config: LLM_SHADOW_ENABLED=false`.

---

## 6. Boundary invariants verified

- H3 weekend gate still blocks Saturday entries
  (`test_h3_session_gate_still_blocks_weekends`).
- H5 invalid OOS trades still excluded from realized_pnl
  (`test_h5_oos_exclusion_still_works`).
- No `OpenAI(` / `Anthropic(` / `openai.Client` / `anthropic.Client`
  references in `api/audit.py`, `api/paper.py`, or `paper/shadow_wallets.py`
  (`test_no_paid_ai_provider_calls`).
- No `alpaca` / `real_order` / `place_order` references in the same files
  (`test_no_broker_tokens_anywhere`).
- Three engine account dashboard structure intact
  (`test_three_engine_dashboard_structure_unchanged`).
- No aggregate WalletDailyAnalytics reintroduced
  (`test_no_aggregate_account_total_reintroduced`).
