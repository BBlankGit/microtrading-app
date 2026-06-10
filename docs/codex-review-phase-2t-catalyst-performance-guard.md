# Codex Review — Phase 2T Catalyst Performance Guard

Date: 2026-06-10  
Repository: `BBlankGit/microtrading-app`  
Scope: latest Phase 2T catalyst-performance guard implementation present in this checkout, plus the latest Phase 2T test-only patch at `HEAD`.

## Executive summary

Phase 2T is **partially correct and generally safe for fake-money monitoring**, but I do **not** recommend treating it as fully complete without a follow-up patch.

The good news:

- `fda_regulatory` is configured as the default blocked catalyst type.
- The simulator creates a hard rejection before catalyst entry when the **first** catalyst's `classified_event_type` is in the configured block list.
- That hard rejection prevents catalyst entry even when the score passes.
- The hard rejection also prevents the no-catalyst and momentum fallback paths from firing because it is not marked as an `is_no_catalyst_rejection`.
- `earnings` and `m_and_a` are not blocked by default.
- No broker/live-trading/real-order/AI/LLM/Ollama behavior was added in the reviewed Phase 2T surfaces.

The material issues:

1. **Dashboard candidate rows can hide the catalyst-type block reason.** The backend candidate has `rejection_reason = catalyst_type_blocked:<type>`, but the dashboard renders `decision_reason || rejection_reason`; for a score-passing blocked candidate, `decision_reason` can be `pass`, so the visible candidate table may show `pass` instead of the block reason.
2. **Only the first accepted catalyst is checked.** If a candidate has multiple accepted catalysts and a blocked catalyst appears after the first item, the Phase 2T block does not fire.
3. **Runtime validation only validates that `PAPER_BLOCKED_CATALYST_TYPES` is a string.** It exposes and parses the list, but it does not validate CSV token format, known catalyst types, empty tokens beyond filtering, duplicates, or suspicious values.
4. **Patch hygiene is mixed.** The Phase 2T implementation lines are blamed to commit `865cc9e`, which also changed Redis/session restore integrity code. The latest `HEAD` patch only adds Phase 2T tests, but the implementation commit itself is not isolated to Phase 2T.

## Commands run

```bash
git status --short
git log --oneline -5
git show --stat --oneline HEAD
git show --name-only --format='' HEAD
rg -n "PAPER_BLOCKED_CATALYST_TYPES|blocked catalyst|catalyst.*block|phase 2t|Phase 2T|fda_regulatory|m_and_a|earnings|blocked_catalyst" -S .
git blame -L 65,115 backend/core/config.py
git blame -L 80,115 backend/paper/runtime_config.py
git blame -L 200,230 backend/api/monitoring.py
git show --stat --oneline 865cc9e
git show --name-only --format='' 865cc9e
sed -n '1,150p' backend/core/config.py
sed -n '70,125p' backend/paper/runtime_config.py
sed -n '560,615p' backend/paper/runtime_config.py
sed -n '430,505p' backend/paper/runtime_config.py
rg -n "catalyst_type_blocked|blocked_catalyst|PAPER_BLOCK_STRONG_NEGATIVE|blocked_catalyst_types_list|hard_rejection|is_no_catalyst_rejection|Path A|entry_mode|no_catalyst" backend/paper/simulator.py
nl -ba backend/paper/simulator.py | sed -n '570,760p'
nl -ba backend/paper/simulator.py | sed -n '755,890p'
nl -ba backend/api/monitoring.py | sed -n '205,245p'
nl -ba frontend/dashboard/app/page.tsx | sed -n '70,110p'
nl -ba frontend/dashboard/app/page.tsx | sed -n '714,776p'
nl -ba frontend/dashboard/app/page.tsx | sed -n '2428,2448p'
nl -ba backend/tests/test_phase_2t.py | sed -n '168,560p'
PYTHONPATH=backend pytest -q backend/tests/test_phase_2t.py
rg -n "openai|anthropic|langchain|ollama|alpaca|ibapi|tastytrade|td_ameritrade|schwab|place_order|submit_order|execute_order|send_order|broker" backend/paper backend/core backend/api/monitoring.py frontend/dashboard/app/page.tsx backend/tests/test_phase_2t.py
git diff --name-only e49d03c..HEAD -- backend/paper/marketdata_adapter.py backend/paper/exits.py backend/paper/session_restore.py backend/paper/simulator.py backend/core/config.py backend/paper/runtime_config.py backend/api/monitoring.py frontend/dashboard/app/page.tsx backend/tests/test_phase_2t.py
```

Test result: `34 passed, 1 warning in 0.24s` for `backend/tests/test_phase_2t.py`.

## Latest-patch / implementation-scope note

`HEAD` is `fdee234 Add catalyst type performance guard`, and `git show --stat HEAD` shows it adds only `backend/tests/test_phase_2t.py`. The implementation currently in the tree is blamed to commit `865cc9e Harden paper Redis state restore integrity`, which also changed Phase 2T implementation surfaces (`backend/core/config.py`, `backend/paper/runtime_config.py`, `backend/paper/simulator.py`, `backend/api/monitoring.py`, and `frontend/dashboard/app/page.tsx`) and Redis/session restore files.

For that reason, this review treats the current Phase 2T behavior as the implementation under review, while separately calling out where the implementation patch was not isolated.

## Requirement-by-requirement review

| # | Requirement | Result | Review notes |
|---|---|---|---|
| 1 | Configured blocked catalyst types are blocked before entry | **Partial pass** | The simulator computes `_blocked_cat_types` once per tick and sets `hard_rejection = catalyst_type_blocked:<type>` before Path A catalyst entry. However, it checks only `cats[0].classified_event_type`, not every accepted catalyst. |
| 2 | `fda_regulatory` can be blocked by `PAPER_BLOCKED_CATALYST_TYPES` | **Pass** | Default config sets `PAPER_BLOCKED_CATALYST_TYPES = "fda_regulatory"`, runtime parsing returns normalized list entries, and simulator blocks `cat_type in _blocked_cat_types`. |
| 3 | `earnings` and `m_and_a` are not blocked by default | **Pass** | The default block list contains only `fda_regulatory`; tests cover `earnings` and `m_and_a` as eligible when score and quality pass. |
| 4 | Blocked catalyst types cannot enter even if score passes | **Partial pass** | True for the first accepted catalyst type. A score-passing `fda_regulatory` first catalyst is hard-rejected. But a blocked catalyst after the first accepted catalyst can be missed. |
| 5 | No-catalyst path cannot bypass a blocked catalyst | **Pass for first-catalyst block; partial overall** | When the Phase 2T block fires, it explicitly clears `is_no_catalyst_rejection`, so Path C and momentum fallback cannot enter. The same first-catalyst limitation applies. |
| 6 | Candidate/dashboard/monitoring output shows catalyst-type block reasons | **Partial fail** | Candidate output includes `rejection_reason` and `catalyst_type_blocked`; monitoring exposes enabled/list/count; dashboard status exposes list/count. But the candidate table renders `decision_reason || rejection_reason`, which can hide `catalyst_type_blocked:<type>` behind `pass`. |
| 7 | Runtime config validates/exposes blocked catalyst type list | **Partial pass** | Runtime config schema exposes the field, effective config returns it, and helper parsing normalizes it. Validation only enforces `str`, not list token correctness or known catalyst types. |
| 8 | Marketdata cache logic was not changed | **Pass for latest `HEAD`; no Phase 2T-specific cache change found** | Latest `HEAD` changes only Phase 2T tests. The Phase 2T implementation reuses existing stale-marketdata gating and does not modify marketdata adapter/cache files in the checked surfaces. |
| 9 | TP/SL/intrabar exit logic was not changed | **Pass** | Phase 2T references are absent from `backend/paper/exits.py`; no exit-path change was found in the latest Phase 2T test patch. |
| 10 | Redis restore/session integrity logic was not changed | **Fail as patch-hygiene finding for implementation commit** | The implementation lines are blamed to `865cc9e`, and that same commit also changed `backend/paper/session_restore.py` and related Redis/session files. Latest `HEAD` did not change those files, but the Phase 2T implementation was not isolated from Redis/session integrity changes. |
| 11 | No broker/live trading/real orders/AI/LLM/Ollama were added | **Pass** | Searches found only fake-money/no-broker disclaimers and test forbidden-token checks in the reviewed Phase 2T surfaces; simulator status remains `broker_connected = False`. |
| 12 | Phase 2T is safe for fake-money monitoring | **Pass with caveats** | No live execution path was added, and the guard is conservative when it fires. Caveats: dashboard visibility, first-catalyst-only detection, runtime list validation, and mixed implementation commit scope should be fixed before calling Phase 2T complete. |

## Detailed findings

### Finding 1 — Dashboard candidate table can hide catalyst-type block reasons

Severity: **Medium**

Backend candidate dictionaries correctly include both the hard rejection and the `catalyst_type_blocked` flag. For a blocked candidate, simulator code initializes `rejection_reason` from `hard_rejection`, and the Phase 2T block sets the hard rejection to `catalyst_type_blocked:<cat_type>`.

However, the dashboard candidate table renders:

```tsx
{c.decision_reason || c.rejection_reason || "—"}
```

A blocked candidate can still have a score-passing `decision_reason` such as `pass` because scoring is intentionally computed before hard entry gates. In that common case, the visible candidate row shows `pass` rather than `catalyst_type_blocked:fda_regulatory`.

Impact:

- Requirement 6 is only partially met.
- Operators may not see the actual Phase 2T block reason in the candidate table even though the backend candidate payload contains it.

Suggested fix:

- Render hard rejection first, e.g. `c.rejection_reason || c.decision_reason || "—"`.
- Optionally add a visible badge when `c.catalyst_type_blocked` is true.
- Add a frontend/unit or snapshot-style test proving blocked rows show `catalyst_type_blocked:<type>` instead of `pass`.

### Finding 2 — The guard checks only the first accepted catalyst

Severity: **High**

The simulator derives:

```python
cat_type = cats[0].get("classified_event_type") if cats else None
```

Then it blocks only that `cat_type` when it appears in `_blocked_cat_types`.

Impact:

- If accepted catalysts are ordered as `[earnings, fda_regulatory]`, the candidate is treated as `earnings`, not blocked by Phase 2T, and can enter if score passes.
- This undermines requirements 1, 4, and 5 for multi-catalyst candidates.

Suggested fix:

- Build normalized catalyst types from all accepted catalysts, e.g. `cat_types = [...]`.
- Block if **any** accepted catalyst type is in the configured block set.
- Store the matched blocked type in the rejection reason and candidate output.
- Add a regression test with an unblocked first catalyst and a blocked second catalyst.

### Finding 3 — Runtime config validation is too loose for a blocked catalyst list

Severity: **Medium**

`PAPER_BLOCKED_CATALYST_TYPES` is present in `_SCHEMA`, exposed in effective config/schema output, and parsed by `blocked_catalyst_types_list()`. Validation, however, only checks that the value is a Python string. It does not validate allowed characters, normalize during validation, reject malformed CSV tokens, or check against a known catalyst taxonomy.

Impact:

- Requirement 7 is only partially met if “validates list” means validating the list contents.
- Operators can set values that parse into surprising tokens or typoed catalyst types with no feedback.

Suggested fix:

- Add field-specific validation for comma-separated normalized catalyst tokens, such as `^[a-z0-9_]+$`.
- Consider rejecting duplicate tokens and/or warning on unknown catalyst types.
- Add tests for whitespace, uppercase normalization, invalid characters, empty-only strings, and duplicates.

### Finding 4 — Phase 2T implementation is mixed with Redis/session restore changes

Severity: **Low/Medium patch hygiene**

The latest `HEAD` patch adds only `backend/tests/test_phase_2t.py`, but the Phase 2T implementation currently in the tree is blamed to `865cc9e`, a commit titled `Harden paper Redis state restore integrity`. That same commit changed Phase 2T code and Redis/session restore code.

Impact:

- Requirement 10 is not satisfied if the “implementation patch” is interpreted as commit `865cc9e`.
- It makes review provenance harder because catalyst-entry behavior and session-restore integrity changes are coupled in one implementation commit.

Suggested fix:

- No code behavior change is necessarily required for Phase 2T safety from this finding alone.
- Future patches should isolate catalyst-guard changes from Redis/session restore changes.
- If possible, document that the current `HEAD` test patch only adds tests and does not touch session restore.

## Positive observations

- The default config blocks `fda_regulatory` and does not include `earnings` or `m_and_a`.
- The simulator computes blocked catalyst types once per tick and applies the guard before Path A catalyst entry.
- When the guard fires, it sets a hard rejection and does not mark the rejection as no-catalyst eligible, so no-catalyst Path C and momentum fallback do not bypass the block.
- Monitoring exposes `catalyst_type_guard.enabled`, `blocked_catalyst_types`, `blocked_candidates_last_tick`, and a fake-money/no-real-orders disclaimer.
- The dashboard monitoring status card displays the guard status, blocked list, and blocked count.
- Phase 2T tests cover default `fda_regulatory`, guard disablement, score-pass blocking, no-catalyst bypass prevention, `earnings`, `m_and_a`, multiple configured blocked types one at a time, and no broker/AI imports.
- The reviewed Phase 2T logic does not alter TP/SL/intrabar exit code.
- The reviewed Phase 2T surfaces preserve fake-money/no-broker/no-real-order boundaries.

## Final recommendation

Approve Phase 2T only as a **fake-money monitoring guard with caveats**, not as fully complete. Before relying on it as a complete catalyst-performance guard, ship a follow-up patch that:

1. Blocks when **any** accepted catalyst type is configured as blocked.
2. Makes dashboard candidate rows prioritize hard rejection reasons over scoring decision text.
3. Adds real content validation for `PAPER_BLOCKED_CATALYST_TYPES`.
4. Keeps future Phase 2T changes isolated from Redis/session integrity changes.
