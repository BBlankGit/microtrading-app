"""
Safety invariant tests: verify that no broker SDK, order execution, or
AI/LLM imports exist in executable backend code for this phase.
These tests scan source files rather than importing them.
"""
import pathlib
import re


_BACKEND_DIR = pathlib.Path(__file__).parent.parent
_SOURCE_DIRS = [
    _BACKEND_DIR / "api",
    _BACKEND_DIR / "catalysts",
    _BACKEND_DIR / "core",
    _BACKEND_DIR / "data",
    _BACKEND_DIR / "main.py",
]

_EXCLUDED_DIRS = {"__pycache__"}


def _source_files():
    for target in _SOURCE_DIRS:
        if target.is_file():
            yield target
        elif target.is_dir():
            for f in target.rglob("*.py"):
                if not any(part in _EXCLUDED_DIRS for part in f.parts):
                    yield f


def _all_source_text() -> list[tuple[pathlib.Path, str]]:
    results = []
    for f in _source_files():
        results.append((f, f.read_text(encoding="utf-8")))
    return results


# ── Broker / execution SDK ───────────────────────────────────────────────────

_BROKER_PATTERNS = [
    r"\balpaca\b",
    r"\balpaca_trade_api\b",
    r"\bibkr\b",
    r"\bib_insync\b",
    r"\binteractive_brokers\b",
    r"\bschwab\b",
    r"\btd_ameritrade\b",
    r"\brobin_stocks\b",
]


def test_no_broker_sdk_imports():
    sources = _all_source_text()
    violations = []
    for path, text in sources:
        for pattern in _BROKER_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"{path.relative_to(_BACKEND_DIR)}: matched '{pattern}'")
    assert not violations, "Broker SDK imports found:\n" + "\n".join(violations)


# ── Order execution routes / function names ──────────────────────────────────

_ORDER_PATTERNS = [
    r'["\'/](?:place|submit|create|execute|send)[_-]?orders?["\'/]',
    r'\bplace_order\b',
    r'\bsubmit_order\b',
    r'\bcreate_order\b',
    r'\bexecute_order\b',
    r'\bsend_order\b',
    r'router\.(?:post|put)\s*\(\s*["\'][^"\']*orders?["\']',
]


def test_no_order_execution_routes():
    sources = _all_source_text()
    violations = []
    for path, text in sources:
        for pattern in _ORDER_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"{path.relative_to(_BACKEND_DIR)}: matched '{pattern}'")
    assert not violations, "Order execution route/function patterns found:\n" + "\n".join(violations)


# ── AI / LLM SDK imports ─────────────────────────────────────────────────────

_AI_IMPORT_PATTERNS = [
    r'^\s*import\s+openai\b',
    r'^\s*from\s+openai\b',
    r'^\s*import\s+anthropic\b',
    r'^\s*from\s+anthropic\b',
    r'^\s*import\s+langchain\b',
    r'^\s*from\s+langchain\b',
    r'^\s*import\s+llama_index\b',
    r'^\s*from\s+llama_index\b',
]


def test_no_ai_llm_imports_in_executable_code():
    sources = _all_source_text()
    violations = []
    for path, text in sources:
        for pattern in _AI_IMPORT_PATTERNS:
            if re.search(pattern, text, re.MULTILINE):
                violations.append(f"{path.relative_to(_BACKEND_DIR)}: matched '{pattern}'")
    assert not violations, "AI/LLM SDK imports found:\n" + "\n".join(violations)
