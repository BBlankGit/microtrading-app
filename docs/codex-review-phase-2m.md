# Codex Review — Phase 2M Controlled Momentum Entry Mode

Review scope: latest Phase 2M commit only (`5dbaf6f Implement controlled momentum entry mode (Phase 2M)`).

## Critical issues

No critical issues found.

The Phase 2M changes do not add broker integration, live trading, real order placement, real-money execution, AI/LLM calls, or Ollama integration. The implementation remains a fake-money paper simulator feature and is gated behind disabled-by-default runtime configuration.

## Non-blocking issues

1. **Momentum sizing multiplier is applied before the hard USD cap.**
   - Current formula computes `cash * PAPER_POSITION_SIZE_PERCENT * PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER`, then applies `min(..., PAPER_MAX_POSITION_SIZE_USD)`.
   - This reduces default starting-cash momentum entries as intended, but if the normal catalyst size is already capped by `PAPER_MAX_POSITION_SIZE_USD`, a large-cash account can still produce a momentum entry equal to the same cap as a catalyst entry.
   - Safer future patch: compute the normal capped budget first, then multiply it for momentum: `min(cash * pct, cap) * multiplier`, followed by the cash guard in `PaperAccount.enter_position()`.
   - This is non-blocking for fake-money monitoring because momentum mode is disabled by default and the current path still respects hard caps and cash.

2. **Candidate rows can show momentum eligibility metadata even when catalyst mode wins.**
   - Momentum evaluation is computed whenever momentum mode is enabled, before the final catalyst-vs-momentum decision.
   - The actual entry logic still prioritizes catalyst entries, so this is not an execution safety issue.
   - Future polish: only set `momentum_eligible` as actionable/visible when the catalyst path did not enter and the no-catalyst fallback condition applies, or add a `momentum_evaluated_as_fallback` flag.

## Momentum logic assessment

Phase 2M implements momentum as a strict secondary path rather than a replacement for catalyst mode.

- Momentum mode is disabled by default in base settings.
- `evaluate_momentum_entry()` checks the explicit enable flag first and returns `momentum_mode_disabled` when false.
- The simulator first evaluates catalyst mode. Catalyst entries take priority when hard gates pass and the catalyst score passes.
- Momentum entry is only attempted in the fallback branch when:
  - the catalyst path did not enter,
  - the hard rejection reason is specifically no accepted catalysts or only `generic_news`, and
  - `evaluate_momentum_entry()` returns eligible.
- Momentum does not bypass the shared hard gates for non-tradable quality, spread, non-positive price movement, low volume ratio, or strong bearish catalyst rejection.
- Momentum additionally requires stricter conditions:
  - tighter max spread (`PAPER_MOMENTUM_MAX_SPREAD_PERCENT`, default `0.25%`),
  - stronger price move (`PAPER_MOMENTUM_MIN_CHANGE_PERCENT`, default `1.5%`),
  - stronger volume ratio (`PAPER_MOMENTUM_MIN_VOLUME_RATIO`, default `2.0x`),
  - risk-on regime requirement by default,
  - momentum score threshold default `85`.

Assessment: the entry flow is safe and correctly structured as catalyst-first, momentum-second.

## Runtime config assessment

Momentum mode is runtime-configurable and admin-protected.

- The runtime schema includes all Phase 2M fields, with bounds and `category: momentum` metadata.
- Runtime config PATCH and reset endpoints remain admin-protected through `require_admin_token`.
- Momentum mode remains disabled after runtime reset because the base setting is false and reset clears overrides.
- Read-only config/schema endpoints expose values for dashboard visibility but cannot mutate configuration.
- Monitoring and readiness expose/warn on momentum mode state.

Assessment: runtime configurability is appropriate. No unauthenticated mutation path was found.

## Simulator/account safety assessment

The simulator/account path remains fake-money only.

- `PaperAccount` remains in-memory virtual accounting with no external execution calls.
- Momentum entries call the same `can_enter()` account gate used by catalyst entries, preserving:
  - duplicate-position prevention,
  - max open positions,
  - max total trades/day,
  - cash availability.
- Momentum adds its own daily cap through `PAPER_MOMENTUM_MAX_TRADES_PER_DAY`.
- `PaperAccount.enter_position()` still caps position cost by available cash.
- The simulator status continues to hard-code `live_trading_enabled: False` and `broker_connected: False`.

Assessment: account safety is intact for fake-money monitoring. The sizing multiplier/cap ordering noted above should be improved before treating the multiplier as guaranteed reduction in every cap-bound scenario.

## Dashboard/journal assessment

Candidate output, journal data, and dashboard rendering distinguish catalyst and momentum entries.

- Candidate dictionaries now include `entry_mode` plus momentum-specific score/rejection/gate fields.
- Entry and exit events carry `entry_mode`.
- `Position` and `ClosedTrade` models carry `entry_mode`.
- Journal schema and inserts persist candidate momentum fields and trade `entry_mode`.
- Dashboard candidate table adds a `Mode` column with distinct `cat` and `mom` badges.
- Dashboard settings add a Momentum Mode panel with a fake-money/no-broker/no-real-orders disclaimer.

Assessment: catalyst vs momentum visibility is clear enough for monitoring. A future enhancement could add momentum score/gate details directly in the candidate row tooltip or expanded detail view.

## Readiness/monitoring assessment

Readiness and monitoring correctly flag momentum mode.

- Readiness includes a new `momentum_mode` check.
- Disabled momentum returns pass with a catalyst-only/default message.
- Enabled momentum returns warn and explicitly states fake-money/no-broker/no-real-orders.
- Monitoring includes a `momentum_mode` status dictionary with thresholds and safety disclaimer.
- Monitoring appends an enabled-momentum warning.
- Readiness recommended actions include disabling momentum mode when not intentionally testing it.

Assessment: readiness/monitoring behavior is appropriate and conservative.

## Test coverage assessment

Phase 2M test coverage is strong.

Covered:

- disabled/default behavior,
- conservative defaults,
- runtime schema inclusion and validation bounds,
- momentum pass gates,
- momentum fail gates,
- minimum-gate score behavior,
- catalyst mode still used when momentum is disabled,
- model/account `entry_mode` propagation,
- momentum sizing at default cash/cap assumptions,
- candidate output fields,
- readiness pass/warn behavior,
- monitoring payload/warning behavior,
- no broker/AI imports in momentum/simulator files,
- disabled state after runtime reset.

Gaps / recommended future tests:

1. Add an end-to-end simulator test proving momentum enters only after `no accepted catalysts` / `only generic_news` and never after strong bearish catalyst rejection.
2. Add tests proving max open positions, max total daily trades, and max momentum daily trades block momentum entries in `run_tick()`.
3. Add a sizing test for cap-bound accounts to catch the multiplier-before-cap behavior described above.
4. Add a test that no real Polygon calls are made by Phase 2M tests as a suite-level guard, beyond the current patched call sites and import checks.

Executed during review: `pytest backend/tests/test_phase2m.py` — 30 passed, 1 deprecation warning from Starlette/FastAPI test client.

## Safety assessment

Phase 2M is safe for fake-money monitoring.

Reasons:

- It is disabled by default.
- It must be explicitly enabled via bounded runtime config or environment configuration.
- Runtime mutation is admin-protected.
- It does not add broker/live-order/AI/Ollama paths.
- It reuses account can-enter checks and adds a momentum-specific daily cap.
- It preserves catalyst-first behavior and strong bearish catalyst rejection.
- Readiness and monitoring warn when enabled.

## Whether Phase 2M is safe for fake-money monitoring

Yes. Phase 2M is safe for fake-money monitoring as implemented, especially with momentum mode left disabled unless deliberately testing it.

## Whether any patch is required before market hours

No mandatory patch is required before market hours for fake-money monitoring with momentum mode disabled.

Recommended before enabling momentum for active research:

- Patch the momentum sizing formula so the multiplier applies after the normal capped position budget is computed.
- Add explicit simulator-level tests for momentum fallback eligibility, account gates, and momentum daily-limit blocking.
