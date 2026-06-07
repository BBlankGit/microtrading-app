# Codex Review — Phase 2K-H2 Simulator Fallback Runtime Config

Reviewed patch: `d5593ad Fix simulator fallback runtime max symbols override`

Scope: latest Phase 2K-H2 patch only.

## Executive summary

Phase 2K-H2 correctly fixes the simulator universe-error fallback so it now uses the runtime-effective `PAPER_MAX_SYMBOLS_PER_TICK` value. The code change is narrowly limited to the error fallback slice in `paper.simulator.run_tick()` and does not alter the normal universe path, scoring, hard gates, entry/exit strategy decisions, broker behavior, AI/LLM behavior, or any real-money execution path.

The patch also adds a focused regression test that forces `get_active_paper_universe()` to fail, sets a runtime override of `PAPER_MAX_SYMBOLS_PER_TICK = 3`, sets the base setting to `999`, and verifies only three symbols are evaluated. That directly covers the bug fixed in this H2 patch.

## Critical issues

None found.

No evidence in this H2 patch of:

- Broker integration.
- Live trading enablement.
- Real order placement.
- Real-money execution.
- AI/LLM or OpenAI/LangChain integration.
- Secret exposure.
- Strategy/scoring/entry/exit logic changes outside the targeted fallback consistency fix.

## Fallback consistency assessment

Status: **Pass**.

The simulator exception fallback now slices the base universe with the runtime-effective max-symbol count:

```python
symbols = settings.paper_base_universe_list()[:int(_cfg("PAPER_MAX_SYMBOLS_PER_TICK"))]
```

This resolves the H1 review finding where the universe-error path still used `settings.PAPER_MAX_SYMBOLS_PER_TICK` directly. As a result:

- Normal active-universe resolution remains unchanged.
- If active-universe resolution raises, fallback symbol count now respects runtime overrides.
- The fallback remains a fake-money simulator path only.
- The fallback still records `universe_refresh_reason = "error_fallback"` and appends the universe error to the tick result.

## Normal strategy logic assessment

Status: **Pass**.

The H2 production code change is a one-line replacement in the universe-error fallback slice. It does not change:

- Market quality evaluation behavior.
- Catalyst/news collection behavior.
- Candidate scoring behavior.
- Hard rejection gates.
- Entry score threshold behavior.
- Entry price selection.
- Position budget formula.
- Max open positions or max trades/day checks.
- Take-profit, stop-loss, or max-hold exit checks.
- Journal persistence behavior.
- Market-regime metadata behavior.

The added tests include two position-sizing tests, but those are test-only additions and do not modify runtime strategy code.

## Safety assessment

Status: **Pass — fake-money simulation remains isolated**.

The reviewed H2 patch does not add or enable any broker, live-trading, real-order, AI/LLM, or real-money pathway. The changed runtime path remains inside `backend/paper/simulator.py`, whose module and `run_tick()` docstrings continue to describe research paper simulation only.

The test suite retains the existing import guard that scans Phase 2K-H1 backend source files for forbidden broker/Alpaca/OpenAI/LangChain imports. The H2 patch does not expand the runtime surface beyond the simulator fallback and tests.

## Test coverage assessment

Status: **Pass for the H2 fallback bug**.

The new focused test `test_simulator_fallback_uses_runtime_max_symbols()` covers the important regression scenario:

- Clears runtime overrides before execution.
- Sets runtime `PAPER_MAX_SYMBOLS_PER_TICK` to `3`.
- Forces `get_active_paper_universe()` to raise.
- Mocks the base universe to contain 20 symbols.
- Sets the base `settings.PAPER_MAX_SYMBOLS_PER_TICK` to `999` to prove the base setting is not used.
- Tracks calls into `evaluate_market_quality()`.
- Asserts exactly three symbols are evaluated.
- Asserts the tick reports `universe_refresh_reason == "error_fallback"`.
- Clears runtime overrides in a `finally` block.

Additional H2 tests verify paper-account position sizing and the budget formula, but those are broader runtime-config regressions rather than direct coverage for the simulator fallback fix.

Reviewed command result:

```text
pytest backend/tests/test_phase2kh1.py -q
47 passed, 1 warning in 0.46s
```

The warning is a third-party Starlette/FastAPI TestClient deprecation warning and is not caused by this patch.

## Patch required before market hours?

**No patch is required before market hours for Phase 2K-H2.**

The previously identified fallback inconsistency is fixed, directly tested, and remains limited to fake-money simulation. No live-trading, broker, real-order, AI/LLM, or real-money execution risk was introduced.

## Final recommendation

Approve the Phase 2K-H2 patch as-is.
