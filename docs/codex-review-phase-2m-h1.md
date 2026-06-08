# Codex Review — Phase 2M-H1 Momentum Sizing and Simulator Gate Tests

Reviewed patch: `ba884e2` (`Harden momentum sizing and simulator gate tests`)

Scope reviewed: latest Phase 2M-H1 patch only, which modifies:

- `backend/paper/simulator.py`
- `backend/tests/test_phase2m.py`

## Critical issues

None found.

The Phase 2M-H1 patch fixes the cap-bound momentum sizing bug in the simulator entry path and does not introduce broker, live-trading, order-execution, AI/LLM, Ollama, OpenAI, Anthropic, LangChain, or real-money execution code in the reviewed patch.

## Non-blocking issues

1. **Several new tests mirror simulator logic instead of executing the simulator branch directly.**
   - The cap-bound momentum sizing test validates the intended formula with local arithmetic, but it does not execute `run_tick()` and assert the actual simulated position cost basis.
   - The catalyst sizing unchanged test similarly validates the arithmetic model rather than the simulator catalyst branch.
   - The strong-bearish catalyst test reproduces the hard-rejection ordering locally rather than running a mocked simulator tick with a strong bearish catalyst.
   - The max momentum trades/day test reproduces the count comparison locally rather than running `run_tick()` with the threshold already reached.

   These are not blockers because the production code path is straightforward and the simulator-level fallback test does execute `run_tick()`, but follow-up tests would be stronger if they asserted the actual simulator outcomes.

2. **The simulator safety test checks forbidden imports but not forbidden execution symbols in `simulator.py`.**
   - `test_momentum_py_no_execution_calls()` checks execution strings in `momentum.py`.
   - `test_simulator_no_broker_imports()` checks forbidden imports in `simulator.py`.
   - There is no matching `simulator.py` execution-symbol string check in the Phase 2M test file. Manual review of the latest patch did not find broker/order execution additions.

## Momentum sizing assessment

Pass.

The reviewed simulator patch now computes momentum position size as:

```python
normal_budget = min(_account.cash * (pos_pct / 100.0), settings.PAPER_MAX_POSITION_SIZE_USD)
position_budget = normal_budget * size_multiplier
```

That matches the required ordering:

```python
normal_budget = min(cash * position_size_percent, max_position_size_usd)
momentum_budget = normal_budget * momentum_multiplier
```

This fixes the prior cap-bound behavior where applying the multiplier before the cap could still produce a full-cap momentum entry on larger fake-money accounts.

## Catalyst-mode regression assessment

Pass.

Catalyst sizing remains unchanged in the reviewed code. The catalyst path still computes:

```python
budget_pct = _account.cash * (pos_pct / 100.0)
position_budget = min(budget_pct, settings.PAPER_MAX_POSITION_SIZE_USD)
```

No momentum multiplier is applied to catalyst entries, and catalyst entries still pass `entry_mode="catalyst"` into the fake-money account.

## Simulator gate assessment

Pass.

The simulator continues to apply momentum only as a fallback after the catalyst path is not taken. Catalyst mode is evaluated first, and the momentum branch is only reached through the `elif` branch when all of the following are true:

- there is a hard rejection,
- the rejection is a no-catalyst-style rejection,
- momentum evaluation was computed,
- momentum evaluation is eligible.

The strong-bearish hard gate remains before the no-catalyst fallback flags are set, so a strong bearish catalyst does not set `is_no_catalyst_rejection` and cannot be rescued by momentum.

Account-level gates still block momentum entries:

- **Max open positions:** momentum calls `_account.can_enter()` with `PAPER_MAX_OPEN_POSITIONS`.
- **Max total trades/day:** momentum calls `_account.can_enter()` with `PAPER_MAX_TRADES_PER_DAY`.
- **Max momentum trades/day:** the simulator checks `today_momentum_count >= PAPER_MOMENTUM_MAX_TRADES_PER_DAY` before attempting a momentum entry.

## Runtime config/defaults assessment

Pass.

Momentum mode remains disabled by default in base settings:

```python
PAPER_MOMENTUM_MODE_ENABLED: bool = False
```

The runtime schema still exposes the momentum flag as a runtime-applied momentum config value, and `effective_value("PAPER_MOMENTUM_MODE_ENABLED")` falls back to base settings unless an explicit runtime override is present. The existing runtime reset test confirms that clearing overrides returns momentum mode to disabled.

Runtime verification therefore leaves momentum disabled unless the user explicitly enables `PAPER_MOMENTUM_MODE_ENABLED`.

## Test coverage assessment

Pass with the non-blocking caveat above.

The Phase 2M-H1 patch adds or updates coverage for the requested areas:

- **Cap-bound momentum sizing:** covered by `test_momentum_sizing_cap_applied_before_multiplier()`.
- **Catalyst sizing unchanged:** covered by `test_catalyst_sizing_no_multiplier_applied()`.
- **Momentum disabled default:** already covered by default/effective-value tests and reinforced by runtime reset coverage.
- **Simulator-level momentum fallback eligibility:** covered by `test_simulator_momentum_fallback_entry_mode()`, which runs `sim.run_tick()` with mocked universe, Polygon snapshot, previous close, quality evaluation, catalyst collection, persistence, cached universe, and save-state calls.
- **Strong bearish catalyst not rescued:** covered by `test_strong_bearish_catalyst_not_rescued_by_momentum()`, though it mirrors the gate logic rather than executing `run_tick()`.
- **Max open positions gate:** covered by `test_momentum_blocked_max_open_positions()` through `PaperAccount.can_enter()`.
- **Max total trades/day gate:** covered by `test_momentum_blocked_max_daily_trades()` through `PaperAccount.can_enter()`.
- **Max momentum trades/day gate:** covered by `test_momentum_daily_limit_blocks_at_threshold()`, though it mirrors the simulator count comparison rather than executing `run_tick()`.
- **No real Polygon calls:** the simulator fallback test mocks Polygon snapshot and previous-close calls.
- **No broker/order/AI/LLM/Ollama imports:** forbidden module coverage now includes `ollama` and checks `momentum.py` plus `simulator.py` imports.

Targeted verification run:

```text
pytest backend/tests/test_phase2m.py
37 passed, 1 warning
```

## Safety assessment

Pass.

The reviewed patch is still fake-money-only. The simulator and momentum module continue to document no broker, no live trading, no real orders, no real-money execution, and no AI/LLM behavior. The latest patch only changes deterministic sizing logic in the paper simulator and expands tests.

No reviewed patch changes add:

- broker integration,
- live trading,
- real order placement,
- real-money execution,
- OpenAI,
- Anthropic,
- LangChain,
- Ollama,
- other AI/LLM integration.

## Safe for fake-money monitoring?

Yes.

Phase 2M-H1 is safe for fake-money monitoring. Momentum mode remains opt-in and disabled by default, catalyst mode remains primary, momentum is limited to no-catalyst fallback cases, strong bearish catalyst rejection remains non-rescuable, and account gates still apply before a simulated momentum entry is opened.

## Patch required before market hours?

No.

No additional patch is required before market hours for fake-money monitoring. The only recommended follow-up is non-blocking test hardening so more of the new assertions execute `run_tick()` directly instead of mirroring simulator logic.
