# Codex Review — Phase M1 ETF Proxy Market Trend Momentum

Review target: latest M1 patch (`0ef3471 Add ETF proxy market trend momentum`) on `BBlankGit/microtrading-app`.

Review date: 2026-06-11.

## Verdict

**Conditionally approved for fake-money monitoring.** The patch implements an ETF-proxy rolling market-trend layer without adding futures, provider keys, heavy universe jobs, broker/live-order paths, TP/SL/exit changes, or LLM calls. Backend tests and the frontend production build pass locally.

Two behavior notes should be tracked before relying on the adjustment beyond monitoring:

1. **Trend adjustment flows into legacy momentum mode as well as no-catalyst momentum.** The simulator mutates the shared per-tick `risk_on_score` before both `evaluate_momentum_entry()` and `evaluate_no_catalyst_entry()` consume it. If M1 was intended only for no-catalyst and market-mover risk context, this is broader than intended.
2. **Market-mover risk-off gating does not actually use the trend-adjusted score.** The market-mover gate checks the regime label (`risk_off`) rather than the adjusted `risk_on_score`, so the comment/commit claim that market-mover paths pick up the adjusted score is not fully true.

## Scope reviewed

Only the latest M1 patch was reviewed. Changed files in the patch:

- `backend/api/market_trend.py`
- `backend/api/monitoring.py`
- `backend/core/config.py`
- `backend/main.py`
- `backend/market/regime.py`
- `backend/market/trend.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase_m1.py`
- `frontend/dashboard/app/page.tsx`

## Checklist review

| # | Review focus | Result | Notes |
|---:|---|---|---|
| 1 | Market trend uses rolling snapshots, not only instant values | Pass | `backend/market/trend.py` stores snapshots in an in-memory `deque`, records at a configured interval, and prunes by configured history minutes. `backend/market/regime.py` records after successful regime builds. |
| 2 | 5m/10m/15m deltas calculated correctly | Pass with caveat | Deltas are computed as latest `risk_on_score`/ETF `change_percent` minus the closest snapshot at or before the target age. This is correct for rolling deltas of the regime score and daily percent-change proxy values. Caveat: if enough snapshots exist but none are old enough for 5m/10m, missing deltas become zero in classification. |
| 3 | Improving/deteriorating/flat/unknown classification reasonable | Pass with caveat | Thresholds are transparent and asymmetric in a reasonable risk-control way (+8 max improvement, -10 max deterioration). Caveat: classification uses risk score and QQQ deltas only; SPY/IWM are exposed but do not drive direction. Unknown is based on snapshot count, not whether a requested window is available. |
| 4 | True futures are not falsely claimed as available | Pass | API docstring and payload set `futures_available=false` and `provider_status=using_etf_proxy`; warnings explicitly say true Nasdaq futures are not available/configured. |
| 5 | ETF proxy source clearly labeled | Pass | Source is configured as `etf_proxy`, returned by API, shown in dashboard, and embedded in candidate rows. |
| 6 | QQQ/SPY/IWM primary proxies | Pass | Defaults are `QQQ,SPY,IWM`, and snapshot capture iterates those primary symbols. |
| 7 | Leveraged ETFs TQQQ/SQQQ visibility-only unless explicitly enabled | Pass for default behavior | Defaults list `TQQQ,SQQQ` as optional proxies and keep `MARKET_TREND_INCLUDE_LEVERAGED_PROXIES_IN_SCORE=False`. I did not find scoring use of leveraged proxies in this patch. |
| 8 | No new futures/provider dependency or key | Pass | No dependency files changed and no futures/provider key was introduced. The patch reuses existing regime data. |
| 9 | No heavy 5,000-symbol job added | Pass | The changed code records regime snapshots and dashboard/API fields only; no new universe-wide or 5,000-symbol fetch job appears in the M1 diff. |
| 10 | Trend adjustment transparent and does not create entries alone | Pass | The trend overlay exposes before/after score, direction, strength, adjustment, and reason. It can only affect entry eligibility through existing gates; it does not independently create an entry path. |
| 11 | No-catalyst and market-mover gates use trend-adjusted risk only where intended | Needs follow-up | No-catalyst uses the adjusted score because `_tick_regime["risk_on_score"]` is mutated before `evaluate_no_catalyst_entry()`. Legacy momentum also uses the adjusted score through the same shared object. Market-mover risk-off logic checks `_tick_regime["regime"] == "risk_off"`, so it does not use the adjusted risk score. |
| 12 | Catalyst path not hard-blocked by trend | Pass | The trend change is applied to the regime object used by fallback evaluators. Catalyst scoring/hard-rejection logic does not consume market-trend direction/adjustment as a hard block. |
| 13 | Dashboard/API expose source, provider_status, deltas, direction, strength, adjustment, reason | Pass | `/api/market/trend` returns the full payload. The dashboard fetches it and renders provider/source, deltas, direction, strength, adjustment, and reason. Monitoring status exposes a compact summary. |
| 14 | Candidate output exposes market trend fields | Pass | Candidate rows now include enabled/source/direction/strength/adjustment/reason and before/after regime score fields. |
| 15 | No TP/SL/exit behavior changed | Pass | The simulator diff only adds pre-entry trend overlay and candidate telemetry fields; no exit logic hunks were changed. |
| 16 | No broker/live trading/real orders added | Pass | M1 code comments and API docstrings explicitly remain read-only/fake-money; no broker/live-order modules or calls were added in the changed files. |
| 17 | No OpenAI/Anthropic/Ollama/LLM calls added | Pass | `backend/market/trend.py` imports only stdlib plus settings, and M1 tests AST-check no forbidden AI/LLM imports in the trend module. No LLM package/dependency changes were present. |
| 18 | Backend tests and frontend build pass | Pass | `pytest backend/tests/test_phase_m1.py`, full backend `pytest`, and `npm run build` in `frontend/dashboard` all passed. |
| 19 | M1 safe for fake-money monitoring | Pass with follow-up notes | Safe for monitoring/fake-money use. Before treating it as strategy-impacting, clarify intended consumers of adjusted risk (no-catalyst only vs. momentum/market-mover) and consider returning `unknown` until a real window-aged snapshot exists. |

## Detailed observations

### Rolling snapshots and deltas

- The trend layer uses `_history: deque[dict]`, guarded by `_last_snapshot_time`, and only records if `MARKET_TREND_ENABLED` is true and the configured interval has elapsed.
- Each snapshot captures `risk_on_score`, regime metadata, breadth, leader count, and QQQ/SPY/IWM `change_percent`/price values from the existing market-regime leader data.
- `_snapshot_at_or_before()` walks newest-to-oldest and selects the nearest snapshot whose age is at least the requested window, which is the right approach for sparse minute-level snapshots.
- Delta values are calculated as `latest - old` and rounded to three decimals.

### Classification

- Classification thresholds are explicit and easy to reason about:
  - Strong improving: `risk_delta_10m >= +10` or `qqq_delta_10m >= +0.40%` → `+8`.
  - Moderate improving: `risk_delta_10m >= +5` or `qqq_delta_10m >= +0.25%` → `+4`.
  - Weak improving: `risk_delta_5m > 0` or `qqq_delta_5m > +0.10%` → `+2`.
  - Strong deteriorating: `risk_delta_10m <= -10` or `qqq_delta_10m <= -0.40%` → `-10`.
  - Moderate deteriorating: `risk_delta_10m <= -5` or `qqq_delta_10m <= -0.25%` → `-6`.
  - Weak deteriorating: `risk_delta_5m < 0` or `qqq_delta_5m < -0.10%` → `-3`.
  - Else flat → `0`.
- The adjustment is clamped through the final score calculation to the range `0..100`.
- Main caveat: `unknown` is based only on `MARKET_TREND_MIN_SNAPSHOTS`. If there are three 1-minute snapshots but no 5-minute-aged snapshot, missing deltas are normalized to `0.0` and the trend can be classified as `flat` instead of `unknown/collecting`.

### ETF proxy/futures/provider posture

- The patch does not add a futures provider, futures dependency, or new API key.
- Provider status is fixed to `using_etf_proxy` and `futures_available` is always false for this phase.
- The dashboard text explicitly says true Nasdaq/SPX futures are not configured/available and that QQQ/SPY/IWM are the proxies.

### Entry-path impact

- The implementation is transparent: the raw market regime score is preserved as `risk_on_score_before_trend`, and the candidate/API/dashboard surfaces before/after trend-adjusted scores.
- Trend does not introduce a standalone entry path.
- Catalyst entries are not blocked by trend.
- Follow-up needed: the adjusted score is applied by mutating `_tick_regime["risk_on_score"]`. Because the same `_tick_regime` is passed to legacy momentum and no-catalyst evaluators, both can consume the adjusted score. The market-mover risk-off gate checks the unadjusted `regime` label, so it does not actually consume trend-adjusted risk score.

## Tests/checks run

- `pytest backend/tests/test_phase_m1.py` — **13 passed**, 1 warning.
- `pytest` from `backend/` — **1167 passed, 2 skipped**, 2 warnings.
- `npm run build` from `frontend/dashboard/` — **passed**; production build completed successfully. npm emitted a warning about unknown env config `http-proxy`, but the build succeeded.
