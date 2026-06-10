# Codex Review — Phase 2U-H1 Paper State Integrity

Review target: latest Phase 2U-H1 patch, commit `944f0ae` (`Fix Redis paper state integrity gaps`).

Scope honored: this review inspected only the latest patch and the directly connected restore/status/API plumbing needed to verify warning propagation. No code changes were made.

## Verdict

**Phase 2U-H1 is safe for fake-money monitoring.** The patch closes the high-severity integrity gaps it targets:

- Redis restore now drops Redis positions with missing, null, or empty `position_id` before per-position journal membership checks can accidentally fail open.
- Dropped Redis positions produce visible restore warnings.
- Redis restore warnings propagate from `try_redis_restore()` into `restore_session()`, then into simulator status, `/api/paper/status`, and the embedded status in `/api/paper/dashboard`.
- The normal tick path now saves Redis only after journal persistence returns `ok: true`; journal exceptions and `ok: false` responses no longer write a Redis snapshot.
- `saved_after_journal: true` is stamped by `_save_state()`, and the patched tick path only reaches `_save_state()` after confirmed journal success.
- The latest patch did not alter strategy selection, catalyst/no-catalyst handling, marketdata cache behavior, broker/live-order code, or AI/LLM/Ollama behavior.

## Findings

### Blocking findings

None.

### Non-blocking observation

`reset_simulator()` still calls `_save_state()` directly after clearing in-memory state. That call stamps `saved_after_journal: true` without a journal write in that reset path. This does **not** appear to undermine the Phase 2U-H1 open-position integrity goal because reset clears positions before saving, so there are no Redis open positions that could lack journal rows. Still, if the project wants the phrase "`saved_after_journal: true` only ever appears after journal `ok: true`" to be globally literal rather than tick-path-specific, the reset path should eventually get separate metadata or delete/clear Redis instead of calling `_save_state()`.

## Review checklist

### 1. Redis restore rejects missing/null/empty `position_id` before journal checks

**Pass.** `try_redis_restore()` converts a missing/null/empty `position_id` to `""`, checks `if not pid`, appends a `missing_position_id_skipped:<symbol>` warning, logs a warning, and `continue`s before the entry-mode, valid-entry, and closed-position checks for that position.

One nuance: the function still fetches the journal ID sets once before iterating positions. The important integrity behavior is correct: each bad position is rejected before any per-position journal membership checks can be evaluated or fail open.

### 2. Skipped Redis positions with missing `position_id` produce visible restore warnings

**Pass.** The missing-ID branch appends `missing_position_id_skipped:<symbol>` into `restore_warnings`, and the filtered snapshot is returned with that list attached. The new regression tests cover both empty-string and absent-key cases.

### 3. Redis restore warnings propagate through `restore_session()`, `get_status()`, `/api/paper/status`, and `/api/paper/dashboard`

**Pass.** The Redis branch in `restore_session()` copies `snapshot["restore_warnings"]` into `result["restore_warnings"]` and sets `result["warning"]` when warnings exist. `restore_paper_session()` stores those fields in simulator `_state`; `get_status()` includes `restore_warning` and `restore_warnings`; `/api/paper/status` returns `simulator.get_status()` directly; `/api/paper/dashboard` embeds that same status object under `status`.

### 4. `_save_state` is called only after journal persistence returns `ok: true`

**Pass for the normal tick path changed by Phase 2U-H1.** `run_tick()` initializes journal state to not attempted, calls `_persist_journal_tick()`, catches exceptions as `ok: false`, computes `_journal_ok` using `result["journal"].get("ok") is True`, and calls `_save_state()` only inside that true branch.

Non-blocking nuance: `reset_simulator()` still calls `_save_state()` outside the journal path after clearing state; see the observation above.

### 5. Redis is not saved when journal persistence raises or returns `ok: false`

**Pass for the tick path.** If `_persist_journal_tick()` raises, `run_tick()` records an error dict and `_journal_ok` is false. If it returns `{"ok": false}`, `_journal_ok` is also false. In both cases `_save_state()` is skipped. The new regression tests explicitly cover the raise, `ok: false`, and `ok: true` branches.

### 6. `saved_after_journal: true` is only stamped on confirmed journal success

**Pass for tick-generated snapshots.** `_save_state()` still stamps `saved_after_journal: true`, but the patched `run_tick()` only calls `_save_state()` after confirmed `ok: true` journal persistence.

Non-blocking nuance: reset-generated empty snapshots are still stamped through the direct reset path, as noted above.

### 7. Strategy/catalyst/no-catalyst logic was not changed

**Pass.** The latest patch changes only `backend/paper/session_restore.py`, the journal-gated `_save_state()` call in `backend/paper/simulator.py`, and tests. The simulator diff is isolated to the Redis persistence gate after the journal write; it does not touch candidate scoring, entry modes, catalyst evaluation, momentum/no-catalyst handling, bracket exits, or sizing logic.

### 8. Marketdata cache logic was not changed

**Pass.** The latest simulator change occurs after journal persistence and before the existing market-regime comment. It does not change marketdata adapter calls, cache counters, last-tick marketdata state, or cache result handling.

### 9. No broker/live trading/real orders/AI/LLM/Ollama were added

**Pass.** The changed implementation files do not add broker/live-order execution or AI/LLM/Ollama integrations. Existing status fields continue to report `mode: research_paper_simulation`, `live_trading_enabled: false`, and `broker_connected: false`; the dashboard disclaimer remains research-only fake-money with no broker, no live trading, and no real orders.

### 10. Phase 2U-H1 safety for fake-money monitoring

**Pass.** The patch is safe for fake-money monitoring. Redis restore is stricter for malformed paper positions, operators can see restore warnings in status/dashboard payloads, and Redis writes in the tick loop no longer occur when the journal write fails. The remaining reset-path nuance is not a live-trading or real-money risk and does not restore unsafe open positions because reset saves an empty account state.

## Evidence reviewed

- `backend/paper/session_restore.py`: Redis restore validation, warning accumulation, and `restore_session()` Redis warning propagation.
- `backend/paper/simulator.py`: simulator state/status warning fields, restore application, journal-gated Redis persistence, `_save_state()` metadata, and reset-path nuance.
- `backend/api/paper.py`: `/api/paper/status` and `/api/paper/dashboard` status plumbing.
- `backend/tests/test_phase_2u.py`: targeted Phase 2U-H1 regression coverage.

## Validation run

- `pytest backend/tests/test_phase_2u.py -q` — passed: 28 passed, 1 warning.
