# Codex Review — Phase I6-H3 Stale Finnhub Cache Metadata

Review target: latest `I6-H3` patch on branch `work`, commit `27680e1` (`Fix stale Finnhub cache metadata`).

Scope honored: reviewed only the latest I6-H3 patch. No production code was changed by this review.

## Verdict

**Approved for fake-money monitoring.**

I did not find a blocking issue in the I6-H3 patch. The patch fixes the stale-cache metadata bug for both Finnhub earnings and insider refreshes: successful refreshes update the cache timestamp normally, while failed refreshes with prior cached rows preserve the prior `fetched_at` and `_cache_time` and explicitly disclose that stale cache is being served.

## Review checklist

| # | Area | Result | Notes |
|---|------|--------|-------|
| 1 | Successful refresh updates cache time / `fetched_at` normally | Pass | Earnings and insiders set `fetched_at`, `last_successful_fetched_at`, `last_refresh_status=success`, `serving_stale_cache=false`, and update `_cache_time` on success. |
| 2 | Rate-limit/error with prior rows preserves old cache time / `fetched_at` | Pass | Prior rows keep their previous top-level `fetched_at`; `_cache_time` is intentionally not updated on the preserve-cache branches. |
| 3 | `cache_age_seconds` / `stale` do not falsely imply freshness after failed refresh | Pass | API `stale` is true when `serving_stale_cache` is true, when no usable cache is available, or when age exceeds TTL. Since `_cache_time` is not reset when prior rows are preserved, cache age keeps increasing after failed refreshes. |
| 4 | `serving_stale_cache` metadata is honest | Pass | Preserve-cache failure paths set `serving_stale_cache=true`; successful refreshes and no-prior-cache failures set it false. |
| 5 | No prior cache + error/rate-limit returns no rows and `available=false` | Pass | Both earnings and insiders return `results=[]`, `available=false`, `fetched_at=None`, and failure status when no prior usable rows exist. |
| 6 | Behavior is consistent for earnings and insiders | Pass | The success, preserved-cache failure, and no-prior-cache failure logic is symmetrical between the two modules. |
| 7 | No Finnhub key logged or hardcoded | Pass | The patch does not log key values. Tests monkeypatch `FINNHUB_API_KEY` with a dummy value only. Existing missing-key warnings mention the variable name, not a secret value. |
| 8 | No NEWSAPI usage added | Pass | The I6-H3 diff adds no NewsAPI references or usage. |
| 9 | No trading/scoring/entry/exit behavior changed | Pass | The I6-H3 production diff is limited to intelligence API metadata and Finnhub earnings/insider cache handling. Scoring functions and trading paths were not changed. |
| 10 | No TP/SL/exit behavior changed | Pass | No take-profit, stop-loss, or exit logic changed in the patch. |
| 11 | No broker/live trading/real orders added | Pass | No broker adapters, live-trading paths, or real-order code were added. |
| 12 | No OpenAI/Anthropic/Ollama/LLM calls added | Pass | The patch adds no LLM imports, clients, configuration, or runtime calls. |
| 13 | Backend tests and frontend build pass | Pass | `pytest` passed and `npm run build` passed. |
| 14 | Safe for fake-money monitoring | Pass | The patch is read-only metadata/cache handling for intelligence feeds and preserves fake-money-only boundaries. |

## Evidence reviewed

### Earnings

- Success path records a fresh `now_iso` as `fetched_at`, mirrors it into `last_successful_fetched_at`, marks `last_refresh_status` as `success`, sets `serving_stale_cache=false`, and updates `_cache_time`.
- Rate-limit/error path with prior cached rows updates only failure metadata, keeps prior rows and top-level `fetched_at`, sets `serving_stale_cache=true`, and intentionally does **not** update `_cache_time`.
- No-prior-cache failure path returns `available=false`, `results=[]`, `fetched_at=None`, and `serving_stale_cache=false`.

### Insiders

- Success, preserved-cache failure, and no-prior-cache failure behavior mirrors earnings.
- The insider preserve-cache path likewise avoids resetting `_cache_time`, so age does not regress after a failed refresh.

### API metadata

- `/intelligence/earnings` and `/intelligence/insiders` now include `last_attempted_at`, `last_successful_fetched_at`, `serving_stale_cache`, `last_refresh_status`, and `last_refresh_error`.
- API `stale` is derived from preserved-stale serving, unavailable cache state, or TTL age, preventing failed refreshes from looking fresh.

## Tests run

```bash
cd /workspace/microtrading-app/backend && pytest
```

Result: `1154 passed, 2 skipped, 2 warnings`.

```bash
cd /workspace/microtrading-app/frontend/dashboard && npm run build
```

Result: successful Next.js production build.

## Notes / non-blocking observations

- The admin refresh endpoints still return a compact response and do not surface all of the newly added stale-cache metadata. This is not a blocker for I6-H3 because the cache payload and read endpoints expose the honest metadata, and the compact refresh response does not report `cache_age_seconds` or `stale` in a misleading way.
- A successful but empty provider response is treated as an available fresh cache; a later failure with no prior rows returns unavailable/no rows rather than serving an empty prior result as stale. That matches the I6-H3 focus on preserving prior rows and avoiding fake rows.
