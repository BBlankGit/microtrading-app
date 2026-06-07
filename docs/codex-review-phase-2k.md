# Codex Review — Phase 2K Runtime Strategy Configuration Panel

Reviewed commit: `6ebd6a3` (`Implement Phase 2K runtime strategy configuration panel`)

Scope: only the latest Phase 2K changes.

## Critical issues

None for real-money safety.

Phase 2K did **not** add broker integration, live trading, real order placement, AI/LLM behavior, or real-money execution. The new runtime configuration code explicitly frames itself as fake-money-only, the API disclaimer repeats that there is no broker/live trading/real orders, and the status endpoint remains explicit that execution is disabled.

## Non-blocking issues

1. **Several exposed runtime fields are not actually consumed by their target runtime modules.**
   - `PAPER_POSITION_SIZE_PERCENT` is exposed, validated, persisted, and shown in the dashboard, but the simulator still enters positions with `settings.PAPER_MAX_POSITION_SIZE_USD` rather than an effective runtime-derived position size.
   - `PAPER_MAX_UNIVERSE_SIZE`, `PAPER_MAX_SYMBOLS_PER_TICK`, `PAPER_DYNAMIC_UNIVERSE_ENABLED`, `PAPER_DYNAMIC_REFRESH_SECONDS`, the market-discovery knobs, and the market-regime knobs are in the runtime schema, but `paper.universe`, `paper.discovery`, and `market.regime` still read `settings` directly.
   - Safety impact: low, because this is fake money. Usability impact: medium, because an operator may believe the dashboard changed these knobs when the running simulator/discovery/regime code is still using base `.env` settings.

2. **Position-size semantics are unclear.**
   `PAPER_POSITION_SIZE_PERCENT` is derived from base USD position size and starting cash, but it is not applied during simulated entry sizing. This makes the Strategy Settings panel misleading for a high-impact fake-money risk parameter.

3. **Dashboard covers only a subset of schema fields.**
   The backend schema contains additional discovery/regime fields such as discovery refresh seconds, min/max discovery price, volume filters, and regime thresholds. The dashboard only exposes the main numeric fields and booleans. This is acceptable for a first panel but should be documented as a curated subset.

4. **Auth tests check route dependencies, not full HTTP behavior.**
   The tests verify PATCH/reset routes have dependencies, but they do not exercise 401/503/200 behavior with missing, wrong, unconfigured, and valid `ADMIN_API_TOKEN` values through the ASGI app.

5. **Runtime persistence is best-effort after in-memory apply.**
   Updates are validation-atomic in memory, but persistence failures leave the runtime override active in memory and return a warning rather than rolling back. This is a reasonable availability-first fake-money fallback, but it should be understood as “memory-atomic, persistence-best-effort,” not fully durable transaction semantics.

## Runtime config assessment

Phase 2K introduces a two-layer runtime config model:

1. base config from `.env` / `core.config.settings`, and
2. runtime overrides stored in memory and best-effort persisted to Postgres.

The effective value behavior is clear: base config is loaded first and `_runtime_overrides` is applied on top, so runtime overrides take precedence over base settings. The schema response also exposes `base_value`, `runtime_override`, and `effective_value`, which makes the layering easy to inspect from the API/dashboard.

Validation is mostly strong and bounded:

- entry score is bounded to `0..100`;
- take-profit/stop-loss are bounded to `0.05..20.0`;
- max hold time is bounded to `1..390` minutes;
- max open positions and trades/day are bounded;
- universe/discovery/regime fields have explicit ranges;
- cross-field validation prevents discovery min price from being greater than or equal to max price;
- cross-field validation prevents risk-off score from being greater than or equal to risk-on score.

Invalid updates are rejected before mutation. `update_runtime_config()` validates first, raises on any validation error, then applies all coerced fields together to the in-memory override map. This satisfies the key atomicity concern for invalid updates.

## API/auth assessment

The new runtime config router is safe at the route-design level:

- `GET /api/config/runtime` is read-only and unauthenticated.
- `GET /api/config/runtime/schema` is read-only and unauthenticated.
- `PATCH /api/config/runtime` uses `Depends(require_admin_token)`.
- `POST /api/config/runtime/reset` uses `Depends(require_admin_token)`.

`require_admin_token()` rejects unconfigured sentinel tokens with `503`, rejects missing/malformed bearer tokens with `401`, compares tokens with `hmac.compare_digest`, and does not log or return the expected token.

The PATCH endpoint validates the full `updates` payload before applying it and returns validation errors as HTTP 400. Reset clears all runtime overrides and returns base-effective config.

## Safety/secrets assessment

No new broker/live-trading/order/AI/LLM path was identified in the Phase 2K changes.

The runtime schema only includes a hard-coded allowlist of fake-money strategy knobs. It does not include `ADMIN_API_TOKEN`, API keys, database URLs, Redis URLs, Polygon credentials, broker credentials, or any free-form settings dump. Unknown fields are rejected, so attempts to PATCH secret-like keys such as `POLYGON_API_KEY` are not accepted.

The dashboard asks the user to paste `ADMIN_API_TOKEN` for state-changing actions, but it does not display the configured server-side token. This is consistent with prior admin controls and does not expose secrets from runtime config.

## Simulator integration assessment

The simulator/scoring integration is partially complete and stays fake-money-only.

Runtime overrides are used for intended fake-money trading behavior in these areas:

- scoring threshold via `PAPER_ENTRY_SCORE_THRESHOLD`;
- take-profit percentage;
- stop-loss percentage;
- max hold minutes;
- max open positions;
- max trades per day;
- strong bearish catalyst rejection and materiality threshold;
- tick result/status reporting for selected runtime strategy values.

However, not all fields exposed by runtime config are wired into their runtime consumers:

- position size override is not used for simulated entries;
- universe sizing/enabled/refresh values are not used by `paper.universe`;
- market discovery runtime values are not used by `paper.discovery`;
- market regime runtime values are not used by `market.regime` or regime API gating.

This does not create real-money risk, but it can create operator confusion and inaccurate expectations during a fake-money run.

## Dashboard assessment

The Strategy Settings dashboard panel is generally clear and safety-oriented:

- it is labeled `runtime config · admin-protected · fake-money only`;
- it repeats “No broker. No live trading. No real orders.”;
- it shows base/effective/override values, making layering visible;
- it highlights active overrides;
- it disables reset when no overrides are active;
- it requires a pasted admin token before save/reset;
- numeric inputs include min/max/step hints aligned with the backend for displayed fields.

Main dashboard concern: the panel displays and saves `PAPER_POSITION_SIZE_PERCENT` even though simulator entries still use the base USD max position size. It also displays toggles whose downstream modules may still read base `settings` rather than runtime effective values.

## Runtime config persistence/fallback assessment

Persistence fallback is safe for fake-money simulation:

- startup initializes runtime config tables if a DB pool is available;
- DB unavailability does not crash startup;
- runtime config falls back to memory-only mode with a warning;
- monitoring includes runtime config status and warnings;
- reset attempts to delete persisted overrides and audit the reset.

Caveat: persistence is best-effort after in-memory mutation. If DB persistence fails, the active process still uses the override until restart, but the setting may not survive restart. This is acceptable for a fake-money simulator if operators monitor the persistence warning.

## Test coverage assessment

Phase 2K includes broad tests for:

- no broker/OpenAI imports in runtime config;
- no secret-like keys in schema;
- fake-money API disclaimers;
- schema membership and field types;
- base/effective layering;
- validation bounds and type checks;
- unknown-field rejection;
- cross-field validation;
- invalid-update rejection;
- reset behavior;
- runtime status;
- scoring threshold override behavior;
- API route shape and dependency presence for admin-protected routes;
- DB fallback/persistence-warning behavior;
- strong-bearish override lookup.

Coverage gaps to consider later:

- full HTTP auth behavior for missing/wrong/unconfigured/valid `ADMIN_API_TOKEN`;
- PATCH/reset integration tests through the FastAPI app;
- explicit tests proving invalid mixed updates leave existing overrides unchanged;
- simulator tick tests for take-profit/stop-loss/max-hold/max-positions/max-trades runtime behavior;
- tests proving exposed universe/discovery/regime/position-size controls are either wired correctly or intentionally UI-only/read-only.

## Safe to run tomorrow as fake-money simulation?

Yes. Phase 2K is safe to run tomorrow as a fake-money simulation. It does not introduce broker connectivity, live trading, real order placement, AI/LLM calls, or real-money execution. Runtime changes are bounded, admin-protected for mutation, and limited to the paper simulator/research configuration surface.

Operational note: because some displayed settings are not yet wired into their downstream runtime consumers, operators should not rely on the dashboard as the sole source of truth for position sizing, universe/discovery, or market-regime behavior until those wiring gaps are resolved or explicitly documented.

## Patch required before market hours?

No safety patch is required before market hours for fake-money operation.

Recommended before relying operationally on the panel: patch or document the currently misleading controls, especially `PAPER_POSITION_SIZE_PERCENT` and the universe/discovery/regime knobs that are exposed in runtime config but still read from base settings in their runtime modules.
