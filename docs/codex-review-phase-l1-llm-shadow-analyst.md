# Codex Review — Phase L1 LLM Shadow Analyst

Review target: latest L1 patch at `c910f0f Add LLM shadow analyst`.

Scope honored: reviewed only the latest patch files:

- `backend/api/llm_shadow.py`
- `backend/core/config.py`
- `backend/intelligence/llm_shadow.py`
- `backend/main.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase_l1.py`
- `frontend/dashboard/app/page.tsx`

## Executive verdict

**L1 is safe for fake-money monitoring from a trading-control perspective, but it is not fully complete as a market-data/context packet implementation.**

The patch keeps LLM output shadow-only: it is appended after deterministic entry/exit/account decisions are made, and I found no path where LLM output can change `eligible`, `action`, `entry_mode`, exits, position sizing, cash, equity, broker connectivity, or real-order execution.

However, the candidate packet assembled during the simulator tick does **not** currently satisfy all requested context completeness requirements:

1. The simulator passes `news_items_by_symbol=None` into `build_candidate_packet`, so LLM packets produced by normal ticks omit the full news/catalyst items even though the packet builder supports them.
2. The simulator candidate dict does not include several raw market-quality fields (`bid`, `ask`, `last_trade_price`/`last_price`, `day_volume`) that the packet builder tries to read, and the packet builder omits some existing cache metadata such as `marketdata_fetched_at`, `marketdata_fallback_used`, and the actual `marketdata_error` detail.
3. The simulator always passes `intraday_history=None`; this is honest unavailable metadata, but it means no intraday evolution is included if any cached intraday history exists elsewhere.
4. Dashboard labels are close but not fully explicit: the table uses `Decision / Rejection`, `Shadow Decision`, and `LLM Decision`, not the exact clearer labels `Engine Decision`, `Deterministic Shadow Decision`, and `LLM Shadow Decision`.

## Findings

### Finding 1 — LLM tick packets omit full news/catalyst feed context

**Severity:** Medium  
**Impacted checklist items:** 4, 6  
**Status:** Fails requested completeness requirement, but not a trading-safety issue.

`build_candidate_packet` supports a rich `news` section with title, source, published timestamp, URL, rule event type, impact, sentiment, materiality, flags, reasons, and whether the item was used by the engine. In the simulator integration, however, `_analyze_one()` calls `build_candidate_packet(..., news_items_by_symbol=None, ...)`, so normal tick-triggered LLM packets always receive an empty `news` list.

Evidence:

- Packet builder reads `news_items_by_symbol` and builds news rows only when supplied.
- Simulator passes `news_items_by_symbol=None` during normal LLM analysis.

Impact:

- The LLM cannot review the same full news/catalyst packet that deterministic intelligence used.
- The dashboard/intelligence tab may show news, but the LLM packet from the trading tick does not include it.
- This undercuts requirements that the candidate packet include news and not only intelligence-tab data.

Recommendation:

- In a future code patch, pass the collected per-symbol news/catalyst items already available in the tick (or a cache snapshot keyed by ticker) into `build_candidate_packet`.
- Add an integration test that verifies the simulator-side packet, not just direct builder calls, includes news for a candidate with catalysts.

### Finding 2 — Marketdata/Polygon/cache fields are incomplete in real simulator packets

**Severity:** Medium  
**Impacted checklist item:** 4  
**Status:** Fails requested completeness requirement, but not a trading-safety issue.

The packet builder attempts to include marketdata fields (`last_price`, `bid`, `ask`, `day_volume`, etc.), but the real simulator candidate dict does not populate many of those fields before LLM packet construction. It does include some derived values (`spread_percent`, `change_percent`, volume ratios, cache metadata), but not the full raw market-quality snapshot fields that exist in `evaluate_market_quality` output.

Evidence:

- `evaluate_market_quality()` returns `last_trade_price`, `bid`, `ask`, `day_volume`, `previous_day_volume`, `volume_ratio`, quote sizes, spread, and quality booleans.
- The simulator candidate includes some derived/cache fields, but the L1 patch did not add `bid`, `ask`, `last_trade_price`/`last_price`, or `day_volume` to the candidate dict.
- The LLM packet builder reads those missing fields from the candidate, so they become `None` in real tick packets.
- The simulator candidate includes cache metadata (`marketdata_fetched_at`, `marketdata_fallback_used`, `marketdata_error`), but the LLM packet only includes age/source/stale plus a boolean `marketdata_missing`; it does not carry fetched timestamp, fallback flag, or sanitized error detail.

Impact:

- The LLM packet is not yet the “full marketdata/Polygon/cache fields” packet requested.
- The LLM may see an incomplete quote/price/volume picture even when the deterministic engine had those fields available.

Recommendation:

- Add the raw market-quality fields from `q` to the simulator candidate or pass `q` directly into the packet builder.
- Include cache metadata fields in `marketdata`: `marketdata_fetched_at`, `marketdata_fallback_used`, and sanitized `marketdata_error`.
- Add a simulator-level test that patches `_llm_mod.analyze_candidate_packet` and asserts the packet contains bid/ask/last trade/day volume/cache fields.

### Finding 3 — Intraday evolution is always unavailable in simulator LLM packets

**Severity:** Low/Medium  
**Impacted checklist item:** 5  
**Status:** Partially passes because metadata is honest unavailable; incomplete if intraday history exists elsewhere.

The packet builder supports an `intraday_history` input and emits either capped recent price/change/volume points or `intraday_history_available: False` with an explanatory note. The simulator currently passes `intraday_history=None` unconditionally.

Impact:

- This meets the “honest unavailable metadata” part of the requirement.
- It does not meet the “includes intraday evolution if available” part if any cached intraday evolution becomes available outside this patch.

Recommendation:

- Keep the current unavailable metadata as the safe fallback.
- If a cached intraday series exists later, thread it into `build_candidate_packet` without adding new Polygon calls in the LLM path.

### Finding 4 — Dashboard labels are not fully explicit for the three decision layers

**Severity:** Low  
**Impacted checklist item:** 14  
**Status:** Mostly clear, but exact requested clarity is not fully met.

The dashboard distinguishes deterministic and LLM columns visually, but the table headers use:

- `Decision / Rejection`
- `Shadow Decision`
- `LLM Decision`

The requested labels were clearer:

- `Engine Decision`
- `Deterministic Shadow Decision`
- `LLM Shadow Decision`

Impact:

- Low operational risk: the columns are separated and color-coded.
- Human operators may still benefit from more explicit labels, especially because `Shadow Decision` and `LLM Decision` are adjacent.

Recommendation:

- Rename dashboard headers to the requested labels in a future frontend-only patch.

## Checklist review

### 1. LLM is shadow-only and cannot change `eligible` / `action` / `entry_mode`

**Pass.**

The simulator finishes deterministic entry path selection and account actions before appending LLM fields. The LLM block initializes `llm_*` defaults and only writes keys returned by `_by_sym` into the candidate. Normalized LLM response keys are all `llm_*`, so they do not overwrite `eligible`, `action`, or `entry_mode`.

### 2. LLM cannot place trades or affect exits / position sizing / cash / equity

**Pass.**

The LLM integration occurs after the deterministic entry block, after enhanced shadow stats, and before state/journal persistence. It does not call `_account.enter_position`, exit evaluation, or sizing logic. Account cash/equity are included as read-only context in the packet, but LLM output is not routed back into account mutation.

### 3. No broker/live trading/real-order path was added

**Pass.**

The L1 patch adds an OpenAI HTTP call for analysis only and a read-only/admin diagnostic API router. I found no broker adapter, order endpoint, live-trading flag enablement, or real-order execution path in the patch.

### 4. Candidate packet includes full marketdata/Polygon/cache fields, not only intelligence-tab data

**Fail / incomplete.**

The packet builder has a `marketdata` section, but real simulator packets are incomplete because several fields the builder reads are never populated on simulator candidates. Existing cache metadata is also only partially represented.

See Findings 1 and 2.

### 5. Candidate packet includes intraday evolution if available, or honest unavailable metadata

**Partial pass.**

The builder honestly emits `intraday_history_available: False` with a note when no history is supplied. The simulator always supplies `None`, so there is no intraday evolution in L1 normal tick packets.

### 6. Candidate packet includes engine decision, deterministic shadow decision, news, reddit, earnings, insiders, market regime, and market trend

**Partial pass.**

- Engine decision: pass.
- Deterministic enhanced shadow decision: pass.
- Reddit: pass for summary/rank fields.
- Earnings: pass.
- Insiders: pass.
- Market regime/trend: pass.
- News: fail in simulator integration because `news_items_by_symbol=None` is passed.

### 7. LLM candidate selection is capped and cost-controlled

**Pass.**

The selector caps at `LLM_SHADOW_MAX_CANDIDATES_PER_TICK`, defaults to 5, skips stale marketdata and wide spreads, excludes open positions by default, caches packets by hash with TTL, uses a timeout, and limits response tokens. One minor implementation note: the selector comment says missing bid/ask should be skipped, but the code currently `pass`es through missing bid/ask, likely because real candidates do not populate bid/ask.

### 8. Dashboard GET endpoints do not trigger LLM calls

**Pass.**

The dashboard LLM tab polls `GET /api/intelligence/llm/status`, and that endpoint returns `_llm.get_status()` only. The only endpoint that calls `analyze_candidate_packet` is `POST /api/intelligence/llm/analyze-candidate`, protected by `require_admin_token`.

### 9. Runtime config defaults LLM off

**Pass.**

`LLM_SHADOW_ENABLED` defaults to `False` in `backend/core/config.py`.

### 10. Missing API key is handled safely

**Pass.**

`analyze_candidate_packet` checks `api_key_present()` before any provider work and returns `missing_api_key` with zero provider calls. The simulator also marks default candidate rows as `missing_api_key` and does not enter the LLM analysis loop unless enabled and key-present.

### 11. Prompts/responses do not log secrets

**Pass.**

The prompt contains only the structured packet. The API key is used only in the Authorization header. HTTP error handling avoids response body logging. Response logging logs only symbol, decision, confidence, and latency. Redaction exists for error strings.

### 12. LLM JSON output is validated and errors/timeouts do not affect trading

**Pass.**

The OpenAI call requests JSON object output, parses JSON, requires a dict, normalizes enums/clamped numeric fields, and wraps failures into stable `llm_status` error results. Simulator LLM integration is inside a defensive `try/except`, so LLM failures cannot break a tick.

### 13. LLM results are clearly separated from deterministic shadow scoring

**Pass.**

Deterministic shadow scoring writes `enhanced_shadow_*`; LLM writes `llm_*`. The dashboard renders deterministic shadow columns separately from LLM columns.

### 14. Dashboard labels Engine Decision / Deterministic Shadow Decision / LLM Shadow Decision clearly

**Partial pass.**

The UI separates the layers, but labels are not as explicit as requested. See Finding 4.

### 15. Backend tests and frontend build pass

**Pass.**

Commands run:

- `cd backend && pytest tests/test_phase_l1.py` — 21 passed, 1 warning.
- `cd frontend/dashboard && npm run build` — passed.

### 16. L1 is safe for fake-money monitoring

**Pass with context-completeness caveats.**

From a safety perspective, L1 is safe for fake-money monitoring because it is default-off, key-gated, capped, cached, timeout-wrapped, error-isolated, and not wired into trading/account mutation. From an analyst-quality perspective, the packet completeness gaps above should be fixed before relying on LLM conclusions as a high-fidelity shadow analyst.

## Suggested follow-up tests

For the next implementation patch, add tests that exercise the simulator integration rather than only direct packet-builder calls:

1. Patch `_llm_mod.analyze_candidate_packet` to capture packets emitted during `_run_tick_once()` and assert news items are present when catalysts/news exist.
2. Assert captured packets include `bid`, `ask`, `last_trade_price`, `day_volume`, quote sizes if available, cache fetched timestamp, fallback flag, stale flag, and sanitized error detail.
3. Assert any future intraday cache is passed through only when already cached, with no new Polygon calls in the LLM path.
4. Assert dashboard headers contain the exact terms `Engine Decision`, `Deterministic Shadow Decision`, and `LLM Shadow Decision`.
