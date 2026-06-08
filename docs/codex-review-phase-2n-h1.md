# Codex Review — Phase 2N-H1 Trading-Day Scoped Daily Loss Guard

Review scope: latest Phase 2N-H1 patch only (`604472d Make daily loss guard trading-day scoped`).

## Critical issues

1. **Dashboard does not yet show the trading date or daily baseline.**
   - The backend status payload now includes `trading_date`, `daily_start_equity`, and `current_equity` in `daily_loss_guard`, and readiness copies those fields into the readiness check details.
   - The React dashboard still renders only guard status, daily P&L, threshold, and reason. It does not render the trading date, baseline equity, or current equity, and its `DailyLossGuard` TypeScript interface was not extended with those fields.
   - This means the dashboard does not yet satisfy the Phase 2N-H1 requirement that monitoring/readiness/dashboard truthfully show daily P&L / trading date / baseline.

2. **The first tick after a New York date rollover can reset the baseline after processing exits.**
   - `run_tick()` fetches prices, then enters the locked processing section, processes exits first, computes momentum counts, and only then performs the NY trading-date baseline rollover.
   - If an overnight/open position exits on the first tick of a new NY date, that exit is applied before `daily_start_equity` is reset. The new daily baseline can therefore include the result of the first current-day exit, making the guard show zero or understated daily P&L for that tick.
   - This can mask current-day first-tick losses and can allow entries later in the same tick even though the trading-day loss threshold should already be breached.
   - The guard should reset the NY-date baseline before evaluating exits/entries for that tick, or otherwise explicitly snapshot the new-day baseline before any current-day account mutations.

3. **Monitoring/status can show a stale trading date until a simulator tick runs.**
   - `daily_baseline_date` is initialized at import/reset and rolled forward inside `run_tick()` only.
   - `get_status()` and `/api/monitoring/status` call the risk guard directly without first ensuring the account baseline date matches the current America/New_York date.
   - If the process crosses midnight New York time while the simulator is stopped, paused, or delayed before the next tick, status/readiness/monitoring can temporarily report the prior NY trading date and prior baseline, which is not fully truthful for current-day monitoring.

## Non-blocking issues

1. **Timezone fallback is approximate.**
   - `_ny_trading_date()` correctly uses `zoneinfo.ZoneInfo("America/New_York")` in the normal path.
   - Its fallback uses a fixed UTC-4 offset, which is incorrect during standard time. This is low risk in supported Python environments with `zoneinfo`, but the fallback is not truly America/New_York.

2. **Test duplication / minor cleanup.**
   - `test_prior_day_profit_does_not_mask_today_loss()` asserts `result["triggered"] is True` twice.
   - `test_can_enter_allows_same_symbol_after_exit()` calls `can_enter()` twice before asserting.
   - These do not change behavior coverage, but they should be cleaned up when the next patch touches these tests.

3. **Daily trade and momentum counts remain UTC-scoped.**
   - This Phase 2N-H1 review focuses on the daily loss guard, not trade-count limits.
   - However, `PaperAccount.today_str()` and the simulator's momentum-count calculation still use UTC dates. If future phases want every daily limiter to align with NY trading dates, those paths will need separate work.

## Trading-day baseline assessment

- **Mostly implemented, but with ordering and observability caveats.**
- The account now tracks `daily_baseline_date` and `daily_start_equity` separately from `starting_cash`.
- The simulator initializes those fields on module load and reset, and resets only the daily baseline on NY date rollover without clearing cash, positions, or trades.
- The risk calculation now uses `current_equity - daily_start_equity`, so prior cumulative account P&L no longer directly drives the guard after the baseline has rolled.
- The rollover behavior correctly avoids resetting the whole account.
- The main flaw is that rollover currently happens after exits in `run_tick()`, so the first current-day exit can be absorbed into the new baseline instead of counted in current-day P&L.
- A secondary flaw is that status/readiness/monitoring do not roll the baseline forward unless a tick has run.

## Daily loss guard assessment

- **Current-day scoped calculation:** The core risk module now computes daily P&L from `daily_start_equity` rather than cumulative realized + unrealized P&L from simulator start. This addresses the Phase 2N-Lite cumulative-P&L issue after the baseline is current.
- **Threshold behavior:** The guard triggers at or beyond the configured percent or USD threshold (`<= -threshold`), which is stricter and reasonable for a max-loss guard.
- **Prior-day losses:** Prior-day losses no longer block new-day entries once the NY-date rollover has reset `daily_start_equity` to current equity.
- **Prior-day profits:** Prior-day profits no longer mask current-day losses when `daily_start_equity` is correctly set to the new-day baseline.
- **Catalyst and momentum entries:** The simulator checks the guard before catalyst entries and before momentum fallback entries.
- **Exits:** Exits are processed before the guard blocks entries, so stop-loss/take-profit/max-hold exits are not blocked.
- **Important remaining risk:** Because rollover is after exits, a first-tick new-day exit can be excluded from daily P&L. That is the main patch-required item before relying on Phase 2N-H1 during market hours.

## Re-entry / no-cooldown / no-profit-cap assessment

- **No daily profit cap was added.** I found no new profit-cap behavior in the reviewed risk/simulator paths.
- **No take-profit cooldown was added.** There is no new cooldown state or cooldown gate in the reviewed patch.
- **Immediate same-symbol re-entry after profit remains possible** if the setup still qualifies, the symbol is no longer in `positions`, account limits allow another entry, cash is available, and the daily loss guard is not triggered.
- `PaperAccount.can_enter()` blocks only symbols currently in open positions, not symbols with prior closed trades, so profitable exits do not create a same-symbol lockout.

## Monitoring / readiness / dashboard assessment

- **Monitoring endpoint:** `/api/monitoring/status` includes the backend `daily_loss_guard` object from `paper.simulator.get_status()`, so it can carry `trading_date`, `daily_start_equity`, `current_equity`, daily P&L, threshold, and trigger state.
- **Readiness endpoint:** `_check_daily_loss_guard()` now includes `trading_date`, `daily_start_equity`, and `current_equity` in the check details.
- **Dashboard API:** `/api/paper/dashboard` includes `status`, and `status.daily_loss_guard` now carries the new fields.
- **React dashboard UI:** Not complete. The UI still displays only guard status, Daily P&L, threshold, and trigger reason. It does not display trading date, daily baseline equity, or current equity, so dashboard truthfulness is incomplete for Phase 2N-H1.
- **Staleness caveat:** All monitoring/readiness/dashboard paths can report stale baseline dates if no tick has rolled the baseline after a NY date change.

## Test coverage assessment

- **Covered:**
  - Baseline fields exist and initialize.
  - Same-day percent and USD threshold behavior.
  - Day rollover resets the daily baseline without resetting the account.
  - Prior-day loss does not block new-day entries after rollover.
  - Prior-day profit does not mask current-day loss when the baseline is correctly set.
  - Guard blocks catalyst-path entries.
  - Guard blocks momentum-path entries.
  - Guard does not block exits.
  - Monitoring and readiness include the new daily-loss fields.
  - No profit-cap strings and no cooldown strings in the core risk/simulator files.
  - Same-symbol re-entry is allowed by account logic after a profitable exit.
  - Risk/account files do not import Polygon.
  - Risk/account files do not import broker/order/AI/LLM modules.

- **Gaps:**
  - No test covers the first tick after NY rollover when an open position exits before the baseline reset. This is the most important missing regression test.
  - No test covers `get_status()` / monitoring after a NY date change but before `run_tick()` has run.
  - Dashboard UI is not tested for rendering trading date and baseline; the current UI does not render them.
  - The "no real Polygon calls" tests cover `risk.py` and `account.py`, and simulator tick tests monkeypatch Polygon calls. That is adequate for this risk guard patch, but there is no broad no-network sentinel around all Phase 2N-H1 tests.

## Safety assessment

- The reviewed patch remains fake-money-only.
- I found no broker integration, live-trading path, real order placement, real-money execution path, AI/LLM integration, Ollama, OpenAI, Anthropic, or LangChain integration added by the Phase 2N-H1 patch.
- The simulator status continues to report `live_trading_enabled: false` and `broker_connected: false`.
- The guard blocks only new simulated entries and does not liquidate or block exits.
- No daily profit cap or take-profit cooldown was added.

## Safe for fake-money monitoring?

**Conditionally yes, but not yet fully safe for market-hours reliance without a small follow-up patch.**

Phase 2N-H1 is safe for fake-money monitoring in the sense that it does not add live trading, broker execution, real orders, or AI/LLM behavior. The core daily-loss formula is now trading-day scoped once the baseline is current.

However, for market-hours use, I would fix the baseline rollover ordering before relying on the guard. The current implementation can exclude a first-tick current-day exit from daily P&L if the NY date changed since the prior tick.

## Patch required before market hours?

**Yes.** A patch is required before market hours if Phase 2N-H1 is intended to be the active guard for new-day fake-money entries.

Minimum recommended patch:

1. Move the NY trading-date baseline rollover to occur before any exits or entries mutate the account during `run_tick()`.
2. Ensure `get_status()` / monitoring / readiness either roll the daily baseline forward or clearly report that the baseline is pending rollover until the next tick.
3. Update the React dashboard type and UI to display trading date, daily baseline equity, and current equity.
4. Add regression tests for:
   - new NY date + open position exit on first tick;
   - monitoring/status after NY date change before the first tick;
   - dashboard-visible trading date and baseline fields.
