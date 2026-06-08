# Codex Review — Phase 2L-H4 Non-Finite Float Readiness JSON-Safety

Reviewed patch: `76b5794` (`Handle non-finite floats in readiness JSON safety`)

## Critical issues

None found.

The Phase 2L-H4 patch addresses the strict JSON serialization failure mode introduced by `NaN`, `Infinity`, and `-Infinity` values in readiness details. I did not find any required code patch before market hours.

## JSON-safety assessment

Pass.

- `make_json_safe` now handles JSON primitives explicitly and checks floats with `math.isfinite`.
- Finite floats are preserved.
- `NaN`, `Infinity`, and `-Infinity` are converted to `None`, which serializes as JSON `null`.
- The implementation keeps the recursive protections from the prior patch:
  - `datetime` and `date` are converted to ISO strings.
  - `dict` values are recursively sanitized.
  - `list`, `tuple`, `set`, and `frozenset` are converted to recursively sanitized lists.
  - Remaining unsupported objects are converted through `redact_sensitive_error`.
  - The outer `try`/`except` still prevents sanitizer crashes from escaping.

This is sufficient for Starlette/FastAPI strict JSON serialization because the values returned by the readiness endpoints are passed through `make_json_safe`, and the H4 tests explicitly verify `json.dumps(..., allow_nan=False)` for the sanitizer and endpoint response payloads.

One non-blocking observation: dict keys are still converted with `str(k)` rather than redacted. That is not a regression in this patch and is not required for the Phase 2L-H4 non-finite-float readiness issue, but if future readiness details could place secrets in keys, key redaction would be a useful defense-in-depth follow-up.

## Route crash-proofing assessment

Pass.

- `/api/readiness/session` sanitizes raw check details through `_sanitize_checks`, computes status from sanitized checks, and returns the final assembled response through `make_json_safe`.
- `/api/readiness/session/compact` also sanitizes raw checks before aggregation and returns the final compact response through `make_json_safe`.
- Both routes retain protected fallback responses when check execution or response assembly fails.
- Endpoint-level tests cover nested non-serializable details and non-finite floats for both readiness routes.
- The compact route does not return check details in its public response, but the test is still meaningful because nested bad details must pass through `_sanitize_checks`, `_overall_status`, and `_recommended_actions` without triggering a 500.

I did not find a route-level strict JSON serialization crash remaining for nested unsupported details or non-finite floats in check `details`.

## Redaction assessment

Pass, with improvement.

- Existing exception redaction is preserved through `redact_sensitive_error`.
- H4 improves redaction by applying redaction to string values passed through `make_json_safe` when those strings match configured secret patterns.
- Existing tests continue to cover Polygon exception redaction and mixed-form secret redaction.
- New H4 coverage verifies `make_json_safe` redacts primitive string values containing secret-like patterns.

As noted above, dict keys are not redacted, but that appears outside the current patch requirement and is not a blocker for market-hours readiness.

## Test coverage assessment

Pass.

The H4 tests cover the requested risk areas:

- Unit-level non-finite float handling:
  - `float("nan")` -> `None`
  - `float("inf")` -> `None`
  - `float("-inf")` -> `None`
  - finite float preserved
  - strict `json.dumps(..., allow_nan=False)` succeeds
- Endpoint-level `/api/readiness/session` handling of nested `NaN` and `Infinity` details with HTTP 200.
- Endpoint-level `/api/readiness/session/compact` handling of nested `NaN` and `Infinity` details with HTTP 200.
- Endpoint-level nested non-serializable detail structures for both routes, including `object()`, `datetime`, `set`, `tuple`, `frozenset`, and nested non-finite floats.
- String redaction through `make_json_safe`.

Validation run:

```text
pytest backend/tests/test_phase2l.py -q
75 passed, 1 warning in 0.90s
```

The warning is an environment/dependency deprecation warning from FastAPI/Starlette test client usage and is unrelated to the H4 JSON-safety patch.

## Safety assessment

Pass.

I reviewed the latest Phase 2L-H4 diff and searched the touched readiness code/tests for broker, live-trading, order-execution, and AI/LLM indicators. The patch only imports `math`, adjusts readiness JSON sanitization, and adds tests. It does not add broker integration, live trading, real orders, AI/LLM behavior, or real-money execution.

The readiness module continues to state the safety boundaries clearly: no broker, no live trading, no real orders, no real-money execution, and no AI/LLM. The safety invariant check still hard-codes `execution_enabled` to `False` and fails if simulator status reports live trading or broker connectivity.

## Whether any patch is still required before market hours

No patch is required before market hours for Phase 2L-H4.

The non-finite float readiness JSON-safety issue appears resolved, endpoint crash-proofing is covered at the route level, redaction is preserved and improved for string values, and no prohibited trading/AI capabilities were introduced.
