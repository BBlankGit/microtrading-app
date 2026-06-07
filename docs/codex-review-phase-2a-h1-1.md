# Codex Review: Phase 2A-H1.1 Test Isolation Patch

Reviewed patch: `2d56357 Isolate paper endpoint auth tests from real Polygon calls`

Scope reviewed: only the latest patch touching `backend/tests/test_paper.py`.

## Critical issues

None found in the scoped patch.

The protected endpoint happy-path auth test now patches all four state-changing simulator call sites before POSTing to the protected endpoints:

- `paper.simulator.start_simulator`
- `paper.simulator.stop_simulator`
- `paper.simulator.reset_simulator`
- `paper.simulator.run_tick`

Because `backend/api/paper.py` imports the simulator module (`from paper import simulator`) and calls functions through that module, patching `paper.simulator.*` is the correct patch target for these endpoints.

## Non-blocking issues

- The patch leaves an unused top-level `asyncio` import in `backend/tests/test_paper.py`. This is harmless for behavior and test isolation, but it is cleanup debt.
- The local execution environment is missing `pytest-asyncio`, even though `backend/requirements.txt` declares it. As a result, the full `tests/test_paper.py` file cannot complete in this environment because async tests are rejected by pytest before execution. This appears to be an environment/dependency issue rather than a regression caused by the scoped patch.
- The targeted protected endpoint auth tests pass with `POLYGON_API_KEY=dummy`, which is the most relevant verification for the H1.1 isolation concern.

## Test isolation assessment

Pass.

The previous risk was that `test_protected_endpoints_accept_correct_token` could hit real Polygon through `/api/paper/start` and `/api/paper/tick` when `POLYGON_API_KEY` was configured. The scoped patch resolves that specific risk:

- `/api/paper/start` is isolated by patching `paper.simulator.start_simulator` with `AsyncMock`.
- `/api/paper/stop` is isolated by patching `paper.simulator.stop_simulator` with `AsyncMock`.
- `/api/paper/reset` is isolated by patching `paper.simulator.reset_simulator` with `AsyncMock`.
- `/api/paper/tick` is isolated by patching `paper.simulator.run_tick` with an `AsyncMock` returning a static tick stub.
- The patched test posts to every protected endpoint only while these mocks are active.

The missing-token and wrong-token tests still do not require simulator mocks because request handling rejects unauthorized calls before the simulator functions should execute. The current test outcomes support this: the targeted protected endpoint auth tests pass with a configured `POLYGON_API_KEY` value.

## Safety assessment

Pass.

No runtime code was changed in the latest patch; `git diff --name-only HEAD~1..HEAD` reports only `backend/tests/test_paper.py`.

No broker integration, live trading, real order path, AI/LLM call, or strategy scoring path was introduced by the scoped patch. The changes are limited to test imports, protected endpoint test mocks, and removal of unused/misleading test helpers.

The existing paper safety invariant tests remain present and still scan the paper module for broker imports, order execution patterns, and AI/LLM imports.

## Unused/misleading helper removal

Pass.

The scoped patch removes the unused `_patch_tick(...)` helper and `_run(...)` helper. This is safe because the async tick tests directly use `pytest.mark.asyncio` and explicit mocks around `polygon_client`, `evaluate_market_quality`, `collect_news_for_symbols`, and `_save_state` at each call site. Removing the stale helper reduces confusion without reducing test coverage.

## Pytest results

Commands run:

```bash
cd backend && POLYGON_API_KEY=dummy pytest tests/test_paper.py -q
```

Result: 29 passed, 7 failed, 9 warnings.

Failure reason: the environment does not have `pytest-asyncio` installed, so pytest reports that async tests are not natively supported and treats every `@pytest.mark.asyncio` test as a failure. The warnings also show `Unknown config option: asyncio_mode` and unknown `pytest.mark.asyncio`, which is consistent with the missing plugin.

```bash
cd backend && POLYGON_API_KEY=dummy pytest tests/test_paper.py -q -k 'protected_endpoints_accept_correct_token or protected_endpoints_reject_missing_token or protected_endpoints_reject_wrong_token'
```

Result: 3 passed, 33 deselected, 9 warnings.

Assessment: acceptable for validating this H1.1 patch's core isolation goal. Full-file pytest completion still depends on installing the declared `pytest-asyncio` test dependency in the execution environment.

## Previous Codex concern status

Fully resolved for the protected paper endpoint auth tests.

With the new mocks in place, the happy-path protected auth test no longer starts the real simulator loop and no longer invokes the real tick path. Therefore it should not call real Polygon even when `POLYGON_API_KEY` is configured.

## Phase 2A fake-money readiness

Phase 2A is safe to run tomorrow as fake-money simulation, based on this scoped review, provided it is run in the existing paper-simulation mode and not connected to any broker or live-order system.

This review found no new broker, live trading, real order, AI/LLM, strategy scoring, or real-money path in the latest test-only patch.
