# Codex Review — Phase G1B-H6 Wallet Journal / Analytics / DB Audit

**Verdict: PASS WITH CAVEATS**

## 1. Executive summary

G1B-H6 addresses the immediate dashboard-confusion risk by moving the remaining ENGINE-only Journal / History, Journal Report, and Analytics panels into a collapsed `Legacy ENGINE diagnostics` details block. The labels are explicit that these panels are ENGINE-only and are superseded by wallet-aware sections above them. This satisfies the acceptable fallback path in the review request, even though the preferred wallet-aware Journal Report and Wallet / Strategy Analytics conversion was not implemented in this patch.

The patch also adds `/api/audit/persistence/deep-status`, which is a meaningful read-only DB audit endpoint for candidate, outcome, trade, wallet snapshot, timestamp, and analysis-readiness checks. It improves freeze inspectability, especially for `extras_json` coverage, outcome status/horizon/source, trade wallet/strategy completeness, invalid out-of-session separability, and candidate-to-outcome joinability.

Caveats remain because the deep audit endpoint does not fully prove every requested raw-data field and timestamp dimension. In particular, it does not report candidate `tick_ts` min/max, candidate counts by explicit strategy/path/wallet, trade `session_date_ny` missing counts, persisted wallet-state table rows, or deterministic/AI shadow decision-field persistence coverage. I did not find runtime evidence from Claude in the repo, so deployment/browser/audit-output proof remains unreviewed.

## 2. Findings

### Finding 1 — Legacy ENGINE dashboard sections are now clearly isolated

**Status: Pass.**

The main dashboard keeps wallet-aware `Trading Activity` visible above the legacy diagnostics and describes it as covering all fake wallets, latest US trading session, and wallet filtering. `WalletDailyAnalytics` remains immediately below it as the wallet-scoped daily analytics section. The old ENGINE-only panels are inside a collapsed `<details>` block titled `Legacy ENGINE diagnostics`, with subtitle text saying `ENGINE-only`, `superseded by wallet-aware sections above`, and `collapsed by default`.

Inside that collapsed block:

- `Legacy ENGINE Analytics` is explicitly `ENGINE-only`.
- `Legacy ENGINE Journal Report` is explicitly an engine-only journal daily summary.
- `Legacy ENGINE Journal / History` is explicitly an ENGINE-only persistent PostgreSQL log.

This is not the preferred wallet-aware Journal Report / Strategy Analytics implementation, but it meets the acceptable fallback of clear legacy labeling plus visual separation/collapse.

### Finding 2 — Main visible daily reporting remains wallet-aware

**Status: Pass.**

The visible dashboard path continues to emphasize wallet-aware reporting through `Trading Activity` and `WalletDailyAnalytics`. The legacy report is no longer visually presented as the primary daily report because it is nested inside the collapsed legacy details block.

### Finding 3 — Deep persistence audit endpoint was added

**Status: Pass with caveats.**

`GET /api/audit/persistence/deep-status` was added and is read-only. It checks whether a DB pool exists, then reports candidate totals and `extras_json` coverage, outcome breakdowns, trade wallet/strategy counts and missing-field counts, invalid out-of-session trade count, live wallet snapshots, candidate-to-outcome joinability, NY-session derivation notes, and UTC timestamp documentation.

Important caveats:

- Candidate audit reports `created_at` min/max but not `tick_ts` min/max.
- Candidate audit reports `by_marketdata_source`, `by_action`, and `by_rejection_reason`, but not an explicit by-wallet, by-strategy, or by-path/source breakdown for all decision sources.
- Trade audit does not report missing `session_date_ny` counts. This is acceptable only if session date remains intentionally derivable rather than stored.
- Wallet snapshots are pulled from current simulator/shadow in-memory status rather than proving a persisted wallet-state table.
- Raw field preservation for catalyst details, marketdata snapshots, deterministic shadow decision fields, and AI shadow disabled/error/not-selected fields is not fully proven by this endpoint.

### Finding 4 — H3/H4/H5 regression risk appears low for the latest patch

**Status: Pass for reviewed scope.**

The latest patch changes only `backend/api/audit.py`, `backend/tests/test_phase_g1b_h6.py`, and `frontend/dashboard/app/page.tsx`. It does not change scoring thresholds, Engine entry/exit logic, TP/SL/max-hold logic, wallet performance calculations, or the H3 EOD/session gate code. The new H6 tests include a weekend-block assertion for the H3 session gate and wallet trade row tagging checks.

### Finding 5 — Safety boundaries remain intact for the latest patch

**Status: Pass.**

The H6 endpoint is audit/read-only code. I found no new live trading, broker, real-order, real-money execution, or paid-AI call implementation in the latest patch. `LLM_SHADOW_ENABLED` remains disabled by default.

### Finding 6 — Tests cover the main H6 changes but not all requested runtime/persistence proofs

**Status: Pass with caveats.**

The new test file covers legacy section renaming/grouping, no obvious generic unfiltered daily/analytics labels, endpoint response shape, candidate `extras_json` coverage keys, outcome breakdown keys, trade wallet/strategy missing counts, timestamp integrity shape, candidate-to-outcome joinability, NY-session support note, invalid out-of-session separability, wallet snapshots, H3 weekend gate, and forbidden broker/paid-AI tokens in the deep-status endpoint.

The tests do not fully cover:

- browser-rendered visual state or screenshots;
- wallet filter interaction for legacy and wallet-aware sections;
- a real PostgreSQL audit with non-empty candidate/outcome/trade rows;
- candidate `tick_ts` min/max;
- raw deterministic shadow / AI shadow decision persistence;
- candidate catalyst/marketdata snapshot field coverage;
- no scoring/entry/exit/TP/SL changes via diff assertions beyond the latest patch scope.

## 3. Evidence

### Dashboard structure evidence

- Wallet-aware `Trading Activity` is visible before the legacy block and advertises all fake wallets, latest US trading session, close persistence, and wallet filtering.
- `WalletDailyAnalytics` is rendered directly below Trading Activity as wallet-scoped daily analytics.
- Legacy diagnostics are placed in a collapsed `<details>` section titled `Legacy ENGINE diagnostics` with a subtitle stating `ENGINE-only`, `superseded by wallet-aware sections above`, and `collapsed by default`.
- The three old panels are explicitly titled `Legacy ENGINE Analytics`, `Legacy ENGINE Journal Report`, and `Legacy ENGINE Journal / History`, each with ENGINE-only/fake-money/no-broker labeling.

### Persistence audit evidence

- The endpoint route is `@router.get("/persistence/deep-status")` and documents that it is a comprehensive G1B-H6 persistence audit.
- Candidate audit queries total candidate rows, rows with `extras_json`, `created_at` min/max, action counts, rejection-reason counts, marketdata-source counts, missing tick IDs, and missing `created_at` counts.
- Outcome audit queries total outcomes, status counts, horizon/status counts, source counts, and resolved timestamp min/max.
- Trade audit queries total trades, event counts, wallet counts, strategy counts, exit-reason counts, missing wallet/strategy/opened/closed timestamps, invalid out-of-session count, and created timestamp min/max.
- Analysis readiness reports candidate-to-outcome joinable rows, trade wallet/strategy separability, NY session-date derivation support, invalid out-of-session separability, and wallet breakdown support for engine, deterministic shadow, and AI shadow.
- Timestamp metadata documents `TIMESTAMPTZ (UTC)`, NY session derivation through `session.session_date_for`, and a 300-second future timestamp tolerance.

### Safety evidence

- H6 tests include broker/live/order token checks for the deep-status endpoint and paid-AI token checks for the same function.
- Core config still defaults `LLM_SHADOW_ENABLED` to `False`.
- The latest H6 patch did not modify trading/scoring/entry/exit modules.

## 4. DB persistence audit judgment

**Judgment: PASS WITH CAVEATS.**

The added endpoint is a substantial improvement and is sufficient to verify many freeze-readiness invariants from a running database. It should help answer whether candidate rows exist, whether `extras_json` is populated, whether outcomes are resolving by horizon/status/source, whether trade rows are wallet/strategy separable, whether invalid out-of-session trades are counted separately, and whether timestamps are plausibly UTC with NY-session derivation support.

However, it is not a complete proof of all requested future-analysis fields. Follow-up should add or expose:

1. candidate `tick_ts` min/max and missing `tick_ts` count;
2. candidate counts by persisted decision source/path/strategy/wallet where available;
3. explicit raw-field coverage for catalyst data and marketdata snapshot payloads;
4. deterministic shadow decision/status field coverage;
5. AI shadow disabled/error/not-selected field coverage, even when LLM is disabled;
6. persisted wallet-state audit if wallet state is intended to be stored beyond in-memory snapshots;
7. `session_date_ny` missing count if a stored session-date column is later added.

## 5. Dashboard clarity judgment

**Judgment: PASS.**

The dashboard now clearly separates main wallet-aware reporting from legacy ENGINE-only diagnostics. The remaining legacy Journal / History, Journal Report, and Analytics sections are no longer generic-looking top-level daily sections; they are explicitly labeled `Legacy ENGINE` and hidden inside a collapsed details block. That resolves the main H6 confusion concern without requiring a full wallet-aware rewrite of those panels in this patch.

Preferred future UX remains a true wallet-aware Journal Report and Wallet / Strategy Analytics panel, but that is now an enhancement rather than a blocker for clarity.

## 6. Tests reviewed

I reviewed and ran the new H6 tests. They cover:

- legacy ENGINE Journal / History, Journal Report, and Analytics labeling;
- collapsed `Legacy ENGINE diagnostics` grouping;
- absence of obvious generic unfiltered top-level Analytics / Today Session Report labels;
- `/api/audit/persistence/deep-status` response availability;
- candidate `extras_json` coverage fields;
- outcome by-status/by-horizon/by-source fields;
- trade wallet/strategy counts and missing counts;
- timestamp integrity keys;
- candidate-to-outcome joinability keys;
- trade wallet/strategy separability keys;
- NY-session filtering support note;
- invalid out-of-session separability;
- wallet snapshots for engine and both shadow wallets;
- wallet trade rows carrying `wallet_id` and `strategy_id`;
- H3 weekend session gate;
- no broker/live/order/paid-AI tokens in the deep-status endpoint.

Command run:

```bash
python -m pytest backend/tests/test_phase_g1b_h6.py
```

Result: **21 passed, 1 warning**.

## 7. Runtime evidence reviewed

No Claude runtime evidence file, dashboard screenshot, deployed commit proof, browser proof, or live `/api/audit/persistence/deep-status` JSON output was present in the reviewed repo patch. Therefore I reviewed code and tests only.

Runtime evidence still desirable before freeze:

- deployed commit hash matching this code;
- backend health output;
- frontend build output;
- dashboard screenshot showing legacy diagnostics collapsed by default;
- browser proof that wallet filter selection changes wallet-aware sections;
- live deep-status endpoint output with non-empty DB counts and no integrity failures.

## 8. Freeze-readiness judgment

**Freeze readiness: PASS WITH CAVEATS.**

H6 is safe to merge for fake-money monitoring and resolves the immediate misleading-dashboard-section concern. It does not add broker/live/real-order code, paid AI calls, or trading logic changes.

Before relying on the system for deeper post-freeze analysis, collect live deep-status output and patch the audit endpoint to prove the remaining raw-field and timestamp dimensions listed above. The current endpoint is good enough for high-level separability and integrity, but not yet a full forensic guarantee that every useful shadow/decision/catalyst/marketdata field is persisted in PostgreSQL.

## 9. Required follow-up patches, if any

No blocker follow-up is required for dashboard clarity.

Recommended follow-ups:

1. Add candidate `tick_ts` min/max and missing `tick_ts` count to `/api/audit/persistence/deep-status`.
2. Add candidate breakdowns by persisted decision source/path/strategy/wallet where schema support exists.
3. Add audit fields proving catalyst and marketdata snapshot persistence coverage.
4. Add deterministic shadow and AI shadow decision/status coverage to the audit output, including AI disabled/error/not-selected counts.
5. Add runtime evidence with live deep-status JSON and a dashboard screenshot after deployment.
6. Eventually replace legacy ENGINE Journal Report and Analytics with first-class wallet-aware versions, while keeping legacy panels collapsed or moving them to a diagnostics-only area.
