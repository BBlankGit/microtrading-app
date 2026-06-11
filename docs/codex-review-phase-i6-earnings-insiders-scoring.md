# Codex Review — Phase I6 Earnings Calendar, Insider Transactions, and Fake-Money Scoring

Date: 2026-06-11  
Reviewed patch: `4855e56 Add earnings and insider intelligence scoring`  
Scope: latest Phase I6 patch only; no code changes made.

## Executive Summary

Phase I6 is broadly aligned with the requested fake-money-only direction: the new Earnings and Insider surfaces are cache-backed, the refresh endpoints are admin-token protected, dashboard tabs clearly warn when providers are not configured, scoring changes are deterministic and transparent, and no broker/live trading/real-order/LLM integrations were introduced.

However, I would not call the patch fully merge-clean yet because the backend test suite fails and there is one honesty/status inconsistency in the provider stubs:

1. **Blocking:** `pytest -q` fails in `tests/test_phase_s1v1_h2.py::test_score_candidate_called_with_adjusted_q_in_source` because the Phase I6 formatting of the `score_candidate` call no longer matches the source-inspection substring expected by the test.
2. **Needs cleanup:** For configured-but-unwired providers (`EARNINGS_DATA_PROVIDER=polygon|finnhub`, `INSIDER_DATA_PROVIDER=polygon|finnhub`), both modules return empty data with a warning but set `enabled: True`. The patch description and user requirement call for being honest when unavailable; the warning is honest, but `enabled: True` is misleading because no provider fetcher is wired.

With those two items addressed, the implementation looks safe for fake-money monitoring.

## Review Checklist

| # | Check | Result | Notes |
|---:|---|---|---|
| 1 | Earnings Calendar endpoint is cache-first and honest when disabled/unavailable | ⚠️ Mostly pass, with status-label concern | `GET /api/intelligence/earnings` uses the earnings module cache and only warms it on an empty cache. When provider is `none`, it returns `enabled=false`, empty rows, and a clear warning. For `polygon`/`finnhub` stubs, it returns empty rows and warning but `enabled=true`, which is less honest than the patch claims. |
| 2 | Insider Transactions endpoint is cache-first and honest when disabled/unavailable | ⚠️ Mostly pass, with same status-label concern | `GET /api/intelligence/insiders` uses the insider module cache and only warms it on an empty cache. Provider `none` is honest; configured-but-unwired providers return warnings but `enabled=true`. |
| 3 | Refresh endpoints are admin-protected | ✅ Pass | `POST /api/intelligence/earnings/refresh` and `POST /api/intelligence/insiders/refresh` both declare `dependencies=[Depends(require_admin_token)]`. |
| 4 | GET endpoints avoid live external calls on every dashboard refresh | ✅ Pass | GET handlers use in-memory snapshots and only call `fetch_and_refresh()` on empty cache; the dashboard Earnings/Insiders tabs self-fetch and are not part of the 30-second global loop. Provider fetchers are stubs and make no external calls. |
| 5 | No hardcoded V6 secrets or new credentials were added | ✅ Pass | Config adds provider selectors and scoring knobs, but no concrete keys/secrets. The only key mention is a placeholder/reference to future `FINNHUB_API_KEY`. |
| 6 | No heavy 5,000-symbol polling job was added | ✅ Pass | No new 5,000-symbol polling loop was added. The simulator snapshots two intelligence caches once per tick and indexes the cached rows by symbol. |
| 7 | Earnings tab displays data or placeholder clearly | ✅ Pass | The tab shows an explanatory banner, disabled-provider warning, filters, refresh status, cache age, and an explicit no-rows placeholder. |
| 8 | Insiders tab displays data or placeholder clearly | ✅ Pass | The tab shows an explanatory banner, disabled-provider warning, filters, refresh status, cache age, and an explicit no-rows placeholder. |
| 9 | Earnings scoring is a risk/proximity penalty, not a bullish catalyst by itself | ✅ Pass | Earnings adjustment is only zero or negative, with optional hard block. The dashboard explicitly states upcoming earnings are not automatically bullish and cannot create an entry. |
| 10 | Insider scoring only boosts recent open-market purchases and handles sales/awards/tax withholding cautiously | ✅ Pass | Only recent code `P` open-market purchases qualify for boosts. Sales have default penalty `0`; awards, tax withholding, gifts, exercises, and other codes are informational/neutral by default. |
| 11 | Earnings/insider adjustments are transparent in candidate output | ✅ Pass | Candidate output includes earnings and insider adjustment fields, reasons, dates/counts, and transaction codes. |
| 12 | Base score, intelligence adjustment, and final score are visible or auditable | ✅ Pass | Scoring returns `base_score_before_intelligence_adjustments`, `intelligence_score_adjustment`, and `final_score_after_intelligence_adjustments`; the dashboard displays the intelligence adjustment with tooltip from base to final. |
| 13 | Earnings calendar alone cannot create an entry | ✅ Pass | Earnings never adds positive score and is only an adjustment on existing candidate/scoring paths. |
| 14 | Insider sales do not automatically hard-block or over-penalize | ✅ Pass | Insider sales are surfaced; default sell penalty is `0`, and there is no hard-block logic for sales. |
| 15 | TP/SL/exit behavior was not changed | ✅ Pass | Phase I6 diff does not modify the paper exits module or TP/SL config defaults. Simulator additions are around cache snapshotting and candidate scoring/output, not exit calculation. |
| 16 | No broker/live trading/real orders were added | ✅ Pass | New modules and scoring docs explicitly state no broker/live trading/real orders, and no new broker/order integration appears in the patch. |
| 17 | No OpenAI/Anthropic/Ollama/LLM calls were added | ✅ Pass | New intelligence/scoring modules are deterministic rule-based and contain no LLM calls. The patch adds no OpenAI/Anthropic/Ollama invocation. |
| 18 | Tests and frontend build pass | ❌ Fail | Frontend build passes. Backend tests fail: `1 failed, 1118 passed, 2 skipped`. |
| 19 | Phase I6 is safe for fake-money monitoring | ⚠️ Conditionally | Runtime behavior appears fake-money-safe and cache-first, but the failing test and `enabled=true` for unavailable configured providers should be fixed before accepting. |

## Detailed Findings

### Finding 1 — Backend tests fail because of a source-inspection regression

**Severity:** Blocking for merge/release hygiene  
**Area:** Tests / simulator scoring call formatting

`pytest -q` fails with:

```text
FAILED tests/test_phase_s1v1_h2.py::test_score_candidate_called_with_adjusted_q_in_source
ValueError: substring not found
```

The failing test expects the literal source substring:

```text
score_candidate(sym, _q_for_paths
```

Phase I6 changed the call to a multi-line form:

```python
scoring = score_candidate(
    sym,
    _q_for_paths,
    cats,
    earnings_info=_earn_info,
    insider_info=_ins_info,
)
```

The implementation behavior is probably correct, but the repository requirement is that tests pass. Either the call should be formatted to satisfy the existing test, or the test should be updated to inspect the AST / tolerate multiline formatting.

### Finding 2 — Configured-but-unwired provider stubs return `enabled=true`

**Severity:** Medium  
**Area:** Honest unavailable-state semantics

For default provider `none`, both modules behave well:

- `enabled: False`
- no fake rows
- warning explaining provider is not configured

For `polygon` or `finnhub`, both modules currently do this:

- no real fetcher is wired
- `results` remains empty
- warning explains the provider is unavailable/stubbed
- **but `enabled: True` is returned**

That can mislead the frontend/API consumer into thinking real data collection is enabled. The warning mitigates this, but the review requirement explicitly asks for honesty when disabled/unavailable. Recommended fix: return either `enabled: False` or add a distinct field such as `available: False` / `provider_status: "stub_unavailable"` for configured-but-unwired providers.

## Endpoint Review

### Earnings Calendar

- `GET /api/intelligence/earnings` is cache-first in practice: it checks the module snapshot and only calls `fetch_and_refresh()` when no snapshot exists.
- It reports cache metadata: `cache_age_seconds`, `ttl_seconds`, and `stale`.
- It supports filters and pagination: ticker/symbol, from/to date, days ahead, sort, limit, offset.
- It returns no fake rows when provider is `none`.
- It correctly exposes a disabled-provider warning for provider `none`.
- For stale cache, GET marks `stale` rather than forcing a live call on every dashboard request.
- Admin refresh is protected.

### Insider Transactions

- `GET /api/intelligence/insiders` is cache-first in practice: it checks the module snapshot and only calls `fetch_and_refresh()` when no snapshot exists.
- It reports cache metadata: `cache_age_seconds`, `ttl_seconds`, and `stale`.
- It supports filters and pagination: ticker/symbol, transaction type, minimum value, days back, sort, limit, offset.
- It returns no fake rows when provider is `none`.
- It correctly exposes a disabled-provider warning for provider `none`.
- Admin refresh is protected.

## Scoring Review

### Earnings scoring

- Deterministic, rule-based, and fake-money only.
- Adjustment is never positive.
- Close earnings produce configurable penalties:
  - strong penalty within 1 day by default: `-10`
  - medium penalty within 2 days by default: `-5`
  - light penalty within 3 days by default: `-3`
- Optional hard block exists but defaults to disabled via `PAPER_EARNINGS_BLOCK_WITHIN_DAYS = 0`.
- Candidate output includes adjustment, reason, next date, days until, and hard-block flag.
- Earnings calendar alone cannot create a catalyst or entry because it only adjusts an already computed candidate score.

### Insider scoring

- Deterministic, rule-based, and fake-money only.
- Only recent open-market purchases (`Form 4` code `P`) qualify for bullish score boosts.
- Purchases below the configured value threshold produce a reason but no boost.
- Sales are not an automatic hard block and default to no penalty.
- Awards, option exercises, tax withholding, gifts, and unknown codes are informational/neutral by default.
- Candidate output includes adjustment, reason, recent buy count/value, latest transaction date, and transaction codes.

## Frontend Review

- Earnings tab is explicit that upcoming earnings are not automatically bullish and that earnings alone cannot create an entry.
- Insiders tab is explicit that only recent open-market purchases are treated as bullish and that sales/awards/tax withholding are cautious/informational.
- Both tabs show provider-disabled warnings and no-row placeholders.
- Both refresh buttons require an admin token on the client and call admin-protected backend endpoints.
- Earnings/Insiders tabs self-manage fetches and are not included in the global 30-second dashboard refresh loop.
- Candidate table displays `Earn Adj`, `Ins Adj`, and `Intel Adj`, with tooltips/reasons and a base-to-final tooltip.

## External Calls / Polling / Safety Review

- No new live provider fetcher is implemented for earnings or insiders; provider branches are stubs with warnings.
- No new 5,000-symbol polling job was added.
- No new broker, live trading, or real-order path was added.
- No new OpenAI, Anthropic, Ollama, or LLM call was added.
- TP/SL/exit code was not changed by the Phase I6 patch.

## Verification Commands

### Backend tests

```bash
cd /workspace/microtrading-app/backend && pytest -q
```

Result:

```text
1 failed, 1118 passed, 2 skipped, 2 warnings in 9.55s
```

Failure:

```text
FAILED tests/test_phase_s1v1_h2.py::test_score_candidate_called_with_adjusted_q_in_source
ValueError: substring not found
```

### Frontend build

```bash
cd /workspace/microtrading-app/frontend/dashboard && npm run build
```

Result: passed.

## Recommendation

**Do not merge Phase I6 as-is until the backend test failure is fixed.** After that, I recommend tightening the API semantics for configured-but-unavailable provider stubs so they do not report `enabled=true` without a real data fetcher.

Once those are addressed, Phase I6 appears safe for fake-money monitoring: it is cache-first, transparent, deterministic, non-broker, non-LLM, and avoids adding heavy polling or real-order behavior.
