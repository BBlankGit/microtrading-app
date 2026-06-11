"""
Phase L1-H3 — Dotted/punctuation token redaction.

Fake-money simulation only. Extends the L1-H2 redaction tests to cover
JWT-style dotted tokens, percent-encoded values, slash/plus/equals
padding, and colon-separated scopes. Also re-asserts the false-positive
guards from L1-H2.
"""
from __future__ import annotations

import pytest


# ── 1–4. Dotted / punctuation values are fully redacted ─────────────────────

def test_redact_dotted_token():
    from intelligence.llm_shadow import _redact

    out = _redact("token=abcdef.ghijkl")
    assert "abcdef" not in out
    assert "ghijkl" not in out
    assert "<redacted>" in out
    assert "token=" in out


def test_redact_jwt_three_part_access_token():
    from intelligence.llm_shadow import _redact

    out = _redact("access_token=abc.def.ghi")
    assert "abc" not in out.replace("access_token=<redacted>", "")
    assert ".def" not in out
    assert ".ghi" not in out
    assert "<redacted>" in out
    assert "access_token=" in out


def test_redact_dotted_short_first_segment_still_fully_redacted():
    """The L1-H2 regex stopped at '.', leaving '.ghijkl' visible. Make sure
    L1-H3 collapses the whole value, even when the first dot-segment is
    short."""
    from intelligence.llm_shadow import _redact

    # Total length 12 chars (including dots) — passes the >=6 guard.
    out = _redact("token=abc.defghi")
    assert "defghi" not in out, f"dotted suffix leaked: {out!r}"
    assert "<redacted>" in out


def test_redact_apikey_with_slash_plus_padding():
    from intelligence.llm_shadow import _redact

    out = _redact("apiKey=abc.def/ghi+123==")
    assert "abc.def/ghi+123==" not in out
    assert "<redacted>" in out
    assert "apiKey=" in out


def test_redact_percent_encoded_value():
    from intelligence.llm_shadow import _redact

    out = _redact("key=abc%2Fdef%2Bghi")
    assert "abc%2Fdef%2Bghi" not in out
    assert "<redacted>" in out


def test_redact_colon_separated_jwt_scope():
    from intelligence.llm_shadow import _redact

    # Tokens with colons in the value (e.g. JWT scopes encoded inline).
    out = _redact("token=user:42:read.write")
    assert "user:42:read.write" not in out
    assert "<redacted>" in out


# ── 5. Bearer / sk-* still redacted in dotted form ─────────────────────────

def test_bearer_dotted_token_still_fully_redacted():
    from intelligence.llm_shadow import _redact

    out = _redact("Authorization: Bearer abc.def.ghi")
    assert "abc.def.ghi" not in out
    assert "<redacted>" in out


def test_openai_quoted_sk_key_still_redacted():
    from intelligence.llm_shadow import _redact

    out = _redact('OPENAI_API_KEY="sk-abcdefghijklmnopqrstuvwxyz"')
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in out
    assert "<redacted>" in out


def test_polygon_dotted_key():
    from intelligence.llm_shadow import _redact

    out = _redact("POLYGON_API_KEY=abc.def.ghi")
    assert "abc.def.ghi" not in out
    assert "<redacted>" in out


# ── 6. URL with multiple params: only secret values redacted ───────────────

def test_url_redacts_only_secret_param_values():
    from intelligence.llm_shadow import _redact

    url = (
        "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
        "?apiKey=abc.def.ghi+xyz==&ticker=AAPL&limit=10"
    )
    out = _redact(url)
    assert "abc.def.ghi+xyz==" not in out
    # Non-secret params are preserved exactly.
    assert "ticker=AAPL" in out
    assert "limit=10" in out
    assert "apiKey=<redacted>" in out


def test_url_with_two_secret_params_both_redacted():
    from intelligence.llm_shadow import _redact

    url = (
        "https://example.com/x?access_token=abc.def.ghi&apikey=zzz.yyy.xxx"
        "&symbol=AAPL"
    )
    out = _redact(url)
    assert "abc.def.ghi" not in out
    assert "zzz.yyy.xxx" not in out
    assert "symbol=AAPL" in out


# ── 7. False-positive guards (same tradeoffs as L1-H2) ─────────────────────

def test_false_positive_guard_short_values_not_redacted():
    """Values shorter than the {6,} minimum are left alone."""
    from intelligence.llm_shadow import _redact

    for s in ("key=1", "key=true", "token=no", "token=null"):
        out = _redact(s)
        assert out == s, f"unexpected redaction on {s!r}: {out!r}"


def test_false_positive_guard_dotted_short_values_not_redacted():
    """Short dotted natural strings like 'key=v1.0' (5 chars incl. dot) are
    below the {6,} threshold and stay unchanged. Documented tradeoff:
    once a dotted value crosses 6 chars (e.g. 'key=v1.0.0' → 6 chars), it
    DOES get redacted. This is the intended behavior since 6+ char dotted
    strings are far more likely to be real credentials than English."""
    from intelligence.llm_shadow import _redact

    out_short = _redact("key=v1.0")
    assert out_short == "key=v1.0"

    # Documented tradeoff: this would be redacted.
    out_six = _redact("key=v1.0.0")
    assert "<redacted>" in out_six


def test_false_positive_guard_unrelated_phrases_not_touched():
    from intelligence.llm_shadow import _redact

    s = "the API key is rotated weekly; the token expires after 1h"
    assert _redact(s) == s


def test_false_positive_guard_compound_key_names_not_matched():
    """sort_key=42, primary_key=42, secret_key_id=42 must NOT trigger the
    bare 'key=' rule — \\b prevents matching mid-word."""
    from intelligence.llm_shadow import _redact

    assert _redact("sort_key=42") == "sort_key=42"
    assert _redact("primary_key=42") == "primary_key=42"


# ── 8. Packet-level integration with a dotted Polygon token ────────────────

def test_packet_marketdata_error_redacts_dotted_token():
    from intelligence.llm_shadow import build_candidate_packet

    cand = {
        "symbol": "AAPL",
        "marketdata_error":
            "GET https://api.example.com/v1?apiKey=abc.def.ghi+xyz== failed",
    }
    pkt = build_candidate_packet(cand)
    err = pkt["marketdata"]["marketdata_error"] or ""
    assert "abc.def.ghi+xyz==" not in err
    assert "<redacted>" in err
    assert pkt["marketdata"]["marketdata_missing"] is True


# ── 9. Defensive: no prompt logging enabled, no provider behavior change ──

def test_prompt_logging_still_default_off():
    from core.config import settings
    assert settings.LLM_SHADOW_LOG_PROMPTS is False


def test_redact_is_pure():
    """AST: _redact must not call any network method."""
    import ast
    import inspect
    from intelligence import llm_shadow as L

    src = inspect.getsource(L._redact)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            assert name not in {"get", "post", "urlopen", "request"}
