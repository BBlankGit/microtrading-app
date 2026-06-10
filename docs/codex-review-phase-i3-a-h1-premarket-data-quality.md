# Codex Review — Phase I3-A-H1 PRE Market Movers Data-Quality Hardening

## Review Scope

Reviewed only the latest Phase I3-A-H1 patch, commit `6299088` (`Harden premarket movers data quality`). The patch touches:

- `backend/api/intelligence.py`
- `backend/intelligence/premarket.py`
- `backend/tests/test_phase_i3a.py`
- `frontend/dashboard/app/page.tsx`

This review did not change application code.

## Verdict

**Approved for fake-money monitoring.** The H1 patch addresses the requested premarket movers data-quality hardening without adding direct Polygon polling, full-universe scanning, broker/live trading behavior, AI/LLM/Ollama integrations, copied auth/test endpoints, or changes to trading/scoring/entry/exit/catalyst/no-catalyst logic.

No blocking findings were identified.

## Checklist Findings

| # | Review item | Result | Evidence |
|---|---|---|---|
| 1 | `/api/intelligence/premarket` refreshes when snapshot TTL expires | Pass | The endpoint now computes `needs_refresh` when `fetched_at` is missing or `ttl_seconds <= 0`, then calls `fetch_and_refresh()`. `get_snapshot()` exposes remaining TTL as `max(0, ttl - age)`, so an expired snapshot reaches `0` and triggers refresh. A regression test seeds a stale snapshot and asserts the endpoint re-reads symbols once. |
| 2 | Missing/invalid/non-finite `previous_close` is excluded safely | Pass | `_safe_float()` rejects missing, non-numeric, and non-finite values. `_compute_mover()` reads collector `prev_close`, skips when it is `None` or `<= 0`, and exposes the validated value as `previous_close`. Tests cover `None`, zero, and negative previous close. |
| 3 | Malformed numeric fields are skipped per-symbol and do not fail the whole refresh | Pass | `_compute_mover()` wraps per-symbol parsing in a defensive `try` and returns `None` on invalid data. `fetch_and_refresh()` simply skips `None` movers and continues. Tests cover bad `last_price`, bad `change_percent`, malformed payloads, and mixed valid/invalid batch refresh. |
| 4 | `gap_percent` is computed explicitly from `last_price` and `previous_close`, or documented if collector `change_percent` is used | Pass | The module docstring and `_compute_mover()` docstring state that `gap_percent` is computed from validated prices. The implementation uses `((last_price - prev_close) / prev_close) * 100`; collector `change_percent` is retained separately as `raw_change_percent`. A test deliberately sets collector change to `99.99` while the real gap is `10%` and asserts `gap_percent == 10%`. |
| 5 | Frontend displays the correct `gap_percent` field | Pass | The frontend type was updated to `gap_percent`/`previous_close`/`raw_change_percent`, and the row renderer displays `m.gap_percent` in the `Gap%` column plus the validated previous close. |
| 6 | No full 5,000+ universe scanning was added | Pass | The refresh reads only `read_active_symbols()` from the collector cache and loops over those symbols. The H1 diff did not add symbol discovery, ticker scanning, or 5,000+ universe logic. |
| 7 | No direct/heavy Polygon polling was added | Pass | Premarket intelligence still imports only `marketdata.cache.read_active_symbols` and `read_symbol` inside refresh. Direct Polygon REST access remains isolated in the existing marketdata collector, not the intelligence endpoint. |
| 8 | Trading/scoring/entry/exit/catalyst/no-catalyst logic was not changed | Pass | The latest patch is limited to the intelligence API, premarket intelligence module, premarket tests, and dashboard display. No paper trading, scorer, entry/exit, catalyst, or no-catalyst modules were changed. |
| 9 | Marketdata collector architecture was not changed | Pass | No marketdata collector/cache/source files were changed by the H1 patch. Premarket continues to consume the collector cache. |
| 10 | No broker/live trading/real orders/AI/LLM/Ollama were added | Pass | The changed backend intelligence files explicitly remain read-only/no broker/no live trading/no real orders, and no AI/LLM/Ollama code appears in the H1 changes. |
| 11 | No V6 hardcoded keys/auth/test endpoints were copied | Pass | The patch did not introduce config keys, auth endpoints, hardcoded secrets, or test-only API endpoints. Existing `/premarket` remains a read-only GET endpoint; no new V6 auth/test surface was added. |
| 12 | Tests and frontend build pass | Pass | `pytest` passed with `975 passed, 2 skipped, 1 warning`; targeted `pytest tests/test_phase_i3a.py` passed with `23 passed, 1 warning`; `npm run build` in `frontend/dashboard` completed successfully. |
| 13 | Phase I3-A-H1 is safe for fake-money monitoring | Pass | The feature remains read-only, cache-backed, per-symbol defensive, frontend-aligned, and isolated from trading decisions and live/broker execution. |

## Notes

- The endpoint docstring says TTL expiry means `ttl_seconds == 0`. In implementation, `ttl_seconds` is a remaining TTL value clamped to zero, so this wording matches the current code path.
- `_compute_mover()` still requires a finite collector `change_percent` even though `gap_percent` is computed from prices. This is conservative data-quality filtering and is covered by tests. If future requirements allow price-only gap computation when collector change is absent, that would be a behavior change outside this review.

## Validation Commands Run

- `pytest tests/test_phase_i3a.py` from `backend/` — passed (`23 passed, 1 warning`).
- `pytest` from `backend/` — passed (`975 passed, 2 skipped, 1 warning`).
- `npm run build` from `frontend/dashboard/` — passed.
