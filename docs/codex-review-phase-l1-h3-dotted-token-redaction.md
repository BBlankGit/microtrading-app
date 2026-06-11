# Codex Review — Phase L1-H3 Dotted/Punctuation Token Redaction

Review target: latest patch `1110016 Harden dotted token redaction`.

Scope followed: review only; no application code changed. This document is the only intended repository change from this review.

## Executive verdict

**Approved for fake-money monitoring.** The L1-H3 patch correctly broadens known-secret value redaction from alphanumeric/underscore/hyphen values to dotted and punctuation-heavy values while preserving query delimiters and non-secret query parameters. The patch is limited to `backend/intelligence/llm_shadow.py` redaction logic plus `backend/tests/test_phase_l1_h3.py`; it does not alter trading/scoring/entry/exit, TP/SL/exit, broker, or order-placement behavior.

Backend tests and the frontend production build both pass.

## Patch reviewed

Latest patch files:

- `backend/intelligence/llm_shadow.py`
- `backend/tests/test_phase_l1_h3.py`

The code change replaces the previous secret-value character class with `_SECRET_VALUE_CHARS = r"A-Za-z0-9._/+=:%\-"`, then applies that class to the existing known-secret assignment redaction regex. The patch also documents the delimiter tradeoff and adds focused tests for dotted tokens, JWT-style values, percent-encoded values, slash/plus/base64 padding, colon-containing values, URL query strings, and short-value false-positive guards.

## Review checklist

| # | Focus area | Finding |
|---|---|---|
| 1 | Dotted query values like `token=abcdef.ghijkl` fully redacted | **Pass.** Known-secret assignments now allow `.` in the matched value, and tests assert both dotted segments disappear. |
| 2 | `access_token=abc.def.ghi` fully redacted | **Pass.** `access[_-]?token` remains a known secret key and dotted values are now consumed as one redacted value. |
| 3 | Punctuation-heavy values with `/ + = % : -` fully redacted for known secret keys | **Pass.** The L1-H3 value class explicitly includes `/`, `+`, `=`, `%`, `:`, and `-`; tests cover slash/plus/base64 padding, percent encoding, and colon-separated token scopes. |
| 4 | Non-secret query params preserved | **Pass.** Redaction is still key-name gated; tests verify `ticker=AAPL`, `limit=10`, and `symbol=AAPL` survive while secret params are redacted. |
| 5 | Short harmless values like `key=true` / `token=null` protected or tradeoff documented | **Pass.** The `{6,}` value-length guard remains, comments document the tradeoff, and tests assert `key=true` and `token=null` are unchanged. |
| 6 | Bearer token and `sk-*` redaction still work | **Pass.** Existing bare-secret patterns remain intact, and L1-H3 tests assert dotted Bearer tokens and OpenAI-style keys redact. |
| 7 | Env-style API key redaction still works | **Pass.** Env key names such as `OPENAI_API_KEY`, `POLYGON_API_KEY`, and other provider API-key forms remain in the known-secret key list; tests include quoted `OPENAI_API_KEY="sk-..."` and dotted `POLYGON_API_KEY=...`. |
| 8 | `marketdata_error`, `llm_error`, and `last_error` still route through redaction | **Pass.** `marketdata_error` is redacted in packet building; `_error_result` redacts `llm_error`; failure telemetry stores redacted `last_error`. |
| 9 | Full prompts are not logged | **Pass.** Prompt logging defaults off. The LLM call sends the packet to the provider when enabled, but the only success log records symbol, decision, confidence, and latency; it does not log the full prompt. |
| 10 | LLM remains shadow-only | **Pass.** Config and module comments keep LLM diagnostic-only, disabled by default, and simulator integration only attaches `llm_*` output fields. |
| 11 | No trading/scoring/entry/exit behavior changed | **Pass.** Latest patch touches only redaction and tests. Existing simulator code states and implements that LLM output never modifies `eligible`, `action`, or `entry_mode`. |
| 12 | No TP/SL/exit behavior changed | **Pass.** No exit, TP, SL, or position-management code is modified by the latest patch. |
| 13 | No broker/live trading/real orders added | **Pass.** LLM shadow module/API continue to state no broker/live trading/real orders; latest patch adds no broker/order code. |
| 14 | No new external API calls added | **Pass.** The only runtime code change is regex redaction. Existing OpenAI call remains gated by `LLM_SHADOW_ENABLED` and API-key presence; packet helpers still avoid new Polygon/news fetches. |
| 15 | Backend tests and frontend build pass | **Pass.** `pytest -q backend/tests/test_phase_l1_h3.py`, full backend `pytest -q`, and frontend `npm run build` all pass. |
| 16 | L1-H3 safe for fake-money monitoring | **Pass.** Redaction coverage improves without altering trading behavior or adding live-trading/order pathways. |

## Detailed notes

### Redaction behavior

- The L1-H3 character class includes alphanumerics plus `_`, `.`, `/`, `+`, `=`, `:`, `%`, and `-`, so JWT-like and URL/base64-like secret values are matched as a single value for known secret key names.
- Safe delimiters such as whitespace, `&`, comma, semicolon, quotes, and closing brackets/braces remain excluded. This is important for URL query strings: secret values stop at `&`, allowing later non-secret params to remain visible.
- The known-secret key list remains curated and includes provider env-style keys, API-key variants, `access_token`, `refresh_token`, bare `TOKEN`/`token`, and bare `key`.
- The minimum `{6,}` guard remains intentional. It prevents noisy redaction for short benign values such as `key=true`, `token=no`, and `token=null`; the test suite documents that dotted values crossing six characters, such as `key=v1.0.0`, will redact as the conservative security tradeoff.

### Logging and prompt handling

- `LLM_SHADOW_LOG_PROMPTS` remains `False` by default.
- The LLM request payload includes the structured packet as the provider prompt only when shadow analysis is enabled and an API key is present. The current logging path does not emit that payload; it logs only structured response metadata.
- Error text paths continue to call `_redact`, including packet-level `marketdata_error`, returned `llm_error`, retry `last_err`, and status `last_error`.

### Trading safety and external-call safety

- The latest patch does not modify simulator entry/exit decision logic, scoring logic, TP/SL handling, broker integrations, or order placement.
- LLM remains disabled by default and shadow-only. Simulator integration initializes safe default `llm_*` fields and, when enabled, copies returned LLM telemetry onto candidate rows only.
- No new external calls are introduced by L1-H3. The existing OpenAI call path is unchanged and remains gated; packet construction uses existing in-memory/context data and the cached intraday helper does not fetch Polygon.

## Commands run

```bash
git show --stat --oneline HEAD
git diff HEAD^..HEAD -- backend/intelligence/llm_shadow.py backend/tests/test_phase_l1_h3.py
pytest -q backend/tests/test_phase_l1_h3.py
pytest -q
npm run build
```

## Final assessment

L1-H3 closes the dotted-token leak identified in L1-H2-era redaction by ensuring `token=abcdef.ghijkl`, `access_token=abc.def.ghi`, and punctuation-heavy known-secret values are redacted as complete values instead of leaving suffixes visible. Non-secret query parameters are preserved. The short-value false-positive guard remains documented and tested. The change is safe for fake-money monitoring.
