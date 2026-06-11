# Codex Review — Phase I6-H2 Finnhub Earnings + Insider Fetchers

Review date: 2026-06-11  
Reviewed patch: `44892ff` (`Wire Finnhub earnings and insider fetchers`)  
Scope: latest I6-H2 patch only.

## Verdict

**Conditionally approved for fake-money monitoring, with one non-blocking correctness issue to fix next.**

The I6-H2 patch wires real, read-only Finnhub fetchers for earnings and insider transactions without hardcoding or logging the Finnhub key, without using NEWSAPI, without adding broker/live-trading/real-order paths, and without adding OpenAI/Anthropic/Ollama/LLM calls. Backend tests and the frontend production build pass.

The main issue I found is that provider status switches to `rate_limited`/`error` when serving prior rows after a failed refresh, but the module resets the monotonic cache timer. The old `fetched_at` is retained, yet API `cache_age_seconds` becomes near zero and `stale` can report false. That makes stale-cache semantics less honest after an error/rate limit.

## Checks performed

- `git show --stat --oneline --decorate HEAD`
- `git show --name-only --format='' HEAD`
- `git diff HEAD^..HEAD -- backend/core/config.py backend/intelligence/earnings.py backend/intelligence/finnhub_client.py backend/intelligence/insiders.py backend/tests/test_phase_i6_h2.py backend/tests/test_phase_i6_h1.py`
- `git diff HEAD^..HEAD -- . | rg -n "NEWSAPI|NEWS_API|newsapi|sk-|FINNHUB_API_KEY\s*=\s*['\"][^'\"]+|openai|anthropic|ollama|langchain|place_order|submit_order|execute_order|send_order|create_order|broker"`
- `rg -n "earnings|insider|Earn Adj|Ins Adj|Intel Adj|earnings_score_adjustment|insider_score_adjustment|require_admin_token|refresh" backend/api backend/paper frontend/dashboard -g '!node_modules' -g '!dist' -g '!build'`
- `pytest -q` from `backend/`
- `npm run build` from `frontend/dashboard/`

## Finding

### Finding 1 — stale-cache metadata is misleading after rate limits/errors with prior rows

**Severity:** Medium  
**Area:** Provider status / stale cache honesty

When the earnings fetcher or insider fetcher receives a rate limit or error and an older cache already has rows, the code preserves the old rows and old `fetched_at`, sets `provider_status` to `rate_limited` or `error`, and updates the warning/errors. That behavior is good because the UI can keep showing the last usable feed.

However, both refresh paths also reset `_cache_time = time.monotonic()` before returning the preserved cache. The API computes `cache_age_seconds` and `stale` from that monotonic timer. Therefore a stale result set can appear fresh immediately after an error/rate-limit refresh, even though `fetched_at` still refers to the older successful fetch.

Recommended fix in a follow-up patch:

- do not reset `_cache_time` when preserving prior rows after an error/rate limit; or
- add explicit fields such as `last_attempted_at`, `last_successful_fetched_at`, and `serving_stale_cache: true`; and
- ensure `stale` stays true, or at least honestly communicates that rows are from the previous successful fetch.

This is not a fake-money safety blocker because `provider_status` and `warning` do reveal the failed/rate-limited attempt, and stale rows are read-only scoring inputs. It is still worth fixing because the review requirement explicitly asks for honest active/missing-key/error/rate-limit/stale-cache semantics.

## Scope review

Only the latest I6-H2 commit changed code under:

- `backend/core/config.py`
- `backend/intelligence/earnings.py`
- `backend/intelligence/finnhub_client.py`
- `backend/intelligence/insiders.py`
- `backend/tests/test_phase_i6_h1.py`
- `backend/tests/test_phase_i6_h2.py`

No frontend, simulator, scoring, exit, broker, order, or API endpoint source file changed in this I6-H2 patch.

## Requirement-by-requirement review

### 1. Finnhub key is read from env/config only and never hardcoded/logged

**Pass.** `FINNHUB_API_KEY` is added as an empty default setting, so the value comes from settings/environment rather than the repo. The Finnhub client reads `settings.FINNHUB_API_KEY`, rejects blank/placeholder values, injects the token into the request query parameters, and logs only sanitized request paths/status/type names rather than the token or response body.

I found no hardcoded Finnhub key in the latest patch. The I6-H2 tests also include a log-capture check that verifies a sentinel API key is not emitted on a request-error path.

### 2. NEWSAPI was not used in this phase

**Pass.** The I6-H2 diff does not add `NEWSAPI`, `NEWS_API`, `NewsAPI`, or `newsapi` references. The new fetchers call Finnhub endpoints only.

### 3. Earnings fetcher uses Finnhub correctly and normalizes results

**Pass.** The earnings fetcher calls Finnhub `/calendar/earnings` with `from`/`to` parameters covering today through the configured lookahead window. It expects `earningsCalendar`, filters rows to the capped tracked universe, and normalizes provider fields into the existing canonical schema: `ticker`, `report_date`, `report_time`, EPS/revenue estimate/actual fields, `confirmed`, `days_until`, `source`, and `fetched_at`.

The fetcher handles unexpected payloads, Finnhub errors, and 429 rate limits without raising to API callers.

### 4. Insider fetcher uses Finnhub correctly and normalizes Form 4 transaction codes

**Pass.** The insider fetcher calls Finnhub `/stock/insider-transactions` per capped symbol with `symbol`, `from`, and `to` parameters. It injects the queried symbol into returned rows when Finnhub omits it. It normalizes Form 4 transaction codes into conservative transaction types/labels:

- `P` → `open_market_purchase`, `bullish_buy`
- `M` → `option_exercise`, `informational_buy`
- `S` → `sale`, `sale`
- `A` / `F` / `G` → neutral compensation/gift labels
- `D` / `X` → sale-like disposition/exercise-and-sale labels
- unknown codes → `other`, `unknown`

The parser also handles Finnhub-style expanded strings such as `P-Purchase` by taking the first code letter.

### 5. GET endpoints remain cache-first and avoid repeated external calls on dashboard refresh

**Pass.** The existing GET endpoints remain cache-first: they call the module refresh function only on cold start when no snapshot exists, then read/filter/sort/paginate from the in-memory snapshot. Dashboard polling of these GET endpoints therefore does not force a Finnhub call on every refresh.

The module refresh functions also short-circuit on fresh cache unless `force=True` is passed.

### 6. POST refresh endpoints remain admin-protected

**Pass.** Existing `POST /api/intelligence/earnings/refresh` and `POST /api/intelligence/insiders/refresh` remain protected by `Depends(require_admin_token)`. I6-H2 did not change those endpoint definitions.

### 7. Symbol universe is capped and no 5,000-symbol polling loop was added

**Pass.** Both fetchers build a deduped universe from `DEFAULT_UNIVERSE` plus `PAPER_BASE_UNIVERSE`, then cap it using config:

- earnings default cap: `EARNINGS_MAX_SYMBOLS_PER_REFRESH = 100`
- insider default cap: `INSIDER_MAX_SYMBOLS_PER_REFRESH = 50`

The earnings fetcher makes one calendar-window request and filters it to the tracked symbols. The insider fetcher loops only over the capped tracked symbols, includes a configurable inter-symbol delay, and stops early on rate limit. I found no 5,000-symbol polling loop in the I6-H2 patch.

### 8. `provider_status` semantics are honest for active/missing key/error/rate-limit/stale cache

**Mostly pass, with the stale-cache finding above.**

Good behavior:

- `none` → `not_configured`
- configured but not wired → `configured_but_unwired`
- Finnhub without a usable key → `missing_api_key`
- successful Finnhub fetch → `active`
- 429 → `rate_limited`
- other fetch/payload failure → `error`

Gap: when old rows are served after `rate_limited` or `error`, the old `fetched_at` is retained but the cache timer is reset. API `cache_age_seconds`/`stale` can therefore imply freshness for stale rows.

### 9. Scoring integration remains transparent and deterministic

**Pass.** I6-H2 did not change `backend/paper/scoring.py` or `backend/paper/simulator.py`. The inherited I6 scoring path remains rule-based and transparent: candidate output includes base score, intelligence adjustment, final score, earnings adjustment/reason/block fields, and insider adjustment/reason/recent-buy metadata.

### 10. Earnings are risk/proximity penalties only and cannot create entries alone

**Pass.** I6-H2 did not alter the scoring function. Earnings adjustments remain non-positive proximity penalties and optional hard blocks. The API note still states earnings alone do not create an entry, and the scoring path only adjusts an already computed candidate score.

### 11. Insider boosts apply only to recent open-market purchases

**Pass.** The scoring code boosts only transactions that are recent and normalized as `open_market_purchase`; with the default non-discretionary filter enabled, that means Form 4 code `P`. I6-H2 preserves that rule while adding Finnhub normalization tests.

### 12. Sales/awards/tax withholding/option exercise remain cautious/informational by default

**Pass.** Non-`P` transaction types are normalized conservatively. Sales can only affect scoring through the optional `PAPER_INSIDER_SELL_PENALTY_POINTS`, which defaults to no penalty. Awards, tax withholding, gifts, and option exercise are informational/neutral by default.

### 13. Candidate output and dashboard expose Earn Adj / Ins Adj / Intel Adj

**Pass.** I6-H2 did not change candidate output or dashboard source, but the existing candidate output includes `earnings_score_adjustment`, `insider_score_adjustment`, and `intelligence_score_adjustment`, and the dashboard table exposes `Earn Adj`, `Ins Adj`, and `Intel Adj` columns.

### 14. TP/SL/exit behavior was not changed

**Pass.** The I6-H2 patch did not modify exit, TP, or SL code. The diff contains no take-profit/stop-loss/exit changes.

### 15. No broker/live trading/real orders were added

**Pass.** The I6-H2 diff does not add broker SDK imports, live-trading controls, or order-placement calls. The new Finnhub client is read-only intelligence data access.

### 16. No OpenAI/Anthropic/Ollama/LLM calls were added

**Pass.** The I6-H2 diff does not add OpenAI, Anthropic, Ollama, LangChain, model, or LLM calls. The new scoring/fetching behavior is deterministic and rule-based.

### 17. Backend tests and frontend build pass

**Pass.** Backend tests and frontend production build both pass in this workspace.

Backend:

```text
1145 passed, 2 skipped, 2 warnings in 13.62s
```

Frontend:

```text
✓ Compiled successfully
```

### 18. I6-H2 is safe for fake-money monitoring

**Pass with follow-up recommended.** I6-H2 is safe for fake-money monitoring because it is read-only, cache-first, admin-protected for forced refreshes, bounded by a capped universe, deterministic in scoring, and does not add broker/live-order/LLM behavior. The stale-cache metadata issue should be fixed for operator clarity, but it does not create real-money execution risk.

## Test results

### Backend tests

Command:

```bash
cd /workspace/microtrading-app/backend && pytest -q
```

Result:

```text
1145 passed, 2 skipped, 2 warnings in 13.62s
```

### Frontend build

Command:

```bash
cd /workspace/microtrading-app/frontend/dashboard && npm run build
```

Result: passed. The build emitted the existing npm environment warning about unknown `http-proxy` config, then completed successfully.

## Recommendation

Merge is acceptable for fake-money monitoring if the team is comfortable tracking the stale-cache metadata issue as a follow-up. I recommend fixing that issue before relying on the provider-status/cache-age fields for operational alerts or dashboard freshness decisions.
