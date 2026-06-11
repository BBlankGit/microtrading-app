# Codex Review — Phase I6-H1 Provider Status + Test Fix

Review date: 2026-06-11  
Reviewed patch: `59655ce` (`Fix I6 provider status and tests`)  
Scope: latest I6-H1 patch only.

## Verdict

**Approved for fake-money monitoring.** I found no blocking issues in the I6-H1 patch.

The backend test suite passes, the frontend production build passes, provider status reporting is now honest for both unconfigured and configured-but-unwired providers, and the patch does not add real provider fetchers, external provider API calls, broker/live-trading behavior, real orders, or LLM calls.

## Checks performed

- `git diff --name-only HEAD^ HEAD`
- `git diff --function-context HEAD^ HEAD -- backend/intelligence/earnings.py backend/intelligence/insiders.py`
- `rg -n "score_candidate\(" backend/paper/simulator.py`
- `nl -ba backend/paper/simulator.py | sed -n '900,970p'`
- `rg -n "httpx|requests|aiohttp|AsyncClient|fetch\(|openai|anthropic|ollama|llm|broker|order|live trading|real orders" backend/api/intelligence.py backend/intelligence/earnings.py backend/intelligence/insiders.py backend/tests/test_phase_i6_h1.py backend/tests/test_phase_s1v1_h2.py frontend/dashboard/app/page.tsx`
- `pytest` from `backend/`
- `npm run build` from `frontend/dashboard/`

## 1. Backend pytest status

**Pass.** `pytest` completed successfully from `backend/`:

```text
1129 passed, 2 skipped, 2 warnings in 12.84s
```

The count differs from the commit message's historical `1117 passed, 14 skipped`, but the current branch's full backend suite passes.

## 2. `score_candidate` / `_q_for_paths` test meaningfulness

**Pass.** The rewritten test remains meaningful.

The AST-based assertion verifies all of the important semantics from the prior source-string test while being less brittle about formatting:

- `_q_for_paths` must be assigned inside `run_tick`.
- A `score_candidate(...)` call must exist.
- The second positional argument to that call must be the `ast.Name` `_q_for_paths`.
- The call must appear after the `_q_for_paths` assignment.

This still specifically protects against regressing to raw `q` as the scoring input. It also tolerates the Phase I6 keyword arguments `earnings_info` and `insider_info`, which is appropriate because those kwargs do not affect whether adjusted quality is passed positionally.

Manual source inspection confirms `run_tick` computes `_q_for_paths = dict(q, volume_ratio=_ta_ratio) if _use_ta_vol else q` and then calls `score_candidate(sym, _q_for_paths, cats, earnings_info=..., insider_info=...)`.

## 3. Provider `none` reports honest `not_configured`

**Pass.** For both earnings and insiders:

- Provider normalization maps empty/`none` to `not_configured`.
- `fetch_and_refresh()` returns `enabled: false`, `available: false`, `provider_status: "not_configured"`, `source: "none"`, empty `results`, and a warning explicitly saying no fake data is shown.
- Tests cover both modules' `none` behavior.

This is materially more honest than treating `enabled` as true merely because a provider-like string exists.

## 4. Configured-but-unwired `finnhub` / `polygon` statuses

**Pass.** Both earnings and insiders define `_WIRED_PROVIDERS` as an empty set for Phase I6-H1. Therefore any configured provider other than `none` is reported as:

- `provider_status: "configured_but_unwired"`
- `enabled: false`
- `available: false`
- empty `results`
- warning text saying no fetcher is implemented and no fake data is shown

The new tests cover `finnhub` and `polygon` for both earnings and insiders.

## 5. Frontend not_configured vs configured_but_unwired distinction

**Pass.** The dashboard now exposes both provider states clearly enough for operators:

- The `EarningsSnapshot` and `InsiderSnapshot` interfaces include optional `available` and `provider_status` fields.
- Warning banners trigger when either `enabled === false` or `available === false`.
- `configured_but_unwired` renders a specific message: the provider is configured, but no fetcher is implemented yet and no fake data is shown.
- `not_configured` renders a separate provider-not-configured message.
- The banner also displays `[provider_status: ...]`, making the backend state visible even if the text is later changed.

## 6. No real provider fetcher added

**Pass.** No real provider fetcher was added in this patch.

The only active-provider branch initializes `results_raw: list[dict] = []` and contains a note placeholder to populate it when a future real fetcher is wired. Because `_WIRED_PROVIDERS` is currently empty for both modules, that active branch is not reachable through normal configured `finnhub`/`polygon` settings in this patch.

## 7. No external API calls from provider stubs

**Pass.** The provider stubs do not make external API calls.

The changed earnings/insiders source files do not create an HTTP client or call `requests`, `httpx`, `aiohttp`, or provider SDKs. The only new `httpx` references are in tests that patch `httpx.AsyncClient.get` and `.post` to raise if an unwired branch tries to call out. Those tests pass.

Note: `frontend/dashboard/app/page.tsx` contains existing browser `fetch(...)` calls to the app's own API routes; the I6-H1 frontend changes only affect local dashboard status rendering for the earnings/insiders tabs.

## 8. No trading/scoring/entry/exit behavior changed beyond existing I6 behavior

**Pass.** The latest patch does not modify the simulator, entry, exit, broker, order, or scoring modules outside the I6 provider status/test/frontend files listed by `git diff --name-only HEAD^ HEAD`.

Within earnings/insiders, the patch changes provider availability/status semantics and cache payload metadata. The deterministic scoring functions still return zero adjustment when no symbol data exists, and the new tests assert that inactive provider paths contribute zero score/blocks.

One behavior change is intentional and safe: `is_enabled()` is now an alias for `is_available()`, so naming `finnhub`/`polygon` no longer makes an unwired provider appear enabled. That reduces false-positive provider readiness; it does not add new entry/exit or order behavior.

## 9. No broker/live trading/real orders added

**Pass.** The patch does not add broker integration, live trading, or real order code.

The changed backend intelligence modules explicitly remain read-only/fake-money modules, and the changed test file repeats the no-broker/no-live/no-real-orders invariant. No changed production file introduces order placement or broker client behavior.

## 10. No OpenAI/Anthropic/Ollama/LLM calls added

**Pass.** No OpenAI, Anthropic, Ollama, or LLM call path was added.

The only LLM-related strings in the changed production intelligence files are negative safety statements in module docstrings. The provider status patch is deterministic status/cache logic and frontend rendering.

## 11. Frontend build status

**Pass.** `npm run build` completed successfully from `frontend/dashboard/`:

```text
✓ Compiled successfully
✓ Generating static pages (4/4)
```

The command emitted npm's existing `Unknown env config "http-proxy"` warning, but the build exited with code 0.

## 12. Safe for fake-money monitoring

**Pass.** I6-H1 is safe for fake-money monitoring.

Reasons:

- Backend tests pass.
- Frontend build passes.
- Provider status is honest for unconfigured and configured-but-unwired states.
- No fake earnings/insider data is fabricated for unwired providers.
- Provider stubs do not call external APIs.
- No real provider fetcher was added.
- No broker, live trading, real order, or LLM behavior was introduced.
- Existing scoring remains deterministic and inactive-provider scoring remains neutral.

## Findings

No blocking or non-blocking code findings were identified in the scoped I6-H1 patch.
