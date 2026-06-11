# Codex Review — Phase I5-H1 News Search / Filters / Sort

Review target: latest patch on `work`, commit `ab4d262` (`Add news search and filters`).

Scope honored: review only. No application code changed.

## Verdict

**Overall: PASS for fake-money monitoring**, with one UI correctness issue to fix before considering the feature fully polished.

The I5-H1 patch moves `GET /api/intelligence/news` to a backend-backed, cache-first search/filter/sort endpoint. The backend implements exact case-insensitive ticker filtering, free-text search over the relevant news fields, sort choices, a larger default limit with a hard cap, offset pagination metadata, cache age/stale metadata, and an admin-protected manual refresh endpoint. The dashboard exposes clear controls and removes news from the global 30-second refresh loop.

**Main issue found:** the frontend still hard-caps rendered rows with `items.slice(0, 100)`, so selecting `Limit: 250` or `Limit: 500` can fetch and report more rows than the table actually displays.

## Review checklist

| # | Area | Result | Notes |
|---|---|---:|---|
| 1 | Backend-backed search, not visible-row filtering | PASS | The backend copies cached results, applies filters/sort, then paginates; the UI sends query params to `/api/intelligence/news`. |
| 2 | Exact case-insensitive ticker/symbol filter | PASS | `ticker`/`symbol` are normalized to uppercase and matched exactly against `symbol` or entries in `tickers`. |
| 3 | Free-text `q` across title/source/event type/ticker | PASS | `_haystack()` includes title, source, publisher, classified/event type, symbol, tickers, and related metadata. |
| 4 | Sorting for date, ticker, materiality, sentiment score | PASS | Sort keys cover `published_at`, `fetched_at`, `ticker`, `event_type`, `materiality_score`, and `sentiment_score`. |
| 5 | Default newest-first news sort | PASS | Backend defaults `sort_by=published_at`, `sort_dir=desc`; UI state defaults match. |
| 6 | Increased default limit and capped max | PASS | Backend default is `100` and FastAPI validation caps at `500`; UI offers 50/100/250/500. |
| 7 | Pagination/offset and counts | PASS backend / PARTIAL UI | Backend implements `offset`, `total_count`, `returned_count`, `limit`, and `offset`. UI exposes limit but not offset/page controls. |
| 8 | Cache-first GET without 30-second external pressure | PASS | GET performs one cold-start fetch only when cache is empty. Cached and stale reads do not auto-fetch from Polygon. |
| 9 | Manual refresh admin-protected | PASS | `POST /api/intelligence/news/refresh` depends on `require_admin_token`; UI requires token before invoking it. |
| 10 | Cache age/stale metadata visible | PASS | Response includes age/TTL/stale; UI renders cache time, age, TTL, and stale warning. |
| 11 | UI search/filter/sort/limit controls clear | PASS with issue | Controls are visible and labeled, but table rendering ignores limits above 100 due to `items.slice(0, 100)`. |
| 12 | Unavailable/empty data handled honestly | PASS | Backend returns empty-cache warnings; UI shows no-data/no-match states and backend warnings. |
| 13 | No trading/scoring/entry/exit behavior changed | PASS | Latest patch touches only the intelligence API display endpoint and dashboard UI. |
| 14 | No broker/live trading/real orders added | PASS | No broker/order integrations were added in the patch. |
| 15 | No OpenAI/Anthropic/Ollama/LLM calls added | PASS | No LLM imports or API calls were added; text states rule-based/no AI. |
| 16 | No new secrets or V6 hardcoded keys copied | PASS | No hardcoded keys/secrets observed in the latest diff. |
| 17 | Tests and frontend build pass | PASS | `pytest` and `npm run build` passed. |
| 18 | Safe for fake-money monitoring | PASS | The patch is read-only and cache-first; no live trading or order path was introduced. |

## Detailed findings

### Finding 1 — Frontend limit selector can overstate rows shown

**Severity:** Medium  
**Status:** Needs follow-up

The backend can return up to the selected limit, and the status row can report `returned_count` values above 100, but the table renders `items.slice(0, 100)`. This means `Limit: 250` or `Limit: 500` may display only the first 100 rows while claiming more were returned.

**Evidence:**

- UI exposes `Limit: 250` and `Limit: 500` options.
- Table rendering maps over `items.slice(0, 100)`.

**Recommendation:** Render `items.map(...)` because the backend already paginates/caps results, or slice by `data.limit` if a frontend guard is still desired.

### Finding 2 — Offset pagination exists on backend but has no UI controls

**Severity:** Low  
**Status:** Acceptable for I5-H1 if backend API support was the requirement; follow-up if user-facing pagination was intended.

The backend accepts `offset` and returns count metadata. The UI currently sends search/filter/sort/limit params but does not expose previous/next pagination or an offset control. This is not a backend blocker, but it means users cannot page beyond the first window from the dashboard.

**Recommendation:** Add simple Previous/Next controls using `offset`, disabled at bounds using `total_count`, in a future UI polish pass.

## Backend review notes

- News cache is module-level and protected by an `asyncio.Lock`, providing single-flight cold-start/manual refresh behavior.
- `GET /api/intelligence/news` only calls `_fetch_news_into_cache()` when `_news_cache is None`; a 30-second dashboard poll does not cause a 30-second Polygon fetch loop.
- Stale data is reported honestly with `stale` and `warning`; stale GETs continue serving cache rather than making external calls.
- Filters are applied before pagination, so search/filter/sort are backend-backed over the cached result set rather than applied to currently visible rows.
- Manual refresh is the only forced refresh path and is protected with `Depends(require_admin_token)`.

## Frontend review notes

- `NewsTab` owns its news fetch state and query params rather than relying on preloaded visible rows.
- The global dashboard 30-second refresh no longer fetches news; NewsTab polls only while mounted.
- The UI clearly exposes search, ticker, event type, sentiment, sort field, sort direction, limit, clear, and admin refresh controls.
- The UI displays fetched timestamp, cache age, TTL, returned/matched counts, cached symbol count, stale state, and warnings.
- The row render cap of 100 is the only notable UI correctness defect found in this patch.

## Safety assessment

I5-H1 remains safe for fake-money monitoring:

- It is a read-only intelligence/dashboard patch.
- It does not alter entry/exit logic, score thresholds, trading eligibility, broker integration, order placement, or live-trading controls.
- It does not add OpenAI, Anthropic, Ollama, or other LLM API calls.
- It does not add hardcoded keys or secrets.
- It reduces external news API pressure versus the previous global 30-second dashboard fetch behavior.

## Verification performed

- Reviewed latest commit diff: `git show --stat --patch --find-renames --find-copies --minimal --format=fuller HEAD -- backend/api/intelligence.py frontend/dashboard/app/page.tsx`
- Reviewed relevant backend implementation: `nl -ba backend/api/intelligence.py | sed -n '280,550p'`
- Reviewed relevant frontend implementation: `nl -ba frontend/dashboard/app/page.tsx | sed -n '3427,3715p'` and `nl -ba frontend/dashboard/app/page.tsx | sed -n '3748,3785p'`
- Searched the latest patch for safety-sensitive additions: `git diff HEAD^..HEAD -- backend/api/intelligence.py frontend/dashboard/app/page.tsx | rg -n "OpenAI|Anthropic|Ollama|LLM|anthropic|openai|ollama|broker|order|trade|score|entry|exit|secret|key|token|API_KEY|api_key|limit|offset|sort|collect_news_for_symbols|require_admin_token"`
- Ran backend tests: `pytest` from `backend/` — **1119 passed, 2 skipped, 2 warnings**.
- Ran frontend production build: `npm run build` from `frontend/dashboard/` — **passed**.
