# Codex Review — Phase 2N-Lite Active Microtrading Limits and Daily Loss Guard

Scope reviewed: latest patch only (`281a2ac Increase paper trading limits and add daily loss guard`), compared against its parent.

## Critical issues

1. **Daily loss guard is not actually calendar-day scoped.**
   - The guard is presented throughout the patch as a daily loss guard, and the UI/readiness/monitoring labels report `daily_pnl` / `Daily P&L`.
   - However, `backend/paper/risk.py` explicitly uses realized + unrealized P&L since simulator start/reset and has no date rollover tracking.
   - Impact: a prior day loss can continue blocking entries on a later day until simulator reset or manual override, and a prior day profit can mask current-day losses. This is a correctness gap for a feature named and surfaced as a daily max loss guard.
   - Recommendation: add a calendar-day baseline (UTC or configured market/session date) before relying on this as a true daily guard. For fake-money monitoring, this is operationally safe but semantically misleading.

## Non-blocking issues

1. **Naming mismatch around open-position limit.**
   - Runtime config exposes `PAPER_MAX_OPEN_POSITIONS` and aliases it to `settings.PAPER_MAX_POSITIONS`.
   - `.env.example` and `Settings` still use `PAPER_MAX_POSITIONS`, not an environment variable named `PAPER_MAX_OPEN_POSITIONS`.
   - The effective default is 5, so runtime behavior matches the limit intent. But operators who set only `PAPER_MAX_OPEN_POSITIONS` in `.env` would not affect the base `Settings` value because Pydantic ignores unknown env fields.

2. **Test coverage has no explicit static assertion for absence of profit caps or take-profit cooldowns.**
   - Behavior inspection shows no new profit cap and no cooldown state was added.
   - The test suite verifies exits still occur and same-symbol re-entry remains possible indirectly through control flow, but it would be stronger to add direct regression tests/search assertions for forbidden profit-cap/cooldown fields if those are contractual invariants.

3. **Readiness recommendation text says to adjust `PAPER_DAILY_MAX_LOSS_PERCENT` to resume entries.**
   - This is technically possible and admin-protected, but it can normalize loosening the guard during a drawdown.
   - Consider recommending reset/new session only for normal operations, and threshold adjustment only for deliberate test scenarios.

## Default limit assessment

- **Pass:** `PAPER_MAX_POSITIONS` default changed from 2 to 5 in `Settings` and `.env.example`.
- **Pass:** Runtime config continues to expose `PAPER_MAX_OPEN_POSITIONS`; it resolves to the `PAPER_MAX_POSITIONS` setting through the existing alias, so the effective open-position limit is 5.
- **Pass:** `PAPER_MAX_TRADES_PER_DAY` default changed from 20 to 100.
- **Pass:** `PAPER_MOMENTUM_MAX_TRADES_PER_DAY` default changed from 5 to 30.
- **Pass:** `PAPER_MOMENTUM_MODE_ENABLED` remains default `False`.

## Daily loss guard assessment

- **Pass:** The guard is fake-money only and deterministic. The new `paper.risk` module contains no broker/AI behavior and calculates guard state from virtual account P&L.
- **Pass:** The guard blocks new entries only. In `run_tick`, exits are processed before guard evaluation and before the entry loop.
- **Pass:** Catalyst entries are blocked when the guard is triggered by setting candidate action/rejection to `daily_max_loss_guard` before `can_enter` and `enter_position`.
- **Pass:** Momentum entries are also blocked when the guard is triggered.
- **Pass:** The guard includes both percent and optional USD thresholds. `PAPER_DAILY_MAX_LOSS_USD=0` disables the USD threshold.
- **Issue:** Despite the daily naming, the implementation is cumulative since simulator start/reset, not day-specific. This is the main blocker for semantic correctness.

## Re-entry/no-cooldown assessment

- **Pass:** No daily profit cap was added.
- **Pass:** No cooldown after take-profit was added.
- **Pass:** Immediate same-symbol re-entry after a profitable exit remains possible when the same symbol still qualifies, because exits remove the position before the entry loop and `can_enter` only rejects currently open positions, max positions, daily trade count, and cash availability.
- **Caveat:** If the daily loss guard is already triggered after exits, it will still block re-entry. That is expected risk-guard behavior, not a take-profit cooldown.

## Runtime config assessment

- **Pass:** Daily loss guard settings are runtime-configurable through `paper.runtime_config`:
  - `PAPER_DAILY_MAX_LOSS_ENABLED`
  - `PAPER_DAILY_MAX_LOSS_PERCENT`
  - `PAPER_DAILY_MAX_LOSS_USD`
- **Pass:** Runtime bounds and types are defined and validation rejects invalid updates.
- **Pass:** The runtime PATCH/reset API is admin-protected via `require_admin_token`.
- **Pass:** Runtime updates are persisted/audited when Postgres is available, with memory-only fallback warning behavior unchanged.

## Dashboard/monitoring/readiness assessment

- **Pass:** `/api/monitoring/status` includes `daily_loss_guard` and emits a warning when triggered.
- **Pass:** `/api/readiness/session` includes a `daily_loss_guard` check and warns when the guard is triggered.
- **Pass:** The dashboard surfaces guard status, daily P&L, threshold, and trigger reason in the paper status area.
- **Pass:** The strategy settings panel exposes daily loss guard enable/percent/USD controls in the runtime config UI.
- **Issue:** Because the underlying P&L is cumulative since reset, dashboard/readiness/monitoring labels that say daily P&L can mislead operators unless the implementation is made truly daily or the labels are changed.

## Test coverage assessment

- **Pass:** Defaults are covered for max positions, max trades/day, momentum max trades/day, guard enabled, guard percent, and guard USD.
- **Pass:** Runtime schema and validation are covered for daily loss guard fields, including type and min/max validation.
- **Pass:** Guard trigger logic is covered for disabled state, no loss, percent threshold, exact threshold, USD threshold, combined thresholds, unrealized P&L, exception fallback, and threshold result fields.
- **Pass:** Catalyst blocking is covered.
- **Pass:** Momentum blocking is covered.
- **Pass:** Exits-not-blocked behavior is covered.
- **Pass:** Monitoring and readiness exposure are covered.
- **Pass:** Safety tests check no broker/AI imports in the new risk path and simulator Phase 2N path, no execution-call names in `risk.py`, and simulator status remains `live_trading_enabled=False` / `broker_connected=False`.
- **Mostly pass:** Tests patch Polygon calls in run-tick scenarios and the Phase 2N test file runs without real Polygon network calls.
- **Gap:** No explicit regression test asserts absence of profit caps or cooldown symbols/state. This is currently verified by patch review rather than direct tests.
- **Gap:** No test catches the calendar-day semantic problem. A test should simulate a day rollover and verify the guard uses a new daily baseline.

## Safety assessment

- **Pass:** No broker integration, live trading, real orders, real-money execution, OpenAI, Anthropic, Ollama, LangChain, or AI/LLM integration was added in the latest patch.
- **Pass:** The simulator status continues to hard-code `live_trading_enabled=False` and `broker_connected=False`.
- **Pass:** All new guard behavior operates on the in-memory virtual `PaperAccount` and runtime config only.
- **Pass:** The system remains safe for fake-money monitoring from an execution-safety perspective.
- **Operational caveat:** The cumulative-not-daily guard can over-block or under-block relative to a true daily risk limit, so operators should understand it as a since-reset drawdown guard until patched.

## Is Phase 2N-Lite safe for fake-money monitoring?

**Yes, with caveat.** It is safe for fake-money monitoring because it does not add broker/live-order/AI execution paths and it only blocks virtual entries. However, it should not be described or relied on as a true calendar-day loss guard until the day-baseline issue is fixed or the wording is changed to "since reset" / "session drawdown" guard.

## Is any patch required before market hours?

**Recommended before market hours if the release goal is a true daily max loss guard.** The required patch is to add date/session-scoped P&L baseline tracking and tests for day rollover. If the team accepts the current behavior as a fake-money since-reset drawdown guard, then no execution-safety patch is required before market hours, but the dashboard/readiness/monitoring wording should be clarified to avoid operator confusion.
