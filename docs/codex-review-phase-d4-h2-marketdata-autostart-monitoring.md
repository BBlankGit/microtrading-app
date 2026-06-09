# Codex Review — Phase D4-H2 Marketdata Autostart Monitoring Polish

## Review scope

Reviewed only the latest D4-H2 patch at `bcff515` (`Expose marketdata autostart status in monitoring`). No production code changes were made as part of this review.

## Verdict

**Approved for fake-money monitoring.** The D4-H2 patch is observability-focused, exposes the requested collector lifecycle fields through `/api/monitoring/status`, keeps `/api/marketdata/health` aligned with the collector service state, removes the D4-H1 cwd-sensitive test path, and does not introduce broker/live-trading/real-order/AI/LLM/Ollama behavior.

## Findings

### 1. `/api/monitoring/status` collector fields

Pass. The endpoint now adds the requested fields under the `marketdata_cache` object:

- `collector_enabled` from `settings.MARKETDATA_COLLECTOR_ENABLED`
- `collector_running` from `marketdata.service.get_service_status()["running"]`
- `collector_auto_started` from `marketdata.service.get_service_status()["auto_started"]`
- `collector_started_at` from `marketdata.service.get_service_status()["started_at"]`

The values are read-only status values and do not start, stop, or otherwise mutate the collector.

### 2. `/api/marketdata/health` correctness

Pass. The D4-H2 patch does not modify `backend/api/marketdata.py`, `backend/marketdata/health.py`, `backend/marketdata/service.py`, cache reading, Redis probing, or Polygon collection code. The health endpoint continues to delegate to `marketdata.health.get_health()`, add the read-only disclaimer, and report service-derived `running`, `started_at`, and `auto_started` values consistently with the service status.

### 3. D4-H1 test path cwd-sensitivity

Pass. `backend/tests/test_phase_d4_h1.py` no longer reads `Path("marketdata/service.py")` relative to the current working directory. It now resolves the backend directory from `__file__` before reading `marketdata/service.py`, so the test works from both the repository root and the backend directory.

### 4. Tests from repository root and backend directory

Pass. Full backend test runs passed from both locations:

- Repository root: `pytest backend/tests` → `805 passed, 1 skipped, 1 warning`
- Backend directory: `pytest tests` → `805 passed, 1 skipped, 1 warning`

Both runs emitted the same existing warning profile: a Starlette/httpx deprecation warning plus an unawaited `AsyncMock` runtime warning during teardown. These warnings did not fail the suite and are not introduced by code changes in this review.

### 5. Marketdata fetch logic

Pass. The latest patch does not alter marketdata fetch behavior. The production change is limited to adding read-only monitoring fields in `backend/api/monitoring.py`. The remaining patch hunks only adjust tests by forcing `paper.marketdata_adapter.try_cache_for_quality` to return a cache miss in tests that are intended to exercise mocked `evaluate_market_quality` behavior, preventing real Redis cache data from leaking into those tests when the collector is enabled.

### 6. Strategy, catalyst, and no-catalyst logic

Pass. No production strategy, catalyst, no-catalyst, simulator entry/exit, scoring, risk guard, or trade-decision logic was changed in the D4-H2 patch. The affected strategy-adjacent files are tests only, and those changes isolate marketdata cache state rather than changing expected business behavior.

### 7. Broker/live trading/real orders/AI/LLM/Ollama additions

Pass. The latest patch does not add broker integrations, live trading paths, real order execution, AI/LLM/Ollama integrations, or related imports. The existing D4-H1 safety test continues to parse `marketdata/service.py` and assert forbidden broker/AI imports are absent, and the full safety test suite passes.

### 8. Fake-money monitoring safety

Pass. D4-H2 is safe for fake-money monitoring. It improves operator visibility into whether the marketdata collector is configured, running, auto-started, and when it started. It does not add execution capabilities, does not connect to a broker, and does not change marketdata collection/fetch semantics or simulated trading decision logic.

## Files reviewed

- `backend/api/monitoring.py`
- `backend/api/marketdata.py`
- `backend/marketdata/health.py`
- `backend/marketdata/service.py`
- `backend/main.py`
- `backend/tests/test_phase_d4_h1.py`
- Latest-patch test updates in `backend/tests/test_paper.py`, `backend/tests/test_phase2m.py`, `backend/tests/test_phase2n.py`, `backend/tests/test_phase2n_lite.py`, and `backend/tests/test_phase2o_lite.py`

## Commands run

```bash
git show --stat --oneline HEAD
git show --name-only --format='' HEAD
git diff HEAD^ HEAD -- backend/tests/test_phase2n.py backend/tests/test_phase2n_lite.py backend/tests/test_phase2o_lite.py
pytest backend/tests
(cd backend && pytest tests)
```
