# Codex Review — Phase I2 Intelligence Tabs and Reddit Ranking

**Reviewed patch:** `d820dc7 Add intelligence tabs and Reddit ranking` (latest Phase I2 patch only)  
**Scope constraint:** Review only; no code changes made.  
**Review date:** 2026-06-10

## Executive verdict

**Phase I2 is safe for fake-money monitoring with two low/medium operational caveats.** The patch adds a read-only intelligence panel and ApeWisdom-backed Reddit rankings without wiring the data into trading, scoring, entry/exit, catalyst, or order paths. No Polygon calls, broker/live-trading integrations, LLM/Ollama calls, or V6 hardcoded keys/auth/test endpoints were added in the reviewed diff.

The main caveats are:

1. **Cached-data visibility on upstream failure:** the backend preserves cached Reddit data on ApeWisdom failure, but the frontend error branch hides any cached rows whenever `ok` is false and `error` is populated.
2. **Cold-start/concurrent fetch throttling:** the backend has a 15-minute post-success rate guard, but there is no in-process fetch lock/coalescing, so concurrent cold-start requests could make duplicate ApeWisdom calls before the first successful fetch sets `_fetched_at`.

Neither caveat changes trading behavior or creates live-trading risk.

## Review matrix

| # | Focus area | Result | Notes |
|---|---|---|---|
| 1 | Reddit ranking uses ApeWisdom and requires no API key | **Pass** | The only Reddit ranking URL is ApeWisdom's public endpoint, and the module does not read a Reddit/ApeWisdom key. |
| 2 | Reddit data cached/rate-limited safely | **Pass with caveat** | In-memory and Redis cache are present with a 900-second TTL/rate guard. Caveat: no fetch coalescing/lock for concurrent cold-start requests. |
| 3 | API failures do not crash backend/dashboard | **Pass with caveat** | Backend catches fetch and Redis errors. Frontend fetch catches network failures. Caveat: cached rows can be hidden in the frontend when an upstream error is returned with cached data. |
| 4 | Spike detection avoids false division errors | **Pass** | Division only occurs after `prev_m` is truthy and `> 0`; no divide-by-zero path observed. |
| 5 | `/api/intelligence/reddit` and refresh endpoint are safe | **Pass** | GET is read-only and returns cache/fetch result. Refresh is admin-token protected and still subject to rate guard. |
| 6 | Frontend Reddit tab is read-only and clearly marked | **Pass** | UI includes read-only/no-trading/no-broker/no-real-order disclaimers. Refresh only refreshes intelligence cache. |
| 7 | Placeholder tabs do not call external APIs yet | **Pass** | PRE/POST, Earnings, Insiders, News, Heatmap, and LLM Shadow render `ComingSoon`; no fetches are attached to those tabs. |
| 8 | No Polygon calls added | **Pass** | The Phase I2 diff adds no Polygon imports/calls; the new Reddit module imports only standard libs and `httpx`. |
| 9 | Trading/scoring/entry/exit/catalyst/no-catalyst logic unchanged | **Pass** | Reviewed diff touches only intelligence API/module/tests, FastAPI router registration/startup, and dashboard display code. |
| 10 | No broker/live trading/real orders/AI/LLM/Ollama added | **Pass** | No such imports/integrations were added; UI/backend disclaimers explicitly state none are present. |
| 11 | No V6 hardcoded keys/auth/test endpoints copied | **Pass** | No hardcoded external keys or V6-style auth/test endpoints observed in the Phase I2 diff. Refresh uses existing `require_admin_token`. |
| 12 | Safe for fake-money monitoring | **Pass** | Read-only intelligence-only feature; no trading-path mutation observed. |

## Detailed findings

### 1. ApeWisdom source and no API key requirement — Pass

The Reddit intelligence module defines a single upstream URL, `https://apewisdom.io/api/v1.0/filter/all-stocks/page/1`, and uses `httpx.AsyncClient(...).get(_APEWISDOM_URL)` without attaching credentials, API-key query params, or custom auth headers. The module docstring explicitly describes ApeWisdom as free and keyless.

Evidence:

- `backend/intelligence/reddit.py` defines `_APEWISDOM_URL`, timeout, TTL, and result cap constants.
- `fetch_and_refresh()` calls only `_APEWISDOM_URL` with no auth material.
- The API route docstrings identify ApeWisdom as the Reddit source.

### 2. Cache and rate limiting — Pass with caveat

The backend uses:

- in-memory `_current`, `_previous`, and `_fetched_at` state;
- Redis best-effort persistence under `intelligence:reddit:latest` and `intelligence:reddit:previous`;
- `_CACHE_TTL = 900` seconds;
- an early return from `fetch_and_refresh()` when the last successful fetch is younger than TTL;
- a background refresh loop that sleeps for `_CACHE_TTL` between attempts.

This is generally safe and avoids tight polling under normal operation.

**Caveat:** there is no explicit `asyncio.Lock` or in-flight request coalescing around `fetch_and_refresh()`. If multiple dashboard/backend requests hit a cold process before the first successful fetch updates `_fetched_at`, each request can independently call ApeWisdom. This is not a trading risk, but it is an upstream-rate/concurrency hardening gap.

### 3. Failure handling — Pass with caveat

Backend failure handling is defensive:

- Redis save/load helpers catch exceptions and return/log safely.
- ApeWisdom fetch errors are caught, `_fetch_error` is set, and `get_snapshot(error=...)` is returned instead of raising.
- The background loop wraps refresh attempts in `try/except`.
- The frontend `fetchReddit()` wrapper catches fetch failures and returns `null`.
- Manual refresh catches client-side exceptions and reports a message.

**Caveat:** if a previous snapshot exists and a later ApeWisdom fetch fails, the backend returns cached `results` with `error` populated and `ok: false`. The frontend currently returns the red error panel immediately when `!reddit.ok && reddit.error`, so it does not render cached rows even though the panel text says "Showing cached data if available." This is a UX/resilience issue, not a crash or trading-safety issue.

### 4. Spike detection — Pass

`_detect_spikes()` builds a previous-mentions map and only computes `round(curr_m / prev_m, 2)` inside this guard:

```python
if prev_m and prev_m > 0 and curr_m >= _SPIKE_RATIO * prev_m:
```

Therefore zero, missing, or falsy previous mentions do not divide. The included tests cover exact 3x, below-threshold, and no-previous-snapshot scenarios.

### 5. Endpoint safety — Pass

`GET /api/intelligence/reddit`:

- reads current snapshot first;
- fetches only on cold empty cache with no current error;
- returns snapshot JSON;
- does not accept order/trading parameters.

`POST /api/intelligence/reddit/refresh`:

- is protected by `Depends(require_admin_token)`;
- invokes the same rate-guarded refresh path;
- returns a compact status payload rather than exposing extra control actions.

No broker/order side effects were observed.

### 6. Frontend read-only marking — Pass

The dashboard marks the Intelligence panel as `read-only · no trading integration · Phase I2`. The intelligence component also displays: `Read-only intelligence layer · Not integrated into trading decisions · No broker · No live trading · No real orders`.

The Reddit tab exposes a cache refresh action, but that refresh only calls the intelligence refresh endpoint and does not place orders, change strategy, alter scoring, or trigger trading paths.

### 7. Placeholder tabs — Pass

The added tabs are:

- Reddit
- PRE/POST
- Earnings
- Insiders
- News
- Heatmap
- LLM Shadow

Only Reddit renders a data table and refresh action. The remaining tabs render `ComingSoon`, which contains static placeholder text and no `fetch()` or external API call wiring.

### 8. No Polygon calls — Pass

The Phase I2 diff contains no added Polygon import or call. Existing Polygon files remain outside this patch's functional changes. The new Reddit module imports `asyncio`, `json`, `logging`, `time`, `typing.Any`, and `httpx` only.

### 9. Trading/scoring/entry/exit/catalyst/no-catalyst unchanged — Pass

The reviewed patch touches only:

- `backend/api/intelligence.py`
- `backend/intelligence/__init__.py`
- `backend/intelligence/reddit.py`
- `backend/main.py`
- `backend/tests/test_phase_i2.py`
- `frontend/dashboard/app/page.tsx`

No strategy, scoring, entry, exit, catalyst, or no-catalyst implementation files were modified in the latest Phase I2 patch.

### 10. No broker/live/real orders/AI/LLM/Ollama — Pass

The reviewed diff does not add broker SDK imports, order submission paths, live-trading toggles, OpenAI/Anthropic/LangChain/Ollama imports, or LLM runtime calls. The LLM Shadow tab is a static placeholder only.

### 11. No V6 hardcoded keys/auth/test endpoints — Pass

No hardcoded external API keys were observed in the Phase I2 additions. The only auth-sensitive addition is the Reddit refresh button/endpoint, which uses the existing admin-token dependency rather than copying a new V6-style auth or test endpoint.

### 12. Fake-money monitoring safety — Pass

The feature is suitable for fake-money monitoring because it is read-only, cache-backed, failure-tolerant, and isolated from trading behavior. The implementation adds observability/intelligence display only and does not mutate trading state or execution settings.

## Tests/checks run

```text
pytest backend/tests/test_phase_i2.py
```

Result: **15 passed, 1 skipped, 1 warning**.

```text
npm run build
```

Result: **passed**. Next.js production build completed successfully. npm emitted an environment warning about unknown `http-proxy` config, but the build itself succeeded.

## Recommendation

Approve Phase I2 for fake-money monitoring. Consider follow-up hardening tasks (not required for safety approval):

1. Show cached Reddit rows in the frontend even when `error` is present, using an inline warning banner rather than returning early.
2. Add an in-process async lock or in-flight promise around cold-start refreshes to prevent duplicate ApeWisdom calls under concurrent requests.
