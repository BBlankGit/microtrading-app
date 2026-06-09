# Codex Review — Phase D4-H1 Marketdata Collector Auto-start

Reviewed patch: `7db1575 Auto-start marketdata collector after backend restart` (`HEAD~1..HEAD`).

## Scope

Only the latest Phase D4-H1 patch was reviewed. The patch changes:

- `backend/main.py`
- `backend/marketdata/service.py`
- `backend/marketdata/health.py`
- `backend/tests/conftest.py`
- `backend/tests/test_phase_d4_h1.py`

No strategy, catalyst, no-catalyst, broker, live-trading, order-execution, AI, LLM, or Ollama files were modified by this patch.

## Review Findings

### Finding 1 — Monitoring endpoint does not expose collector auto-start state

**Severity:** Low/Medium

`/api/marketdata/health` now exposes `enabled`, `running`, `started_at`, and `auto_started`, which is enough to verify that the collector was auto-started by backend lifespan. However, the broader monitoring surface (`/api/monitoring`) still only reports the paper marketdata-cache feature flag and `collector_running`; it does not include the collector's configured enabled state (`MARKETDATA_COLLECTOR_ENABLED`), `auto_started`, or `started_at`.

For fake-money operations, this means an operator using the monitoring dashboard can see that the cache is enabled and the collector is running, but cannot distinguish whether the collector was automatically restored after a backend restart or manually started later. This is not a trading-safety issue, but it does not fully satisfy the review focus item that health/monitoring clearly show enabled/running/auto-start state.

**Suggested fix:** Include `collector_enabled`, `collector_auto_started`, and `collector_started_at` in the `/api/monitoring` `marketdata_cache` object, sourced from `settings.MARKETDATA_COLLECTOR_ENABLED` and `marketdata.service.get_service_status()`.

### Finding 2 — New AST safety test is current-working-directory sensitive

**Severity:** Low

`backend/tests/test_phase_d4_h1.py::test_no_broker_or_ai_imports_in_service` reads `Path("marketdata/service.py")`. This passes when pytest is launched from `backend/`, but it fails when the same test is launched from the repository root as `pytest backend/tests/test_phase_d4_h1.py`, because the relative path resolves to `/workspace/microtrading-app/marketdata/service.py` instead of `/workspace/microtrading-app/backend/marketdata/service.py`.

This is a test robustness issue only; it does not affect runtime collector behavior. It also does not cause real Polygon calls.

**Suggested fix:** Resolve the service path relative to the test file, for example `Path(__file__).resolve().parents[1] / "marketdata" / "service.py"`.

## Focus-Area Assessment

1. **Collector auto-starts after backend restart when enabled:** Pass. `main.lifespan()` calls `marketdata.service.start_collector(auto_started=True)` when `settings.MARKETDATA_COLLECTOR_ENABLED` is true.
2. **Collector remains disabled when configured disabled:** Pass. Lifespan does not call `start_collector()` when `MARKETDATA_COLLECTOR_ENABLED` is false.
3. **Manual start/stop still works:** Pass. `start_collector()` defaults `auto_started=False`; `stop_collector()` clears `started_at` and `auto_started`. Existing admin start/stop endpoints continue to call the same service functions.
4. **Health/monitoring clearly show enabled/running/auto-start state:** Partial. `/api/marketdata/health` does; `/api/monitoring` does not expose `auto_started`, `started_at`, or collector-enabled state.
5. **Paper ticks use cache after restart without manual collector start:** Pass with configuration caveat. When `MARKETDATA_COLLECTOR_ENABLED=true`, the collector is started during backend lifespan, so the existing paper marketdata cache adapter can consume cache data without a manual collector start. The patch does not change the paper tick/cache adapter logic.
6. **No strategy/catalyst/no-catalyst logic changed:** Pass. The latest patch does not modify strategy, catalyst, or no-catalyst modules.
7. **No broker/live trading/real orders/AI/LLM/Ollama added:** Pass. The changed runtime modules remain marketdata/backend-lifecycle only and include no broker, live trading, real-order, AI, LLM, or Ollama imports.
8. **Tests avoid real Polygon calls:** Pass. Lifespan tests patch `marketdata.service.start_collector`; health tests patch cache/Redis access; service tests patch the collector class/task creation. No test performs a real Polygon request.
9. **D4-H1 is safe for fake-money monitoring:** Pass with the monitoring visibility caveat in Finding 1. The implementation starts a read-only marketdata collector and does not add live trading, broker, order submission, or AI/LLM behavior.

## Test / Check Commands Run

- `git diff --stat HEAD~1..HEAD`
- `git diff --name-only HEAD~1..HEAD`
- `git diff HEAD~1..HEAD -- backend/main.py backend/marketdata/health.py backend/marketdata/service.py backend/tests/conftest.py backend/tests/test_phase_d4_h1.py`
- `pytest backend/tests/test_phase_d4_h1.py` from repository root — failed because the new AST test uses a cwd-sensitive relative path.
- `(cd backend && pytest tests/test_phase_d4_h1.py)` — passed, 7 passed, with warnings about Starlette/httpx deprecation and an unawaited `AsyncMock` warning.
- `(cd backend && pytest tests/test_phase_d4.py tests/test_phase_d4_h1.py)` — passed, 27 passed, 1 skipped, with the same warning classes.

## Overall Recommendation

D4-H1 is safe for fake-money monitoring and correctly auto-starts the read-only collector when explicitly enabled. I recommend addressing the monitoring visibility gap before considering the monitoring/dashboard acceptance criteria fully complete, and fixing the cwd-sensitive test path to make the test reliable from both repository-root and backend working directories.
