# Codex Review — Phase 2S-H2 Paper Session Restore NY Date and Dashboard Metadata

Review target: latest Phase 2S-H2 patch only (`HEAD` `bbf31ce`, parent `3ee7a2e`).

## Verdict

**Approved / no blocking findings.** Phase 2S-H2 is safe and complete for fake-money monitoring within the requested scope.

The patch keeps the changes limited to paper account date handling, session-restore diagnostics, dashboard restore metadata rendering, and regression tests. I did not find broker/live-trading/real-order/AI/LLM/Ollama additions, and I did not find strategy/catalyst/no-catalyst or marketdata cache logic changes in the latest patch.

## Scope reviewed

Latest patch files:

- `backend/paper/account.py`
- `backend/paper/session_restore.py`
- `backend/tests/test_phase_2s.py`
- `backend/tests/test_phase_2s_h1.py`
- `backend/tests/test_phase_2s_h2.py`
- `frontend/dashboard/app/page.tsx`

Review commands used:

- `git diff --stat HEAD~1..HEAD`
- `git diff --name-only HEAD~1..HEAD`
- `git diff --color=never HEAD~1..HEAD -- backend/paper/account.py backend/paper/session_restore.py frontend/dashboard/app/page.tsx`
- `rg -n "restore_paper_session|persist|paper_trades_journal|record|insert|position_id" backend/paper/simulator.py backend/paper/journal.py backend/paper/session_restore.py`
- `rg -n "interface PaperStatus|type PaperStatus|restart_persistent|restore_source|state is not restored|not restored|container restart|restore_warning|restore_warnings" frontend/dashboard/app/page.tsx backend/paper/simulator.py backend/paper/session_restore.py backend/paper/account.py`
- `pytest backend/tests/test_phase_2s_h2.py backend/tests/test_phase_2s_h1.py backend/tests/test_phase_2s.py`

## Findings

No blocking findings.

## Focus-area review

### 1. PaperAccount daily trade count uses America/New_York date consistently

**Pass.** `PaperAccount.today_str()` now constructs an `America/New_York` `ZoneInfo`, calls the injected clock with that timezone when present, otherwise calls `datetime.now(tz)`, and returns the resulting NY calendar date. `daily_trade_count()` and `_refresh_daily_count()` both flow through `today_str()`, so the reset/check date is now NY-scoped.

Evidence:

- `PaperAccount.__init__` accepts `_clock` for deterministic NY-boundary testing.
- `today_str()` uses `ZoneInfo("America/New_York")`.
- `daily_trade_count()` compares `_daily_date` to `today_str()`.
- `_refresh_daily_count()` also uses `today_str()` before resetting/incrementing.

### 2. Restored `trades_today` is not reset during UTC/NY date mismatch windows

**Pass.** The previously risky window is around UTC midnight while New York is still on the prior calendar date. With `today_str()` now returning the NY date, a restored `_daily_date` such as `2026-06-09` remains equal to `today_str()` at `2026-06-10 01:00 UTC` / `2026-06-09 21:00 America/New_York`; `daily_trade_count()` therefore returns the restored count instead of zero.

Coverage added in `backend/tests/test_phase_2s_h2.py` specifically exercises the UTC/NY mismatch window and verifies the restored count remains intact.

### 3. `can_enter` respects restored NY daily trade count at max trades

**Pass.** `can_enter()` still calls `_refresh_daily_count()` before enforcing the max-daily-trades guard. Because `_refresh_daily_count()` now uses the NY date path, a restored NY `_daily_date` is not spuriously reset during UTC/NY mismatch windows. If the restored count is already equal to `max_trades`, `can_enter()` returns `False` with the max daily trades reason.

The H2 tests cover both the blocked-at-max case and the below-max case using injected NY-boundary clocks.

### 4. Skipped open-position rows, especially `position_id IS NULL`, are warned visibly

**Pass.** DB restore excludes open entry rows with `position_id IS NULL` and now counts them with a dedicated SQL diagnostic. When the count is non-zero, it appends a human-readable `restore_warnings` entry explaining that the rows were skipped because `position_id IS NULL` and cannot be reliably matched for restore. The DB fallback also surfaces prior-NY-day skipped rows and malformed reconstructed rows.

Evidence reviewed:

- Open restore query requires `position_id IS NOT NULL`.
- A separate `COUNT(*)` query counts same-NY-day open entries with `position_id IS NULL`.
- `restore_warnings` includes the `position_id IS NULL` diagnostic.
- `restore_session()` promotes DB warnings into both `restore_warnings` and the combined `warning` string.

### 5. Frontend dashboard no longer hardcodes `restart_persistent=false`

**Pass.** The footer no longer uses the old `String(s?.restart_persistent ?? false)` fallback. It now shows the dynamic `s.restart_persistent` value when status exists, and `unknown` only when the status object is unavailable.

### 6. Frontend dashboard no longer says state is not restored after container restart

**Pass.** The stale text path that said `Session not restored from persistence (fresh start or no snapshot available for today).` has been removed. The footer now renders neutral restore metadata fields (`restore_source`, restored counts, restored P&L, restored trade count) rather than hardcoding a negative restore message.

Searches for the stale phrases requested in the review focus did not find them in `frontend/dashboard/app/page.tsx`.

### 7. Dashboard/status expose restore metadata and warnings

**Pass.** Backend status includes `restart_persistent`, `restore_source`, restored closed/open counts, restored realized P&L, restored `trades_today`, `restore_warning`, and `restore_warnings`. The frontend `PaperStatus` interface declares the same restore fields and the footer renders the restore source, counts, P&L, trade count, warning, and warnings list.

### 8. Restart restore avoids duplicate trade rows

**Pass.** The restore path applies restored account state in memory and does not insert journal rows during restore. Redis persistence writes a JSON snapshot to Redis, not `paper_trades_journal`; DB fallback reads journal rows and populates `_account.trades` / `_account.positions`, but it does not write them back to the journal. Journal inserts still occur only from future tick `entries` and `exits`, not from restore application.

Also relevant: DB open-position restore excludes any `position_id` that already has an exit row, so already-closed positions are not restored as open positions.

### 9. Strategy/catalyst/no-catalyst logic was not changed

**Pass.** The latest patch did not modify strategy, catalyst, no-catalyst, scoring, momentum, or simulator decision logic files. The changed backend runtime files are limited to `paper/account.py` and `paper/session_restore.py`; tests also include AST checks that `session_restore.py` does not import scoring, momentum, catalyst, or no-catalyst modules.

### 10. Marketdata cache logic was not changed

**Pass.** The latest patch did not modify marketdata cache modules or simulator marketdata cache logic. The diff file list contains no data/marketdata cache files.

### 11. No broker/live trading/real orders/AI/LLM/Ollama were added

**Pass.** The runtime patch did not add broker/live-trading/real-order/AI/LLM/Ollama integrations. Existing simulator status remains explicit that the mode is research paper simulation with `live_trading_enabled: False` and `broker_connected: False`, and the restore/session tests assert no forbidden imports in the reviewed restore/account/simulator modules.

### 12. Phase 2S-H2 is safe and complete for fake-money monitoring

**Pass.** Based on the latest patch and regression coverage, Phase 2S-H2 is safe and complete for fake-money monitoring:

- NY-date daily trade counts are handled consistently in `PaperAccount`.
- Restored `trades_today` survives UTC/NY boundary windows.
- `can_enter()` respects the restored max-trades count.
- Skipped DB restore rows are visible via restore warnings.
- Dashboard restore metadata is dynamic instead of hardcoded stale text.
- Restore does not write duplicate journal rows.
- Strategy/marketdata/broker/live/AI surfaces are not changed.

## Validation

Test command:

```bash
pytest backend/tests/test_phase_2s_h2.py backend/tests/test_phase_2s_h1.py backend/tests/test_phase_2s.py
```

Result:

- `59 passed, 1 warning in 0.40s`
- Warning only: `StarletteDeprecationWarning` from `fastapi.testclient` / Starlette test client compatibility; not related to Phase 2S-H2 behavior.
