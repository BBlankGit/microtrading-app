# Codex Review — Phase G1B Freeze Persistence, Outcomes, Wallets

**Verdict: FAIL**

## 1. Executive summary

I reviewed the current repository state for the latest Phase G1B scope. I do **not** find a G1B implementation for full freeze-readiness persistence, outcome tracking, or three independent fake wallets.

The current code still has the pre-G1B journal model: `paper_candidates` persists many typed fields, but there is no `extras_json` or equivalent full runtime-context capture. There is no candidate outcome table/resolver for 5/10/15/30/60 minute horizons. The simulator still uses a single in-memory `PaperAccount`, and positions/trades do not carry `wallet_id` or `strategy_id`.

The safety boundary remains broadly intact: I did not find new broker/live/order execution paths in the reviewed G1B-related areas. However, because the requested G1B functionality is absent, this phase cannot be approved for a two-week fake-money freeze.

## 2. Findings

### Finding 1 — Full candidate context persistence is not implemented

**Severity: High / blocking**

Evidence reviewed:

- `paper_candidates` has typed columns for candidate basics, scoring, sentiment, momentum, marketdata, and no-catalyst snapshots, but no `extras_json` or equivalent catch-all runtime context column.
- Candidate insertion serializes only selected fields from each candidate dict into fixed columns.
- LLM and deterministic shadow fields are computed onto candidate dictionaries during the tick, but the journal insert does not persist those fields.

Impact:

- Freeze audit cannot reconstruct full candidate runtime context.
- Available LLM states such as disabled/error/not_selected, deterministic shadow decisions, premarket/reddit/earnings/insider/regime/trend details, and source/path data may be lost unless they happen to map to an existing typed column.
- No G1B secret-redaction path for persisted full context exists because no full-context persistence exists.

### Finding 2 — Candidate outcome tracking is not implemented

**Severity: High / blocking**

Evidence reviewed:

- I found no `paper_candidate_outcomes` table or equivalent outcome table.
- I found no outcome resolver module or loop.
- I found no implementation for 5, 10, 15, 30, and 60 minute outcome horizons.
- I found no fields for future return, hit-target, hit-stop, status, source, error, or `resolved_at`.

Impact:

- The app cannot validate post-candidate behavior during a freeze.
- There is no rate-safe/capped resolver behavior to review.
- Missing data handling for candidate outcomes is absent.

### Finding 3 — Three independent fake wallets are not implemented

**Severity: High / blocking**

Evidence reviewed:

- `PaperAccount` has one cash balance, one positions dictionary, and one closed-trades list.
- `Position` and `ClosedTrade` models do not include `wallet_id` or `strategy_id`.
- `paper_trades_journal` does not define `wallet_id` or `strategy_id`; only `position_id` is added by migration.
- Simulator entry/exit code still calls the single `_account.enter_position(...)` and `_account.exit_position(...)` paths.

Impact:

- There is no independent `ENGINE`, `DETERMINISTIC_SHADOW`, or `AI_SHADOW` wallet accounting.
- Deterministic shadow cannot open isolated fake positions independently from ENGINE.
- AI shadow cannot be shown inactive as an independent wallet when LLM is disabled, nor can it be tested as opening mocked `WOULD_ENTER` trades independently.
- Trades and positions cannot be separated by wallet or strategy in persistence/API/dashboard outputs.

### Finding 4 — Existing ENGINE behavior appears preserved, but only because G1B behavior is absent

**Severity: Medium**

I did not find G1B changes to thresholds, entry logic, or exit logic in the current repository state. The paper settings still show the existing score threshold and TP/SL/max-hold settings. The simulator comments state that LLM output does not modify `eligible`, `action`, or `entry_mode`.

This is positive for preservation, but it is not evidence of a correct G1B implementation because the requested wallet/outcome/context features were not added.

### Finding 5 — AI/LLM remains disabled by default; cloud providers are not introduced as default calls

**Severity: Low / informational**

Evidence reviewed:

- `LLM_SHADOW_ENABLED` defaults to `False`.
- Default provider is local `ollama`, but disabled by default.
- The simulator populates LLM default fields and calls the analyzer only if `simulator_ready()` reports ready.

Caveat:

- There is no independent `AI_SHADOW` wallet to inspect as inactive. The AI disabled behavior is therefore partially satisfied at the LLM layer, but not at the G1B wallet layer.

### Finding 6 — Dashboard/API freeze visibility is incomplete for G1B

**Severity: High / blocking**

Current APIs can inspect existing journal tables and paper status, but I found no new G1B API/dashboard visibility for:

- wallet summary/PnL by `ENGINE`, `DETERMINISTIC_SHADOW`, `AI_SHADOW`;
- open/closed positions by wallet;
- candidate context audit completeness;
- outcome resolver status.

Impact:

- Even if DB-only data existed, freeze validation would be difficult; in the current state, the key DB data does not exist either.

### Finding 7 — Database/migration safety is safe but incomplete

**Severity: High for completeness; Low for destructive-risk**

Evidence reviewed:

- Existing DDL is idempotent (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
- I did not see destructive resets in the reviewed paper journal schema.
- Existing rows remain compatible with current typed-column migrations.

Missing for G1B:

- No `extras_json` migration.
- No outcome table/indexes.
- No wallet/strategy columns on persisted positions/trades.
- No bounded JSON-size strategy for full context persistence.

### Finding 8 — Tests do not cover G1B scope

**Severity: High / blocking**

I found tests for earlier G1A/G1A-H1 LLM-provider behavior, but no G1B tests covering:

- full context persistence / `extras_json`;
- secret redaction before context persistence;
- candidate outcome row creation and resolver behavior;
- missing-data outcome statuses;
- capped resolver behavior;
- independent ENGINE / DETERMINISTIC_SHADOW / AI_SHADOW wallets;
- wallet isolation by `wallet_id` / `strategy_id`;
- AI_SHADOW inactive when AI disabled;
- AI_SHADOW mocked `WOULD_ENTER` behavior.

### Finding 9 — Runtime evidence is not available in-repo for G1B

**Severity: Medium**

I did not find a G1B runtime verification artifact demonstrating:

- candidates persisted with full context;
- outcome rows created;
- wallets exist;
- ENGINE still works;
- deterministic shadow wallet exists;
- AI wallet inactive when AI disabled;
- no paid AI calls;
- backend health OK.

### Finding 10 — Safety check: no G1B broker/live/order implementation found

**Severity: Low / positive**

I searched for broker/live/order-related terms. The repository contains many historical safety comments/tests and existing API status fields such as `broker_connected`, but I did not find evidence that G1B adds broker integration, live trading, real orders, real-money execution, Alpaca, IBKR, Robinhood, or comparable broker code.

## 3. Evidence

Key code evidence:

- `paper_candidates` schema has fixed typed fields and no `extras_json` context column.
- The candidate journal insert persists selected typed fields only.
- `paper_trades_journal` schema has no `wallet_id` or `strategy_id` columns.
- `PaperAccount` is a single-account model with one cash balance, one positions dictionary, and one trade list.
- `Position` and `ClosedTrade` models have no wallet/strategy identifiers.
- `LLM_SHADOW_ENABLED` defaults to `False`.
- Simulator LLM comments state LLM output does not modify engine eligibility/action/entry mode.

Search evidence:

- Repository search for `extras_json`, `candidate_outcomes`, and `paper_candidate_outcomes` did not find G1B implementation code.
- Repository search for `wallet_id`, `strategy_id`, `DETERMINISTIC_SHADOW`, and `AI_SHADOW` did not find G1B wallet implementation code.
- Repository search for broker/live/order terms did not reveal new G1B real-money execution paths.

## 4. Tests reviewed

Reviewed test files and coverage by search:

- `backend/tests/test_phase_g1a.py`
- `backend/tests/test_phase_g1a_h1.py`
- existing paper/journal/safety tests discovered by repository search

I did not find G1B-specific tests for the required persistence, outcome, and wallet behaviors.

## 5. Runtime evidence reviewed

No G1B runtime verification artifact was available in the repository. I did not run the backend as a service because the requested work is a code review with no application-code changes, and the repository does not contain the G1B implementation needed to generate meaningful runtime proof for the requested features.

## 6. Freeze-readiness judgment

**Not freeze-ready.**

The current repository state cannot support a two-week fake-money freeze audit for G1B because it lacks the three core prerequisites:

1. full candidate context persistence;
2. outcome tracking at required horizons;
3. independent ENGINE / DETERMINISTIC_SHADOW / AI_SHADOW fake wallets.

The safest approval status is **FAIL** until these are implemented and tested.

## 7. Required follow-up patches

Before re-review, implement and test at least the following:

1. Add full candidate runtime context persistence:
   - add `paper_candidates.extras_json` or equivalent;
   - persist engine, deterministic shadow, AI/LLM, marketdata, news/catalyst, reddit, premarket/full-market mover, earnings, insider, regime, trend, path/source, and runtime config/config-version data when available;
   - redact API keys/secrets/tokens before persistence;
   - bound JSON size and handle old rows with null context safely.

2. Add candidate outcome tracking:
   - create an idempotent outcome table for 5/10/15/30/60 minute horizons;
   - implement a capped/rate-safe resolver that does not block the paper tick loop;
   - avoid replaying thousands of symbols;
   - honestly mark missing data;
   - store future return, hit-target/hit-stop fields, status, source, error, and `resolved_at`.

3. Add three independent fake wallets:
   - `ENGINE`, `DETERMINISTIC_SHADOW`, `AI_SHADOW`;
   - same starting capital or clearly documented baseline;
   - persist `wallet_id` and/or `strategy_id` on positions/trades;
   - isolate wallet positions/trades;
   - allow deterministic shadow fake entries independently from ENGINE;
   - keep AI_SHADOW inactive while AI/LLM is disabled;
   - support mocked AI `WOULD_ENTER` entries in tests;
   - apply TP/SL/max-hold/exit rules consistently unless explicitly documented otherwise.

4. Preserve ENGINE behavior:
   - add regression tests proving no scoring threshold, entry, exit, TP/SL, eligibility, action, or entry-mode changes from shadow/AI outputs.

5. Expose freeze validation data:
   - wallet summary/PnL;
   - open and closed positions by wallet;
   - candidate context audit completeness;
   - outcome resolver status.

6. Add tests covering every G1B acceptance criterion listed in the review request.
