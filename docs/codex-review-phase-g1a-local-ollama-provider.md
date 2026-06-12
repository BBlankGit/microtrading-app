# Codex Review — Phase G1A Local Ollama LLM Provider

## Review scope

Reviewed only the latest G1A patch on `HEAD` (`ac6bbd1 Add local Ollama LLM provider`) against its parent. The patch changes:

- `backend/api/llm_shadow.py`
- `backend/core/config.py`
- `backend/intelligence/llm_shadow.py`
- `backend/tests/test_phase_g1a.py`
- `backend/tests/test_phase_l1.py`
- `infra/docker/docker-compose.yml`

No application code was changed during this review; this file is the only review artifact added.

## Executive summary

**G1A is directionally safe infrastructure for an optional local Ollama provider, but I found one material integration gap:** the simulator tick path still gates LLM execution on `api_key_present()`, so `provider=ollama` cannot actually run from normal ticks without a real-looking `OPENAI_API_KEY`. Direct diagnostic analysis via `/api/intelligence/llm/analyze-candidate` and the provider module do not require the key, but the production tick integration still does.

OpenAI is now optional, placeholder OpenAI keys are rejected, Ollama calls use only the configured `OLLAMA_BASE_URL`, docker-compose does not expose Ollama publicly, and malformed Ollama output is converted to `llm_status=error` rather than crashing the direct analysis path. The patch does not change trading/scoring/entry/exit/TP/SL/broker behavior and adds no paid external API calls.

## Material findings

### Finding 1 — `provider=ollama` is still blocked in the normal simulator tick path by `OPENAI_API_KEY`

**Severity:** Medium / product-functional gap  
**Status:** Open in G1A

The LLM provider module correctly treats Ollama as keyless, but the existing simulator integration still uses the old OpenAI-era gate:

- Candidate defaults are marked `missing_api_key` whenever LLM is enabled and `api_key_present()` is false.
- The tick only selects/builds/analyzes LLM packets when `is_enabled()` **and** `api_key_present()` are both true.

That means a normal fake-money tick with:

```env
LLM_SHADOW_ENABLED=true
LLM_PROVIDER=ollama
OPENAI_API_KEY=
```

will not call the local Ollama path and will mark candidate LLM status as `missing_api_key`, even though Ollama is intended to require no OpenAI key.

This does **not** create paid OpenAI calls and does **not** affect trading decisions, but it does mean the local/free provider path is not fully usable from normal ticks yet. The admin diagnostic endpoint still reaches `analyze_candidate_packet()` directly, where the provider-specific keyless Ollama checks are correct.

## Checklist review

| # | Review focus | Result | Evidence / notes |
|---:|---|---|---|
| 1 | `LLM_PROVIDER` defaults to `ollama`, not `openai` | **Pass** | `Settings.LLM_PROVIDER` is now `"ollama"`; helper fallback is also `ollama`. |
| 2 | `LLM_SHADOW_ENABLED` still defaults to `false` | **Pass** | `Settings.LLM_SHADOW_ENABLED` remains `False`. |
| 3 | `provider=ollama` does not require `OPENAI_API_KEY` | **Partial / Fail in tick path** | `analyze_candidate_packet()` does not key-gate Ollama, but simulator ticks still require `api_key_present()` before LLM analysis. |
| 4 | Placeholder OpenAI keys such as `optional_change_me` are invalid/missing and do not trigger OpenAI calls | **Pass** | Placeholder denylist includes `OPTIONAL_CHANGE_ME`; tests assert no OpenAI call with `optional_change_me`. |
| 5 | `provider=openai` remains optional and safely key-gated | **Pass** | OpenAI dispatch requires `api_key_present()` before `_openai_call()`. |
| 6 | Ollama provider calls only configured local `OLLAMA_BASE_URL` | **Pass** | Tags probe and generate URL are constructed from `ollama_base_url()`, which reads `settings.OLLAMA_BASE_URL`. No OpenAI branch is reachable when provider is `ollama`. |
| 7 | Ollama is not exposed publicly by docker-compose or config changes | **Pass** | Compose adds no Ollama service and no `11434` port mapping. |
| 8 | `host.docker.internal` / `host-gateway` wiring is safe and minimal | **Pass** | The only compose wiring is `extra_hosts` on the backend service, mapping `host.docker.internal:host-gateway`. |
| 9 | Status endpoint reports provider/model/base_url/local availability/model availability/api-key required/present | **Pass for endpoint with Ollama** | API now calls `get_status_async()`. Base status includes `provider`, `model`, `base_url`, `api_key_required`, and `api_key_present`; async Ollama status adds `local_provider_available`, `model_available`, and `models_installed`. |
| 10 | `provider_unavailable` and `model_missing` are handled safely | **Pass** | Ollama preflight returns `provider_unavailable` if tags cannot be reached and `model_missing` if configured model is absent. Tests cover both without generation calls. |
| 11 | Malformed Ollama JSON returns `llm_status=error` without crashing ticks | **Pass for provider/direct path; tick protected defensively** | Bad Ollama response raises internally, is caught by `analyze_candidate_packet()`, and returns `_error_result("error")`. The simulator LLM block is also wrapped defensively so exceptions do not break ticks. |
| 12 | LLM output remains shadow-only and cannot change `eligible`/`action`/`entry_mode` | **Pass** | The LLM module documents shadow-only behavior, normalized output has only `llm_*` fields, and tests assert no trading control fields in the default LLM shape. |
| 13 | No trading/scoring/entry/exit behavior changed | **Pass** | Latest patch did not modify trading/scoring/entry/exit modules; simulator logic was not changed by G1A. |
| 14 | No TP/SL/exit behavior changed | **Pass** | No exit/TP/SL files changed in the latest patch. |
| 15 | No broker/live trading/real orders were added | **Pass** | Patch files do not add broker integrations, live trading, or real-order code. Existing comments continue to say fake-money/no broker/no real orders. |
| 16 | No new paid external API calls were added | **Pass** | OpenAI remains behind explicit `provider=openai` and key gate; Ollama uses the local base URL. No other paid API client was added. |
| 17 | OpenAI calls are unreachable when `provider=ollama` | **Pass in provider module** | Dispatch calls `_ollama_call()` in the non-OpenAI branch after `prov == "ollama"`; `_openai_call()` is only called when `prov == "openai"`. |
| 18 | Tests pass; pre-existing flaky/failing tests noted separately | **Pass for LLM/G1A tests; one unrelated full-suite failure** | G1A/L1 targeted tests passed. Full backend suite had one failure in `test_phase_2t.py` looking for an exact frontend rejection-reason expression; this appears unrelated to G1A because the latest patch did not touch frontend files. |
| 19 | Runtime evidence supports keeping LLM disabled for now because `qwen2.5:7b-instruct` is too slow and returns malformed JSON on full packets | **Prudent, but not fully evidenced in committed patch** | The patch defaults LLM disabled and tests malformed JSON handling. I did not find committed benchmark/log evidence in G1A proving qwen full-packet slowness or malformed full-packet behavior. Given the default-disabled posture and malformed-output test, keeping it disabled until model/runtime evidence improves is the safe decision. |
| 20 | G1A is safe infrastructure, even if selected local model is not production-ready | **Mostly pass, with Finding 1 caveat** | Status/admin diagnostic/provider infrastructure is safe and optional. Normal tick-path Ollama activation needs a follow-up to remove the OpenAI-key gate for `provider=ollama`. |

## Detailed evidence

### Defaults and provider/key gating

`backend/core/config.py` now makes LLM shadow disabled by default, defaults the provider to Ollama, defaults the model to `qwen2.5:7b-instruct`, and adds local Ollama base/probe configuration.

`backend/intelligence/llm_shadow.py` rejects common placeholder keys, including `OPTIONAL_CHANGE_ME` and values containing `CHANGE_ME`, `CHANGEME`, or `PLACEHOLDER`. The provider helper defaults to `ollama`; the OpenAI branch checks `api_key_present()` before any OpenAI call; the Ollama branch does not check the OpenAI key.

The remaining issue is outside the patched provider dispatch: `backend/paper/simulator.py` still has old comments and logic saying LLM runs only when enabled and the API key is present. That makes the normal tick path inconsistent with the new keyless Ollama provider.

### Ollama locality and docker exposure

The Ollama tags probe and generation call build URLs only from `OLLAMA_BASE_URL` via `ollama_base_url()`:

- `/api/tags` for availability/model checks.
- `/api/generate` for local generation.

`infra/docker/docker-compose.yml` adds only backend `extra_hosts` mapping for `host.docker.internal:host-gateway`. It does not add an Ollama container, does not publish host port `11434`, and does not expose Ollama publicly.

### Status endpoint

The status API changed from synchronous `get_status()` to async `get_status_async()`, which means the endpoint can report local Ollama availability/model presence without triggering generation. For `provider=ollama`, the endpoint reports:

- `provider`
- `model`
- `base_url`
- `local_provider_available`
- `model_available`
- `models_installed`
- `api_key_required`
- `api_key_present`

The probe is cached for 30 seconds to reduce dashboard polling overhead.

### Error handling

Ollama readiness failures short-circuit safely:

- Tags unreachable -> `llm_status="provider_unavailable"`
- Configured model absent -> `llm_status="model_missing"`
- Bad/malformed generation response -> `llm_status="error"`

The direct analysis function never raises to callers on provider errors; it returns stable error shapes. The simulator LLM block is also surrounded by a defensive `try/except`, so even unexpected LLM exceptions are logged and do not break ticks.

### Shadow-only / no trading behavior changes

The G1A patch touches the LLM API/provider/config/tests and docker-compose only. It does not change the simulator entry/exit logic, scoring modules, TP/SL/exit modules, broker/live-trading wiring, or frontend trading controls. LLM results remain `llm_*` telemetry fields and are not control fields such as `eligible`, `action`, or `entry_mode`.

## Tests and checks run

```bash
git show --stat --oneline HEAD
git show --name-only --format='' HEAD
rg -n "llm_shadow|analyze_candidate_packet|record_tick_call|llm_" backend -g '!*.pyc'
python -m pytest backend/tests/test_phase_g1a.py backend/tests/test_phase_l1.py backend/tests/test_phase_l1_h2.py backend/tests/test_phase_l1_h3.py
python -m pytest backend/tests
```

Results:

- `python -m pytest backend/tests/test_phase_g1a.py backend/tests/test_phase_l1.py backend/tests/test_phase_l1_h2.py backend/tests/test_phase_l1_h3.py`: **100 passed**, 1 warning.
- `python -m pytest backend/tests`: **1316 passed, 2 skipped, 1 failed**, 2 warnings.
  - Failure: `backend/tests/test_phase_2t.py::test_frontend_renders_rejection_reason_before_decision_reason` expects the exact string `c.rejection_reason || c.decision_reason` in `frontend/dashboard/app/page.tsx`.
  - This appears unrelated to G1A because the latest patch did not modify frontend files.

## Recommendation

Do **not** turn on LLM shadow in normal ticks yet.

G1A is safe to keep as optional infrastructure, but follow-up work should:

1. Replace the simulator's `api_key_present()` gate with provider-aware readiness logic so `provider=ollama` can run without `OPENAI_API_KEY`.
2. Keep `LLM_SHADOW_ENABLED=false` by default until the selected local model reliably returns valid JSON fast enough on full candidate packets.
3. Add committed runtime evidence/benchmark notes for the chosen local model and prompt packet size before considering production-style shadow monitoring.
