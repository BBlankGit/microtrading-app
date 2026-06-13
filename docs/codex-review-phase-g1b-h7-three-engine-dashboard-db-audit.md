# Codex Review — Phase G1B-H7 Three-Engine Dashboard + DB Audit

**Verdict: YELLOW / NEEDS FOLLOW-UP**

## 1. Executive summary

G1B-H7 substantially improves the dashboard shape: the primary account area now renders three independent account cards for `ENGINE`, `DETERMINISTIC_SHADOW`, and `AI_SHADOW`; the normal flow includes three daily-report cards, three decision-analytics cards, one wallet-tagged Trading Activity section, an adjusted wallet-comparison section, and legacy ENGINE-only diagnostics moved into a collapsed advanced section.

However, I would not mark this patch freeze-ready yet. The remaining issues are mostly audit/readiness correctness rather than app-code safety:

1. **DB deep-status is still incomplete against the requested audit contract.** It reports `tick_id` coverage, but not candidate `tick_ts` min/max/missing count; it does not add explicit candidate count by path/source, candidate count by catalyst type, or candidate count by engine/decision type; it does not explicitly report missing entry/exit timestamps; and NY-session analysis is documented as derivable rather than actually grouped by NY session date.
2. **Decision analytics are dashboard/runtime-memory based, not fully Postgres-auditable.** `/api/paper/wallets/analytics` derives same-structure analytics from `last_tick_candidates` in simulator memory, not persisted candidate rows. That is acceptable as an interim display, but it does not satisfy the future-analysis persistence requirement by itself.
3. **A dead/unrendered aggregate daily-analytics component remains in the frontend source.** I did not find it rendered in the main dashboard flow, so this is not a primary UI failure, but the code still contains an `All Wallets — Daily Analytics` aggregate across engine + shadows and should be removed or refactored to avoid future reintroduction.
4. **Runtime evidence from Claude was not present in the repo/context I reviewed.** I reviewed static code and the committed tests only.

## 2. Dashboard/account/report/analytics findings

### No misleading primary aggregate account

**Mostly pass, with cleanup caveat.** The main dashboard now places `Engine Performance Today` first, then `Engine Accounts`, and the simulator status explicitly says there is no combined cash/equity total across engines. The `Engine Accounts` section labels the accounts as three independent fake-money experimental accounts with no combined balance. The account-card implementation renders cash/equity per wallet only and labels each card as independent.

Caveat: `WalletDailyAnalytics` still exists as a dead/unrendered component that aggregates total P&L, realized P&L, unrealized P&L, trade counts, and raw OOS P&L when `walletId === "all"`. I found no call site in the main page for that component, so it does not currently appear to be a primary dashboard metric, but it should be removed or converted to a strictly per-engine component to avoid future accidental re-use.

### Three separate engine account cards

**Pass.** `EngineAccountsSection` renders `ENGINE Account`, `DETERMINISTIC_SHADOW Account`, and `AI_SHADOW Account` cards. Each card includes `wallet_id`, `strategy_id`, active/inactive status, inactive reason, cash, equity, realized P&L, unrealized P&L, total P&L, daily P&L, return %, open positions, closed trades, win rate, average trade P&L, best trade, worst trade, invalid OOS count, and last update.

`AI_SHADOW` remains visible through the explicit card instantiation and inactive reasons are displayed whenever a wallet is inactive and `inactive_reason` exists.

### Same daily report structure for each engine

**Mostly pass.** `EngineDailyReportsSection` renders three `EngineDailyReportCard` instances for `engine`, `deterministic_shadow`, and `ai_shadow`. The card has a same-structure display including session date, closed trades, wins/losses, win rate, realized/unrealized/total P&L, return %, average/best/worst trade P&L, current open positions, EOD flatten count, invalid OOS count, and last trade time. Wallets with no current-session activity show `No trades for this session`.

Small gap: the requested field list says “trades opened”; the current card uses current open positions and closed trades but does not label a separate “trades opened” count.

### Same analytics structure for each engine

**Pass with persistence caveat.** The frontend renders three analytics cards under `Engine Decision Analytics` and uses separate branches for `engine`, `deterministic_shadow`, and `ai_shadow`, so it does not silently reuse ENGINE analytics for shadows. The backend endpoint returns three analytics objects.

ENGINE analytics include candidate funnel, score distribution, rejection data, catalyst data, and performance from the existing analytics helper. Deterministic shadow analytics include `WOULD_ENTER`, `WATCH`, `WOULD_REJECT`, no-decision count, average score, shadow positions/trades, and top rejection reasons. AI shadow analytics include enabled state, `WOULD_ENTER`/`WATCH`/`WOULD_REJECT`, disabled/error/not-selected counts, AI positions/trades, `no_paid_ai_calls`, and an inactive reason when LLM shadow is disabled.

Caveat: these analytics are calculated from `last_tick_candidates` in simulator state, not from Postgres. That is acceptable for dashboard display, but not enough for DB-audit/future-analysis readiness.

### One canonical Trading Activity section

**Pass.** The main flow keeps a single `Trading Activity` section with `WalletExplorer`. The explorer defaults to `all`, supports wallet filtering, and uses wallet-aware positions/trades fetches.

### Wallet comparison/ranking

**Pass.** `Engine Performance Today` renders per-wallet comparison cards from `/api/paper/wallets/performance`. The reviewed tests confirm ranking by OOS-excluded adjusted total P&L.

### Legacy ENGINE diagnostics

**Pass.** Legacy ENGINE analytics/journal/history are moved under `Advanced diagnostics — not part of the normal three-engine daily report` and inside a collapsed `<details>` block at the bottom of the main tab.

## 3. DB persistence audit findings

**Needs follow-up.** G1B-H7 improves `/api/audit/persistence/deep-status`, but it still falls short of the requested audit contract.

### Added or present

- Candidate totals, extras_json count, extras_json coverage %, created_at min/max, count by action, rejection reason, and marketdata source are present.
- Outcome totals, status/horizon/source counts, resolved_at min/max, candidate-to-outcome joinable rows, distinct candidates with outcomes, candidates with at least five horizons, and missing/pending/error count by horizon are present.
- Trade totals, wallet/strategy breakdowns, missing wallet/strategy counts, opened_at/closed_at missing counts, exit-reason distribution, invalid OOS count, and created_at min/max are present.
- Field-family coverage probes were added for marketdata, catalyst/news, Reddit, earnings, insider, market regime/trend, deterministic shadow, AI shadow, and AI shadow disabled/error states.
- Per-engine trade-count readiness fields were added.
- Timestamp metadata says timestamps are stored as UTC `TIMESTAMPTZ` and NY session date is derivable via `session.session_date_for(...)`.

### Missing or incomplete

- The requested **candidate `tick_ts` min/max/missing count** is not implemented. The endpoint reports `missing_tick_id`, not `tick_ts` min/max/missing.
- Candidate count by **path/source** is not explicitly implemented except `by_marketdata_source`; this does not fully satisfy source/path analysis.
- Candidate count by **catalyst type** is not explicitly implemented.
- Candidate count by **engine/decision type** is not explicitly implemented in the candidate audit. Field-family coverage probes exist, but they are not grouped candidate counts by engine/decision type.
- Trade audit does not explicitly report missing `entry_time` count or missing `exit_time` count for closed trades; it reports missing `opened_at` and `closed_at` for journal events.
- NY session date is documented as derivable but not stored or grouped in the returned audit payload.
- Timestamp integrity does not include comprehensive null critical timestamp anomalies beyond `created_at` and opened/closed journal fields.
- The endpoint reports field-family coverage by sampling the most recent 5,000 extras rows. That is useful and honest when documented, but it is not full-table coverage.
- `deterministic_shadow_data_separable` and `ai_shadow_data_separable` are returned as unconditional `True`; they should be backed by observed persisted grouping fields/counts, or return a clear unavailable/not-collected state when no persisted rows support them.

## 4. Regression findings

**No blocking regression found in reviewed code/tests.**

- H3 regular-session entry gate is still covered by a weekend block test.
- H5 invalid OOS exclusion is covered by regression tests for realized P&L and wallet ranking.
- H4/H5 wallet-scoped performance and wallet-tagged activity are still present through `/api/paper/wallets/performance`, `WalletExplorer`, and wallet/strategy table headers.
- The main dashboard no longer renders a primary combined cash/equity account metric.
- I did not see changes to scoring thresholds, normal ENGINE entry/exit logic, TP/SL/max-hold logic, or H3 entry-gate production code in the latest patch diff.

## 5. Safety findings

**Pass.** The latest diff adds no broker/live-order implementation and no paid AI call implementation. The only new AI-related text is dashboard/API metadata: `no_paid_ai_calls`, the local/free provider note, and the inactive reason `LLM_SHADOW_ENABLED=false`.

The safety scan of the latest patch found only comments/tests/provider-note strings and no new `place_order`, `submit_order`, `execute_order`, `send_order`, broker integration, or paid-provider client invocation.

## 6. Evidence

- Latest reviewed commit: `0a36dee Redesign dashboard for three engine accounts`.
- Latest patch files: `backend/api/audit.py`, `backend/api/paper.py`, `backend/tests/test_phase_g1b_h7.py`, and `frontend/dashboard/app/page.tsx`.
- `EngineAccountCard` implements the required per-account fields and inactive reason display.
- `EngineAccountsSection` renders exactly three cards for `engine`, `deterministic_shadow`, and `ai_shadow`.
- `EngineDailyReportsSection` renders three same-structure daily report cards.
- `EngineDecisionAnalyticsSection` renders three analytics cards with distinct engine/shadow/AI branches.
- The main dashboard order includes Engine Performance Today, Engine Accounts, Simulator Status, Controls, Engine Daily Reports, Trading Activity, Engine Decision Analytics, then advanced legacy diagnostics.
- `/api/paper/wallets/analytics` returns three per-engine analytics objects and does not call a paid AI provider.
- `/api/audit/persistence/deep-status` includes added field-family coverage and per-engine trade readiness, but still lacks several required audit dimensions.

## 7. Tests reviewed

The new `backend/tests/test_phase_g1b_h7.py` suite covers:

- no primary aggregate account section strings;
- three account cards;
- account-card required fields;
- AI shadow inactive reason surface;
- three daily-report panels and no-trades state;
- three analytics endpoint objects;
- no paid AI calls label;
- deterministic shadow decision-count fields;
- shadow/AI analytics not using the engine branch;
- Trading Activity wallet/strategy columns;
- wallet comparison excluding OOS trades;
- legacy diagnostics under collapsed details;
- deep-status field-family coverage;
- deep-status per-engine separability fields;
- deep-status outcome joinability by horizon;
- deep-status candidate created_at and missing tick-id fields;
- deep-status trade wallet/strategy completeness;
- H3 weekend gate;
- H5 OOS exclusion;
- no forbidden broker tokens in the new analytics endpoint;
- no paid-provider client invocation in the new analytics endpoint.

I ran:

```bash
pytest backend/tests/test_phase_g1b_h7.py -q
```

Result: **26 passed, 1 warning**.

## 8. Runtime evidence reviewed

No Claude runtime evidence was available in the repo/context I reviewed. I did not review a deployed dashboard screenshot, browser proof, deployed commit evidence from the VM, backend health output, frontend build output, or live `/api/audit/persistence/deep-status` JSON from the deployed VM.

## 9. Freeze-readiness judgment

**Not freeze-ready yet.** The dashboard shape is close enough for product review, but the DB audit/readiness portion remains incomplete. The most important missing items are candidate `tick_ts` audit fields, explicit candidate source/path/catalyst/engine grouping, stronger timestamp/session-date grouping, and making per-engine separability evidence based on persisted data rather than unconditional booleans or runtime memory.

## 10. Required follow-up patches

1. Remove or refactor the dead aggregate `WalletDailyAnalytics` component so no source path still contains an `All Wallets — Daily Analytics` aggregate across engine + shadows.
2. Extend `/api/audit/persistence/deep-status` to report candidate `tick_ts` min/max/missing count if persisted, or explicitly report it as not persisted/not collected.
3. Add candidate count by persisted path/source, action, rejection reason, catalyst type, and engine/decision type; if a dimension is not persisted, report `not_collected` rather than implying coverage.
4. Add explicit trade missing `entry_time` and closed-trade missing `exit_time` audits, or explicitly map/report how `opened_at` and `closed_at` satisfy those fields.
5. Add NY-session-date grouping for candidates/outcomes/trades, using either stored NY session date or explicit derivation in the endpoint payload.
6. Replace unconditional `deterministic_shadow_data_separable: True` and `ai_shadow_data_separable: True` with evidence-based checks from persisted data.
7. Persist or auditably expose shadow/AI decision analytics from Postgres rather than relying only on `last_tick_candidates` in memory.
8. Add tests for the missing audit fields above, especially `tick_ts` min/max/missing, source/path counts, catalyst-type counts, engine/decision-type counts, NY-session grouping, and evidence-based per-engine separability.
