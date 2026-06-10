# Codex Review — Phase I2-H1 Reddit Intelligence Resilience

Review date: 2026-06-10  
Reviewed patch: `7bc90379d65d1adcc974c4a42c7ec652efbf5ea9` (`Harden Reddit intelligence cache resilience`)  
Scope: latest Phase I2-H1 patch only; no code changes made.

## Verdict

**PASS — Phase I2-H1 is safe for fake-money monitoring.**

The patch addresses the prior resilience concerns for Reddit intelligence:

- cached Reddit rows remain available when ApeWisdom refreshes fail;
- the frontend shows an inline cached-data warning instead of hiding the table;
- concurrent cold-start refreshes are coalesced with an `asyncio.Lock` and double-checked TTL guard;
- the 900-second ApeWisdom rate guard remains intact;
- failure with no cache returns a safe API response rather than crashing;
- no Polygon, broker/live-trading/order, AI/LLM/Ollama, V6 key/auth/test-endpoint, or trading decision logic changes were introduced by this patch.

## Findings

No blocking or non-blocking findings were identified.

## Scope Verification

The reviewed commit changed only:

- `backend/intelligence/reddit.py`
- `backend/tests/test_phase_i2.py`
- `frontend/dashboard/app/page.tsx`

No paper-trading engine, scoring, entry, exit, catalyst, no-catalyst, broker, live-order, Polygon client, or AI/LLM modules were modified by the Phase I2-H1 patch.

## Review Checklist

| # | Question | Result | Evidence |
|---|---|---|---|
| 1 | Cached Reddit rows remain visible when ApeWisdom refresh fails | PASS | `fetch_and_refresh()` catches ApeWisdom/httpx failures, preserves `_current`, sets `_fetch_error`, and returns `get_snapshot(error=...)`; `get_snapshot()` always includes `results: _current` and `result_count: len(_current)`. |
| 2 | Inline warning is shown instead of hiding cached data | PASS | The frontend full red error return is gated by `reddit.error && reddit.results.length === 0`; when `reddit.error && reddit.results.length > 0`, a yellow inline warning is rendered and the results table remains rendered. |
| 3 | Concurrent cold-start refreshes are coalesced | PASS | A module-level `_fetch_lock = asyncio.Lock()` wraps the slow refresh path, with a second TTL check inside the lock so waiters return the freshly cached snapshot instead of issuing duplicate upstream requests. |
| 4 | 900-second TTL/rate guard still works | PASS | `_CACHE_TTL` remains `900`; `fetch_and_refresh()` checks age before the lock and again inside the lock, returning the cached snapshot when age is below TTL. |
| 5 | API failure without cache remains safe | PASS | On failure with no `_current`, the API returns HTTP 200 with `ok: false`, empty results, and an `error` field; the frontend red panel is shown only for this empty-cache failure state. |
| 6 | No Polygon calls were added | PASS | The Phase I2-H1 implementation uses ApeWisdom via `httpx` only; patch touched no Polygon modules and the Reddit intelligence test suite includes AST guards against Polygon imports. |
| 7 | Trading/scoring/entry/exit/catalyst/no-catalyst logic was not changed | PASS | The patch did not touch paper-trading or strategy modules; changed files are limited to Reddit intelligence, its tests, and the dashboard Reddit UI. |
| 8 | No broker/live trading/real orders/AI/LLM/Ollama were added | PASS | The Reddit intelligence module remains read-only and the tests guard against broker/live/AI imports. The only frontend `llm` tab remains a planned read-only placeholder from existing intelligence tabs, not executable LLM integration. |
| 9 | No V6 hardcoded keys/auth/test endpoints were copied | PASS | No hardcoded credentials, copied V6 auth/test endpoints, or new credential paths were found in the patch. The existing Reddit refresh endpoint remains admin-token protected. |
| 10 | Safe for fake-money monitoring | PASS | The changes improve display and fetch resilience while remaining read-only and isolated from trading execution/decision code. |

## Test / Command Evidence

Executed from `/workspace/microtrading-app`:

```bash
pytest backend/tests/test_phase_i2.py
```

Result: `20 passed, 1 skipped, 1 warning in 0.38s`.

Additional review commands used:

```bash
git show --find-renames --find-copies --stat 7bc9037
git show --find-renames --find-copies --patch --unified=80 7bc9037 -- backend/intelligence/reddit.py backend/tests/test_phase_i2.py frontend/dashboard/app/page.tsx
git show --patch --unified=0 7bc9037 -- backend/intelligence/reddit.py backend/tests/test_phase_i2.py frontend/dashboard/app/page.tsx | rg -n "^diff|^@@|^\\+|^-|polygon|broker|alpaca|order|openai|anthropic|langchain|ollama|llm|AI|entry|exit|score|catalyst|V6|auth|key"
rg -n "@.*intelligence/reddit|intelligence/reddit|reddit/refresh|fetch_and_refresh|get_snapshot" backend -g '*.py'
rg -n "function RedditTab|ApeWisdom|reddit\\.error|reddit\\.results|Reddit" frontend/dashboard/app/page.tsx
```

## Notes

- The manual `/api/intelligence/reddit/refresh` path still honors the 900-second rate guard, consistent with the existing endpoint docstring.
- If ApeWisdom fails on a true cold start and there is no Redis/in-memory cache, the API remains safe but returns no rows until a later background/admin refresh succeeds. This is acceptable for Phase I2-H1 fake-money monitoring because it fails closed with a visible error and no trading integration.
