# Codex Review — Phase 2G-H1 Test Reliability Patch

## Scope reviewed

Reviewed only the latest Phase 2G-H1 commit, `461da21 Fix Phase 2G journal retry test expectations`.

The patch changes only `backend/tests/test_phase2g.py`; no production modules were modified in this patch.

## Critical issues

None found.

The previously failing Phase 2G retry expectation was fixed correctly by replacing the environment-dependent test with two explicit tests that control `DATABASE_URL` directly:

- `test_persist_skips_reinit_when_no_database_url` sets `DATABASE_URL` to an empty string and verifies `persist_tick_result()` returns a skipped journal result without calling `try_reinit()`.
- `test_persist_attempts_reinit_when_database_url_configured` sets a non-empty dummy `DATABASE_URL` and verifies `try_reinit()` is attempted exactly once while still avoiding any real database connection by mocking the retry function.

This matches the production behavior in `persist_tick_result()`: when the journal is disabled, retry is gated behind `settings.DATABASE_URL`; if the URL is absent, no retry is attempted and the write is skipped as disabled.

## Test reliability assessment

Assessment: passing and materially more reliable.

The revised tests now make the two intended states explicit instead of depending on the developer or CI environment:

1. **No DB reinit retry when `DATABASE_URL` is missing**
   - Covered by the new empty-URL test.
   - The test patches `core.config.settings` to a fake settings object with `DATABASE_URL = ""`.
   - The test patches `paper.journal.try_reinit()` and asserts it is not called.

2. **DB reinit retry only when `DATABASE_URL` is configured**
   - Covered by the new configured-URL test.
   - The test patches `core.config.settings` to a fake settings object with a dummy PostgreSQL URL.
   - The test patches `paper.journal.try_reinit()` and asserts it is called exactly once.

3. **No accidental real DB dependency**
   - Both retry-path tests mock `try_reinit()`, so the configured-URL test does not require PostgreSQL and does not open a real database connection.

4. **Additional Phase 2G coverage**
   - The added performance attribution grouping test validates that rows with `catalyst_type` and `total_score` produce catalyst and score buckets rather than fallback `unknown` or `no_score` buckets.
   - The added monitoring test validates the high-candidate-count warning path using a fake in-memory pool.

`pytest -q` is green from the backend directory: 238 tests passed with one third-party Starlette/httpx deprecation warning.

## Safety assessment

Safe.

No production strategy logic changed in this patch. The latest commit modifies only the Phase 2G test file.

No broker integration, live trading path, real order placement, AI/LLM integration, or real-money execution was added by this patch. The repository's existing safety posture remains unchanged: the relevant production modules continue to describe and implement research-only, fake-money behavior, and the Phase 2G tests continue to include safety checks for broker/order/AI tokens in the persistence modules.

## Whether any patch is still required before market hours

No patch is required before market hours for the Phase 2G-H1 issue.

The failing Phase 2G test was corrected to reflect intended behavior, the retry tests are now environment-independent, no production logic was modified, no unsafe execution surface was introduced, and the full backend pytest suite is green.
