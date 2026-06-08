# Codex Review — Phase D1 Shared Market Data Collector MVP

Review target: latest Phase D1 patch, commit `d8ebd56` (`Add shared market data collector MVP`).

Scope: this review covers only the Phase D1 market-data collector/cache patch. I did not change application code.

## Critical issues

1. **Rate limiting counts collector cycles, not actual Polygon attempts.**
   - `MarketDataCollector._cycle()` records one request before `_fetch_with_retry()` runs, but `_fetch_with_retry()` can call `polygon_source.fetch_bulk_snapshots()` once plus `MARKETDATA_RETRY_COUNT` retries.
   - With the default `MARKETDATA_MAX_REQUESTS_PER_MINUTE=50` and `MARKETDATA_RETRY_COUNT=1`, the effective worst-case Polygon request volume can be about 100 HTTP calls/minute during repeated failures while metrics still report 50 requests/minute.
   - This means request-rate limiting exists, but it does **not fully prevent excessive Polygon calls** under timeout/error conditions.
   - **Recommended pre-D2 fix:** count every fetch attempt against the rate limiter, and stop retrying when the remaining budget is exhausted. Ideally expose both `cycles_last_minute` and `polygon_attempts_last_minute`.

2. **Configured Polygon timeout is not wired into the HTTP client.**
   - Phase D1 adds `MARKETDATA_REQUEST_TIMEOUT_SECONDS`, but `data.polygon_client` still uses its module-level `_TIMEOUT = 10.0` for all Polygon requests.
   - The collector therefore cannot be tuned independently through the new D1 setting, and the tests only simulate timeout messages rather than verifying the real client timeout configuration.
   - **Recommended pre-D2 fix:** pass the configured collector timeout into the bulk snapshot call path or make `polygon_client` read the timeout setting for collector calls.

## Non-blocking issues

- **Backoff is fixed, not exponential/jittered.** The collector does retry with a backoff sleep, but `MARKETDATA_RETRY_BACKOFF_SECONDS` is a constant delay. This is acceptable for an MVP, but exponential backoff with jitter would be safer during Polygon incidents.
- **Redis active-symbol list is only updated on non-empty payload cycles.** If a later cycle returns no payloads, old `market:symbols:active` remains until its TTL expires. This is bounded by the 300-second TTL and is non-blocking, but the `/symbols` endpoint can briefly show stale cached symbols after a total fetch failure.
- **Redis connections are not closed in `finally` blocks.** `cache.write_cycle_results()` and read helpers close Redis after normal operations, but an exception after connection creation can skip `aclose()`. This is mitigated by broad exception handling, but connection cleanup should be hardened before heavier operation.
- **Health endpoint does one Redis read per configured symbol.** The D1 default watchlist is small, so this is fine for MVP. If D2 expands the universe significantly, health should batch reads or use `MGET`.
- **Admin start/stop endpoints were added.** The required read endpoints are read-only, but `/api/marketdata/start` and `/api/marketdata/stop` mutate collector lifecycle state behind `ADMIN_API_TOKEN`. This is operationally reasonable, but should be documented as admin-only control-plane behavior.

## Architecture assessment

- **Shared collector/cache was added.** The patch introduces a dedicated `backend/marketdata/` package with collector, cache, service lifecycle, health, Polygon-source adapter, and payload model modules.
- **Trading decisions are not changed in Phase D1.** The latest patch did not modify `backend/paper/` strategy, simulator, scoring, momentum, exits, or V5 strategy files. The collector is additive and currently writes snapshots/metrics to Redis for read-only consumption rather than feeding the simulator.
- **Startup is opt-in.** `MARKETDATA_COLLECTOR_ENABLED` defaults to `False`; when enabled, the app lifespan starts the collector and stops it on shutdown.
- **Singleton task model is appropriate for MVP.** `marketdata.service` maintains one collector task per process and avoids starting a duplicate task in the same process. Multi-process deployments would still need coordination if multiple workers are enabled.
- **No D2 integration is present yet.** The patch intentionally does not route simulator decisions through the shared cache, so it is safe from strategy-regression risk but does not yet reduce simulator Polygon usage.

## Redis/cache assessment

- **Keys are namespaced and predictable.** Snapshot keys use `market:snapshot:{SYMBOL}`, active symbols use `market:symbols:active`, metrics use `market:metrics`, and health reserves `market:health`.
- **Payload shape is structured.** Symbol payloads include symbol, source, fetch timestamps, TTL, price/quote fields, spread, day volume, change percent, previous close, minute placeholders, raw status, and error text.
- **Secrets are not cached.** The payload does not include the Polygon API key or broker/order fields.
- **TTLs are present.** Snapshot keys use the configured cache TTL, metrics expire after 120 seconds, and active symbols expire after 300 seconds.
- **Symbol normalization is mostly safe.** Snapshot write keys upper-case symbols. API reads also upper-case and strip the path parameter. However, `snapshot_key()` does not validate symbol characters, so arbitrary path strings can form arbitrary namespaced Redis keys. This is not command-injection risk with Redis `GET`, but symbol validation would improve hygiene.
- **Serialization is JSON-only.** This is safe for the current primitive payloads and avoids pickle/deserialization risk.

## API endpoint assessment

- **`GET /api/marketdata/health`: works read-only.** It pings Redis, checks per-symbol cache freshness, reports collector counters/timestamps, and returns a research-only disclaimer.
- **`GET /api/marketdata/symbol/{symbol}`: works read-only.** It reads a single cached symbol and returns 404 if no cached payload exists. It does not call Polygon directly.
- **`GET /api/marketdata/symbols`: works read-only.** It returns configured symbols, cached active symbols, running status, and disclaimer.
- **`GET /api/marketdata/metrics`: works read-only.** It returns in-memory service metrics plus cached Redis metrics. It does not mutate trading state or trigger market-data fetches.
- **Control-plane note:** `POST /api/marketdata/start` and `/stop` are not read-only, but they are admin-token protected and only manage the collector task. They do not place trades or change strategy decisions.

## Rate limiting/retry assessment

- **Retry/backoff exists.** `_fetch_with_retry()` attempts the bulk fetch and sleeps `MARKETDATA_RETRY_BACKOFF_SECONDS` before retry attempts. Timeout/error counters are incremented, and failed cycles write metrics instead of crashing.
- **Collector does not crash on Polygon timeout.** `_fetch_with_retry()` catches exceptions from `polygon_source.fetch_bulk_snapshots()` and returns an empty payload list after exhausting retries. `_cycle()` then writes metrics. The outer `run()` loop also catches unhandled cycle exceptions and continues.
- **Request-rate limiting exists but is incomplete.** `_can_request()` gates cycles against `MARKETDATA_MAX_REQUESTS_PER_MINUTE`, but retries are not counted as requests. This is the main D1 blocker for safe D2 integration.
- **Budget skipping is non-crashing.** When the rate-limit window is exhausted, `_cycle()` logs and returns without a Polygon call.

## Test coverage assessment

- **Phase D1 tests passed locally.** `python -m pytest tests/test_phase_d1.py -q` from `backend/` passed: 14 tests, 1 Starlette/httpx deprecation warning.
- **Polygon is mocked.** The D1 test suite patches `marketdata.polygon_source.fetch_bulk_snapshots()` and `data.polygon_client.get_bulk_ticker_snapshots()` for collector/source tests, avoiding real Polygon network calls.
- **Endpoints are covered.** Tests cover health response shape, symbol success, and missing-symbol 404. The suite does not currently cover `/symbols` or `/metrics`, so those endpoints should get explicit tests before D2.
- **Redis serialization is covered.** Tests verify snapshot key format, JSON payload serialization, and read deserialization.
- **Timeout and rate-limit behavior are covered at MVP level.** Tests prove the collector does not raise on a mocked timeout and skips a cycle when the request deque is full. They do not prove every retry is rate-budgeted, which is the critical gap noted above.
- **Safety invariants are partially covered.** Tests scan `backend/marketdata/` for forbidden broker/live-trading and AI/LLM imports, but they do not scan all touched files or prove V5 untouched.

## Safety assessment

- **No broker integration added.** The Phase D1 marketdata modules do not import broker SDKs or order-management code.
- **No live trading, real orders, or real-money execution added.** The collector only polls Polygon snapshots and writes Redis cache payloads/metrics.
- **No AI/LLM/Ollama/OpenAI/Anthropic/LangChain integration added.** The new collector modules are deterministic data plumbing.
- **Microtrading simulator strategy logic remains unchanged.** No `backend/paper/` strategy/simulator logic was modified in this patch.
- **V5 is not modified in this phase.** The latest patch file list is limited to backend marketdata/API/config/data additions and D1 tests; no V5 files are touched.
- **Safe alongside fake-money monitoring.** Running the collector alongside fake-money monitoring should not alter entries, exits, scoring, position sizing, journaling, or risk gates because no simulator consumer was changed.

## Is Phase D1 safe for fake-money monitoring?

**Yes, with operational caution.** Phase D1 is safe to run alongside the fake-money monitor because it is read-only with respect to trading decisions and has no broker/order/live-trading/real-money/AI paths. The collector should remain limited to a modest symbol list and conservative polling interval until the retry-aware rate limiter is fixed.

## Is any patch required before D2 integration?

**Yes.** Before D2 integrates simulator data consumption with this shared collector/cache, patch the rate limiter so every Polygon HTTP attempt, including retries, consumes request budget. Also wire `MARKETDATA_REQUEST_TIMEOUT_SECONDS` into the bulk Polygon request path and add explicit endpoint tests for `/api/marketdata/symbols` and `/api/marketdata/metrics`.
