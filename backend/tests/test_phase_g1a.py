"""
Phase G1A — Local Ollama LLM provider.

Fake-money simulation only. Verifies:
  - provider=ollama does not require OPENAI_API_KEY
  - provider=openai with `optional_change_me` (and other broadened
    placeholders) is treated as missing_api_key
  - ollama unreachable → provider_unavailable, no crash
  - missing model → model_missing, no crash
  - valid Ollama JSON normalizes correctly
  - invalid Ollama response → error, no trading impact
  - existing OpenAI safety semantics preserved
  - LLM still shadow-only (defaults to provider="ollama", enabled=False)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest


def _reset_llm_module():
    from intelligence import llm_shadow as L
    L._cache.clear()
    L._probe_cache.clear()
    L._status.update({
        "calls_total": 0, "calls_last_tick": 0, "calls_success": 0,
        "calls_error": 0, "cache_hits": 0, "cache_misses": 0,
        "latency_ms_sum": 0,
        "last_call_at": None, "last_success_at": None,
        "last_error": None, "last_model_used": None,
    })


# ── Defaults: ollama provider, disabled, no key required ────────────────────

def test_default_provider_is_ollama():
    from core.config import settings
    assert settings.LLM_PROVIDER == "ollama"
    assert settings.LLM_SHADOW_ENABLED is False


def test_status_reports_provider_and_base_url_with_no_key_required():
    from core.config import settings
    from intelligence import llm_shadow as L

    _reset_llm_module()
    with patch.object(settings, "LLM_PROVIDER", "ollama"):
        s = L.get_status()
    assert s["provider"] == "ollama"
    assert s["api_key_required"] is False
    assert s["base_url"] and s["base_url"].startswith("http")


# ── Broadened placeholder denylist ──────────────────────────────────────────

@pytest.mark.parametrize("placeholder", [
    "", "PASTE_YOUR_KEY_HERE", "CHANGEME", "CHANGE_ME",
    "OPTIONAL_CHANGE_ME", "optional_change_me", "OPTIONAL",
    "NONE", "NULL", "YOUR_KEY", "YOUR_API_KEY", "SECRET", "TODO",
    "API_KEY_PLACEHOLDER",
])
def test_api_key_placeholders_rejected(monkeypatch, placeholder):
    from core.config import settings
    from intelligence import llm_shadow as L

    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    if placeholder == "":
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", placeholder)
    assert L.api_key_present() is False


def test_real_looking_key_accepted(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L

    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real123456789abcdef0123456789")
    assert L.api_key_present() is True


# ── provider=openai with placeholder → missing_api_key, no call ─────────────

def test_openai_with_placeholder_does_not_call(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "optional_change_me")

    async def _no_call(*_a, **_k):
        raise AssertionError("OpenAI must NOT be called with a placeholder key")

    monkeypatch.setattr(httpx.AsyncClient, "post", _no_call)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "missing_api_key"


# ── provider=ollama unreachable → provider_unavailable ─────────────────────

def test_ollama_unavailable_returns_provider_unavailable(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:65500")

    async def _conn_err(self, url, *args, **kwargs):
        raise httpx.ConnectError("conn refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", _conn_err)
    monkeypatch.setattr(httpx.AsyncClient, "post", _conn_err)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "provider_unavailable"


# ── Provider available but model missing ───────────────────────────────────

def test_ollama_model_missing_returns_model_missing(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_MODEL", "ghost-model:1b")

    class TagsResp:
        status_code = 200
        def json(self):
            return {"models": [{"name": "qwen2.5:7b-instruct"}]}

    async def _get(self, url, *args, **kwargs):
        return TagsResp()

    async def _no_post(self, url, *args, **kwargs):
        raise AssertionError("must not call /api/generate when model missing")

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _no_post)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "model_missing"


# ── Valid Ollama response normalizes correctly ─────────────────────────────

def test_ollama_valid_response_normalizes(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_MODEL", "qwen2.5:7b-instruct")

    valid_payload = {
        "llm_decision": "WATCH",
        "llm_confidence": 0.6,
        "llm_time_horizon": "intraday",
        "llm_impact_assessment": "medium",
        "llm_directional_bias": "bullish",
        "llm_expected_move": "moderate_up",
        "llm_agrees_with_engine": True,
        "llm_agrees_with_shadow": False,
        "llm_primary_reason": "good vol",
        "llm_supporting_factors": ["earnings beat"],
        "llm_risk_factors": ["wide market down"],
        "llm_missing_data": [],
        "llm_do_not_trade_reason": None,
        "llm_score_adjustment_suggestion": 4,
        "llm_recommended_action": "wait_for_confirmation",
        "llm_recommended_confirmation": "volume_acceleration",
        "llm_summary": "watch",
    }

    class TagsResp:
        status_code = 200
        def json(self):
            return {"models": [{"name": "qwen2.5:7b-instruct"}]}

    class GenResp:
        status_code = 200
        def json(self):
            return {"response": json.dumps(valid_payload)}

    async def _get(self, url, *args, **kwargs): return TagsResp()
    async def _post(self, url, *args, **kwargs): return GenResp()

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "AAPL"}}))
    assert out["llm_status"] == "ok"
    assert out["llm_decision"] == "WATCH"
    assert out["llm_confidence"] == 0.6
    assert out["llm_provider"] == "ollama"
    assert out["llm_model"] == "qwen2.5:7b-instruct"


# ── Ollama returns prose around JSON — extractor recovers ──────────────────

def test_ollama_json_extracted_from_surrounding_prose(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)

    valid = {"llm_decision": "WOULD_REJECT", "llm_confidence": 0.3,
             "llm_recommended_action": "monitor_only", "llm_summary": ""}

    class TagsResp:
        status_code = 200
        def json(self): return {"models": [{"name": "qwen2.5:7b-instruct"}]}

    class GenResp:
        status_code = 200
        def json(self):
            wrapped = f"Sure! Here is the JSON:\n```\n{json.dumps(valid)}\n```\nThanks."
            return {"response": wrapped}

    async def _get(self, url, *args, **kwargs): return TagsResp()
    async def _post(self, url, *args, **kwargs): return GenResp()

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "ok"
    assert out["llm_decision"] == "WOULD_REJECT"


# ── Ollama returns garbage → error, no crash ───────────────────────────────

def test_ollama_invalid_json_returns_error(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_MAX_RETRIES", 0)

    class TagsResp:
        status_code = 200
        def json(self): return {"models": [{"name": "qwen2.5:7b-instruct"}]}

    class GenResp:
        status_code = 200
        def json(self): return {"response": "i refuse to comply, no json here at all"}

    async def _get(self, url, *args, **kwargs): return TagsResp()
    async def _post(self, url, *args, **kwargs): return GenResp()

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "error"
    assert L._status["calls_error"] >= 1


# ── Shadow-only invariant: result shape never carries trading control ──────

def test_llm_result_shape_has_no_trading_control_fields():
    from intelligence.llm_shadow import default_not_selected_result

    d = default_not_selected_result()
    # The LLM result MUST NOT include keys that the simulator uses for
    # eligibility / action / entry_mode.
    forbidden = {"eligible", "action", "entry_mode", "score_pass",
                 "rejection_reason", "decision_reason"}
    assert not (forbidden & set(d.keys()))


# ── Status accessor still does not invoke the provider when probes cached ──

@pytest.mark.asyncio
async def test_async_status_uses_cached_probe_for_availability(monkeypatch):
    """When the probe cache says available, the async status reports it
    without making another tags call. (The model-available check may still
    issue one call to refresh the installed list, since cached probe only
    stores availability not names.)"""
    from core.config import settings
    from intelligence import llm_shadow as L

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

    import time as _t
    L._probe_cache["tags"] = (True, _t.monotonic())

    async def _names_only():
        return ["qwen2.5:7b-instruct"]

    monkeypatch.setattr(L, "_probe_ollama_tags", _names_only)
    s = await L.get_status_async()
    assert s["local_provider_available"] is True
    assert s["model_available"] is True
    assert "qwen2.5:7b-instruct" in s["models_installed"]


# ── Hard-coded provider tokens ─────────────────────────────────────────────

def test_known_provider_tokens_present_in_source():
    """The Ollama provider must be wired in the dispatch chain alongside the
    OpenAI provider."""
    import inspect
    from intelligence import llm_shadow as L

    src = inspect.getsource(L)
    for needle in (
        "_ollama_call",
        "_openai_call",
        "provider_unavailable",
        "model_missing",
        "host.docker.internal",
        "_extract_json_object",
    ):
        assert needle in src, f"missing needle {needle!r}"
