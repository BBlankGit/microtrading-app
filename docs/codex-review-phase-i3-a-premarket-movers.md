# Codex Review — Phase I3-A PRE Market Movers Read-Only Tab

**Repository:** `BBlankGit/microtrading-app`  
**Review date:** 2026-06-10  
**Reviewed branch/HEAD:** `work` at `5862322` (`Merge pull request #58 from BBlankGit/codex/review-phase-i2-h1-reddit-resilience-patch`)  
**Scope requested:** latest Phase I3-A patch only; do not change code.

## Verdict

**Blocking / not accepted for Phase I3-A as reviewed.**

I could not find an implemented Phase I3-A PRE Market Movers patch in the checked-out repository state. The current intelligence API only exposes the Phase I2 Reddit endpoints, and the dashboard still renders the PRE/POST intelligence tab as a generic “Coming soon” placeholder rather than a PRE Market Movers read-only view.

This is safe in the narrow sense that no new trading, broker, AI/LLM, hardcoded-key, full-universe, or direct Polygon risk was introduced by Phase I3-A in this checkout; however, Phase I3-A itself is **not functionally present**, so it is not ready to accept as a completed fake-money monitoring feature.

## Evidence reviewed

- `backend/api/intelligence.py`
  - Router prefix is `/api/intelligence`.
  - Only `GET /reddit` and admin-protected `POST /reddit/refresh` are defined.
  - No `GET /premarket` route exists in the current file.
- `frontend/dashboard/app/page.tsx`
  - Intelligence tab list contains `reddit`, `prepost`, `earnings`, `insiders`, `news`, `heatmap`, and `llm`.
  - `prepost` renders `<ComingSoon name="PRE/POST Gap Scanner" />`.
  - Frontend polling fetches only `/api/intelligence/reddit` for the intelligence section.
- `backend/main.py`
  - The intelligence router is included, but startup comments and behavior are still Phase I2 Reddit-only.
- Repository search
  - No route or frontend call for `/api/intelligence/premarket` was found.
  - No PRE Market Movers model/type/table/ranking code was found in the current checked-out source.

## Checklist findings

| # | Review focus | Finding |
|---|---|---|
| 1 | Whether `GET /api/intelligence/premarket` exists and returns a safe structured response. | **Fail / not implemented.** `backend/api/intelligence.py` currently defines only `/reddit` and `/reddit/refresh`; there is no `/premarket` route to validate. |
| 2 | Whether the PRE Market Movers tab is read-only and clearly marked as not integrated into trading decisions. | **Fail / not implemented.** The broader intelligence section has a read-only disclaimer, but the PRE tab is still a `ComingSoon` placeholder, not a PRE Market Movers tab. |
| 3 | Whether top movers are ranked correctly by premarket gap percent. | **Not verifiable / not implemented.** No premarket mover list or gap-percent sort exists in the reviewed source. |
| 4 | Whether invalid/missing price and previous-close data are excluded safely. | **Not verifiable / not implemented.** No Phase I3-A filtering logic exists to review. |
| 5 | Whether the implementation avoids scanning the full 5,000+ universe. | **Safe by absence, but not functionally satisfied.** No Phase I3-A scanner exists, so no new full-universe scan was added; however, no bounded PRE movers implementation exists either. |
| 6 | Whether any direct Polygon calls were added; if yes, whether they are limited/cache-backed/timeout-protected. | **No new Phase I3-A direct Polygon calls found.** Existing Polygon usage remains in pre-existing market data, readiness, and paper-discovery code. |
| 7 | Whether the endpoint uses existing microtrading universe/cache/collector data where possible. | **Fail / not implemented.** No endpoint exists, so there is no reuse of the existing universe/cache/collector architecture for PRE movers. |
| 8 | Whether POST/after-hours is not implemented as a separate priority tab. | **Pass with caveat.** No separate after-hours priority tab was added. The existing placeholder label remains `PRE/POST`, which is not a Phase I3-A PRE Market Movers implementation. |
| 9 | Whether no V6 hardcoded keys/auth/test endpoints were copied. | **Pass.** No new hardcoded V6 keys/auth/test endpoints related to Phase I3-A were found in the current source. The V6 material remains documentation-only in `docs/intelligence/v6-intelligence-audit-2026-06-10.md`. |
| 10 | Whether trading/scoring/entry/exit/catalyst/no-catalyst logic was not changed. | **Pass for this review state.** No Phase I3-A code changes were present in those areas. Existing backend tests covering paper, scoring, catalysts, exits, and safety passed. |
| 11 | Whether marketdata collector architecture was not changed in a risky way. | **Pass for this review state.** No Phase I3-A marketdata collector changes were found. Existing collector-related tests passed. |
| 12 | Whether no broker/live trading/real orders/AI/LLM/Ollama were added. | **Pass.** No Phase I3-A broker, live trading, real-order, AI, LLM, or Ollama implementation was found. |
| 13 | Whether frontend build and backend tests pass. | **Pass.** `cd backend && pytest` passed with 952 passed, 2 skipped, 1 warning. `cd frontend/dashboard && npm run build` passed; npm emitted a non-fatal unknown `http-proxy` env-config warning. |
| 14 | Whether Phase I3-A is safe for fake-money monitoring. | **Not accepted as completed.** It appears safe by absence of risky changes, but it is not usable as a PRE Market Movers monitoring feature because the API endpoint and tab are missing. |

## Specific blocking issues

### 1. Missing `GET /api/intelligence/premarket`

Phase I3-A requires a safe structured response for PRE Market Movers. The current API router only contains Reddit endpoints:

- `GET /api/intelligence/reddit`
- `POST /api/intelligence/reddit/refresh` with admin-token protection

There is no `GET /api/intelligence/premarket`, no premarket response schema, and no safe empty/error fallback to inspect.

### 2. PRE Market Movers UI is not implemented

The dashboard intelligence tabs still include the older `🌗 PRE/POST` tab. Selecting it renders the generic `ComingSoon` component with the name `PRE/POST Gap Scanner`. There is no PRE Market Movers table, no ranking display, no gap-percent column, and no explicit PRE-tab-level note that these movers are excluded from trading decisions beyond the broader intelligence disclaimer.

### 3. Ranking and invalid-data filtering cannot be validated

Because no premarket mover computation exists, the review cannot validate:

- descending rank by premarket gap percent,
- exclusion of missing/invalid premarket price,
- exclusion of missing/zero/invalid previous close,
- finite numeric gap handling,
- stable capped response size,
- cache age/source/error metadata.

### 4. Data-source architecture cannot be validated

The requested design preference is to use existing microtrading universe/cache/collector data where possible and avoid scanning the full 5,000+ universe. Since the endpoint is absent, there is no implementation to validate for bounded symbol selection, cache reuse, collector reuse, or timeout behavior.

## Safety assessment

The reviewed checkout does not introduce new unsafe behavior for fake-money monitoring:

- No live trading or broker functionality was added.
- No real order placement was added.
- No AI/LLM/Ollama path was added.
- No V6 hardcoded secrets or V6 test endpoints were copied into runnable code.
- No risky marketdata collector architecture change was found.
- Existing backend and frontend checks pass.

However, the feature is not complete. A future Phase I3-A implementation should be re-reviewed once it adds the `/api/intelligence/premarket` endpoint and a true PRE Market Movers tab.

## Recommended acceptance criteria for the next Phase I3-A patch

Before acceptance, the next patch should demonstrate all of the following:

1. `GET /api/intelligence/premarket` returns a structured response such as:
   - `ok`, `source`, `fetched_at`, `age_seconds`, `ttl_seconds`, `result_count`, `results`, `errors`/`warnings`.
2. Results are explicitly read-only and not consumed by scoring, entry, exit, catalyst, or no-catalyst code.
3. Results are ranked by premarket gap percent in descending order, with deterministic tie handling.
4. Rows with missing, non-positive, or non-finite premarket price / previous close are excluded.
5. The implementation uses a bounded symbol set and avoids scanning the full 5,000+ universe.
6. Any direct Polygon calls are limited, cache-backed, timeout-protected, and use existing `data.polygon_client` helpers rather than raw URLs.
7. Existing marketdata cache/collector/universe data is reused where practical.
8. The UI tab is PRE-specific, not a separate after-hours priority tab.
9. Tests cover route shape, sorting, invalid-data filtering, bounded universe behavior, no trading integration, and safety invariants.

## Commands run

```bash
git status --short
git log --oneline -5
git fetch --all --prune
git log --oneline --decorate --all -30
rg -n "premarket|PRE Market|pre-market|after-hours|after hours|Market Movers|movers" .
rg -n "INTEL_TABS|fetchReddit|RedditSnapshot|function IntelligenceSection|ComingSoon|PRE/POST|/api/intelligence" frontend/dashboard/app/page.tsx backend/main.py backend/api/*.py
rg -n "api/intelligence/premarket|premarket|PRE Market|Pre Market|after-hours|after hours|POST|polygon|Polygon|ollama|openai|broker|order" backend frontend/dashboard/app -g '!backend/tests/**'
cd backend && pytest
cd frontend/dashboard && npm run build
```

## Test results

- `cd backend && pytest` — **passed**: 952 passed, 2 skipped, 1 warning.
- `cd frontend/dashboard && npm run build` — **passed**: production build completed successfully. npm emitted a non-fatal warning: `Unknown env config "http-proxy"`.
