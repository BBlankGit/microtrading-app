# Codex Review — Phase 2S-H1 Paper Session Restore Reliability

Date reviewed: 2026-06-09

Scope: latest available checkout for `BBlankGit/microtrading-app`, focused on the Phase 2S paper-session-restore implementation and the requested Phase 2S-H1 reliability concerns. I did not modify application code.

## Verdict

**Not yet a clean Phase 2S-H1 pass.** The restore path is still fake-money-only and the core restored P&L/open-position mechanics are usable for monitoring, but two requested H1 reliability fixes are not present in the current checkout:

1. `PaperAccount` still uses a UTC calendar date for the daily trade counter, even though the rest of the restore/daily-loss baseline logic is New-York-date scoped.
2. The frontend dashboard still hardcodes `restart_persistent=false` in visible UI text and does not render the restore metadata/warnings already exposed by the backend status payload.

Because of those gaps, I would treat the current patch as **safe for fake-money monitoring with caution**, not as fully complete for Phase 2S-H1.

## Review Findings Against Requested Focus Areas

### 1. Daily trade count uses New York trading date consistently

**Finding: FAIL.** The current daily trade counter remains UTC-based.

Evidence:

- `backend/paper/account.py` imports `datetime`/`timezone` and `today_str()` returns `datetime.now(timezone.utc).strftime("%Y-%m-%d")`.
- `daily_trade_count()` compares `_daily_date` to that UTC `today_str()`.
- `_refresh_daily_count()` also rolls `_daily_trade_count` using that UTC `today_str()`.
- In contrast, `backend/paper/simulator.py` has `_ny_trading_date()` and uses it for restore and daily-loss baseline rollover.

Impact:

- Between 00:00 UTC and 00:00 America/New_York, the simulator can disagree with itself about “today”: restore/baseline logic is New York scoped, but `PaperAccount` trade count is UTC scoped.
- This directly affects max-daily-trades gating and dashboard `Trades Today` display.

### 2. Restored `trades_today` is not reset by UTC/NY date mismatch

**Finding: FAIL / still vulnerable.** DB restore sets `_account._daily_date = ny_today`, but `PaperAccount.daily_trade_count()` immediately compares that NY date to UTC `today_str()`. During UTC/NY mismatch windows, a restored non-zero `_daily_trade_count` can display as zero and `can_enter()` can reset it to zero.

Evidence:

- DB restore applies `_account._daily_trade_count` from DB data and sets `_account._daily_date = ny_today`.
- `daily_trade_count()` returns zero if `_daily_date != today_str()`, where `today_str()` is UTC.
- `can_enter()` calls `_refresh_daily_count()` before enforcing `max_trades`, and `_refresh_daily_count()` resets the count/date when UTC `today_str()` differs.

Impact:

- Restored `trades_today` can be silently discarded around the UTC/NY boundary.
- This can allow too many same-NY-session fake-money entries after a restart.

### 3. Daily loss guard still uses restored P&L

**Finding: PASS with caveat.** Restored realized trades and open positions feed account equity, and the guard reads `account.daily_start_equity` plus current account equity. Redis restore also restores `daily_start_equity`; DB fallback reconstructs `cash`, restored trades, and open positions.

Evidence:

- Redis restore rebuilds cash, starting cash, positions, trades, `_daily_trade_count`, `daily_baseline_date`, and `daily_start_equity`.
- DB restore rebuilds cash from `starting_cash + realized_pnl - open_cost_basis`, restores trades/positions, and sets `daily_start_equity` from DB data/default starting cash.
- `get_status()` computes `daily_loss_guard` through `_daily_loss_guard(_account, _last_prices)`.
- `risk.daily_loss_guard_triggered()` bases daily P&L on `current_equity - daily_start_equity`.

Caveat:

- DB fallback sets `daily_start_equity` to `starting_cash`, not a reconstructed intraday baseline. That preserves restored daily realized P&L for a same-day restarted paper session, but it is an estimate rather than a true persisted baseline if the baseline was changed by a prior NY-date rollover.

### 4. Skipped open-position rows are warned visibly

**Finding: PARTIAL / backend log only.** Malformed closed/open rows are logged with `logger.warning(...)`, and DB fallback sets a generic `restore_warning = "cash_estimated_from_db"`. However, rows excluded from open-position restore because `position_id IS NULL` are filtered in SQL before Python sees them, and there is no visible dashboard/status count or warning for those skipped legacy rows.

Evidence:

- DB open-position query explicitly requires `position_id IS NOT NULL`.
- The function comments say rows with `NULL position_id` are excluded from open-position restore.
- Malformed open rows are logged with `session_restore: skipping malformed open row`, but no skip count or row-level warning is returned in restore metadata.
- The only DB warning returned is `cash_estimated_from_db`.

Impact:

- Operators may not visibly know that some legacy open-position entry rows were skipped, unless they inspect backend logs and infer from counts.

### 5. Frontend dashboard no longer hardcodes `restart_persistent=false`

**Finding: FAIL.** The frontend still hardcodes restart persistence as false in two visible places.

Evidence:

- The status grid renders `<StatBox label="Restart Persistent" value="false" ... />`.
- The footer renders `restart_persistent: false`.
- The footer text still states that simulator state is not restored after container restart.

Impact:

- Backend status can correctly expose `restart_persistent: true`, but the dashboard will still tell the operator `false`.

### 6. Dashboard/status expose restore metadata and warnings

**Finding: backend PASS, frontend FAIL.**

Backend evidence:

- Simulator state contains `restore_source`, `restored_closed_trades_count`, `restored_open_positions_count`, `restored_daily_realized_pnl`, `restored_trades_today`, and `restore_warning`.
- `get_status()` returns those fields.
- `/api/paper/status` returns `simulator.get_status()` and `/api/paper/dashboard` embeds that status object.

Frontend evidence:

- The TypeScript `PaperStatus` interface only includes `state_restored_from_snapshot` and `restart_persistent`; it omits the other restore metadata fields.
- No frontend render references exist for `restore_source`, `restored_closed_trades_count`, `restored_open_positions_count`, `restored_daily_realized_pnl`, `restored_trades_today`, or `restore_warning`.

Impact:

- API consumers can see restore metadata, but dashboard users cannot.

### 7. Restart avoids duplicate trade rows

**Finding: MOSTLY PASS for restore itself, with DB uniqueness caveat.** Restore is read-only and applies restored state in memory. It does not write restored entries or exits back into `paper_trades_journal`, so restart restore itself should not duplicate journal rows.

Evidence:

- `paper.session_restore` reads Redis/DB only and returns reconstructed objects.
- `restore_paper_session()` applies restored cash/trades/positions to `_account` and metadata to `_state`; it does not call journal persistence.
- Open DB restore uses `position_id NOT IN (SELECT position_id FROM paper_trades_journal WHERE event = 'exit' AND position_id IS NOT NULL)` to avoid restoring already-exited positions.
- Journal writes entry/exit events only from tick results.

Caveat:

- The schema adds an index on `position_id`, but not a uniqueness constraint on `(position_id, event)`. That means database-level deduplication is not guaranteed if some future tick/retry path inserts the same event twice. I did not find the restore path itself causing duplicates.

### 8. Strategy/catalyst/no-catalyst logic was not changed

**Finding: PASS for direct module changes in the Phase 2S restore patch.** The Phase 2S implementation commit changed restore/journal/simulator/test files, not `paper/momentum.py`, `paper/no_catalyst_momentum.py`, `paper/scoring.py`, or catalyst collector code.

Caveat:

- The simulator file was changed for restore integration. The existing entry loop still calls the same deterministic scoring/evaluation functions; I did not find new AI/broker/order logic in that path.

### 9. Marketdata cache logic was not changed

**Finding: PASS for the Phase 2S restore patch.** The Phase 2S restore commit did not modify marketdata cache modules. Later repository history contains D4 marketdata-autostart changes, but those are outside the Phase 2S-H1 review scope and are not part of this restore reliability review.

### 10. No broker/live trading/real orders/AI/LLM/Ollama were added

**Finding: PASS.** The reviewed restore files remain documented as fake-money/research-only and static import scanning of `backend/paper/session_restore.py`, `backend/paper/simulator.py`, and `backend/paper/account.py` found no forbidden broker or AI imports among `alpaca`, `ibapi`, `interactive_brokers`, `td_ameritrade`, `openai`, `anthropic`, `langchain`, or `ollama`.

Evidence:

- `session_restore.py` docstring explicitly says no broker, no live trading, no real orders, no real-money execution, and read-only restore.
- `simulator.py` docstring explicitly says no broker, no live trading, no real orders, no real-money execution.
- `get_status()` returns `live_trading_enabled: False` and `broker_connected: False`.

### 11. Phase 2S-H1 is safe for fake-money monitoring

**Finding: SAFE WITH CAUTION, not fully complete.** I did not find real-money, broker, live-order, AI/LLM, or Ollama additions. Restore itself is non-fatal and read-only from Redis/Postgres. However, because the daily trade counter is still UTC-based and the frontend still misreports persistence/does not render restore metadata, I would not mark Phase 2S-H1 complete.

Recommended minimum follow-up before calling H1 done:

1. Make `PaperAccount.today_str()` use America/New_York trading date or inject the simulator’s NY date helper into the account layer.
2. Ensure restored Redis snapshots normalize `_daily_date` to the current NY trading date when `daily_baseline_date` is valid, or otherwise migrate/validate legacy UTC snapshots.
3. Add tests that simulate UTC/NY mismatch windows and assert restored `daily_trade_count` is preserved and max-daily-trades gating still blocks entries.
4. Add visible restore metadata to the dashboard and remove hardcoded `restart_persistent=false` text.
5. Return visible warning metadata/counts for skipped open-position rows, especially legacy rows with `NULL position_id`.
6. Consider a database uniqueness guard for journal events, such as a partial unique index on `(position_id, event)` where `position_id IS NOT NULL`, if duplicate event rows are a realistic retry risk.

## Checks Run

- `PYTHONPATH=backend pytest -q backend/tests/test_phase_2s.py` — passed: 12 tests, 1 warning.
- Static AST import scan on `backend/paper/session_restore.py`, `backend/paper/simulator.py`, and `backend/paper/account.py` for broker/AI/Ollama imports — passed: no forbidden imports found.
- `rg` review of restore metadata, daily-date fields, and frontend `restart_persistent` rendering — found the UTC/NY and frontend hardcoding issues described above.
