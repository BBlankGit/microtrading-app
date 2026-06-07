# Codex Review — Phase 2K-H1 Runtime Config Wiring

Reviewed patch: `f423f1c Wire Phase 2K runtime config controls to runtime modules`

Scope: latest Phase 2K-H1 changes only.

## Executive summary

Phase 2K-H1 materially improves the runtime configuration story: the previously advertised runtime controls are now largely backed by `effective_value()` lookups in the simulator, universe builder, discovery module, market-regime service, and monitoring/API paths. The patch keeps the system fake-money only, does not introduce broker/live-order/AI integrations, and preserves admin-only mutation of runtime config.

One runtime-wiring edge case remains: if `run_tick()` cannot resolve the active universe, its exception fallback still slices the base universe with `settings.PAPER_MAX_SYMBOLS_PER_TICK` instead of the runtime override. This does not create real-money risk, but it means an admin override for max symbols per tick can be bypassed on a universe error path.

## Critical issues

None found that would create broker integration, live trading, real orders, AI/LLM calls, secret exposure, or real-money execution.

## Non-blocking issues

### 1. Universe-error fallback bypasses runtime max-symbol override

In `backend/paper/simulator.py`, the normal universe path consumes the active universe returned by `get_active_paper_universe()`, but the exception fallback still uses the base settings object:

```python
symbols = settings.paper_base_universe_list()[:settings.PAPER_MAX_SYMBOLS_PER_TICK]
```

Impact:

- If `PAPER_MAX_SYMBOLS_PER_TICK` is lowered at runtime and the universe builder throws, the simulator can evaluate the base-config number of symbols instead of the runtime override.
- This affects fake-money simulation/API usage only; max open positions, max trades/day, and position sizing still use runtime config later in the entry path.
- This should be patched for truthfulness/consistency, but it is not a real-money safety blocker.

Suggested fix:

- Replace the fallback slice with `_cfg("PAPER_MAX_SYMBOLS_PER_TICK")`.
- Add a focused test that forces `get_active_paper_universe()` to raise and verifies the fallback symbol count follows the runtime override.

### 2. Runtime-wiring tests are broad but several assertions only test the config helper, not the consuming modules

Several Phase 2K-H1 tests named as downstream consumption checks only assert that `paper.runtime_config.effective_value()` returns an override. That confirms the config helper works, but not that universe/discovery/regime/simulator code paths actually consume the override under realistic execution.

Examples:

- `test_universe_max_symbols_per_tick_override_consumed()`
- `test_universe_max_universe_size_override_consumed()`
- `test_discovery_max_symbols_override_consumed()`
- `test_discovery_min_price_override_consumed()`
- `test_market_regime_refresh_seconds_override_consumed()`

The patch does include some stronger behavior tests, such as regime classification and no-real-network patching, but coverage would be stronger if each runtime module had at least one direct behavior test for its important override paths.

Suggested additions:

- Discovery: feed fake movers and assert runtime min/max price, volume, change, and max symbols alter returned symbols.
- Universe: mock Polygon quality calls and assert runtime max universe size and max symbols per tick alter candidate/evaluation counts.
- Simulator: mock an entry path and assert runtime position-size percent changes cost basis, including cap behavior.
- Simulator fallback: force universe failure and assert the fallback uses runtime max symbols.
- Market regime: verify runtime TTL by seeding/refreshing cache with patched time or a short override.

## Runtime wiring assessment

### Trading/scoring/risk controls

Status: **Mostly wired and truthful.**

- Entry score threshold is consumed by `paper.scoring.score_candidate()` through `_cfg("PAPER_ENTRY_SCORE_THRESHOLD")`.
- Take-profit, stop-loss, and max-hold controls are consumed during exit checks through `_cfg()`.
- Max open positions and max trades/day are consumed before entry through `_cfg()`.
- Bearish-catalyst rejection and materiality threshold are consumed in the simulator hard-gate path through `_cfg()`.

### Position-size override

Status: **Wired safely for fake-money entries.**

The simulator now computes a per-entry budget from runtime `PAPER_POSITION_SIZE_PERCENT` as:

```python
budget_pct = _account.cash * (pos_pct / 100.0)
position_budget = min(budget_pct, settings.PAPER_MAX_POSITION_SIZE_USD)
```

That budget is passed into `PaperAccount.enter_position()`, which also caps by remaining fake cash. This means:

- Runtime percent can reduce fake-money entry size.
- Runtime percent cannot exceed the hard USD ceiling.
- Entry cannot spend more than available fake cash.
- Existing open positions are not retroactively resized, which the dashboard now states explicitly.

### Universe controls

Status: **Wired in normal paths; one fallback edge case remains.**

- `PAPER_DYNAMIC_REFRESH_SECONDS` is consumed for universe cache TTL.
- `PAPER_DYNAMIC_UNIVERSE_ENABLED` is consumed to switch dynamic ranking on/off.
- `PAPER_MAX_UNIVERSE_SIZE` is consumed to cap the merged candidate pool.
- `PAPER_MAX_SYMBOLS_PER_TICK` is consumed for disabled, fallback, active-list, and result metadata paths inside `paper.universe`.
- Exception fallback inside `paper.simulator.run_tick()` still uses `settings.PAPER_MAX_SYMBOLS_PER_TICK`, as noted above.

### Discovery controls

Status: **Wired for the runtime-exposed discovery controls.**

- `PAPER_MARKET_DISCOVERY_ENABLED` is consumed by discovery and universe integration.
- `PAPER_MARKET_DISCOVERY_REFRESH_SECONDS` is consumed for discovery cache TTL.
- `PAPER_MARKET_DISCOVERY_MAX_SYMBOLS` is consumed to cap discovered symbols.
- `PAPER_MARKET_DISCOVERY_MIN_PRICE`, `MAX_PRICE`, `MIN_VOLUME`, and `MIN_ABS_CHANGE_PERCENT` are consumed by mover filtering.
- Gainers/losers/most-active source toggles remain base-settings only and are not exposed as runtime-editable fields. The most-active path is explicitly commented as not runtime-tunable, which is acceptable because it is not exposed in the runtime schema.

### Market-regime controls

Status: **Wired.**

- API enable checks now use runtime `MARKET_REGIME_ENABLED`.
- Monitoring status now reports and gates market-regime collection through runtime `MARKET_REGIME_ENABLED`.
- Market-regime cache TTL uses runtime `MARKET_REGIME_REFRESH_SECONDS`.
- Risk-on/risk-off thresholds use runtime `MARKET_REGIME_MIN_RISK_ON_SCORE` and `MARKET_REGIME_MAX_RISK_OFF_SCORE`.
- Market-regime metadata remains observational in the simulator; it does not change entry/exit behavior.

## Dashboard truthfulness assessment

Status: **Truthful after the H1 label update, with one limitation to understand.**

The dashboard now says:

- Editable settings in the panel are applied at runtime.
- The settings affect fake-money simulation only.
- There is no broker, no live trading, and no real orders.
- Changes apply on the next tick and do not retroactively affect existing open positions.

That language is accurate for the controls currently displayed in the panel. The dashboard does not expose every field present in the backend runtime schema, such as several discovery filter/TTL controls, regime thresholds, and max universe size. That is not false labeling, but if operators expect the dashboard to represent every runtime-configurable field, the UI should either add the remaining fields or include a note that this is a subset of backend runtime controls.

## Safety assessment

Status: **Safe for fake-money simulation.**

No evidence was found in the H1 patch of:

- Broker integration.
- Live trading enablement.
- Real order placement.
- Real-money execution.
- AI/LLM calls.
- Secret exposure in runtime config schema.

Admin protection remains intact:

- Runtime config GET/schema endpoints remain read-only.
- PATCH `/api/config/runtime` still requires `require_admin_token`.
- POST `/api/config/runtime/reset` still requires `require_admin_token`.
- Market-regime refresh remains admin-protected.

Secret safety remains intact:

- Runtime config schema contains only bounded simulation/research controls.
- API keys, auth tokens, DB URLs, passwords, and other secrets are not included in the schema.

## Test coverage assessment

Status: **Useful safety regression coverage, but runtime-wiring behavior coverage should be strengthened.**

Positive coverage:

- H1 tests assert schema metadata includes runtime-applied labels.
- H1 tests check no forbidden broker/AI/live-trading imports in changed backend files.
- H1 tests check admin dependencies exist on config mutation routes.
- H1 tests include a patched market-regime call, avoiding real Polygon network access.
- The reviewed test run passed: `pytest backend/tests/test_phase2kh1.py -q`.

Coverage gaps:

- Several tests verify `effective_value()` returns overrides but do not exercise the consuming runtime modules.
- Position sizing tests verify formula/config helper behavior, but do not run the simulator entry path and assert actual fake position cost basis/share sizing.
- The simulator universe-error fallback is untested and currently bypasses the runtime max-symbol override.
- Discovery filter tests should directly exercise `_filter_movers()` or `discover_market_movers()` with patched Polygon responses to prove runtime filters change output.
- Universe tests should mock Polygon quality responses to prove runtime max universe/max symbols alter the actual active universe.

## Patch required before market hours?

**No safety-critical patch is required before market hours** because the H1 changes remain fake-money only and do not introduce live trading, broker connectivity, real orders, AI/LLM behavior, or secret exposure.

However, I recommend a small follow-up patch before relying on runtime controls during market hours:

1. Change the simulator universe-error fallback to use `_cfg("PAPER_MAX_SYMBOLS_PER_TICK")`.
2. Add direct behavior tests for the fallback and for position-size entry sizing.

This follow-up would improve dashboard/runtime truthfulness and reduce surprise during fake-money market-hours operation, but it is not a real-money safety blocker.
