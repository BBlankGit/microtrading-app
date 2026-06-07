# Codex Review: Phases 0 through 1G

Review date: 2026-06-07

## Scope and constraints

This review covers the current repository state from Phase 0 foundation through the implemented Phase 1 data/catalyst/streaming work. It is intentionally limited to review findings and does not add application code, features, broker integration, live trading, paper trading, or AI/LLM calls.

Reviewed areas:

- FastAPI application wiring and public route surface
- Polygon REST market data client and route adapters
- Polygon WebSocket streaming path and Redis latest-value cache
- Catalyst collection, deterministic filtering, and deterministic event classification
- Market-quality gate implementation
- Frontend dashboard skeleton
- Docker and environment defaults
- Existing test posture

## Executive summary

The project is directionally consistent with a research-only, no-broker/no-live-trading posture: there is no broker integration present, no live order path, no paper-order implementation, and the AI package is only a placeholder. However, it should **not** be promoted beyond an internal Phase 1 research prototype until the critical issues below are addressed.

The largest blockers are operational and safety-related rather than trading-execution-related:

1. The backend exposes unauthenticated state-changing stream-control endpoints while CORS is wide open.
2. Some stream endpoints can raise server errors when Redis is not configured, which makes the health/status surface unreliable outside the docker-compose path.
3. There is essentially no automated test coverage for the implemented backend logic or route behavior.
4. The public status surface discloses a Polygon key preview and runtime configuration without authentication.

## Critical issues

### 1. Unauthenticated state-changing stream controls are exposed with permissive CORS

`backend/main.py` enables CORS for all origins, all methods, and all headers. The stream API exposes `POST /api/stream/start` and `POST /api/stream/stop`, which can start and stop a Polygon WebSocket task using the configured Polygon API key.

Why this is critical:

- Any browser origin can attempt to call state-changing backend endpoints if the backend is reachable.
- Starting the stream consumes infrastructure resources and Polygon quota/entitlement capacity.
- This is not a trading-execution path, but it is still an externally triggerable operational action.
- It creates an avoidable abuse and denial-of-wallet/denial-of-service risk for a cloud-hosted research service.

Required before proceeding:

- Restrict CORS to explicit frontend origins.
- Add authentication/authorization before any state-changing operational endpoint.
- Consider disabling stream start/stop endpoints entirely outside a trusted internal environment.

### 2. Stream status can crash when `REDIS_URL` is unset or invalid

`backend/api/stream.py` creates a Redis client before entering its `try` block in `_redis_connected()`. With the default `REDIS_URL` value from settings being an empty string, `GET /api/stream/status` raises a `ValueError` rather than returning a controlled unavailable status.

Observed check:

- `PYTHONPATH=backend python - <<'PY' ... c.get('/api/stream/status') ... PY` failed with `ValueError: Redis URL must specify one of the following schemes (redis://, rediss://, unix://)`.

Why this is critical:

- Status endpoints should be safe and reliable even when optional infrastructure is missing.
- This weakens deployability and monitoring during early phases.
- The same Redis URL construction pattern appears in the WebSocket data path and catalyst cache path, so invalid Redis configuration may cause inconsistent failures.

Required before proceeding:

- Validate required settings at startup for configured deployment modes.
- Make status endpoints fail closed with structured `redis_connected: false`/configuration error details instead of uncaught exceptions.
- Add route tests for missing, invalid, and valid Redis configuration paths.

### 3. No meaningful automated backend test suite exists

The `tests/` directory currently contains only `tests/__init__.py`. `pytest -q` exits with code 5 because no tests are collected.

Why this is critical:

- Implemented deterministic logic is exactly the type of code that should be locked down with unit tests: symbol normalization, Polygon payload normalization, market-quality gates, catalyst filtering, event classification, and route error mapping.
- Without tests, regressions could silently change research filters, tradability gates, or external API error handling.
- This is a blocker for advancing into any phase that makes decisions from this data, even if those decisions remain research-only.

Required before proceeding:

- Add unit tests for all deterministic pure functions.
- Add FastAPI route tests with mocked Polygon/Redis dependencies.
- Add regression tests for no-broker/no-live-trading/no-order invariants.

### 4. Runtime configuration and key preview are publicly exposed

`/api/data/status` returns whether Polygon is configured and includes a masked key preview. The masking is better than exposing the raw key, but the endpoint is currently unauthenticated and the application allows any origin.

Why this is critical:

- The key preview may aid inventorying, correlation, or support-social-engineering attacks.
- Configuration exposure is unnecessary for public users.
- Combined with the unauthenticated stream controls, this makes the externally visible operational surface too revealing.

Required before proceeding:

- Remove key preview from unauthenticated responses.
- Gate operational/configuration status behind authentication.
- Keep raw keys out of logs and responses; the WebSocket code already avoids logging the full auth payload, which should remain an invariant.

## Important non-blocking issues

### 1. README and runtime status overstate paper-trading readiness

The README and `/api/status` describe the mode as paper trading only, but `backend/execution/` is currently only a package placeholder. That is acceptable for the user-requested no-trading scope, but it may confuse reviewers into thinking a paper execution path already exists.

Recommendation:

- Clarify wording as “research-only / no execution implemented” until a future approved phase actually adds paper trading.
- Preserve the explicit no-live-trading and no-broker language.

### 2. API route modules duplicate Polygon error mapping

`backend/api/market.py` and `backend/api/quality.py` each define a local `_polygon_error_to_http()` with the same behavior. Duplication increases the chance of inconsistent error handling as more Polygon-backed endpoints are added.

Recommendation:

- Move shared external-provider error translation into a common API utility module.
- Test the mapping once and reuse it across route modules.

### 3. Symbol validation is inconsistent across endpoints

The Polygon REST client has a strict uppercase 1-to-5-letter symbol regex. Some route handlers trim and uppercase symbols before passing them to the client, but stream latest reads use the path parameter directly for Redis key construction after only uppercase/strip normalization.

Recommendation:

- Centralize symbol validation and reuse it for REST, stream, catalyst, and universe endpoints.
- Decide whether tickers with dots/hyphens/classes are in or out of scope, then document that policy.

### 4. Redis cache writes are best-effort but lifecycle handling is inconsistent

Catalyst collection opens Redis inside a `try` block and handles failures as best-effort. Stream status opens Redis before exception handling and can crash when the URL is invalid. WebSocket streaming creates Redis connections inside a reconnect loop and depends on valid settings.

Recommendation:

- Create one Redis helper that validates URL presence/scheme and returns structured unavailable states.
- Ensure every optional Redis path fails gracefully when Redis is disabled or unavailable.

### 5. WebSocket stream state is in-process only

The Polygon stream task and state live in module globals. This is acceptable for a prototype but does not scale across multiple Uvicorn workers or multiple backend replicas.

Recommendation:

- Document single-worker assumptions.
- Before production-like deployment, move stream orchestration to a dedicated worker/service or add explicit distributed ownership/locking.

### 6. Event classification is deterministic but uncalibrated

The rules are intentionally non-AI and non-trading. The current classifier uses keyword matching and first-match priority. This is reasonable for Phase 1, but event-confidence values should be treated as rule confidence labels, not predictive signal quality.

Recommendation:

- Rename or document `event_confidence` as classification confidence only.
- Add fixtures with known catalyst headlines to prevent rule priority regressions.

### 7. Market-quality thresholds are hard-coded

The quality gate currently hard-codes minimum day volume, previous-day volume, and maximum spread percentage. This is acceptable for a prototype but should become configuration before broader research use.

Recommendation:

- Move thresholds to typed settings or policy constants with tests.
- Keep the gate explicitly non-directional and non-advisory.

### 8. Frontend dashboard is static and can drift from backend state

The dashboard hard-codes “Phase 0” and “No external connections active,” while the backend already includes Phase 1-style Polygon REST and WebSocket data routes.

Recommendation:

- In a future UI phase, have the dashboard read backend status rather than hard-coding operational state.
- Until then, document the dashboard as a skeleton only.

## Recommended tests

Before advancing beyond Phase 1G, add the following tests.

### Backend unit tests

- `core.config`
  - `polygon_key_preview()` returns `not configured` when empty.
  - `polygon_key_preview()` never returns the full key.
  - `polygon_configured()` reflects empty vs non-empty keys.

- `data.polygon_client`
  - Symbol validation accepts only supported symbols.
  - Missing API key raises the intended `PolygonError`.
  - 403/404/non-200/Polygon error payloads map to expected `PolygonError` values.
  - Normalization does not leak `apiKey`.

- `data.schemas`
  - Snapshot, previous-close, and news normalization handle missing optional fields.
  - Bid/ask mapping is covered with representative Polygon payloads.

- `data.market_quality`
  - Accepts high-liquidity/tight-spread fixtures.
  - Rejects missing bid, missing ask, crossed quote, missing trade, low day volume, low previous-day volume, and excessive spread.
  - Confirms the function never emits buy/sell/hold direction.

- `data.stream_normalizer`
  - Normalizes `T`, `Q`, and `AM` messages.
  - Returns `None` for unrecognized events.

- `catalysts.schemas`
  - Catalyst IDs are stable with Polygon article IDs.
  - URL-hash fallback is deterministic.
  - Relevance hint is direct only when the requested symbol is in the ticker list.

- `catalysts.filters`
  - Rejects duplicate IDs, missing titles, invalid timestamps, stale items, and indirect relevance.
  - Adds `freshness_age_hours` and `filter_status` only to accepted items.

- `catalysts.event_classifier`
  - Covers each major rule category.
  - Confirms priority behavior when multiple rules match.
  - Confirms fallback to `generic_news`.

### Backend route tests

- `/health`, `/api/status`, and `/api/data/status` return stable response contracts.
- Polygon-backed routes return controlled errors when the key is missing.
- Stream status returns controlled unavailable responses when Redis is missing or invalid.
- Stream start returns a controlled error when Polygon is not configured.
- Catalyst endpoints enforce symbol-count and limit bounds.
- CORS policy tests confirm only approved origins once CORS is restricted.

### Frontend tests/checks

- `npm run build` should remain part of CI.
- Add a non-interactive lint configuration so `npm run lint` can run in CI.
- Add minimal component/render tests once the dashboard starts consuming backend status.

### Security tests

- Assert that no response contains `POLYGON_API_KEY`, `OPENAI_API_KEY`, or full secret values.
- Assert state-changing endpoints require authentication once auth is added.
- Add dependency/vulnerability scanning for Python and npm packages.

## Suggested refactors

1. Add `backend/api/errors.py` or similar for shared provider exception mapping.
2. Add `backend/api/dependencies.py` for common symbol validation, settings access, and future auth dependencies.
3. Add `backend/data/redis_client.py` for safe Redis URL validation, connection creation, and unavailable-state responses.
4. Move market-quality thresholds into typed settings or a policy module.
5. Separate stream orchestration from request handlers; routes should request state transitions from a managed service rather than own module-global tasks directly.
6. Rename or document classifier confidence fields to prevent downstream users from treating them as predictive trading scores.
7. Clarify documentation terminology around “paper” vs “research-only/no execution implemented” until an explicitly approved paper-trading phase exists.
8. Add an invariant test module that verifies there are no broker SDK imports, no live-order routes, and no AI/LLM calls in the current phase.

## Security/secrets concerns

- `.env.example` includes placeholder API keys and docker-compose database credentials. These are not secrets by themselves, but the database password must not be reused outside local/dev environments.
- `OPENAI_API_KEY` exists in settings and `.env.example`, but there is currently no AI/LLM call path. Keep it unused unless a future approved phase explicitly allows AI integration.
- `POLYGON_API_KEY` is used by REST and WebSocket code. The full key is not intentionally returned or logged, but the key preview exposed by `/api/data/status` should not be public.
- Docker Compose exposes Postgres and Redis ports on the host. That is convenient for development but should not be used as-is on a public server.
- There is no authentication layer yet. Treat every backend endpoint as public if the service is reachable.
- Broad CORS (`*`) should be considered unsafe for any deployment beyond isolated local development.

## Review checks performed

- `python -m compileall backend tests` passed.
- `pytest -q` found no tests and exited with code 5.
- FastAPI smoke checks for `/health`, `/api/status`, and `/api/data/status` returned HTTP 200 using `TestClient`.
- FastAPI smoke check for `/api/stream/status` failed with an uncaught Redis URL `ValueError` when `REDIS_URL` was not configured.
- `npm run lint` was not usable non-interactively because Next.js prompted to configure ESLint.
- `npm run build` completed successfully for the dashboard.

## Safe to proceed to the next phase?

**Decision: Not safe to proceed beyond internal Phase 1G research-prototype work until the critical issues are fixed.**

Safe to do next:

- Fix the critical operational/security issues listed above.
- Add automated tests.
- Improve documentation accuracy.
- Refactor shared utilities without adding trading features.

Not safe to do next yet:

- Broker integration.
- Live trading.
- Paper trading.
- AI/LLM calls for catalyst scoring or recommendations.
- Any execution engine work that depends on the current untested data and catalyst paths.

Once unauthenticated operational controls are removed or gated, Redis failure behavior is controlled, key/config exposure is reduced, and baseline tests are in place, the project should be safe to continue with additional research-only data-quality and observability phases.
