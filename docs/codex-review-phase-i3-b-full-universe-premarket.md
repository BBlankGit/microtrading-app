# Codex Review — Phase I3-B Full-Universe PRE Market Scanner

## Review Scope

Reviewed only the latest Phase I3-B patch, commit `a498ce5` (`Add full-universe premarket scanner`). The patch touches:

- `backend/api/intelligence.py`
- `backend/core/config.py`
- `backend/data/polygon_client.py`
- `backend/intelligence/full_premarket.py`
- `backend/main.py`
- `backend/tests/test_phase_i3a.py`
- `backend/tests/test_phase_i3b.py`
- `frontend/dashboard/app/page.tsx`

This review did not change application code.

## Verdict

**Approved for fake-money monitoring, with operational caution.** Phase I3-B implements a read-only full-universe premarket scanner using Polygon bulk/chunked snapshots, central Redis caching, conservative TTL/interval guards, an active-universe fallback, and an admin-token-protected manual refresh endpoint. I did not find broker/live-trading/real-order/AI/LLM/Ollama additions, V6 hardcoded key/auth/test endpoint copies, or changes to trading/scoring/entry/exit/catalyst/no-catalyst logic.

The implementation is safe for fake-money monitoring and is reasonably safe for Polygon pressure under the default cadence. Operators should still treat `/api/intelligence/premarket` as an endpoint capable of triggering a full scan on cold start or expired cache when the scanner is enabled, and should keep the default intervals/concurrency conservative unless Polygon plan limits are confirmed.

No blocking findings were identified.

## Checklist Findings

| # | Review item | Result | Evidence |
|---|---|---|---|
| 1 | Full-universe PRE scanning is implemented and exposed through `/api/intelligence/premarket` | Pass | `backend/intelligence/full_premarket.py` adds a dedicated full-universe scanner. `GET /api/intelligence/premarket` checks `PREMARKET_SCANNER_ENABLED`, prefers the full-universe snapshot, refreshes it on TTL expiry/cold start, and only then falls back to the existing active-universe premarket path. |
| 2 | Scan uses Polygon bulk/chunked snapshot only, not per-ticker REST calls | Pass | `_scan_universe()` chunks the selected universe and calls `get_bulk_ticker_snapshots()` per chunk. The bulk client uses `/v2/snapshot/locale/us/markets/stocks/tickers` with a comma-separated `tickers` parameter. No per-symbol snapshot or previous-close calls are used by the full scan path. |
| 3 | Polygon API keys are not hardcoded and existing config/client patterns are used | Pass | The new scanner imports `settings` and calls existing-style helpers in `data.polygon_client`. The client continues to read `settings.POLYGON_API_KEY` through `_auth_params()` and `_assert_configured()`. I found no hardcoded Polygon key in the Phase I3-B diff. |
| 4 | Universe selection is appropriate for US common stocks and avoids ETFs/warrants/OTC where possible | Pass | `refresh_universe()` requests Polygon reference tickers with `market="stocks"`, `type="CS"`, and `active="true"`, which is the right available filter for listed common stocks and should avoid most ETFs/warrants/OTC noise. The fallback universe is smaller and inherited from existing paper/V5 symbols, so it is best-effort rather than a full CS-only universe. |
| 5 | Scan cadence/cooldown is safe and does not run every second | Pass | Defaults are premarket interval `60s`, regular interval `180s`, result TTL `90s`, chunk size `200`, max concurrent chunks `5`, and manual-refresh safety cooldown `30s`. The background loop sleeps `300s` afterhours/closed and does not scan every second. |
| 6 | Full scan results are cached centrally in Redis | Pass | `_redis_save_result()` stores `{"snapshot": snap, "fetched_at": fetched_at}` under `intelligence:premarket:full_universe` with a TTL of four times the result TTL. `ensure_loaded()` loads that central Redis result at startup. |
| 7 | `GET /api/intelligence/premarket` serves cached full-universe results and falls back safely when unavailable | Pass | The endpoint serves the in-memory full-universe snapshot loaded from Redis at startup, refreshes when stale, and falls back to the active-universe cache path if no successful full-universe scan is available. If a prior full-universe snapshot exists and a refresh fails, `fetch_and_refresh()` returns that stale cached snapshot with `ok: false` and an error field rather than raising. |
| 8 | `POST /api/intelligence/premarket/refresh` is admin-token protected | Pass | The refresh route is declared with `dependencies=[Depends(require_admin_token)]` and uses a manual-refresh cooldown unless `safe=true` is explicitly supplied by an authenticated caller. |
| 9 | Invalid/missing/malformed price and previous-close data are skipped per symbol | Pass | `_safe_float()` rejects missing, non-numeric, and non-finite values. `_entry_to_mover()` skips entries with missing/invalid/too-low last price, missing/non-positive previous close, or missing change percent, and catches malformed entries without raising. Tests cover invalid floats, missing previous close, zero previous close, missing change percent, malformed entries, and sub-$3 prices. |
| 10 | `top_gainers`, `top_losers`, and `top_movers` are ranked correctly by `gap_percent` | Pass | The scanner computes `gap_percent` from last price and previous close, sorts movers by absolute gap descending, splits gainers and losers, and assigns ranks. For gainers this yields largest positive gap first; for losers it yields most negative absolute gap first; `top_movers` is largest absolute gap first. |
| 11 | Frontend clearly shows Full Universe vs Active Universe fallback mode | Pass | The dashboard checks `premarket.mode === "full_universe"` and renders either `FULL UNIVERSE` or `ACTIVE UNIVERSE`, with scanned-symbol and valid-mover counts. The footer also distinguishes Polygon bulk snapshot full-universe mode from marketdata collector cache fallback mode. |
| 12 | Tab remains read-only and not integrated into trading decisions | Pass | The API and scanner docstrings explicitly state read-only/no broker/no live trading/no real orders. The frontend displays the premarket tab as read-only/no trading integration. No trading modules consume the new full-universe snapshot. |
| 13 | No trading/scoring/entry/exit/catalyst/no-catalyst logic was changed | Pass | The Phase I3-B diff is limited to intelligence API/scanner/client/config/startup/tests/dashboard files. No `backend/paper/`, `backend/engine/`, `backend/execution/`, or `backend/catalysts/` production logic changed. |
| 14 | Marketdata collector high-frequency architecture was not dangerously expanded to 5,000+ symbols | Pass | The patch does not modify `backend/marketdata/collector.py`, `backend/marketdata/service.py`, or the collector universe builder. Full-universe polling is isolated in `backend/intelligence/full_premarket.py` and uses chunked bulk snapshot scans, not the high-frequency marketdata collector. |
| 15 | No broker/live trading/real orders/AI/LLM/Ollama were added | Pass | Diff scanning found only read-only safety comments for broker/live-trading terms and no added broker SDKs, order-routing functions, OpenAI/Anthropic/LangChain/Ollama integrations, or LLM calls. |
| 16 | No V6 hardcoded keys/auth/test endpoints were copied | Pass | The patch adds no hardcoded secrets and no test-only auth endpoints. Polygon auth remains through `settings.POLYGON_API_KEY`; admin refresh uses the existing `require_admin_token` dependency. |
| 17 | Tests and frontend build pass | Pass | Full backend `pytest` passed with `995 passed, 2 skipped, 1 warning`. Targeted Phase I3-A/I3-B tests passed with `43 passed, 1 warning`. `npm run build` in `frontend/dashboard` completed successfully. |
| 18 | Phase I3-B is safe for fake-money monitoring and safe for Polygon pressure | Pass with caution | The feature is read-only, cache-backed, TTL-guarded, chunked, and isolated from trading. Default pressure is roughly one full scan per minute during premarket, with `ceil(universe/200)` bulk snapshot requests and max five concurrent chunks. This is materially safer than per-ticker REST, but still depends on the deployed Polygon plan and should not be tightened without rate-limit review. |

## Additional Notes

- `GET /api/intelligence/premarket` can trigger a full scan on cold start or when the full-universe snapshot TTL is expired. This is acceptable under the requested exposure, but it means the public read endpoint is not purely cache-only when the scanner is enabled.
- The scanner requires `todaysChangePerc` to be present even though `gap_percent` is computed from validated price and previous close. This is conservative data-quality filtering and matches the Phase I3-A hardening pattern.
- The fallback universe used when Polygon reference tickers fail is intentionally small and not guaranteed to be CS-only, because it reuses existing paper/V5 configured symbols. The primary universe path is the one that satisfies full-universe common-stock selection.
- Manual refresh supports `?safe=true`, which bypasses the 30-second safety cooldown. Because the route is admin-token protected, this is an operator escape hatch rather than a public pressure risk.

## Validation Commands Run

- `pytest backend/tests/test_phase_i3b.py backend/tests/test_phase_i3a.py` from repo root — passed (`43 passed, 1 warning`).
- `pytest` from `backend/` — passed (`995 passed, 2 skipped, 1 warning`).
- `npm run build` from `frontend/dashboard/` — passed.
