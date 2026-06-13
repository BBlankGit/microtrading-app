# Codex Review — Phase G1A-H1 Provider-Aware LLM Gate

Review date: 2026-06-13  
Repository: `BBlankGit/microtrading-app`  
Reviewed patch: `287febed7957cb42df8a1fd84eeb21256173b29c` (`Fix provider-aware LLM simulator gate`)  
Scope: latest G1A-H1 patch only

## Verdict

**PASS with one unrelated full-suite test failure noted.**

The G1A-H1 patch closes Codex Finding 1 from G1A: the paper simulator no longer uses the OpenAI-era `api_key_present()` gate to decide whether normal simulator ticks may run LLM analysis. The simulator now uses a provider-aware `simulator_ready()` helper, which allows `provider=ollama` without `OPENAI_API_KEY`, preserves the OpenAI key requirement for `provider=openai`, and keeps LLM disabled by default.

The patch is tightly scoped to:

- `backend/intelligence/llm_shadow.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase_g1a_h1.py`

No trading/scoring/entry/exit logic, TP/SL logic, broker/live-order code, or paid external API integration was changed by this patch.

## Scope Check

Command reviewed:

```bash
git diff --name-only HEAD^ HEAD
```

Changed files:

```text
backend/intelligence/llm_shadow.py
backend/paper/simulator.py
backend/tests/test_phase_g1a_h1.py
```

This matches the expected G1A-H1 scope: one provider-readiness helper, one simulator gate replacement, and regression tests.

## Findings by Requested Focus Area

### 1. Normal simulator ticks can use `provider=ollama` without `OPENAI_API_KEY`

**PASS.**

`simulator_ready()` returns `(True, "not_selected")` whenever LLM is enabled and `provider()` resolves to `ollama`; it does not check `OPENAI_API_KEY` in that branch. The normal simulator tick binds that result and uses `_llm_ready` as the selector/analyzer gate.

Evidence:

- `simulator_ready()` returns ready for Ollama without an API-key precondition.
- `run_tick()` uses `_llm_mod.simulator_ready()` and gates the analyzer on `_llm_ready`.
- Regression tests explicitly cover Ollama without `OPENAI_API_KEY`.

### 2. `provider=openai` still requires a valid key

**PASS.**

For OpenAI, `simulator_ready()` still calls `api_key_present()` and returns `(False, "missing_api_key")` if the key is absent or placeholder-like. `analyze_candidate_packet()` independently enforces the same OpenAI pre-flight check before any network call.

### 3. `provider=ollama` never calls OpenAI

**PASS.**

The analyzer selects the provider branch once via `prov = provider()`. The OpenAI call path is reachable only when `prov == "openai"`; the Ollama branch probes the local provider and later calls `_ollama_call()`. `_openai_call()` posts to `https://api.openai.com/v1/chat/completions`, but it is not selected for `provider=ollama`.

### 4. Placeholder OpenAI keys still prevent OpenAI calls

**PASS.**

`api_key_present()` rejects placeholder values including `OPTIONAL_CHANGE_ME`, plus values containing `CHANGE_ME`, `CHANGEME`, or `PLACEHOLDER`. With `provider=openai`, both `simulator_ready()` and `analyze_candidate_packet()` short-circuit to `missing_api_key` before `_openai_call()` can run.

Regression coverage also monkeypatches `httpx.AsyncClient.post` to raise if an OpenAI POST is attempted with `OPENAI_API_KEY=optional_change_me`; the test passes.

### 5. Missing/unsupported/local-provider errors are reported safely

**PASS.**

The error surface remains stable and redacted:

- Disabled LLM returns `llm_status="disabled"`.
- Missing or placeholder OpenAI key returns `llm_status="missing_api_key"`.
- Unsupported provider returns `llm_status="provider_not_supported"`.
- Unreachable Ollama returns `llm_status="provider_unavailable"`.
- Missing local model returns `llm_status="model_missing"`.
- `_error_result()` redacts any supplied error text before exposing it in `llm_error`.

### 6. LLM remains disabled by default

**PASS.**

The default configuration keeps `LLM_SHADOW_ENABLED: bool = False`. The default provider is local Ollama, but it remains inert unless the shadow analyst is explicitly enabled.

### 7. Candidate `llm_status` is no longer incorrectly `missing_api_key` for `provider=ollama`

**PASS.**

The simulator now derives candidate default status from `simulator_ready()`'s second return value. For enabled Ollama, that value is `"not_selected"`, not `"missing_api_key"`. Picked candidates that encounter an unreachable local Ollama endpoint report `"provider_unavailable"`, also not `"missing_api_key"`.

### 8. No trading/scoring/entry/exit behavior changed

**PASS.**

The simulator patch is confined to the LLM shadow section. It initializes candidate LLM telemetry defaults, resets LLM counters, and decides whether to run LLM shadow analysis. The patch does not alter candidate scoring, eligibility, action, entry mode, entry execution, or exit execution logic.

The new regression test also asserts that the default LLM result still excludes trading-decision keys such as `eligible`, `action`, `entry_mode`, `score_pass`, `rejection_reason`, and `decision_reason`.

### 9. No TP/SL/exit behavior changed

**PASS.**

The reviewed diff does not touch TP/SL settings, bracket-exit evaluation, virtual-account exit code, or exit persistence. The only simulator change is within the LLM shadow diagnostic block.

### 10. No broker/live trading/real orders were added

**PASS.**

No broker, live-trading, or order-management modules were added or imported by the G1A-H1 patch. Existing safety language in the LLM module still states fake-money simulation only and no broker/live/real orders.

### 11. No paid external API calls were added

**PASS.**

The patch does not add a new paid external API integration. It only changes the simulator readiness gate and adds tests. Existing OpenAI support remains optional and gated behind `provider=openai` plus a non-placeholder key. Ollama calls target the configured local `OLLAMA_BASE_URL`.

### 12. Tests pass

**PARTIAL / TARGETED PASS; FULL-SUITE UNRELATED FAILURE.**

Targeted G1A-H1 regression tests pass:

```bash
cd backend && pytest tests/test_phase_g1a_h1.py -q
```

Result:

```text
15 passed, 1 warning in 0.25s
```

Full backend suite command:

```bash
cd backend && pytest -q
```

Result:

```text
1 failed, 1331 passed, 2 skipped, 2 warnings in 22.70s
```

Failure:

```text
FAILED tests/test_phase_2t.py::test_frontend_renders_rejection_reason_before_decision_reason
AssertionError: rejection_reason || decision_reason not found in page.tsx
```

This failure is outside the G1A-H1 patch scope: the latest patch did not modify `frontend/dashboard/app/page.tsx` or `backend/tests/test_phase_2t.py`.

### 13. G1A-H1 closes Codex Finding 1 from G1A

**PASS.**

Finding 1 was that normal paper-simulator ticks still gated LLM analysis on `api_key_present()`, blocking local Ollama when no valid `OPENAI_API_KEY` existed. G1A-H1 removes that direct simulator gate and replaces it with provider-aware readiness. For enabled Ollama, the simulator proceeds to selection/analyzer flow without an OpenAI key; actual local availability is handled by `analyze_candidate_packet()` with local-provider statuses.

## Review Notes

- The simulator comment above section 4c still says "AND the API key is present". That comment is now stale for local providers, but it is not behavior-changing. A future cleanup patch could reword it to "provider-aware LLM readiness".
- The new test file contains 15 tests in this workspace, while the commit message mentions 14 cases. This is harmless documentation drift in the commit message only.

## Final Determination

G1A-H1 is acceptable for the provider-aware simulator LLM gate. It correctly restores the local Ollama path for normal paper ticks, preserves OpenAI key safety, keeps LLM disabled by default, and does not alter trading behavior.
