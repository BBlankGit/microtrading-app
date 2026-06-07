# Codex Review — Phase 2L-H3 JSON-Safe Readiness Response Patch

## Critical issues

1. **JSON safety is still incomplete for non-finite floats (`NaN`, `Infinity`, `-Infinity`).**
   - `make_json_safe()` currently returns every `float` unchanged.
   - Starlette/FastAPI JSON responses reject non-finite floats with `ValueError: Out of range float values are not JSON compliant` before a response can be emitted.
   - I reproduced this by patching `_run_all_checks()` to return a readiness check with `details: {"bad": float("nan")}` and calling `/api/readiness/session`; the request raised `ValueError` instead of returning a crash-proof JSON response.
   - This means the patch resolves common nested Python object serialization failures, but the readiness response is **not yet fully JSON-safe before FastAPI serialization**.

2. **Endpoint tests do not cover nested non-serializable details for both endpoints.**
   - The new endpoint tests use a shallow `object()` in `details`.
   - Nested `object()` coverage exists only in the direct `make_json_safe()` unit test.
   - The compact endpoint test also does not assert that sanitized details are present in the compact payload, because the compact response does not return checks/details; it only verifies that `_sanitize_checks()` can be traversed without crashing.

## JSON-safety assessment

- The patch adds `make_json_safe()`, which recursively handles `None`, booleans, integers, finite-looking floats, strings, `datetime`, `date`, dictionaries, lists, tuples, sets, frozensets, and unknown objects.
- `_sanitize_checks()` now applies `make_json_safe()` to check `details`, which addresses nested `object()`, `datetime`, `set`, and `tuple` values inside details.
- Both route handlers now wrap their normal and fallback response dictionaries with `make_json_safe()` before returning to FastAPI.
- However, the implementation is **not fully JSON-safe** because it leaves `float("nan")`, `float("inf")`, and `float("-inf")` unchanged. These are Python floats but are not valid JSON values under Starlette's strict JSON renderer.

## Route crash-proofing assessment

- `/api/readiness/session` remains route-level crash-proof for ordinary check-runner failures and for nested non-serializable objects like `object()`, `datetime`, `set`, and `tuple` in check details.
- `/api/readiness/session/compact` remains route-level crash-proof for ordinary check-runner failures and for malformed/non-serializable check details traversed during sanitization.
- The outer `try` blocks and fallback bodies are preserved for both endpoints.
- The crash-proofing claim has one remaining exception: non-finite floats can still escape `make_json_safe()` and fail during FastAPI/Starlette serialization.

## Redaction assessment

- Existing `redact_sensitive_error()` coverage is preserved for exception/error string paths.
- Unknown non-serializable objects are converted through `redact_sensitive_error()`, so secret-like values exposed by an object's `__str__()` are redacted before becoming a JSON string.
- The patch does not redact ordinary primitive string values during recursive sanitization. If a future check placed a secret-like primitive string directly into `details`, `make_json_safe()` would return that string unchanged. Current readiness checks generally use redacted errors or operational booleans/counts, so this is not a newly introduced broker/trading risk, but it is a residual redaction gap for arbitrary future details.

## Test coverage assessment

- The Phase 2L test file passes locally.
- Added tests verify:
  - `/api/readiness/session` returns HTTP 200 for a check detail containing a shallow `object()`.
  - `/api/readiness/session/compact` returns HTTP 200 for a check detail containing a shallow `object()`.
  - `make_json_safe()` recursively converts a nested `object()`, `datetime`, `set`, and `tuple` into values accepted by `json.dumps()`.
- Gaps:
  - No endpoint-level test uses nested non-serializable details for `/api/readiness/session`.
  - No endpoint-level test uses nested non-serializable details for `/api/readiness/session/compact`.
  - No test covers non-finite floats (`NaN`, `Infinity`, `-Infinity`) despite those values still causing serialization failure.
  - No test asserts redaction through `make_json_safe()` for an unknown object whose string representation contains token/password/secret-like content.

## Safety assessment

- The reviewed patch only changes readiness response sanitization and Phase 2L tests.
- I found no added broker integration, live trading enablement, real order placement, AI/LLM integration, or real-money execution path.
- The module-level safety disclaimer remains present, and readiness remains framed as fake-money simulation monitoring only.
- Existing AST/import safety tests still scan for forbidden broker/AI imports and execution-related call names.

## Patch required before market hours?

**Yes.** A small follow-up patch is still required before market hours if the goal is complete JSON-safe, route-level crash-proof readiness responses. At minimum, `make_json_safe()` should coerce non-finite floats to `None` or a redacted/string sentinel before returning data to FastAPI, and tests should add endpoint-level nested detail coverage plus non-finite float coverage for `/api/readiness/session` and, where applicable, `/api/readiness/session/compact`.
