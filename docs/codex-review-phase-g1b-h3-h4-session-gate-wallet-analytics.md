# Codex Review — Phase G1B-H3 + G1B-H4 Session Gate and Wallet Analytics

**Final reviewed HEAD:** `b76bb79` (`Add wallet-scoped performance analytics`)  
**H3 implementation commit identified:** `a2a1480` (`Block out-of-session fake entries (Phase G1B-H3)`)  
**H4 implementation commit identified:** `b76bb79` (`Add wallet-scoped performance analytics`)  
**Combined diff reviewed:** `a2a1480^..b76bb79`  
**Verdict:** **PASS WITH CAVEATS**

## 1. Executive summary

G1B-H3 and G1B-H4 are broadly implemented and appear safe within the fake-money/paper-simulation boundary. The H3 session gate defaults to regular US equity session only, blocks the engine branch chain before any engine `enter_position()` calls, blocks deterministic and AI shadow entries through the shadow-wallet tick path, and adds remediation for pre-existing out-of-session positions across engine and shadow wallets. The API and dashboard expose session-gate status, blocked-entry reason, invalid/out-of-session counts, and warnings for positions that need remediation.

G1B-H4 adds `/api/paper/wallets/performance`, returns all three wallets, adds top-level dashboard wallet comparison, and adds a selected-wallet/aggregate daily analytics section. The dashboard keeps global market context separate from wallet-specific sections.

The caveats are not blockers for deploying the fake-money review surface, but they should be fixed or explicitly accepted before freeze sign-off:

1. **Invalid out-of-session trades are counted inside normal realized P&L, win/loss counts, win rate, average/best/worst trade P&L, total P&L, and ranking.** They are separately counted as `invalid_out_of_session_count`, but the normal metrics are not excluded or visibly adjusted in the API. This is the main freeze caveat for H4 metrics.
2. **Runtime evidence is mostly not committed/reviewable.** Code and unit tests pass, but I did not find committed evidence for deployed commit health, browser verification, market-closed tick behavior, old TSLA-like remediation on the VM, or News Feed scrollbar regression.
3. **H4 dashboard tests are mostly source-string/API unit checks rather than browser/render tests.** They help guard structure but do not prove layout behavior in a running browser.

## 2. H3 findings — universal regular-session entry gate

### 2.1 Default regular-session gate

**Pass.** Defaults are correctly conservative:

- `PAPER_REGULAR_SESSION_ONLY=True`.
- `PAPER_ALLOW_EXTENDED_HOURS_ENTRIES=False`.
- `LLM_SHADOW_ENABLED=False` remains default.

The shared session helper treats only Monday-Friday, 09:30 inclusive through 16:00 exclusive America/New_York as regular session. Weekends, pre-open, and post-close produce stable block reasons.

### 2.2 Gate coverage across fake-entry paths

**Pass.** The engine computes `_eod.entries_blocked()` once immediately before the entry branch chain. If blocked, it marks the candidate ineligible, stamps the action and rejection reason, and skips the branch chain. That protects:

- catalyst entry;
- no-catalyst momentum entry;
- market-mover no-catalyst entry;
- legacy momentum entry;
- any other entry branch inside the same branch chain before the `enter_position()` calls.

The shadow-wallet tick path separately calls `_eod.entries_blocked()` and processes deterministic and AI shadow entries only when entries are not blocked. Because AI shadow entries are processed inside the same `if not _entries_blocked` block, a later mocked/enabled LLM `WOULD_ENTER` cannot open a shadow position outside session through this path.

### 2.3 Blocked-entry telemetry

**Pass.** Blocked engine candidates remain in `last_candidates` with stable `action` and `rejection_reason` values from the session helper (`market_closed_weekend`, `market_preopen`, or `market_postclose`). The H3 change blocks after scoring/enrichment and before entry action, so it does not appear to change score thresholds. Normal in-session branches remain reachable when `_eod.entries_blocked()` returns false.

One minor naming note: the implementation uses the precise market-state reason directly rather than a generic `session_entry_blocked`, which is acceptable and more auditable.

### 2.4 Existing out-of-session position remediation

**Pass.** The H3 implementation detects entry timestamps outside regular session using `position_entry_is_out_of_session()` and remediates them with `invalid_out_of_session_entry_flatten`. This is present for:

- engine positions in `simulator.py`;
- deterministic shadow positions in `shadow_wallets.py`;
- AI shadow positions in `shadow_wallets.py`.

If no exit price is available, the code emits visible warnings such as `missing_exit_price_invalid_session` rather than silently leaving the position as normal. The API annotates still-open out-of-session positions with `out_of_session: true`, `reason: invalid_out_of_session_open_position`, and `remediation: pending_flatten`.

### 2.5 H3 dashboard/API visibility

**Pass.** `/api/paper/wallets` exposes:

- `market_session_open`;
- `entries_allowed`;
- `entry_block_reason`;
- `out_of_session_open_positions`;
- `invalid_out_of_session_positions`.

The dashboard renders “Market closed — fake entries disabled” with the block reason and shows invalid/out-of-session warnings with wallet, strategy, symbol, entry time, and remediation details where available.

## 3. H4 findings — wallet-scoped analytics and engine comparison

### 3.1 Wallet performance API

**Pass with caveat.** `/api/paper/wallets/performance` exists and returns one object each for `engine`, `deterministic_shadow`, and `ai_shadow`. Fields include wallet identity, strategy identity, display name, status/inactive reason, session date, cash/equity/P&L metrics, return percent, open/closed counts, win/loss counts, win rate, average/best/worst trade P&L, invalid out-of-session count, EOD flatten count, last trade time, and last update time.

Unavailable values are generally `None`/`null`, for example `max_drawdown`, no-trade win rate, and no-trade average/best/worst trade P&L.

**Caveat:** invalid out-of-session flatten trades are counted in the normal `session_trades` list used for realized P&L, win/loss, win rate, average/best/worst trade P&L, total P&L, return percent, and best-wallet ranking. They are labeled separately by count, but not excluded from normal freeze metrics. This should be corrected or documented before freeze-readiness is treated as complete.

### 3.2 Engine comparison dashboard section

**Pass.** The dashboard adds a top-level `Engine Performance Today` section near the top of the Main Dashboard. It renders all wallet cards side by side, identifies the best wallet by total P&L, shows P&L, realized/unrealized P&L, return percent, open positions, closed trades, win rate, average trade P&L, inactive reason/status, and fake-wallet/paper/simulated wording.

### 3.3 Wallet filter scopes performance statistics

**Pass.** The new `WalletDailyAnalytics` section uses the selected wallet filter:

- `all` aggregates all three wallets and labels the result as aggregate across engine + shadows;
- `engine` filters to engine only;
- `deterministic_shadow` filters to deterministic shadow only;
- `ai_shadow` filters to AI shadow only.

This addresses the specific H4 blocking risk where bottom daily stats could remain ENGINE-only regardless of the selected wallet. The older generic `Analytics` section still remains engine-oriented, but the new H4 section is the wallet-scoped daily analytics surface and is clearly labeled.

### 3.4 Global vs wallet-scoped sections

**Pass.** Market readiness, monitoring, market regime, market trend, session readiness, candidates, universe, and market discovery remain global sections. Wallet-specific surfaces are separately labeled as Fake Wallets, Per-Wallet Positions & Trades, Engine Performance Today, and wallet-scoped Daily Analytics.

### 3.5 End-of-day/latest-session analytics

**Pass by code/tests.** The performance endpoint defaults to `latest_session_date_ny()` when `session_date` is absent or `latest`, and the session helper uses America/New_York session-date logic. Existing per-wallet trades endpoints also use `latest_session_date_ny()`/`session_date_for()` patterns. Unit tests cover latest-session default and explicit session filtering.

**Runtime caveat:** I did not find committed runtime evidence proving after-close/latest-session behavior on the deployed VM or browser dashboard.

### 3.6 Performance metrics and invalid trade handling

**Needs follow-up.** Invalid/out-of-session trades are labeled and counted separately, but they are still included in normal performance metrics. EOD flatten trades are counted/labeled and included in normal metrics, which is acceptable if intentional. Aggregate metrics in the dashboard sum one wallet object per wallet and do not double-count the same wallet. AI shadow inactive state is exposed; however, an inactive wallet with zero P&L can still be part of ranking by total P&L, which is not wrong but should be understood as “best among returned wallets,” not “best active strategy only.”

### 3.7 Dashboard clarity

**Pass.** The high-level dashboard flow is understandable:

1. global market/session context;
2. top-level wallet comparison;
3. account/fake-wallet summary;
4. per-wallet position/trade explorer;
5. wallet-scoped daily analytics;
6. global candidates/universe/analytics/journal sections.

Paper/fake-money/no-broker/no-real-orders wording remains visible.

## 4. Cross-impact findings

I did not find evidence that H4 broke H3. H4 adds a performance endpoint and dashboard analytics surfaces; it does not alter the H3 `entries_blocked()` helper, the engine pre-branch session gate, or shadow-wallet entry blocking. The combined diff does not change TP/SL/max-hold thresholds. The H3 entry gate is still applied before engine branch-specific `enter_position()` calls, and shadow wallets still block entries globally when session entries are blocked.

The primary cross-impact is metric semantics: H3 creates `invalid_out_of_session_entry_flatten` trades, while H4’s analytics count those trades in normal performance. That is an H4 analytics caveat, not an H3 gate/remediation failure.

## 5. Evidence

### Commits reviewed

- `a2a1480` — `Block out-of-session fake entries (Phase G1B-H3)`.
- `b76bb79` — `Add wallet-scoped performance analytics`.
- Final reviewed HEAD: `b76bb79`.
- Combined diff basis: `a2a1480^..b76bb79`.

### Code evidence

- Conservative defaults are present in `backend/core/config.py`: regular-session-only true, extended-hours entries false, LLM shadow disabled.
- Session helper reasons are stable and cover weekend, pre-open, and post-close.
- Engine session gate is applied before all engine entry paths.
- Shadow entries are skipped when `_eod.entries_blocked()` is true.
- Out-of-session remediation uses `invalid_out_of_session_entry_flatten` and emits missing-exit-price warnings.
- `/api/paper/wallets` exposes H3 session and invalid-position visibility.
- `/api/paper/wallets/performance` returns all three wallets and H4 metrics.
- Dashboard renders Market Session/Fake Wallet warnings, Engine Performance Today, and wallet-scoped Daily Analytics.

### Safety-boundary scan

I searched for new/changed broker/live/order-related terms and did not find new broker integration, live trading, real order placement, Alpaca, IBKR, Robinhood, `place_order`, `submit_order`, `execute_order`, or `send_order` implementation in the reviewed H3/H4 patch. Matches in the repo are existing safety tests, disclaimers, status booleans, and pre-existing LLM provider code. No paid AI call path was added by H3/H4; LLM shadow remains disabled by default.

## 6. Tests reviewed

### H3 test coverage

`backend/tests/test_phase_g1b_h3.py` covers:

- regular-session allowed behavior;
- weekend, pre-open, and post-close block reasons;
- extended-hours/regular-session config behavior;
- out-of-session remediation helpers;
- API/dashboard visibility checks;
- source-level guard that the simulator calls `entries_blocked()` before all entry paths;
- shadow-wallet session-blocking behavior;
- no forbidden broker/live/order tokens in the new session/remediation modules.

### H4 test coverage

`backend/tests/test_phase_g1b_h4.py` covers:

- performance API returns all three wallets;
- required fields are present;
- aggregate comparison/session-status fields are present;
- `session_date=latest` and default latest session behavior;
- explicit session-date filtering;
- total P&L equals realized plus unrealized;
- win-rate calculation;
- no-trade null win rate;
- dashboard source contains wallet performance types/fetch/component names;
- endpoint source avoids forbidden broker/live/order tokens;
- best-wallet ranking by total P&L.

### Gaps in tests

- No test proves invalid out-of-session flatten trades are excluded from normal P&L/win-rate/ranking metrics; current implementation includes them.
- H4 dashboard tests are mostly source-string checks, not browser/render tests.
- I did not find direct tests proving global market sections are not filtered by wallet, although the code structure supports that.
- I did not find committed runtime/browser evidence for dashboard cards, wallet filter changing lower analytics, or News Feed scrollbar behavior.

## 7. Runtime evidence reviewed

I reviewed committed code and tests only. I did not find committed/reported runtime evidence for:

- deployed commit SHA on the VM;
- backend health response after deploy;
- frontend production build after deploy;
- browser screenshot showing wallet comparison section;
- all three wallet cards visible in browser;
- wallet filter changing daily analytics in browser;
- market-closed tick not opening fake entries on VM;
- old TSLA-like out-of-session position remediated/flagged on VM;
- News Feed layout still lacking horizontal scrollbar.

Therefore, the implementation passes based on code and unit tests, but runtime evidence is still recommended before freeze.

## 8. Freeze-readiness judgment

**PASS WITH CAVEATS.** H3 is freeze-ready from code/test review. H4 is functionally implemented and safe within fake-money boundaries, but freeze metrics should not be considered final until invalid out-of-session flatten trades are either excluded from normal performance metrics/ranking or the API/dashboard clearly expose separate normal-vs-invalid-adjusted metrics. Runtime evidence should also be captured for the deployed VM and dashboard.

## 9. Required follow-up patches, if any

1. **H4 metrics semantics:** Update `/api/paper/wallets/performance` so trades with `exit_reason == "invalid_out_of_session_entry_flatten"` are excluded from normal realized P&L, win/loss, win rate, average/best/worst trade P&L, return percent, total P&L, and best-wallet ranking; or add clearly named adjusted/unadjusted fields and make the dashboard use adjusted normal-performance metrics for freeze reporting.
2. **H4 tests:** Add tests for invalid-trade exclusion/labeling in wallet performance metrics and ranking.
3. **Runtime evidence:** Commit or report VM evidence for deployed commit, backend health, frontend build/browser, wallet comparison visibility, wallet filter behavior, market-closed tick no-entry behavior, old out-of-session remediation, and News Feed no-horizontal-scroll regression.
4. **Optional clarity:** If inactive AI_SHADOW should not compete for “best wallet,” add an `active_only` best/ranking field or label the current ranking as “all wallets including inactive.”
