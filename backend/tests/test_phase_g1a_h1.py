"""
Phase G1A-H1 — Provider-aware simulator tick gate.

Verifies that the paper simulator's section-4c LLM injection no longer
gates on the OpenAI-era api_key_present() check, and instead routes
through intelligence.llm_shadow.simulator_ready(). Fake-money simulation
only; no real LLM calls in any test.

Matrix:
   LLM disabled                                → (False, "disabled")
   provider=openai + missing key               → (False, "missing_api_key")
   provider=openai + placeholder key           → (False, "missing_api_key")
   provider=openai + sk-* looking key          → (True,  "not_selected")
   provider=ollama + no OPENAI_API_KEY         → (True,  "not_selected")
   provider=ollama + placeholder OPENAI key    → (True,  "not_selected")
   provider=anything-else                      → (False, "provider_not_supported")
"""
from __future__ import annotations

import ast
import inspect

import pytest


# ── simulator_ready() truth table ────────────────────────────────────────────

def test_simulator_ready_disabled(monkeypatch):
    from core.config import settings
    from intelligence.llm_shadow import simulator_ready

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    ready, status = simulator_ready()
    assert ready is False
    assert status == "disabled"


def test_simulator_ready_openai_missing_key(monkeypatch):
    from core.config import settings
    from intelligence.llm_shadow import simulator_ready

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ready, status = simulator_ready()
    assert ready is False
    assert status == "missing_api_key"


def test_simulator_ready_openai_placeholder(monkeypatch):
    from core.config import settings
    from intelligence.llm_shadow import simulator_ready

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "optional_change_me")
    ready, status = simulator_ready()
    assert ready is False
    assert status == "missing_api_key"


def test_simulator_ready_openai_with_valid_looking_key(monkeypatch):
    from core.config import settings
    from intelligence.llm_shadow import simulator_ready

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real1234567890abcdef0123456789")
    ready, status = simulator_ready()
    assert ready is True
    assert status == "not_selected"


def test_simulator_ready_ollama_without_openai_key(monkeypatch):
    """The key change: provider=ollama must NOT require OPENAI_API_KEY."""
    from core.config import settings
    from intelligence.llm_shadow import simulator_ready

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ready, status = simulator_ready()
    assert ready is True
    assert status == "not_selected"


def test_simulator_ready_ollama_with_placeholder_openai_key_ignored(monkeypatch):
    """Even if a placeholder OPENAI_API_KEY is set, ollama provider ignores it."""
    from core.config import settings
    from intelligence.llm_shadow import simulator_ready

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "optional_change_me")
    ready, status = simulator_ready()
    assert ready is True
    assert status == "not_selected"


def test_simulator_ready_unsupported_provider(monkeypatch):
    from core.config import settings
    from intelligence.llm_shadow import simulator_ready

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    ready, status = simulator_ready()
    assert ready is False
    assert status == "provider_not_supported"


# ── Simulator wiring (AST checks) ───────────────────────────────────────────

def _run_tick_src() -> str:
    import paper.simulator as sim
    return inspect.getsource(sim.run_tick)


def test_simulator_no_longer_gates_on_api_key_present():
    """
    After Phase G1A-H1, run_tick must not contain a condition that calls
    _llm_mod.api_key_present() to decide whether to run LLM analysis.
    """
    src = _run_tick_src()
    assert "_llm_mod.api_key_present()" not in src, (
        "run_tick still uses api_key_present() — should call simulator_ready() instead"
    )


def test_simulator_uses_simulator_ready_helper():
    """run_tick must call _llm_mod.simulator_ready()."""
    src = _run_tick_src()
    assert "_llm_mod.simulator_ready()" in src, (
        "run_tick must use the provider-aware simulator_ready() helper"
    )


def test_simulator_default_status_comes_from_simulator_ready():
    """The candidate default LLM status string must come from
    simulator_ready()'s second return value (a local named _llm_default_status)
    — not from a hardcoded literal."""
    src = _run_tick_src()
    assert "_llm_default_status" in src


# ── provider=ollama disabled → still "disabled" status (no overreach) ───────

@pytest.mark.asyncio
async def test_disabled_does_not_call_provider(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

    async def _no_get(*a, **k):
        raise AssertionError("status probe must not run while disabled")
    async def _no_post(*a, **k):
        raise AssertionError("no analyze when disabled")

    monkeypatch.setattr(httpx.AsyncClient, "get", _no_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _no_post)
    out = await L.analyze_candidate_packet({"identity": {"symbol": "X"}})
    assert out["llm_status"] == "disabled"


# ── provider=ollama enabled but unreachable returns provider_unavailable ───

@pytest.mark.asyncio
async def test_ollama_unreachable_returns_provider_unavailable(monkeypatch):
    """Critical: when provider=ollama is enabled but the local endpoint is
    down, the simulator's per-candidate analyze should report
    "provider_unavailable" — NOT "missing_api_key" (the old OpenAI-era
    error)."""
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    L._cache.clear()
    L._probe_cache.clear()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:65500")
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def _conn_err(self, url, *args, **kwargs):
        raise httpx.ConnectError("conn refused")
    monkeypatch.setattr(httpx.AsyncClient, "get", _conn_err)

    out = await L.analyze_candidate_packet({"identity": {"symbol": "X"}})
    assert out["llm_status"] == "provider_unavailable"
    # NOT missing_api_key
    assert out["llm_status"] != "missing_api_key"


# ── provider=openai with placeholder must never POST to OpenAI ─────────────

@pytest.mark.asyncio
async def test_openai_placeholder_never_calls_openai(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    L._cache.clear()
    L._probe_cache.clear()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "optional_change_me")

    async def _no_post(*a, **k):
        raise AssertionError("OpenAI must NOT be POSTed with a placeholder key")
    monkeypatch.setattr(httpx.AsyncClient, "post", _no_post)
    out = await L.analyze_candidate_packet({"identity": {"symbol": "X"}})
    assert out["llm_status"] == "missing_api_key"


# ── Shadow-only invariant preserved ────────────────────────────────────────

def test_default_not_selected_result_still_has_no_trading_keys():
    from intelligence.llm_shadow import default_not_selected_result

    d = default_not_selected_result()
    forbidden = {"eligible", "action", "entry_mode", "score_pass",
                 "rejection_reason", "decision_reason"}
    assert not (forbidden & set(d.keys()))


# ── Source-truth: classifier path strings present ──────────────────────────

def test_simulator_ready_path_strings_present_in_module_source():
    import intelligence.llm_shadow as L

    src = inspect.getsource(L.simulator_ready)
    for needle in (
        '"disabled"',
        '"missing_api_key"',
        '"not_selected"',
        '"provider_not_supported"',
        "is_enabled",
        "provider",
        "api_key_present",
    ):
        assert needle in src, f"missing needle {needle!r}"
