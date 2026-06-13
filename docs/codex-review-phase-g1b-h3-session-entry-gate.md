# Codex Review — Phase G1B-H3 Session Entry Gate

**Reviewed commit:** `a2a1480 Block out-of-session fake entries (Phase G1B-H3)`  
**Review scope:** latest G1B-H3 patch only (`HEAD^..HEAD`).  
**Judgment:** **PASS WITH CAVEATS**

## 1. Executive summary

G1B-H3 materially fixes the G1B-H2 production risk: fake-money entries are now default-denied outside the regular US equity session unless an explicit extended-hours override is enabled. The new default configuration is regular-session-only, the central `paper.eod.entries_blocked()` helper now returns stable market-closed reasons for weekends, pre-open, and post-close, and the Engine entry branch chain checks that helper before any Engine `enter_position()` call.

The patch also gates deterministic-shadow and AI-shadow wallet entries by reusing the same `entries_blocked()` helper, while preserving LLM safety defaults (`LLM_SHADOW_ENABLED=false`) and not adding broker/live/order integrations. Existing out-of-session positions are no longer treated as normal: Engine positions are force-closed during the next tick when an exit price is available, shadow wallets run the same invalid-entry flatten sweep, and the API/dashboard annotate any remaining invalid open positions.

Caveats are mostly evidence/test-coverage caveats rather than blocking implementation gaps:

- No runtime evidence was included in the repository for an actual deployed weekend/closed-market tick or for the specific production TSLA position after remediation.
- Engine remediation is implemented in `run_tick()`, but the added tests directly exercise the shadow remediation helper and source invariants rather than a full Engine tick with an injected out-of-session Engine position.
- Dashboard invalid-position rows include wallet, symbol, and entry time, but the warning summary does not render `strategy_id` even though the backend warning includes it.

None of these caveats show an unprotected fake-entry path in the reviewed patch.

## 2. Findings

### Finding 1 — Universal regular-session entry gate is present and default-deny

**Status: PASS.**

The patch adds `PAPER_REGULAR_SESSION_ONLY=True` and `PAPER_ALLOW_EXTENDED_HOURS_ENTRIES=False` defaults in `Settings`, matching the required default-deny posture for fake-money entries outside Monday-Friday 09:30-16:00 America/New_York.

`paper.session` adds stable helpers for `entries_allowed_now()`, `entry_block_reason()`, and `is_valid_entry_time()`. `entry_block_reason()` distinguishes `market_closed_weekend`, `market_preopen`, and `market_postclose`, and `is_valid_entry_time()` treats only weekday 09:30 <= time < 16:00 ET as valid.

`paper.eod.entries_blocked()` now invokes this universal session gate before the legacy EOD cutoff. With the default settings, any non-regular-session timestamp returns blocked with a stable session reason.

### Finding 2 — Engine entry branches are gated before `enter_position()`

**Status: PASS.**

In `paper.simulator.run_tick()`, the patch calls `_eod.entries_blocked()` before the Engine branch chain. When blocked, the candidate is marked ineligible, receives `action` and `rejection_reason` set to the session-block reason, and the `elif` branch chain prevents all Engine branches from reaching `enter_position()`.

The protected branch chain includes:

- Path A catalyst entry;
- Path D market-mover no-catalyst entry;
- Path C no-catalyst momentum entry;
- Path B legacy momentum entry.

This preserves upstream scoring while blocking account mutation outside the session.

### Finding 3 — Deterministic Shadow and AI Shadow entries are gated

**Status: PASS.**

`paper.shadow_wallets.process_tick()` calls `_eod.entries_blocked()` before shadow entries and only invokes `_process_entries_for()` when entries are not blocked. Because the AI shadow entry processing is nested under the same blocked check and still requires `_llm_enabled()`, the same session gate protects AI shadow entries even if LLM shadow is explicitly enabled later.

### Finding 4 — Blocked candidates retain clear telemetry and auditability

**Status: PASS.**

Outside session, Engine candidates are not entered, are marked `eligible=False`, and receive the stable block reason in both `action` and `rejection_reason`. The candidate is still appended to `result["candidates"]` after shadow scoring / telemetry enrichment, so the rejected decision remains available for dashboard/API audit.

The patch does not modify score thresholds in the reviewed diff; it changes only whether an entry may execute after the existing scoring result.

### Finding 5 — Existing out-of-session positions are remediated or flagged

**Status: PASS WITH CAVEATS.**

The patch adds `OUT_OF_SESSION_REASON = "invalid_out_of_session_entry_flatten"` and `position_entry_is_out_of_session()`. Engine `run_tick()` sweeps current Engine positions whose entry timestamp falls outside regular session hours and force-closes them with that reason when an exit price is available. If no exit price is available, it appends a warning with `reason="missing_exit_price_invalid_session"` rather than silently treating the position as normal.

Shadow wallets add an `only_out_of_session` flatten mode and call it for both deterministic and AI wallets each tick before normal exit processing. This covers invalid out-of-session positions across Engine, DETERMINISTIC_SHADOW, and AI_SHADOW.

Caveat: invalid trades are labelable/excludable by the stable exit reason, but no dedicated freeze-metrics exclusion filter was added in this patch. That is acceptable for this phase if downstream freeze metrics already filter by exit reason, but should be verified before final freeze reporting.

### Finding 6 — Dashboard/API visibility is present

**Status: PASS WITH MINOR CAVEAT.**

`GET /api/paper/wallets` now includes session and invalid-position status fields: `market_session_open`, `entries_allowed`, `entry_block_reason`, `out_of_session_open_positions`, and `invalid_out_of_session_positions`.

`GET /api/paper/wallets/positions` annotates each position with `out_of_session` and emits warning objects containing wallet, strategy, symbol, entry time, reason, and remediation. The dashboard shows “Market closed — fake entries disabled” when entries are blocked and displays red warnings / OOS badges for invalid positions.

Minor caveat: the dashboard invalid-position warning renders wallet, symbol, entry time, and remediation, but not `strategy_id`, even though the backend includes `strategy_id` in the warning payload.

### Finding 7 — In-session Engine behavior appears preserved

**Status: PASS.**

The new gate is inactive during regular session. The patch does not change Engine score thresholds, TP/SL configuration, max-hold behavior, or the Engine entry branch scoring logic other than adding the pre-entry gate. Existing exit paths remain intact, with the only new exit reason being the invalid out-of-session remediation reason.

### Finding 8 — AI/LLM safety remains intact

**Status: PASS.**

`LLM_SHADOW_ENABLED` remains false by default. The G1B-H3 patch does not add OpenAI, DeepSeek, Groq, Mistral, Gemini, or paid AI calls. It does not alter the existing LLM selection/analysis path except that AI shadow wallet entries are blocked by the shadow-wallet session gate.

### Finding 9 — Broker/live/real-order safety remains intact

**Status: PASS.**

The reviewed patch does not add broker integration, live trading, real orders, real-money execution, Alpaca, IBKR, Robinhood, or order-placement code. The changed files remain in fake-money paper simulation, API annotation, dashboard display, and tests.

## 3. Evidence

### Changed files reviewed

- `backend/core/config.py`
- `backend/paper/session.py`
- `backend/paper/eod.py`
- `backend/paper/simulator.py`
- `backend/paper/shadow_wallets.py`
- `backend/api/paper.py`
- `frontend/dashboard/app/page.tsx`
- `backend/tests/test_phase_g1b_h2.py`
- `backend/tests/test_phase_g1b_h3.py`

### Key implementation evidence

- Defaults are regular-session-only and extended-hours entries are disabled by default.
- `entry_block_reason()` returns `market_closed_weekend`, `market_preopen`, or `market_postclose` outside regular session.
- `entries_blocked()` runs the universal session gate before the legacy EOD cutoff.
- Engine `run_tick()` checks `_eod.entries_blocked()` before all Engine entry branches and sets candidate `eligible=False`, `action`, and `rejection_reason` when blocked.
- Shadow wallet `process_tick()` checks `_eod.entries_blocked()` before deterministic and AI shadow wallet entries.
- Engine and shadow remediation uses `invalid_out_of_session_entry_flatten` for invalid out-of-session entries and emits missing-price warnings instead of silently leaving unremediated positions normal.
- API and dashboard expose market-closed / entries-disabled state and invalid out-of-session position warnings.

## 4. Tests reviewed

The new `backend/tests/test_phase_g1b_h3.py` covers:

- entries allowed during regular session;
- entries blocked on weekends;
- entries blocked before 09:30 ET;
- entries blocked after 16:00 ET;
- extended-hours override behavior;
- invalid TSLA-style Saturday 00:08 ET entry-time detection;
- stable invalid-entry flatten reason;
- deterministic shadow out-of-session remediation;
- missing-exit-price warning for invalid shadow position;
- API wallet session fields;
- API out-of-session position annotation;
- source-level invariants that Engine and shadow gates exist;
- frontend text checks for market-closed and OOS warnings;
- default `LLM_SHADOW_ENABLED=false`;
- no broker/live/order import tokens in selected modules.

I ran:

```bash
pytest backend/tests/test_phase_g1b_h3.py -q
```

Result: `29 passed, 2 skipped, 1 warning`.

Test coverage caveats:

- The tests do not include a full `run_tick()` integration test that injects an Engine position opened outside session and verifies it is closed with `invalid_out_of_session_entry_flatten`.
- The Engine branch protection test is primarily source/invariant based rather than four separate executable branch-entry tests for catalyst, market-mover, no-catalyst, and legacy momentum.
- AI shadow blocked-entry behavior is covered by the shared gate/source structure, but there is no explicit mocked LLM `WOULD_ENTER` closed-market executable test in the displayed test body.

These are recommended follow-up hardening tests, not observed runtime blockers in the implementation.

## 5. Runtime evidence reviewed

No Claude/runtime evidence file or deployment transcript for G1B-H3 was present in the latest patch. I therefore did **not** review independent evidence for:

- current deployed commit;
- backend health;
- frontend build;
- a weekend/market-closed tick in the deployed environment;
- confirmation that no new fake entries opened during that tick;
- status of the old TSLA Saturday 00:08 ET out-of-session position;
- dashboard/API live market-closed status;
- deployed wallet positions after remediation.

Because runtime evidence was not provided, this review is based on code inspection and the local G1B-H3 tests only.

## 6. Freeze-readiness judgment

**PASS WITH CAVEATS — freeze-ready for fake-money monitoring once deployed, with recommended runtime verification immediately after deployment.**

The reviewed code closes the blocking G1B-H2 issue: fake entries are default-denied outside regular US market hours across Engine, deterministic shadow, and AI shadow entry paths. Existing invalid out-of-session positions are either force-closed on the next tick when priced or flagged with explicit warnings if an exit price is unavailable.

This remains fake-money / paper-only. No broker integration, live trading, real orders, real-money execution, or paid AI calls were introduced.

The remaining caveats are operational assurance and test-hardening items rather than code blockers.

## 7. Required follow-up patches, if any

No blocking follow-up patch is required before deploying the G1B-H3 code for fake-money monitoring.

Recommended follow-ups:

1. Add executable full-tick tests for every Engine entry branch outside session: catalyst, market-mover no-catalyst, no-catalyst momentum, and legacy momentum.
2. Add a full-tick Engine remediation test that seeds an Engine position with `entry_time="2026-06-13T04:08:59+00:00"`, supplies an exit price, and asserts the position is closed with `invalid_out_of_session_entry_flatten`.
3. Add an explicit AI_SHADOW closed-market test with `LLM_SHADOW_ENABLED=true` and mocked `llm_decision="WOULD_ENTER"`, asserting no AI shadow position opens.
4. Render `strategy_id` in the dashboard invalid out-of-session warning rows, since the backend already provides it.
5. Capture and attach runtime evidence after deployment: deployed commit, backend health, one market-closed/weekend tick result, no new entries, TSLA invalid-position remediation/flag status, and `/api/paper/wallets` session status.
6. Verify freeze-performance reporting excludes or clearly labels trades exited with `invalid_out_of_session_entry_flatten`.
