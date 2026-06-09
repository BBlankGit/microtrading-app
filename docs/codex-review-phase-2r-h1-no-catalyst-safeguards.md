# Codex Review — Phase 2R-H1 No-Catalyst Momentum Safeguards

Review scope: latest Phase 2R-H1 patch only (`HEAD`, commit `3c35012 Harden no-catalyst momentum entry safeguards`).

## Executive verdict

Phase 2R-H1 is safe to enable conservatively during fake-money monitoring, subject to the existing operational assumptions that paper trading remains fake-money only and runtime overrides are changed deliberately.

I found no code changes that add broker execution, live trading, real order placement, AI/LLM integrations, Ollama, OpenAI calls, Anthropic calls, or LangChain usage. The no-catalyst path remains disabled by default, the new defaults are intentionally stricter than the standard catalyst/global gates, stale marketdata now blocks Path C before no-catalyst evaluation/entry, and the catalyst path and bearish/strong-bearish protections remain intact.

## Review checklist

| # | Focus area | Result | Evidence |
|---|---|---|---|
| 1 | Stale marketdata blocks no-catalyst entries before Path C | Pass | The stale-data guard runs before no-catalyst evaluation, sets `hard_rejection = "stale_marketdata_entry_blocked"`, and resets `is_no_catalyst_rejection = False`, which prevents `nc_eval` and Path C from firing. |
| 2 | No-catalyst defaults are stricter than standard catalyst/global gates | Pass | Defaults are stricter or intentionally blocking: min score `80` vs standard entry threshold `70`, no-catalyst min volume ratio `1.5` vs global volume hard gate `0.8`, max spread `0.20%` vs shared hard gate `0.50%`, risk-on required, and min momentum component `25` exceeds the current component maximum documented by tests. |
| 3 | No-catalyst remains disabled by default | Pass | `PAPER_NO_CATALYST_ENTRY_ENABLED` remains `False`. |
| 4 | Catalyst path remains unchanged | Pass | Path A is still selected only when no hard rejection exists and the catalyst score passes; it still enters with `entry_mode="catalyst"`. The H1 test covers no-catalyst-enabled Path A regression. |
| 5 | Bearish/strong bearish catalyst protection remains intact | Pass | Shared hard rejection for strong bearish catalyst still precedes no-catalyst evaluation. The no-catalyst evaluator still has an additional bearish-catalyst block when enabled. |
| 6 | Journal candidate output persists/returns `entry_mode` and no-catalyst blocker fields | Pass | DB migration adds no-catalyst audit columns, journal persistence writes them, and the candidates API returns them alongside `entry_mode`. |
| 7 | Tests avoid real Polygon calls | Pass | The simulator integration tests patch Polygon snapshot and previous-close calls with async mocks; no unmocked Polygon path is introduced by the H1 tests. |
| 8 | Marketdata cache-first behavior remains intact | Pass | The cache layer is still consulted first when enabled; fresh cache hits return before Polygon calls, and the default `PAPER_USE_MARKETDATA_CACHE` remains `True`. |
| 9 | No broker/live trading/real orders/AI/LLM/Ollama/OpenAI/Anthropic/LangChain added | Pass | The patch is limited to config defaults, paper simulator gating, paper journal/API audit fields, DB schema migration, and tests. No execution or AI integration code was added. |
| 10 | 2R-H1 safe to enable conservatively during fake-money monitoring | Pass | Conservative enablement is reasonable because the feature is still default-off, the new default momentum component gate blocks no-catalyst entries unless explicitly relaxed, stale data blocks Path C, daily limits/position sizing remain capped, and paper simulator constraints remain fake-money only. |

## Detailed findings

### 1. Stale marketdata now blocks Path C before no-catalyst entry

The simulator builds hard rejections before entry-path selection. For stale marketdata with `PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY=True`, the guard now unconditionally overwrites the rejection with `stale_marketdata_entry_blocked` and resets `is_no_catalyst_rejection` to `False`. Because `nc_eval` is only computed when `is_no_catalyst_rejection` is true, stale marketdata prevents both no-catalyst evaluation and Path C entry.

This addresses the prior hazard where a no-catalyst rejection reason could survive into Path C despite stale marketdata.

### 2. No-catalyst defaults are stricter than standard catalyst/global gates

The H1 defaults are conservative:

- no-catalyst entry flag: disabled by default;
- min total score: `80`, stricter than standard catalyst threshold `70`;
- min momentum component score: `25`, which the H1 tests document as higher than the current max component score of `20`;
- min change: `2.0%`;
- min volume ratio: `1.5`, stricter than the global hard gate default of `0.8`;
- max spread: `0.20%`, stricter than the simulator shared hard gate of `0.50%`;
- risk-on regime required by default;
- any bearish catalyst sentiment blocks no-catalyst evaluation by default;
- position size multiplier remains `0.5`; and
- no-catalyst daily cap remains `20`.

The practical outcome is that simply enabling `PAPER_NO_CATALYST_ENTRY_ENABLED=True` should still not open this path under default thresholds unless the runtime operator also relaxes the blocking momentum component gate.

### 3. No-catalyst remains default-off

`PAPER_NO_CATALYST_ENTRY_ENABLED` remains `False` in settings. The no-catalyst evaluator also immediately rejects when that effective value is false.

### 4. Catalyst path remains unchanged

Path A still has priority and remains governed by the existing `hard_rejection is None and scoring["score_pass"]` condition. When it enters, it uses the existing catalyst sizing path and records `entry_mode="catalyst"`. The no-catalyst branch is still an `elif` after Path A and requires `is_no_catalyst_rejection`, which true catalyst candidates do not set.

The added regression test exercises a normal accepted catalyst while no-catalyst mode is enabled and asserts the candidate/entry is not labeled `momentum_no_catalyst`.

### 5. Bearish and strong-bearish catalyst protections remain intact

The strong-bearish hard gate remains in the simulator's shared hard-safety gate section before no-catalyst evaluation. Separately, the no-catalyst evaluator still rejects bearish catalyst sentiment when `PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH` is enabled, which it is by default.

### 6. Journal candidate audit output now includes no-catalyst state

Phase 2R-H1 adds the five requested candidate audit columns:

- `catalyst_required`
- `no_catalyst_momentum_eligible`
- `no_catalyst_momentum_reasons_json`
- `no_catalyst_momentum_blockers_json`
- `no_catalyst_config_snapshot_json`

The simulator emits these fields on each candidate, journal persistence writes them, schema migration adds them idempotently with `ADD COLUMN IF NOT EXISTS`, and `GET /api/journal/candidates` selects them for API output. Existing `entry_mode` persistence/return remains present.

### 7. Tests avoid real Polygon calls

The H1 simulator tests patch `paper.simulator.polygon_client.get_ticker_snapshot` and `paper.simulator.polygon_client.get_previous_close` with `AsyncMock`, and also patch market quality evaluation, universe discovery, news collection, journal persistence, cached universe, and state save. This keeps tests deterministic and avoids real Polygon traffic.

### 8. Marketdata cache-first behavior remains intact

When `PAPER_USE_MARKETDATA_CACHE` is true, the simulator still calls `try_cache_for_quality` before any Polygon path. A fresh cached quality result immediately populates the quality map and returns, skipping Polygon. H1 also preserves the cache-first default of `PAPER_USE_MARKETDATA_CACHE=True`.

### 9. No prohibited integrations or execution paths added

The latest patch changes only:

- settings defaults;
- simulator guard ordering/flags;
- paper journal persistence and candidate API output;
- paper DB schema migration; and
- tests.

No broker modules, live-trading toggles, real order submission code, or AI/LLM framework integrations were added by the H1 patch.

## Test result

Command run:

```bash
pytest backend/tests/test_phase_2r.py -q
```

Result: `41 passed, 1 warning in 0.43s`.

The warning is a pre-existing FastAPI/Starlette deprecation warning from `fastapi.testclient`, not a Phase 2R-H1 failure.

## Recommendation

Approve Phase 2R-H1 for conservative fake-money monitoring. If enabling no-catalyst mode for observation, keep the default blocking thresholds initially, then only relax `PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE` and related gates through documented runtime overrides after reviewing journaled candidate blockers and stale-marketdata behavior.
