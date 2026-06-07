# Codex Review — Phase 2I Final: Rule-Based Catalyst Sentiment Layer

Review date: 2026-06-07  
Review target: current checked-out implementation containing `backend/catalysts/sentiment.py` and `backend/tests/test_phase2i.py`.

> Note: this container has no configured `origin` remote (`git remote -v` returned empty and `git fetch origin main` failed), so I could not independently fetch GitHub `origin/main`. I reviewed the checked-out branch provided in `/workspace/microtrading-app`, which contains the Phase 2I implementation described in the prompt.

## Critical issues

None found.

Phase 2I does **not** introduce AI/LLM calls, broker connectivity, live trading, real orders, or real-money execution in the reviewed sentiment/scoring path. The simulator continues to advertise fake-money/research-only behavior and explicitly reports `live_trading_enabled: False` and `broker_connected: False`.

## Non-blocking issues

1. **Persisted journal candidate API does not expose the persisted sentiment columns.**
   - The DB schema stores `catalyst_sentiment`, `catalyst_sentiment_score`, and `catalyst_materiality_score` on `paper_candidates`.
   - `persist_tick_result()` inserts those fields.
   - However, `GET /api/journal/candidates` selects only the pre-Phase-2I candidate fields and omits the sentiment columns. This does not affect simulator safety or entry/exit behavior, but it means historical candidate review through that endpoint will not show sentiment even though the data is stored.

2. **Neutral sentiment is structurally supported but effectively unreachable with the current phrase tables.**
   - The analyzer has a `neutral` branch for weak directional signals.
   - Current bullish/bearish phrase weights all appear to be `>= 0.4`, and the offering sentinel is `0.6`, so any matched rule currently becomes bullish/bearish/mixed rather than neutral.
   - This is not unsafe, but it means the advertised `neutral` label is not meaningfully exercised by current analyzer rules or tests.

3. **Financing priors are conservative enough to avoid automatic entries from event type alone, but some financing phrases are treated mildly bullish.**
   - `funding round` and `raises capital` are listed as mild bullish phrases.
   - Explicit offerings/private placements/ATM/shelf/secondary offering terms are bearish, so the higher-risk dilution cases are covered.
   - Still, capital raises can be dilutive in micro/small-cap contexts. This is acceptable for tomorrow's fake-money simulation because scoring is transparent and the hard entry gates remain active, but it is worth watching in candidate output.

## Sentiment rules assessment

**Assessment: acceptable and deterministic.**

- The sentiment layer is explicitly documented as rule-based, deterministic, non-AI, non-LLM, no-broker, no-live-trading, and no-real-orders.
- It lowercases `title + description` and performs deterministic substring phrase matching against fixed bullish and bearish phrase lists.
- It returns a transparent result shape: `sentiment`, `sentiment_score`, `materiality_score`, `sentiment_method`, `sentiment_reasons`, `bearish_flags`, and `bullish_flags`.
- Bullish coverage includes FDA/regulatory approvals, guidance raises, estimate beats, record revenue/earnings/profit, acquisitions, contracts, partnerships, analyst upgrades, target raises, product launches, and mild funding phrases.
- Bearish coverage includes FDA rejections/CRLs/clinical holds, guidance cuts, estimate misses, bankruptcy/going-concern/delisting, public/secondary/follow-on/registered-direct/ATM/shelf/private-placement offerings, dilution, executive resignations, downgrades, target cuts, SEC investigations, class actions, lawsuits, weak demand, and recalls.
- Mixed sentiment is handled when both bullish and bearish max weights meet the directional threshold.
- Unknown sentiment is handled when no directional rule matches.
- Neutral sentiment is present in code but is not practically reached under the current phrase weights.

## Event-type prior assessment, especially offering/financing

**Assessment: safe/conservative for offerings; acceptable but monitor financing.**

- Offering event-type prior is conservative: when `classified_event_type == "offering"` and no bearish phrase matched, the analyzer adds an internal bearish sentinel with materiality `0.6`.
- The internal offering sentinel is intentionally hidden from public `bearish_flags`, while `sentiment_reasons` exposes that the bearish signal came from an "offering event type prior".
- Explicit offering phrases override the prior naturally because they create real bearish phrase matches.
- Financing event type has only a materiality default and no bearish prior. This avoids treating every financing as bearish, but it also means ambiguous debt/financing articles can be `unknown` or mildly bullish if they contain phrases like `funding round` or `raises capital`.
- For a fake-money simulator, this is acceptable because it remains transparent and bounded by market-quality, catalyst, score, and hard rejection gates.

## Scoring integration assessment

**Assessment: safe and transparent.**

- Scoring remains deterministic and transparent.
- If sentiment fields are present, scoring uses the strongest catalyst by materiality and absolute sentiment score.
- Bullish catalysts receive catalyst-score credit scaled by materiality.
- Mixed catalysts receive reduced catalyst-score credit and add a negative reason explaining the conflict.
- Neutral/unknown catalysts receive only minimal catalyst credit and add a weak/unknown negative reason.
- Bearish catalysts receive zero catalyst score and a bearish risk penalty.
- The final output includes a component breakdown and positive/negative decision reasons.
- If sentiment fields are absent, scoring falls back to the earlier event-type scoring path, preserving compatibility with pre-Phase-2I catalyst records.

## Strong bearish rejection assessment

**Assessment: configurable and visible.**

- The hard rejection gate is controlled by `PAPER_REJECT_STRONG_BEARISH_CATALYST` and `PAPER_BEARISH_CATALYST_REJECT_MATERIALITY`.
- Defaults are conservative: strong bearish rejection enabled, threshold `0.8`.
- The simulator emits `rejection_reason = "strong_bearish_catalyst"` when the gate fires.
- This makes strong bearish rejection visible in candidate output and journal rejections.

## Simulator / journal / dashboard assessment

**Simulator candidate output: pass.**

- The simulator requests catalysts with `classify_events=True` and `analyze_sentiment=True`.
- Candidate output includes `catalyst_sentiment`, `catalyst_sentiment_score`, `catalyst_materiality_score`, `catalyst_sentiment_reasons`, `bullish_flags`, `bearish_flags`, `strongest_catalyst_title`, and `strongest_catalyst_sentiment`.

**Journal persistence: pass.**

- `paper_candidates` stores sentiment, sentiment score, and materiality score.
- Journal insertion writes those fields.

**Journal read API: non-blocking gap.**

- `GET /api/journal/candidates` does not currently select or return the sentiment fields. This affects historical inspection only, not simulation safety.

**Dashboard: pass for live candidates; partial for historical journal.**

- The main candidates table has Type, Sentiment, materiality, and tooltip reasons.
- The dashboard clearly retains fake-money/no-broker/no-real-orders warnings.
- Historical journal panels do not yet add sentiment breakdowns, but this is not required before market hours for a fake-money run.

## DB / backward-compatibility assessment

**Assessment: backward compatible.**

- New sentiment columns are nullable.
- Existing table creation includes the columns for fresh databases.
- Existing databases are migrated with `ALTER TABLE paper_candidates ADD COLUMN IF NOT EXISTS ...`.
- Journal writes are non-fatal to the simulator if Postgres is unavailable.

## Test coverage assessment

**Assessment: strong for the requested safety and sentiment cases.**

Covered:

- No AI/broker/order keywords in `sentiment.py`.
- Sentiment method label and return shape.
- Bullish FDA/guidance/earnings/M&A/contract/upgrade cases.
- Bearish FDA rejection/guidance cuts/earnings misses/bankruptcy/offering/downgrade/SEC investigation cases.
- Mixed bullish+bearish cases.
- Unknown cases and event-type materiality defaults.
- Offering event-type prior and sentinel hiding.
- Sentiment-aware scoring for bullish, mixed, neutral, unknown, and bearish inputs.
- Bearish score penalty.
- Strong bearish hard-reject logic scenarios.
- Config field existence/defaults.
- DB schema and journal SQL sentiment columns.
- News collector integration with `analyze_sentiment=False` and `analyze_sentiment=True`.
- Polygon calls are mocked in news collector integration tests.

Gap:

- Analyzer-level neutral is not tested with a real current rule because the current rules do not appear to produce neutral.
- Simulator hard-reject is not exercised through a full simulator tick; tests mirror the gate logic around `score_candidate()` instead.
- Journal read API exposure of sentiment fields is not tested.

Local test result:

- `pytest backend/tests/test_phase2i.py -q` → 49 passed, 1 warning.

## Safety assessment

**Assessment: safe for fake-money simulation.**

- No AI/LLM calls were added in the sentiment implementation.
- No broker integration was added.
- No live trading was added.
- No real orders or real-money execution were added.
- Strategy changes are limited to safer catalyst filtering/scoring and a configurable strong-bearish hard rejection.
- Simulator state remains virtual/fake-money.
- Existing hard gates for tradability, spread, positive change, volume, accepted catalysts, generic-only catalysts, score threshold, max positions, and max trades/day remain in place.

## Safe to run tomorrow?

Yes. Phase 2I is safe to run on Monday, 2026-06-08 as a **fake-money simulation**.

It should not be treated as production trading logic or financial advice. The run should be monitored for the non-blocking financing-prior behavior and for whether historical journal screens need sentiment fields exposed later.

## Patch required before market hours?

No patch is required before market hours for fake-money simulation.

Recommended later cleanup, not market-blocking:

1. Expose persisted sentiment columns from `GET /api/journal/candidates`.
2. Add an analyzer-level neutral test or adjust rule thresholds if neutral should be a reachable production label.
3. Consider documenting or tightening financing phrase behavior if live small-cap/micro-cap dilution risk analysis is added in a future phase.
