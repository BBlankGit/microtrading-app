# Codex Review — Phase 2H Market Regime Monitor

## Scope reviewed

Reviewed only the latest Phase 2H commit, `ba62c3c Implement Phase 2H market regime monitor`.

Files changed by the Phase 2H commit:

- `backend/api/market_regime.py`
- `backend/api/monitoring.py`
- `backend/api/paper.py`
- `backend/core/config.py`
- `backend/main.py`
- `backend/market/__init__.py`
- `backend/market/regime.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase2h.py`
- `frontend/dashboard/app/page.tsx`

Verification command run:

- `pytest tests/test_phase2h.py` from `backend/` — 45 passed, 1 third-party Starlette/httpx deprecation warning.

## Critical issues

### 1. All per-symbol Polygon failures can report `risk_off` instead of `unknown`

`backend/market/regime.py` catches individual Polygon snapshot failures inside `_fetch_symbol()` and records those symbols as failed. That avoids crashes, which is good. However, if every symbol fails, `_build_regime()` still calls `_compute_risk()` with empty breadth and leaders. `_compute_risk()` assigns a default leader component of 20 points, producing `risk_on_score = 20` and therefore `regime = "risk_off"` under the default `MARKET_REGIME_MAX_RISK_OFF_SCORE = 40`.

That means a complete Polygon outage or complete symbol-fetch failure is classified as bearish market context rather than unknown/unavailable data. This does not alter trading decisions, but it does violate the Phase 2H requirement that Polygon failures degrade to `unknown`/warnings instead of misleading regime classification.

Expected behavior for zero fetched symbols should be closer to:

- `risk.regime = "unknown"`
- `risk.risk_on_score = None` or clearly unavailable
- `risk.confidence = "unknown"`
- non-fatal warning/error metadata indicating no symbols were fetched

This gap is not covered by the current tests. `test_get_market_regime_returns_error_payload_on_exception` covers a top-level `_build_regime()` exception, and `test_build_regime_handles_partial_failures` covers partial failures, but there is no test where every configured Polygon snapshot call fails inside `_fetch_symbol()`.

## Non-blocking issues

### 1. Market-regime cache is shallow-copied

`get_market_regime()` returns `dict(_cache)`, which protects only the top-level dictionary. Nested structures such as `risk`, `breadth`, `leaders`, and symbol arrays are still shared references. Current callers appear read-only, so this is not an immediate bug, but a defensive deep copy or immutable response construction would reduce accidental cache mutation risk.

### 2. No single-flight guard around cold-cache refreshes

The module-level TTL cache prevents repeated REST calls after a successful refresh, but concurrent cold-cache callers can all enter `_build_regime()` before `_cache_time` is updated. Because `/api/paper/dashboard`, `/api/monitoring/status`, simulator ticks, and `/api/market/regime` can all request regime data, a burst at startup or right after TTL expiry can duplicate Polygon calls.

This is non-blocking at the current default of 10 symbols and 60-second TTL, but an `asyncio.Lock` or single-flight refresh guard would make API-load behavior more predictable.

### 3. POST refresh intentionally bypasses TTL

`/api/market/regime/refresh` correctly requires admin auth and force-refreshes data. Because it bypasses TTL by design, operational guidance should avoid repeatedly polling this endpoint. The normal GET/dashboard/status paths should be used for routine observation.

## Market regime assessment

Overall assessment: mostly correct and observational, with one important failure-classification issue.

Positive findings:

- The new market-regime module is explicitly documented as observational only and states that it does not affect entry/exit logic.
- The scoring algorithm is deterministic: it uses configured symbols, Polygon snapshot fields, fixed breadth thresholds, fixed leader symbols (`SPY`, `QQQ`, `IWM`), and configured score cutoffs.
- No broker integration, live-trading path, real orders, AI/LLM integration, or real-money execution was added in the reviewed Phase 2H changes.
- The simulator only appends market-regime metadata to the tick result after existing journal handling; it does not use regime values to filter candidates, size positions, enter trades, exit trades, or change risk controls.

Concern:

- Complete per-symbol fetch failure can become `risk_off` instead of `unknown`, as described in Critical issues.

## API assessment

Overall assessment: API routes are implemented correctly except for the all-failures classification inherited from the regime engine.

Positive findings:

- `GET /api/market/regime` is read-only and unauthenticated, which is appropriate for observational context.
- `POST /api/market/regime/refresh` is mounted under the same router and calls `get_market_regime(force_refresh=True)`.
- The refresh route depends on `require_admin_token`, so it requires `ADMIN_API_TOKEN` when the endpoint is enabled or disabled. FastAPI dependencies are evaluated before the route body, so the disabled branch does not bypass auth.
- Disabled-mode responses clearly return `enabled: false` and avoid calling the regime engine.
- Router registration in `backend/main.py` exposes the API under the expected `/api/market/regime` prefix.

Concern:

- The API will surface the engine's misleading all-failure `risk_off` result until the engine is patched.

## Dashboard assessment

Overall assessment: clear and safe.

Positive findings:

- The dashboard includes a dedicated Market Regime section.
- The section header says `observational only · breadth/risk context · no strategy changes`.
- The panel shows regime, score, confidence, fetched/failed symbol counts, breadth details, key leader details, timestamp, and the backend disclaimer.
- Error display is visible when an error field is present.
- The top dashboard label remains fake-money/no-broker/no-live-trading/no-real-orders and was updated to Phase 2H.

Concern:

- If the backend returns all-failure `risk_off` without an `error` field, the dashboard will faithfully show `RISK OFF` rather than clearly indicating unavailable/unknown data. This is a backend classification issue rather than a dashboard rendering issue.

## Monitoring assessment

Overall assessment: includes useful market-regime summary and non-fatal warnings, but inherits the all-failures classification issue.

Positive findings:

- `/api/monitoring/status` now includes a `market_regime` summary with enabled state, regime, score, confidence, timestamp, fetched/failed counts, and error metadata.
- Regime errors are handled as warnings and do not make the monitoring endpoint crash.
- `risk_off`, `unknown` confidence, and `low` confidence produce warnings.
- The risk-off warning explicitly says the regime is observational only and causes no strategy changes.

Concern:

- Because complete per-symbol failures do not set a top-level `error` and are classified by `_compute_risk()` as `risk_off`, monitoring may warn about `RISK_OFF` instead of warning that market-regime data is unavailable/unknown due to failed Polygon fetches.

## Test coverage assessment

Overall assessment: strong coverage for most Phase 2H behavior, with one missing edge case.

Positive findings:

- Tests avoid real Polygon calls by monkeypatching `polygon_client.get_ticker_snapshot()` and related simulator data calls.
- Risk-on, risk-off, neutral, confidence, cache hit, cache miss, force refresh, top-level error payload, partial Polygon failure, API shape, refresh auth requirement, monitoring warnings, dashboard payload inclusion, simulator payload inclusion, and disabled behavior are covered.
- Safety tests scan the new regime files for broker/order/AI-related tokens.
- `pytest tests/test_phase2h.py` passed: 45 tests passed with only a third-party deprecation warning.

Missing coverage:

- Add a test where every configured symbol raises from `polygon_client.get_ticker_snapshot()` inside `_build_regime()`. The expected result should be `risk.regime == "unknown"`, `confidence == "unknown"`, all symbols in `symbols_failed`, no crash, and a monitoring warning that data is unavailable/low-confidence rather than a bearish market warning.

## Operational/API-load assessment

Overall assessment: acceptable for fake-money simulation, with modest improvement opportunities.

Positive findings:

- The default symbol list is small: 10 ETFs.
- The default TTL is 60 seconds, which prevents routine dashboard/status/simulator calls from making a fresh REST call every time.
- Normal GET/status/dashboard/simulator paths share the same module-level cache.
- Polygon failures are caught per symbol and at the top-level build wrapper, so routine outages should not crash the app.

Operational cautions:

- Cold starts, TTL expiry bursts, or simultaneous dashboard/status/tick calls can duplicate refreshes because there is no single-flight lock.
- Admin refresh bypasses TTL and should not be polled.
- If `MARKET_REGIME_ENABLED=True` in production-like simulation, expect up to 10 Polygon snapshot calls per cache refresh under normal serialized access, with possible duplicates under concurrency.

## Whether Phase 2H is safe to run tomorrow as fake-money simulation

Yes, Phase 2H appears safe to run tomorrow as fake-money simulation.

Reasoning:

- No broker integration, live trading, real order placement, AI/LLM integration, or real-money execution was added by the reviewed Phase 2H changes.
- Market regime data is added as observational metadata and UI/monitoring context only.
- Strategy entry/exit logic and simulator trade decision logic were not changed to depend on market-regime output.
- Polygon/API failures are generally non-fatal and should not crash the simulator or monitoring endpoints.

Caveat:

- During a Polygon outage or all-symbol fetch failure, the regime may be displayed as `risk_off` rather than `unknown`. That is misleading operational context but does not create real-money execution risk and does not change fake-money strategy behavior.

## Whether any patch is required before market hours

A small patch is recommended before market hours for Phase 2H correctness/acceptance, but not because of real-money execution risk.

Recommended patch:

1. In `backend/market/regime.py`, when `total_fetched == 0` or `confidence == "unknown"` due to no usable snapshots, return an explicit unknown-risk payload instead of calling `_compute_risk()` into a default score.
2. Add a top-level non-fatal warning/error marker such as `error: "No market regime symbols fetched"` or a structured `warnings` array.
3. Add tests covering all per-symbol failures and the monitoring warning produced by that state.

If the question is strictly whether fake-money simulation can run safely without this patch, the answer is yes. If the question is whether Phase 2H fully satisfies the requested failure-degradation behavior before market hours, the answer is no: patch the all-failures path first.
