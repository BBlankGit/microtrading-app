# Codex Review: Phase 2G Journal Hardening

Review scope: latest Phase 2G commit only (`312f5fe Harden Phase 2 journal readiness and performance attribution`).

## Executive conclusion

Phase 2G is a journal/persistence hardening change. I found no added broker integration, live trading, real orders, AI integration, or real-money execution. Strategy gating, scoring, position sizing, take-profit/stop-loss/max-hold logic appear unchanged; the strategy-facing changes are limited to passing the existing entry score into the paper position/trade models so closed journal rows can preserve attribution.

The persistence changes are broadly safe and non-destructive. Exit rows now carry `catalyst_type` and `total_score`, performance reporting can group closed-trade P&L by those fields, the new indexes are idempotent, startup/readiness retry is non-fatal, retry cooldown is present, retention status is read-only, and monitoring/dashboard warnings are non-fatal.

Patch required before market hours: **No functional patch appears required before market hours.** However, there is one **test blocker**: `pytest -q tests/test_phase2g.py` currently fails in the default local environment because `test_persist_attempts_reinit_when_disabled` expects a retry even when `DATABASE_URL` is not configured, while production code intentionally guards retry attempts behind `settings.DATABASE_URL`. This should be fixed before relying on the Phase 2G test suite as green.

## Critical issues

1. **Phase 2G test suite is not green in the default environment.**
   - Command run from `backend/`: `pytest -q tests/test_phase2g.py`.
   - Result: 28 passed, 1 failed, 1 warning.
   - Failure: `test_persist_attempts_reinit_when_disabled` expected `reinit_called["n"] == 1`, but the implementation only calls `try_reinit()` when `settings.DATABASE_URL` is truthy. With no local `DATABASE_URL`, no retry is attempted and the assertion fails.
   - Impact: This is a **test reliability blocker**, not evidence of unsafe live trading behavior. The implementation behavior is consistent with avoiding pointless reconnect attempts when there is no configured database URL.

## Non-blocking issues

1. **`last_retry_at` is exposed as a monotonic clock value.**
   - The value is useful for internal cooldown calculations, but less useful to dashboard/API consumers than an ISO timestamp or derived `seconds_until_next_retry` value.
   - This is non-blocking because it does not affect safety, persistence, or retry behavior.

2. **Performance attribution is not retroactive for old exit rows.**
   - Existing historical `exit` rows that were written before Phase 2G will still have null `catalyst_type`/`total_score` and therefore aggregate as `unknown`/`no_score`.
   - This is expected and non-blocking, but it should be understood when interpreting historical reports after deploy.

3. **`pnl_by_symbol` remains empty.**
   - Phase 2G focuses on catalyst type and score bucket attribution, which is implemented. The response still includes `pnl_by_symbol: []`, but symbol attribution was not part of this review scope.

4. **Monitoring high-candidate warning is not directly tested.**
   - The implementation catches DB/count errors and keeps warnings non-fatal, but the new high-row-count warning path is not covered by the Phase 2G tests.

## Safety assessment: broker/live trading/AI/real-money execution

Status: **Pass.**

Evidence reviewed:

- The changed journal and monitoring modules continue to declare read-only/research-only/no-live-trading behavior.
- The changed simulator module still advertises no broker, no live trading, no real orders, and no real-money execution.
- A targeted forbidden-token scan of the Phase 2G changed files found only safety disclaimers and test strings for terms such as `alpaca`, `execute_order`, `place_order`, `openai`, `anthropic`, and `langchain`; no new execution integration was found.
- The simulator status still reports `broker_connected: False`.

Conclusion: **No broker, live trading, real order, AI, or real-money execution path was added.**

## Strategy logic assessment

Status: **Pass.**

The Phase 2G simulator changes do not alter entry eligibility, hard rejection gates, score threshold logic, sizing, max-position checks, or exit triggers. They only:

- Include the original entry catalyst/score in exit result dictionaries.
- Pass the already-computed `scoring["total_score"]` into `PaperAccount.enter_position()`.

The existing hard gates remain the same: tradability, spread, positive change, minimum volume ratio, catalyst presence, and generic-news-only rejection. Exit logic remains take-profit, stop-loss, and max-hold based.

Conclusion: **Strategy behavior is unchanged; attribution metadata is now carried alongside existing decisions.**

## Exit journal attribution assessment

Status: **Pass for new rows.**

Phase 2G adds `entry_score` to both `Position` and `ClosedTrade`, stores it at entry, preserves it at exit, emits it in simulator exit dictionaries as `total_score`, and writes both `catalyst_type` and `total_score` into `paper_trades_journal` exit rows.

Conclusion: **New exit journal rows now preserve catalyst and score attribution.** Existing pre-Phase-2G exit rows remain unattributed unless backfilled.

## Performance reporting assessment

Status: **Pass for requested catalyst/score attribution.**

The `/api/journal/performance` query now selects `pnl`, `catalyst_type`, and `total_score` from closed exit rows and aggregates:

- `pnl_by_catalyst_type`, grouped by `catalyst_type` with nulls reported as `unknown`.
- `pnl_by_score_bucket`, grouped into `80+`, `70-79`, `50-69`, `<50`, and `no_score`.

Conclusion: **Performance reporting can now attribute closed-trade P&L by catalyst type and score bucket.** This depends on Phase 2G-or-newer exit rows having attribution columns populated.

## Persistence assessment

Status: **Pass, with tests caveat.**

### Idempotent indexes

The new candidate/trade indexes are all added with `CREATE INDEX IF NOT EXISTS`, including:

- `idx_paper_candidates_created_at`
- `idx_paper_candidates_symbol_created_at`
- `idx_paper_candidates_tick_created_at`
- `idx_paper_candidates_rejection_reason`
- `idx_paper_trades_event_created_at`
- `idx_paper_trades_event_symbol_created_at`

Conclusion: **Journal indexes were added idempotently.**

### Startup/readiness retry

`try_reinit()` calls `_db.init_tables()` inside a non-raising wrapper, sets `_journal_enabled = True` on success, logs failures, and returns `False` on exceptions. `persist_tick_result()` and `/api/journal/status` can attempt lazy reinitialization when the journal is disabled and `DATABASE_URL` exists.

Conclusion: **DB startup/readiness retry is safe and non-fatal.**

### Retry cooldown

`try_reinit()` stores `_last_retry_at` and returns early when the elapsed monotonic time is below `settings.JOURNAL_RETRY_SECONDS`.

Conclusion: **The cooldown prevents excessive DB reconnect/table-init attempts.**

### Retention config/status

`JOURNAL_RETENTION_DAYS` is configuration only. `/api/journal/status` and `/api/journal/retention/status` report retention configuration and row counts/date ranges, and both report `auto_cleanup_enabled: False`. There is no delete/truncate/drop cleanup path in Phase 2G.

Conclusion: **Retention status is safe, read-only, and non-destructive.**

## Monitoring assessment

Status: **Pass.**

Phase 2G adds useful, non-fatal warnings for:

- Last journal write failure.
- High candidate row count while auto-cleanup is disabled.

The candidate count probe is wrapped in `try/except` and does not fail the monitoring endpoint if the count query fails. Dashboard additions show last write status, retention policy, and an informational note when no closed trades exist yet.

Conclusion: **Monitoring/dashboard warnings are useful and non-fatal.**

## Test coverage assessment

Status: **Partial pass; one failing test.**

Coverage added in `backend/tests/test_phase2g.py` includes:

- No broker/AI import token checks for new persistence files.
- New index-name and `IF NOT EXISTS` checks.
- Config checks for `JOURNAL_RETRY_SECONDS` and `JOURNAL_RETENTION_DAYS`.
- Model/account propagation of `entry_score`.
- Persistence of exit attribution fields into exit insert arguments.
- Retry success, cooldown, and exception safety.
- Journal status and retention status fields.
- Monitoring warning for failed journal writes.
- `last_retry_at` status exposure.

Gaps:

- The Phase 2G test file currently fails in the default environment because `DATABASE_URL` is unset but one test expects `persist_tick_result()` to attempt retry anyway.
- There is no direct test for `/api/journal/performance` grouping P&L by catalyst type and score bucket.
- There is no direct test for the high-candidate-count monitoring warning.
- Retention status tests cover disabled/null responses and field presence, but not populated DB row counts/date ranges.

Conclusion: **Tests cover much of the hardening behavior, but coverage is incomplete and the Phase 2G test file must be fixed or run with an explicit DB URL expectation before it can be considered green.**

## Market-hours patch decision

Patch required before market hours: **No production-safety patch required.**

Rationale:

- No live-trading or broker execution was introduced.
- Strategy logic is unchanged.
- Persistence retry is non-fatal and throttled.
- Retention is read-only/non-destructive.
- Monitoring warnings are non-fatal.
- The only critical issue found is a failing test expectation in the default environment, not a live-trading or destructive-persistence risk.

Recommended pre-market follow-up: fix the failing test by either setting a temporary non-empty `DATABASE_URL` in the test or changing the assertion to reflect the intended behavior that no retry is attempted when no database URL is configured. Add focused tests for performance attribution grouping and high-candidate monitoring warnings.
