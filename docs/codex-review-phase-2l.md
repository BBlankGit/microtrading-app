# Codex Review — Phase 2L Market Session Readiness Checks

Reviewed scope: latest Phase 2L changes only (`2479ff3..6f5f5cb`):

- `backend/api/readiness.py`
- `backend/main.py`
- `backend/tests/test_phase2l.py`
- `frontend/dashboard/app/page.tsx`

## Critical issues

1. **Readiness endpoints are not fully crash-proof if the check runner itself raises.**
   - The individual checks are mostly wrapped in local `try`/`except` blocks, but both `/api/readiness/session` and `/api/readiness/session/compact` call `_run_all_checks(...)` directly and do not catch an exception from the runner.
   - The Phase 2L test named `test_session_never_raises_on_check_exception` explicitly patches `_run_all_checks` to raise, then permits either `200` or `500`, so it does not enforce the stated invariant that the readiness endpoint never crashes if sub-checks fail.
   - This is a blocker for the “endpoint never crashes” requirement, even though normal current sub-check paths are defensive.

2. **Polygon error messages may expose unredacted exception text.**
   - `_check_polygon_data()` copies `str(exc)[:200]` into both the user-facing message and details.
   - The current Polygon client generally avoids placing the configured key in its own `PolygonError` messages, but network/client exception strings are not guaranteed to be secret-free. A defensive readiness endpoint should redact API keys, query parameters such as `apiKey=...`, bearer tokens, and obvious credential substrings before returning errors.
   - The current no-secrets test only patches the whole check runner with a safe response and therefore does not test Polygon exception redaction.

## Non-blocking issues

1. **Safety invariant coverage does not check a dynamic execution-enabled flag.**
   - The invariant checks `live_trading_enabled` and `broker_connected`, but `execution_enabled` is hard-coded to `False` in returned details rather than read from simulator/config status. That is safe for the current fake-money system, but the test requirement specifically mentions execution flags; a future explicit execution flag would not be detected unless added.

2. **Market-session detection is best-effort and omits holidays/early closes.**
   - The code correctly labels the helper as best-effort and says holidays are not included yet. This is acceptable for Phase 2L operational guidance, but it can produce misleading “market open” readiness on U.S. market holidays or half days.

3. **Polygon cache has no concurrency guard.**
   - The 60-second TTL limits ordinary dashboard polling load, but concurrent cold-cache requests can all call Polygon before the first response populates the cache. This is probably acceptable for the current single-dashboard use case but worth tightening later with an async lock or in-flight task.

## Readiness logic assessment

- **No broker/live trading/real-order path added:** I found no new broker integration, live trading execution, order submission, AI/LLM integration, or real-money execution in the Phase 2L readiness code. The module-level disclaimer explicitly states that no broker, live trading, real orders, real-money execution, or AI/LLM are involved.
- **Operational/read-only nature:** The checks read simulator state/status, journal status, runtime status, cached universe, market-regime cache, and one Polygon SPY snapshot. They do not mutate simulator state, place orders, connect brokers, or trigger execution. The only operational side effect is the in-memory Polygon readiness cache.
- **Overall status:** The aggregate status mapping is straightforward: any failed check returns `not_ready`, any warning returns `warning`, otherwise `ready`.
- **Recommended actions:** The actions are operational, e.g., set Polygon API key, check journal connectivity, start the fake-money simulator, refresh the universe, or review runtime overrides. They do not instruct real trading or broker activity.
- **Crash resilience:** Individual checks mostly degrade to `warn`/`fail` on exceptions, but the route-level lack of fallback around `_run_all_checks()` remains a critical gap.

## API-load assessment

- The only active external API readiness call is `polygon_client.get_ticker_snapshot("SPY")`.
- `_check_polygon_data()` caches the result for 60 seconds, and the dashboard auto-refreshes every 30 seconds, so normal use should be at most about one Polygon snapshot request per backend process per minute.
- Tests mock Polygon calls in endpoint-level cases by patching `_check_polygon_data`, and the direct cache test patches `data.polygon_client.get_ticker_snapshot`; no test should make a real Polygon request.
- Non-blocking risk: concurrent first requests after cache expiry can duplicate Polygon calls because there is no async lock/in-flight request sharing.

## Dashboard assessment

- The new readiness section is clear that it is “fake-money only,” “no broker,” and “no real orders.”
- The page header continues to state “Fake-money simulator · No broker · No live trading · No real orders.”
- The readiness panel disclaimer says it is operational guidance for fake-money simulation monitoring only and does not enable broker trading or real orders.
- The dashboard does not present readiness as permission to trade real money. The “READY” badge could be read as operational readiness, but the surrounding copy sufficiently constrains it to fake-money monitoring.

## Safety/secrets assessment

- Safety invariants fail when `live_trading_enabled` or `broker_connected` are true.
- No broker modules, order placement functions, AI/LLM modules, or real-money execution integrations were added by the Phase 2L code.
- The API key check returns only a boolean-style `configured` detail and does not return the configured Polygon key.
- Critical gap: Polygon exception strings are returned directly/truncated but not redacted, so secrets exposure is not fully ruled out if a lower-level client or future exception includes credentials.

## Test coverage assessment

Covered:

- Healthy/pass, warning, and failure aggregate states.
- Compact endpoint shape.
- Safety invariant failures for live trading and broker flags.
- Missing/present Polygon key.
- Simulator, journal, universe, tick-freshness status variants.
- Polygon cache behavior with a mocked Polygon client call.
- Basic no broker/AI imports and no execution-call substrings in `readiness.py`.
- Router registration.

Gaps:

- The “endpoint never crashes” test currently allows `500`, so it does not enforce the requirement.
- No test proves a real Polygon call cannot occur through the full endpoint path; endpoint tests patch `_check_polygon_data`, and the cache test patches `get_ticker_snapshot`, which is good, but there is no guard such as failing if `httpx.AsyncClient` is reached.
- No test verifies Polygon exception redaction.
- No test covers an explicit `execution_enabled=True` safety flag because the invariant currently hard-codes execution as false.
- Dashboard clarity is not covered by tests; it was assessed manually from the JSX copy.

## Is Phase 2L safe to run for fake-money monitoring?

**Mostly yes, with two caveats.** Phase 2L does not add broker integration, live trading, real orders, AI/LLM behavior, or real-money execution, and the readiness checks are operational/read-only for fake-money monitoring. However, before relying on it during market hours, the endpoint should be made route-level crash-proof and Polygon error output should be redacted defensively.

## Is any patch required before market hours?

**Yes.** I recommend a small pre-market patch to:

1. Wrap `/api/readiness/session` and `/api/readiness/session/compact` check execution in a route-level fallback so failures return a `not_ready`/warning response rather than HTTP 500.
2. Strengthen `test_session_never_raises_on_check_exception` to require HTTP 200 and a safe failed/warning readiness response.
3. Redact Polygon/API-key/token/password/secret-looking substrings before returning exception text.
4. Add a no-real-Polygon-call guard test that fails if the full endpoint path reaches the actual HTTP client.
5. Optionally include `execution_enabled` in the safety invariant if that flag exists or is added to simulator status/config.
