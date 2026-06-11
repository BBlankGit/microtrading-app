# Codex Review — Phase I5 Intelligence Dashboard Tab

Review target: latest local patch `3546441 Add Intelligence dashboard tab` against its parent.

Scope honored: review only. No application code was changed.

## Executive verdict

**Phase I5 is generally safe for fake-money monitoring, with two operational caveats:**

1. The new `/api/intelligence/news` endpoint is display-oriented and does not alter trading state, but it is not a pure read from an infrastructure perspective because the reused `collect_news_for_symbols` helper performs a best-effort Redis cache write.
2. The dashboard auto-refresh now fetches news every 30 seconds for the default universe. This is not a heavy 5,000-symbol historical job, but it does add recurring Polygon news API pressure.

Frontend build and backend tests pass.

## Checklist

| # | Review item | Result | Notes |
|---|---|---|---|
| 1 | Top-level Intelligence tab implemented and accessible without scrolling | **Pass** | A top-level navigation bar is rendered near the top of the page, after the header/loading area, with `Main Dashboard`, `Intelligence`, and `Strategy Settings`. It should be visible without scrolling on normal desktop viewports, though it is not sticky. |
| 2 | Full-Market Movers, Reddit Ranking, News/Catalysts, Earnings Calendar, Insider Transactions, and LLM placeholder organized inside the tab | **Pass** | The `IntelligenceSection` contains tabs for Reddit, Full-Market Movers, Earnings, Insiders, News, Heatmap, and LLM Shadow. Heatmap is extra and remains a placeholder. |
| 3 | Unavailable feeds show clear placeholders rather than fake data | **Pass** | Earnings and insiders endpoints return `implemented: false`, `enabled: false`, empty result arrays, and warnings. The frontend renders a dashed placeholder with status and “no fake data shown.” LLM is also explicitly inactive. |
| 4 | News/Catalysts section accurately states current analysis is deterministic/rule-based and not AI/LLM | **Pass** | Both backend response metadata and frontend copy state rule-based / deterministic analysis and no AI/LLM. |
| 5 | Reddit correctly described as shadow/display unless real entry usage exists | **Pass** | The existing Reddit endpoint docstring states it is read-only and not integrated into trading decisions. The Intelligence container also repeats read-only / no trading integration. No new Reddit trading integration was added. |
| 6 | Earnings/insiders display-only unless real entry usage exists | **Pass** | Both endpoints return placeholders and notes saying display-only / no entry-exit impact. No engine integration was added. |
| 7 | New backend endpoints are read-only | **Pass with caveat** | New routes are GET-only and do not touch broker/trading state. Caveat: `/api/intelligence/news` calls `collect_news_for_symbols`, which writes a best-effort Redis cache entry. This is not a trading side effect, but it is not a strict persistence read-only endpoint. |
| 8 | No trading/scoring/entry/exit behavior changed | **Pass** | The patch only changes `backend/api/intelligence.py` and `frontend/dashboard/app/page.tsx`; no simulator, strategy, scoring, entry, or exit files changed. Existing catalyst collection/scoring helpers are reused only for the display endpoint. |
| 9 | No broker/live trading/real orders added | **Pass** | No broker/order modules were modified, and new UI/backend copy repeatedly states no broker, no live trading, and no real orders. |
| 10 | No OpenAI/Anthropic/Ollama/LLM calls added | **Pass** | No LLM SDK calls/imports were added. The LLM UI is a placeholder and explicitly says no OpenAI / Anthropic / Ollama / LLM calls are made. |
| 11 | No new secret keys or hardcoded V6 secrets copied | **Pass** | The patch adds no settings, environment-variable secrets, API keys, or hardcoded credentials. It references V6 migration sources only in placeholder warning text. |
| 12 | No heavy 5,000-symbol historical jobs added | **Pass with caveat** | No historical backfill job was added. News collection defaults to the 10-symbol `DEFAULT_UNIVERSE` and the collector caps requests at 25 symbols. Caveat: dashboard refresh calls the news endpoint every 30 seconds, adding recurring Polygon news calls. Existing full-universe premarket scanner code was already present before I5. |
| 13 | Frontend build and backend tests pass | **Pass** | `npm run build` passed in `frontend/dashboard`; `pytest` passed in `backend` with 1119 passed, 2 skipped, and 2 warnings. |
| 14 | Safe `--no-deps` deploy instructions followed or documented | **Not evidenced** | The I5 patch did not add or modify deploy documentation, and no `--no-deps` instruction was found in the patch. If deployment is part of acceptance, add an explicit safe deploy note elsewhere before rollout. |
| 15 | I5 safe for fake-money monitoring | **Pass with caution** | The feature remains fake-money/display-only and passes tests/build. Monitor API pressure from 30-second news refreshes and be aware of the Redis cache write side effect. |

## Evidence reviewed

### Backend

- `backend/api/intelligence.py` adds Phase I5 routes: `GET /api/intelligence/news`, `GET /api/intelligence/earnings`, and `GET /api/intelligence/insiders`.
- `/news` wraps the existing catalyst collector with deterministic event classification and sentiment analysis, returns `analysis_mode: rule-based (no AI/LLM)`, and labels the feed as display-only / no live orders / no AI-LLM.
- `/earnings` and `/insiders` return empty, stable placeholder payloads with `implemented: false`, `enabled: false`, `results: []`, and explanatory warnings.
- Existing Reddit/premarket refresh POST endpoints remain from prior phases and were not newly added by this patch.

### Frontend

- `frontend/dashboard/app/page.tsx` adds a top-level tab state and a navigation bar containing `📊 Main Dashboard`, `🧠 Intelligence`, and `⚙ Strategy Settings`.
- The Intelligence section contains subtabs for Reddit, Full-Market Movers, Earnings, Insiders, News, Heatmap, and LLM Shadow.
- News renders actual catalyst rows from the backend feed and clearly labels the analysis as rule-based / deterministic / non-LLM.
- Earnings, insiders, heatmap, and LLM render placeholders rather than fabricated feed data.

## Testing performed

- `npm run build` from `frontend/dashboard` — passed.
- `pytest` from `backend` — passed: 1119 passed, 2 skipped, 2 warnings.

## Recommendation

Accept Phase I5 for fake-money monitoring if the team is comfortable with the two caveats above. For a follow-up hardening patch, consider either:

1. Making `/api/intelligence/news` a cache-read-first endpoint with explicit manual refresh, or disabling the Redis write path for dashboard display reads; and
2. Documenting the safe `--no-deps` deployment procedure if that is required for release sign-off.
