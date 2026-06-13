# Codex Review — Phase G1B-H9 Final Audit / Shadow Status

**Verdict: YELLOW / NEEDS FOLLOW-UP**

## 1. Executive summary

G1B-H9 materially improves the specific G1B-H8 caveats around deterministic shadow activation, explicit extras JSON collection status, direct `resolved_at` null counts, true missing-horizon-row checks, multi-source latest NY session dates, and per-engine readiness flags.

However, I am not marking this PASS because the patch does **not** add the requested DB-seeded exact-value tests. The new H9 tests are mostly response-shape/static/source tests against the app and current runtime state, not controlled database fixtures that prove exact aggregate values. I also found API-field coverage gaps: `/api/paper/wallets` exposes the new status/config fields, but `/api/paper/wallets/performance` and `/api/paper/wallets/analytics` do not expose the full requested `enabled`, `active`, `enabled_by_config`, `processing_enabled`, `last_decision_at`, and related status-field set. No committed Claude runtime evidence was present for deployed VM status, live dashboard screenshots, or live `/api/audit/persistence/deep-status` output.

The patch remains fake-money/paper-only from the reviewed diff, keeps `LLM_SHADOW_ENABLED=false` by default, does not add paid AI calls, and does not change scoring thresholds or normal engine entry/exit/TP/SL/max-hold logic.

## 2. Deterministic shadow status findings

**Mostly pass, with API-surface caveats.**

What passes:

- `PAPER_SHADOW_WALLETS_ENABLED` now defaults to `True`, and a dedicated `PAPER_DETERMINISTIC_SHADOW_ENABLED` flag defaults to `True`.
- Deterministic shadow status no longer depends on `LLM_SHADOW_ENABLED`; `_wallet_status()` only marks deterministic shadow inactive when the master shadow switch or deterministic-specific switch is disabled.
- The deterministic snapshot includes `enabled`, `processing_enabled`, `enabled_by_config`, `depends_on_llm`, `last_entry_at`, `last_exit_at`, and `last_decision_at`.
- If deterministic shadow is disabled, the exact reason is exposed as `PAPER_DETERMINISTIC_SHADOW_ENABLED=false`.
- The dashboard now renders active no-trade state as `active — no trades this session`, so no trades alone should not make the card appear inactive.

Caveats:

- `last_decision_at` is set to `last_entry_at`, so it only reflects entry decisions, not WATCH/WOULD_REJECT decisions. This is labeled best-effort in code, but it does not fully satisfy “last decision” semantics for a no-entry deterministic-shadow session.
- `/api/paper/wallets/performance` returns `status` and `inactive_reason`, but not the full requested processing/config fields.
- `/api/paper/wallets/analytics` returns decision counts and availability fields, but not the full requested `enabled`/`active`/`enabled_by_config`/`processing_enabled` status field set.

## 3. AI shadow status findings

**Pass with caveats.**

- `LLM_SHADOW_ENABLED` remains default `False`.
- `AI_SHADOW` remains visible and inactive in wallet snapshots when LLM shadow is disabled, with `inactive_reason == "LLM_SHADOW_ENABLED=false"`.
- The AI analytics response reports `llm_enabled`, decision/status counts, `no_paid_ai_calls`, and `unavailable_reason == "LLM_SHADOW_ENABLED=false"` when LLM is disabled.
- The reviewed H9 diff does not add paid OpenAI/Anthropic/DeepSeek/Groq/Mistral/Gemini client calls.

Caveat: `/api/paper/wallets/analytics` keeps a provider note mentioning local/free LLM provider examples, but the endpoint does not expose the same precise status/config structure as `/api/paper/wallets`.

## 4. DB audit caveat-closure findings

**Mostly pass.**

Closed or substantially improved H8 caveats:

1. **extras JSON explicit status:** field-family coverage now includes `coverage_scope`, `sample_size`, `rows_present`, `coverage_percent`, `status`, and `keys_found`.
2. **candidate tick timestamp:** deep-status still honestly reports candidate `tick_ts` as not stored directly, but includes joinability to `paper_ticks.started_at` through `tick_id`.
3. **global `analysis_ready`:** deep-status now adds separate `engine_analysis_ready`, `deterministic_shadow_analysis_ready`, `ai_shadow_analysis_ready`, and `overall_freeze_audit_ready` flags, with top-level `analysis_ready` mapped to the stricter overall flag.
4. **direct resolved_at null counts:** outcome audit now includes direct `resolved_at_null_count` and `resolved_at_present_count`, separate from status-derived missing counts.
5. **true missing horizon rows:** outcome audit now checks absent candidate/horizon rows with per-horizon `candidates_with_row`, `candidates_missing_row`, resolved, pending, and error/missing-data counts, plus top-level required-horizon summaries.
6. **latest session date:** NY session grouping now reports latest trade, candidate, and outcome session dates, then chooses the max available date and source.
7. **deterministic readiness:** deterministic shadow readiness is based on evidence of collected deterministic shadow fields, not hidden behind one global ready flag.

Remaining caveats:

- The latest-session source is selected with `next(src for src, d in available if d == latest_session_date)`, so ties are deterministic by ordering but not explicitly documented.
- Deep-status still samples extras JSON from the most recent 5,000 rows rather than full-table coverage. This is acceptable because `coverage_scope` is explicit, but it remains a sampled audit.
- `resolved_at_min`/`resolved_at_max` are present as legacy `min_resolved_at`/`max_resolved_at`, not under the exact requested names.

## 5. DB-seeded test findings

**Needs follow-up. This is the main blocker for PASS.**

The patch adds `backend/tests/test_phase_g1b_h9.py`, but the tests are not DB-seeded exact-value tests. They primarily verify:

- default config values;
- response fields from `/api/paper/wallets`;
- deep-status field presence/shape when a DB pool exists;
- source strings in the dashboard;
- selected H3/H5/H7 regression invariants;
- absence of a few forbidden tokens in selected modules.

They do **not** seed controlled database rows and assert exact aggregate outputs for the requested cases, including exact candidate tick timestamp derivation, exact extras-family collected/not-collected coverage, exact direct `resolved_at_null_count`, exact missing horizon rows, exact latest-session fallback from trades/candidates/outcomes, exact trade timestamp integrity counts, or readiness false/warnings when critical dimensions are absent.

Because the H9 assignment explicitly required DB-seeded exact-value tests and stated shape/source tests alone are not enough, this remains a required follow-up patch.

## 6. Dashboard regression findings

**Mostly pass.**

- The wallet snapshot TypeScript interface includes the new H9 status/config/timestamp fields.
- `EngineAccountCard` now displays inactive reason as `disabled by config: ...` and displays `active — no trades this session` when an active account has no open or closed trades.
- The three account cards are still explicitly rendered for `ENGINE`, `DETERMINISTIC_SHADOW`, and `AI_SHADOW`.
- I did not find a resurrected `WalletDailyAnalytics` aggregate component or obvious primary aggregate all-wallet cash/equity card in the latest patch.

Caveat: I did not review a browser screenshot or deployed dashboard runtime artifact, so dashboard findings are source-based only.

## 7. H3/H5/H7 regression findings

**Pass by code/tests reviewed.**

- The H9 test suite includes a weekend closed-market gate assertion for H3.
- The H9 targeted test verifies invalid out-of-session trades are excluded from normal realized P&L in wallet performance.
- Existing H7 dashboard structure markers remain present and `function WalletDailyAnalytics` remains absent.
- The targeted regression suite I ran passed, including H3, H5, H7, and H9 tests.

## 8. Safety findings

**Pass.**

- The latest diff does not introduce broker, live-trading, real-order, real-money execution, Alpaca, IBKR, Robinhood, `place_order`, `submit_order`, `execute_order`, or `send_order` implementation.
- The latest diff does not introduce paid AI API calls.
- `LLM_SHADOW_ENABLED` remains false by default.
- The H9 patch does not change `PAPER_ENTRY_SCORE_THRESHOLD`, TP/SL percentages, max-hold minutes, or normal engine entry/exit mechanics in the reviewed diff.
- All reviewed changes remain within fake-money/paper simulation boundaries.

## 9. Evidence

Reviewed code evidence:

- Latest reviewed commit: `1abb09f Close audit caveats and enable deterministic shadow status`.
- Latest patch changed only `backend/api/audit.py`, `backend/core/config.py`, `backend/paper/shadow_wallets.py`, `backend/tests/test_phase_g1b_h9.py`, and `frontend/dashboard/app/page.tsx`.
- Deterministic shadow config defaults are now on.
- Shadow wallet status/config metadata is implemented in `backend/paper/shadow_wallets.py`.
- Deep-status audit fields are implemented in `backend/api/audit.py`.
- Dashboard display changes are implemented in `frontend/dashboard/app/page.tsx`.

Commands used for review:

```bash
git status --short
git log --oneline -5
git diff --stat HEAD~1..HEAD
git diff --name-only HEAD~1..HEAD
rg -n "G1B-H9|deep-status|DETERMINISTIC_SHADOW|AI_SHADOW|LLM_SHADOW_ENABLED|resolved_at_null|coverage_scope|latest_session_date|missing_horizon" -S .
python -m py_compile backend/tests/test_phase_g1b_h9.py
cd backend && pytest -q tests/test_phase_g1b_h9.py tests/test_phase_g1b_h3.py tests/test_phase_g1b_h5.py tests/test_phase_g1b_h7.py
git diff HEAD~1..HEAD -G"broker|live trading|real order|real-money|Alpaca|IBKR|Robinhood|place_order|submit_order|execute_order|send_order|OpenAI\(|DeepSeek|Groq|Mistral|Gemini|Ollama|LLM_SHADOW_ENABLED|PAPER_ENTRY_SCORE_THRESHOLD|TAKE_PROFIT|STOP_LOSS|MAX_HOLD" -- .
```

## 10. Tests reviewed

Reviewed new H9 tests:

- `test_paper_shadow_wallets_enabled_default_is_true`
- `test_deterministic_shadow_specific_flag_exists_and_defaults_true`
- `test_deterministic_shadow_active_by_default`
- `test_ai_shadow_inactive_due_llm_disabled_by_default`
- `test_deterministic_shadow_does_not_depend_on_llm`
- `test_deterministic_shadow_disabled_by_own_flag`
- `test_shadow_wallet_exposes_enabled_processing_config_fields`
- `test_ai_shadow_snapshot_carries_no_paid_ai_calls_flag`
- deep-status field-shape tests for coverage scope/status, resolved_at counts, horizon fields, latest-session fields, and readiness flags
- dashboard source-string tests for no-trade state, disabled config reason, H9 wallet snapshot fields, no aggregate account total, and three-engine structure
- H3 weekend gate, H5 invalid-OOS exclusion, and limited safety token tests

Test result:

```text
103 passed, 2 skipped, 1 warning in 0.65s
```

## 11. Runtime evidence reviewed

No committed Claude runtime evidence was present in the repository/context for G1B-H9. I did **not** review:

- deployed VM commit evidence;
- backend health output;
- frontend production build output from Claude;
- deployed dashboard screenshot showing deterministic shadow active/no-trade state;
- live `/api/paper/wallets`, `/api/paper/wallets/performance`, `/api/paper/wallets/analytics`, or `/api/audit/persistence/deep-status` JSON from the deployed VM.

This review is therefore based on the GitHub/source patch and local tests only.

## 12. Freeze-readiness judgment

**YELLOW / NEEDS FOLLOW-UP.**

The code direction is good and closes many H8 caveats, but it is not freeze-ready as a final audit gate because the required DB-seeded exact-value tests are missing and runtime evidence was not available. The API status-field coverage across all three requested wallet endpoints is also incomplete.

## 13. Required follow-up patches

1. Add DB-seeded exact-value tests that create controlled candidates, ticks, outcomes, trades, and extras JSON rows, then assert exact deep-status values for all requested H9 audit dimensions.
2. Extend `/api/paper/wallets/performance` and `/api/paper/wallets/analytics` to expose the full wallet status/config field set or document why `/api/paper/wallets` is the canonical status endpoint.
3. Track a true deterministic `last_decision_at` for WATCH/WOULD_REJECT/no-entry decisions, not only entry timestamps.
4. Add/attach runtime evidence after VM deployment: deployed commit, backend health, dashboard screenshot, wallet endpoint JSON, and live deep-status JSON showing readiness flags, blocking gaps, warnings, coverage statuses, resolved_at direct counts, missing horizon rows, and latest-session source.
5. Consider adding exact requested aliases `resolved_at_min` and `resolved_at_max` alongside `min_resolved_at` and `max_resolved_at` for contract clarity.
