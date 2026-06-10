# Codex Review — Phase S1-V1 Auto-Resume, Time-Adjusted Volume, and Full-Market Movers Volume Multiples

## Executive summary

I reviewed the current checked-out repository state at `HEAD` (`ce52cdc`, `Merge pull request #65 from BBlankGit/codex/review-phase-i4-b-h1-cache-only-fix`) for the requested Phase S1-V1 scope.

**Conclusion: S1-V1 is not implemented in this checkout.** The existing app remains a fake-money research simulator, and the existing safety boundaries around broker/live trading, shadow scoring, and injected mover cache behavior are still intact. However, the requested S1-V1 features are largely absent:

- No persisted `desired_running` flag exists.
- Backend startup restores paper account/session state but does not auto-resume the simulator.
- No NY regular-session elapsed-fraction time-adjusted relative volume is computed.
- Catalyst, momentum, and no-catalyst volume gates still use raw `volume_ratio`.
- Full-Market Movers is session-aware and bulk-scan based, but it does not expose `volume_vs_previous_day_ratio`, `time_adjusted_volume_ratio`, or 30d/60d average-volume fields.

**Safety recommendation:** the current checkout is safe for fake-money monitoring in the same sense as the prior I4-B/H1 state, but it should **not** be accepted as Phase S1-V1 complete. If a separate S1-V1 branch exists, it was not present in this local checkout and should be reviewed directly before merge/deployment.

## Review scope and evidence commands

Commands run:

```bash
git status --short
git log --oneline --decorate --all -n 30
rg -n "desired_running|auto.?resume|time_adjusted|volume_vs_previous|Full-Market|volume_ratio" backend frontend docs -S -g '!node_modules'
pytest
npm install && npm run build
```

A network fetch attempt against `https://github.com/BBlankGit/microtrading-app.git` failed with `CONNECT tunnel failed, response 403`, so this review is limited to the repository contents available in `/workspace/microtrading-app`.

## Findings by requested focus area

| # | Focus area | Result | Evidence / notes |
|---:|---|---|---|
| 1 | Paper simulator desired running state is persisted on start/stop | **Fail — absent** | There is no `desired_running` state key in the simulator state or Redis snapshot. `start_simulator()` only sets in-memory `_state["running"] = True`, and `stop_simulator()` only sets `_state["running"] = False`. `_save_state()` persists account/session fields but no desired-running preference. |
| 2 | Backend restart auto-resumes only when `desired_running=true` | **Fail — absent** | Startup calls `restore_paper_session()` only. That function restores account/session data, not the simulator loop. There is no startup branch that checks a persisted desired-running flag or calls `start_simulator()` based on it. |
| 3 | Auto-resume remains fake-money only and cannot start broker/live trading | **Pass for safety, but no auto-resume exists** | The simulator module and status paths explicitly state no broker, no live trading, no real orders, and status reports `live_trading_enabled: False` / `broker_connected: False`. Because auto-resume is absent, it cannot accidentally start broker/live trading. |
| 4 | Auto-resume status/warnings are exposed | **Fail — absent** | Restore metadata and warnings are exposed, but there are no auto-resume-specific fields such as `desired_running`, `auto_resume_attempted`, `auto_resume_started`, or `auto_resume_warning`. |
| 5 | Time-adjusted relative volume computed correctly using NY regular-session elapsed fraction | **Fail — absent** | Both direct Polygon quality and cache quality compute raw `volume_ratio = day_volume / previous_day_volume`. There is no elapsed regular-session fraction, NY 09:30–16:00 clamp, or expected-volume-so-far denominator. |
| 6 | Raw `volume_ratio` remains available | **Pass** | Raw `volume_ratio` is still returned from market-quality builders and included in candidate records. |
| 7 | Catalyst/no-catalyst volume gates use `time_adjusted_volume_ratio` when enabled | **Fail — absent** | The hard gate uses `q.get("volume_ratio")`; momentum and no-catalyst evaluators also use raw `quality.get("volume_ratio")`. No enable flag or adjusted-ratio selector exists. |
| 8 | Early-session candidates can pass volume gate based on expected volume so far | **Fail** | Because the ratio compares current day volume to full prior-day volume and the market-quality sufficient-volume gate also requires `day_volume >= 500,000`, early-session names can still be rejected against full-day volume expectations rather than expected volume so far. |
| 9 | Missing/invalid volume data rejects safely | **Pass** | Missing or insufficient `day_volume` / previous-day volume makes `has_sufficient_volume` false and therefore `tradable` false in both direct and cache market-quality paths. Downstream momentum/no-catalyst gates also require a non-null volume ratio. |
| 10 | Movers tab is renamed to Full-Market Movers and session-aware | **Pass** | The frontend tab label is `🌐 Full-Market Movers`; the tab title varies by `premarket`, `regular`, `afterhours`, and `closed`. The backend scanner classifies sessions and only actively refreshes during premarket/regular while serving cached data after-hours/closed. |
| 11 | Full-Market Movers API/UI includes `volume_vs_previous_day_ratio` and `time_adjusted_volume_ratio` | **Fail — absent** | Mover objects currently include symbol, last price, previous close, gap percent, raw change percent, day volume, dollar volume, and source. The frontend type and row render only volume/dollar volume, not either requested ratio. |
| 12 | 30d/60d average volume fields are safe/null if unavailable without heavy calls | **Fail for field presence; pass for avoiding heavy calls** | No 30d/60d average-volume fields are exposed, even as null placeholders. However, no per-symbol historical average-volume calls were added in this checkout. |
| 13 | No heavy per-symbol historical calls added for 5,000 symbols | **Pass** | The full-universe scanner uses Polygon bulk snapshots in chunks and explicitly documents no per-ticker REST calls. No historical per-symbol volume calls were found. |
| 14 | TP/SL/exit behavior was not changed | **Pass** | Exit behavior remains in the existing virtual bracket and max-hold logic. I found no S1-V1 changes to TP, SL, intrabar exits, or max-hold exit behavior in this checkout. |
| 15 | Shadow score still does not execute trades | **Pass** | Enhanced shadow scoring is appended after entry decisions are finalized, and its aggregate disclaimer says shadow is not used for trading decisions. |
| 16 | No Polygon calls were added in paper tick path | **Pass for S1-V1; existing calls unchanged** | The paper tick still has the existing Polygon direct/fallback path for normal symbols. Injection-only full-market movers are explicitly rejected on stale/missing cache instead of falling back to Polygon. No new S1-V1 Polygon path was found. |
| 17 | No broker/live trading/real orders/AI/LLM/Ollama were added | **Pass** | The touched runtime paths remain deterministic fake-money simulation/read-only intelligence. The simulator and status responses explicitly report no broker/live/real orders. No Ollama/LLM execution path was found in the reviewed backend changes. |
| 18 | Tests and frontend build pass | **Pass** | `pytest` passed with 1029 passed, 2 skipped, 2 warnings. `npm install && npm run build` passed for the dashboard. |
| 19 | S1-V1 is safe for fake-money monitoring | **Mixed** | The current checkout is safe as the existing fake-money monitoring app, but **not safe to treat as S1-V1 complete**, because the requested persistence/auto-resume and time-adjusted volume behavior are missing. |

## Detailed review notes

### 1. Auto-resume / desired running state

The simulator has separate in-memory runtime state and account snapshot persistence. The in-memory `_state` includes `running`, restore metadata, tick telemetry, market-data telemetry, and shadow stats, but no desired-running flag. The start endpoint calls `start_simulator()`, which only flips in-memory state and creates the loop task. The stop endpoint calls `stop_simulator()`, which only stops the loop and flips in-memory `running` false.

The Redis snapshot writer persists account state (`cash`, `positions`, `trades`, daily counters, baseline equity, and last prices) plus integrity metadata. It does not persist a desired-running value. Therefore a restart cannot distinguish “operator wanted the simulator running” from “operator intentionally stopped it.”

Startup invokes `restore_paper_session()` from the FastAPI lifespan. That restore applies account/session state and restore metadata, but does not start the simulator loop. This is safer than an incorrect auto-resume implementation, but it does not satisfy S1-V1.

Recommended follow-up for S1-V1:

- Add a dedicated persistent desired-state key/field, preferably separate from account snapshot integrity state.
- Set `desired_running=true` before/after successful manual start, and `desired_running=false` on manual stop/reset as intended.
- On backend startup, restore account state first, then auto-start only when the persisted desired state is true.
- Expose fields such as `desired_running`, `auto_resume_attempted`, `auto_resume_started`, `auto_resume_warning`, and `auto_resume_last_checked_at` through `/api/paper/status` and monitoring.

### 2. Time-adjusted relative volume

Raw relative volume remains available, but no time-adjusted calculation exists. The direct market-quality code computes:

```python
volume_ratio = day_volume / prev_day_volume
```

The cache adapter mirrors the same formula. A correct S1-V1 implementation should calculate NY regular-session elapsed fraction, for example:

- Before 09:30 ET: fraction should be either null/not regular or a safe minimum depending on intended premarket behavior.
- 09:30–16:00 ET: fraction = elapsed regular-session seconds / 23,400 seconds, clamped to a sane lower bound to avoid division explosion immediately after open.
- After 16:00 ET: fraction = 1.0.
- Expected volume so far = previous-day volume × elapsed fraction.
- `time_adjusted_volume_ratio = day_volume / expected_volume_so_far` when inputs are valid.

The current implementation still penalizes early-session candidates against full previous-day volume and additionally requires a hard minimum current `day_volume >= 500,000`, so early-session candidates cannot reliably pass based on expected volume so far.

### 3. Volume gates

The main catalyst hard gate, momentum fallback gate, no-catalyst gate, and scoring volume component all read raw `volume_ratio`. There is no runtime config switch that selects `time_adjusted_volume_ratio` when enabled. If S1-V1 intends time-adjusted gates to be optional, the implementation should make the chosen ratio explicit in candidate telemetry, for example:

- `volume_ratio` — raw current-day vs previous-day ratio.
- `time_adjusted_volume_ratio` — adjusted vs expected-so-far ratio.
- `volume_gate_ratio_used` — either `volume_ratio` or `time_adjusted_volume_ratio`.
- `volume_gate_mode` — `raw` or `time_adjusted_regular_session`.

### 4. Full-Market Movers

The rename/session-awareness requirement is already satisfied by the existing I4-B implementation:

- The dashboard tab label says “Full-Market Movers.”
- The tab title changes by market session.
- The backend scanner detects premarket, regular, after-hours, and closed sessions.
- The background scan loop actively refreshes only during premarket and regular sessions, then serves cached data when after-hours/closed.

However, the S1-V1 volume-multiple fields are not present. The backend mover shape lacks `volume_vs_previous_day_ratio`, `time_adjusted_volume_ratio`, `avg_volume_30d`, and `avg_volume_60d`. The frontend type and row rendering also lack those fields. If 30d/60d averages are not available without heavy calls, the API should expose null fields explicitly and document that they are intentionally unavailable until a cheap source/cache exists.

### 5. Heavy-call and Polygon safety

No heavy per-symbol historical calls were added for the full-market scan. The scanner continues to use bulk snapshots in chunks and explicitly documents no per-ticker REST calls. The paper tick still contains existing Polygon direct/fallback behavior for normal paper symbols, while injection-only mover symbols are blocked from Polygon fallback on cache miss/stale data.

### 6. Trading safety

The current checkout remains fake-money only:

- The simulator module explicitly states no broker, no live trading, no real orders, and no real-money execution.
- `/api/status` reports research mode with execution disabled and no broker connection.
- The paper dashboard disclaimer says research-only fake-money simulation.
- Shadow scoring is diagnostic-only and appended after actual entry decisions are already made.

I found no S1-V1 change that adds broker/live trading, real orders, AI/LLM/Ollama execution, or real-money pathways.

## Tests / checks

- `pytest` — **passed**: 1029 passed, 2 skipped, 2 warnings.
- `npm install && npm run build` from `frontend/dashboard` — **passed**. npm emitted a non-fatal `Unknown env config "http-proxy"` warning before install/build; Next.js build completed successfully.

## Final recommendation

Do **not** accept this checkout as Phase S1-V1 complete. It is safe for the existing fake-money monitoring workflow, but the requested S1-V1 behavior must be implemented and then re-reviewed, especially:

1. Persisted desired-running state and restart auto-resume gated strictly by that state.
2. Auto-resume telemetry/warnings in paper status and monitoring.
3. Correct NY regular-session time-adjusted volume ratio.
4. Optional gate switching to `time_adjusted_volume_ratio` with raw `volume_ratio` preserved.
5. Full-Market Movers API/UI volume multiple fields, with 30d/60d averages safely null unless already cheaply available.
