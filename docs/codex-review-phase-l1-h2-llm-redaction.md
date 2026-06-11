# Codex Review — Phase L1-H2 LLM Secret Redaction Hardening

## Scope

Reviewed only the latest L1-H2 patch in `BBlankGit/microtrading-app`:

- Commit reviewed: `41c3944 Harden LLM secret redaction`
- Files changed by the reviewed patch:
  - `backend/intelligence/llm_shadow.py`
  - `backend/tests/test_phase_l1_h2.py`

This review did not intentionally modify application code.

## Executive Verdict

**Conditionally safe for fake-money monitoring.** The patch is narrowly scoped to LLM-shadow redaction and tests. It does not change trading, scoring, entry, exit, TP/SL, broker, or order-placement behavior, and it does not add new production external API calls.

The main hardening goals are met for the credential formats covered by the implementation and tests: Bearer headers, OpenAI-style `sk-*` keys, common secret-bearing query/assignment names, `marketdata_error`, `llm_error`, and `llm_status.last_error` all route through `_redact()`.

One follow-up is recommended before treating the redactor as comprehensive for all access-token shapes: **query/assignment values containing punctuation such as dots can be partially or not redacted** because `_SECRET_ASSIGN_PATTERN` only treats `[A-Za-z0-9_-]{6,}` as the secret value. This matters most for `token=` / `access_token=` values that may be JWT-like or otherwise dotted.

## Review Checklist

| # | Focus area | Result | Notes |
|---|---|---|---|
| 1 | Bearer tokens and `sk-*` keys | Pass | `_BARE_SECRET_PATTERNS` redacts `sk-...` keys and case-insensitive `Bearer ...` values, with tests for both. |
| 2 | Query params `apiKey` / `apikey` / `key` / `token` / `access_token` / `api_key` | Mostly pass, with caveat | Covered for alphanumeric, underscore, and hyphen values of length >= 6. Dotted or punctuation-heavy values can leak suffixes or fail to match. |
| 3 | Env/assignment style `POLYGON_API_KEY`, `FINNHUB_API_KEY`, `NEWSAPI_KEY`, `NEWS_API_KEY`, `OPENAI_API_KEY`, `API_KEY`, `TOKEN` | Pass | Secret-name alternation includes the requested env names, and assignment-style redaction preserves names while replacing values. |
| 4 | `marketdata_error` in LLM packets redacted | Pass | `build_candidate_packet()` applies `_redact()` before writing `marketdata.marketdata_error`; integration tests cover env-style and URL query examples. |
| 5 | `llm_error` / status error text redacted | Pass | `_error_result()` redacts `llm_error`; `analyze_candidate_packet()` redacts exception text before storing `_status["last_error"]`. |
| 6 | Full prompts are not logged | Pass | The reviewed patch does not enable prompt logging; the only production logger call in the LLM path logs symbol, decision, confidence, and latency, not the packet/prompt body. |
| 7 | Redaction avoids excessive false positives | Pass with tradeoff | The minimum 6-character value rule and word boundary reduce false positives such as `key=true`, `token=null`, and `sort_key=42`; the broad bare `key=` rule can still redact generic long `key=` values by design because `key` is in scope. |
| 8 | LLM remains shadow-only | Pass | Module and status disclaimer remain shadow-only; default `LLM_SHADOW_ENABLED` remains `False`. |
| 9 | No trading/scoring/entry/exit behavior changed | Pass | Patch touches only the LLM shadow module and L1-H2 tests. No scoring/entry/exit modules changed. |
| 10 | No TP/SL/exit behavior changed | Pass | No risk, TP/SL, or exit modules changed. |
| 11 | No broker/live trading/real orders added | Pass | No broker/execution/order modules changed; LLM module still documents fake-money/no-real-orders behavior. |
| 12 | No new external API calls added | Pass | Production diff does not add a new external call path; `_redact()` remains pure string processing. Existing OpenAI call path is unchanged. |
| 13 | Backend tests and frontend build pass | Pass | `pytest` passed with 1273 passed / 2 skipped; `npm run build` passed for the dashboard. |
| 14 | Safe for fake-money monitoring | Conditional pass | Safe as a narrow shadow-only hardening patch, with recommended follow-up for dotted/punctuation token query values. |

## Detailed Findings

### Finding 1 — Query/assignment redaction can miss or partially redact dotted access tokens

**Severity:** Medium

The redaction assignment pattern captures values with only alphanumeric, underscore, and hyphen characters and requires at least 6 characters:

```python
(?P<val>[A-Za-z0-9_\-]{6,})
```

That is intentionally conservative for false-positive control, but it leaves a coverage gap for query parameters explicitly in scope when values include punctuation, especially JWT-like tokens:

- `token=abcdef.ghijkl` becomes `token=<redacted>.ghijkl`, leaking the suffix after the dot.
- `access_token=abc.def.ghi` remains unredacted because the first segment is shorter than 6 characters.

This does not invalidate the patch for the currently tested formats, and Bearer tokens with dots are covered by the bare Bearer pattern. However, query params named `token` or `access_token` commonly carry dotted access tokens, so this is a recommended follow-up hardening item.

**Suggested follow-up:** For known secret-bearing key names in assignment/query contexts, consider redacting until a safe delimiter such as `&`, whitespace, comma, closing quote, or closing brace/bracket instead of limiting the value to `[A-Za-z0-9_-]` only. Keep the existing short-value guard or add targeted false-positive tests to preserve the L1-H2 intent.

## Evidence Reviewed

### Redaction implementation

- The patch introduces `_BARE_SECRET_PATTERNS` for OpenAI-style `sk-*` keys and HTTP Bearer headers.
- The secret-name alternation includes provider/env names and generic query/assignment names such as `api[_-]?key`, `access[_-]?token`, `TOKEN`, `token`, and `key`.
- `_SECRET_ASSIGN_PATTERN` preserves the key name, separator, and quotes, while replacing the matched value with `<redacted>`.
- `_redact()` applies bare-secret replacement first, then assignment/query replacement.

### LLM packet and error egress

- `build_candidate_packet()` redacts `candidate["marketdata_error"]` before storing it under `packet["marketdata"]["marketdata_error"]`.
- `_error_result()` redacts `error_text` before exposing `llm_error`.
- `analyze_candidate_packet()` redacts exception strings before assigning `last_err`, before assigning `_status["last_error"]`, and before returning `_error_result("error", ...)`.

### Prompt logging and shadow-only behavior

- The reviewed patch does not enable prompt logging.
- `settings.LLM_SHADOW_LOG_PROMPTS` remains default `False`, with a test asserting the default.
- The production LLM logging path logs only summary metadata when response logging is enabled, not the full prompt/packet body.
- The LLM module remains fake-money/shadow-only and does not place trades.

### Behavior isolation

- `git show --stat HEAD` shows only `backend/intelligence/llm_shadow.py` and `backend/tests/test_phase_l1_h2.py` changed by L1-H2.
- No trading/scoring/entry/exit/TP/SL/risk/broker/order modules changed in the reviewed patch.
- The only production external API path in `llm_shadow.py` remains the pre-existing OpenAI chat-completions call; L1-H2 did not add a new call path.

## Commands Run

```bash
git status --short
git log --oneline -5
git show --stat --oneline HEAD
git show --name-only --format=fuller HEAD
git diff HEAD^..HEAD -- backend/intelligence/llm_shadow.py backend/tests/test_phase_l1_h2.py
rg -n "LLM_SHADOW_LOG_PROMPTS|prompt|logger\.|_redact|marketdata_error|llm_error|last_error|LLM_SHADOW_ENABLED|paper|broker|order|alpaca|requests|httpx|urlopen" backend/intelligence/llm_shadow.py backend/core/config.py backend/tests/test_phase_l1_h2.py
PYTHONPATH=backend python - <<'PY'
from intelligence.llm_shadow import _redact
samples = [
 'url?token=abcdef.ghijkl&x=1',
 'url?access_token=abc.def.ghi&x=1',
 'primary-key=longvalue123',
 'sort_key=longvalue123',
 'OPENAI_API_KEY="sk-abcdefghijklmnopqrstuvwxyz"',
 'Authorization: Bearer abc.def.ghi',
]
for s in samples:
    print(s, '=>', _redact(s))
PY
(cd backend && pytest)
(cd frontend/dashboard && npm run build)
```

## Test Results

- Backend: `1273 passed, 2 skipped, 2 warnings in 17.23s`
- Frontend: `next build` completed successfully and generated the static dashboard routes.

## Final Recommendation

Approve L1-H2 for fake-money monitoring as a narrow redaction hardening patch, with a follow-up ticket to expand assignment/query-value redaction for dotted and punctuation-bearing access-token formats while preserving the existing false-positive guards.
