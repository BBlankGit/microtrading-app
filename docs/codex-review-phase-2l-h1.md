# Codex Review — Phase 2L-H1 Readiness Hardening

Reviewed patch: `d5d245a Harden readiness endpoints and redact errors`

## Critical issues

1. **Strict route-level crash-proofing is incomplete.**
   - The new handlers catch exceptions thrown by `_run_all_checks(...)`, so direct runner failure now returns a JSON `not_ready` response instead of propagating a 500.
   - However, both route handlers still perform response aggregation after that guarded block. In the full route, `_overall_status(checks)`, summary construction, and `_recommended_actions(...)` can still raise if a check object is malformed or missing required keys. In the compact route, `_overall_status(checks)`, count construction, and `_recommended_actions(...)` have the same residual risk.
   - This means `/api/readiness/session` and `/api/readiness/session/compact` are **runner-failure hardened**, but not fully route-level crash-proof under the strict meaning of “the route never returns HTTP 500 from readiness assembly failures.”
   - **Recommended before market hours:** add a final route-level safety wrapper around aggregation/response assembly, or validate/sanitize check objects before aggregation.

2. **Secret redaction is improved but not exhaustive for secret-like values.**
   - Redaction covers configured `POLYGON_API_KEY`, `api_key`/`api-key`/`apiKey`-style `=` values, access/token `=` values, bearer tokens, password `=` values, secret `=` values, and `?key=`/`&key=` URL parameters.
   - It does **not** cover common colon/JSON forms such as `password: hunter2`, `"password": "hunter2"`, `client_secret: value`, or `apiKey: value` unless the value also matches the configured Polygon key replacement.
   - **Recommended before market hours if external/client exceptions may include JSON or colon-formatted diagnostics:** extend redaction patterns and tests to cover colon/JSON secret formats.

## Readiness crash-proofing assessment

- `/api/readiness/session` now wraps `_run_all_checks(market_open)` in `try/except`, logs the failure, redacts the exception string, and returns an HTTP-200-compatible response body with `overall_status: not_ready`, a synthetic `readiness_internal` failed check, fail summary, recommended action, and disclaimer.
- `/api/readiness/session/compact` now wraps `_run_all_checks(market_open)` in `try/except`, logs the failure, and returns an HTTP-200-compatible compact fallback with `overall_status: not_ready`, `fail_count: 1`, safe default booleans/nulls, recommended action, and disclaimer.
- The patch therefore satisfies the specific runner-failure behavior: runner exceptions are converted into not-ready/fail payloads rather than unhandled route exceptions.
- The patch does **not** fully satisfy strict route-level crash-proofing because exceptions after `_run_all_checks(...)` returns are not guarded by the new `try/except` blocks.

## Error redaction assessment

- Polygon/client exception output is no longer directly exposed in `_check_polygon_data`; the patch routes exception text through `redact_sensitive_error(...)` before putting it into the message/details payload.
- Runner-failure output for the full session endpoint is also redacted before being returned in the fallback `readiness_internal` check.
- The covered cases include API key forms, access/token forms, bearer tokens, password `=` forms, secret `=` forms, and the configured Polygon API key value.
- Residual gap: redaction does not cover colon/JSON-style secret output or many broader secret-like key names (`client_secret`, `refresh_token`, etc.) unless they also match one of the existing patterns. This is a hardening gap rather than evidence of a current leak in the tested paths.
- Compact runner fallback does not include exception text in the response, so it avoids response leakage for runner failures by omission.

## Test coverage assessment

- Tests now enforce HTTP 200 for both readiness endpoints when the runner raises:
  - `test_session_never_raises_on_check_exception` asserts `/api/readiness/session` returns `200`, `overall_status == "not_ready"`, includes `readiness_internal`, and does not leak the injected `SECRET123` value.
  - `test_compact_never_raises_on_runner_failure` asserts `/api/readiness/session/compact` returns `200`, `overall_status == "not_ready"`, `fail_count >= 1`, and does not leak the injected `LEAKSECRET` value.
- Tests verify redaction with unit coverage for API key, token, bearer, password, long-message truncation, configured Polygon key replacement, safe messages, and Polygon exception payloads containing multiple secret forms.
- Tests do not currently verify colon/JSON secret formats or broader secret-like key names.
- Tests appear to avoid real Polygon calls:
  - Endpoint-level tests generally patch `_check_polygon_data` or patch `data.polygon_client.get_ticker_snapshot`.
  - `_check_polygon_data` tests patch the Polygon client function with fake async implementations.
  - The “unreachable Polygon” test uses a patched client that raises `ConnectionError`, confirming the endpoint handles unavailable Polygon without relying on network access.
- I ran `pytest backend/tests/test_phase2l.py -q`; all 51 tests passed with one Starlette/httpx deprecation warning.

## Safety assessment

- The patch did not add broker integration, live trading, real orders, AI/LLM, or real-money execution paths.
- The readiness module retains explicit safety disclaimers and observational-only language.
- The safety invariant check continues to fail if simulator status reports `live_trading_enabled` or `broker_connected`, and continues to hard-code `execution_enabled: False` in readiness details.
- The AST/import safety tests continue to guard against broker/AI imports and order-submission call names in `backend/api/readiness.py`.

## Is another patch required before market hours?

**Yes, if the acceptance bar is strict route-level crash-proofing.** The latest patch closes the runner-failure-to-HTTP-500 hole and adds meaningful secret redaction, but a small follow-up hardening patch is still recommended before market hours to:

1. Guard the full route response-assembly section after `_run_all_checks(...)` returns.
2. Guard the compact route response-assembly section after `_run_all_checks(...)` returns.
3. Expand redaction/tests for colon/JSON secret formats and broader secret-like keys.

If the acceptance bar is limited to “runner failures return HTTP 200 with not-ready/fail payloads,” then the patch meets that specific requirement.
