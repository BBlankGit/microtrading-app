# Codex Review — Phase G1B-H1 Wallet Dashboard, EOD Flatten, Outcome Audit, and News Layout

Review target: latest G1B-H1 patch at `HEAD` (`f9154ad`, `Add wallet dashboard visibility and EOD review fixes`).

Scope: reviewed only the latest G1B-H1 patch (`HEAD~1..HEAD`). No application code was modified by this review.

## Verdict: YELLOW / NEEDS FOLLOW-UP

## 1. Executive summary

G1B-H1 materially improves the G1B yellow areas: the backend now exposes all three fake wallets, the dashboard renders all three wallet cards including inactive `AI_SHADOW`, per-wallet open-position and latest-session closed-trade views were added, outcome rows now carry a `source`, high/low outcome limits are documented as unavailable instead of fabricated, and the News table was restructured to avoid the previous normal-desktop horizontal scroll issue.

However, I would not freeze this as a full PASS yet. The patch still leaves several acceptance gaps:

1. **EOD flatten is not robust if the simulator does not tick at/after 16:00 ET on the same NY calendar day.** `flatten_due()` only returns true from the configured close offset through the end of that NY date; by the next morning it returns false, so stale overnight fake positions can survive if no tick ran after close.
2. **Per-wallet rows do not clearly display `strategy_id` in the dashboard tables.** API rows are tagged with `strategy_id`, but the new dashboard rows only show `wallet_id`.
3. **Wallet trade API filtering does not implement `strategy_id`.** It supports `wallet_id`, `session_date`, and `latest_session`, which is useful, but not the requested strategy filter.
4. **Candidate/outcome audit visibility is backend/API-only and partial.** The API exposes counts, coverage percent, high/low caveat, and resolver heartbeat, but the dashboard does not surface this audit panel, and the API does not return actual recent candidates with `extras_json` content.
5. **Tests are mostly source/unit checks and do not prove actual rendered dashboard behavior or runtime after-market behavior.** The News layout tests were skipped in this environment because the hard-coded frontend path did not match the repo path.

Given those issues, G1B-H1 is **safe for fake-money monitoring**, but it still needs follow-up before being considered freeze-complete against the full review checklist.

## 2. Findings

### Finding 1 — Three-wallet dashboard visibility mostly passes

**Status: Pass.**

The `/api/paper/wallets` endpoint always returns `engine`, `deterministic_shadow`, `ai_shadow`, and a three-element `wallets` list. The engine snapshot includes `wallet_id`, `strategy_id`, active status, cash/equity from simulator status, daily PnL, win rate, and last update time. Shadow snapshots are provided by `paper.shadow_wallets.snapshot()`.

The dashboard has a three-card `WalletsPanel` with explicit `ENGINE`, `DETERMINISTIC_SHADOW`, and `AI_SHADOW` cards. Each card shows active/inactive status, inactive reason, cash, equity, realized/unrealized/total/daily PnL, open position count, closed trade count, win rate, and last update time.

`AI_SHADOW` remains visible when inactive. The shadow-wallet status code marks it inactive with an LLM-disabled reason when `LLM_SHADOW_ENABLED` is false.

### Finding 2 — Wallet-specific APIs are useful but not complete

**Status: Pass with caveat.**

The patch adds:

- `GET /api/paper/wallets/positions`, optional `wallet_id` filter.
- `GET /api/paper/wallets/trades`, optional `wallet_id`, `session_date`, and `latest_session` filters.

Rows are tagged with `wallet_id` and `strategy_id`. Existing engine-only `/api/paper/positions` and `/api/paper/trades` remain unchanged.

Caveat: the requested `strategy_id` filter is not implemented on the trade/position endpoints. This is not fatal because each wallet currently maps to a strategy, but it is an acceptance gap if future strategy variants share a wallet.

### Finding 3 — Dashboard per-wallet open/closed views are present, but `strategy_id` is not displayed

**Status: Needs follow-up.**

The dashboard adds a wallet selector and separate Open Positions by Wallet and Latest-Session Closed Trades by Wallet tables. Both use the new wallet APIs and support all-wallets or wallet-specific filtering. The legacy engine-only open positions and closed trades sections remain in place.

However, the new table rows show `wallet_id` but not `strategy_id`, despite the requirement to clearly display both. Also, the new latest-session table does not implement a “latest 3 closed trades by default / Show all / Show fewer” behavior; that default behavior may still exist in the legacy engine-only `TradesTable`, but the new per-wallet section renders all latest-session trades.

### Finding 4 — After-market closed-position visibility mostly passes

**Status: Pass with caveats.**

The backend uses `America/New_York` helpers for session date resolution. During or after the NY open on a weekday, `latest_session_date_ny()` returns the current NY date; before the open it rolls back to the previous weekday; on weekends it rolls back to Friday. `session_date_for()` converts timestamps to NY session dates rather than UTC/Japan dates.

This means closed trades should remain visible after 16:00 ET through the next NY open when `latest_session=true` is used. The new per-wallet dashboard requests `latest_session=true`, so it should not go blank merely because the market is closed.

Caveat: holiday handling is explicitly not implemented; the session helper is weekday-only.

### Finding 5 — EOD flatten exists but has a material overnight robustness gap

**Status: Needs follow-up.**

Defaults are safe: overnight positions are disabled, EOD flatten is enabled, and a 10-minute entry cutoff is configured by default. The simulator short-circuits entries inside the cutoff window and engine/shadow wallets attempt `exit_reason="eod_flatten"` exits when flattening is due. Missing exit prices are surfaced as warnings rather than silently ignored.

Material gap: `flatten_due()` returns true only when `minutes_to_close <= offset` on a weekday. With the default `offset=0`, this is true at/after 16:00 ET on the same NY date, but it becomes false the next premarket because minutes to that day’s 16:00 close is positive. If the simulator misses all ticks after close, normal open fake positions can persist overnight without being flattened on the next tick. The acceptance criterion asks for no overnight normal positions when overnight holding is disabled; this implementation does not guarantee that.

The dashboard warning is also approximate: it uses only the NY hour and position count. It does not consult backend `PAPER_ALLOW_OVERNIGHT_POSITIONS`, `PAPER_EOD_FLATTEN_ENABLED`, or the 09:30/16:00 session window.

### Finding 6 — Outcome source and high/low caveat pass

**Status: Pass.**

The DB migration adds `source TEXT` to `paper_candidate_outcomes`. The resolver writes `marketdata_cache` for resolved cache rows, `missing_cache` for missing/invalid data, and `error` for resolver exceptions.

The resolver intentionally leaves `max_high_return_percent` and `max_low_return_percent` null because it only has a point-in-time cache price at resolution. The caveat is exposed via persistence status. This avoids fabricated high/low values.

### Finding 7 — Candidate/outcome audit visibility is partial

**Status: Needs follow-up.**

The audit endpoint exposes candidate totals, count with `extras_json`, coverage percentage, outcomes by status, outcomes by horizon/status, outcomes by source, recent extras examples, the high/low caveat, and resolver last-run status.

Gaps:

- It does not expose actual candidate rows with `extras_json` content, only recent examples with `has_extras`.
- I found no dashboard panel that calls `/api/audit/persistence/status` or displays these audit counts/caveats.
- Resolver last-run is exposed, but no richer recent audit status or recent resolver error list is surfaced.

### Finding 8 — News Feed / News-Catalysts layout likely passes

**Status: Pass with test caveat.**

The News table was reworked to remove the local horizontal scroll wrapper, use `table-fixed`, merge several columns into a Signal column, drop the inactive AI Analysis column, and wrap/truncate long text with title/tooltips/details. This is directionally the right fix for normal desktop widths.

Caveat: runtime browser verification was not provided in the repo, and the included News layout tests skipped in this environment because their helper only checks hard-coded paths outside `/workspace/microtrading-app`.

### Finding 9 — Engine behavior preservation mostly passes

**Status: Pass with caveat.**

I did not find scoring threshold changes, TP/SL threshold changes, or broker/live execution changes in the latest patch. The only normal engine entry-path mutation I found is the explicit EOD entry cutoff wrapper, which was in scope. Shadow-wallet processing remains in separate ledgers and does not intentionally mutate the engine account.

Caveat: the EOD cutoff sets `candidate["eligible"]`, `candidate["action"]`, and `candidate["rejection_reason"]` during the per-candidate engine path. That is expected for the cutoff, but it is still a candidate-surface behavior change during the cutoff window.

### Finding 10 — AI/LLM safety passes

**Status: Pass.**

`LLM_SHADOW_ENABLED` remains false by default, `AI_SHADOW` is inactive when LLM shadow is disabled, and the latest patch does not add OpenAI, DeepSeek, Groq, Mistral, Gemini, or Ollama calls. The AI shadow wallet only acts when the existing candidate LLM decision says `WOULD_ENTER` and LLM shadow is enabled.

### Finding 11 — Safety boundary passes

**Status: Pass.**

The reviewed patch is still fake-money/paper simulation only. I did not find new broker integration, live trading, real-order placement, real-money execution, Alpaca, IBKR, Robinhood, or order-placement code in the latest patch. Existing disclaimer text references “no broker/no real orders” but does not implement broker functionality.

## 3. Evidence

### Changed files in latest G1B-H1 patch

`git diff --name-only HEAD~1..HEAD` showed these files changed:

- `backend/api/paper.py`
- `backend/core/config.py`
- `backend/paper/db.py`
- `backend/paper/eod.py`
- `backend/paper/outcome_resolver.py`
- `backend/paper/session.py`
- `backend/paper/shadow_wallets.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase_g1b_h1.py`
- `frontend/dashboard/app/page.tsx`

### Backend/API evidence

- `/api/paper/wallets` returns `engine`, `deterministic_shadow`, `ai_shadow`, `shadow_wallets_enabled`, `llm_enabled`, and a three-element `wallets` list.
- `/api/paper/wallets/positions` returns engine/shadow open positions and tags rows with `wallet_id` and `strategy_id`.
- `/api/paper/wallets/trades` returns engine/shadow closed trades and supports `wallet_id`, `session_date`, and `latest_session`.
- The legacy `/api/paper/positions` and `/api/paper/trades` endpoints remain engine-only and unchanged in shape.
- EOD defaults are in settings: overnight false, EOD flatten true, entry cutoff 10 minutes.
- `paper.eod.entries_blocked()` blocks new entries inside the regular-session cutoff window.
- `paper.eod.flatten_due()` drives EOD flattening but only relative to the current same-day close.
- `paper.session` centralizes NY timezone session date handling.
- Outcome resolver writes `source` and exposes the high/low caveat and audit counts.

### Frontend/dashboard evidence

- The dashboard renders `WalletsPanel` with all three wallet cards.
- The wallet cards show active/inactive status, inactive reason, cash/equity, realized/unrealized/total/daily PnL, open/closed counts, win rate, and last update.
- `WalletExplorer` adds an all/engine/deterministic/AI wallet selector and fetches per-wallet positions/trades.
- Open and closed per-wallet tables display wallet, symbol, prices, PnL, reason/catalyst/times, but not `strategy_id`.
- The News table was restructured with `table-fixed`, narrower columns, merged Signal data, wrapped title/explanation cells, and no local `overflow-x-auto` wrapper in the reviewed block.

## 4. Tests reviewed

The patch adds `backend/tests/test_phase_g1b_h1.py`, covering:

- `/api/paper/wallets` returns three wallets.
- `AI_SHADOW` remains visible while inactive.
- Wallet snapshot summary fields exist.
- Wallet-specific positions/trades endpoints respond and tag engine rows.
- NY session helper behavior for intraday, after-hours, weekend, and premarket cases.
- Latest-session trade filtering by NY session date when a `session_date` is supplied.
- EOD cutoff/default helper behavior.
- Shadow wallet EOD flatten success and missing-price warning.
- Persistence status response shape.
- Outcome resolver source string presence and migration source column.
- Legacy endpoint backward compatibility.
- Source-level engine-branch sanity checks.
- Best-effort News layout source checks.
- AST-level guard against forbidden broker/live imports in new modules.

## 5. Runtime evidence reviewed

I did not find committed screenshot/runtime evidence from Claude or another runner showing:

- actual rendered dashboard with all three wallet cards;
- `AI_SHADOW` visible inactive in a browser;
- per-wallet open/closed sections working in browser;
- closed positions visible after market close in a live after-hours run;
- no normal open positions after close, or warning banner visible when flatten could not run;
- News feed no horizontal scrollbar at desktop width;
- backend health OK;
- frontend build OK.

I ran the targeted backend test file locally. It passed, with two skipped News source tests.

## 6. Freeze-readiness judgment

**YELLOW / NEEDS FOLLOW-UP.**

G1B-H1 is safe within the fake-money/no-broker/no-real-order boundaries and closes many of the visibility gaps from G1B. It is not freeze-complete because EOD flattening does not guarantee no overnight fake positions if no same-day post-close tick occurs, strategy ID is not visible/filterable enough, candidate/outcome audit visibility is not actually present on the dashboard, and runtime/browser evidence is missing.

## 7. Required follow-up patches

1. **Make EOD flatten robust across missed post-close ticks.** Track each open position’s NY session date and flatten any prior-session normal position when overnight holding is disabled, even if the next tick occurs the following premarket/open.
2. **Add `strategy_id` filtering and display.** Support `strategy_id` query filtering on wallet position/trade APIs, and add `strategy_id` columns or detail rows in the per-wallet dashboard tables.
3. **Add a dashboard audit panel.** Surface candidate totals, `extras_json` coverage, recent candidate audit status, outcome counts by horizon/status/source, high/low caveat, and resolver last-run status in the dashboard.
4. **Expose recent candidate examples with bounded `extras_json`.** The audit API should return a small, sanitized sample of recent candidates with `extras_json` so coverage can be inspected without querying the DB directly.
5. **Strengthen tests.** Add tests for missed-post-close EOD flatten on the next day, `strategy_id` filters/display, dashboard audit data mapping, and actual frontend path/source checks that do not skip in the repo layout.
6. **Add runtime evidence.** Provide a browser screenshot or Playwright-style evidence for the wallet cards/per-wallet tables/News layout, backend health, frontend build, and after-market/latest-session behavior.
