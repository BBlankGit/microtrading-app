"""
Phase L1-H2 — Hardened secret redaction in LLM packet / error fields.

Fake-money simulation only. Verifies the broadened _redact() helper
catches Bearer tokens, sk-* keys, and `name=value` / `name:"value"` forms
for a curated list of secret-bearing key names, including URL query
strings. The helper must NEVER over-redact short non-credential values.
"""
from __future__ import annotations

import pytest


# ── Bare secret patterns ────────────────────────────────────────────────────

def test_redact_bearer_token():
    from intelligence.llm_shadow import _redact

    out = _redact("Authorization: Bearer abcdef123456ghi")
    assert "abcdef123456ghi" not in out
    assert "<redacted>" in out


def test_redact_bearer_token_case_insensitive():
    from intelligence.llm_shadow import _redact

    out = _redact("authorization: bearer xyz987654abc")
    assert "xyz987654abc" not in out


def test_redact_openai_sk_key():
    from intelligence.llm_shadow import _redact

    out = _redact("error using sk-VERY_SECRET_KEY_ABCDEF1234567890 failed")
    assert "sk-VERY_SECRET_KEY" not in out
    assert "<redacted>" in out


# ── Query-param / assignment-style secret patterns ──────────────────────────

@pytest.mark.parametrize("key_name", [
    "apiKey", "apikey", "api_key", "api-key",
    "token", "TOKEN", "access_token", "access-token", "accessToken",
    "refresh_token", "refreshToken",
    "secret_key", "secret-key",
])
def test_redact_known_key_assignment(key_name):
    from intelligence.llm_shadow import _redact

    out = _redact(f"{key_name}=abc123XYZ")
    assert "abc123XYZ" not in out, f"value leaked when key={key_name!r}: {out!r}"
    assert key_name in out  # name preserved
    assert "<redacted>" in out


@pytest.mark.parametrize("env_name", [
    "POLYGON_API_KEY", "FINNHUB_API_KEY",
    "NEWSAPI_KEY", "NEWS_API_KEY",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "API_KEY",
])
def test_redact_env_style_assignment(env_name):
    from intelligence.llm_shadow import _redact

    out = _redact(f"{env_name}=abc123XYZ")
    assert "abc123XYZ" not in out, f"value leaked when key={env_name!r}: {out!r}"
    assert env_name in out
    assert "<redacted>" in out


def test_redact_url_query_string():
    from intelligence.llm_shadow import _redact

    url = "https://api.example.com/data?apikey=secret123def&symbol=AAPL"
    out = _redact(url)
    assert "secret123def" not in out
    assert "symbol=AAPL" in out  # non-secret param preserved
    assert "apikey=" in out      # param name preserved


def test_redact_polygon_url_with_apikey():
    from intelligence.llm_shadow import _redact

    url = "https://api.polygon.io/v2/snapshot?apiKey=SECRET_VAL_12345&ticker=AAPL"
    out = _redact(url)
    assert "SECRET_VAL_12345" not in out
    assert "ticker=AAPL" in out


def test_redact_json_style_quoted_value():
    from intelligence.llm_shadow import _redact

    out = _redact('{"api_key": "supersecret123"}')
    assert "supersecret123" not in out
    assert "<redacted>" in out


def test_redact_colon_separator():
    from intelligence.llm_shadow import _redact

    out = _redact("config token: longvaluexyz123")
    assert "longvaluexyz123" not in out


# ── False-positive guards ───────────────────────────────────────────────────

def test_redact_does_not_overmatch_short_values():
    """Values < 6 chars should NOT be redacted — avoids false positives like
    'key=true', 'token=null', 'sort_key=42'."""
    from intelligence.llm_shadow import _redact

    out = _redact("key=true")
    assert "true" in out
    assert "<redacted>" not in out

    out2 = _redact("token=null")
    assert "null" in out2
    assert "<redacted>" not in out2

    out3 = _redact("sort_key=42")
    assert "42" in out3


def test_redact_does_not_match_unrelated_phrases():
    """Plain English mentions of 'key', 'token', 'API_KEY' without an
    assignment must remain unchanged."""
    from intelligence.llm_shadow import _redact

    s = "the API key is rotated weekly; the token expires after 1h"
    out = _redact(s)
    assert out == s


def test_redact_preserves_empty_input():
    from intelligence.llm_shadow import _redact

    assert _redact("") == ""
    assert _redact(None) == ""


# ── Packet integration ─────────────────────────────────────────────────────

def test_packet_marketdata_error_redacts_env_assignment():
    """Polygon error text echoing an env-style assignment must be sanitized
    before it lands on the LLM packet."""
    from intelligence.llm_shadow import build_candidate_packet

    cand = {
        "symbol": "AAPL",
        "marketdata_error":
            "polygon http 403: invalid POLYGON_API_KEY=topsecret_value_xyz123",
    }
    pkt = build_candidate_packet(cand)
    err = pkt["marketdata"]["marketdata_error"] or ""
    assert "topsecret_value_xyz123" not in err
    assert "<redacted>" in err
    assert pkt["marketdata"]["marketdata_missing"] is True


def test_packet_marketdata_error_redacts_url_query():
    from intelligence.llm_shadow import build_candidate_packet

    cand = {
        "symbol": "AAPL",
        "marketdata_error":
            "GET https://api.polygon.io/v2/snapshot?apiKey=SECRET_KEY_1234abcd failed",
    }
    pkt = build_candidate_packet(cand)
    err = pkt["marketdata"]["marketdata_error"] or ""
    assert "SECRET_KEY_1234abcd" not in err
    # The URL skeleton survives so the LLM still sees the failing path.
    assert "polygon" in err.lower()


def test_llm_status_last_error_redacted_on_failure(monkeypatch):
    """A provider error containing a key must not appear in
    intelligence.llm_shadow._status.last_error."""
    import asyncio
    import httpx
    from core.config import settings
    from intelligence import llm_shadow as L

    # Reset module state
    L._cache.clear()
    L._status.update({
        "calls_total": 0, "calls_last_tick": 0, "calls_success": 0,
        "calls_error": 0, "cache_hits": 0, "cache_misses": 0,
        "latency_ms_sum": 0,
        "last_call_at": None, "last_success_at": None,
        "last_error": None, "last_model_used": None,
    })

    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecret1234567890")
    monkeypatch.setattr(settings, "LLM_SHADOW_MAX_RETRIES", 0)

    async def _err_post(self, url, json=None, headers=None):
        raise httpx.ConnectError(
            "boom: target https://api.openai.com/v1/chat/completions?apikey=sk-supersecret1234567890"
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", _err_post)
    asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    last_err = L._status.get("last_error") or ""
    assert "sk-supersecret1234567890" not in last_err
    assert "<redacted>" in last_err or last_err == ""


# ── No new external calls or log changes ───────────────────────────────────

def test_redact_is_pure_no_external_calls():
    """AST-walk: _redact and helpers must not make any function call that
    looks like network I/O (httpx, requests, urlopen, etc)."""
    import ast
    import pathlib

    src = (pathlib.Path(__file__).parent.parent
           / "intelligence" / "llm_shadow.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_redact":
            # No httpx/requests/urlopen calls inside the function body.
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    fn = inner.func
                    name = ""
                    if isinstance(fn, ast.Name):
                        name = fn.id
                    elif isinstance(fn, ast.Attribute):
                        name = fn.attr
                    assert name not in {"get", "post", "urlopen", "request"}, (
                        f"_redact must not perform network I/O — found call to {name!r}"
                    )
            return
    pytest.fail("_redact function not found in llm_shadow.py")


def test_full_prompt_logging_still_off_by_default():
    from core.config import settings

    # The default must remain False — L1-H2 must not enable prompt logging.
    assert settings.LLM_SHADOW_LOG_PROMPTS is False
