# Codex Review — Phase I3-A PRE Market Movers Read-Only Tab

Review date: 2026-06-10  
Reviewed patch: `812c321 Add premarket movers intelligence tab`  
Scope: latest Phase I3-A patch only (`backend/api/intelligence.py`, `backend/intelligence/premarket.py`, `backend/tests/test_phase_i3a.py`, `frontend/dashboard/app/page.tsx`).

## Executive verdict

Phase I3-A is broadly aligned with a read-only, fake-money monitoring feature: it adds `GET /api/intelligence/premarket`, a dashboard-only PRE Market Movers tab, Redis-cache-based data access, no direct Polygon calls, no broker/order integrations, and focused tests that pass.

However, I found two review concerns that should be addressed before treating the tab as a reliable premarket signal display:

1. **Stale-cache refresh gap:** the endpoint only refreshes on cold start (`fetched_at` missing), not when the in-memory snapshot is older than the session TTL. The `fetch_and_refresh()` function has TTL logic, but `GET /api/intelligence/premarket` does not invoke it after the first successful fetch.
2. **Previous-close validation gap:** `_compute_mover()` excludes missing `last_price` and missing `change_percent`, but it does not require valid `prev_close`. The response may include movers with `prev_close: null`, and malformed numeric values can fail the whole refresh instead of excluding only the bad symbol.

These issues do **not** appear to affect trading decisions because the feature is read-only and isolated from scoring/entry/exit logic, but they reduce data-quality confidence for the tab itself.

## Review matrix

| # | Check | Result | Notes |
|---|---|---|---|
| 1 | `GET /api/intelligence/premarket` exists and returns a safe structured response | **Pass with caveat** | Route exists and returns a stable shape with `ok`, `session`, `symbol_count`, `gainers`, `losers`, `error`, `fetched_at`, `age_seconds`, and `ttl_seconds`. Caveat: endpoint refreshes only on cold start, not TTL expiry. |
| 2 | PRE Market Movers tab is read-only and clearly marked as not integrated into trading decisions | **Pass** | Frontend only fetches via GET and displays read-only copy: `read-only · no trading integration`; no buttons/actions for trading were added. |
| 3 | Top movers are ranked correctly by premarket gap percent | **Pass with terminology caveat** | Movers are sorted by `abs(change_percent)` descending before splitting gainers/losers. For positive gainers and negative losers this yields largest absolute gaps first. Caveat: the field used is collector `change_percent`; the patch does not compute a separate explicit `premarket_gap_percent` from `last_price` and `prev_close`. |
| 4 | Invalid/missing price and previous-close data are excluded safely | **Partial / needs follow-up** | Missing `last_price` and missing `change_percent` are excluded. Missing `prev_close` is **not** excluded; it is returned as `null`. Invalid numeric types can raise during per-symbol computation and cause the refresh to fall into the global error path rather than skipping only that bad symbol. |
| 5 | Implementation avoids scanning the full 5,000+ universe | **Pass** | Uses `marketdata.cache.read_active_symbols()`, whose active list is produced by the marketdata collector. The collector universe is capped by existing settings (`MARKETDATA_MAX_SYMBOLS_PER_CYCLE`, currently 100), not the full universe. |
| 6 | Direct Polygon calls added; if yes, limited/cache-backed/timeout-protected | **Pass** | No direct Polygon calls were added in the Phase I3-A files. The premarket module reads Redis cache keys only. |
| 7 | Endpoint uses existing microtrading universe/cache/collector data where possible | **Pass** | Uses `read_active_symbols()` and `read_symbol()` from `marketdata.cache`, reading existing `market:symbols:active` and `market:snapshot:{symbol}` data. |
| 8 | POST/after-hours is not implemented as a separate priority tab | **Pass** | No POST premarket refresh endpoint was added. The UI has one PRE Market Movers tab; `afterhours` is only a session label in the same tab. |
| 9 | No V6 hardcoded keys/auth/test endpoints were copied | **Pass** | No hardcoded API keys, auth bypasses, or test endpoints are present in the Phase I3-A diff. |
| 10 | Trading/scoring/entry/exit/catalyst/no-catalyst logic was not changed | **Pass** | Changed files are limited to intelligence API/module/tests and dashboard display. No paper simulator, scoring, entry, exit, catalyst, or no-catalyst modules were changed. |
| 11 | Marketdata collector architecture was not changed in a risky way | **Pass** | No collector/source/config architecture files were changed by this patch. Existing cache readers are reused. |
| 12 | No broker/live trading/real orders/AI/LLM/Ollama were added | **Pass** | Patch contains read-only disclaimers and does not add broker/order/AI/LLM/Ollama code paths. |
| 13 | Frontend build and backend tests pass | **Pass** | `pytest tests/test_phase_i3a.py` passed: 12 passed, 1 warning. `npm run build` passed for the dashboard. |
| 14 | Phase I3-A is safe for fake-money monitoring | **Pass with follow-up recommended** | Safe in the sense that it does not drive trading decisions and does not add live-order paths. Follow-up recommended for stale-cache refresh and previous-close/invalid-data validation before relying on tab accuracy. |

## Detailed findings

### Finding 1 — Endpoint does not refresh on TTL expiry

Severity: **Medium**  
Area: backend endpoint freshness

`fetch_and_refresh()` has a TTL guard and can refresh stale snapshots, but `GET /api/intelligence/premarket` only calls it when `snap["fetched_at"]` is missing. After the first successful fetch, the endpoint can continue returning an expired in-memory snapshot indefinitely until another caller invokes `fetch_and_refresh()` or process state resets.

Recommended follow-up:

- Have the endpoint call `fetch_and_refresh()` when `fetched_at` is missing **or** when `age_seconds >= ttl_seconds` / TTL has expired.
- Add an endpoint test that seeds stale `_fetched_at` and verifies a refresh occurs.

### Finding 2 — Previous-close / invalid-number exclusion is incomplete

Severity: **Medium**  
Area: data quality and safe exclusion

`_compute_mover()` excludes symbols with missing `last_price` or missing `change_percent`, and filters sub-$3 symbols. It does not require valid `prev_close`, even though the review criterion asks for invalid/missing price and previous-close data to be excluded safely. It also compares `last_price < _MIN_PRICE` before coercion and then rounds/coerces later, so malformed numeric fields can raise and send the whole refresh into the global error handler.

Recommended follow-up:

- Parse `last_price`, `prev_close`, `change_percent`, and optionally `day_volume` inside a per-symbol try/except.
- Exclude symbols when `last_price`, `prev_close`, or `change_percent` is missing, non-numeric, non-finite, or when `prev_close <= 0`.
- Add tests for `prev_close is None`, `prev_close <= 0`, string/invalid numeric payloads, and one malformed symbol among otherwise valid symbols.

### Finding 3 — Ranking uses collector `change_percent`, not an explicit premarket gap field

Severity: **Low / clarification**  
Area: naming / semantics

The ranking implementation sorts by `abs(change_percent)` and displays `%` as the mover value. This is acceptable if the collector `change_percent` represents premarket gap from previous close for the snapshot source. The patch does not independently compute `premarket_gap_percent = (last_price - prev_close) / prev_close * 100`, so the endpoint is coupled to the collector's interpretation of `change_percent`.

Recommended follow-up:

- Either document that collector `change_percent` is the authoritative gap field, or compute a dedicated `gap_percent` from validated `last_price` and `prev_close` in this module.
- If a dedicated field is added later, rank by that field and expose it clearly in the API/UI.

## Evidence reviewed

- `backend/api/intelligence.py` adds `@router.get("/premarket")` and calls the premarket intelligence module.
- `backend/intelligence/premarket.py` reads `marketdata.cache.read_active_symbols` and `marketdata.cache.read_symbol`, computes movers, applies TTL state, and returns a structured snapshot.
- `frontend/dashboard/app/page.tsx` adds the PRE Market Movers tab, `fetchPremarket()`, display-only mover rows, and read-only/no-trading copy.
- `backend/tests/test_phase_i3a.py` covers session labels, TTL helper, mover filtering for missing price/change percent and sub-$3 prices, fetch sorting, TTL guard, error cache preservation, and endpoint smoke shape.
- Existing `backend/marketdata/cache.py` provides Redis cache readers for active symbols and per-symbol snapshots.
- Existing `backend/marketdata/universe_builder.py` caps the collector universe via `MARKETDATA_MAX_SYMBOLS_PER_CYCLE`.

## Commands run

```bash
git show --stat --oneline HEAD
git show --name-only --format='' HEAD
git diff --name-only HEAD^ HEAD
git diff --stat HEAD^ HEAD
rg -n "Premarket|premarket|PRE Market|Pre-market|Market Movers" frontend/dashboard/app/page.tsx backend/tests/test_phase_i3a.py backend/api/intelligence.py
rg -n "def read_active_symbols|async def read_active_symbols|market:snapshot|active_symbols|ACTIVE" backend/marketdata backend -g'*.py'
rg -n "polygon|POLYGON|OLLAMA|llm|broker|alpaca|order|score|catalyst|entry|exit" backend/api/intelligence.py backend/intelligence/premarket.py backend/tests/test_phase_i3a.py frontend/dashboard/app/page.tsx
pytest tests/test_phase_i3a.py
npm run build
```

## Test results

- `pytest tests/test_phase_i3a.py` from `backend/`: **passed** — 12 passed, 1 warning (`StarletteDeprecationWarning` from FastAPI/TestClient dependency stack).
- `npm run build` from `frontend/dashboard/`: **passed** — Next.js production build completed successfully. npm emitted a non-fatal warning: `Unknown env config "http-proxy"`.

## Final safety assessment

Phase I3-A is safe for fake-money monitoring from an execution-risk perspective because it is read-only, dashboard-scoped, cache-backed, and not connected to broker/live-order/scoring/entry/exit paths.

Data-quality follow-up is still recommended before the tab is treated as an accurate premarket mover source: refresh stale snapshots through the endpoint and harden per-symbol validation around previous close and malformed numeric payloads.
