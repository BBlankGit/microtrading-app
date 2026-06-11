# Codex Review — Phase N1-H1 Market Mover Session Hard-Blocking

Review date: 2026-06-11  
Repository: `BBlankGit/microtrading-app`  
Reviewed patch: `12635fd Harden market mover entry session gates`  
Scope: latest Phase N1-H1 patch only

## Verdict

**PASS — Phase N1-H1 is safe for fake-money monitoring.**

The latest patch hardens the `market_mover_no_catalyst` path by adding an immutable safe-session allowlist, intersecting runtime-configured sessions with that allowlist, exposing warnings for unsafe configured sessions, and preserving the existing paper-only/account/volume/catalyst/risk controls. I found no code changes that add Polygon calls, broker/live-order behavior, AI/LLM/Ollama integrations, or TP/SL/exit changes.

One scoped clarification: unsafe configured sessions are **ignored with per-candidate warnings at evaluation time**, not rejected by runtime-config validation. This matches the accepted requirement of "rejected or ignored with warnings," but the warning is surfaced in candidate diagnostics rather than as a runtime-config API validation error.

## Review Checklist

| # | Focus area | Result | Evidence |
|---|---|---|---|
| 1 | Immutable hard-blocks for `afterhours`, `closed`, `non_regular`, `overnight`, and `unknown` sessions | **PASS** | `_MM_SAFE_SESSIONS` is hard-coded to `{"premarket", "regular"}`. Any `_tick_session_type` outside that set gets `session_hard_blocked`, so `afterhours`, `closed`, `non_regular`, `overnight`, `unknown`, and any other non-safe value are blocked. Tests explicitly cover afterhours, closed, non_regular, and overnight; unknown is covered by the same not-in-safe-set branch. |
| 2 | Runtime overrides cannot allow unsafe sessions | **PASS** | Runtime values are normalized into `_mm_raw_sessions`, then intersected with `_MM_SAFE_SESSIONS`; unsafe values never enter `_mm_configured_safe`. The hard block checks `_tick_session_type not in _MM_SAFE_SESSIONS` before market-mover gate evaluation continues. |
| 3 | Effective allowed sessions restricted to premarket and regular only | **PASS** | Effective market-mover sessions are `_mm_raw_sessions & _MM_SAFE_SESSIONS`, and `_MM_SAFE_SESSIONS` contains only `premarket` and `regular`. |
| 4 | Unsafe configured sessions rejected or ignored with warnings | **PASS** | Unsafe configured tokens are computed as `_mm_raw_sessions - _MM_SAFE_SESSIONS`; when present, `market_mover_unsafe_sessions_warning` is populated with `Unsafe market mover sessions ignored: ...`. Runtime validation still accepts strings, so behavior is ignore-with-warning, not config rejection. |
| 5 | Regular session still requires `time_adjusted_volume_ratio` | **PASS** | In regular session, the Path D volume gate is `time_adjusted`; missing `_ta_ratio` adds `missing_time_adjusted_volume`, and low `_ta_ratio` adds a `ta_vol_..._below_...` blocker. The new tests assert regular uses the time-adjusted gate. |
| 6 | Premarket session still uses `volume_vs_previous_day_ratio` or `dollar_volume` | **PASS** | In premarket, the gate first accepts `_mm_vol_vs_prev >= PAPER_MARKET_MOVER_MIN_PREMARKET_VOLUME_VS_PREV_DAY_RATIO`, then falls back to `_mm_dollar_vol >= PAPER_MARKET_MOVER_MIN_DOLLAR_VOLUME`; otherwise it blocks with `premarket_volume_insufficient`. |
| 7 | No unsafe session can bypass volume gates | **PASS for `market_mover_no_catalyst` Path D** | Unsafe sessions are blocked before the Path D session-specific volume gate runs, leaving `market_mover_entry_volume_gate_type` unset and `eligible` false. The explicit test covers afterhours with an unsafe override. |
| 8 | `PAPER_MARKET_MOVER_ALLOW_RISK_OFF` correctly wired or removed/hidden | **PASS** | The setting remains present in base config and runtime schema, and the patch wires it into Path D. If false and market regime is `risk_off`, the candidate receives `risk_off_blocked`; tests cover both false/block and true/allow behavior. |
| 9 | `fda_regulatory` and other blocked catalysts still hard-block | **PASS** | Existing blocked catalyst types are computed once per tick when the guard is enabled. If any accepted catalyst type is configured as blocked, `hard_rejection` becomes `catalyst_type_blocked:<type>` and `is_no_catalyst_rejection` is forced false, preventing Path D entry. The N1-H1 tests cover `fda_regulatory`. |
| 10 | Strong bearish still hard-blocks | **PASS** | The original strong-bearish hard gate remains before no-catalyst routing, and Path D also has its own `PAPER_MARKET_MOVER_BLOCK_IF_ANY_BEARISH` blocker. The N1-H1 tests cover the Path D bearish blocker. |
| 11 | Existing account gates still apply | **PASS** | Path D still checks the market-mover daily limit, the daily max-loss guard, and `_account.can_enter(...)` before opening a virtual position. Position sizing still uses the configured position-size percentage, paper max position size, and market-mover multiplier. |
| 12 | Shadow scoring still does not control entries | **PASS** | Shadow scoring remains documented and implemented as diagnostic-only before entry evaluation. The patch did not modify shadow-scoring entry controls. |
| 13 | TP/SL/exit behavior was not changed | **PASS** | The latest patch changed only runtime config, simulator session gating, and tests. It did not touch `paper/exits.py` or the simulator exit section. Existing exit code still uses `evaluate_virtual_bracket_exit(...)` with `PAPER_TAKE_PROFIT_PERCENT`, `PAPER_STOP_LOSS_PERCENT`, and `PAPER_MAX_HOLD_MINUTES`. |
| 14 | No Polygon calls were added | **PASS** | The Path D evaluation comments still state no Polygon calls, and the changed block relies on existing quality/scoring/session metadata. The N1-H1 test asserts no `polygon_client` reference appears in the market-mover evaluation block. |
| 15 | No broker/live trading/real orders/AI/LLM/Ollama added | **PASS** | The simulator remains explicitly fake-money/no-broker/no-real-orders. The N1-H1 tests scan simulator source for broker/order/AI/Ollama symbols. |
| 16 | Tests and frontend build pass | **PASS** | `pytest -q tests/test_phase_n1h1.py tests/test_phase_n1.py` passed with 36 tests. `npm run build` in `frontend/dashboard` completed successfully. |
| 17 | N1-H1 safe for fake-money monitoring | **PASS** | Given the immutable session allowlist, runtime override intersection, retained volume/account/catalyst/bearish/risk-off gates, and unchanged fake-money-only execution model, N1-H1 is safe for fake-money monitoring. |

## Patch Evidence

### Safe session hard-blocking

The patch defines a module-level immutable allowlist:

```python
_MM_SAFE_SESSIONS: frozenset[str] = frozenset({"premarket", "regular"})
```

Runtime configuration is normalized, intersected with `_MM_SAFE_SESSIONS`, and any unsafe configured tokens are converted into a warning. Path D then hard-blocks any tick session outside `_MM_SAFE_SESSIONS` before evaluating rank/change/spread/score/volume gates.

This means a runtime override such as `PAPER_MARKET_MOVER_ALLOWED_SESSIONS=afterhours,closed,overnight,unknown` cannot make those sessions eligible. The effective safe set is empty for that override, and the current session is still hard-blocked if it is not `premarket` or `regular`.

### Volume gates remain session-specific

For safe sessions only:

- `regular` uses `PAPER_MARKET_MOVER_MIN_TIME_ADJ_VOLUME_RATIO` against `_ta_ratio`.
- `premarket` uses `volume_vs_previous_day_ratio` first, then `dollar_volume` as fallback.
- Unsafe sessions never reach the volume-gate branch for Path D.

### Catalyst and bearish controls remain hard gates

The existing `PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES` / `PAPER_BLOCKED_CATALYST_TYPES` logic remains before Path D routing. When it fires, `is_no_catalyst_rejection` is set false, preventing market-mover no-catalyst entry. Strong bearish catalyst controls remain both in the shared hard-gate section and in the Path D-specific blocker list.

### Account gates remain in force

The Path D entry branch still requires:

1. Market-mover daily trade count under `PAPER_MARKET_MOVER_MAX_TRADES_PER_DAY`.
2. Daily max-loss guard not triggered.
3. `_account.can_enter(...)` success using the existing max-open-position and max-trades-per-day controls.
4. A valid positive entry price.

### Fake-money boundaries preserved

The latest patch did not add broker/live-order integrations, real-order execution, AI/LLM/Ollama integrations, or new Polygon calls. It also did not alter take-profit, stop-loss, max-hold, or intrabar exit behavior.

## Commands Run

```bash
git show --stat --oneline HEAD
```

```bash
git show --name-only --format='' HEAD
```

```bash
nl -ba backend/paper/simulator.py | sed -n '1018,1098p'
```

```bash
nl -ba backend/paper/simulator.py | sed -n '1095,1142p'
```

```bash
nl -ba backend/paper/simulator.py | sed -n '1289,1357p'
```

```bash
nl -ba backend/paper/runtime_config.py | sed -n '478,578p'
```

```bash
nl -ba backend/core/config.py | sed -n '225,239p'
```

```bash
nl -ba backend/tests/test_phase_n1h1.py | sed -n '219,358p'
```

```bash
pytest -q tests/test_phase_n1h1.py tests/test_phase_n1.py
```

```bash
npm run build
```

## Test Results

- `pytest -q tests/test_phase_n1h1.py tests/test_phase_n1.py` — **PASS**, 36 passed, 1 `StarletteDeprecationWarning` from the environment.
- `npm run build` from `frontend/dashboard` — **PASS**, Next.js production build completed successfully. npm emitted `Unknown env config "http-proxy"`, but the build succeeded.
