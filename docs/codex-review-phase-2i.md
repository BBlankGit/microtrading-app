# Codex Review — Phase 2I Rule-Based Catalyst Sentiment Layer

## Scope reviewed

Reviewed the current repository state on branch `work` at `d9f3c18` for the requested Phase 2I sentiment layer. I only changed this review document. I did not change executable code.

Important scope note: the checkout does **not** contain a Phase 2I catalyst sentiment implementation. Searches for catalyst sentiment fields/rules/configuration found only older Phase 2H market-regime uses of `bullish`/`bearish` and existing comments explicitly saying catalyst normalization/filtering/event classification have no sentiment. Therefore, this review treats Phase 2I as **not present in this checkout** rather than approving a sentiment implementation.

Commands used for review:

- `git log --oneline -8`
- `git show-ref`
- `rg -n "sentiment|catalyst_sentiment|strong_bearish|bullish|bearish|mixed" backend frontend .env.example`
- `rg -n "SENTIMENT|BEARISH|CATALYST|PAPER_|BROKER|LIVE|ORDER|openai|anthropic|langchain|polygon" backend frontend .env.example -g '!**/__pycache__/**'`
- `pytest backend/tests/test_safety_invariants.py backend/tests/test_paper.py -q`

## Critical issues

1. **Phase 2I sentiment layer is absent from the reviewed checkout.**
   - There is no catalyst sentiment classifier, no sentiment enum/output field, no sentiment score component, no strong-bearish rejection setting, and no dashboard/journal sentiment columns.
   - Existing catalyst normalization says it adds no AI sentiment, score, or recommendation.
   - Existing catalyst filtering says it performs no scoring or sentiment inference.
   - Existing event classification explicitly says it adds event-type metadata only and no sentiment.

2. **Feature-completeness risk if the intent was to run Phase 2I tomorrow.**
   - The app can still run the existing fake-money simulator, but it will not exercise or display any Phase 2I catalyst sentiment behavior because no such behavior is present.

No critical real-money safety issue was found in the reviewed state.

## Non-blocking issues

1. **No sentiment-specific tests exist because no sentiment feature exists.**
   - Existing tests cover safety invariants, candidate scoring, and mocked simulator paths, but not bullish/bearish/mixed/neutral/unknown catalyst sentiment cases.

2. **No dashboard/journal sentiment visibility exists.**
   - Candidate and journal surfaces currently expose catalyst type/count and score components, not catalyst sentiment.

3. **Strong bearish rejection is not implemented or configurable.**
   - This is not unsafe by itself because no sentiment layer exists, but it means the requested Phase 2I safety behavior cannot be verified.

## Sentiment rules assessment

Phase 2I catalyst sentiment rules were not found.

Current catalyst processing is deterministic and rule-based for **event type classification**, not sentiment:

- `classify_catalyst_event()` builds lowercase text from title, description, and keywords.
- It walks a priority-ordered `_RULES` table.
- It returns the first matching `classified_event_type`, numeric event confidence, matched rules, and `classification_method: "rules_v1"`.
- It states that it adds no AI, no sentiment, and no trade recommendation.

Because no sentiment classifier exists, I could not validate bullish, bearish, mixed, neutral, or unknown sentiment classification behavior.

## Scoring integration assessment

No Phase 2I sentiment scoring integration was found.

Current scoring remains transparent and deterministic:

- It explicitly states no broker, no live trading, no real orders, and no AI/LLM calls.
- It scores market quality, spread, momentum, volume, catalyst event type, and risk penalty.
- Catalyst scoring is based only on event type buckets: high-value event types receive full catalyst weight, mid-value event types receive partial weight, and other accepted catalysts receive a low/generic score.
- The total score is clamped to 0–100 and compared to `PAPER_ENTRY_SCORE_THRESHOLD`.

Safety implication: because sentiment is not integrated, there is no risk of opaque AI sentiment or hidden sentiment-based order execution. However, the requested Phase 2I sentiment transparency and strong-bearish filtering cannot be assessed or relied on.

## Simulator/journal/dashboard assessment

### Simulator

The simulator still uses hard quality/catalyst gates and deterministic score-gate entry logic. It does not include sentiment fields in candidate output. Candidate output includes catalyst count, catalyst type, score components, positive/negative reasons, and decision/rejection reason.

### Journal

The journal schema and persistence path currently store catalyst type, score, score components, positive reasons, negative reasons, and decision reason. No sentiment columns or sentiment JSON fields were found. Because no schema change was present for Phase 2I, there is no observed backward-compatibility risk from Phase 2I DB changes.

### Dashboard

The dashboard candidate table explains existing score components and displays catalyst count/type, but not sentiment. The daily catalyst breakdown groups by catalyst type, not sentiment. Therefore, dashboard sentiment fields are not unclear; they are absent.

## Test coverage assessment

The relevant existing test coverage is safety/scoring/simulator-oriented, not Phase 2I sentiment-oriented.

Positive existing coverage:

- Safety invariant tests scan executable backend code for broker SDK imports, order execution route/function patterns, and AI/LLM imports.
- Paper tests include an additional paper-module safety scan for broker imports, order execution patterns, and AI/LLM imports.
- Existing scoring tests cover high-quality/high-catalyst pass, no-catalyst scoring, negative momentum penalties, wide-spread penalties, untradable penalties, score clamping, and expected scoring schema.
- Simulator tests use mocked data paths for tick behavior rather than requiring real Polygon calls.

Missing for Phase 2I:

- Bullish headline/body classification tests.
- Bearish headline/body classification tests.
- Mixed-signal tests where both bullish and bearish evidence appears.
- Neutral/unknown tests for weak or unrecognized catalysts.
- Strong-bearish rejection tests, including config on/off behavior and candidate-output visibility.
- Score-component tests showing how sentiment affects score and reasons.
- Journal/dashboard API tests verifying sentiment fields are persisted and exposed if schema/UI changes are added.

Test command result:

- `pytest backend/tests/test_safety_invariants.py backend/tests/test_paper.py -q` passed: 48 passed, 1 Starlette deprecation warning.

## Safety assessment

No new broker integration, live-trading route, real order path, real-money execution path, or AI/LLM import was found in the reviewed checkout.

Existing safety posture remains fake-money simulation only:

- Backend safety tests scan for broker SDK imports, order execution patterns, and AI/LLM imports.
- Existing scoring module declares deterministic rule-based fake-money scoring only.
- Existing journal DB module declares no broker and no real orders.
- `.env.example` keeps `LIVE_TRADING_ENABLED=false`.

Strategy changes are not visible for Phase 2I; current strategy changes remain limited to earlier catalyst event filtering/scoring and market quality/risk gates, not broker execution.

## Is Phase 2I safe to run tomorrow as fake-money simulation?

**Safe to run tomorrow as the existing fake-money simulator: yes.** I found no broker/order/live-trading/real-money/AI additions in this checkout, and the safety/paper test subset passed.

**Safe to run tomorrow as a Phase 2I sentiment layer: no / not applicable.** The Phase 2I sentiment layer is not present, so tomorrow's run would not validate bullish/bearish/mixed/neutral sentiment behavior, sentiment scoring, or strong-bearish rejection.

## Is any patch required before market hours?

- **No patch is required before market hours for fake-money safety.** The reviewed state does not introduce live execution or AI/LLM risk.
- **A patch is required before market hours only if Phase 2I sentiment functionality is expected to be active.** That patch should add deterministic sentiment rules, visible candidate/journal/dashboard sentiment fields, tests for bullish/bearish/mixed/neutral/unknown cases, and configurable strong-bearish rejection if that behavior is part of the Phase 2I requirement.
