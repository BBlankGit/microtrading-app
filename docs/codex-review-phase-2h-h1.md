# Codex Review: Phase 2H-H1 Market Regime All-Failures Patch

Reviewed only the latest Phase 2H-H1 patch, commit `fba2669 Fix market regime all-failures unknown classification`.

## Critical issues

None found.

The patch directly addresses the prior all-symbol market-regime fetch failure problem. Complete per-symbol fetch failure now produces an explicit unknown/unavailable market-regime payload instead of allowing empty data to be scored as `risk_off`.

## Market-regime failure-path assessment

Pass.

- `_build_regime()` now detects `total_fetched == 0` before computing breadth/leaders risk score.
- In that all-failure branch, the returned payload is explicit and non-bearish:
  - `symbols_fetched: []`
  - `symbols_failed: failed`
  - `fetch_ratio: 0.0`
  - `risk.regime: "unknown"`
  - `risk.risk_on_score: None`
  - `risk.confidence: "unknown"`
  - `risk.fetched_count: 0`
  - `risk.warnings` includes a no-symbols-fetched/unavailable warning
  - top-level `error: "No market regime symbols fetched"`
- This all-failure branch returns before `_compute_risk()`, so the previous empty-input score path that could produce `20 -> risk_off` is bypassed.
- Normal non-empty data still flows through `_compute_breadth()`, `_compute_leaders()`, `_data_confidence()`, and `_compute_risk()` as before.
- `_compute_risk()` only gained a `warnings: []` field for response-shape consistency; its scoring thresholds and regime classification logic were not otherwise changed.

The top-level `get_market_regime()` exception fallback still returns `unknown`/`None`/`unknown` if `_build_regime()` itself raises. That path remains non-bearish and acceptable for this scope.

## Monitoring assessment

Pass.

- `/api/monitoring/status` now turns a market-regime top-level `error` into the warning text `Market regime data unavailable — check Polygon API configuration.`
- Because the all-symbol failure payload now sets a top-level `error`, monitoring takes the unavailable-data warning branch before the `risk_off` branch.
- The risk-off monitoring warning remains available for genuine successfully-scored `risk_off` market context, and it still says the regime is observational only and causes no strategy changes.
- Low/unknown confidence without a top-level error still produces an insufficient-symbol-data warning, which is appropriate for partial or degraded data.

## Dashboard behavior

Clear and acceptable; no dashboard patch is required for this H1 fix.

- The dashboard already renders unknown regimes with the neutral gray fallback badge/color instead of red risk-off styling.
- It suppresses the score badge when `risk.risk_on_score` is `null`, which avoids showing a misleading numeric risk score for unavailable data.
- It displays the fetched/failed symbol counts and the top-level error string. For all-symbol failure, this means the panel can show `0 symbols fetched`, the failed count, and `ERR: No market regime symbols fetched`.
- Breadth and leader cards remain populated with empty/placeholder values. This is not ideal as a UX refinement, but it is clear enough because the unknown badge, absent score, failed-symbol count, and error label identify data unavailability.

## Test coverage assessment

Pass.

The patch adds focused tests for the prior untested all-symbol failure path and continues to avoid real Polygon calls.

Covered cases include:

- all fetches fail -> `risk.regime == "unknown"`
- all fetches fail -> `risk.risk_on_score is None`
- all fetches fail -> `risk.confidence == "unknown"`
- all fetches fail -> all requested symbols appear in `symbols_failed`
- all fetches fail -> `fetch_ratio == 0.0`
- all fetches fail -> top-level `error` is present
- all fetches fail -> `risk.warnings` is present
- all fetches fail through `get_market_regime()` -> no crash and unknown regime
- all fetches fail -> not classified as `risk_off`
- monitoring all-fail payload -> no risk-off warning
- monitoring all-fail payload -> unavailable warning present
- normal `_compute_risk()` payload includes `warnings: []`

The all-failure tests monkeypatch `polygon_client.get_ticker_snapshot()` to raise exceptions, so they exercise the failure handling without making real Polygon API calls. The full backend test suite passed locally: `296 passed, 1 warning`.

## Safety assessment

Pass.

- No strategy logic changed in this H1 patch. The latest commit touches only `backend/market/regime.py`, `backend/api/monitoring.py`, and `backend/tests/test_phase2h.py`.
- No broker integration, live trading, real orders, AI/LLM, or real-money execution code was added.
- The market-regime module remains explicitly documented as observational context only.
- The simulator market-regime use remains metadata-only from the previous Phase 2H work; this patch does not change entry, exit, sizing, selection, risk controls, broker behavior, or order execution.

## Whether any patch is still required before market hours

No patch is required before market hours for the Phase 2H-H1 all-failures issue.

The prior critical behavior has been fixed: complete market-regime symbol fetch failure now reports unknown/unavailable data and monitoring warns about unavailable data rather than bearish market context. Optional future UX cleanup could hide or de-emphasize empty breadth/leader detail cards when market-regime data is unavailable, but that is not a pre-market blocker.
