# Codex Review — Phase 2U Paper Redis State Integrity and Test Isolation

Date: 2026-06-10

Scope requested: review only the latest Phase 2U patch in `BBlankGit/microtrading-app`; do not change code.

Repository state reviewed: current `work` branch at `0e9f230` (`Merge pull request #50 from BBlankGit/codex/review-phase-2t-catalyst-performance-guard`). I did not find a Phase 2U implementation patch in the local branch history; the latest checked-in change is a Phase 2T review document. Because the requested Phase 2U patch is not present in this checkout, this review evaluates the current paper Redis/session-restore implementation against the Phase 2U requirements and treats missing controls as blockers.

## Verdict

**Not safe to approve as Phase 2U.** The current implementation still trusts the legacy `paper:state` Redis key for same-day restores, writes Redis before journal persistence, has no production/test Redis namespace separation, and does not validate Redis positions against persisted journal entry rows or non-null `entry_mode` before applying them.

The system remains bounded to fake-money monitoring only in the sense that it still exposes no broker/live-order path, but Phase 2U's state-integrity goals are not satisfied. A stale or manually written Redis `paper:state` value can still resurrect fake open positions that the journal never recorded.

## Phase 2U checklist

| # | Requirement | Result | Evidence / notes |
|---|---|---:|---|
| 1 | Tests/developer code can no longer write to production paper Redis state. | **Fail** | `make_redis()` always uses the configured `settings.REDIS_URL`; there is no paper-state-specific guard, test namespace, production refusal, or caller identity check. `backend/tests/conftest.py` only patches startup restore and the market-data collector for the `client` fixture; it does not globally prevent direct `_save_state()`/`make_redis()` writes in tests. |
| 2 | Redis paper state uses a safe namespace. | **Fail** | Both simulator save and session restore use `_REDIS_KEY = "paper:state"`. This is a global legacy key, not a safe environment/test/app namespace. |
| 3 | Restore skips Redis positions without matching journal entry rows. | **Fail** | Redis restore returns the snapshot after only a NY-date check, and `restore_paper_session()` applies every `snap["positions"]` entry directly into `_account.positions`. There is no journal lookup for `position_id` or matching entry row before accepting Redis positions. |
| 4 | Restore skips positions with null/missing `entry_mode`. | **Fail** | `Position.entry_mode` is nullable in the model, Redis restore constructs `Position(**p)` without validating it, and DB restore copies `row["entry_mode"]` without filtering null/missing values. |
| 5 | Orphaned/skipped positions produce visible restore warnings. | **Partial / DB only** | DB restore emits warnings for null `position_id`, prior-day rows, and malformed rows, and exposes `restore_warnings` in simulator status. However, Redis restore has no orphan/entry-mode validation, so Redis-orphaned positions are accepted rather than skipped/warned. |
| 6 | Redis state is saved only after journal persistence, or snapshots are marked/audited so unjournaled state is refused. | **Fail** | `run_tick()` calls `_save_state()` before `_persist_journal_tick()`. The Redis snapshot has no journal success marker, tick id, audit marker, schema version, or journal position list that restore can verify. |
| 7 | Legacy `paper:state` is not blindly trusted. | **Fail** | `try_redis_restore()` still reads `paper:state` and trusts it when `daily_baseline_date == ny_today`. It performs no version, provenance, journal status, or per-position integrity checks. |
| 8 | Clearing paper simulator state does not clear marketdata cache/runtime config/journal DB. | **Pass** | `reset_simulator()` resets in-memory paper fields and then overwrites the paper snapshot via `_save_state()`. I found no Redis flush/delete, marketdata-cache clear, runtime-config delete, or journal-table delete in that path. |
| 9 | Strategy/catalyst/no-catalyst logic was not changed. | **No Phase 2U delta found** | The current entry logic remains the existing catalyst path plus momentum/no-catalyst fallbacks. Because no Phase 2U patch exists in this checkout, I cannot confirm an intended Phase 2U diff; I found no state-integrity-specific strategy edits. |
| 10 | Marketdata cache logic was not changed. | **No Phase 2U delta found** | The current marketdata cache code remains under `market:*` keys and the simulator cache adapter still only reads market-quality data. No Phase 2U marketdata-cache changes were present in this checkout. |
| 11 | No broker/live trading/real orders/AI/LLM/Ollama were added. | **Pass** | Current status/disclaimer paths still report `live_trading_enabled: False` and `broker_connected: False`, simulator code remains fake-money, and the reviewed Redis/session-restore code does not add broker, order, AI, LLM, or Ollama calls. |
| 12 | Phase 2U is safe for fake-money monitoring. | **Fail for state integrity** | The app remains fake-money only, but fake-money monitoring after restart can still be misleading because Redis can restore unjournaled/orphaned positions. Phase 2U should not be considered safe until Redis restore is journal-verifiable or disabled/refused for legacy snapshots. |

## Detailed findings

### 1. Production/test Redis isolation is still missing

`backend/data/redis_client.py` exposes a generic `make_redis()` that creates a client from `settings.REDIS_URL`. There is no helper dedicated to paper simulator state, no namespace derivation from environment/app instance, and no test-mode refusal for production URLs.

`backend/tests/conftest.py` reduces startup side effects for the `client` fixture by patching `paper.simulator.restore_paper_session` and `marketdata.service.start_collector`. That helps API tests avoid startup restore/live Polygon collection, but it does not stop tests or developer scripts from importing `paper.simulator._save_state()` or `paper.session_restore.make_redis()` and writing/reading the same production `paper:state` key if `REDIS_URL` points there.

**Impact:** a local or CI test that uses a production-like `REDIS_URL` can still overwrite the production fake-money Redis snapshot.

**Expected Phase 2U direction:** create an explicit paper-state key builder/client that refuses production paper-state writes unless the process is in an approved runtime, and force tests to use an isolated namespace such as `paper:test:<run_id>:state` or a fake Redis object.

### 2. Redis paper state is still the legacy global key

The simulator defines `_REDIS_KEY = "paper:state"`, and session restore defines the same key. That key is unqualified by environment, deployment, repository, app instance, branch, test run, or schema version.

Marketdata cache keys are at least separate (`market:snapshot:*`, `market:symbols:active`, `market:metrics`, `market:health`), so paper reset is not colliding with the marketdata cache. But the paper state key itself is not Phase 2U-safe.

**Impact:** old deployments, local developer runs, tests, and production fake-money monitoring can all address the same paper snapshot if pointed at the same Redis.

### 3. Redis restore accepts orphaned positions without journal proof

`try_redis_restore()` reads Redis, parses JSON, checks `daily_baseline_date`, and returns the snapshot. The apply path in `restore_paper_session()` then constructs `Position(**p)` for every Redis position.

There is no query to `paper_trades_journal` to require a matching `event='entry'` row for the Redis `position_id`, no check that the entry is not closed by an exit row, and no warning for positions that fail those checks. In contrast, the DB fallback restore does use `position_id IS NOT NULL` and excludes positions with exit rows, but that safer DB logic is bypassed whenever Redis returns any same-day snapshot.

**Impact:** a Redis-only position can become an active fake-money position after restart even if the durable journal has no corresponding entry.

### 4. Null/missing `entry_mode` is still accepted

`Position.entry_mode` is declared as `str | None = None`. Redis restore applies position dictionaries directly, and DB restore assigns `entry_mode=row["entry_mode"]` to `Position` without rejecting nulls.

**Impact:** old or malformed positions can be restored without a valid strategy lineage (`catalyst`, `momentum`, or `momentum_no_catalyst`). That weakens restored daily counts and monitoring by entry mode.

**Expected Phase 2U direction:** reject open positions where `entry_mode` is missing/null/not in the known modes, add a visible restore warning, and ensure Redis restore follows the same rule as DB restore.

### 5. Restore warnings exist for DB skips, but not Redis integrity skips

The DB path records warnings for:

- open entry rows with `position_id IS NULL`,
- prior-day open entries excluded from same-day restore,
- malformed open rows.

Those warnings are propagated through `restore_session()` and then exposed by `get_status()` as `restore_warning` and `restore_warnings`.

However, Redis restore has no skip logic and therefore no warning path for orphaned Redis positions, positions lacking `entry_mode`, legacy schema snapshots, or unjournaled snapshots.

**Impact:** operators can see DB restore warnings, but not the higher-risk Redis restore trust problems.

### 6. Redis save happens before journal persistence

At the end of a tick, `run_tick()` calls `_save_state()` first, then attempts `_persist_journal_tick()`. If Redis succeeds but the journal write fails or is skipped, Redis now contains state that restore will prefer over DB on the next startup.

The snapshot itself contains account cash, positions, trades, daily counters, dates, and last prices. It does not contain a journal write success marker, journal tick id, schema version, snapshot provenance, `journal_ok`, or any audit hash/checksum tying the Redis snapshot to durable journal rows.

**Impact:** the exact failure mode Phase 2U is meant to prevent is still possible: Redis can preserve unjournaled fake positions and later restore them as authoritative.

**Expected Phase 2U direction:** either persist journal first and save Redis only after a confirmed journal write, or tag Redis snapshots with journal/audit metadata and refuse any snapshot that cannot be verified against the journal.

### 7. Legacy `paper:state` remains trusted by default

The only Redis restore validity check is same-day `daily_baseline_date`. That means a legacy snapshot from before Phase 2U, or a manually crafted same-day snapshot, can still restore.

**Expected Phase 2U direction:** treat legacy `paper:state` as untrusted by default. Options include refusing it entirely, migrating it only after full journal validation, or using a new versioned key such as `paper:sim:<env>:state:v2` with required integrity fields.

### 8. Reset/clear behavior appears scoped to paper state

`reset_simulator()` stops the simulator, resets in-memory account fields, reset restore metadata, and calls `_save_state()`. I did not find a Redis `flush*`, broad `delete`, marketdata cache clear, runtime-config reset, or journal DB truncation/delete in that reset path.

This is one item that currently looks acceptable: clearing/resetting the paper simulator should not wipe marketdata cache, runtime config, or the journal DB. The caveat is that reset still writes the unsafe legacy `paper:state` snapshot.

### 9. Strategy, catalyst, no-catalyst, and marketdata cache logic

No Phase 2U patch was present in this checkout, so there was no Phase 2U diff to inspect for strategy changes. In the current tree:

- catalyst entries still use the existing `score_pass` path and set `entry_mode="catalyst"`,
- no-catalyst momentum entries still use `entry_mode="momentum_no_catalyst"`,
- momentum fallback entries still use `entry_mode="momentum"`,
- marketdata cache integration still reads through `paper.marketdata_adapter.try_cache_for_quality()` and uses marketdata cache keys under `market:*`.

I did not find Redis state-integrity changes that alter those decision paths.

### 10. Broker/live trading/AI/LLM boundary

The reviewed Redis/session-restore paths do not add broker clients, real order placement, live trading, AI, LLM, or Ollama calls. The simulator and API status continue to state fake-money/no-broker/no-live-order behavior.

This satisfies the execution-safety boundary, but it does not satisfy state-integrity safety for fake-money monitoring.

## Required fixes before Phase 2U approval

1. Replace or quarantine `paper:state` with a versioned, environment-scoped paper-state namespace.
2. Add a paper Redis client/key helper that prevents tests/developer runs from writing production paper state.
3. Save Redis only after journal persistence succeeds, or include auditable journal markers and refuse unjournaled snapshots.
4. Make Redis restore validate every open position against journal entry rows by `position_id` and ensure there is no matching exit row.
5. Skip and warn on Redis/DB positions with null, missing, or unknown `entry_mode`.
6. Surface Redis restore skip counts/warnings in `restore_warning`, `restore_warnings`, logs, and `/api/paper/status`.
7. Refuse legacy `paper:state` snapshots unless they pass a strict migration/verification path.
8. Add tests covering production Redis write refusal, isolated test namespace, Redis orphan rejection, missing `entry_mode` rejection, unjournaled snapshot refusal, legacy key refusal, and reset scoping.

## Commands run

```bash
git status --short
git branch -vv
git log --oneline --decorate --graph -20
rg -n "Phase 2U|phase_2u|safe namespace|journal|entry_mode|paper:state|restore_warnings|missing journal|entry row|marketdata cache|Ollama|broker|live trading" backend/tests backend/paper backend/api docs README.md .env.example --glob '!*.pyc'
rg -n "flush|delete\(|unlink|DEL |paper:state|runtime_config|journal|reset_simulator|clear" backend -S
rg -n "alpaca|ibkr|broker|order|execution|live_trading|ollama|openai|llm|anthropic|chat|agent" backend README.md .env.example -S
PYTHONPATH=backend pytest -q backend/tests/test_phase_2s.py backend/tests/test_phase_2s_h1.py backend/tests/test_phase_2s_h2.py
```

Targeted restore tests passed: `59 passed, 1 warning in 0.44s`. These tests validate existing Phase 2S restore behavior, not the missing Phase 2U integrity requirements above.
