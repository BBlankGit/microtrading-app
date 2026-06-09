# Codex Review: Phase 2R-H2 No-Catalyst Momentum Score Schema Alignment

Review date: 2026-06-09

Scope: latest Phase 2R-H2 patch only (`HEAD^..HEAD`, commit `3e331c2`).

Reviewed files changed by the patch:

- `backend/core/config.py`
- `backend/tests/test_phase_2r.py`

## Executive summary

Phase 2R-H2 is safe for fake-money monitoring. The patch aligns the no-catalyst momentum component default with the runtime schema ceiling by changing `PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE` from `25` to `20`, and it adds targeted tests proving that the runtime schema accepts `20` and rejects `21`.

No production code outside the default config value changed in this patch. The no-catalyst feature remains disabled by default, the other conservative no-catalyst gates remain unchanged, the catalyst path remains unchanged, and the patch does not add broker/live-trading/real-order/AI/LLM/Ollama behavior.

## Review checklist

### 1. `PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE` default is now `20`

**PASS.** The latest patch changes only the default value in `backend/core/config.py` from `25` to `20`.

Current default:

```python
PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE: int = 20
```

This matches the runtime schema ceiling for the `momentum_score` component.

### 2. Runtime schema accepts `20` and rejects `21`

**PASS.** The schema entry for `PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE` remains an integer field with `min=0` and `max=20`. The generic validator rejects integers above the schema maximum with an `exceeds maximum` error.

The Phase 2R-H2 patch adds/updates tests to verify both edges:

- `20` is accepted: `validate_runtime_config({"PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE": 20})` returns `(True, [])`.
- `21` is rejected: `validate_runtime_config({"PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE": 21})` returns `(False, [...exceeds maximum 20...])`.

Manual verification also confirmed:

```text
default 20
enabled_default False
20 (True, [])
21 (False, ['PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE: 21 exceeds maximum 20'])
```

### 3. No-catalyst mode remains disabled by default

**PASS.** The default remains:

```python
PAPER_NO_CATALYST_ENTRY_ENABLED: bool = False
```

The no-catalyst evaluator still hard-rejects immediately when `PAPER_NO_CATALYST_ENTRY_ENABLED` is false, returning `no_catalyst_entry_disabled` before later entry gates are considered.

### 4. Other no-catalyst conservative gates remain unchanged

**PASS.** The latest patch changed only the min momentum score default and the associated tests. The other no-catalyst conservative defaults remain:

| Setting | Current default | Status |
| --- | ---: | --- |
| `PAPER_NO_CATALYST_ENTRY_ENABLED` | `False` | unchanged |
| `PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH` | `True` | unchanged |
| `PAPER_NO_CATALYST_MIN_SCORE` | `80` | unchanged |
| `PAPER_NO_CATALYST_MIN_CHANGE_PERCENT` | `2.0` | unchanged |
| `PAPER_NO_CATALYST_MIN_VOLUME_RATIO` | `1.5` | unchanged |
| `PAPER_NO_CATALYST_MAX_SPREAD_PERCENT` | `0.20` | unchanged |
| `PAPER_NO_CATALYST_REQUIRE_RISK_ON` | `True` | unchanged |
| `PAPER_NO_CATALYST_MIN_RISK_SCORE` | `60` | unchanged |
| `PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER` | `0.5` | unchanged |
| `PAPER_NO_CATALYST_MAX_TRADES_PER_DAY` | `20` | unchanged |

The evaluator still applies the same strict gate sequence: feature-enabled, bearish-catalyst block, total score, momentum component, price change, volume ratio, spread, and market-regime/risk-on.

### 5. Catalyst path remains unchanged

**PASS.** The latest patch did not change `backend/paper/simulator.py` or other catalyst-path implementation files. The simulator still prioritizes paths as documented by the no-catalyst module:

1. Path A: catalyst
2. Path C: no-catalyst momentum
3. Path B: momentum fallback

The actual entry branch for catalyst entries remains separate from the no-catalyst branch and uses `entry_mode="catalyst"`. Since Phase 2R-H2 changed only `backend/core/config.py` and `backend/tests/test_phase_2r.py`, catalyst execution behavior is unchanged by this patch.

### 6. No broker/live trading/real orders/AI/LLM/Ollama were added

**PASS.** The patch only changes a config default and tests. The no-catalyst module explicitly states:

- No broker.
- No live trading.
- No real orders.
- No real-money execution.
- No AI/LLM.
- Deterministic rule-based logic only.

The Phase 2R test module also includes forbidden-module and forbidden-execution checks covering OpenAI/Anthropic/LangChain/Ollama/broker integrations and order-submission function names.

### 7. Phase 2R-H2 safe for fake-money monitoring

**PASS.** Phase 2R-H2 is safe for fake-money monitoring because:

- It resolves the prior default/schema mismatch by setting the default to the schema ceiling of `20`.
- Runtime validation now has direct regression coverage for the boundary values `20` and `21`.
- No-catalyst mode remains off unless explicitly enabled at runtime/configuration.
- All other conservative no-catalyst gates remain in place.
- Catalyst path behavior is untouched.
- No broker/live-trading/real-order/AI/LLM/Ollama behavior is introduced.

## Tests and checks run

```bash
PYTHONPATH=backend pytest -q backend/tests/test_phase_2r.py
```

Result: `42 passed, 1 warning in 0.29s`.

```bash
PYTHONPATH=backend python - <<'PY'
from core.config import settings
from paper.runtime_config import validate_runtime_config, effective_value
print('default', settings.PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE)
print('enabled_default', effective_value('PAPER_NO_CATALYST_ENTRY_ENABLED'))
print('20', validate_runtime_config({'PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE': 20}))
print('21', validate_runtime_config({'PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE': 21}))
PY
```

Result:

```text
default 20
enabled_default False
20 (True, [])
21 (False, ['PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE: 21 exceeds maximum 20'])
```

```bash
git diff --name-only HEAD^..HEAD
git diff --stat HEAD^..HEAD
```

Result: latest patch changes only `backend/core/config.py` and `backend/tests/test_phase_2r.py`.

## Verdict

Approved for fake-money monitoring. Phase 2R-H2 is a narrow schema-alignment patch with adequate boundary test coverage and no expansion into live trading, broker connectivity, real orders, or AI/LLM functionality.
