"""
Phase I6-H1 — Provider honesty semantics for earnings/insiders intelligence.

Fake-money simulation only. No broker. No live trading. No real orders.
No AI/LLM/Ollama. Verifies that misconfigured/unwired providers report
honest status fields instead of misleading enabled=true.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset_earnings_cache():
    from intelligence import earnings as e
    e._cache = None
    e._cache_time = None


def _reset_insiders_cache():
    from intelligence import insiders as ins
    ins._cache = None
    ins._cache_time = None


# ── Earnings: provider=none → not_configured ──────────────────────────────────

def test_earnings_provider_none_reports_not_configured():
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings_cache()
    with patch.object(settings, "EARNINGS_DATA_PROVIDER", "none"):
        assert e.provider_status() == "not_configured"
        assert e.is_available() is False
        snap = __import__("asyncio").run(e.fetch_and_refresh(force=True))
    assert snap["enabled"] is False
    assert snap["available"] is False
    assert snap["provider_status"] == "not_configured"
    assert snap["results"] == []
    assert "not configured" in (snap.get("warning") or "").lower()


# ── Earnings: provider=finnhub but no fetcher → configured_but_unwired ────────

def test_earnings_provider_polygon_unwired_reports_configured_but_unwired_with_warning():
    # NOTE: as of Phase I6-H2 finnhub is a wired provider, so the
    # "configured-but-unwired" semantics are exercised with polygon, which
    # remains unwired.
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings_cache()
    with patch.object(settings, "EARNINGS_DATA_PROVIDER", "polygon"):
        assert e.provider_status() == "configured_but_unwired"
        assert e.is_available() is False
        snap = __import__("asyncio").run(e.fetch_and_refresh(force=True))
    assert snap["enabled"] is False
    assert snap["available"] is False
    assert snap["provider_status"] == "configured_but_unwired"
    assert snap["results"] == []
    assert "configured" in (snap.get("warning") or "").lower()
    assert "fetcher" in (snap.get("warning") or "").lower()


def test_earnings_provider_polygon_unwired_reports_configured_but_unwired():
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings_cache()
    with patch.object(settings, "EARNINGS_DATA_PROVIDER", "polygon"):
        assert e.provider_status() == "configured_but_unwired"
        assert e.is_available() is False
        snap = __import__("asyncio").run(e.fetch_and_refresh(force=True))
    assert snap["available"] is False
    assert snap["provider_status"] == "configured_but_unwired"
    assert snap["results"] == []


# ── Insiders: same matrix ─────────────────────────────────────────────────────

def test_insiders_provider_none_reports_not_configured():
    from core.config import settings
    from intelligence import insiders as ins

    _reset_insiders_cache()
    with patch.object(settings, "INSIDER_DATA_PROVIDER", "none"):
        assert ins.provider_status() == "not_configured"
        assert ins.is_available() is False
        snap = __import__("asyncio").run(ins.fetch_and_refresh(force=True))
    assert snap["enabled"] is False
    assert snap["available"] is False
    assert snap["provider_status"] == "not_configured"
    assert snap["results"] == []
    assert "not configured" in (snap.get("warning") or "").lower()


def test_insiders_provider_polygon_unwired_reports_configured_but_unwired_with_warning():
    # NOTE: as of Phase I6-H2 finnhub is a wired provider, so the
    # "configured-but-unwired" semantics are exercised with polygon.
    from core.config import settings
    from intelligence import insiders as ins

    _reset_insiders_cache()
    with patch.object(settings, "INSIDER_DATA_PROVIDER", "polygon"):
        assert ins.provider_status() == "configured_but_unwired"
        assert ins.is_available() is False
        snap = __import__("asyncio").run(ins.fetch_and_refresh(force=True))
    assert snap["enabled"] is False
    assert snap["available"] is False
    assert snap["provider_status"] == "configured_but_unwired"
    assert snap["results"] == []


def test_insiders_provider_polygon_unwired_reports_configured_but_unwired():
    from core.config import settings
    from intelligence import insiders as ins

    _reset_insiders_cache()
    with patch.object(settings, "INSIDER_DATA_PROVIDER", "polygon"):
        snap = __import__("asyncio").run(ins.fetch_and_refresh(force=True))
    assert snap["available"] is False
    assert snap["provider_status"] == "configured_but_unwired"
    assert snap["results"] == []


# ── No external HTTP calls are made by unwired provider stubs ─────────────────

def test_earnings_unwired_provider_does_not_make_http_calls():
    """The configured_but_unwired branch must not invoke any httpx HTTP client."""
    import asyncio
    import httpx
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings_cache()
    # polygon stays unwired in Phase I6-H2.
    with patch.object(settings, "EARNINGS_DATA_PROVIDER", "polygon"), \
         patch.object(httpx.AsyncClient, "get", side_effect=AssertionError("no http call expected")), \
         patch.object(httpx.AsyncClient, "post", side_effect=AssertionError("no http call expected")):
        snap = asyncio.run(e.fetch_and_refresh(force=True))
    assert snap["provider_status"] == "configured_but_unwired"
    assert snap["results"] == []


def test_insiders_unwired_provider_does_not_make_http_calls():
    import asyncio
    import httpx
    from core.config import settings
    from intelligence import insiders as ins

    _reset_insiders_cache()
    with patch.object(settings, "INSIDER_DATA_PROVIDER", "polygon"), \
         patch.object(httpx.AsyncClient, "get", side_effect=AssertionError("no http call expected")), \
         patch.object(httpx.AsyncClient, "post", side_effect=AssertionError("no http call expected")):
        snap = asyncio.run(ins.fetch_and_refresh(force=True))
    assert snap["provider_status"] == "configured_but_unwired"
    assert snap["results"] == []


# ── Scoring path: adjustments still zero when providers are inactive ──────────

def test_earnings_scoring_zero_when_no_provider():
    from core.config import settings
    from intelligence.earnings import score_earnings_proximity

    info = score_earnings_proximity("NVDA", {})
    assert info["earnings_score_adjustment"] == 0
    assert info["earnings_blocked"] is False
    assert info["enabled"] is settings.PAPER_EARNINGS_SCORING_ENABLED


def test_insider_scoring_zero_when_no_provider():
    from core.config import settings
    from intelligence.insiders import score_insiders

    info = score_insiders("NVDA", {})
    assert info["insider_score_adjustment"] == 0
    assert info["insider_recent_buy_count"] == 0
    assert info["enabled"] is settings.PAPER_INSIDER_SCORING_ENABLED
