# Codex Review: Phase 2S-H3 Dashboard Restart-Persistent StatBox Fix

## Scope

Reviewed only latest commit `6d04442` (`Fix hardcoded Restart Persistent false in status card StatBox`).

The commit changes one file only:

- `frontend/dashboard/app/page.tsx`

No backend files, strategy files, catalyst/no-catalyst logic, marketdata files, broker/live-trading code, AI/LLM/Ollama code, or real-order execution paths were changed by the reviewed commit.

## Review checklist

| # | Question | Result |
|---|---|---|
| 1 | Does the dashboard Account StatBox no longer hardcode Restart Persistent as `false`? | **Yes** |
| 2 | Does the StatBox now read `status.restart_persistent` from `/api/paper/dashboard`? | **Yes** |
| 3 | Does missing status render safely as `unknown` or equivalent, not `false`? | **No / issue found** |
| 4 | Was backend logic unchanged? | **Yes** |
| 5 | Was strategy/catalyst/no-catalyst/marketdata logic unchanged? | **Yes** |
| 6 | Were broker/live trading/real orders/AI/LLM/Ollama additions avoided? | **Yes** |
| 7 | Is this UI fix safe for fake-money monitoring? | **Mostly yes, with one display-safety caveat** |

## Evidence reviewed

### Commit footprint

`git diff --name-status 6d04442^ 6d04442` shows a single modified file:

```text
M	frontend/dashboard/app/page.tsx
```

The reviewed patch is a one-line UI change in the Account stat grid:

```diff
-            <StatBox label="Restart Persistent" value="false" cls="text-red-400" />
+            <StatBox label="Restart Persistent" value={s.restart_persistent ? "true" : "false"} cls={s.restart_persistent ? "text-green-400" : "text-red-400"} />
```

### `/api/paper/dashboard` data path

The frontend dashboard fetch function calls `/api/paper/dashboard` and stores the returned dashboard object in state. The main page then derives `const s = dashboard?.status`, and the Account section renders only when `s` is present.

The backend dashboard endpoint constructs the response with `status = simulator.get_status()` and returns it under the `status` key. `simulator.get_status()` includes a `restart_persistent` boolean in the status dictionary.

Therefore the changed StatBox now reads from `dashboard.status.restart_persistent`, which is the `status.restart_persistent` value returned by `/api/paper/dashboard`.

## Findings

### Finding 1 — Fixed hardcoded Account StatBox value

**Severity:** None / fixed by reviewed commit

The Account StatBox no longer renders the literal string `false`. It now renders `"true"` when `s.restart_persistent` is truthy and `"false"` otherwise, with green/red color matching the boolean value.

This satisfies the main H3 intent of removing the stale hardcoded `false` from the Account StatBox.

### Finding 2 — The StatBox consumes `/api/paper/dashboard` status data

**Severity:** None

The changed StatBox is under the Account section guarded by `s && (...)`, where `s` is assigned from `dashboard?.status`. The dashboard object is loaded by `fetchDashboard()`, which fetches `/api/paper/dashboard`.

The backend endpoint for `/api/paper/dashboard` returns `"status": status`, where `status` comes from `simulator.get_status()`. The simulator status includes `"restart_persistent": _state.get("restart_persistent", False)`.

This confirms the display source is the dashboard API status payload, not a local hardcoded value.

### Finding 3 — Missing `restart_persistent` still renders as `false`

**Severity:** Low / display correctness caveat

The new expression uses a truthiness check:

```tsx
value={s.restart_persistent ? "true" : "false"}
cls={s.restart_persistent ? "text-green-400" : "text-red-400"}
```

If the dashboard `status` object exists but the `restart_persistent` property is absent, `undefined` is falsy in JavaScript, so the StatBox renders `false` in red rather than `unknown` or an equivalent unknown/safe placeholder.

This does **not** reintroduce the old hardcoded literal, because real `true` values from the API will now render correctly. However, it does not fully satisfy the requested missing-field behavior. A stricter UI-safe pattern would distinguish `typeof s.restart_persistent === "boolean"` from missing/non-boolean values and render `unknown` when the field is absent.

Important nuance: if the whole `status` object is missing, the Account section does not render because it is guarded by `s && (...)`. The issue is specifically a present `status` object with missing `restart_persistent`.

## Negative-scope review

### Backend logic

No backend files were changed in commit `6d04442`. The existing backend dashboard/status path still returns simulator status under `/api/paper/dashboard`, and no backend persistence/session restore logic was modified by this commit.

### Strategy, catalyst, no-catalyst, and marketdata logic

The reviewed commit changes only `frontend/dashboard/app/page.tsx`. It does not modify strategy selection, catalyst/no-catalyst handling, candidate generation, universe/discovery behavior, or marketdata service logic.

### Broker/live trading/real orders/AI/LLM/Ollama

The reviewed commit adds no broker integration, no live-trading enablement, no real order path, and no AI/LLM/Ollama functionality. It is a read-only dashboard display change.

## Fake-money monitoring safety assessment

This UI-only change is safe for fake-money monitoring in the sense that it does not alter simulator state, trading behavior, broker connectivity, order placement, strategy behavior, or backend runtime logic. It improves monitoring accuracy when the API returns `restart_persistent: true`, because the Account StatBox will no longer misleadingly show `false`.

The remaining caveat is display fallback behavior: if `status.restart_persistent` is missing from the dashboard payload while `status` itself is present, the StatBox still displays `false` rather than `unknown`. That could mislead operators during an API/schema mismatch, although it would not cause trades or affect fake-money simulation behavior.

## Overall verdict

**Pass with one low-severity UI fallback caveat.**

Commit `6d04442` fixes the primary hardcoded Account StatBox problem and keeps the change limited to frontend display code. It does not change backend, strategy, marketdata, broker/live-trading, real-order, or AI/LLM/Ollama paths. The only incomplete point is that missing `status.restart_persistent` still displays as `false` due to JavaScript truthiness rather than rendering `unknown` or an equivalent safe placeholder.
