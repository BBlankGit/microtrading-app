# Codex Review — Phase 2A-H1 Paper Simulator Clarity and Tests

Review target: latest Phase 2A-H1 patch, commit `bf22364` (`Harden Phase 2A paper simulator clarity and tests`), after the previous Phase 2A Codex review.

## Critical issues

1. **The new protected-endpoint test can still invoke the real simulator tick path, which can call real Polygon when `POLYGON_API_KEY` is configured.**
   - `test_protected_endpoints_accept_correct_token` POSTs to every protected paper endpoint, including `/api/paper/start` and `/api/paper/tick`.
   - `/api/paper/start` starts the background simulator task, and `/api/paper/tick` calls `simulator.run_tick()` directly.
   - `run_tick()` calls `polygon_client.get_ticker_snapshot()` and `polygon_client.get_previous_close()` for each configured paper-universe symbol.
   - Because this API-level test does not mock `paper.simulator.polygon_client`, it does not fully satisfy the stated requirement that added tests do not call real Polygon. It may be harmless in a local environment without a Polygon key, but it is not safe as a general CI/test invariant.

2. **The added async tests did not run in this environment because the pytest async plugin was not active.**
   - Running `POLYGON_API_KEY= pytest tests/test_paper.py -q` from `backend/` produced `29 passed, 7 failed`; all 7 failures were async test collection/execution failures: `async def functions are not natively supported`.
   - `backend/requirements.txt` lists `pytest-asyncio`, so this may be an environment installation issue rather than a code issue, but the current check means I could not confirm the async tick/loop tests by execution in this container.

## Non-blocking issues

1. **The helper `_patch_tick()` in `backend/tests/test_paper.py` appears unused and partially misleading.**
   - It defines `fake_evaluate()` and `fake_collect()`, but returns patches that ignore those helpers and instead hard-code non-tradable quality and an empty catalyst response.
   - Since the later tick tests patch their dependencies inline, this helper is not currently harming runtime behavior. Removing or correcting it would reduce future confusion.

2. **`state_restored_from_snapshot` is hard-coded to `False` in `get_status()` rather than read from `_state`.**
   - This matches the current implementation because there is no restore path, but using `_state["state_restored_from_snapshot"]` would make the reported status more mechanically consistent with the module-level state shape.
   - This is not blocking because the current hard-coded value is the safe/accurate value for this patch.

3. **The dashboard renders `Restart Persistent` and the footer `restart_persistent` as literal `false` instead of using the API field.**
   - That is safe and accurate for this phase, but using `String(s.restart_persistent ?? false)` would prove the UI is displaying the API contract instead of a parallel literal.
   - This is non-blocking because the requirement is to clearly display `restart_persistent=false`, and it does.

## Test coverage assessment

- The tests meaningfully cover core fake-money account behavior: reset, entries, cash deduction, max positions, max daily trades, duplicate-position blocking, P&L, and exits.
- The tests add useful API clarity assertions for `/api/status`, `/api/paper/status`, and `/api/paper/dashboard`, including `snapshot_storage`, `state_restored_from_snapshot`, and `restart_persistent`.
- The tests add useful safety-invariant scans for broker SDK imports, order-execution symbols, and AI/LLM imports within the paper module.
- The tick-level tests are directionally meaningful: they attempt to validate take-profit, stop-loss, max-hold exits, max-position blocking, duplicate-position blocking, and background-loop idempotence.
- However, coverage has two blockers before I would call the test patch clean:
  1. The protected-endpoint API test can call unmocked Polygon through `/api/paper/start` and `/api/paper/tick`.
  2. The async tests did not execute in this environment because `pytest-asyncio` was not active/installed here.

## Safety assessment

- **Redis persistence wording is clearer and no longer implies restart-safe persistence.** The API now reports `snapshot_storage`, `state_restored_from_snapshot=false`, and `restart_persistent=false`; the dashboard footer explicitly says Redis is only a best-effort latest-state snapshot and that simulator state is not restored after container restart.
- **`/api/status` now distinguishes fake-money paper simulation from broker paper trading.** It reports `paper_simulator_available=true`, `paper_trading_real_broker=false`, `live_trading_enabled=false`, `broker_connected=false`, and the message explicitly says no broker connection, live trading, real orders, or real-money execution is implemented.
- **`/api/paper/status` and `/api/paper/dashboard` expose the requested fields.** `get_status()` includes `snapshot_storage`, `state_restored_from_snapshot=false`, and `restart_persistent=false`; `/api/paper/dashboard` embeds that same status payload.
- **The dashboard clearly communicates fake-money simulation and safety boundaries.** It shows “Research-only fake-money simulation,” “No broker,” “No live trading,” “No real orders,” and `restart_persistent: false`, plus the non-restore Redis wording.
- **No broker integration, live trading, real-order path, AI/LLM call, strategy scoring, or real-money execution appears to have been added by this patch.** The inspected changes are status/disclaimer wording, snapshot metadata exposure, dashboard text/fields, and tests. The simulator continues to place only virtual positions in `PaperAccount` and contains no broker/order SDK integration.

## Safe to run tomorrow as fake-money simulation?

**Yes, with the same operational caveat as Phase 2A: it is safe to run as a fake-money research simulation, not as broker paper trading or live trading.** The reviewed patch improves labeling and status metadata and does not add broker connectivity, live trading, real orders, real-money execution, AI/LLM calls, or strategy scoring.

## Is any patch required before market hours?

- **Runtime safety:** No patch is required before market hours solely for fake-money simulation safety; the safety wording and API fields are now clear.
- **Test/CI safety:** A patch is required before treating the new tests as compliant with the “do not call real Polygon” requirement. The protected-endpoint test should mock `paper.simulator.start_simulator`, `paper.simulator.stop_simulator`, `paper.simulator.reset_simulator`, and/or `paper.simulator.run_tick`, or otherwise exclude `/api/paper/start` and `/api/paper/tick` from unmocked API auth checks.
- **Test execution environment:** Ensure `pytest-asyncio` is installed/active before relying on the async tests in CI.

## Commands run

- `git status --short`
- `git log --oneline -8`
- `git show --stat --oneline HEAD`
- `git diff --name-only HEAD^ HEAD`
- `git diff --stat HEAD^ HEAD`
- `git diff --unified=80 HEAD^ HEAD -- backend/main.py backend/paper/simulator.py frontend/dashboard/app/page.tsx`
- `nl -ba backend/api/paper.py`
- `nl -ba backend/main.py`
- `nl -ba backend/paper/simulator.py`
- `nl -ba frontend/dashboard/app/page.tsx`
- `nl -ba backend/tests/test_paper.py`
- `rg -n "openai|anthropic|langchain|alpaca|ibkr|interactive|broker|place_order|submit_order|execute_order|send_order|create_order|live_trading|real[-_ ]?money|paper_trading" backend frontend -g '!**/__pycache__/**'`
- `cd backend && POLYGON_API_KEY= pytest tests/test_paper.py -q`
