# Codex Review — Phase M1-H1 Market Trend Consumer Clarification

Date: 2026-06-11

Reviewed patch: `55be533 Clarify market trend consumers` (`HEAD~1..HEAD`)

Scope reviewed: latest M1-H1 patch only.

## Verdict

**Conditional pass for fake-money monitoring, with two follow-up issues.** The patch preserves the raw market regime, adds a separate trend-adjusted regime, routes legacy/no-catalyst/market-mover consumers mostly as intended, exposes the new state in API/dashboard, and keeps the work fake-money only with no broker, futures-provider, real-order, or LLM dependency additions.

However, I found two audit/config-consumer gaps that should be fixed before considering the phase fully complete:

1. **Shadow trend consumer flag is exposed/defaulted but not actually consumed.** `MARKET_TREND_APPLY_TO_SHADOW` defaults to `true` and is included in `trend_consumers`, but `compute_shadow_score(...)` is still always called with raw `_tick_regime`.
2. **Candidate trend-consumer telemetry can mislabel catalyst candidates that are also market-mover-sourced.** A symbol with `_mm_meta` and accepted catalysts follows the catalyst path, but candidate telemetry reports `market_trend_path_name = market_mover` and `market_trend_regime_used = trend_adjusted` when market-mover trend consumption is enabled.

These do **not** add live-trading risk and do **not** change TP/SL/exit behavior, but they reduce audit clarity for exactly the M1-H1 consumer-separation objective.

## Findings

### Finding 1 — Shadow consumer flag is not wired to shadow scoring

**Severity:** Medium

`MARKET_TREND_APPLY_TO_SHADOW` is added with a default of `true` and surfaced via `trend_consumers`, implying shadow scoring consumes trend-adjusted regime by default. The simulator computes `_trend_apply_legacy`, `_trend_apply_no_cat`, and `_trend_apply_mm`, but does not read `_trend_apply_shadow`. Later, shadow scoring is called with `tick_regime=_tick_regime` unconditionally.

**Why this matters:** the dashboard/API can claim `shadow: trend_adjusted`, while the shadow scorer still uses raw regime. This violates the “config flags control trend consumers correctly” and “trend-adjusted regime is separate and auditable” goals for the shadow consumer.

**Suggested fix:** read `MARKET_TREND_APPLY_TO_SHADOW` once per tick and pass `_regime_for(_trend_apply_shadow)` into `compute_shadow_score(...)`. Add a test that patches the flag both ways and verifies the shadow scoring input/regime-sensitive output.

### Finding 2 — Candidate telemetry can report the wrong consuming path/regime for catalyst market-mover symbols

**Severity:** Medium

Candidate telemetry currently treats any candidate with `_mm_meta` as `market_mover` for `market_trend_path_name` and as consuming trend-adjusted regime when `_trend_apply_mm` is enabled. But the actual entry order still sends candidates with accepted catalysts and passing scores through Path A (`entry_mode = catalyst`) before Path D (`market_mover_no_catalyst`). Therefore a market-mover-sourced catalyst candidate can be audited as if the market-mover path consumed adjusted trend, even though the catalyst path was the actual path and is supposed to not be trend-hard-blocked.

**Why this matters:** this weakens the candidate-row answer to “which regime was consumed?” and can make catalyst-path decisions appear trend-adjusted when they were not.

**Suggested fix:** derive candidate trend telemetry from the actual primary path, not just source metadata. For example, default to catalyst/raw when `hard_rejection is None`, use market-mover only when the Path D eligibility condition is the active no-catalyst market-mover path, and use no-catalyst for Path C/B-style no-catalyst evaluation where appropriate. Add a regression test for a full-market-mover symbol with accepted catalysts.

## Checklist Review

### 1. Raw market regime is preserved and not destructively overwritten

**Pass.** The simulator builds `_tick_regime` from `get_market_regime()` and then creates `_tick_regime_adjusted = dict(_tick_regime)` rather than mutating the raw dict. It stores both `result["market_regime"]` and `result["market_regime_adjusted"]` separately.

### 2. Trend-adjusted regime is separate and auditable

**Pass with caveat.** `_tick_regime_adjusted` carries `risk_on_score_before_trend`, adjusted `risk_on_score`, `regime_before_trend`, adjusted `regime`, and embedded `trend` details. The trend overlay returns before/after scores and raw/adjusted labels. Caveat: shadow consumer telemetry claims adjusted consumption but the shadow scorer still receives raw regime.

### 3. Legacy momentum uses raw regime by default

**Pass.** `MARKET_TREND_APPLY_TO_LEGACY_MOMENTUM` defaults to `false`; simulator evaluates legacy momentum with `_regime_for(_trend_apply_legacy)`, which returns raw `_tick_regime` unless the flag is enabled.

### 4. No-catalyst momentum uses trend-adjusted regime by default

**Pass.** `MARKET_TREND_APPLY_TO_NO_CATALYST` defaults to `true`; simulator evaluates no-catalyst momentum with `_regime_for(_trend_apply_no_cat)`.

### 5. Market-mover uses trend-adjusted regime by default

**Pass for the market-mover risk-off gate; telemetry caveat.** `MARKET_TREND_APPLY_TO_MARKET_MOVER` defaults to `true`, and the market-mover risk-off gate uses `_regime_for(_trend_apply_mm)`. Candidate telemetry may over-report market-mover adjusted consumption for catalyst candidates that merely have market-mover source metadata.

### 6. Catalyst path does not hard-block based on trend

**Pass.** The catalyst path entry condition remains `hard_rejection is None and scoring["score_pass"]`. No trend-regime check was added to catalyst hard gates. The new `MARKET_TREND_APPLY_TO_CATALYST` flag is exposed in `trend_consumers` but not used to hard-block catalyst entries.

### 7. Config flags control trend consumers correctly

**Partial.** Legacy, no-catalyst, and market-mover flags control those paths. Catalyst is intentionally non-blocking. Shadow is not correctly wired: the flag is exposed/defaulted but shadow scoring always receives raw `_tick_regime`.

### 8. Market-mover risk-off gate uses adjusted regime when configured

**Pass.** The market-mover risk-off gate chooses `_regime_for(_trend_apply_mm)`, marks `market_mover_regime_used`, and emits an adjusted-specific blocker string when the adjusted regime is risk-off.

### 9. Candidate output shows raw/adjusted regime and which one was consumed

**Partial.** Candidate rows include before/after scores, collecting/window state, consumer config, `market_trend_consumed_by_path`, `market_trend_regime_used`, and market-mover-specific regime fields. But raw and adjusted **labels** are not included on each candidate row, only scores are. Also, path/regime telemetry can be wrong for catalyst candidates with market-mover metadata.

### 10. Collecting/unknown state is returned when snapshots exist but no 5m-aged window exists

**Pass.** `_classify(...)` returns `unknown`/`collecting trend history; no 5m-aged snapshot yet` when minimum snapshots exist but `has_5m_window` is false. Tests cover the three-fresh-snapshot case.

### 11. Missing 10m/15m windows are not silently treated as real zero deltas

**Pass.** `get_trend()` sets `has_window` per window and returns `None` deltas when no aged snapshot exists. `_classify(...)` only evaluates 10m threshold logic when `has_10m_window` is true. Tests cover missing 10m/15m windows returning `None` deltas.

### 12. Dashboard/API expose trend consumers and collecting state

**Pass.** Monitoring summary includes raw/adjusted labels, collecting/window flags, and `trend_consumers`. Dashboard types and panel render collecting state, windows, consumer configuration, and raw/adjusted labels.

### 13. No futures/provider dependency was added

**Pass.** The patch keeps trend source as ETF proxy telemetry and explicitly reports `futures_available: false` / `provider_status: using_etf_proxy`. No new futures provider package/import was introduced in the reviewed diff.

### 14. No TP/SL/exit behavior changed

**Pass.** The reviewed patch does not modify `backend/paper/exits.py` and the simulator exit section remains limited to existing bracket/max-hold behavior.

### 15. No broker/live trading/real orders were added

**Pass.** The patch remains in fake-money simulator/dashboard/test/config/monitoring files. No broker/live trading order placement path was added.

### 16. No OpenAI/Anthropic/Ollama/LLM calls were added

**Pass.** The new M1-H1 test includes an AST guard for forbidden imports in `market/trend.py`, and the reviewed diff did not add LLM calls.

### 17. Backend tests and frontend build pass

**Pass.** Commands run:

```bash
PYTHONPATH=backend pytest backend/tests/test_phase_m1_h1.py backend/tests/test_phase_n1h1.py
npm install
npm run build
```

Results: backend M1-H1/N1-H1 tests passed (`27 passed, 1 warning`), npm dependencies were already up to date, and the Next.js production build completed successfully.

### 18. M1-H1 is safe for fake-money monitoring

**Pass, with audit follow-ups recommended.** The patch does not introduce live trading, broker calls, real orders, LLM calls, TP/SL changes, or futures-provider dependencies. It is safe for fake-money monitoring. The two findings should be addressed to make consumer auditability fully accurate.

## Files Reviewed

- `backend/core/config.py`
- `backend/market/trend.py`
- `backend/paper/simulator.py`
- `backend/api/monitoring.py`
- `frontend/dashboard/app/page.tsx`
- `backend/tests/test_phase_m1_h1.py`
- `backend/tests/test_phase_n1h1.py`

## Verification Commands

```bash
git diff HEAD~1..HEAD -- backend/core/config.py backend/market/trend.py backend/paper/simulator.py backend/api/monitoring.py frontend/dashboard/app/page.tsx backend/tests/test_phase_m1_h1.py backend/tests/test_phase_n1h1.py
rg -n "record_snapshot|build_trend_overlay|market_regime_adjusted|MARKET_TREND_APPLY_TO_CATALYST|MARKET_TREND_APPLY_TO_SHADOW|trend_consumers|adjusted_regime_label|raw_regime_label|risk_on_score_before_trend" backend frontend docs -g '!node_modules'
PYTHONPATH=backend pytest backend/tests/test_phase_m1_h1.py backend/tests/test_phase_n1h1.py
npm install
npm run build
```
