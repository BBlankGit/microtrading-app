# G0 — Microtrading Freeze-Readiness Audit

**Audit date:** 2026-06-12
**Auditor:** automated G0 audit run (read-only; no application changes)
**Target:** 2-week data-collection freeze period
**Repo HEAD:** main @ 1f328a1 (post UI-L2)

---

## 1. Executive summary

**Classification: 🟡 YELLOW — safe to run, with material data-completeness caveats.**

The trading control surface is healthy and behaving correctly. The engine never
places real orders, all consumer-facing dashboard values match runtime values
for the fields that are persisted, and restart-persistence works end-to-end
(today's restore picked up 99 closed trades, $-4.58 realized PnL, restart_persistent=true).

The blocking concerns are **not** safety-of-trading — they are
**data-completeness for the post-freeze analytical work the user intends to do**:

1. **Only ~19% of the runtime candidate fields land in the database.** Every
   tick now carries 151 fields per candidate; the `paper_candidates` schema
   has 39 columns. The 122 unpersisted fields include **every deterministic
   shadow output, every LLM shadow output, every earnings/insider/trend/
   market-mover/premarket/reddit field, and the catalyst block flags.**
   These will be invisible after the freeze.
2. **There is no outcome-resolution layer.** Nothing in the codebase records
   what happened to each candidate at +5m / +10m / +15m / +30m / +60m, no
   `hit_target` / `hit_stop` flags, no future-return columns. Without it the
   "Would the engine have been right?" analysis can't be answered by query —
   only by replay using the marketdata cache, which currently has 30-second
   TTL and no historical store.
3. **LLM has been spending 107,072 calls hitting OpenAI HTTP 401** since L1
   was enabled — the `OPENAI_API_KEY` in `.env` is the placeholder
   `optional_change_me` (length 19, prefix `optio…`, suffix `…e_me`),
   which slips through `is_configured()`'s denylist. No real LLM data is
   being collected at all. The shadow-only safety design has held — engine
   decisions are unaffected — but the 2-week freeze will produce zero
   LLM shadow rows.

Below the line, runtime overrides round-trip correctly, frontend matches
backend, 1×24h backend log has zero errors / exceptions / 429 / 403, and
disk-usage projection (≈ 1.8 GB over 14 days) is well within capacity.

---

## 2. Health status (Section A)

| Component | State | Notes |
|---|---|---|
| Backend | ✅ Up | `/health` 200, uvicorn responding |
| Frontend | ✅ Up | Next.js 200, x-nextjs-cache HIT |
| Postgres | ✅ Up | `microtrader/microtrading`, 6 tables, 465 MB |
| Redis | ✅ Up | 99 keys, marketdata snapshots + intel caches |
| Paper simulator | ✅ Running | restart_persistent=true, restore_source=redis |
| Marketdata collector | ✅ Up | 90 symbols, fresh, last cycle 2026-06-12T15:15Z |
| Market regime | ✅ active | risk_on, score 94, 10/10 ETFs |
| Market trend | ✅ active | snapshot_count=27, direction=improving, NOT collecting |
| Finnhub earnings | ✅ active | total_count=2 (next earnings windows narrow) |
| Finnhub insiders | ✅ active | total_count=825 (5-day window) |
| Polygon news | ✅ active | total_count=200, not stale |
| Reddit (ApeWisdom) | ✅ active | 100 tickers, age 217s |
| Full-market movers | ✅ active | full_universe, session=regular, 4015 valid movers |
| **LLM Shadow** | 🔴 **broken** | enabled+key_present TRUE but 107 072/107 072 calls = HTTP 401 |

`marketdata_cache.last_tick_stats` shows
`cache_hits=52, cache_misses=48, polygon_fallbacks=0, missing_marketdata=48`.
The collector fetches 90 symbols every cycle; the simulator's per-tick universe
is 52 — the 48 misses are symbols outside the collector set on this tick. Worth
keeping an eye on during the freeze (caveat #6 below).

---

## 3. Data-source status

| Source | Provider | Cache TTL | Provider status | Notes |
|---|---|---|---|---|
| Polygon snapshots | polygon | 30 s | `enabled=True`, `running=True` | base 9 + 36 v5 + paper-universe 50 = 90 sym |
| Polygon news | polygon | 300 s | `active` | I5-H1 cache-first; admin refresh required for new pulls |
| Finnhub earnings | finnhub | 7200 s | `active` | I6-H2 wired; only 2 rows currently (small upcoming window) |
| Finnhub insiders | finnhub | 1800 s | `active` | 825 rows, 5-day lookback, 50 sym cap |
| ApeWisdom (reddit) | apewisdom | 900 s | active, no key | works without key |
| ETF regime/trend | polygon | 60 s | active | 10 ETFs, M1 trend buffer 27 snaps |
| OpenAI LLM | openai | 300 s | **placeholder key — every call 401** | see executive summary |

---

## 4. Persistence map (Section D)

### 4.1 Postgres (5 data tables + audit)

| Table | Rows | Last write | Retention |
|---|---|---|---|
| `paper_candidates` | 585 235 | 2026-06-12 15:18 UTC | 14 d (auto_cleanup **OFF**) |
| `paper_ticks` | 11 512 | 2026-06-12 15:18 UTC | 14 d (auto_cleanup **OFF**) |
| `paper_trades_journal` | 1 027 | 2026-06-12 13:57 UTC | 14 d (auto_cleanup **OFF**) |
| `paper_universe_snapshots` | 11 510 | (per tick) | 14 d (auto_cleanup **OFF**) |
| `paper_runtime_config` | 12 | 2026-06-10 15:49 UTC | n/a |
| `paper_runtime_config_audit` | 61 | (per change) | n/a |

Daily volume (recent):
- 2026-06-12 (partial): 175 728 candidate rows
- 2026-06-11: 188 993
- 2026-06-10: 125 640
- 2026-06-09: 56 004
- 2026-06-08: 37 237

Disk: **465 MB now → projected ≈ 1.8 GB after 14 days** at ~180k rows/day.
`auto_cleanup_enabled=false` — nothing will be deleted during the freeze
(but `JOURNAL_RETENTION_DAYS=14` is the *policy* default and a future
cleanup pass would wipe data older than 14 days; not an active concern in
this window).

### 4.2 Redis (99 keys)

| Key pattern | Purpose | Persistence |
|---|---|---|
| `market:snapshot:<SYM>` | per-symbol marketdata cache | TTL 30 s |
| `market:metrics` | aggregate marketdata metrics | rolling |
| `catalysts:latest` | news collector cache | TTL 300 s |
| `intelligence:premarket:full_universe` | full-market movers | TTL 90 s |
| `intelligence:reddit:latest` / `:previous` | ApeWisdom snapshots | TTL 900 s |
| paper state (positions, journal handles) | restart-persistence | persistent |

### 4.3 Schema row-count mapping

| Logical concept | Stored where | Fields persisted | Fields not persisted |
|---|---|---|---|
| Engine candidate decision | `paper_candidates` | 39/151 = 26% of runtime | 122 fields lost — see §5 |
| Tick aggregate | `paper_ticks` | 17 cols | OK |
| Closed trade | `paper_trades_journal` | 19 cols | OK |
| Universe | `paper_universe_snapshots` | 9 cols | OK |
| Runtime overrides | `paper_runtime_config` (+audit) | full | OK |
| Marketdata history | Redis only, 30 s TTL | — | **no historical store** |
| LLM shadow output | nowhere | — | **transient only** |

---

## 5. Candidate decision storage status (Section E)

One tick run during this audit (`/tmp/g0_tick.json`):
- `symbols_evaluated`: 52
- `entries_made`: 0 / `exits_made`: 0
- `candidate_count`: 52
- Each candidate has **151 runtime fields**.

Coverage of dashboard/runtime fields by the persisted schema:

```
Runtime candidate fields : 151
Persisted columns        :  39
Coverage                 :  29/151 ≈ 19.2 %
```

The **122 fields not persisted** by category:

| Category | Count | Examples |
|---|---|---|
| Deterministic shadow | 9 | `enhanced_shadow_decision`, `enhanced_shadow_score`, `enhanced_shadow_components`, `enhanced_shadow_blockers`, `enhanced_shadow_confidence` |
| LLM shadow | 23 | `llm_decision`, `llm_confidence`, `llm_status`, `llm_primary_reason`, `llm_supporting_factors`, `llm_risk_factors`, `llm_model`, `llm_cached`, `llm_latency_ms`, … |
| Earnings/insider intelligence | 16 | `earnings_score_adjustment`, `insider_score_adjustment`, `intelligence_score_adjustment`, `base_score_before_intelligence_adjustments`, `earnings_days_until`, … |
| Market trend / regime | 21 | `market_trend_direction`, `market_trend_adjustment`, `market_regime_score_before/after_trend`, `market_trend_path_name`, `market_trend_regime_used`, … |
| Market mover entry | 17 | `market_mover_entry_eligible`, `market_mover_entry_reason`, `market_mover_regime_used`, … |
| Premarket / Reddit | 11 | `premarket_rank`, `premarket_gap_percent`, `reddit_rank`, `reddit_spike_ratio`, … |
| Catalyst flags | 9 | `catalyst_type_blocked`, `blocked_catalyst_type`, `catalyst_sentiment_reasons`, `catalyst_type_weight` |
| Marketdata metadata | 1 | `marketdata_fetched_at` |
| Other | 18 | `bullish_flags`, `bearish_flags`, `candidate_sources`, `daily_loss_guard_triggered`, `dollar_volume`, `momentum_gate_results`, `negative_reasons`, … |

The DB writer (`backend/paper/journal.py`) was last extended around Phase 2M
(momentum fields). Everything from **I4-A** (enhanced shadow), **I6**
(earnings/insiders), **M1** (market trend), **N1** (market mover), and **L1**
(LLM shadow) is **dashboard-visible but DB-invisible.** It is captured in the
runtime candidate dict, surfaces on `/api/paper/dashboard`, but the journal
INSERT only writes the 39-column subset.

---

## 6. Engine vs Deterministic Shadow vs LLM Shadow — auditability today

| Source | Live (this tick) | Persisted in DB | Notes |
|---|---|---|---|
| Engine decision | ✅ for all 52 | ✅ `eligible`, `action`, `entry_mode`, `total_score`, `rejection_reason`, components | full audit |
| Deterministic shadow | ✅ for all 52 (`WOULD_REJECT 45, WATCH 5, WOULD_ENTER 2`) | ❌ | every field lost on next restart |
| LLM shadow | ✅ for 32 (all errored 401), 20 not_selected | ❌ | every field lost; also: zero successful calls so far |

**For post-freeze analysis:** the persisted store can answer
"what did the engine decide for symbol X at time T", but not
"would the deterministic shadow have entered", "what did the LLM say",
"was a missed-opportunity surfaced", "did regime/trend/insider/earnings move
the score", or "did the LLM ever agree with the engine".

---

## 7. Runtime config vs dashboard vs engine consistency (Section B + G)

Schema size: **77 runtime-tunable fields** in `paper.runtime_config._SCHEMA`.
Runtime overrides currently active: **12**.

| Setting | Effective value | Override author | Engine usage |
|---|---|---|---|
| `PAPER_NO_CATALYST_ENTRY_ENABLED` | `true` | overnight-no-catalyst-data-collection | `no_catalyst_momentum.evaluate_no_catalyst_entry` |
| `PAPER_NO_CATALYST_MIN_SCORE` | `80` | (same) | same |
| `PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE` | `18` | (same) | same |
| `PAPER_NO_CATALYST_MIN_VOLUME_RATIO` | `1.5` | (same) | same |
| `PAPER_NO_CATALYST_MIN_CHANGE_PERCENT` | `2.0` | (same) | same |
| `PAPER_NO_CATALYST_MAX_SPREAD_PERCENT` | `0.2` | (same) | same |
| `PAPER_NO_CATALYST_REQUIRE_RISK_ON` | `true` | (same) | same — uses trend-adjusted regime under M1-H4 |
| `PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH` | `true` | (same) | `paper/no_catalyst_momentum.py:51` |
| `PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER` | `0.5` | (same) | sizing pipeline |
| `PAPER_BLOCKED_CATALYST_TYPES` | `"fda_regulatory"` | phase-2t-block-fda-regulatory | `simulator.run_tick` cat-type guard |
| `PAPER_POLL_INTERVAL_SECONDS` | `15` | preopen-reduce-paper-poll-interval | simulator loop |
| `PAPER_DAILY_MAX_LOSS_ENABLED` | `false` | fake-money-data-collection-disable-daily-loss-guard | risk guard |

All twelve overrides round-trip through `effective_config` and were observed
acting at runtime: the no-catalyst path is the dominant rejection reason
(`no accepted catalysts` = 24 of 52 this tick), the FDA-regulatory block is
visible on candidates with `catalyst_type_blocked=true`, the daily loss guard
shows `triggered=false`, and `restored_trades_today=100 / restored_daily_realized_pnl=-4.58` confirms the guard
is currently disabled (otherwise it would have tripped). PAPER_POLL_INTERVAL_SECONDS
== 15 matches the observed cadence.

**Settings NOT in the runtime schema (engine consumes from `settings.X` only):**

The L1 + I6 + M1 phases added several new categories but did NOT extend
`_SCHEMA`, so these are operator-restart-only:

- `LLM_SHADOW_*` (all 18 keys)
- `EARNINGS_DATA_PROVIDER`, `INSIDER_DATA_PROVIDER`, all `EARNINGS_*` / `INSIDER_*` scoring keys
- `MARKET_TREND_*` (all 15 keys)
- `MARKET_REGIME_*` (some)
- `FINNHUB_API_KEY` (env-only, correct)

This is **why the user's earlier PATCH to `/api/config/runtime` for
`LLM_SHADOW_ENABLED` was rejected with "Body must contain a non-empty 'updates' dict"** — the schema validator refuses unknown fields. The runtime
toggle currently in effect for LLM enablement is the `.env` line, not
the database table.

### Dashboard-to-backend consistency spot-checks

| Dashboard section | Endpoint | Backend module | Engine-used? |
|---|---|---|---|
| Market Session Readiness | `/api/readiness/session` | `api/readiness.py` | display |
| Monitoring Status | `/api/monitoring/status` | `api/monitoring.py` | display + summary |
| Market Regime | `dashboard.market_regime` | `market/regime.py` | yes — passes through `_tick_regime` |
| Market Trend | `/api/market/trend` | `market/trend.py` | yes — `_tick_regime_adjusted` |
| Strategy Settings | `/api/config/runtime` | `paper/runtime_config.py` | yes |
| Open Positions | `dashboard.positions` | `paper.account` | source of truth |
| Closed Trades | `dashboard.trades` | `paper.account` + DB journal | source of truth |
| Candidate Decisions | `dashboard.last_candidates` | `paper.simulator._state["last_candidates"]` | last tick only |
| Intelligence — Reddit | `/api/intelligence/reddit` | `intelligence/reddit.py` | shadow only |
| Intelligence — Premarket | `/api/intelligence/premarket` | `intelligence/premarket.py`/`full_premarket.py` | used by market-mover path |
| Intelligence — News | `/api/intelligence/news` | `api/intelligence.py` + `catalysts/news_collector` | engine uses via `catalyst_map` (rule-based) |
| Intelligence — Earnings | `/api/intelligence/earnings` | `intelligence/earnings.py` | yes — `score_earnings_proximity` |
| Intelligence — Insiders | `/api/intelligence/insiders` | `intelligence/insiders.py` | yes — `score_insiders` |
| LLM Shadow | `/api/intelligence/llm/status` | `intelligence/llm_shadow.py` | shadow only |

All checked sources are real; none are stub data.

---

## 8. Hardcoded value audit (Section C)

The bulk of scoring lives in `backend/paper/scoring.py`. It has multiple
threshold cliffs that are intentionally **not** in the runtime schema:

| File:line | Constant | Classification |
|---|---|---|
| `scoring.py:73-83` | spread tiers `0.05 / 0.15 / 0.30` for spread_score | **acceptable algorithmic constant** — these are the score buckets, not gates |
| `scoring.py:91-97` | change-pct tiers `2.0 / 1.0 / 0` for momentum_score | acceptable constant |
| `scoring.py:108-114` | volume_ratio tiers `1.5 / 1.0 / 0.8` for volume_score | acceptable constant |
| `scoring.py:160` | catalyst materiality tiers `0.7 / 0.4` | acceptable constant |
| `momentum.py:184-186` | regime-score regime-bonus tiers `80 / 70` | acceptable constant |
| `paper/simulator.py:1012` | hard reject spread `> 0.50%` | dangerous — should be runtime; not currently overridable |
| `paper/simulator.py:1014` | hard reject `change_percent <= 0` | acceptable invariant |
| `intelligence/llm_shadow.py:225-230` | LLM selection — wide-spread skip `> 0.50%` | duplicate of above, same number |
| `core/config.py:32+` | catalysts.scoring HIGH/MID lists | **acceptable** — type taxonomies |
| `market/trend.py:_classify` | trend thresholds `±10 / ±5 / ±2 / ±0.40 / ±0.25 / ±0.10` | acceptable algorithmic constants |
| `paper/no_catalyst_momentum.py` | several `MIN_*` defaults | already in `_SCHEMA` ✅ |
| `intelligence/insiders.py` | tier thresholds for $50k / $250k | in `core/config.py` Settings; not `_SCHEMA` — **should be moved to schema** later |
| `intelligence/earnings.py` | days_until tiers `1 / 2 / 3` | same — Settings but not schema |

No `sk-*`, `Bearer`, `apiKey=…`, `POLYGON_API_KEY=…` strings found in code.
Secrets are env-driven everywhere.

---

## 9. Outcome-analysis readiness (Section F)

**Outcome tracking exists: NO.**

Grep across `backend/` for `outcome | resolve | resolution | future_return |
return_5m | return_10m | return_15m | return_30m | return_60m | hit_target |
hit_stop` returned only:
- usages in tests (unrelated)
- `Path.resolve()` calls
- `asyncio.gather(...)` returning `outcomes`
- the literal token `resolved` in a docstring

There is **no table**, **no Redis key**, **no cron**, **no resolver job**
that, for a candidate seen at time T, records:
- did it hit +1% / +2% / +3% / +5% within 5m / 10m / 15m / 30m / 60m?
- did it hit -1% / -2% / -3% stop?
- what was its actual return at each window?
- would the engine / shadow / LLM have been right?

Without such a layer, the post-freeze analysis the user described will need
to:
1. Replay candidate rows against an external historical-bars source (the
   simulator does not store historical bars — only the rolling Redis snapshot
   with 30 s TTL).
2. Re-pull Polygon historical aggregates for each (symbol, T) pair.

This is **the largest analytical-readiness gap** in the system.

---

## 10. Restart-persistence readiness (Section H)

Verified by current `dashboard.status`:

```
running:                          True
restart_persistent:               True
restore_source:                   "redis"
restored_closed_trades_count:     99
restored_open_positions_count:    0
restored_daily_realized_pnl:      -4.5802
restored_trades_today:            100
restore_warning:                  None
mode:                             "research_paper_simulation"
live_trading_enabled:             False
broker_connected:                 False
```

`session_restore.py` covers the documented flow: Redis snapshot first, DB
fallback, malformed-row drops are logged at WARN level. `paper_runtime_config`
holds runtime overrides keyed by config field name, so a restart re-loads them.
`_DESIRED_RUNNING_KEY` persists the simulator's intended state.

⚠️ **Caveat (already in §7):** L1 / I6 / M1 settings are NOT runtime-tunable,
so the `LLM_SHADOW_ENABLED=true` line is in `.env` only. If a freeze restart
re-reads `.env`, LLM stays enabled. If someone rotates `.env` mid-freeze
without that line, LLM silently disables.

---

## 11. Error / log review (Section I)

24-hour backend log scan returned **zero** matches for:
`error | exception | traceback | warning | timeout | 429 | 403 | stale`

Sampling 2000 most recent log lines: only API access logs, all 200 OK. No
HTTP 4xx/5xx, no Polygon errors, no Finnhub errors, no journal write
failures, no Redis disconnects.

**Single notable outlier in module telemetry (not in logs):**

```
/api/intelligence/llm/status → calls_total: 107 072
                              calls_success: 0
                              calls_error: 107 072
                              last_error: "openai http 401"
```

Combined with the `OPENAI_API_KEY` literal value of `optional_change_me`
(verified via length + prefix + suffix probe, never printed), this confirms
that every LLM call since L1 went out has been rejected by OpenAI. The
shadow-only safety design has held — none of the 107k errors affected
trading behavior, none leaked secrets into logs (verified: the L1-H2/H3
redaction shows `<redacted>` in `last_error`). But all LLM Shadow rows
during the freeze will be `llm_status=error` unless the key is replaced.

---

## 12. Freeze-readiness classification: 🟡 YELLOW

**Run the freeze if and only if you accept these data-completeness gaps,**
or commit to fixing the blockers below before starting.

The system is safe to keep running (no broker, no real orders, no LLM
behavior change, restart-persistent, journal writes succeeding). What it
**cannot** do today is preserve enough data to back-analyze the comparison
between engine / deterministic shadow / LLM after the fact.

---

## 13. Exact blockers (if user wants a 🟢 GREEN before freezing)

1. **Persist the missing 122 candidate fields.** Extend
   `paper_candidates` (and the `paper/journal.py` INSERT) to cover the
   enhanced shadow, LLM, intelligence, market-trend, market-mover, and
   premarket/reddit columns. Either as discrete columns or as a single
   `extras_json jsonb` blob (the simpler path; preserves the full runtime
   dict shape per candidate without 100+ ALTER TABLE statements).

2. **Add an outcome-resolution layer.** Either:
   - a periodic resolver job that, every N minutes, walks unresolved
     candidates older than 60 min and pulls aggregate bars from Polygon
     to record `return_{5,10,15,30,60}m`, `hit_+1pct_minutes`,
     `hit_-2pct_minutes`, etc. into a new `paper_candidate_outcomes` table; OR
   - a streamier collector that subscribes to Polygon WS, holds rolling
     minute bars, and resolves against an in-memory schedule.

3. **Replace the placeholder `OPENAI_API_KEY`** with a real key before
   the freeze starts, or accept that the LLM Shadow column will be all-error
   for 14 days.

---

## 14. Non-blocking caveats

- `auto_cleanup_enabled=false` — good for the freeze. Make sure no one
  flips it on during.
- LLM / I6 / M1 settings are not in `_SCHEMA`. Any mid-freeze tweak
  requires editing `.env` and restarting the backend.
- Marketdata cache TTL is 30 s; the simulator's universe (50) is wider
  than the collector's 90 minus the always-on regime ETFs minus
  `paper_universe_symbols` overlap. **48 of 52 candidates this tick had
  `missing_marketdata_last_tick=true`** in `marketdata_cache.last_tick_stats`.
  This produced no errors (all candidates still got a rejection reason)
  but it means **48 of every 52 candidates have NULL marketdata fields
  on the persisted row.** Worth confirming this is the intended cadence
  before freezing.
- DB size projected to ≈ 1.8 GB after 14 days — well within disk capacity
  but the Postgres container has no volume size telemetry in this audit.
- The L1 `_KNOWN_PLACEHOLDER_VALUES` denylist does not include the literal
  `optional_change_me`; this is why a clearly bogus key was accepted as
  "present". Worth a follow-up (would have to be a code change, not part
  of G0).
- No backend errors / 429 / 403 / Polygon / Finnhub failures in the
  last 24h — **the data sources are stable.**
- Hardcoded `0.50` spread cutoff is duplicated in `simulator.py` and
  `llm_shadow.select_candidates_for_llm`; if anyone tunes one they'd need
  to tune the other.

---

## 15. Recommendation for the 2-week data collection period

**Two viable paths:**

### Path A — freeze now, accept the gaps (🟡 YELLOW)
- Get 14 days of:
  - engine decisions, full audit (39 cols × 2.5M rows)
  - tick-aggregate stats
  - closed trades
  - runtime config history
- Lose:
  - all deterministic shadow rows
  - all LLM shadow rows (which would be all-error anyway with current key)
  - all earnings / insider / market-trend / market-regime adjustments
  - all premarket-rank / reddit-rank attribution
  - any outcome resolution

You can still do meaningful analytical work on engine behavior + closed
trades, but you cannot answer "would the LLM / shadow have been better"
without a replay.

### Path B — bring it to 🟢 GREEN first (1–2 day dev sprint)
- Phase G1 (suggested): add `paper_candidates.extras_json` and write
  the full runtime dict to it. ≈ 1 backend change, 1 migration, no
  scoring touch.
- Phase G2 (suggested): add `paper_candidate_outcomes` table + a
  resolver job that walks the last 7 days nightly and back-fills.
- Phase G3 (suggested): rotate the OPENAI_API_KEY and tighten the
  placeholder denylist.

If the user proceeds with **Path A**, the deliverables can be re-derived
later with effort but at lower fidelity. **Path B** is the only one that
makes the comparison "did the engine make the right call vs shadow vs LLM"
queryable directly from the database.

---

*End of G0 audit. No application code, configuration, or runtime state was
modified during this audit. Containers, runtime overrides, and the LLM
status were all observed read-only.*
