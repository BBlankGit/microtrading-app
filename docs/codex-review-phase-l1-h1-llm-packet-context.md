# Codex Review — Phase L1-H1 LLM Packet Context Completion

Review date: 2026-06-11  
Reviewed patch: `ad7df1e` (`Complete LLM packet context`) only, against its parent.

## Verdict

Phase L1-H1 is a meaningful improvement to LLM shadow packet quality and remains fake-money/shadow-only with no broker or real-order integration added. The packet builder now receives the simulator's already-computed market-quality data, includes cached catalyst/news rows when the simulator already has them, marks missing intraday history honestly, and improves dashboard label clarity.

I found **one security hardening gap**: `marketdata_error` redaction currently covers OpenAI-style `sk-...` strings and `Bearer ...` tokens, but it does not redact common query-parameter or assignment-style secrets such as `apiKey=...`, `POLYGON_API_KEY=...`, `token=...`, or `key=...`. The current Polygon client normally raises sanitized high-level `PolygonError` messages, so this is not an observed leak in the normal path, but the packet contract says `marketdata_error` is sanitized and no secrets are exposed; the redactor should be broadened before treating that guarantee as complete.

## Scope confirmation

Reviewed only files touched by the latest L1-H1 patch:

- `backend/intelligence/llm_shadow.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase_l1.py`
- `backend/tests/test_phase_l1_h1.py`
- `frontend/dashboard/app/page.tsx`

No production code was changed by this review. This document is the only file added.

## Findings

### 1. Cached news/catalyst rows are included in normal simulator LLM packets when available

**Status: Pass.**

The LLM section in `run_tick` builds `_llm_news_by_sym` from `catalyst_map`, which was already populated earlier in the tick for normal engine catalyst processing. It caps rows with `LLM_SHADOW_MAX_NEWS_ITEMS_PER_SYMBOL` and passes that map into `build_candidate_packet` for each selected LLM candidate. The packet builder then emits a `news` section with `news_available`, capped `items`, and explicit unavailable reasons.

Notes:

- Symbols with no rows are explicitly represented as `[]`, allowing the packet builder to distinguish “no cached news for symbol” from “news lookup not provided.”
- The builder preserves useful catalyst attributes including title, source, publication timestamp, URL, rule event type, rule impact, sentiment, materiality, sentiment score, bullish/bearish flags, reasons, explanation, and `used_by_engine`.

### 2. LLM path does not trigger live external news calls

**Status: Pass.**

The only direct news fetch in the simulator remains the pre-existing catalyst collection stage before LLM processing. The LLM-specific section reads from the already-built `catalyst_map`; it does not call `collect_news_for_symbols`, Polygon news endpoints, or another live news client.

The L1-H1 simulator tests include AST/string coverage verifying the packet call now passes `_llm_news_by_sym` and no longer passes `news_items_by_symbol=None`.

### 3. LLM packets include market data fields and cache metadata

**Status: Pass.**

`build_candidate_packet` now accepts a `quality` argument and prefers those per-tick `evaluate_market_quality` values before falling back to candidate fields. The market-data section now includes:

- `bid`
- `ask`
- `last_trade_price`
- legacy alias `last_price`
- `day_volume`
- `previous_day_volume`
- `bid_size` / `ask_size` when present
- spread and spread percent
- change percent
- volume ratio
- tradability
- market-data source, age, fetched timestamp, fallback-used flag, stale flag, missing flag, and error text

The simulator passes `quality=quality_map.get(symbol)` into packet construction, so normal packets should get the richest available market-quality view.

### 4. `marketdata_error` is sanitized, but redaction is incomplete for non-OpenAI secret shapes

**Status: Needs follow-up hardening.**

The packet builder sanitizes `candidate["marketdata_error"]` before putting it in the LLM packet, and the current redactor handles OpenAI-style `sk-...` substrings and `Bearer ...` tokens.

Gap: the redactor does **not** currently cover common non-Bearer secret forms such as:

- `apiKey=...`
- `apikey=...`
- `POLYGON_API_KEY=...`
- `token=...`
- `key=...`
- URL query strings containing API keys

The current Polygon client's explicit `PolygonError` messages are mostly sanitized, but generic network/client exceptions or future data-provider errors could include request URLs or key-like query parameters. Because the review criterion is “no secrets are exposed,” I would treat this as a **medium-priority hardening item** for a follow-up patch.

### 5. Intraday helper is cache-only and makes no Polygon/external calls

**Status: Pass.**

`get_cached_intraday_history(symbol, max_points)` is a placeholder extension point that returns `None` and performs no calls. The packet builder invokes it only when no `intraday_history` map is supplied, and the helper is intentionally cache-only. L1-H1 tests AST-inspect the helper body to confirm there are no calls in the helper.

### 6. Unavailable intraday history is honestly represented

**Status: Pass.**

When no cached intraday history exists, the packet contains:

- `intraday_history_available: False`
- empty `recent_price_points`
- empty `recent_change_percent_points`
- empty `recent_volume_points`
- `intraday_unavailable_reason: "no cached intraday history series for symbol"`

This avoids hallucinating minute bars or implying that unavailable data was fetched.

### 7. Candidate packet still includes required decision/context sections

**Status: Pass.**

The candidate packet still includes:

- real engine decision context under `engine`
- deterministic enhanced shadow decision context under `shadow`
- reddit telemetry under `reddit`
- earnings context under `earnings`
- insider context under `insiders`
- market regime and market trend context under `market_context`

The L1-H1 additions did not remove those sections.

### 8. LLM remains shadow-only and cannot change `eligible`, `action`, or `entry_mode`

**Status: Pass.**

The simulator initializes LLM defaults on candidates and only overlays the normalized LLM result payload. The normalized response schema is restricted to `llm_*` fields and does not include `eligible`, `action`, or `entry_mode`. The simulator comment also explicitly documents that LLM output never modifies those engine fields.

### 9. LLM cannot place trades or affect exits, position sizing, cash, or equity

**Status: Pass.**

The LLM section runs after the entry/exit accounting work and only writes LLM telemetry fields back to candidate rows. It does not call account entry/exit methods, bracket exit helpers, risk sizing logic, cash/equity mutation paths, or broker integrations. The account summary included in the packet is read-only context.

### 10. Dashboard labels clearly distinguish engine, deterministic shadow, and LLM shadow decisions

**Status: Pass.**

The candidates table headers were updated from ambiguous “Decision / Rejection”, “Shadow Decision”, and “LLM Decision” labels to clearer labels:

- `Engine Decision`
- `Deterministic Shadow Decision`
- `LLM Shadow Decision`

Tooltips reinforce that deterministic shadow and LLM shadow are diagnostic only and do not place trades.

### 11. No TP/SL/exit behavior changed

**Status: Pass.**

The latest patch did not modify the exits module and did not alter the simulator's TP/SL or bracket-exit logic. LLM processing remains after those mechanics and writes only LLM telemetry to candidates.

### 12. No broker/live trading/real orders were added

**Status: Pass.**

No broker integration or real-order path was added. The simulator and LLM module continue to state fake-money/shadow-only constraints, and the LLM system prompt says the analyst does not place trades.

### 13. No full prompts/secrets are logged

**Status: Pass with the same redaction caveat as finding 4.**

The LLM call sends the structured packet to OpenAI when enabled and keyed, but normal success logging records only symbol, decision, confidence, and latency. Error handling avoids logging response bodies and redacts error text with `_redact`.

There is no full prompt logging in the reviewed code path. However, because `_redact` is incomplete for `apiKey=`/query-parameter style secrets, the same hardening recommendation applies to error text and status fields.

### 14. Backend tests and frontend build pass

**Status: Pass.**

Commands run:

- `pytest -q` from `backend/` — passed: 1238 passed, 2 skipped, 2 warnings.
- `npm install` from `frontend/dashboard/` — passed; dependencies already up to date. NPM printed an environment warning about unknown `http-proxy` config.
- `npm run build` from `frontend/dashboard/` — passed; Next.js production build completed successfully.

### 15. Safe for fake-money monitoring and improved analyst packet quality

**Status: Pass, with follow-up redaction hardening recommended.**

The patch is safe for fake-money monitoring because LLM output remains diagnostic telemetry only, has no order placement path, cannot mutate engine trade decisions, and does not affect exits, position sizing, cash, or equity. It materially improves analyst packet quality by providing richer market-data fields, cache metadata, explicit news availability, cached catalyst rows, and honest intraday unavailability.

Before promoting the packet contract as fully “secret-safe,” broaden `_redact` to cover common provider key and URL query-parameter patterns.

## Test evidence

```text
backend$ pytest -q
1238 passed, 2 skipped, 2 warnings in 16.62s
```

```text
frontend/dashboard$ npm install
up to date in 588ms
```

```text
frontend/dashboard$ npm run build
✓ Compiled successfully
✓ Generating static pages (4/4)
```
