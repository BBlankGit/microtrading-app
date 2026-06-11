"""
Phase L1-H1 — LLM packet completeness + dashboard label clarity.

Fake-money simulation only. No broker, no live trading, no real orders.
No real LLM calls. Verifies:
  - build_candidate_packet honors the new `quality` parameter and surfaces
    bid/ask/sizes/last_trade_price/day_volume/prev_day_volume directly
  - cache-metadata fields (marketdata_fetched_at, marketdata_fallback_used,
    sanitized marketdata_error) are present
  - news_available flag + news_unavailable_reason render correctly
  - rule_impact_level is bucketed from materiality_score even when the
    raw catalyst row was not normalized by I5-H2
  - get_cached_intraday_history is a pure helper (no httpx import); returns
    None today and the packet exposes a clear unavailable_reason
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest


def _q(**kwargs):
    """Tiny quality builder."""
    base = {
        "symbol": "AAPL",
        "last_trade_price": 150.05,
        "bid": 149.99,
        "ask": 150.11,
        "bid_size": 300,
        "ask_size": 200,
        "spread": 0.12,
        "spread_percent": 0.08,
        "day_volume": 12_345_678,
        "previous_day_volume": 10_000_000,
        "volume_ratio": 1.23,
        "change_percent": 1.75,
        "tradable": True,
        "rejection_reasons": [],
    }
    base.update(kwargs)
    return base


def _c(**kwargs):
    """Tiny candidate builder."""
    base = {
        "symbol": "AAPL",
        "eligible": True,
        "total_score": 75,
        "spread_percent": 0.08,
        "change_percent": 1.75,
        "volume_ratio": 1.23,
        "marketdata_stale": False,
        "marketdata_fetched_at": "2026-06-11T12:00:00+00:00",
        "marketdata_age_seconds": 5,
        "marketdata_source": "cache",
        "marketdata_fallback_used": False,
        "marketdata_error": None,
        "day_open": 149.0,
        "day_high": 151.5,
        "day_low": 148.8,
        "previous_close": 148.5,
        "dollar_volume": 1.85e9,
        "vwap": 150.2,
        "time_adjusted_volume_ratio": 1.42,
    }
    base.update(kwargs)
    return base


# ── A. Marketdata + cache metadata coverage ─────────────────────────────────

def test_packet_marketdata_pulls_bid_ask_sizes_from_quality():
    from intelligence.llm_shadow import build_candidate_packet

    pkt = build_candidate_packet(_c(), quality=_q())
    md = pkt["marketdata"]
    assert md["last_trade_price"] == 150.05
    assert md["last_price"] == 150.05  # alias
    assert md["bid"] == 149.99
    assert md["ask"] == 150.11
    assert md["bid_size"] == 300
    assert md["ask_size"] == 200
    assert md["day_volume"] == 12_345_678
    assert md["previous_day_volume"] == 10_000_000
    assert md["volume_ratio"] == 1.23
    assert md["spread"] == 0.12
    assert md["spread_percent"] == 0.08
    assert md["change_percent"] == 1.75
    assert md["tradable"] is True


def test_packet_marketdata_falls_back_to_candidate_when_quality_omitted():
    from intelligence.llm_shadow import build_candidate_packet

    cand = _c(
        # Mirror quality fields directly onto candidate (no `quality=` arg)
        bid=10.0, ask=10.1, last_trade_price=10.05,
        bid_size=100, ask_size=200, day_volume=42,
        prev_day_volume=99, volume_ratio=1.5, quality_tradable=True,
    )
    pkt = build_candidate_packet(cand)
    md = pkt["marketdata"]
    assert md["bid"] == 10.0
    assert md["ask"] == 10.1
    assert md["last_trade_price"] == 10.05
    assert md["bid_size"] == 100
    assert md["ask_size"] == 200
    assert md["day_volume"] == 42
    assert md["previous_day_volume"] == 99
    assert md["volume_ratio"] == 1.5
    assert md["tradable"] is True


def test_packet_marketdata_includes_full_cache_metadata():
    from intelligence.llm_shadow import build_candidate_packet

    pkt = build_candidate_packet(_c(
        marketdata_fetched_at="2026-06-11T11:59:55+00:00",
        marketdata_age_seconds=12,
        marketdata_source="polygon",
        marketdata_fallback_used=True,
        marketdata_stale=False,
        marketdata_error=None,
    ))
    md = pkt["marketdata"]
    assert md["marketdata_fetched_at"] == "2026-06-11T11:59:55+00:00"
    assert md["marketdata_age_seconds"] == 12
    assert md["marketdata_source"] == "polygon"
    assert md["marketdata_fallback_used"] is True
    assert md["marketdata_stale"] is False
    assert md["marketdata_missing"] is False
    assert md["marketdata_error"] is None


def test_packet_marketdata_error_is_sanitized():
    from intelligence.llm_shadow import build_candidate_packet

    # Inject a fake error string containing a key-like substring.
    pkt = build_candidate_packet(_c(
        marketdata_error="polygon http 403 with token sk-VERYSECRET1234567890",
    ))
    md = pkt["marketdata"]
    assert md["marketdata_missing"] is True
    err = md["marketdata_error"] or ""
    assert "sk-VERYSECRET" not in err
    assert "<redacted>" in err


# ── B. Intraday helper / packet section ─────────────────────────────────────

def test_get_cached_intraday_history_returns_none_today():
    from intelligence.llm_shadow import get_cached_intraday_history
    assert get_cached_intraday_history("AAPL", 20) is None


def test_intraday_section_unavailable_when_no_cache():
    from intelligence.llm_shadow import build_candidate_packet

    pkt = build_candidate_packet(_c())
    intra = pkt["intraday"]
    assert intra["intraday_history_available"] is False
    assert intra["recent_price_points"] == []
    assert "intraday_unavailable_reason" in intra


def test_intraday_helper_module_does_not_import_httpx_or_polygon():
    """The helper must not pull in external HTTP clients."""
    # The llm_shadow module imports httpx itself (for the OpenAI call), but the
    # intraday helper specifically must not trigger any data-fetch import. We
    # AST-inspect the helper to ensure its body contains no Calls — pure
    # placeholder returning None.
    import intelligence.llm_shadow as L
    src = inspect.getsource(L.get_cached_intraday_history)
    tree = ast.parse(src)
    # Count Call nodes in the function body
    func = tree.body[0]
    calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
    assert len(calls) == 0, "get_cached_intraday_history must not make any calls"


# ── C. News section availability flag ───────────────────────────────────────

def test_news_section_has_items_when_provided():
    from intelligence.llm_shadow import build_candidate_packet

    raw_news = [{
        "title": "Beat earnings",
        "publisher": "Reuters",
        "published_utc": "2026-06-11T10:00:00Z",
        "article_url": "https://example.com/a",
        "classified_event_type": "earnings",
        "sentiment": "bullish",
        "materiality_score": 0.85,
        "sentiment_score": 0.7,
        "bullish_flags": ["beat"],
        "bearish_flags": [],
        "sentiment_reasons": ["strong beat"],
    }]
    pkt = build_candidate_packet(_c(), news_items_by_symbol={"AAPL": raw_news})
    nsec = pkt["news"]
    assert nsec["news_available"] is True
    assert len(nsec["items"]) == 1
    item = nsec["items"][0]
    assert item["title"] == "Beat earnings"
    assert item["rule_event_type"] == "earnings"
    # Materiality bucketed to "high" because materiality >= 0.7
    assert item["rule_impact_level"] == "high"
    assert item["rule_sentiment"] == "bullish"
    assert item["rule_materiality_score"] == 0.85
    assert item["rule_bullish_flags"] == ["beat"]
    assert item["rule_explanation"] == "strong beat"


def test_news_section_unavailable_when_symbol_has_no_rows():
    from intelligence.llm_shadow import build_candidate_packet

    pkt = build_candidate_packet(_c(), news_items_by_symbol={"AAPL": []})
    nsec = pkt["news"]
    assert nsec["news_available"] is False
    assert nsec["news_unavailable_reason"] == "no cached news items for symbol"
    assert nsec["items"] == []


def test_news_section_unavailable_when_lookup_omitted():
    from intelligence.llm_shadow import build_candidate_packet

    pkt = build_candidate_packet(_c())  # no news_items_by_symbol
    nsec = pkt["news"]
    assert nsec["news_available"] is False
    assert nsec["news_unavailable_reason"] == "news lookup not provided to packet builder"


def test_news_bucketing_medium_low_unknown():
    from intelligence.llm_shadow import _bucket_impact_level

    assert _bucket_impact_level(0.85) == "high"
    assert _bucket_impact_level(0.5) == "medium"
    assert _bucket_impact_level(0.1) == "low"
    assert _bucket_impact_level(None) == "unknown"
    assert _bucket_impact_level("not a number") == "unknown"


def test_news_cap_applied_when_news_section_provided():
    from core.config import settings
    from intelligence.llm_shadow import build_candidate_packet
    from unittest.mock import patch

    raw = [{"title": f"n{i}", "classified_event_type": "news"} for i in range(20)]
    with patch.object(settings, "LLM_SHADOW_MAX_NEWS_ITEMS_PER_SYMBOL", 3):
        pkt = build_candidate_packet(_c(), news_items_by_symbol={"AAPL": raw})
    nsec = pkt["news"]
    assert nsec["news_available"] is True
    assert len(nsec["items"]) == 3


# ── D. Simulator wiring (AST checks) ─────────────────────────────────────────

def test_simulator_passes_quality_into_build_candidate_packet():
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
    # The build_candidate_packet call in section 4c must pass quality=… and
    # news_items_by_symbol=_llm_news_by_sym.
    assert "build_candidate_packet" in src
    assert "quality=quality_map.get" in src
    assert "news_items_by_symbol=_llm_news_by_sym" in src


def test_simulator_does_not_pass_none_news_to_packet_anymore():
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
    # The pre-L1-H1 call had news_items_by_symbol=None; that must be gone.
    assert "news_items_by_symbol=None" not in src


# ── E. Defensive: marketdata_error redaction is real ───────────────────────

def test_redact_used_for_marketdata_error():
    from intelligence.llm_shadow import _redact

    assert "sk-SECRETKEY1234567890ABCDEF" not in _redact(
        "got sk-SECRETKEY1234567890ABCDEF"
    )
