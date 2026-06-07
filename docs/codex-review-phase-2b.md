# Codex Review — Phase 2B Candidate Scoring Layer

Review scope: latest Phase 2B changes only, introduced by commit `5b74dd7` (`Implement Phase 2B paper candidate scoring layer`).

## Critical issues

None found.

The Phase 2B changes keep the system inside the existing fake-money paper simulator boundary. I did not find any broker integration, live trading path, real order placement, real-money execution, AI/LLM call, or strategy-scoring mechanism beyond the explicit deterministic rule-based paper scoring layer.

## Non-blocking issues

- No blocking patch is required. The scoring gate is correctly wired before fake entry.
- Minor observability note: `volume_score` becomes `0` when `volume_ratio` is unavailable, but that specific missing-volume condition does not add a `negative_reasons` entry. The component breakdown still exposes the zero, so this is not a safety issue.
- Dashboard rendering is safe and compact, but the component abbreviations (`Q`, `S`, `M`, `V`, `C`, `R`) are terse. This is acceptable for the current dashboard, and the canonical component names remain available in the API payload.
- Frontend linting is not currently configured for this Next.js app in a non-interactive way; `npm run lint` prompts for ESLint setup instead of completing. This is not caused by Phase 2B scoring logic, but it means the dashboard change lacks an automated frontend lint check in this review.

## Scoring correctness assessment

`score_candidate()` is deterministic and rule-based. It reads only the provided `symbol`, `quality`, `catalysts`, and configured `PAPER_ENTRY_SCORE_THRESHOLD`; it does not perform network calls, broker calls, AI/LLM calls, randomization, time-based scoring, or external strategy evaluation.

Component implementation assessment:

- `market_quality_score`: correct. Tradable candidates receive `25`; untradable candidates receive `0` and a negative reason.
- `spread_score`: correct. Spread is scored as `15` for `<= 0.05%`, `10` for `<= 0.15%`, `5` for `<= 0.30%`, otherwise `0`.
- `momentum_score`: correct. Change is scored as `20` for `>= 2.0%`, `15` for `>= 1.0%`, `10` for positive changes below `1.0%`, otherwise `0`.
- `volume_score`: correct. Volume ratio is scored as `15` for `>= 1.5x`, `10` for `>= 1.0x`, `5` for `>= 0.8x`, otherwise `0`.
- `catalyst_score`: correct. High-value event types receive `20`; mid-value event types receive `12`; remaining accepted catalysts receive `5`; no catalysts receive `0`.
- `risk_penalty`: correct. It deducts for wide spread, negative change, untradable quality, and low volume, then floors the total penalty at `-20`.
- `total_score`: correct. It sums all components and clamps the result to `[0, 100]`.
- `score_threshold`: correct. It uses `PAPER_ENTRY_SCORE_THRESHOLD`, with default `70` added to config and `.env.example`.
- `score_pass`: correct. It is `true` only when `total_score >= score_threshold`.

The implementation matches the requested explicit paper scoring model and does not add any other strategy scoring layer.

## Simulator safety assessment

The simulator still enforces hard gates before any fake entry attempt. For each symbol, it computes scoring for transparency, then checks hard eligibility gates for:

- not tradable,
- spread above `0.50%`,
- non-positive `change_percent`,
- `volume_ratio < 0.8` when volume ratio is present,
- no accepted catalysts,
- generic-news-only catalysts.

Only after those hard gates pass does the simulator require `score_pass`. If `score_pass` is false, the candidate is marked `action: score_rejected`, the scoring decision is copied into `rejection_reason`, and no fake position is opened.

If hard gates and score gate both pass, the simulator still calls the existing fake account capacity gate (`can_enter`) before entering a virtual position. The entry remains a `PaperAccount.enter_position()` call only; no broker, exchange, live trading, or real order path is introduced.

Rejected candidates continue to expose scoring details because every candidate record includes `total_score`, `score_threshold`, `score_pass`, `score_components`, `positive_reasons`, `negative_reasons`, and `decision_reason` before the hard-gate/score-gate branch decides action.

## Dashboard assessment

The dashboard update is safe and clear enough for Phase 2B:

- The candidate interface now includes nullable score fields and a structured `ScoreComponents` object.
- The candidates table displays score versus threshold, component breakdown, and a decision/rejection reason.
- Score coloring is display-only and deterministic.
- The dashboard uses React text interpolation for server-provided values, so the displayed decision/rejection strings are not rendered as raw HTML.
- The existing dashboard disclaimer remains explicit that this is research-only fake-money simulation with no broker, no live trading, and no real orders.

No unsafe execution controls, broker actions, real-order buttons, AI/LLM controls, or real-money language were added to the dashboard.

## Test coverage assessment

Backend test coverage for Phase 2B is good:

- `score_candidate()` unit tests cover passing high-quality/high-catalyst scoring, no-catalyst scoring, negative momentum penalties, wide-spread penalties, untradable penalties, score clamping to zero, and required response schema.
- Simulator integration tests cover the new score gate in both directions:
  - below-threshold candidates that pass hard gates are marked `score_rejected` and do not enter;
  - above-threshold candidates that pass hard gates enter a fake position.
- Existing simulator tests continue to cover hard gates and account-level safety constraints.
- Safety invariant tests continue to scan the paper module for broker SDK imports, order-execution patterns, and AI/LLM imports.

Tests avoid real Polygon calls. Tick-level tests patch `polygon_client.get_ticker_snapshot`, `polygon_client.get_previous_close`, `evaluate_market_quality`, and `collect_news_for_symbols`; protected endpoint auth tests patch simulator state-changing functions so they do not perform real market-data work.

Commands run:

- `python -m pytest tests/test_paper.py` from `backend/`: passed (`45 passed`, `1 warning`).
- `python -m pytest` from `backend/`: passed (`77 passed`, `1 warning`).
- `npm run lint` from `frontend/dashboard/`: did not complete because Next.js prompted for initial ESLint configuration in the non-interactive environment.

## Safe to run tomorrow as fake-money simulation?

Yes. Phase 2B appears safe to run tomorrow as a fake-money research simulation. The implementation remains deterministic, transparent, rule-based, and bounded to the paper simulator. It does not introduce broker connectivity, live trading, real orders, real-money execution, AI/LLM calls, or any hidden strategy scoring beyond the requested component score.

This conclusion applies only to fake-money simulation mode. It is not an approval for live trading or real-money execution.

## Is any patch required before market hours?

No patch is required before market hours for the Phase 2B candidate scoring layer.

The only follow-up I would consider later is non-blocking dashboard/test hygiene: add a non-interactive frontend lint/test configuration and optionally make score component labels more self-explanatory in the UI.
