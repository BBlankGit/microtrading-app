# Codex Review — Phase 2U Paper Redis State Integrity

Scope: review of the latest Phase 2U implementation patch only. No application code was changed by this review.

## Executive verdict

**Not yet safe for unattended fake-money monitoring.** The patch moves paper state to a versioned Redis key and adds several useful restore filters, but I found three integrity gaps that should be fixed before Phase 2U is considered complete:

1. Redis restore can keep a position whose `position_id` is missing or empty, so the position is not actually verified against a journal entry row.
2. Redis restore warnings produced while filtering positions are not propagated into the restore result/status path, so skipped positions are not visible to monitoring/UI consumers.
3. Redis save still runs after journal failure/exception and stamps `saved_after_journal: true`, so the marker does not prove journal persistence succeeded.

## Findings

### High — Empty/missing `position_id` can bypass journal verification

`try_redis_restore()` documents that `position_id` must be non-empty, but the implementation only checks membership when `pid` is truthy:

```python
pid: str = pos_data.get("position_id") or ""
...
if valid_pids is not None and pid and pid not in valid_pids:
    ... skip ...
```

Because both the orphan check and closed-position check are guarded by `pid`, a Redis position with a valid `entry_mode` but missing/empty `position_id` can be copied into `filtered` even when `valid_pids` is an empty set. That violates the Phase 2U requirement that Redis restore verify open positions against journal entry rows.

**Impact:** A polluted Redis snapshot can resurrect an open fake-money position that has no journal entry identity. This weakens state integrity and can make the dashboard/account state diverge from the journal.

**Recommended fix:** Reject any Redis position with a missing/empty `position_id` before journal set checks, with a visible warning such as `missing_position_id_skipped:<symbol>`. Add a regression test where `position_id` is absent or `""` and `valid_pids` is `set()`.

### High — Redis restore warnings are not surfaced in restore metadata/status

`try_redis_restore()` appends warnings to `snapshot["restore_warnings"]` when positions are skipped. However, `restore_session()` does not copy `snapshot.get("restore_warnings")` into `result["restore_warnings"]` on the Redis-success path; it only sets counts and returns.

**Impact:** Operators will not see Redis skip warnings through `restore_paper_session()`, `get_status()`, or the dashboard footer even though the lower-level filter generated them. This fails the requirement that skipped Redis positions produce visible restore warnings.

**Recommended fix:** In the Redis branch of `restore_session()`, copy `snapshot.get("restore_warnings", [])` into `result["restore_warnings"]`; optionally set `result["warning"]` when non-empty. Add a regression test that calls `restore_session()` with a Redis snapshot containing an orphaned/skipped position and asserts the returned result includes the warning.

### High — Redis save is not gated on journal persistence success

`run_tick()` correctly calls `_persist_journal_tick()` before `_save_state()`, but `_save_state()` is called unconditionally after the `try/except`. If `_persist_journal_tick()` raises, or returns a non-success result, Redis is still saved with `saved_after_journal: true` and possibly `tick_id=None`.

**Impact:** The new snapshot marker can be misleading. A Redis snapshot may claim it was saved after journal persistence even when journal persistence failed, which undermines the Phase 2U write-order integrity guarantee.

**Recommended fix:** Only call `_save_state(tick_id=...)` after a clearly successful journal result, for example `isinstance(result["journal"], dict) and result["journal"].get("ok") is True`. If journal persistence fails, leave Redis unchanged or write a clearly non-restorable marker that `try_redis_restore()` rejects. Add tests for journal exception and `ok=False` return cases asserting `_save_state` is not called.

## Requirement checklist

1. **Versioned environment/test-safe namespace:** Mostly satisfied. The active key is `{PAPER_STATE_REDIS_NAMESPACE}:state:v2` in both simulator and restore code, and the default namespace is configurable. TestClient-based integration tests patch `_save_state` to avoid production Redis writes. Residual risk remains for tests that call unpatched simulator APIs outside the `client` fixture, but the Phase 2U tests mock Redis for direct `_save_state()` coverage.
2. **Legacy `paper:state` ignored or strictly validated:** Active restore no longer reads bare `paper:state` or `{namespace}:state` v1. Legacy deletion is only available through the explicit `--all` clear script option. The restore path does not strictly validate legacy keys because it does not read them, which is acceptable.
3. **Tests cannot write production paper state:** Mostly satisfied for `client` tests via patched `_save_state`, and Phase 2U direct Redis tests use mocked Redis. This is not a process-wide autouse guard, so future direct tests could still write if they call unpatched `_save_state()`.
4. **Redis restore verifies open positions against journal entry rows:** Partially satisfied, but failed for missing/empty `position_id` because the journal membership check is skipped when `pid` is falsey.
5. **Redis restore rejects null/missing/unknown `entry_mode`:** Satisfied for `None`, missing keys, and unknown values because anything outside the allowed set is skipped.
6. **Skipped Redis positions produce visible restore warnings:** Failed at the user-visible restore metadata layer. `try_redis_restore()` produces warnings, but `restore_session()` drops them on the Redis path.
7. **Redis save happens after journal persistence success:** Failed. Redis save happens after the journal attempt, not after confirmed journal success.
8. **Reset/clear affects only paper simulator state:** Satisfied. `reset_simulator()` resets in-memory paper account/status and writes only the configured v2 paper Redis key. The clear script targets the v2 key by default and only adds legacy paper keys with `--all`; it does not touch marketdata cache, runtime config, or journal DB.
9. **Strategy/catalyst/no-catalyst logic not changed:** For the latest Phase 2U patch, satisfied. The latest patch changes restore/persistence/test/clear behavior only; no strategy decision branches were changed in this latest diff.
10. **Marketdata cache logic not changed:** Satisfied for the latest Phase 2U patch. No marketdata cache files were modified by this latest patch.
11. **No broker/live trading/real orders/AI/LLM/Ollama added:** Satisfied. The inspected imports and patch scope do not add broker, live-trading, real-order, AI, LLM, or Ollama integrations.
12. **Safe for fake-money monitoring:** Not yet. The feature is close, but the three high-severity findings above should be fixed before relying on Phase 2U state restore during fake-money monitoring.

## Tests/checks run

- `pytest backend/tests/test_phase_2u.py backend/tests/test_phase_2s.py backend/tests/test_phase_2s_h1.py` — passed: 55 tests passed, 1 existing Starlette/httpx deprecation warning.
- `git diff HEAD^..HEAD -- backend/paper/simulator.py backend/paper/session_restore.py backend/scripts/clear_paper_state.py` — inspected latest Phase 2U implementation diff.
- `rg -n "_save_state\(|make_redis|paper:prod:state|paper:state" backend/tests backend -g '*.py'` — inspected Redis write/test-isolation touch points.
