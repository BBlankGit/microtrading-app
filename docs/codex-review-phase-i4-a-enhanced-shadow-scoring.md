# Codex Review: Phase I4-A Enhanced Opportunity Shadow Scoring

Review date: 2026-06-10

Reviewed commits:

- `7bfb781` — `Add enhanced opportunity shadow scoring`
- `f961794` — `Harden frontend runtime against stale Next.js chunks` (reviewed separately as frontend-runtime hardening)

Scope honored: reviewed only the latest Phase I4-A patch and the separate frontend-runtime hardening patch. No production code changes were made in this review.

## Executive Summary

Phase I4-A is safe for fake-money monitoring. The enhanced opportunity score is implemented as a diagnostic shadow layer, attached after the simulator has already finalized candidate trading decisions, and it does not control `eligible`, `action`, `entry_mode`, entries, exits, account state, or journal persistence.

The implementation reads premarket and Reddit inputs from cached in-memory intelligence snapshots only in the shadow scoring path. I found no new Polygon, ApeWisdom, broker, live-order, AI, LLM, Ollama, or V6 hardcoded auth/test endpoint additions in the Phase I4-A patch.

The separate frontend-runtime hardening patch is operational/runtime-only: it clears stale `.next` artifacts inside the frontend container, uses Docker named volumes for `.next` and `node_modules`, rebuilds before `next start`, and removes the obsolete standalone output setting. It does not change trading behavior.

## Findings

No blocking findings.

## Detailed Review Against Requested Focus Areas

### 1. Enhanced shadow scoring is computed for candidates

Pass. `compute_shadow_score()` is called once per candidate after the simulator has processed the normal catalyst/momentum decision path. The returned shadow dictionary is appended to the candidate record with `candidate.update(_shadow)`.

### 2. Shadow score, decision, reason, and components are exposed

Pass. The scorer returns the core fields `enhanced_shadow_score`, `enhanced_shadow_decision`, `enhanced_shadow_reason`, and `enhanced_shadow_components`, plus blockers, confidence, premarket fields, and Reddit fields. The simulator appends those fields to candidates and provides fallback values on scoring errors.

### 3. Premarket data is read from cached intelligence snapshot only

Pass. The simulator snapshots premarket data once per tick via `intelligence.full_premarket.get_snapshot()` and builds a lookup from that cached snapshot. The scorer consumes the snapshot/lookup only and does not import or call Polygon. Existing simulator market-data Polygon fallback paths are outside the Phase I4-A shadow scoring path and predate this patch.

### 4. Reddit data is read from cached intelligence snapshot only

Pass. The simulator snapshots Reddit data once per tick via `intelligence.reddit.get_snapshot()` and builds a lookup from that cached snapshot. The scorer consumes the snapshot/lookup only and does not call `fetch_and_refresh()` or ApeWisdom.

### 5. Actual trading decisions are unchanged

Pass. Shadow scoring is appended only after real candidate decisions are finalized. The shadow output does not include `eligible`, `action`, `entry_mode`, or rejection fields, and the simulator does not branch on `enhanced_shadow_score` or `enhanced_shadow_decision` for entries/exits. Entries and exits remain governed by the existing catalyst, momentum, risk, price, and account logic.

### 6. Blocked catalysts and strong bearish catalysts prevent shadow `WOULD_ENTER`

Pass. The scorer hard-blocks configured blocked catalyst types, FDA regulatory catalysts, stale market data, wide spreads, and strong bearish catalysts (`catalyst_sentiment == "bearish"` with materiality at least `0.8`). Hard-blocked candidates receive score `0` and decision `WOULD_REJECT`, so they cannot become shadow `WOULD_ENTER`.

### 7. Monitoring exposes shadow aggregate counts and missed opportunities

Pass. The simulator aggregates `WOULD_ENTER`, `WATCH`, `WOULD_REJECT`, missed-opportunity counts, and top shadow symbols into `enhanced_shadow_stats`, stores them in simulator state as `last_shadow_stats`, and the monitoring API exposes them under `enhanced_shadow_stats`.

### 8. Dashboard labels the feature as shadow-only and not used for trading

Pass. The dashboard candidate table adds enhanced shadow columns and includes explicit shadow-only copy in the missed-opportunity banner and table footer stating that the enhanced score is not used for trading decisions and is independent of engine `eligible`/`action`/`entry_mode`.

### 9. No broker/live trading/real orders/AI/LLM/Ollama added

Pass. The Phase I4-A shadow scorer explicitly documents fake-money/no-live-trading/no-AI constraints and the module imports only `__future__` and typing utilities, with a local standard-library `math` import inside `_safe_float()`. The patch does not introduce broker/live-order integrations or AI/LLM/Ollama integrations.

### 10. No V6 hardcoded keys/auth/test endpoints copied

Pass. I found no V6 hardcoded keys, auth bypasses, or test endpoints in the reviewed Phase I4-A or frontend-runtime hardening diff. Existing monitoring notes that it is read-only/no-auth, but that was pre-existing and not a copied V6 key/auth/test endpoint pattern.

### 11. Tests and frontend build pass

Pass.

Commands run:

- `pytest -q backend/tests/test_phase_i4a.py` — passed: 10 passed, 1 warning.
- `(cd backend && pytest -q)` — passed: 1005 passed, 2 skipped, 2 warnings.
- `(cd frontend/dashboard && npm run build)` — passed.

### 12. Frontend runtime hardening does not change trading behavior and prevents stale Next.js chunk errors

Pass. The hardening patch changes frontend container startup/runtime behavior only: it uses named Docker volumes for `.next` and `node_modules`, deletes stale `.next` contents on startup, installs dependencies, builds, and then starts Next.js. It also removes `output: "standalone"` from Next config. These changes should prevent stale chunk/build artifact mismatches in the container and do not touch backend trading/simulator logic or dashboard decision semantics.

### 13. Safe for fake-money monitoring

Pass. The feature is appropriate for fake-money monitoring because it is diagnostic-only, visibly labeled as shadow-only, uses cached intelligence inputs, exposes aggregate monitoring, and does not alter trade execution paths or account state.

## Notes / Non-blocking Observations

- The Phase I4-A tests include direct unit coverage for premarket boost, Reddit boost, hard blocks, no Polygon calls, no ApeWisdom calls, no forbidden shadow-module imports, and shadow-field independence. The aggregate-count test simulates the aggregation logic rather than invoking a full simulator tick, but the implemented simulator aggregation is straightforward and was reviewed directly.
- Existing simulator market-data code can still call Polygon for normal quote/previous-close behavior when configured. That is not part of the enhanced shadow scoring path and does not violate the Phase I4-A requirement that scoring uses cached premarket intelligence only.

## Final Verdict

Approved for fake-money monitoring. No blockers found in the Phase I4-A enhanced shadow scoring patch or the separate frontend-runtime hardening patch.
