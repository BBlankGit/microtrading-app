# Codex Review — Phase M1-H2: Market Trend Audit Telemetry

**Commit reviewed:** `2e9f811` — *Fix market trend audit telemetry*
**Branch:** `main`
**Files changed:**

- `backend/paper/simulator.py` (+88 / −22)
- `backend/tests/test_phase_m1_h2.py` (+250, new)

**Scope of this review:** only the M1-H2 patch — not M1 or M1-H1 — focused on
shadow trend consumer wiring, candidate path telemetry, raw/adjusted regime
label exposure, and the unchanged-invariants checklist.

---

## 1. Verdict

**Conditional pass for fake-money monitoring.**

The two headline audit issues from M1-H1 (shadow scorer ignoring its consumer
flag, candidate path telemetry derived from candidate source instead of actual
evaluation path) are addressed. The new telemetry shape — `shadow_consumed`,
`shadow_regime_used`, `market_regime_label_before_trend`,
`market_regime_label_after_trend`, `market_trend_regime_label_used` — is
populated correctly on every candidate.

There is **one accuracy bug in the new path classifier** that should be fixed
in a follow-up (proposed Phase M1-H3 below). It does not break the headline
fixes Codex requested, but it introduces two new mislabel cases that violate
the M1-H2 invariant of "telemetry must match the path that actually consumed
regime."

---

## 2. Focus-point findings (1–17)

### 1. MARKET_TREND_APPLY_TO_SHADOW wired to compute_shadow_score input — **PASS**

`backend/paper/simulator.py:1701–1716`:

```python
# Phase M1-H2: route raw vs trend-adjusted regime to the shadow
# scorer according to MARKET_TREND_APPLY_TO_SHADOW.
_shadow_regime = _regime_for(_trend_apply_shadow)
try:
    from intelligence.shadow_scoring import compute_shadow_score
    _shadow = compute_shadow_score(
        symbol=sym,
        quality=q,
        scoring=scoring,
        tick_regime=_shadow_regime,
        …
    )
```

`_trend_apply_shadow` is read once per tick at line 728 alongside the other
consumer flags:

```python
_trend_apply_shadow   = bool(_cfg("MARKET_TREND_APPLY_TO_SHADOW"))
_trend_apply_catalyst = bool(_cfg("MARKET_TREND_APPLY_TO_CATALYST"))
```

`_regime_for` is the same helper used by the no-catalyst and market-mover
paths, so the routing is consistent across consumers.

`compute_shadow_score` is not a no-op consumer of `tick_regime` — it reads
`risk_on_score` and `regime` at `intelligence/shadow_scoring.py:181-182`:

```python
regime = (tick_regime or {}).get("regime", "unknown")
risk_on_score = _safe_float((tick_regime or {}).get("risk_on_score"))
```

Both values flow into the enhanced shadow score, so the rewiring genuinely
changes downstream output — not just a telemetry label.

### 2. Shadow true/false config matches actual raw/adjusted regime input — **PASS**

`tests/test_phase_m1_h2.py::test_simulator_routes_shadow_regime_according_to_flag`
AST-verifies `compute_shadow_score(..., tick_regime=_shadow_regime)` and
`test_simulator_assigns_shadow_regime_from_regime_for` AST-verifies that
`_shadow_regime` is bound from `_regime_for(_trend_apply_shadow)`. Both pass.

Runtime sample (51 candidates with `MARKET_TREND_APPLY_TO_SHADOW=True`):
`shadow_consumed = {True: 51}`, `shadow_regime_used = {trend_adjusted: 51}` —
matches the flag.

### 3. trend_consumers.shadow reflects actual behavior — **PASS with minor caveat**

`backend/market/trend.py:296`:

```python
consumers = {
    "legacy_momentum": bool(settings.MARKET_TREND_APPLY_TO_LEGACY_MOMENTUM),
    "no_catalyst":     bool(settings.MARKET_TREND_APPLY_TO_NO_CATALYST),
    "market_mover":    bool(settings.MARKET_TREND_APPLY_TO_MARKET_MOVER),
    "catalyst":        bool(settings.MARKET_TREND_APPLY_TO_CATALYST),
    "shadow":          bool(settings.MARKET_TREND_APPLY_TO_SHADOW),
}
```

**Minor inconsistency:** trend.py reads `settings.X` directly while the
simulator reads via `_cfg("X")`. Today the values are equivalent because the
M1-H1 / M1-H2 consumer flags are only defined in
`backend/core/config.py:Settings` and are NOT in
`paper.runtime_config._SCHEMA` — so `_cfg` falls through to `settings`. But
if any of these flags later become runtime-tunable, `trend_consumers` would
silently report the *base* config while the simulator follows the runtime
override. Recommend either (a) routing trend.py through `effective_value`,
or (b) adding a comment in trend.py asserting these are intentionally
non-tunable.

### 4. Candidate trend path telemetry derives from actual path logic — **PARTIAL PASS**

The classifier now reads from actual evaluator state (`hard_rejection`,
`is_no_catalyst_rejection`, `_mm_entry_eligible`, `momentum_eval.eligible`)
rather than from candidate source metadata. That is a real improvement over
M1-H1.

However, the classifier's ordering does not match the simulator's own
entry-decision precedence in two cases. See **point 8** below.

### 5. Catalyst candidates with market-mover metadata labeled catalyst / raw / not consumed — **PASS**

Test `test_catalyst_eligible_with_mm_meta_reports_catalyst_not_mm` exercises
exactly this case and passes. The classifier reaches the final `else`
(`catalyst`) branch when `is_no_catalyst_rejection=False`, regardless of
`_mm_meta` — so a catalyst-eligible candidate that is also market-mover-sourced
no longer flips to `market_mover_no_catalyst`. The headline M1-H1 regression
Codex flagged is fixed.

### 6. market_mover_no_catalyst candidates labeled correctly — **PASS**

`elif is_no_catalyst_rejection and _mm_meta is not None and _mm_entry_eligible`
mirrors the simulator's Path D guard at line 1499 (`hard_rejection is not None
and is_no_catalyst_rejection and _mm_eval["eligible"]`). With default flags
the label is `market_mover_no_catalyst`, `regime_used=trend_adjusted`,
`consumed=True`.

### 7. no_catalyst candidates labeled correctly — **PARTIAL PASS**

The classifier's `no_catalyst` branch fires for any `is_no_catalyst_rejection`
candidate that did not match the market-mover branch. However, the actual
simulator splits this state into **two** evaluation paths:

- **Path C: no-catalyst momentum** (line 1566) — `nc_eval.eligible`
- **Path B: legacy momentum fallback** (line 1632) — `momentum_eval.eligible`

When a candidate is `is_no_catalyst_rejection=True`, MM-ineligible, and only
`momentum_eval` (not `nc_eval`) is eligible, the simulator takes Path B
(`entry_mode="momentum"`) — but the M1-H2 classifier labels it `no_catalyst`.
That is a mislabel relative to the actual evaluator that drove the decision.

### 8. legacy_momentum candidates labeled correctly — **FAIL**

Two related issues:

**8a. Branch unreachable for true legacy-momentum candidates.**
`simulator.py:1632` shows Path B (legacy momentum fallback) requires
`hard_rejection is not None and is_no_catalyst_rejection`. But the M1-H2
`legacy_momentum` branch:

```python
elif momentum_eval and momentum_eval.get("eligible"):
    _trend_path_name = "legacy_momentum"
```

only fires when *neither* `rejected_before_path` nor the two
`is_no_catalyst_rejection` branches matched first — i.e. when
`is_no_catalyst_rejection=False`. The actual simulator never assigns
`entry_mode="momentum"` in that state, so this branch never matches a real
legacy-momentum candidate.

**8b. Misfires for catalyst-eligible candidates.**
Conversely, a candidate that is catalyst-eligible AND momentum-eligible
(`is_no_catalyst_rejection=False`, `momentum_eval.eligible=True`) falls into
this `legacy_momentum` branch in the classifier. The simulator takes Path A
(catalyst) at line 1451 because `hard_rejection is None and scoring["score_pass"]`.
So the telemetry says `legacy_momentum` while the actual path is `catalyst`.

Net effect: every real legacy-momentum candidate is labeled `no_catalyst`
(see point 7), and some catalyst candidates are labeled `legacy_momentum`.
The headline `catalyst+_mm_meta → catalyst` fix is correct, but `legacy_momentum`
labeling is broken.

### 9. rejected-before-path candidates labeled correctly — **PASS**

`hard_rejection is not None and not is_no_catalyst_rejection` → matches the
exact state when the simulator's Paths A/B/C/D all skip (hard rejected for a
reason other than missing catalysts). Runtime sample shows all 51 candidates
labeled `rejected_before_path` with `regime_used=raw, consumed=False` because
the market session is closed — consistent with the simulator.

### 10. Raw / adjusted / used regime labels exposed — **PASS**

The candidate row now carries:

- `market_regime_label_before_trend`: `(_tick_regime or {}).get("regime")`
- `market_regime_label_after_trend`: `(_tick_regime_adjusted or {}).get("regime")` (or `None`)
- `market_trend_regime_label_used`: switches on `_trend_path_regime_used`

Runtime sample confirms all three populated. When `_trend_path_regime_used=raw`
the `used` label tracks `before`; when `trend_adjusted` it tracks `after`.
No new label-field invariants are violated.

### 11. Catalyst path remains not hard-blocked by trend — **PASS**

`MARKET_TREND_APPLY_TO_CATALYST` defaults to `False` in
`core/config.py:73`. The classifier's `catalyst` branch sets
`_trend_path_consumed = _trend_apply_catalyst and _tick_regime_adjusted is not None`
— always `False` under defaults. No code path in this patch hard-blocks or
soft-blocks the catalyst entry decision based on trend. Path A's gate
(`hard_rejection is None and scoring["score_pass"]`) is untouched.

### 12. No TP/SL/exit behavior changed — **PASS**

`git diff 2e9f811 -- backend/paper/simulator.py` shows changes only in:

- consumer-flag block at line 722–731
- new trend-path classifier at line 1264–1305
- candidate-dict trend-related keys at line 1378–1395
- shadow-scoring call site at line 1701–1716

No edits to `_check_exit`, hold-time, position sizing, or `exits.py`.

### 13. No broker / live / real-order code added — **PASS**

`grep -rEi "openai|anthropic|ollama|langchain|alpaca|broker|live_trading"
backend/paper/simulator.py backend/tests/test_phase_m1_h2.py` returns no new
hits introduced by the patch.

### 14. No OpenAI/Anthropic/Ollama/LLM calls added — **PASS**

Same grep above. No new external integrations, no new clients, no new
secrets. `compute_shadow_score` is the existing deterministic rule-based
shadow path — only its `tick_regime` input was rewired.

### 15. No futures / provider dependency added — **PASS**

`MARKET_TREND_SOURCE` still defaults to `"etf_proxy"`. No new symbol
configuration, no Polygon futures/index endpoints, no new HTTP clients. The
ETF-proxy-only invariant from M1 is preserved.

### 16. Backend tests and frontend build pass — **PASS**

- Backend: `1176 passed, 14 skipped, 2 warnings in 17.33s` reported.
  Independent run inside the container confirms `tests/test_phase_m1_h2.py`
  contains 12 passing tests.
- Frontend: clean `next build`, page 28.4 kB, first-load JS 115 kB.

### 17. Safe for fake-money monitoring — **YES, with one follow-up**

The patch never enters live orders, never calls a broker, never invokes an
LLM, never depends on futures. It only touches simulator telemetry and the
shadow scorer input wiring. The path classifier mislabel (point 8) is a
**telemetry accuracy bug**, not a trading-behavior bug — entry decisions
still flow through the unchanged simulator decision tree.

---

## 3. New defects introduced by M1-H2

### D1. legacy_momentum path classifier ordering bug (medium severity)

**Where:** `backend/paper/simulator.py:1290–1292`

```python
elif momentum_eval and momentum_eval.get("eligible"):
    _trend_path_name = "legacy_momentum"
    …
```

**Why it's wrong:** The simulator's Path B (line 1632) only entries
`entry_mode="momentum"` when `is_no_catalyst_rejection=True`. By the time
the classifier reaches its `momentum_eval` branch, `is_no_catalyst_rejection`
is already known to be False (the two preceding `elif`s consumed all
no-catalyst-rejection states). So the classifier's `legacy_momentum` branch
never matches a real legacy-momentum candidate.

**Observable consequences:**

- A real legacy-momentum entry (`entry_mode="momentum"`) shows up in
  telemetry as `market_trend_path_name="no_catalyst"`. Auditors looking
  for legacy-momentum behavior will miss it.
- A catalyst-eligible candidate that is also momentum-eligible is labeled
  `legacy_momentum` even though Path A (catalyst, line 1451) actually drives
  the entry. The trend-consumed/regime-used fields then follow
  `_trend_apply_legacy` (default `False`), so the telemetry happens to be
  *raw/not consumed* in practice — which matches what the catalyst path
  would have reported anyway. The label string is wrong but the
  regime-source claim is accidentally correct.

**Suggested fix (Phase M1-H3):**

Replace the single `legacy_momentum` branch with two refinements **inside**
the `is_no_catalyst_rejection` branch, mirroring the simulator's Path
B/C/D order:

```python
if hard_rejection is not None and not is_no_catalyst_rejection:
    _trend_path_name = "rejected_before_path"
    …
elif is_no_catalyst_rejection and _mm_meta is not None and _mm_entry_eligible:
    _trend_path_name = "market_mover_no_catalyst"
    …
elif is_no_catalyst_rejection and nc_eval is not None and nc_eval.get("eligible"):
    _trend_path_name = "no_catalyst"
    …
elif is_no_catalyst_rejection and momentum_eval is not None and momentum_eval.get("eligible"):
    _trend_path_name = "legacy_momentum"
    …
elif is_no_catalyst_rejection:
    _trend_path_name = "no_catalyst_rejected"  # or keep "rejected_before_path"
    …
else:
    _trend_path_name = "catalyst"
    …
```

This makes `legacy_momentum` match the simulator's actual Path B guard, and
removes the spurious `legacy_momentum` label from catalyst candidates.

### D2. `trend_consumers` reads `settings.X` directly (low severity)

**Where:** `backend/market/trend.py:296–300`

trend.py reads consumer flags from `settings.MARKET_TREND_APPLY_TO_*`
directly while the simulator routes them through `_cfg(...)`. Under the
current schema these are equivalent. If any consumer flag becomes
runtime-tunable later, the API/dashboard will publish stale values while
the simulator follows the runtime override.

**Suggested fix:** use `from paper.runtime_config import effective_value as
_cfg` and read each consumer flag via `_cfg("MARKET_TREND_APPLY_TO_*")` in
`get_trend()`. Or add an explicit assertion/comment that these flags are
intentionally non-runtime.

### D3. Source-needle test is structural, not behavioural (low severity)

**Where:** `backend/tests/test_phase_m1_h2.py::test_simulator_path_classifier_keys_present_in_source`

The test asserts that the classifier-related identifiers appear in
`run_tick`'s source. It passes if the strings are present even if the
ordering or guards are wrong. The mirrored `_classify()` helper at the top
of the same file is the only check that actually validates classification
behaviour — and because it's a hand-written mirror rather than an extract
of the real classifier, it can drift from `run_tick` silently.

**Suggested fix:** extract the classifier into a module-level pure function
(e.g. `paper.simulator._classify_trend_path(...)`) that both `run_tick` and
the test import directly. Today's mirror is at risk of becoming stale.

---

## 4. Runtime evidence

51 candidates evaluated (market closed):

```
path_names         = {rejected_before_path: 51}
regime_used        = {raw: 51}
consumed           = {False: 51}
shadow_consumed    = {True: 51}
shadow_regime_used = {trend_adjusted: 51}
```

All non-rejected-before-path branches (`market_mover_no_catalyst`,
`no_catalyst`, `legacy_momentum`, `catalyst`) are unexercised at runtime in
this sample — the headline regression fix is therefore verified only by the
hand-mirrored unit-test classifier, not by live data. A market-open
verification run is recommended before declaring M1 complete.

---

## 5. Recommended next phase

**Phase M1-H3** — single-file follow-up:

1. Fix D1 by extracting `_classify_trend_path(...)` as a module-level
   function and refactor the classifier branches to mirror Path A → D → C →
   B order with explicit `nc_eval` / `momentum_eval` differentiation inside
   the `is_no_catalyst_rejection` branch.
2. Replace `test_simulator_path_classifier_keys_present_in_source` with a
   direct import-and-call of the new helper.
3. Optionally: route `trend.get_trend()`'s consumer reads through `_cfg`.

Estimated diff: ~60 lines simulator, ~30 lines tests.

---

## 6. Unchanged-invariants checklist

| # | Invariant | Verdict |
|---|---|---|
| 12 | TP/SL/exit behavior unchanged | ✅ |
| 13 | No broker/live/real-order code | ✅ |
| 14 | No OpenAI/Anthropic/Ollama/LLM | ✅ |
| 15 | No futures/provider dependency | ✅ |
| 11 | Catalyst path not hard-blocked by trend | ✅ |
|  – | _tick_regime never mutated in place | ✅ (preserved from M1-H1) |
|  – | Shadow scorer receives the regime its consumer flag advertises | ✅ |

---

## 7. Summary

The two issues Codex flagged in M1-H1 are fixed:

- **Shadow scorer wiring**: actually consumes the regime its flag claims.
- **Catalyst+_mm_meta**: no longer mislabeled `market_mover`.

The patch introduces one new accuracy bug (D1) in the `legacy_momentum`
branch of the path classifier, plus two low-severity follow-ups (D2/D3).
None of these affect entry decisions, exits, broker boundaries, or LLM
posture. M1-H2 is **safe for fake-money monitoring as shipped**; a Phase
M1-H3 to address D1 is recommended before calling M1 fully complete.
