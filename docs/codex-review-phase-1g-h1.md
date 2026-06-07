# Codex Review: Phase 1G-H1 Hardening

Date: 2026-06-07  
Scope: H1 hardening changes only.

This review is intentionally limited to:

- CORS restriction
- `ADMIN_API_TOKEN` behavior
- Protected stream start/stop endpoints
- Redis status crash prevention
- `/api/data/status` key-preview behavior
- Research-only `/api/status` wording
- Added pytest baseline
- No broker, no live trading, no paper trading, and no AI/LLM invariants

This review does **not** add features, broker integration, live trading, paper trading, AI/LLM calls, or strategy logic.

## Critical issues remaining

### 1. Redis status crash prevention is incomplete for malformed Redis URLs

`redis_ping_status()` is documented to never raise, and `/api/stream/status` relies on that behavior. However, the current validation only checks that `REDIS_URL` is present and uses a `redis` or `rediss` scheme. It does not catch exceptions raised while constructing the Redis client.

A malformed but scheme-valid URL such as `redis://localhost:notaport/0` raises during `aioredis.from_url(...)`, before the function enters its `try` block. In that case, `/api/stream/status` returns HTTP 500 instead of a safe status payload with `redis_connected: false`.

Impact:

- This directly undercuts the H1 Redis status crash-prevention goal.
- It can turn a configuration typo into an API crash.
- The same construction-time failure path can affect other Redis-dependent endpoints that rely on the same URL validation pattern.

Recommended remediation for the implementation owner:

- Wrap Redis client construction inside the `try` block in `redis_ping_status()`.
- Make `redis_url_valid()` stricter, or avoid treating it as sufficient proof that `from_url()` cannot raise.
- Add a regression test for `REDIS_URL=redis://localhost:notaport/0` against `/api/stream/status`.

## Important non-blocking issues

### 1. Research-only terminology is improved at `/api/status`, but configuration still says `paper`

The new `/api/status` response correctly reports `mode: research`, `execution_enabled: false`, `paper_trading_enabled: false`, `live_trading_enabled: false`, and `broker_connected: false`.

However, `TRADING_MODE` still defaults to `paper`, `.env.example` still sets `TRADING_MODE=paper`, and `/api/data/status` exposes `trading_mode` from that setting. This does not create paper trading behavior by itself, but it keeps a visible semantic conflict with the H1 no-paper-trading posture.

Recommended remediation for the implementation owner:

- Change the default and example trading mode to `research` until an explicitly approved future phase adds paper trading.
- Consider returning a separate explicit execution status field from `/api/data/status` if that endpoint must remain backward-compatible.

### 2. CORS is restricted by default, but lacks direct endpoint-level regression coverage

The application no longer uses wildcard CORS by default. Manual preflight checks showed `http://localhost:3000` is allowed and an unrelated origin is rejected. Existing tests cover parsing and the default non-wildcard setting, but they do not exercise FastAPI's CORS middleware behavior.

Recommended remediation for the implementation owner:

- Add tests for allowed-origin and disallowed-origin preflight requests.
- Include a multi-origin configuration test for the actual middleware, not only the parser.

### 3. Admin token comparison is functionally correct but not hardened against timing analysis

The `ADMIN_API_TOKEN` dependency correctly disables admin operations when unset or set to the documented sentinel value, requires a `Bearer` token, and rejects missing or incorrect tokens. The comparison is a plain string equality check. For this internal research prototype that is acceptable as a non-blocking issue, but `hmac.compare_digest()` would be a better hardening default.

Recommended remediation for the implementation owner:

- Use constant-time comparison for the configured token and supplied token.
- Continue returning generic failure messages that do not reveal the expected token.

### 4. Safety invariant tests are useful, but the scan scope is intentionally narrow

The new invariant tests scan executable backend code under selected directories and verify absence of broker SDK imports, order-execution route/function patterns, and AI/LLM SDK imports. That is a good H1 baseline, but it does not cover all repository files, frontend code, shell scripts, Docker entrypoints, or future generated files.

Recommended remediation for the implementation owner:

- Keep the current backend-focused tests.
- Consider adding a separate repository-wide safety audit in a later hardening pass if the project adds scripts, jobs, or additional services.

## Test coverage assessment

Current pytest baseline:

- `backend/tests/test_config.py` covers CORS origin parsing, non-wildcard default behavior, Polygon key masking, and default disabled key preview.
- `backend/tests/test_data_status.py` covers default omission of `polygon_key_preview`, opt-in masked key preview, and protection against returning the full Polygon API key.
- `backend/tests/test_redis_status.py` covers empty Redis URL, invalid non-URL text, invalid scheme, and non-crashing `/api/stream/status` responses for those cases.
- `backend/tests/test_stream_auth.py` covers disabled admin operations, sentinel token behavior, missing/malformed/wrong authorization, and confirms read-only stream status is not auth-protected.
- `backend/tests/test_safety_invariants.py` covers no broker SDK imports, no order-execution route/function patterns, and no AI/LLM SDK imports in the selected executable backend paths.

Result from this review:

- `cd backend && pytest -q` passed: 26 tests passed.
- The run emitted two warnings: a Starlette `TestClient` deprecation warning and an unknown `asyncio_mode` pytest config warning.
- Additional manual CORS preflight checks showed the configured local frontend origin is allowed and an unrelated origin is rejected.
- Additional manual malformed-Redis testing found the critical gap described above: `REDIS_URL=redis://localhost:notaport/0` causes `/api/stream/status` to return HTTP 500.

Coverage conclusion:

The added pytest baseline is a strong first H1 baseline for auth, key-preview behavior, simple Redis misconfiguration cases, and phase safety invariants. It is not yet complete for malformed Redis URLs that raise during Redis client construction, nor for actual CORS middleware behavior.

## Security assessment

Positive findings:

- CORS is no longer wildcard by default and permits only configured origins.
- Stream start/stop are protected by `ADMIN_API_TOKEN` and are disabled when the token is empty or left at the sentinel value.
- Read-only stream status remains unauthenticated, which is reasonable for operational visibility as long as it avoids secrets.
- `/api/data/status` omits Polygon key preview by default.
- When key preview is explicitly enabled, the full key is not returned.
- `/api/status` now uses research-only language and explicitly reports no execution, no paper trading, no live trading, and no broker connection.
- The backend invariant tests reduce the risk of accidental broker, order execution, or AI/LLM code entering this phase.

Security gaps / cautions:

- Malformed Redis URLs can still crash Redis status handling, which is both a reliability and defensive-hardening gap.
- Admin token comparison should eventually use constant-time comparison.
- CORS tests should verify middleware behavior directly.
- The visible `TRADING_MODE=paper` default/example can mislead operators or reviewers even though no execution path currently exists.

## H1 sufficiency for continuing research-only Phase 1H work

H1 is **mostly sufficient to continue with research-only Phase 1H work**, with one required condition: fix the malformed Redis URL crash path before treating H1 as fully closed.

Rationale:

- No broker integration was added.
- No live trading was added.
- No paper trading implementation was added.
- No AI/LLM calls were added.
- No strategy logic was added.
- Admin stream controls are now protected and fail closed when the admin token is unset or left at the sentinel value.
- Key-preview exposure is now opt-in and masked.
- Runtime status wording is materially safer and clearer for research-only operation.
- The new pytest baseline materially reduces regression risk.

Recommended gate:

- Continue Phase 1H research-only planning and non-execution work.
- Before broad deployment or declaring H1 complete, patch and test the Redis malformed-URL crash case.
