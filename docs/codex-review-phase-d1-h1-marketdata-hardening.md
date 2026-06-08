# Codex Review — Phase D1-H1 Market Data Collector Rate-Limit and Timeout Hardening

Review target: latest patch `a7ab6b9` (`Harden market data collector rate limiting and timeout handling`).

Scope honored: this review covers only the Phase D1-H1 market-data hardening patch. No code changes were made.

## Critical issues

None found.

The D1-H1 patch addresses the previously important collector hardening concerns: Polygon attempts are budgeted per actual collector bulk fetch attempt, retries are counted and budget-gated, the configured request timeout reaches the Polygon bulk snapshot client path, API endpoint coverage was added, symbol validation was tightened, and Redis cache connections are closed in `finally` blocks.

## Non-blocking issues

1. **`skipped_due_to_rate_limit_last_minute` is cycle-skip oriented, not retry-skip oriented.**
   - The collector increments the skipped counter when an entire cycle is skipped before any fetch attempt because no budget remains.
   - If the first attempt uses the last available budget slot and the retry is therefore skipped, the retry correctly does not run, but the skipped counter does not record that skipped retry opportunity.
   - This is not blocking because the actual Polygon budget is still protected and retries still stop when exhausted. If D2 wants more granular observability, consider either documenting this metric as `cycles_skipped_due_to_rate_limit_last_minute` or adding a separate `retry_attempts_skipped_due_to_rate_limit_last_minute` metric.

2. **The collector reserves a budget slot before calling the bulk source.**
   - This is the safest ordering for real HTTP calls because failures and exceptions still consume budget.
   - It can over-count in non-HTTP preflight cases, such as an empty symbol list or Polygon not configured, but this is conservative and does not create API pressure.

## Rate-limit assessment

**Assessment: pass.**

- Each collector Polygon bulk fetch attempt is budgeted immediately before calling the Polygon source.
- Retries consume the same `polygon_attempts` budget as first attempts.
- Budget is checked before every first attempt and retry attempt.
- If no budget remains at cycle start, the cycle is skipped and no Polygon source call is made.
- If budget runs out after a failed first attempt, retry is skipped and the collector returns an empty payload list instead of making another Polygon call.
- `MARKETDATA_MAX_REQUESTS_PER_MINUTE` therefore caps actual collector Polygon bulk attempts, not merely collector cycles.
- The test suite explicitly covers:
  - one successful fetch consuming one Polygon attempt;
  - failed fetch plus retry consuming two Polygon attempts;
  - budget exhaustion preventing a retry;
  - repeated cycles not exceeding `MARKETDATA_MAX_REQUESTS_PER_MINUTE`.

## Timeout assessment

**Assessment: pass.**

- `MARKETDATA_REQUEST_TIMEOUT_SECONDS` is defined in settings and remains `8` seconds by default.
- The market-data Polygon source passes that setting into `data.polygon_client.get_bulk_ticker_snapshots(...)`.
- `get_bulk_ticker_snapshots(...)` now accepts an optional `timeout` argument and forwards it to `_get(...)`.
- `_get(...)` uses the supplied timeout for `httpx.AsyncClient`; if omitted, it preserves the existing default timeout behavior.
- The D1-H1 test suite explicitly asserts that `fetch_bulk_snapshots(...)` passes `MARKETDATA_REQUEST_TIMEOUT_SECONDS` into the Polygon bulk snapshot client.

## API endpoint/test assessment

**Assessment: pass.**

- `/api/marketdata/symbols` has an explicit structure test.
- `/api/marketdata/metrics` has an explicit structure test and checks the new metric keys.
- These endpoint implementations read settings, service status, and Redis cache state only; they do not import or call the Polygon source/client.
- The endpoint tests mock service/cache dependencies and do not exercise real Polygon network calls.
- The broader D1 test module states all Polygon calls are mocked and includes a direct no-real-Polygon test for the market-data source path.

## Redis/cache assessment

**Assessment: pass.**

- `write_cycle_results(...)`, `read_symbol(...)`, `read_active_symbols(...)`, and `read_metrics(...)` all close Redis connections in `finally` blocks.
- Cache write/read exceptions are contained so the collector/API do not crash because of Redis serialization or read failures.
- A D1-H1 test explicitly verifies Redis connection close behavior when a cache write raises.
- Symbol endpoint validation now rejects empty, overlong, and special-character symbols before reaching `cache.read_symbol(...)`, preventing arbitrary Redis snapshot key suffixes through the public symbol route.

## Safety assessment

**Assessment: pass.**

- The D1-H1 patch changed only market-data API, data client, market-data collector/cache/source/service/health, and D1 tests.
- No microtrading simulator strategy files were changed by the latest patch.
- No V5 files were changed by the latest patch.
- The market-data modules remain explicitly read-only/research-only and state no broker, no live trading, no real orders, and no real-money execution.
- No broker integration, live trading, real order submission, real-money execution, AI/LLM integration, Ollama, OpenAI, Anthropic, or LangChain functionality was added in the D1-H1 patch.

## Whether D1-H1 is safe for fake-money monitoring

**Yes.** D1-H1 is safe for fake-money monitoring.

Rationale:

- The collector remains disabled by default via `MARKETDATA_COLLECTOR_ENABLED=false`.
- When manually enabled, it performs read-only Polygon REST collection and Redis cache writes only.
- It does not connect to a broker, place orders, execute trades, or alter simulator strategy logic.
- Rate limiting is conservative and guards every collector bulk fetch attempt, including retries.
- Timeout handling is wired through the collector bulk snapshot path.
- Redis failure handling is defensive and should not turn cache errors into runaway collector behavior.

## Whether any patch is required before D2 integration

**No blocking patch is required before D2 integration.**

Recommended optional follow-up for D2 observability only: clarify whether `skipped_due_to_rate_limit_last_minute` intentionally means skipped cycles, or add a separate retry-skip metric if D2 needs to distinguish skipped retry opportunities from skipped cycles.
