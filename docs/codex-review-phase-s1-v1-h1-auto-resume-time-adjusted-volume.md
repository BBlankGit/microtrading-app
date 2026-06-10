# Codex Review — Phase S1-V1-H1 Auto-Resume, Time-Adjusted Volume, Full-Market Movers Volume Multiples, and Reddit Redis Isolation

Reviewed repository: `BBlankGit/microtrading-app`  
Review scope: latest S1-V1-H1 patch only (`ed89e92 Implement auto-resume and time-adjusted volume metrics`)  
Review date: 2026-06-10

## Executive conclusion

**S1-V1-H1 is mostly safe for fake-money monitoring, with one material product/logic gap and one data-hygiene gap.** The patch remains within the fake-money paper simulator and read-only intelligence surfaces. It does not add broker/live trading, real-order, AI/LLM/Ollama, TP/SL/exit changes, shadow-score execution, or new Polygon calls in the paper tick path.

The H1 patch improves observability and hardening by exposing `auto_resume_attempted`, blocking auto-resume if `LIVE_TRADING_ENABLED` is ever true, renaming Full-Market Movers volume-multiple fields to the requested API/UI names, adding null-safe 30d/60d placeholders, and adding an autouse test fixture that prevents Reddit tests from writing to shared/production Redis keys.

However:

1. **Catalyst/no-catalyst/momentum scoring and path gates do not consistently use the time-adjusted volume view.** The simulator computes `_q_for_paths`, but `score_candidate()`, `evaluate_momentum_entry()`, and `evaluate_no_catalyst_entry()` are still called with raw `q`, so those downstream evaluators still see raw `volume_ratio`.
2. **Malformed/test-like Reddit cached rows are still trusted on Redis load.** The H1 patch isolates test writes, but startup `ensure_loaded()` still assigns Redis rows directly into `_current` without normalization or schema filtering.

Given those caveats, S1-V1-H1 is **safe for fake-money monitoring**, but I would not mark the volume-gate requirement fully complete until the downstream evaluator calls use `_q_for_paths` or equivalent validated adjusted-ratio fields.

## Evidence reviewed

### Latest patch files

The latest S1-V1-H1 patch changes only these files:

- `backend/intelligence/full_premarket.py`
- `backend/paper/simulator.py`
- `backend/tests/conftest.py`
- `backend/tests/test_phase_i2.py`
- `backend/tests/test_phase_s1v1.py`
- `frontend/dashboard/app/page.tsx`

### Commands used

```bash
git status --short
git show --stat --oneline HEAD
git diff HEAD~1..HEAD --stat
git diff HEAD~1..HEAD -- backend/paper/simulator.py backend/intelligence/full_premarket.py frontend/dashboard/app/page.tsx backend/tests/test_phase_s1v1.py backend/tests/conftest.py backend/tests/test_phase_i2.py
rg -n "S1-V1-H1|desired_running|auto.?resume|time_adjusted|volume_ratio|Full-Market|Reddit|shadow|Polygon|paper" -S .
rg -n "auto_resume_if_desired|restore_paper_session|start_simulator|paper.*status|LIVE_TRADING_ENABLED|BROKER|Ollama|LLM|polygon" backend frontend -S
rg -n "PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO|PAPER_TIME_ADJUSTED_VOLUME|PAPER_MIN_VOLUME_RATIO|Strategy Settings|Raw Volume|Time-Adjusted|Full-Market|full-market|session" backend/core backend/paper frontend/dashboard/app/page.tsx -S
python -m pytest tests/test_phase_s1v1.py tests/test_phase_i2.py
python -m pytest
npm run build
```

## Requirement-by-requirement review

| # | Requirement | Result | Notes |
|---:|---|---|---|
| 1 | Paper simulator desired running state is persisted on start/stop | **Pass** | `start_simulator()` persists `True`; `stop_simulator()` persists `False`. Redis persistence is best-effort and non-fatal. |
| 2 | Backend restart auto-resumes only when `desired_running=true` | **Pass** | Startup calls `auto_resume_if_desired()` after restore, and that function starts only when `load_desired_running()` returns `True`; `False` and missing state do not start. |
| 3 | Auto-resume remains fake-money only and cannot start broker/live trading | **Pass** | Simulator status hardcodes fake-money metadata, no broker path is introduced, and H1 adds an explicit `LIVE_TRADING_ENABLED` block before auto-start. |
| 4 | Auto-resume status/warnings are exposed | **Pass** | `get_status()` exposes `desired_running`, `auto_resumed`, `auto_resumed_at`, `auto_resume_attempted`, `auto_resume_source`, and `auto_resume_warning`. |
| 5 | Time-adjusted relative volume uses NY regular-session elapsed fraction | **Pass** | The helper uses America/New_York when available, regular session 09:30-16:00 ET, 390 minutes, and returns `1.0` outside regular session. |
| 6 | Raw `volume_ratio` remains available | **Pass** | The raw `q` object is not overwritten; candidate telemetry includes raw `volume_ratio` plus separate adjusted fields. |
| 7 | Catalyst/no-catalyst/momentum volume gates use `time_adjusted_volume_ratio` when enabled | **Partial / Fail** | The hard shared volume gate uses `_ta_ratio` when available, but the downstream scoring/momentum/no-catalyst evaluators are still invoked with raw `q`, not `_q_for_paths`. |
| 8 | Early-session candidates can pass based on expected volume so far | **Partial** | The shared hard gate can pass based on `day_volume / (previous_day_volume * elapsed_floor)`, but downstream raw-volume scoring/gates may still reject or under-score early candidates. |
| 9 | Missing/invalid volume data rejects safely | **Mixed** | The adjusted helper returns `None` for missing, zero, negative, or non-finite inputs. But when adjusted mode is enabled and `_ta_ratio` is `None`, the hard gate falls back to raw-mode behavior; if raw `volume_ratio` is also `None`, there is no hard volume rejection at that point. |
| 10 | Strategy Settings show raw volume ratio and time-adjusted settings separately | **Pass** | Raw `PAPER_MIN_VOLUME_RATIO` remains in strategy fields; H1 adds a separate Time-Adjusted Volume Gate section. |
| 11 | Movers tab is labeled Full-Market Movers and session-aware | **Pass** | The tab label is `Full-Market Movers`, while the panel title changes by session (`Premarket`, `Regular`, `After-Hours`, or cached/closed). |
| 12 | Full-Market Movers API/UI includes `volume_vs_previous_day_ratio` and `time_adjusted_volume_ratio` | **Pass** | H1 renames the API enrichment fields and updates the frontend type/display to the new names. |
| 13 | 30d/60d average volume fields are safe/null if unavailable without heavy calls | **Pass** | Enrichment adds 30d/60d average-volume fields as `None` placeholders and does not fetch history. |
| 14 | No heavy per-symbol historical calls added for 5,000 symbols | **Pass** | The full-market scanner remains bulk-snapshot/chunk based; H1 enrichment uses existing `day_volume` and `previous_day_volume` values only. |
| 15 | Reddit refresh `force=True` and expired GET refresh behavior are correct | **Pass** | `fetch_and_refresh(force=True)` bypasses the TTL guard; GET refreshes when results are empty or TTL is expired and no current error is set. |
| 16 | Reddit/intelligence tests are isolated and cannot write fake data into production/shared Redis keys | **Pass for save writes** | H1 adds an autouse fixture patching `intelligence.reddit._redis_save`, and specific Reddit tests also patch `_redis_save`. Reads are not globally namespaced, but the asked write-leak risk is addressed. |
| 17 | Malformed/test-like Reddit cached rows are not silently shown as valid ranking data | **Fail / pre-existing still open** | Redis-loaded rows are assigned directly to `_current` in `ensure_loaded()` without normalization or validation, so malformed cached rows can still appear as valid API results. |
| 18 | TP/SL/exit behavior was not changed | **Pass** | The H1 diff does not touch `paper/exits.py` or TP/SL entry/exit logic. |
| 19 | Shadow score still does not execute trades | **Pass** | The H1 diff does not alter shadow-score execution boundaries. Existing status remains observational. |
| 20 | No Polygon calls were added in paper tick path | **Pass** | H1 changed telemetry and adjusted-volume calculations in `run_tick()` only; it did not add new Polygon calls to the tick path. |
| 21 | No broker/live trading/real orders/AI/LLM/Ollama were added | **Pass** | No latest-patch file adds those integrations; simulator and intelligence comments/metadata continue to state fake-money/read-only boundaries. |
| 22 | Tests and frontend build pass | **Pass** | Focused S1/I2 tests, full backend pytest, and dashboard `npm run build` all passed locally. |
| 23 | S1-V1-H1 is safe for fake-money monitoring | **Pass with caveats** | Safe for monitoring because it remains fake-money/read-only, but time-adjusted downstream gates and Reddit cached-row validation need follow-up before calling all S1-V1-H1 acceptance criteria complete. |

## Detailed findings

### 1. Auto-resume persistence and restart behavior

`_persist_desired_running()` stores a boolean desired-running flag both in memory and Redis, using the dedicated key derived from `PAPER_STATE_REDIS_NAMESPACE`. It swallows Redis failures, so the simulator can still start/stop when Redis is unavailable.

`start_simulator()` calls `_persist_desired_running(True)` after creating the simulator task. `stop_simulator()` calls `_persist_desired_running(False)` after shutting down the task. This satisfies the desired-running persistence requirement.

Backend lifespan imports and runs `restore_paper_session()` followed by `auto_resume_if_desired()`, so restart auto-resume is tied to the persisted desired-running flag rather than to restored account state alone.

`auto_resume_if_desired()` has the correct start conditions:

- Missing or unreadable persisted flag: no start, source `no_persisted_state`.
- Persisted `False`: no start, source `redis_not_desired`.
- Persisted `True`: calls `start_simulator()`, marks `auto_resumed`, sets `auto_resumed_at`, and records source `redis`.

H1 also adds an important fake-money hardening guard: if `settings.LIVE_TRADING_ENABLED` is true, auto-resume returns a warning and does not call `start_simulator()`.

### 2. Auto-resume observability

The paper status payload includes:

- `desired_running`
- `auto_resumed`
- `auto_resumed_at`
- `auto_resume_attempted`
- `auto_resume_source`
- `auto_resume_warning`
- `mode: research_paper_simulation`
- `live_trading_enabled: False`
- `broker_connected: False`

This is enough for API/UI monitoring to distinguish “desired false,” “desired true and attempted,” “auto-resumed,” and “blocked/warned.”

One small cleanup issue: `reset_simulator()` clears most auto-resume fields but does not clear `auto_resume_attempted`. That is not in the latest H1 diff's main path and does not affect startup gating, but it can leave stale status after reset.

### 3. Time-adjusted relative volume calculation

`paper.time_adjusted_volume.session_elapsed_ratio()` correctly uses New York time, the regular session window 09:30-16:00 ET, and a 390-minute denominator. It returns `1.0` outside regular session, which avoids applying early-session adjustment outside the regular market.

`time_adjusted_volume_ratio(day_volume, prev_day_volume, elapsed_ratio, min_floor)` computes:

```text
day_volume / (prev_day_volume * max(elapsed_ratio, min_floor))
```

It returns `None` for missing values, non-numeric values, non-finite values, `prev_day_volume <= 0`, negative `day_volume`, or invalid denominator. This is the right arithmetic for “volume versus expected volume so far” and prevents divide-by-near-zero behavior at the open.

The simulator calculates `_ta_ratio` only when `PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO` is enabled and the session is `regular`. Candidate telemetry now includes:

- `time_adjusted_volume_enabled`
- `time_adjusted_volume_ratio`
- `expected_volume_now`
- `prev_day_volume`
- `session_elapsed_ratio`
- `volume_gate_type`
- `volume_gate_ratio_used`
- `volume_gate_threshold_used`

This makes the gate mode inspectable after a tick.

### 4. Important gap: downstream gates still use raw volume ratio

The simulator builds `_q_for_paths = dict(q, volume_ratio=_ta_ratio)` when adjusted mode is active, but the downstream evaluators are still called with raw `q` in the current file:

- `score_candidate(sym, q, cats, ...)`
- `evaluate_momentum_entry(sym, q, scoring, regime)`
- `evaluate_no_catalyst_entry(sym, q, scoring, regime)`

Those functions all read `quality.get("volume_ratio")`. As a result:

- The shared hard gate can use `time_adjusted_volume_ratio`.
- The catalyst path's score volume component still uses raw `volume_ratio`.
- The momentum path's volume gate still uses raw `volume_ratio`.
- The no-catalyst path's volume gate still uses raw `volume_ratio`.

This does not create a real-money safety problem, but it means acceptance item #7 is not fully met and item #8 is only partially met. Early-session names can pass the shared hard gate on expected volume so far but still be blocked or scored down by the raw-ratio downstream evaluators.

### 5. Missing/invalid volume data behavior

The adjusted ratio helper is safe and returns `None` for missing or invalid inputs. Full-Market Movers enrichment also emits `None` for the adjusted and previous-day volume ratios when `previous_day_volume` is missing or not positive.

The simulator hard gate is less strict when adjusted mode is enabled but `_ta_ratio` is unavailable: `_use_ta_vol` becomes false, and the raw-volume hard rejection only fires when `q.get("volume_ratio") is not None and q.get("volume_ratio") < PAPER_MIN_VOLUME_RATIO`. Therefore, if both adjusted data and raw `volume_ratio` are missing, the hard volume gate itself does not reject. Other quality/tradability gates may still reject depending on `evaluate_market_quality()`, but the S1-specific safe-reject requirement is not airtight in this latest patch.

### 6. Full-Market Movers volume multiples and session awareness

The Full-Market Movers backend remains session-aware via `get_current_session()` and returns the session in snapshots. The scanner continues to use Polygon reference tickers for the universe and Polygon bulk ticker snapshots in chunks, not per-symbol historical calls.

H1 changes the volume-multiple enrichment to the requested field names:

- `volume_vs_previous_day_ratio`
- `time_adjusted_volume_ratio`
- `expected_volume_now`
- `session_elapsed_ratio`

It also adds safe null placeholders:

- `avg_daily_volume_30d`
- `volume_vs_30d_avg_ratio`
- `avg_daily_volume_60d`
- `volume_vs_60d_avg_ratio`

These are calculated/enriched non-mutatingly when `get_snapshot()` returns `top_gainers`, `top_losers`, and `top_movers`.

The UI type and row rendering now use the new field names, and the tab is labeled `Full-Market Movers`. The displayed panel title remains session-specific (`Premarket Movers`, `Regular Session Movers`, etc.), which is consistent with “Full-Market Movers and session-aware.”

### 7. Strategy Settings UI separation

The raw strategy setting `PAPER_MIN_VOLUME_RATIO` remains in the main strategy numeric fields. H1 adds a separate `Time-Adjusted Volume Gate` panel with:

- `PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO`
- `PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN`
- `PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR`

The panel explicitly says that, when enabled during regular session, the gate uses time-adjusted relative volume instead of raw full-day volume ratio, and that the feature is fake-money only with no broker/real orders.

### 8. Reddit refresh and Redis isolation

The Reddit refresh logic is correct for force and expired GET behavior:

- `fetch_and_refresh(force=True)` bypasses both TTL checks.
- `GET /api/intelligence/reddit` refreshes when results are empty or TTL is expired and there is no current error.
- `POST /api/intelligence/reddit/refresh` calls `fetch_and_refresh(force=True)`.

H1 adds an autouse pytest fixture patching `intelligence.reddit._redis_save` to an `AsyncMock`, preventing test-generated ApeWisdom rows from being written to whatever Redis namespace the test environment points at. H1 also patches `_redis_save` inside specific concurrent/TTL Reddit tests. That addresses the shared/production Redis write-leak risk.

The remaining problem is cached-row validation. `ensure_loaded()` reads Redis rows with `_redis_load()` and directly assigns `cached` to `_current`. It does not re-run `_normalize_rows()` or validate required fields/types. Therefore malformed or test-like cached rows can still be surfaced as valid ranking data.

### 9. Unchanged safety boundaries

The latest patch does not alter:

- TP/SL or virtual exit logic.
- Shadow score execution behavior.
- Paper tick Polygon call topology.
- Broker/live trading/real orders.
- AI/LLM/Ollama integrations.

The H1 diff is limited to simulator auto-resume status/guarding, time-adjusted-volume telemetry, Full-Market Movers field enrichment/display, and tests.

## Testing performed

### Focused backend tests

Command:

```bash
python -m pytest tests/test_phase_s1v1.py tests/test_phase_i2.py
```

Result:

```text
51 passed, 1 skipped, 1 warning in 0.67s
```

### Full backend test suite

Command:

```bash
python -m pytest
```

Result:

```text
1060 passed, 2 skipped, 1 warning in 12.51s
```

### Frontend production build

Command:

```bash
npm run build
```

Result:

```text
✓ Compiled successfully
✓ Linting and checking validity of types
✓ Generating static pages (4/4)
✓ Finalizing page optimization
```

## Recommendation

S1-V1-H1 is acceptable for fake-money monitoring, but I recommend a small follow-up before closing all acceptance criteria:

1. Pass `_q_for_paths` into `score_candidate()`, `evaluate_momentum_entry()`, and `evaluate_no_catalyst_entry()` when adjusted mode is active, or explicitly add adjusted-ratio-aware parameters to those functions.
2. Add a hard rejection when adjusted volume is enabled during regular session but adjusted volume cannot be computed because volume inputs are missing/invalid.
3. Validate or normalize Redis-loaded Reddit rows before assigning them to `_current`; reject rows that do not look like real ApeWisdom ranking rows.
4. Clear `auto_resume_attempted` in `reset_simulator()` to avoid stale status after a manual reset.
