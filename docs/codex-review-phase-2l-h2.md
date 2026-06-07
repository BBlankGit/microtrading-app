# Codex Review — Phase 2L-H2 Strict Readiness Hardening

Reviewed patch: `4b569ee Make readiness routes fully crash proof and expand redaction`

## Critical issues

1. **Strict route-level crash-proofing still has one serialization escape hatch.**
   - The H2 patch adds an outer `try/except` around both route handlers' response aggregation/assembly and sanitizes top-level malformed check objects before aggregation.
   - However, `_sanitize_checks(...)` preserves `details` whenever it is a `dict` without coercing nested values into JSON-safe primitives. If a check returns a `details` dict containing a non-serializable object, the handler successfully returns a Python dict, but FastAPI response serialization can still raise after the route function returns. That exception is outside the route-level `try/except`, so the endpoint is not fully crash-proof under the strict definition.
   - I verified this with an ad hoc TestClient probe that patched `_run_all_checks` to return `[{"name":"x","status":"pass","message":"ok","details":{"bad": object()}}]`; `/api/readiness/session` raised a FastAPI `jsonable_encoder` `ValueError` instead of returning HTTP 200. This is a real residual readiness hardening gap if malformed check output includes non-JSON-safe nested data.
   - **Recommended fix before market hours:** make check sanitization recursively JSON-safe, or explicitly pass assembled responses through a safe encoder inside the guarded route block and fall back to the internal not-ready response on encoding failure.

No broker/live-trading/real-order/AI/LLM critical issue was found in the latest Phase 2L-H2 patch.

## Route crash-proofing assessment

- `/api/readiness/session` is substantially stronger than H1:
  - `_market_session_now()` is covered by an outer safety wrapper with a safe default market-session payload.
  - `_run_all_checks(market_open)` has an inner runner-failure fallback that returns `overall_status: not_ready`, a synthetic `readiness_internal` failed check, `summary.fail: 1`, recommended action, and the standard disclaimer.
  - Aggregation and response assembly now happen inside the outer route wrapper, so `_overall_status(...)`, summary counting, simulator state lookup, and `_recommended_actions(...)` failures are converted into the safe not-ready fallback instead of bubbling out of the handler.
- `/api/readiness/session/compact` is also substantially stronger than H1:
  - `_market_session_now()` is covered by the outer safety wrapper with `safe_market_open = False` fallback.
  - `_run_all_checks(market_open)` has an inner runner-failure fallback with `overall_status: not_ready`, safe false/null compact fields, `fail_count: 1`, and recommended action.
  - Aggregation, count assembly, compact auxiliary lookups, and `_recommended_actions(...)` now sit inside the outer wrapper and fall back to a not-ready compact payload on route assembly failure.
- Malformed top-level check objects are handled well for aggregation:
  - Non-dict items become failed `malformed_check` entries.
  - Missing or invalid `name` becomes `unknown_check`.
  - Missing or invalid `status` becomes `fail`.
  - Non-string `message` becomes an empty string.
  - Non-dict `details` becomes `{}`.
- **Residual strictness gap:** nested non-serializable values inside an otherwise-dict `details` field can still fail during FastAPI serialization after the handler returns, which bypasses the route's `try/except`. Because the user explicitly asked for route-level crash-proofing including response assembly/aggregation, I do not consider H2 fully strict-ready until nested response payloads are JSON-sanitized.

## Error redaction assessment

- Redaction coverage is meaningfully expanded and now covers the requested formats:
  - Equal-sign forms for `apiKey`/`api_key`/`api-key`, `access_token`, `refresh_token`, `client_secret`, generic `token`, `password`, and `secret`.
  - URL query `?key=` and `&key=` forms.
  - `Authorization: Bearer ...` and generic `Bearer ...` forms.
  - Colon/JSON-style forms such as `password: value`, `"password": "value"`, `'password': 'value'`, `client_secret: value`, `"client_secret": "value"`, `"refresh_token": "value"`, `apiKey: value`, and `"api_key": "value"`.
- The full route's runner-failure and response-assembly fallback include redacted exception text in `details.error`.
- The compact route does not include exception text in either runner or assembly fallback payloads, which avoids compact response leakage by omission.
- Redaction is still pattern-based rather than a guarantee for every conceivable credential label, but for the scope requested here — equals, query, bearer, colon, and JSON-style secret values — the H2 patch covers the important cases and tests them.

## Test coverage assessment

- HTTP 200 behavior for runner failures is covered:
  - Full route runner failure asserts status `200`, `overall_status == "not_ready"`, a `readiness_internal` check, and no injected secret leak.
  - Compact route runner failure asserts status `200`, `overall_status == "not_ready"`, `fail_count >= 1`, and no injected secret leak.
- HTTP 200 behavior for aggregation/assembly failures is covered:
  - Full route patches `_overall_status(...)` to raise after `_run_all_checks(...)` succeeds and asserts status `200`, `overall_status == "not_ready"`, `readiness_internal`, and no injected secret leak.
  - Compact route patches `_recommended_actions(...)` to raise after `_run_all_checks(...)` succeeds and asserts status `200`, `overall_status == "not_ready"`, `fail_count >= 1`, and no injected secret leak.
- Malformed top-level check-object tests cover non-dict checks, missing status, missing name, and valid pass-through checks.
- Colon/JSON redaction tests now cover password, single-quoted password, client secret, refresh token, and API key variants.
- Polygon call isolation is acceptable in the Phase 2L test file:
  - Endpoint tests either patch `_run_all_checks(...)`, patch `_check_polygon_data(...)`, or patch `data.polygon_client.get_ticker_snapshot(...)`.
  - The direct Polygon-data tests patch the Polygon client function with fake async implementations or forced exceptions.
  - The dedicated unreachable-Polygon test patches the Polygon client to raise locally and asserts the endpoint still returns 200.
- **Coverage gap matching the critical issue:** there is no test that injects a malformed check with a dict `details` containing a non-JSON-serializable nested value and asserts the route still returns HTTP 200 with a not-ready/fail payload.
- I ran `pytest backend/tests/test_phase2l.py -q`; all 66 tests passed with one Starlette/httpx deprecation warning.

## Safety assessment

- The latest H2 patch only changes `backend/api/readiness.py` and `backend/tests/test_phase2l.py`.
- I found no new broker integration, live trading enablement, real-order path, AI/LLM call, or real-money execution path in the H2 patch.
- The readiness module continues to state that it is observational/fake-money only and does not enable broker trading or real orders.
- The safety invariant check remains defensive: it fails readiness if simulator status reports `live_trading_enabled` or `broker_connected`, and it reports `execution_enabled: False`.
- The Phase 2L tests retain AST/import and source-name guards against broker/AI imports and execution call names in `backend/api/readiness.py`.

## Whether any patch is still required before market hours

**Yes — one small follow-up patch is still required if the market-hours acceptance bar is strict route-level crash-proofing.**

The H2 patch resolves the H1 gaps for runner failures, malformed top-level check objects, aggregation exceptions, colon/JSON redaction tests, and no-real-Polygon test isolation. The remaining blocker is narrower: make the final response payload JSON-safe before FastAPI serialization so malformed nested `details` values cannot bypass the route-level fallback.

Recommended pre-market patch:

1. Recursively sanitize check `details` and any other response payload values to JSON-safe primitives, or validate the final assembled response with FastAPI/json encoding inside the guarded block.
2. Add tests for `/api/readiness/session` and `/api/readiness/session/compact` where `_run_all_checks(...)` returns a check containing `details: {"bad": object()}` and assert HTTP 200 with `not_ready`/fail fallback.

After that narrow fix, I would consider Phase 2L-H2 strict readiness hardening ready for market-hours use.
