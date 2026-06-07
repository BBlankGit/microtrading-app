# Codex Review: Phase 1G-H1.1 Redis Hardening Patch

Date: 2026-06-07
Repository: `BBlankGit/microtrading-app`
Reviewed patch: `5e68e96 Fix malformed Redis URL handling in stream status`

## Scope

This review is limited to the H1.1 changes related to the malformed Redis URL crash fix after Phase 1G-H1.

Reviewed areas:

- `redis_ping_status()` hardening in `backend/data/redis_client.py`
- `/api/stream/status` behavior in `backend/api/stream.py`
- Redis status regression coverage in `backend/tests/test_redis_status.py`
- Safety/invariant impact of the patch, specifically whether broker, live trading, paper trading, order execution, AI/LLM, or strategy logic was accidentally added

This review does **not** add features, broker integration, live trading, paper trading, AI/LLM calls, or strategy logic.

## Critical issues remaining

No critical H1.1 Redis hardening issues were found.

### 1. `redis_ping_status()` no longer exposes the malformed-port crash path

The H1 critical issue was that a Redis URL such as `redis://localhost:notaport/0` could raise during Redis client construction before the earlier `try` block was entered. H1.1 moves `aioredis.from_url(...)` inside the `try` block and initializes the Redis handle to `None` before construction.

Current behavior:

- Empty `REDIS_URL` returns a safe disconnected status before client construction.
- Malformed Redis URLs are caught by the broad `except Exception` path.
- Connection failures during `ping()` are caught by the same path.
- Redis close failures are swallowed in the `finally` block, so cleanup does not turn a safe status response into an exception.

Manual direct verification confirmed that `redis_ping_status()` returned safe dictionaries, rather than raising, for:

- empty `REDIS_URL`
- `not-a-url`
- `http://localhost:6379`
- `redis://localhost:notaport/0`
- `redis://127.0.0.1:19999/0`

### 2. `/api/stream/status` returns HTTP 200 for the malformed-port regression

Manual endpoint verification with `REDIS_URL=redis://localhost:notaport/0` returned HTTP 200 with:

- `redis_connected: false`
- a `redis_error` message containing the port parsing failure

This satisfies the expected failure mode for read-only status reporting. The endpoint no longer converts this malformed Redis URL into an HTTP 500.

## Non-blocking issues

### 1. The direct async tests depend on `pytest-asyncio` being installed

`backend/requirements.txt` declares `pytest-asyncio`, and `backend/pytest.ini` configures `asyncio_mode = auto`, so a correctly provisioned test environment should run the new direct async tests.

In the current review container, `pytest-asyncio` was not installed. As a result, the endpoint-level tests and safety invariant tests could be exercised, but the direct `@pytest.mark.asyncio` tests failed to execute under the preinstalled global pytest environment. An attempted dependency install was blocked by the environment package index/proxy, so this appears to be a review-environment limitation rather than an H1.1 code defect.

### 2. `redis_ping_status()` still relies on normal typed settings

The function is effectively non-raising for normal configured string values and Redis client failures. It still calls `redis_url_configured()` before the `try` block, which assumes `settings.REDIS_URL` behaves like the configured string field declared by Pydantic settings. That is acceptable for the application path under review, but it means the phrase "Guaranteed to never raise" is strongest when interpreted against normal settings usage rather than arbitrary monkeypatching to non-string sentinel objects.

This is not blocking for H1.1 because the target regression is malformed Redis URL text, and that path is now covered.

## Test result assessment

### Tests added or updated for H1.1

The H1.1 test updates cover the malformed Redis URL regression at two levels:

1. Endpoint regression coverage:
   - `test_stream_status_no_crash_when_redis_url_malformed_port` sets `REDIS_URL` to `redis://localhost:notaport/0`.
   - It asserts `/api/stream/status` returns HTTP 200.
   - It asserts `redis_connected` is `False`.
   - It asserts `redis_error` is present.

2. Direct helper coverage:
   - `test_redis_ping_status_never_raises_on_malformed_port` calls `redis_ping_status()` directly with `redis://localhost:notaport/0`.
   - Related tests cover empty Redis URL and unreachable Redis host behavior.

This is sufficient regression coverage for the specific H1 malformed-port crash.

### Commands run during review

- `pytest -q backend/tests/test_redis_status.py backend/tests/test_stream_auth.py backend/tests/test_safety_invariants.py`
  - Result: 19 passed, 3 failed.
  - The 3 failures were the direct async tests failing because the current environment lacked `pytest-asyncio`, not because the Redis hardening behavior raised.

- `python -m pip show pytest-asyncio || true && python -m pytest -q backend/tests/test_redis_status.py::test_stream_status_no_crash_when_redis_url_malformed_port backend/tests/test_redis_status.py::test_stream_status_redis_error_field_when_url_invalid backend/tests/test_safety_invariants.py`
  - Result: `pytest-asyncio` was not installed; the selected endpoint and safety tests passed: 5 passed.

- `python -m pip install -q -r backend/requirements.txt && pytest -q backend/tests/test_redis_status.py backend/tests/test_stream_auth.py backend/tests/test_safety_invariants.py`
  - Result: dependency installation failed because the package index/proxy returned 403 while trying to fetch `pytest-asyncio`; tests did not run after the failed install.

- `PYTHONPATH=backend python - <<'PY' ... await redis_ping_status() ... PY`
  - Result: direct manual async verification passed for empty, malformed, invalid-scheme, malformed-port, and unreachable Redis URLs. Each case returned a safe status dictionary.

- `PYTHONPATH=backend python - <<'PY' ... TestClient ... GET /api/stream/status ... PY`
  - Result: manual endpoint verification passed. With `REDIS_URL=redis://localhost:notaport/0`, `/api/stream/status` returned HTTP 200 and `redis_connected: false` with `redis_error`.

## Safety review: accidental trading, broker, AI/LLM, or strategy logic

No accidental broker, live trading, paper trading, order execution, AI/LLM, or strategy logic was found in the H1.1 diff.

Observed changes were limited to:

- Redis status hardening.
- Redis status regression tests.
- Admin token comparison hardening with `hmac.compare_digest`.
- Additional auth near-miss tests.
- Changing the default/example `TRADING_MODE` text from `paper` to `research`.

The safety invariant tests that scan executable backend code for broker SDK imports, order execution route/function patterns, and AI/LLM SDK imports passed in the selected test run.

## Whether H1.1 is sufficient to fully close H1

Yes. H1.1 is sufficient to fully close the H1 malformed Redis URL crash issue.

Rationale:

- The Redis client construction path that previously raised outside the `try` block is now inside the protected section.
- Malformed Redis URL strings, including `redis://localhost:notaport/0`, now produce safe disconnected status payloads.
- `/api/stream/status` returns HTTP 200 instead of HTTP 500 for the malformed-port regression.
- The regression is covered by endpoint-level tests and direct helper tests.
- No prohibited trading, broker, execution, AI/LLM, or strategy logic was introduced.

## Whether the project is safe to proceed to the next research-only phase

Yes. The project is safe to proceed to the next research-only phase, assuming the next phase remains within the established research-only constraints.

Proceeding conditions:

- Continue to avoid broker integration.
- Continue to avoid live trading.
- Continue to avoid paper trading implementation unless explicitly approved in a future phase.
- Continue to avoid order execution endpoints or execution helper functions.
- Continue to avoid AI/LLM calls and strategy logic unless explicitly scoped for a future reviewed phase.
- Ensure CI or local test environments install `backend/requirements.txt` so the `pytest-asyncio`-based tests execute normally.
