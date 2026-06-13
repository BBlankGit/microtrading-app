# Codex Review — Phase G1B-H2 Runtime Wallet Dashboard + EOD

**Review target:** latest patch on current branch, commit `8acd829` (`Fix runtime wallet dashboard and late EOD flatten`).

**Scope honored:** this review covers only the G1B-H2 patch and does not modify application code.

**Verdict: YELLOW / NEEDS FOLLOW-UP**

## 1. Executive summary

G1B-H2 materially improves the runtime wallet dashboard and the late-EOD safety gap from G1B-H1. The reviewed source now contains the three-wallet dashboard panel, a wallet filter, wallet-tagged open positions, latest-session closed trades, and source-level removal of the local horizontal overflow wrapper around the News Feed table. The wallet APIs return all three fake wallets and keep the legacy engine-only `/api/paper/positions` and `/api/paper/trades` endpoints intact.

The late-EOD flatten issue is mostly addressed: engine and shadow-wallet positions from prior NY sessions are detected on later ticks, are force-closed with `eod_flatten_late` when an exit price exists, and generate warnings when an exit price is missing.

However, I am keeping this **YELLOW / NEEDS FOLLOW-UP** for freeze readiness because the current code still does not add a general regular-market-hours entry gate. `paper.eod.entries_blocked()` explicitly returns unblocked outside the regular session and only blocks during the EOD cutoff window, relying on “normal session checks” elsewhere. I did not find a universal session gate around the engine entry branches or the shadow-wallet entry branch. That means fake entries can still be admitted after close, on weekends, or before 09:30 ET if upstream candidates/quotes exist. Given the user’s observed Saturday 00:08 ET TSLA entry, this is a freeze blocker unless the project explicitly accepts extended-hours/weekend paper entries and labels/excludes them.

I also could not independently verify Claude’s live-container runtime claims from source alone; the source is now deployable through the provided compose flow, but runtime evidence remains an external claim unless the deployment logs/container inspection artifacts are attached.

## 2. Findings

### Finding A — Deployment/runtime correction is plausible from source, but live evidence is external

The frontend service mounts `frontend/dashboard` from source, deletes the container `.next` directory, runs `npm ci`, builds, and starts Next from the source tree, which should avoid stale `.next` overlays after a real container restart. The backend image builds from `backend/` and copies source into the image. I did not find G1B-H2 changes that require a temporary `docker cp` overlay.

Caveat: this review did not connect to Claude’s live containers. I verified source deployability and local build/test behavior, not the claimed production container state.

### Finding B — Dashboard wallet visibility is present in used page code

The used dashboard component renders three cards unconditionally from the wallet response: `ENGINE`, `DETERMINISTIC_SHADOW`, and `AI_SHADOW`. The same page defines wallet filter options for all wallets and renders both `Open Positions by Wallet` and `Latest-Session Closed Trades by Wallet` sections. The main dashboard includes both `WalletsPanel` and `WalletExplorer`, so this is not dead code.

Caveat: `strategy_id` is visible as a column in the wallet tables, but there is no separate strategy-id filter; filtering is by wallet only.

### Finding C — Wallet APIs are improved and backward compatible

`/api/paper/wallets` returns an engine snapshot plus deterministic and AI shadow snapshots, including inactive status metadata. `/api/paper/wallets/positions` combines engine, deterministic shadow, and AI shadow positions and annotates rows with `wallet_id`, `strategy_id`, and stale-overnight flags. `/api/paper/wallets/trades` combines closed trades across wallets, supports `wallet_id`, `session_date`, and `latest_session=true`, and annotates engine trades with wallet and strategy metadata.

Legacy `/api/paper/positions` and `/api/paper/trades` remain engine-only wrappers around `simulator.get_positions()` and `simulator.get_trades()`, so existing callers are not forced onto the new wallet schema.

### Finding D — Latest-session closed trades use America/New_York session dates

The latest-session helper uses America/New_York and returns today after 09:30 ET on weekdays, the previous weekday before 09:30 ET, and the previous Friday on weekends. The trades endpoint resolves `latest_session=true` through that helper and matches rows using `session_date_for(exit_time || entry_time)`, which rolls pre-open and weekend timestamps back to the prior weekday. This directly addresses the UTC/Japan date-rollover concern for latest-session visibility after the US close and over weekends.

### Finding E — Late EOD flatten is largely fixed

Engine tick processing now runs a late-flatten sweep before the same-day EOD flatten block. It identifies stale positions with `position_is_stale_overnight()`, exits them with the stable reason `eod_flatten_late` when a bid/last/last-known price exists, and appends `missing_exit_price_late_flatten` warnings when no exit price exists. Shadow wallets run an analogous stale sweep before normal exits and before new entries.

This meets the G1B-H1 follow-up requirement for missed same-day close ticks, prior-session positions, warnings on missing exit prices, and persisted exit reason.

Caveat: the stale predicate is based on “entry time before latest completed 16:00 ET close,” not an exchange holiday calendar. That is consistent with existing project helpers but is not a complete market calendar.

### Finding F — Freeze blocker: general out-of-session entries remain possible

The patch did not add a universal “regular market hours only” entry gate. `entries_blocked()` only blocks during the configured EOD cutoff window while already in a regular session; it explicitly returns `(False, None)` outside the regular session. In the engine simulator, this EOD-only block is checked before the branch chain, but the catalyst, no-catalyst, legacy momentum, and other entry branches can still call `_account.enter_position()` if their branch-specific conditions are met. In the shadow wallets, entries are only blocked by the same EOD-cutoff helper, so deterministic shadow entries can also occur outside regular hours when candidates say `WOULD_ENTER`; AI shadow entries remain additionally gated by LLM enablement.

This directly matches the user’s concern: a Saturday 00:08 ET fake TSLA entry is not just “not stale overnight” under the current logic; it should have been blocked or explicitly labeled as out-of-session. Before freeze, the app needs a default-deny session gate for new fake entries unless an explicit extended-hours simulation mode is added.

### Finding G — News Feed layout source fix is present

The News Feed table block no longer uses a local `overflow-x-auto` wrapper. It uses a full-width fixed table, column widths, wrapped title/source/event/explanation cells, and a combined Signal column with details in tooltips. This is a reasonable source-level fix for normal desktop width.

Caveat: I did not run a browser screenshot against a live dashboard with representative long rows, so this is source/build evidence rather than visual runtime proof.

### Finding H — Candidate/outcome audit dashboard caveats remain

I did not find a new G1B-H2 dashboard audit panel for candidate extras coverage, outcome counts, recent candidate examples with bounded `extras_json`, or resolver last-run status. Those G1B-H1 caveats remain backend/API-only or otherwise not visibly resolved on the dashboard.

### Finding I — Safety and AI boundaries remain intact in the reviewed patch

The reviewed patch remains fake-money/paper-only. `LLM_SHADOW_ENABLED` remains default false, AI shadow wallet status is inactive when LLM is disabled, and the AI wallet entry/exit path is guarded by `_llm_enabled()`. I did not find new OpenAI/DeepSeek/Groq/Mistral/Gemini/Ollama calls, broker integration, live orders, or real-money execution code in the G1B-H2 patch.

## 3. Evidence

### Source evidence reviewed

- `git diff --stat HEAD~1..HEAD`
- `git diff --name-only HEAD~1..HEAD`
- `backend/api/paper.py`
- `backend/paper/eod.py`
- `backend/paper/session.py`
- `backend/paper/shadow_wallets.py`
- `backend/paper/simulator.py`
- `backend/tests/test_phase_g1b_h2.py`
- `frontend/dashboard/app/page.tsx`
- `infra/docker/docker-compose.yml`

### Key implementation evidence

- Wallet API snapshot includes engine, deterministic shadow, AI shadow, and a `wallets` array.
- Wallet positions API annotates engine positions with `wallet_id='engine'` and `strategy_id='engine'`, returns shadow positions via `shadow_wallets.get_positions()`, and emits stale warnings.
- Wallet trades API supports `latest_session=true`, `session_date`, and `wallet_id`, then filters by NY session date.
- `session.latest_session_date_ny()` and `session.session_date_for()` use America/New_York session rules.
- `eod.position_is_stale_overnight()` compares entry time against the latest completed NY 16:00 close while overnight positions are disabled.
- Engine and shadow late-flatten paths use `eod_flatten_late` and warning records for missing exit prices.
- Dashboard source renders wallet cards, wallet filter, open positions by wallet, and latest-session closed trades by wallet.
- News Feed source removes the local horizontal overflow wrapper around that table and switches to a fixed-width wrapping layout.

## 4. Tests reviewed

### G1B-H2 targeted test module

`backend/tests/test_phase_g1b_h2.py` covers:

- stale-overnight detection for prior-session positions;
- after-close/weekend stale behavior;
- `PAPER_ALLOW_OVERNIGHT_POSITIONS` opt-out;
- stable `eod_flatten_late` reason;
- shadow-wallet late flatten and missing-price warnings;
- wallet API source shape for all three wallets and wallet-tagged rows;
- latest-session endpoint wiring;
- frontend source strings for wallet panel/filter/tables and strategy columns;
- News Feed source block without `overflow-x-auto`;
- no forbidden broker/live/AI imports in selected touched modules.

### Commands run by Codex

- `pytest backend/tests/test_phase_g1b_h2.py -q` — passed: 18 passed, 3 skipped, 1 warning.
- `pytest -q` — failed in this environment: 1318 passed, 7 skipped, 82 failed. Most failures are async tests lacking an async pytest plugin in the current environment; one pre-existing source-string assertion also fails in `backend/tests/test_phase_2t.py::test_frontend_renders_rejection_reason_before_decision_reason`.
- `cd frontend/dashboard && npm run build` — passed. Next production build completed successfully.

## 5. Runtime evidence reviewed

Claude reported the following runtime evidence, but I treated it as reported evidence rather than independently reproduced live-container evidence:

- deployed commit is `8acd829`;
- backend health OK;
- stale frontend container from 2026-06-11 was rebuilt/redeployed;
- `/api/paper/wallets` returned `engine`, `deterministic_shadow`, and `ai_shadow`;
- dashboard SSR HTML contained `Fake Wallets`, wallet filter, `Open Positions by Wallet`, and `Latest-Session Closed Trades by Wallet`;
- News Feed horizontal scrollbar was gone by source/runtime bundle inspection;
- old TSLA position was opened after Friday market close, so it was not treated as stale under the implementation.

I did not receive container IDs, command transcripts, screenshots, or captured HTTP responses in the repository, so the runtime correction is not independently auditable from committed files alone.

## 6. Freeze-readiness judgment

**YELLOW / NEEDS FOLLOW-UP.**

G1B-H2 is a strong improvement for dashboard visibility, latest-session closed-trade visibility, deploy-from-source behavior, and late-EOD flattening. It should solve the visible three-wallet dashboard problem when the frontend is actually rebuilt from source.

It is **not freeze-ready** until out-of-session fake entries are blocked by default. The project boundaries say fake-money/paper only, but freeze metrics still need clean regular-session semantics. New fake entries should not occur on weekends, before 09:30 ET, after 16:00 ET, or during market-closed states unless an explicit extended-hours simulation mode is introduced and clearly labeled.

## 7. Required follow-up patches

1. **Add a universal entry-session gate before any fake entry can be opened.** Default behavior should block all engine and shadow-wallet entries outside regular US market hours: weekdays 09:30–16:00 ET, excluding market-closed states. If extended-hours simulation is desired, add an explicit setting and visible labeling.
2. **Flag or remediate existing out-of-session positions.** Positions opened after close/weekend/pre-open should be force-closed, voided, or marked invalid/out-of-session and excluded from freeze performance metrics.
3. **Add tests for out-of-session entry blocking.** Cover engine catalyst, no-catalyst/market-mover/momentum branches where practical, deterministic shadow entries, AI shadow entries with LLM enabled, weekends, pre-open, post-close, and the normal regular-session allow case.
4. **Attach auditable runtime artifacts.** Include command transcripts or saved artifacts for container restart/rebuild, `/api/paper/wallets`, `/api/paper/wallets/positions`, `/api/paper/wallets/trades?latest_session=true`, and browser/page evidence for the dashboard and News Feed.
5. **Carry forward dashboard audit caveats.** Add visible candidate extras coverage, outcome counts, recent candidate examples with bounded extras, and resolver last-run status if these are required for freeze operations.
6. **Optional but recommended: add strategy-id filtering.** Strategy is visible in wallet tables, but not filterable separately from wallet.
