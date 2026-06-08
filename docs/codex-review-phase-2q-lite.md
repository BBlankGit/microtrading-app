# Codex Review — Phase 2Q-Lite Virtual Bracket Intrabar Exit Detection

Reviewed latest Phase 2Q-Lite patch: `9542130` (`Add virtual bracket intrabar exit detection`).

Scope honored: this review is limited to the Phase 2Q-Lite changes in:

- `backend/data/polygon_client.py`
- `backend/paper/exits.py`
- `backend/paper/models.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase2q_lite.py`
- `backend/tests/test_paper.py`

## Critical issues

None found that would make Phase 2Q-Lite unsafe for fake-money monitoring.

The patch is research-only/paper-only, does not add broker execution, and the new intrabar path closes simulated bracket exits at the configured bracket target/stop prices when Polygon aggregate high/low evidence is available.

## Non-blocking issues

1. **Point-in-time fallback still exits at observed point price, not the bracket target/stop.**
   - Intrabar TP exits close at `tp_price`, and intrabar SL exits close at `sl_price`.
   - However, when intrabar data is unavailable, the fallback preserves existing behavior and exits at `bid` / `last_trade_price` rather than clamping to the TP/SL threshold.
   - This is acceptable as an existing fallback-preservation behavior, but it means the statement “TP/SL exits close at target/stop” is fully true for intrabar exits and not fully true for fallback exits.

2. **Journal database persistence does not store intrabar evidence columns.**
   - The in-memory closed-trade model and `/api/paper/dashboard` trade payload can carry intrabar fields.
   - The persisted `paper_trades_journal` schema and insert/select paths still store only the basic exit fields, so historical journal endpoints cannot show `intrabar_high`, `intrabar_low`, `tp_price`, `sl_price`, or conservative-both-touched evidence.
   - This does not affect exit safety, but it limits historical auditability after process restart or when using journal endpoints.

3. **Frontend closed-trades table does not explicitly render intrabar evidence.**
   - The dashboard API can return the metadata through simulator trade dictionaries, but the React `Trade` interface/table currently renders only the exit reason and basic prices/P&L.
   - The exit reason strings (`take_profit_intrabar`, `stop_loss_intrabar`, `stop_loss_intrabar_both_touched_conservative`) are visible, but the evidence fields are not displayed in the table.

4. **Entry-minute aggregate exclusion is conservative against pre-entry false positives but can miss post-entry touches inside the entry minute.**
   - `get_intrabar_data()` filters bars by bar start timestamp `>= entry_ms`.
   - If a position opens mid-minute, the aggregate bar for that minute starts before the entry timestamp and is excluded, even though a TP/SL touch may occur after entry but inside that same minute.
   - This is a known limitation of minute aggregates without tick-level ordering. It avoids using pre-entry high/low data but can reduce sensitivity for the first partial minute.

5. **Intrabar cache is keyed only by symbol.**
   - The cache TTL is only 20 seconds and the normal poll interval appears longer, so routine monitoring is unlikely to hit this.
   - Still, if a symbol is exited and re-entered within the cache TTL, cached high/low data from the previous position could be reused before being refiltered against the new entry timestamp.
   - A future hardening patch could key the cache by `(symbol, entry_time, date)` or include entry/date validation in the cache value.

## Intrabar TP/SL assessment

Pass for the new intrabar path.

- `evaluate_virtual_bracket_exit()` computes `tp_price` and `sl_price` from entry price and configured percentages.
- When intrabar high/low are present, it checks `intrabar_high >= tp_price` and `intrabar_low <= sl_price`.
- A TP-only intrabar touch returns `exit_reason = "take_profit_intrabar"` and `exit_price = tp_price`.
- An SL-only intrabar touch returns `exit_reason = "stop_loss_intrabar"` and `exit_price = sl_price`.
- Exact-boundary tests cover high exactly equal to TP and low exactly equal to SL.

Caveat: fallback exits without intrabar data intentionally retain point-in-time behavior and close at the observed point price.

## Conservative both-touched assessment

Pass.

- When both intrabar high and low cross their thresholds, the evaluator returns `stop_loss_intrabar_both_touched_conservative`.
- The simulated exit price is the stop price, not the current/late quote.
- The result marks both `tp_touched` and `sl_touched` as true and sets `conservative_both_touched` to true.
- The simulator increments both the intrabar SL counter and the conservative-both-touched counter for that exit reason.

Caveat: the current intrabar data object is a composite high/low across recent minute bars since entry, not a per-bar sequence with exact ordering. Applying stop-loss on any both-touched composite interval is deliberately conservative, but it can understate P&L in cases where TP plausibly occurred before a later SL.

## API-load assessment

Pass with minor hardening suggestion.

- Additional Polygon aggregate calls are limited to positions already open at the start of the tick.
- Candidate symbols do not trigger intrabar aggregate calls.
- The call path snapshots `_account.positions.keys()` before fetching intrabar data and uses at most one `get_intrabar_data()` call per open symbol.
- `get_recent_minute_bars()` caps the aggregate limit to the range `1..10`; the Phase 2Q-Lite caller uses `limit=5`.
- `get_intrabar_data()` has a 20-second in-process TTL cache to avoid repeated calls for the same symbol within a short interval.
- Tests mock `get_intrabar_data()` / Polygon-facing functions and avoid real Polygon calls.

Minor hardening: make the cache key include entry timestamp/date, not just symbol.

## Journal/dashboard assessment

Partial pass.

- The tick result’s exit records include clear intrabar metadata: `tp_price`, `sl_price`, `tp_touched`, `sl_touched`, `intrabar_high`, `intrabar_low`, `intrabar_source`, and `conservative_both_touched`.
- ClosedTrade objects include nullable intrabar fields and `to_dict()` exposes them in simulator memory responses.
- `/api/paper/dashboard` returns simulator trades, so the API can include those in-memory fields for current-session closed trades.

Limitations:

- Persisted journal trades do not include intrabar evidence columns, and journal trade endpoints do not select or return those fields.
- The frontend closed-trades table shows the intrabar-aware exit reason string but does not show high/low, TP/SL, source, or conservative-both-touched evidence.

## Test coverage assessment

Pass for core behavior.

Covered by `backend/tests/test_phase2q_lite.py` and updated `backend/tests/test_paper.py`:

- TP-only intrabar detection.
- SL-only intrabar detection.
- Both-touched conservative stop-loss ordering.
- Point-in-time fallback TP/SL/no-exit cases.
- Max-hold exit still firing when no bracket exit occurs.
- Daily loss guard not blocking exits.
- Intrabar data not fetched when there are no open positions.
- Exact threshold equality for TP/SL touches.
- ClosedTrade intrabar field serialization.
- No forbidden broker/order/AI imports in the touched paper modules.

Additional tests that would be useful later:

- Cache-key behavior across rapid same-symbol re-entry.
- Entry-mid-minute aggregate behavior.
- Journal persistence/API visibility of intrabar metadata if that becomes a requirement.
- Frontend rendering of intrabar evidence if dashboard evidence visibility becomes a requirement.

## Safety assessment

Pass.

I did not find added broker integration, live trading, real order placement, real-money execution, or AI/LLM integrations in the Phase 2Q-Lite patch.

The new code is confined to:

- Polygon market-data aggregate retrieval.
- Paper simulator exit evaluation.
- Paper model metadata.
- Paper tests.

It remains fake-money monitoring only.

## Safe for fake-money monitoring?

Yes. Phase 2Q-Lite is safe for fake-money monitoring.

The new intrabar high/low detection materially improves paper exit realism versus polling-only point-in-time checks, especially for fast TP/SL touches between 60-second ticks. The implementation is conservative when both sides are touched and does not introduce real execution capabilities.

## Is any patch required before continuing market monitoring?

No required patch before continuing fake-money market monitoring.

Recommended future improvements, but not blockers:

1. Persist intrabar metadata into `paper_trades_journal` and expose it through journal endpoints.
2. Render intrabar high/low, TP/SL, source, and conservative-both-touched status in the dashboard closed-trades table.
3. Key the intrabar cache by symbol + entry timestamp + date.
4. Decide whether fallback point-in-time TP/SL exits should also clamp to bracket target/stop prices or continue preserving prior observed-price behavior.
5. Document the entry-minute aggregate limitation or add a more precise data source if exact first-minute post-entry detection becomes important.
