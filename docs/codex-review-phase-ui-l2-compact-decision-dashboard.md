# Codex Review — Phase UI-L2 Compact Decision Comparison Dashboard

## Scope

Reviewed only the latest UI-L2 patch on the current branch:

- Commit reviewed: `1f328a1 Compact decision comparison dashboard`
- Patch footprint: `frontend/dashboard/app/page.tsx` only
- Review artifact added: `docs/codex-review-phase-ui-l2-compact-decision-dashboard.md`

No application code was changed by this review.

## Verdict

**PASS — UI-L2 is safe for fake-money monitoring.**

The latest patch converts Candidate Decisions from a broad raw-data table into a compact key-decision comparison table, clearly separating the live paper-engine decision from diagnostic deterministic shadow and LLM shadow decisions. Long rationale fields are no longer primary wide columns; they are available through truncated/title text and an expandable row detail panel. Closed positions now show the latest 3 rows by default with a working Show all / Show fewer toggle.

Because the patch changes only the frontend dashboard file and does not modify backend, scoring, candidate selection, LLM, TP/SL, exit, broker, or order code, it does not appear to affect trading behavior.

## Detailed Review Checklist

| # | Review focus | Result | Notes |
|---|---|---:|---|
| 1 | Candidate Decisions is compact comparison table instead of wide raw-data table | PASS | `CandidatesTable` now uses a compact `table-fixed` layout with 9 key columns: Symbol, Price/Chg, Engine Decision, Deterministic Shadow, LLM Shadow, LLM Conf., Agreement, Key Reason/Status, and Details. |
| 2 | Engine Decision, Deterministic Shadow, and LLM Shadow are clear | PASS | Dedicated helpers render engine and LLM badges, deterministic shadow is displayed in its own column, and headers explicitly label the three decision sources. |
| 3 | Key comparison columns fit without horizontal scrolling on normal desktop width | PASS | The candidate table is `w-full table-fixed` with fixed percentage column widths and no horizontal-scroll wrapper around the candidate table. Long status text is truncated or moved into detail views. |
| 4 | Long LLM/engine/shadow explanations moved into tooltip/details instead of wide columns | PASS | The row shows only `Key Reason / Status` with `truncate` and `title`; long engine, deterministic shadow, and LLM rationale fields live in `CandidateDetailPanel` with wrapping. |
| 5 | Row expand/details UI works or tooltip details are available | PASS | Each candidate row toggles `openSym` on click, shows a ▸/▾ affordance, and renders `CandidateDetailPanel` below the selected row. Header and badge titles provide tooltips. |
| 6 | Disagreement statuses are clear, especially Engine reject vs LLM/Shadow WOULD_ENTER | PASS | `computeAgreement` produces orange missed-opportunity states when the engine rejects while deterministic shadow or LLM would enter, and the table highlights those rows. |
| 7 | All 50 monitored candidates can still be reviewed at key-decision level | PASS | `CandidatesTable` maps over the full `candidates` prop without slicing or pagination. The dashboard still passes `dashboard?.last_candidates ?? []`. |
| 8 | Latest Closed Positions shows only latest 3 rows by default | PASS | `TRADES_DEFAULT_VISIBLE = 3`; trades are reversed newest-first, then sliced to 3 unless expanded. |
| 9 | Show all / Show fewer works for closed positions | PASS | `showAll` state toggles between all ordered trades and the default latest 3 rows, with matching button text and status copy. |
| 10 | No backend API behavior changed unless necessary | PASS | Patch footprint is limited to `frontend/dashboard/app/page.tsx`; dashboard fetch still calls `/api/paper/dashboard`. |
| 11 | No trading/scoring/entry/exit behavior changed | PASS | No backend/trading files were touched; changes are UI rendering/state only. |
| 12 | No LLM behavior or candidate selection changed | PASS | LLM fields are displayed only; no LLM API or candidate-selection code was modified. |
| 13 | No TP/SL/exit behavior changed | PASS | No exit, TP, or SL logic files were touched. |
| 14 | No broker/live trading/real orders were added | PASS | No broker or order-placement code was touched; UI copy continues to label shadow decisions as diagnostic/not used for trading. |
| 15 | Frontend build passes | PASS | `npm run build` completed successfully in `frontend/dashboard`. |
| 16 | UI-L2 safe for fake-money monitoring | PASS | The patch improves monitoring readability while preserving paper/fake-money behavior boundaries. |

## Evidence Notes

### Candidate Decisions compactness and readability

- The table now uses fixed percentage columns rather than many raw data columns.
- Decision-source headers are explicit: `Engine Decision`, `Deterministic Shadow`, and `LLM Shadow`.
- The primary row is concise: symbol, price/change, decision badges, confidence, agreement, short reason, and a details toggle.
- The details panel includes the full engine rejection/decision reason, deterministic shadow reason, and LLM primary reason/summary/error, all with wrapping.

### Disagreement handling

The agreement helper distinguishes:

- all-enter agreement
- all-reject agreement
- engine vs deterministic shadow disagreement
- engine vs LLM disagreement
- deterministic shadow vs LLM disagreement
- engine-vs-both disagreement
- LLM inactive cases

Important fake-money monitoring case covered: if the engine rejects while deterministic shadow or LLM says `WOULD_ENTER`, the row receives orange styling and an agreement label/tip that calls attention to the mismatch.

### Closed positions default view

Closed trades now default to the newest three rows while retaining full review access through the toggle. This satisfies the compact dashboard requirement without losing historical visibility.

## Non-Behavioral Safety Assessment

The reviewed patch is frontend-only. It does not alter:

- backend API handlers,
- paper-trading engine behavior,
- scoring thresholds or entry decisions,
- candidate universe/selection logic,
- LLM prompting, model calls, caching, or selection logic,
- take-profit, stop-loss, max-hold, or exit rules,
- broker integrations or live order paths.

## Build Check

```text
npm run build
```

Result: passed.

## Final Recommendation

Approve UI-L2 for fake-money monitoring. The compact comparison dashboard meets the stated review requirements and does not introduce trading-behavior risk.
