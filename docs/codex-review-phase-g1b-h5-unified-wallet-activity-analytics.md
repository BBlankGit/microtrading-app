# Codex Review — Phase G1B-H5 Unified Wallet Activity & Analytics

**Review date:** 2026-06-13  
**Reviewed commit:** `30199f0` (`Unify wallet trading activity and analytics`)  
**Scope:** latest G1B-H5 patch only (`backend/api/paper.py`, `backend/tests/test_phase_g1b_h5.py`, `frontend/dashboard/app/page.tsx`)  
**Verdict:** **PASS WITH CAVEATS**

## 1. Executive summary

G1B-H5 substantially addresses the three remaining G1B-H3/G1B-H4 caveats:

1. The main dashboard no longer renders the legacy standalone Engine-only `Open Positions — ENGINE` / `Closed Trades — ENGINE` tables. It now renders one canonical wallet-aware **Trading Activity** section, with the old `PositionsTable`/`TradesTable` component definitions left unused.
2. The wallet filter defaults to **All wallets**, offers `All wallets`, `ENGINE`, `DETERMINISTIC_SHADOW`, and `AI_SHADOW`, and drives both the unified trading-activity rows and the new wallet-scoped daily analytics section.
3. The `/api/paper/wallets/performance` endpoint now excludes `exit_reason == "invalid_out_of_session_entry_flatten"` trades from normal performance metrics and rankings while exposing raw/audit P&L fields separately.

I did not find any application-code changes to scoring thresholds, normal entry/exit logic, TP/SL/max-hold logic, broker/live-order paths, or paid AI/LLM behavior in the reviewed patch.

**Caveats:**

- The bottom Engine-only analytics and Engine-only journal report remain on the dashboard, but they are now explicitly labeled as Engine-only and appear below the new wallet-scoped daily analytics. This is acceptable for H5 under the stated acceptable solution, but it should not be treated as the main daily wallet report.
- The invalid out-of-session API audit fields include counts and raw P&L fields, but I did not find an explicit `invalid_out_of_session_trades` list in `/api/paper/wallets/performance`. The invalid trades remain visible through the closed-trades feed by raw `exit_reason`, but the requested named audit list is not present.
- I did not find committed runtime evidence from Claude for the VM deployment, browser screenshot, deployed commit health, or live wallet-filter interaction. This review is therefore based on code inspection and local tests/build only.

## 2. Findings

### Finding 1 — Duplicate Engine-only position/trade UI removed from rendered dashboard — **Pass**

The dashboard now renders a single wallet-aware **Trading Activity** section and passes the shared `walletId` state into `WalletExplorer`. The old legacy Engine-only `PositionsTable` and `TradesTable` components remain in source for compatibility/unused code, but I found no rendered `<PositionsTable>` or `<TradesTable>` usage in the current page.

The new H5 tests also assert that the old standalone Engine-only section marker comments are absent from `page.tsx` and that the unified `Trading Activity` section exists.

### Finding 2 — Unified wallet-aware Positions & Trades section — **Pass**

`WalletExplorer` provides the canonical activity UI. It defaults its internal wallet state to `"all"`, maps the wallet options to `All wallets`, `ENGINE`, `DETERMINISTIC_SHADOW`, and `AI_SHADOW`, and renders dynamic headings `Open Positions — {filterLabel}` and `Closed Trades — {filterLabel}`.

Open-position rows display wallet, strategy, symbol, entry price, current price, shares, cost, unrealized P&L/P&L %, catalyst, entry time, plus out-of-session/stale labels when applicable.

Closed-trade rows display wallet, strategy, symbol, entry, exit, P&L, P&L %, exit reason, hold time, catalyst, and close time. Invalid out-of-session trades are visible through their `exit_reason`, but there is no extra badge analogous to the open-position `OOS` badge.

### Finding 3 — Wallet filter drives activity rows and daily analytics — **Pass**

The dashboard keeps one top-level `walletId` state initialized to `"all"`. `WalletExplorer` uses it to filter positions and latest-session trades. `WalletDailyAnalytics` uses the same `walletId` to aggregate all wallets or select a single wallet. This addresses the H4 concern that the bottom daily report appeared silently Engine-only.

### Finding 4 — Latest-session closed trades use NY trading-session logic — **Pass**

The wallet trades endpoint supports `latest_session=true`, resolves the latest completed America/New_York session through `latest_session_date_ny()`, and filters trades using `session_date_for(exit_time or entry_time)`. This should preserve closed-trade visibility after market close and over weekends, avoiding UTC/Japan-date rollover behavior.

### Finding 5 — Bottom daily analytics / daily report no longer silently Engine-only — **Pass with caveat**

A new `WalletDailyAnalytics` section appears directly below Trading Activity and is driven by the selected wallet filter. It displays total P&L, realized P&L, unrealized P&L, closed trades, win rate, best trade, worst trade, invalid out-of-session count warning, raw P&L including OOS, and EOD flatten count.

The older `AnalyticsPanel` and journal report remain, but are now explicitly labeled **ENGINE Analytics** and **ENGINE Journal Report** with Engine-only explanatory subtitles. This meets the acceptable fallback in the review request, provided those legacy sections are not interpreted as the main wallet-scoped daily report.

### Finding 6 — Top wallet comparison remains visible and fake-money labeled — **Pass**

`EnginePerformanceSection` remains above the rest of the dashboard and renders all wallets returned by `/api/paper/wallets/performance`. Each wallet card displays total P&L, realized P&L, unrealized P&L, return %, open positions, closed trades, win rate, average trade, invalid out-of-session count/raw total when applicable, status/inactive reason, and a fake-wallet/paper/simulated label.

### Finding 7 — Invalid out-of-session trades excluded from normal metrics/rankings — **Pass with caveat**

The H5 backend splits session trades into valid vs. invalid out-of-session trades using `exit_reason == "invalid_out_of_session_entry_flatten"`. Normal metrics now use only valid trades for realized P&L, total P&L, return %, closed-trade count, wins/losses, win rate, average trade, best trade, worst trade, EOD flatten count, and wallet rankings. Raw/audit metrics expose count and P&L including invalid trades.

The caveat is that the requested `invalid_out_of_session_trades` audit list is not exposed by `/api/paper/wallets/performance`; only count and raw P&L fields are exposed there.

### Finding 8 — Wallet APIs support unified UI — **Pass**

The wallet activity APIs support no filter / all-wallet behavior and wallet-specific filters for Engine, deterministic shadow, and AI shadow. Engine rows are annotated with `wallet_id: "engine"` and `strategy_id: "engine"`, while shadow rows retain their wallet/strategy metadata. The UI calls these endpoints instead of using the legacy Engine-only dashboard `positions`/`trades` arrays for the main activity display.

### Finding 9 — Global vs wallet-specific dashboard separation — **Pass**

The H5 patch changes only the wallet activity/performance portions of the dashboard. Global market sections such as candidates, universe, market discovery, intelligence/news, readiness, and similar global panels remain separate and are not incorrectly filtered by wallet.

### Finding 10 — H3 session gate regression — **Pass based on patch scope and tests**

The reviewed patch does not modify the H3 session-gate implementation or simulator entry branches. The new H5 tests include a weekend `entries_blocked` regression check. Existing H3 behavior therefore appears preserved.

### Finding 11 — Safety boundary: no broker/live/real-order implementation added — **Pass**

The reviewed diff adds no broker SDK, live-trading integration, real-order path, or order-submission function implementation. Matches in the diff are test assertions, fake-money labels, or unchanged no-broker UI copy.

### Finding 12 — AI safety: no paid AI calls added; LLM remains disabled by default — **Pass**

The reviewed H5 diff does not add OpenAI, DeepSeek, Groq, Mistral, Gemini, Ollama, or other paid AI calls. It does not change `LLM_SHADOW_ENABLED` defaults or AI shadow gating.

### Finding 13 — Tests added for H5 behavior — **Pass with caveat**

The new `backend/tests/test_phase_g1b_h5.py` covers the main H5 requirements: duplicate legacy UI removal, unified section existence, default All-wallet filter, wallet-specific API filtering, wallet/strategy row tags, latest-session NY filtering, invalid OOS exclusion from normal metrics, raw/audit P&L exposure, adjusted ranking, Engine-only labels for legacy analytics/report sections, weekend session-gate regression, and safety-token checks.

Coverage caveat: the tests are mostly source/unit/API tests, not browser interaction tests. They do not verify an actual rendered DOM interaction in a browser, and they do not assert an explicit `invalid_out_of_session_trades` list because the endpoint does not expose one.

## 3. Evidence

### Reviewed patch files

- `backend/api/paper.py`
- `backend/tests/test_phase_g1b_h5.py`
- `frontend/dashboard/app/page.tsx`

### Code evidence summary

- `frontend/dashboard/app/page.tsx` defines `WALLET_OPTIONS` with `all`, `engine`, `deterministic_shadow`, and `ai_shadow`.
- `frontend/dashboard/app/page.tsx` initializes `WalletExplorer` to `useState<string>("all")`.
- `frontend/dashboard/app/page.tsx` renders one **Trading Activity** section containing `WalletExplorer` and labels it as all fake wallets/latest US trading session/filter-by-wallet.
- `frontend/dashboard/app/page.tsx` renders dynamic `Open Positions — {filterLabel}` and `Closed Trades — {filterLabel}` tables with wallet/strategy columns.
- `frontend/dashboard/app/page.tsx` renders `WalletDailyAnalytics` from the same selected `walletId` used by `WalletExplorer`.
- `frontend/dashboard/app/page.tsx` explicitly labels remaining legacy analytics/report sections as **ENGINE Analytics** and **ENGINE Journal Report**.
- `backend/api/paper.py` filters `/api/paper/wallets/trades` by latest NY session when `latest_session=true`.
- `backend/api/paper.py` excludes invalid OOS trades from normal wallet-performance metrics and rankings while exposing raw/audit P&L fields.
- `backend/tests/test_phase_g1b_h5.py` validates the above behavior through 19 passing tests.

### Safety/equivalence evidence

The latest commit changed only:

```text
backend/api/paper.py
backend/tests/test_phase_g1b_h5.py
frontend/dashboard/app/page.tsx
```

Therefore, no strategy modules, simulator entry/exit branches, TP/SL/max-hold implementation files, runtime config defaults, or LLM provider files were modified in H5.

## 4. Tests reviewed

I ran and reviewed the new targeted H5 test suite:

```bash
cd backend && pytest -q tests/test_phase_g1b_h5.py
```

Result:

```text
19 passed, 1 warning in 0.35s
```

I also ran the dashboard production build:

```bash
cd frontend/dashboard && npm run build
```

Result: build completed successfully. npm emitted an `Unknown env config "http-proxy"` warning, but Next.js compiled, type-checked, generated static pages, and exited with status 0.

I additionally ran diff/static review commands:

```bash
git show --stat --oneline HEAD
git show --name-only --format='' HEAD
git diff HEAD^..HEAD -- frontend/dashboard/app/page.tsx backend/api/paper.py backend/tests/test_phase_g1b_h5.py
rg -n "function Wallet|Trading Activity|ENGINE Analytics|ENGINE Journal|Open Positions|Closed Trades|walletFilter|filterLabel|wallets/performance|wallets/positions|wallets/trades|Analytics" frontend/dashboard/app/page.tsx
rg -n "<PositionsTable|<TradesTable|dashboard\?\.positions|dashboard\?\.trades|positions=\{|trades=\{" frontend/dashboard/app/page.tsx
rg -n "interface WalletPerf|invalid_out_of_session_trades|raw_.*invalid|invalid_out_of_session" frontend/dashboard/app/page.tsx backend/api/paper.py backend/tests/test_phase_g1b_h5.py
git diff HEAD^..HEAD -- . | rg -n "broker|live_trading|real_order|Alpaca|IBKR|Robinhood|place_order|submit_order|execute_order|send_order|OpenAI|DeepSeek|Groq|Mistral|Gemini|Ollama|LLM_SHADOW|score_threshold|take_profit|stop_loss|max_hold" -i
```

## 5. Runtime evidence reviewed

No committed or otherwise provided Claude runtime evidence was found for this H5 patch. Specifically, I did not find reviewable artifacts for:

- deployed VM commit SHA;
- backend health after deployment;
- live dashboard screenshot/browser evidence;
- evidence that only one canonical Positions & Trades / Trading Activity section appears in the deployed UI;
- evidence that selecting each wallet changes rows and daily analytics in the deployed browser;
- runtime proof that invalid out-of-session metrics are excluded/separated on the deployed VM;
- runtime proof that H3 out-of-session entry gates still block on the deployed VM.

Because no runtime evidence was available in the repository, the verdict is based on local code inspection, targeted backend tests, and frontend production build.

## 6. Freeze-readiness judgment

**Judgment: PASS WITH CAVEATS for fake-money freeze-readiness.**

G1B-H5 fixes the material source-level blockers from H3/H4: duplicate Engine-only activity UI is removed from the rendered dashboard, the canonical activity section and daily analytics are wallet-aware with an All-wallet default, and invalid out-of-session trades are excluded from normal wallet performance metrics/rankings.

The implementation remains within fake-money / paper simulation boundaries. I found no new broker integration, no live trading, no real orders, no real-money execution, no scoring-threshold changes, no normal Engine entry/exit changes, no TP/SL/max-hold changes, and no paid AI/LLM calls in the reviewed patch.

The freeze caveats are documentation/runtime completeness rather than source-level blockers:

1. Attach or report VM/runtime evidence before relying on the deployed dashboard for freeze monitoring.
2. Consider adding an explicit `invalid_out_of_session_trades` list to `/api/paper/wallets/performance` for easier audit parity with the requested contract.
3. Consider adding a small visual badge for invalid OOS closed-trade rows, not just the raw `exit_reason` text.

## 7. Required follow-up patches, if any

No blocking follow-up patch is required before fake-money monitoring, assuming runtime evidence confirms the deployed UI matches the reviewed source.

Recommended follow-ups:

1. **Runtime evidence artifact:** provide deployed commit, backend health, frontend build/browser screenshot, All-wallet default screenshot, per-wallet filter screenshots or logs, and invalid-OOS metric separation evidence.
2. **Audit field completion:** add `invalid_out_of_session_trades` to `/api/paper/wallets/performance` if the freeze contract requires that exact field.
3. **Closed-trade OOS label:** add an explicit `OOS excluded` badge to invalid out-of-session closed-trade rows for parity with open-position OOS warnings.
4. **Browser-level regression test:** add a Playwright or React Testing Library test that asserts only one rendered trading-activity section exists and that wallet selection changes both rows and daily analytics labels.
