# Codex Review: Phase G1B Freeze Persistence, Outcomes, Wallets

**Reviewed implementation:** `27a0193 Add freeze persistence, outcomes, and parallel fake wallets`  
**Scope:** latest G1B implementation from Claude only  
**Verdict:** **YELLOW / NEEDS FOLLOW-UP**

## 1. Executive summary

G1B adds the three major freeze-prep structures requested: a bounded `paper_candidates.extras_json` snapshot, a `paper_candidate_outcomes` table with five forward-return horizons, and two additional independent fake wallets for deterministic and AI shadow strategies. The implementation remains paper/fake-money only and I did not find new broker/live-order integration in the G1B diff.

However, I would not mark this fully freeze-ready yet. The outcome resolver is intentionally capped and non-provider-calling, but it does not persist a `source` field, does not populate the schema's max-high/max-low return columns, and uses only the current cached price at resolver time rather than horizon-specific or interval history. Dashboard/API visibility exists for wallet and aggregate persistence status, but not enough to inspect candidate `extras_json`, outcome rows, or wallet-specific open/closed trade history through the API/dashboard. Test coverage is useful but mostly unit/static inspection; it does not prove actual persisted candidate rows, outcome rows, or wallet journal rows against a database.

## 2. Findings

### Candidate context persistence

**Status: Mostly pass, with caveats.**

* The migration adds `extras_json JSONB` to `paper_candidates`, and `persist_tick_result` writes `_sanitize_extras_json(c)` as the final candidate insert parameter. This is the expected storage location for full runtime context.
* The sanitizer snapshots the full candidate dictionary after dropping only known bulky raw keys, serializes with `default=str`, redacts secrets through the LLM redaction helper, and bounds payloads to 32 KB with a small truncation envelope.
* This should capture engine fields, rejection/decision reasons, deterministic shadow fields, LLM fields, market-data fields, news/reddit/premarket/earnings/insider/regime/trend/path/config fields **if those fields are present in the runtime candidate dict**.
* Caveat: the implementation is opportunistic rather than schema-verified. There is no test fixture proving the full expected field families are present in a realistic candidate row after a real tick.
* Caveat: if `extras_json` exceeds the byte cap, the fallback envelope preserves only a small subset of fields, so a large candidate can lose much of the requested full context. This is reasonable for write safety but should be monitored during freeze.

### Outcome tracking

**Status: Needs follow-up.**

* The migration creates `paper_candidate_outcomes` with candidate linkage, symbol, horizon, reference/future prices, future return, hit flags, status, error, and `resolved_at`.
* Candidate persistence queues one row per persisted candidate for 5, 10, 15, 30, and 60 minutes.
* The resolver caps each run at `_MAX_PER_RUN = 200` regardless of a larger API request, only selects elapsed pending rows, reads from the existing market-data cache, and marks missing prices or invalid references as `missing_data`.
* The resolver is not called in the paper tick loop in the G1B patch; it is exposed via an admin endpoint, so it should not block tick execution.
* Follow-up required: there is no `source` column/field in the outcome table even though the spec asked for source.
* Follow-up required: the schema includes `max_high_return_percent` and `max_low_return_percent`, but the resolver never writes those values.
* Follow-up recommended: the resolver uses a single cached price at resolution time, not a historical bar/quote for the exact horizon or an interval high/low. This may be acceptable for a first fake-money freeze pass, but the limitation should be documented in runtime evidence and dashboard wording.

### Three fake wallets

**Status: Mostly pass, with visibility caveats.**

* Config adds `PAPER_SHADOW_WALLETS_ENABLED = False` by default and documents the deterministic and AI shadow wallets as independent, fake-money ledgers that use the same starting capital, sizing, TP/SL, and max-hold settings as the engine.
* `shadow_wallets.py` creates two module-scope `PaperAccount` instances, both starting with `settings.PAPER_STARTING_CASH`.
* Deterministic shadow entries are driven by `enhanced_shadow_decision == "WOULD_ENTER"`; AI shadow entries are gated by both `LLM_SHADOW_ENABLED` and `llm_decision == "WOULD_ENTER"`.
* Entry gating consults only the relevant shadow account, so an ENGINE position does not block a DETERMINISTIC_SHADOW or AI_SHADOW position in the same symbol.
* Exits reuse `evaluate_virtual_bracket_exit` with the same TP/SL/max-hold config accessors used by the engine-style virtual account path.
* Journal writes tag engine entries/exits with default `wallet_id`/`strategy_id` of `engine`, and shadow entries/exits retain their own wallet/strategy IDs.
* Caveat: `/api/paper/wallets` exposes status snapshots only. Existing `/api/paper/positions` and `/api/paper/trades` still expose only the engine account, so wallet-specific open/closed position history is not clearly inspectable from API/dashboard without querying the database.

### Engine behavior preservation

**Status: Pass based on diff review.**

* The shadow wallet layer runs after the existing LLM/shadow telemetry layer and is explicitly gated by `PAPER_SHADOW_WALLETS_ENABLED`.
* It writes only `shadow_entries`, `shadow_exits`, and `shadow_wallets_snapshot` into the tick result and does not mutate the engine account.
* I did not identify G1B changes to scoring thresholds, engine eligibility, engine action/entry-mode decisions, engine TP/SL values, or engine entry/exit calls.

### AI/LLM disabled behavior

**Status: Pass.**

* `LLM_SHADOW_ENABLED` remains default `False`.
* AI shadow positions are not processed unless `_llm_enabled()` returns true.
* The G1B diff does not add OpenAI, DeepSeek, Groq, Mistral, Gemini, or Ollama calls. The only OpenAI-looking string in the diff is a fake key used by the redaction unit test.

### Dashboard/API visibility

**Status: Partial.**

* New endpoints expose aggregate persistence status and an admin outcome-resolver trigger.
* `/api/paper/wallets` exposes engine, deterministic shadow, and AI shadow wallet snapshots.
* Follow-up recommended: add API/dashboard visibility for recent candidates with `extras_json` audit status, recent outcome rows/resolver counts by horizon/status, open positions by wallet, and closed trades by wallet. Today, much of the freeze validation data exists only in Postgres or module memory.

### Database/migration safety

**Status: Mostly pass, with caveats.**

* The migration is additive: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`, and indexes. No destructive table reset was found.
* Existing candidate rows remain valid because `extras_json` is nullable. Existing trade rows remain valid because `wallet_id` and `strategy_id` are nullable.
* Outcome rows use a unique `(candidate_id, horizon_minutes)` constraint, cascade-delete with candidate rows, and indexes for status/symbol/tick/pending-created-at.
* JSON size is bounded in application code at 32 KB, but there is no DB-level check constraint enforcing the bound.

### Safety check

**Status: Pass.**

* The G1B diff contains no new broker SDK imports, live-trading path, order placement functions, or real-money execution integration. Matches in the safety search were safety disclaimers or the fake OpenAI redaction-test string only.

## 3. Evidence

* `paper_candidates.extras_json` is added as an additive JSONB column, and `paper_candidate_outcomes` is created with the requested core outcome fields and indexes. `paper_trades_journal` also receives `wallet_id` and `strategy_id`. `backend/paper/db.py:147-193`
* Candidate inserts now include `extras_json`, and the journal queues five pending outcome rows per inserted candidate at 5/10/15/30/60 minutes. `backend/paper/journal.py:146-255`
* The sanitizer serializes the full candidate dict, drops known bulky raw payload keys, redacts the encoded JSON, and truncates oversized payloads to an envelope. `backend/paper/journal.py:429-480`
* The resolver caps `max_rows`, selects only elapsed pending rows, marks missing data honestly, and writes resolved future price/return/hit flags. `backend/paper/outcome_resolver.py:78-166`
* Shadow wallets are independent `PaperAccount` ledgers starting from `PAPER_STARTING_CASH`. `backend/paper/shadow_wallets.py:47-57`
* Shadow entries use per-wallet `can_enter`, which intentionally does not consult the engine account, and write wallet/strategy metadata into entry dicts. `backend/paper/shadow_wallets.py:173-223`
* AI wallet processing is gated by `_llm_enabled()` for both exits and entries. `backend/paper/shadow_wallets.py:244-263`
* The simulator invokes the shadow-wallet layer after normal candidate/LLM processing, gated by `PAPER_SHADOW_WALLETS_ENABLED`, and stores only shadow result fields. `backend/paper/simulator.py:1945-1966`
* `/api/audit/outcomes/resolve` and `/api/audit/persistence/status` are present; the resolver endpoint is admin-protected. `backend/api/audit.py:23-34`
* `/api/paper/wallets` exposes wallet snapshots, but not wallet-specific open/closed trade lists. `backend/api/paper.py:27-45`
* Shadow wallets are off by default, and LLM shadow remains disabled by default. `backend/core/config.py:28-34`, `backend/core/config.py:122-128`

## 4. Tests reviewed

The new test module covers sanitizer serialization, secret redaction, truncation, bulky-key dropping, outcome hit math, resolver cap sanity, audit route presence/admin protection, shadow-wallet disabled behavior, deterministic shadow entry, AI disabled behavior, AI mocked entry when enabled, engine-position independence, starting cash parity, wallet route presence, and static migration/journal checks. `backend/tests/test_phase_g1b.py:1-334`

Coverage gaps:

* No database-backed test proves that a persisted candidate row contains a realistic full `extras_json` context.
* No database-backed test proves five outcome rows are actually inserted for a candidate.
* No mocked resolver test exercises `resolve_pending` end-to-end against fake DB rows, including `missing_data` and cap behavior.
* No test proves `max_high_return_percent`, `max_low_return_percent`, or outcome `source` behavior; source is not implemented.
* No dashboard/API test verifies freeze-inspection views beyond route presence.

## 5. Runtime evidence reviewed

I found no committed runtime verification artifact proving a live/backend run with:

* candidates persisted with full context;
* outcome rows created and resolved;
* wallets visible with engine still working;
* deterministic shadow wallet active;
* AI wallet inactive while LLM disabled;
* no paid AI calls;
* backend health OK.

The available evidence is code review plus unit/static tests. Before the 2-week freeze, run a short paper-simulation soak with Postgres and Redis enabled and archive API/SQL outputs for candidate extras coverage, outcome counts by horizon/status, wallet snapshots, and no-LLM/no-broker safety state.

## 6. Freeze-readiness judgment

**YELLOW / NEEDS FOLLOW-UP.**

G1B is directionally correct and safe from a fake-money boundary perspective, but it is not yet strong enough for an unattended freeze without follow-up. The largest blockers are outcome fidelity/fields (`source`, high/low returns) and inspectability of freeze evidence through API/dashboard. Candidate full-context persistence is likely adequate when runtime fields are present, but should be verified with real tick evidence and sampled `extras_json` rows before the freeze starts.

## 7. Required follow-up patches

1. Add an outcome `source` field and populate it with the resolver source, e.g. `marketdata_cache`, `missing_cache`, or explicit error source.
2. Either populate `max_high_return_percent` and `max_low_return_percent` from interval data, or remove/rename/document those columns as unavailable for this freeze.
3. Add API/dashboard endpoints for wallet-specific open positions and closed trades, including `wallet_id`/`strategy_id` filters.
4. Add API/dashboard visibility for recent candidate persistence audit status and recent outcome rows/counts by horizon/status.
5. Add DB-backed tests or realistic integration tests for candidate `extras_json`, five outcome rows per candidate, resolver `missing_data`, resolver cap behavior, and wallet journal isolation.
6. Add a runtime verification artifact before freeze start showing candidate extras coverage, outcome creation/resolution, all wallets, ENGINE unchanged, AI inactive with LLM disabled, no paid AI calls, and backend health OK.
