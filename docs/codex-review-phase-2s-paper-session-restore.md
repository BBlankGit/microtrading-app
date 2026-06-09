# Codex Review — Phase 2S Persistent Daily Paper Session Restore

Scope reviewed: latest Phase 2S patch only (`c590d72 Restore daily paper session state after restart`). This review does not modify application code.

## Executive verdict

Phase 2S is a meaningful step toward restart persistence for the **fake-money paper simulator**: startup now calls a restore hook after journal initialization, Redis snapshots are preferred when their `daily_baseline_date` matches the current New York trading date, the DB fallback reconstructs same-day closed trades and same-day open entries, restored trades feed account realized P&L, and the backend status payload exposes restore metadata.

However, I would not call the patch fully complete for the stated Phase 2S goals yet. The main blockers are:

1. **`trades_today` can be lost immediately after restore during the UTC/New York date offset window**, because restored daily count is keyed to a New York date while `PaperAccount.daily_trade_count()` and `can_enter()` still use UTC dates.
2. **DB fallback silently drops open positions that were opened on a prior New York trading day or before `position_id` existed**, with no operator-facing warning that such positions were deferred/excluded.
3. **The Next.js dashboard UI still hardcodes `restart_persistent: false` and the old “state is not restored” Redis wording**, so the user-facing dashboard does not expose the new restore source/counts/warnings even though backend status does.

Given those issues, Phase 2S is **mostly safe for fake-money monitoring** because it still has no broker/live-order path, but it can overstate restart persistence and can permit extra same-day entries in a specific NY/UTC boundary window.

## Detailed review against requested focus areas

### 1. Whether daily closed trades survive backend restart

**Mostly pass, with caveats.**

* Redis restore accepts `paper:state` only when the snapshot `daily_baseline_date` equals the current New York date, then applies the snapshot's `trades` list into `_account.trades` through `ClosedTrade(**t)`. `backend/paper/session_restore.py:22-36`, `backend/paper/simulator.py:964-981`
* DB fallback queries `paper_trades_journal` exit rows whose `closed_at` date in `America/New_York` matches the restore day, then rebuilds `ClosedTrade` objects from those rows. `backend/paper/session_restore.py:58-69`, `backend/paper/session_restore.py:88-119`
* The journal now persists `position_id`, `shares`, and `cost_basis` on exit rows, which gives DB fallback enough data to calculate proceeds and preserve P&L fields for closed trades going forward. `backend/paper/journal.py:230-254`

Caveat: DB fallback cannot recover the original entry timestamp for exit rows because the exit insert does not persist `opened_at`, so restored closed trades have blank `entry_time` and `hold_minutes=0.0` unless an exit row happens to contain `opened_at`. That does not break daily realized P&L, but it is an analytics fidelity gap. `backend/paper/session_restore.py:91-118`, `backend/paper/journal.py:234-250`

### 2. Whether daily realized P&L and `trades_today` are reconstructed from persistent storage

**P&L: pass. `trades_today`: partial fail at NY/UTC boundary.**

* Redis metadata computes restored realized P&L from the snapshot `trades` list and reads `daily_trade_count` into `trades_today`. `backend/paper/session_restore.py:176-187`
* DB fallback computes restored realized P&L from rebuilt `ClosedTrade` objects and sets `trades_today` from `daily_trade_count`. `backend/paper/session_restore.py:196-206`
* DB fallback computes `daily_trade_count` as `len(closed_rows) + len(open_rows)`, which corresponds to same-day entries that are now closed plus same-day entries that remain open. `backend/paper/session_restore.py:147-152`
* Restore applies the DB/Redis daily count into `_account._daily_trade_count`. `backend/paper/simulator.py:975-989`

The problem is that `_daily_date` is set to the New York date on DB restore, and Redis snapshots also carry the New York baseline date, but `PaperAccount.daily_trade_count()` and `_refresh_daily_count()` compare `_daily_date` to a UTC date string. Between midnight and approximately 04:00/05:00 UTC, the New York date is still the prior calendar day while UTC is already the next day, so `daily_trade_count()` returns `0`, and the next `can_enter()` call resets `_daily_trade_count` to `0`. `backend/paper/simulator.py:988-990`, `backend/paper/account.py:36-57`

Impact: after a restart during the NY evening / UTC next-day window, the simulator can under-report `trades_today` and allow additional entries beyond the same New York trading-day limit.

### 3. Whether daily loss guard uses restored P&L

**Pass for restored same-day state.**

* Redis restore applies `cash`, positions, closed trades, `daily_baseline_date`, `daily_start_equity`, and `last_prices`. `backend/paper/simulator.py:964-981`
* DB fallback applies estimated `cash`, rebuilt closed trades, rebuilt positions, and a same-day baseline of `starting_cash`. `backend/paper/session_restore.py:143-152`, `backend/paper/simulator.py:983-993`
* The daily loss guard computes current equity from the restored account, subtracts `daily_start_equity`, and returns `daily_pnl`/trigger status from those values. `backend/paper/risk.py:40-58`

Caveat: DB fallback's `cash` is an estimate from starting cash + realized P&L - restored open cost basis, and Phase 2S correctly labels this with `restore_warning="cash_estimated_from_db"`. `backend/paper/session_restore.py:143-152`, `backend/paper/session_restore.py:196-206`

### 4. Whether New York trading-day boundary is handled correctly

**Partial fail.**

The restore selection itself uses New York dates:

* Redis snapshots are considered valid only when `daily_baseline_date` equals the simulator's `_ny_trading_date()`. `backend/paper/session_restore.py:22-36`, `backend/paper/simulator.py:36-43`
* DB fallback filters closed and open rows with `AT TIME ZONE 'America/New_York'`. `backend/paper/session_restore.py:58-86`
* The simulator rolls the daily loss baseline at New York date changes. `backend/paper/simulator.py:561-568`

But the daily trade counter still uses UTC in `PaperAccount.today_str()`, `daily_trade_count()`, and `_refresh_daily_count()`. `backend/paper/account.py:36-57`

This means the NY trading-day boundary is not consistently handled for restored `trades_today` / max-trades enforcement. The inconsistency is especially important because Phase 2S explicitly restores `_daily_date` from New York-date metadata. `backend/paper/simulator.py:975-990`

### 5. Whether dashboard/status expose restore metadata and warnings

**Backend status/API: pass. Frontend dashboard UI: fail.**

Backend:

* `get_status()` now includes `restore_source`, `restored_closed_trades_count`, `restored_open_positions_count`, `restored_daily_realized_pnl`, `restored_trades_today`, and `restore_warning`. `backend/paper/simulator.py:105-115`
* `/api/paper/status` returns `simulator.get_status()`, and `/api/paper/dashboard` embeds that same `status` object. `backend/api/paper.py:10-16`, `backend/api/paper.py:39-65`

Frontend dashboard:

* `PaperStatus` still only types `state_restored_from_snapshot` and `restart_persistent`; it does not type `restore_source`, restored counts/P&L, restored trades today, or `restore_warning`. `frontend/dashboard/app/page.tsx:18-31`
* The dashboard stat card still renders `Restart Persistent` as literal `false`, ignoring `s.restart_persistent`. `frontend/dashboard/app/page.tsx:2390-2394`
* The footer still renders `restart_persistent: false` and says simulator state is not restored after container restart. `frontend/dashboard/app/page.tsx:2542-2550`

If Phase 2S acceptance requires the user-facing dashboard to expose restore metadata and warnings, the frontend part is not done.

### 6. Whether restart avoids duplicate trade rows

**Pass for restart restore itself.**

Restore reads Redis/DB and applies in-memory account state; it does not reinsert restored closed trades or entries into `paper_trades_journal`. `backend/paper/session_restore.py:22-158`, `backend/paper/simulator.py:928-1008`

Future ticks only journal the new `result["entries"]` and `result["exits"]` emitted by that tick. Restored historical closed trades are not placed into the tick result, so a restart alone should not duplicate closed rows. `backend/paper/journal.py:208-254`, `backend/paper/simulator.py:883-891`

The Phase 2S patch also adds `position_id` to entry/exit records so DB fallback can match still-open entries against exits. `backend/paper/journal.py:211-227`, `backend/paper/journal.py:230-254`

### 7. Whether open positions are restored, or if deferred, clearly warned

**Partial fail.**

* Redis restore restores whatever positions are in the valid same-day Redis snapshot. `backend/paper/simulator.py:968-981`
* DB fallback restores open entries only when `position_id IS NOT NULL`, the entry `opened_at` date equals the current New York restore date, and no exit row exists with that `position_id`. `backend/paper/session_restore.py:71-86`
* The source comment explicitly says rows written before Phase 2S with `NULL position_id` are excluded from open-position restore. `backend/paper/session_restore.py:47-49`

The gap: excluded open positions are not surfaced as a warning. Pre-Phase-2S open positions (`position_id IS NULL`) are silently ignored, as are open positions from a prior New York date. The only DB warning is the generic `cash_estimated_from_db`, regardless of whether positions were skipped. `backend/paper/session_restore.py:196-206`

For safe monitoring, operators should see a warning such as `open_positions_skipped_missing_position_id` or `open_positions_prior_day_not_restored` when DB fallback cannot restore open risk.

### 8. Whether strategy logic / catalyst / no-catalyst logic was not changed

**Pass.**

The Phase 2S simulator diff leaves the entry gating structure intact and only adds `position_id` to emitted entry records for catalyst, no-catalyst momentum, and momentum paths. `backend/paper/simulator.py:720-730`, `backend/paper/simulator.py:738-793`, `backend/paper/simulator.py:804-855`

I did not see threshold/gate/score/catalyst/no-catalyst decision logic changed in the latest patch.

### 9. Whether marketdata cache logic was not changed

**Pass.**

The latest Phase 2S simulator diff does not alter the market-data cache/fallback block; it adds restore metadata, journal payload fields, and restore functions. The existing cache stats and source metadata remain as-is in `run_tick()`. `backend/paper/simulator.py:360-412`

### 10. Whether no broker/live trading/real orders/AI/LLM/Ollama were added

**Pass.**

The new restore module states that it is read-only from Redis/Postgres and explicitly no broker/no live trading/no real orders. `backend/paper/session_restore.py:1-5`

Backend status continues to report `mode="research_paper_simulation"`, `live_trading_enabled=False`, and `broker_connected=False`. `backend/paper/simulator.py:116-118`

I did not see any broker integration, live order path, AI/LLM/Ollama integration, or real-money execution added by this patch.

### 11. Whether Phase 2S is safe for fake-money monitoring

**Conditionally safe, but not complete.**

Phase 2S remains fake-money only and the restore path is read-only, so it is not a real-money safety risk. It is safe to continue monitoring with the understanding that:

* Daily loss guard can use restored daily P&L.
* Closed daily trades survive restart through Redis or DB fallback.
* Backend status exposes restore metadata.

But I would not treat the patch as operationally complete until the three blocking issues are fixed:

1. Make daily trade counting use the same New York trading date as restore/baseline logic.
2. Warn when DB fallback skips open positions it cannot safely restore.
3. Update the user-facing dashboard UI/footer to show actual restore metadata and remove the stale “not restored after restart” messaging.

## Recommended fixes before accepting Phase 2S

1. **Unify daily trade counting on New York date.** Replace `PaperAccount.today_str()`'s UTC date with the same New York date helper, or pass a date provider into `PaperAccount` so restore, status, and `can_enter()` all use the same day boundary.
2. **Add DB skip diagnostics.** During DB fallback, count open entry rows excluded because `position_id IS NULL` and entries that are still open but not from the current NY date, and expose those counts/warnings in `restore_warning` or a structured restore warnings list.
3. **Update frontend dashboard.** Add restore fields to `PaperStatus`, render `restore_source`, restored counts/P&L, `restored_trades_today`, and `restore_warning`, and replace hardcoded `restart_persistent: false` plus stale Redis copy with values from status.
4. **Add regression tests for the boundary cases.** Specifically test restore at a UTC date that differs from the New York trading date, DB fallback with skipped `NULL position_id` open rows, and frontend/API dashboard metadata expectations.

## Commands run

```bash
PYTHONPATH=backend pytest backend/tests/test_phase_2s.py -q
```

Result: `12 passed, 1 warning in 0.29s`.

```bash
git diff --check HEAD^..HEAD
```

Result: passed with no whitespace errors.
