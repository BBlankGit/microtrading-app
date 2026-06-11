# Codex Review — Phase N1 Session-Aware Market Mover No-Catalyst Entry

Date: 2026-06-11

Reviewed patch: `d1916d3` (`Add session-aware market mover no-catalyst entry path`)

## Scope

Only the latest Phase N1 patch was reviewed. The review covered the Phase N1 changes in:

- `backend/core/config.py`
- `backend/paper/runtime_config.py`
- `backend/paper/simulator.py`
- `backend/api/monitoring.py`
- `backend/tests/test_phase2kh1.py`
- `backend/tests/test_phase_n1.py`
- `frontend/dashboard/app/page.tsx`

No production code changes were made by this review. This document is the only file added by the review.

## Verdict

**Conditionally approved for fake-money monitoring with the default Phase N1 configuration, but one blocking correctness gap should be fixed before relying on runtime session overrides as a hard safety boundary.**

The patch implements a new `market_mover_no_catalyst` fake-money entry path and, with the default `PAPER_MARKET_MOVER_ALLOWED_SESSIONS=premarket,regular`, the observed control flow blocks afterhours, closed, non-regular, and overnight sessions. The path is correctly scoped to full-market mover candidates, requires no accepted catalyst coverage, keeps existing account gates, applies reduced position sizing, does not use shadow scoring for entries, does not alter TP/SL/exit behavior, and adds no broker/live-order/AI/LLM/Ollama integration.

However, the session block is currently enforced by comparing the current session to the runtime string `PAPER_MARKET_MOVER_ALLOWED_SESSIONS` without validating or hard-denying disallowed values. If an operator/runtime override adds `afterhours`, `closed`, `non_regular`, or `overnight` to that string, the code can pass the session check; because the volume gate only has explicit branches for `regular` and `premarket`, such a misconfigured non-regular session can also bypass the session-specific volume gate entirely. That conflicts with the requirement that afterhours/closed/non_regular/overnight sessions still hard-block entry.

## Review Findings

### Finding 1 — Blocked sessions are not hard-blocked against unsafe runtime overrides

**Severity:** High for correctness/safety-boundary semantics; not a live-trading risk because the code remains fake-money only.

The Phase N1 implementation checks the current session against `PAPER_MARKET_MOVER_ALLOWED_SESSIONS`, whose default is `premarket,regular`. This blocks non-regular sessions under default config. But the config is a plain runtime string and the evaluator does not additionally enforce an immutable allowlist of `{"premarket", "regular"}` or an immutable denylist of `{"afterhours", "closed", "non_regular", "overnight"}`.

Impact:

- With defaults, afterhours/closed/non_regular/overnight are blocked.
- With a bad runtime override such as `PAPER_MARKET_MOVER_ALLOWED_SESSIONS=afterhours`, the session check can pass.
- In a non-regular/non-premarket allowed session, the regular and premarket volume-gate branches are both skipped, so the candidate can become eligible if rank/change/spread/score and other blockers pass.

Recommended fix:

- Normalize allowed sessions to the intersection of configured values and `{"premarket", "regular"}`.
- Add an explicit hard block when `_tick_session_type` is not `premarket` or `regular`, regardless of runtime config.
- Consider schema/API validation so runtime overrides cannot persist blocked sessions.
- Add regression tests proving `afterhours`, `closed`, `non_regular`, and `overnight` remain blocked even if `PAPER_MARKET_MOVER_ALLOWED_SESSIONS` is overridden to include them.

## Detailed Checklist

### 1. New `entry_mode=market_mover_no_catalyst` is implemented

Pass. The new Path D branch marks eligible candidates with `entry_mode="market_mover_no_catalyst"`, creates positions with that entry mode, records result entries with the same entry mode, and tracks same-day counts for open and closed market-mover no-catalyst entries.

### 2. The path only applies to `full_market_movers` candidates

Pass. The market-mover evaluator only runs when `_mm_meta is not None`. `_mm_meta` is populated from the full-market movers snapshot injection map, and candidate metadata labels those candidates with `candidate_sources=["full_market_movers"]`.

### 3. No accepted catalyst is required for this path

Pass. Path D only executes when the shared hard rejection is a no-catalyst-style rejection (`no accepted catalysts` or `only generic_news catalysts`). In that branch it sets `catalyst_required=False` and clears the rejection reason before entry. Candidates with meaningful accepted catalyst coverage use the catalyst path or remain blocked by catalyst-specific guards instead of falling into Path D.

### 4. Entry is allowed only during configured sessions, default premarket and regular

Mostly pass with defaults. Defaults are `premarket,regular`, and the evaluator compares `_tick_session_type` to that runtime setting before marking the candidate eligible.

Caveat: see Finding 1. The runtime setting is not constrained to safe values, so this is not a hard invariant under arbitrary runtime overrides.

### 5. Afterhours/closed/non_regular/overnight sessions block entry

Pass with default configuration, but not hard-guaranteed under unsafe runtime overrides. Tests cover blocked non-regular sessions with the default allowed-session config, but the implementation does not prevent an override from admitting those sessions. See Finding 1.

### 6. Regular-session entries require `time_adjusted_volume_ratio`

Pass. Regular-session Path D sets `market_mover_entry_volume_gate_type="time_adjusted"` and blocks when `_ta_ratio` is missing or below `PAPER_MARKET_MOVER_MIN_TIME_ADJ_VOLUME_RATIO`. Because `_ta_ratio` is only computed during regular session when the time-adjusted volume feature is enabled and inputs are valid, regular market-mover entries require that ratio.

### 7. Premarket entries use `volume_vs_previous_day_ratio` or `dollar_volume` without requiring `time_adjusted_volume_ratio`

Pass. Premarket Path D uses day volume divided by previous-day volume as the primary gate and falls back to dollar volume. It does not require `_ta_ratio`, and the shared raw volume-ratio hard gate is skipped for market-mover candidates outside regular session so the premarket-specific gate can decide the path.

### 8. `fda_regulatory` and other blocked catalyst types still hard-block

Pass. Blocked catalyst types are still checked before entry decisions when accepted catalysts are present. A blocked catalyst type sets a hard rejection and clears no-catalyst eligibility, preventing Path D from firing. Candidate diagnostics expose `catalyst_type_blocked` and `blocked_catalyst_type`.

### 9. Strong bearish candidates still hard-block when configured

Pass. The shared strong-bearish catalyst rejection remains in the common hard gates. Phase N1 also adds a market-mover-specific `PAPER_MARKET_MOVER_BLOCK_IF_ANY_BEARISH` check that appends `strong_bearish_blocked` when bearish sentiment and materiality pass the configured threshold.

### 10. Rank/change/spread/score gates are enforced

Pass. Path D enforces:

- `PAPER_MARKET_MOVER_TOP_RANK_MAX`
- `PAPER_MARKET_MOVER_MIN_CHANGE_PERCENT`
- `PAPER_MARKET_MOVER_MAX_CHANGE_PERCENT`
- `PAPER_MARKET_MOVER_MAX_SPREAD_PERCENT`
- `PAPER_MARKET_MOVER_MIN_SCORE`

The existing broader tradability, positive-change, and spread hard gates also still run before Path D.

### 11. Existing account gates still apply

Pass. Path D uses `_account.can_enter()` with the existing `PAPER_MAX_OPEN_POSITIONS` and `PAPER_MAX_TRADES_PER_DAY` gates, so duplicate positions, maximum open positions, maximum daily trades, and no-cash checks still apply. The daily max-loss guard is checked before account entry. Actual cash availability is also bounded by `_account.enter_position()`, which caps the requested position size to available cash and rejects non-positive size.

Path D additionally has its own `PAPER_MARKET_MOVER_MAX_TRADES_PER_DAY` count gate.

### 12. Position sizing multiplier is applied

Pass. Path D calculates the normal paper budget from `PAPER_POSITION_SIZE_PERCENT` capped by `PAPER_MAX_POSITION_SIZE_USD`, then multiplies by `PAPER_MARKET_MOVER_POSITION_SIZE_MULTIPLIER` before entering the position. The default multiplier is `0.25`, reducing this high-risk no-catalyst path to one quarter of normal fake-money size.

### 13. Shadow scoring still does not control entries

Pass. Phase N1 Path D runs in the normal entry-decision section before the enhanced shadow-scoring enrichment. The shadow aggregate remains diagnostic and is described as not used for trading decisions. Tests include a source-inspection assertion that Path D precedes shadow scoring.

### 14. TP/SL/exit behavior was not changed

Pass. The Phase N1 diff does not alter TP/SL/max-hold exit logic. The new tests also assert the per-position exit loop does not reference `market_mover_no_catalyst`.

### 15. No Polygon calls were added by the Phase N1 path

Pass. The market-mover evaluator uses already available quality data and full-market mover metadata. The Phase N1 evaluator itself does not call Polygon client methods. Existing marketdata acquisition paths remain outside Path D and were not expanded by this patch.

### 16. No broker/live trading/real orders/AI/LLM/Ollama were added

Pass. The added code is confined to fake-money simulator/config/monitoring/dashboard/test surfaces. No broker, live trading, real-order, AI, LLM, or Ollama integrations were added. The Phase N1 tests include a forbidden-import source inspection for simulator imports.

### 17. Dashboard/monitoring clearly label the path as high-risk fake-money only

Pass. Monitoring returns a `market_mover_mode` block with a high-risk fake-money/no-live-trading/no-real-money-execution disclaimer and emits a warning when the mode is enabled. The dashboard adds a dedicated Full-Market Mover Entry panel labeled `HIGH-RISK NO-CATALYST PATH` and states fake-money only/no live trading/no real-money execution.

### 18. Tests and frontend build pass

Pass.

Commands run:

```bash
cd backend && pytest tests/test_phase_n1.py tests/test_phase2kh1.py
cd backend && pytest
cd frontend/dashboard && npm run build
```

Results:

- `pytest tests/test_phase_n1.py tests/test_phase2kh1.py`: 66 passed, 1 warning.
- Full backend `pytest`: 1102 passed, 2 skipped, 2 warnings.
- Frontend `npm run build`: passed. npm emitted the existing `Unknown env config "http-proxy"` warning before the Next.js build, but the build completed successfully.

### 19. Phase N1 safety for fake-money monitoring

Conditionally pass.

Phase N1 is safe for fake-money monitoring with default config and with operators keeping `PAPER_MARKET_MOVER_ALLOWED_SESSIONS` limited to `premarket,regular`. It remains high-risk by design because it intentionally allows fake-money entries without accepted catalyst coverage, but it applies reduced sizing, existing account gates, daily-loss guard, market-mover-specific daily limits, rank/change/spread/score gates, and dashboard/monitoring warnings.

Before treating the session gate as a hard safety invariant, fix Finding 1 so blocked session classes remain impossible even under runtime misconfiguration.

## Notes / Non-blocking Observations

- `PAPER_MARKET_MOVER_ALLOW_RISK_OFF` is added to config, runtime config, monitoring, and the dashboard, but the reviewed Path D evaluator does not appear to apply a market-regime gate either way. This is non-blocking for the requested checklist because Phase N1 requirements did not ask for risk-off gating, but the setting may confuse operators unless wired up or removed.
- The default `PAPER_MARKET_MOVER_ENTRY_ENABLED=True` means this high-risk fake-money path is active by default when the simulator and candidate injection are active. The dashboard/monitoring warnings are clear, but operators should be aware that this is not opt-in at the environment-default layer.
