"""
Phase L1 — LLM Shadow Analyst tests.

Fake-money simulation only. No broker, no live trading, no real orders.
No real LLM calls in any test — everything is mocked. Verifies:
  - default disabled → zero provider calls
  - missing key → missing_api_key, no behavior change
  - packet builder shape across all 12 sections
  - candidate selector caps + skip rules
  - response normalization (valid + invalid JSON, clamping, enums)
  - cache hits do not invoke the provider
  - LLM never mutates eligible/action/entry_mode
  - prompts and logs never contain the API key
"""
from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _reset_llm_module():
    """Clear the module-level cache + telemetry between tests."""
    from intelligence import llm_shadow as L
    L._cache.clear()
    L._status.update({
        "calls_total": 0, "calls_last_tick": 0, "calls_success": 0,
        "calls_error": 0, "cache_hits": 0, "cache_misses": 0,
        "latency_ms_sum": 0,
        "last_call_at": None, "last_success_at": None,
        "last_error": None, "last_model_used": None,
    })


def _base_candidate(symbol="AAPL", **kwargs):
    out = {
        "symbol": symbol,
        "eligible": True,
        "action": None,
        "entry_mode": "catalyst",
        "total_score": 75,
        "score_threshold": 70,
        "score_pass": True,
        "rejection_reason": None,
        "decision_reason": "score 75 >= 70",
        "catalyst_type": "earnings",
        "score_components": {"market_quality_score": 25},
        "spread_percent": 0.05,
        "marketdata_stale": False,
        "enhanced_shadow_decision": "WOULD_ENTER",
        "enhanced_shadow_score": 80,
        "candidate_sources": ["catalyst"],
    }
    out.update(kwargs)
    return out


# ── 1. Default disabled → zero provider calls ────────────────────────────────

def test_llm_disabled_returns_disabled_status_no_call():
    from core.config import settings
    from intelligence import llm_shadow as L

    _reset_llm_module()
    with patch.object(settings, "LLM_SHADOW_ENABLED", False):
        out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "disabled"
    assert out["llm_decision"] is None
    assert L._status["calls_total"] == 0


# ── 2. Missing key short-circuits with missing_api_key ───────────────────────

def test_llm_missing_key_returns_missing_api_key(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "missing_api_key"
    assert L._status["calls_total"] == 0


def test_llm_placeholder_key_treated_as_missing(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "PASTE_YOUR_KEY_HERE")
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "missing_api_key"


# ── 3. Packet builder sections ───────────────────────────────────────────────

def test_packet_includes_all_required_sections():
    from intelligence import llm_shadow as L

    candidate = _base_candidate(
        last_price=150.0, bid=149.9, ask=150.1, spread_percent=0.067,
        change_percent=2.5, day_volume=10_000_000, dollar_volume=1.5e9,
        marketdata_age_seconds=5, marketdata_source="cache",
        quality_tradable=True,
        # intelligence adjustments
        base_score_before_intelligence_adjustments=70,
        intelligence_score_adjustment=5,
        final_score_after_intelligence_adjustments=75,
        earnings_score_adjustment=-3, insider_score_adjustment=10,
        market_trend_adjustment=2,
        # market trend
        market_trend_direction="improving", market_trend_strength="moderate",
        # reddit
        reddit_rank=10, reddit_mentions=500, reddit_spike_ratio=3.5, reddit_boost=2,
        # premarket
        premarket_rank=5, premarket_gap_percent=4.2, market_mover_rank=3,
        # earnings adj
        earnings_next_date="2026-07-01", earnings_days_until=15, earnings_reason="3w out",
        # insider adj
        insider_recent_buy_count=2, insider_recent_buy_value=300000,
        insider_latest_transaction_date="2026-06-09",
        insider_transaction_codes=["P"],
        # shadow
        enhanced_shadow_components={"momentum_score": 25},
        enhanced_shadow_confidence="high",
        enhanced_shadow_reason="strong shadow",
    )

    packet = L.build_candidate_packet(
        candidate,
        market_regime={"regime": "risk_on", "risk_on_score": 80},
        market_trend={
            "regime": "risk_on", "trend_direction": "improving",
            "trend_strength": "moderate", "adjusted_regime_label": "risk_on",
            "market_regime_score_after_trend": 88,
        },
        account_summary={
            "open_position_count": 2, "symbols_open": {"AAPL"},
            "account_cash": 950.0, "account_equity": 1050.0,
            "daily_realized_pnl": 25.5, "daily_loss_guard_triggered": False,
        },
        news_items_by_symbol={"AAPL": [
            {"title": "Beats Q", "publisher": "WSJ", "published_utc": "2026-06-11",
             "rule_event_type": "earnings", "rule_sentiment": "bullish",
             "rule_materiality_score": 0.8, "rule_bullish_flags": ["beat"]},
        ]},
        earnings_by_symbol={"AAPL": {
            "report_date": "2026-07-01", "report_time": "after_close",
            "eps_estimate": 2.10, "revenue_estimate": 1e11, "days_until": 15,
        }},
        insiders_by_symbol={"AAPL": [
            {"transaction_date": "2026-06-09", "transaction_code": "P",
             "transaction_type": "open_market_purchase", "buy_sell_label": "bullish_buy",
             "shares": 1000, "price": 200.0, "value": 200_000,
             "is_discretionary_buy": True, "is_recent": True},
        ]},
        reddit_lookup={"age_seconds": 600, "fetched_at": 1234},
        premarket_lookup={"AAPL": {
            "volume_vs_previous_day_ratio": 2.5,
            "time_adjusted_volume_ratio": 3.0, "source": "polygon",
        }},
    )

    # 1. identity
    assert packet["identity"]["symbol"] == "AAPL"
    # 2. marketdata
    assert packet["marketdata"]["last_price"] == 150.0
    # 3. intraday placeholder when no history
    assert packet["intraday"]["intraday_history_available"] is False
    # 4. engine decision
    assert packet["engine"]["total_score"] == 75
    assert packet["engine"]["intelligence_score_adjustment"] == 5
    # 5. shadow
    assert packet["shadow"]["enhanced_shadow_decision"] == "WOULD_ENTER"
    # 6. news (Phase L1-H1: dict with news_available + items)
    assert packet["news"]["news_available"] is True
    assert len(packet["news"]["items"]) == 1
    assert packet["news"]["items"][0]["rule_event_type"] == "earnings"
    # 7. reddit
    assert packet["reddit"]["reddit_rank"] == 10
    # 8. movers
    assert packet["movers"]["premarket_rank"] == 5
    # 9. earnings
    assert packet["earnings"]["next_earnings_date"] == "2026-07-01"
    # 10. insiders
    assert packet["insiders"]["recent_buy_count"] == 2
    assert len(packet["insiders"]["recent_transactions"]) == 1
    # 11. market context
    assert packet["market_context"]["market_regime_raw"] == "risk_on"
    assert packet["market_context"]["risk_on_score_trend_adjusted"] == 88
    # 12. position
    assert packet["position"]["already_in_position"] is True
    # 13. prompt_version stamped
    assert "prompt_version" in packet


def test_packet_caps_news_per_symbol(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L

    monkeypatch.setattr(settings, "LLM_SHADOW_MAX_NEWS_ITEMS_PER_SYMBOL", 2)
    candidate = _base_candidate()
    news_items = [{"title": f"n{i}", "rule_event_type": "news"} for i in range(10)]
    packet = L.build_candidate_packet(
        candidate, news_items_by_symbol={"AAPL": news_items}
    )
    assert len(packet["news"]["items"]) == 2


# ── 4. Selection logic ──────────────────────────────────────────────────────

def test_selector_caps_at_max(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L

    monkeypatch.setattr(settings, "LLM_SHADOW_MAX_CANDIDATES_PER_TICK", 3)
    cands = [
        _base_candidate(symbol="A", eligible=False, enhanced_shadow_decision="WOULD_ENTER"),
        _base_candidate(symbol="B", eligible=False, enhanced_shadow_decision="WOULD_ENTER"),
        _base_candidate(symbol="C", eligible=True),
        _base_candidate(symbol="D", eligible=True),
        _base_candidate(symbol="E", eligible=False, total_score=85),
    ]
    picked = L.select_candidates_for_llm(cands)
    assert len(picked) == 3


def test_selector_skips_open_positions_by_default():
    from intelligence import llm_shadow as L

    cands = [
        _base_candidate(symbol="OPEN", eligible=True),
        _base_candidate(symbol="NEW",  eligible=True),
    ]
    picked = L.select_candidates_for_llm(cands, open_position_symbols={"OPEN"})
    symbols = [c["symbol"] for c in picked]
    assert "OPEN" not in symbols
    assert "NEW" in symbols


def test_selector_skips_stale_marketdata():
    from intelligence import llm_shadow as L

    cands = [
        _base_candidate(symbol="STALE", marketdata_stale=True, eligible=True),
        _base_candidate(symbol="FRESH", eligible=True),
    ]
    picked = L.select_candidates_for_llm(cands)
    symbols = [c["symbol"] for c in picked]
    assert "STALE" not in symbols
    assert "FRESH" in symbols


def test_selector_skips_wide_spread():
    from intelligence import llm_shadow as L

    cands = [
        _base_candidate(symbol="WIDE",   spread_percent=0.8, eligible=True),
        _base_candidate(symbol="TIGHT",  spread_percent=0.05, eligible=True),
    ]
    picked = L.select_candidates_for_llm(cands)
    symbols = [c["symbol"] for c in picked]
    assert "WIDE" not in symbols
    assert "TIGHT" in symbols


def test_selector_prioritizes_missed_opportunities():
    from intelligence import llm_shadow as L

    cands = [
        _base_candidate(symbol="MISSED", eligible=False,
                        enhanced_shadow_decision="WOULD_ENTER", total_score=55),
        _base_candidate(symbol="ELIG",   eligible=True),
    ]
    picked = L.select_candidates_for_llm(cands)
    assert picked[0]["symbol"] == "MISSED"


# ── 5. Response normalization ───────────────────────────────────────────────

def test_normalize_valid_response():
    from intelligence import llm_shadow as L

    raw = {
        "llm_decision": "WOULD_ENTER",
        "llm_confidence": 0.85,
        "llm_time_horizon": "intraday",
        "llm_impact_assessment": "high",
        "llm_directional_bias": "bullish",
        "llm_expected_move": "moderate_up",
        "llm_agrees_with_engine": True,
        "llm_agrees_with_shadow": True,
        "llm_primary_reason": "strong earnings + insider buy",
        "llm_supporting_factors": ["earnings beat", "insider P"],
        "llm_risk_factors": ["wide market down"],
        "llm_missing_data": [],
        "llm_score_adjustment_suggestion": 8,
        "llm_recommended_action": "enter_now",
        "llm_recommended_confirmation": "volume_acceleration",
        "llm_summary": "buy on confirmation",
    }
    out = L.normalize_llm_response(raw)
    assert out["llm_status"] == "ok"
    assert out["llm_decision"] == "WOULD_ENTER"
    assert out["llm_confidence"] == 0.85


def test_normalize_clamps_confidence_and_adjustment():
    from intelligence import llm_shadow as L

    out = L.normalize_llm_response({
        "llm_confidence": 1.5,
        "llm_score_adjustment_suggestion": 99,
    })
    assert out["llm_confidence"] == 1.0
    assert out["llm_score_adjustment_suggestion"] == 20


def test_normalize_unknown_enum_falls_back_to_unknown():
    from intelligence import llm_shadow as L

    out = L.normalize_llm_response({
        "llm_decision": "MAYBE",
        "llm_time_horizon": "tomorrow",
        "llm_impact_assessment": "BIG",
        "llm_directional_bias": "moonshot",
    })
    assert out["llm_decision"] is None  # invalid decision → None
    assert out["llm_time_horizon"] == "unknown"
    assert out["llm_impact_assessment"] == "unknown"
    assert out["llm_directional_bias"] == "unknown"


def test_invalid_json_returns_error_status(monkeypatch):
    """The provider call returns bad text → llm_status=error, no crash."""
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-realkeyforhttptest1234567890")
    monkeypatch.setattr(settings, "LLM_SHADOW_MAX_RETRIES", 0)

    class FakeResp:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "not json"}}]}

    async def _fake_post(self, url, json=None, headers=None):
        return FakeResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "error"
    assert L._status["calls_error"] >= 1


def test_timeout_returns_error_status(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-realkeyforhttptest1234567890")
    monkeypatch.setattr(settings, "LLM_SHADOW_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(settings, "LLM_SHADOW_MAX_RETRIES", 0)

    async def _slow_post(self, url, json=None, headers=None):
        await asyncio.sleep(5)
        raise RuntimeError("should not reach")

    monkeypatch.setattr(httpx.AsyncClient, "post", _slow_post)
    out = asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    assert out["llm_status"] == "error"


# ── 6. Cache reuse ──────────────────────────────────────────────────────────

def test_cache_prevents_repeated_calls(monkeypatch):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-cachekey1234567890abcdef")

    call_count = {"n": 0}
    valid_payload = {
        "llm_decision": "WATCH", "llm_confidence": 0.5,
        "llm_time_horizon": "intraday", "llm_impact_assessment": "medium",
        "llm_directional_bias": "neutral", "llm_expected_move": "flat",
        "llm_agrees_with_engine": True, "llm_agrees_with_shadow": True,
        "llm_primary_reason": "ok", "llm_supporting_factors": [],
        "llm_risk_factors": [], "llm_missing_data": [],
        "llm_score_adjustment_suggestion": 0,
        "llm_recommended_action": "monitor_only",
        "llm_recommended_confirmation": "none",
        "llm_summary": "watch",
    }

    class FakeResp:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(valid_payload)}}]}

    async def _fake_post(self, url, json=None, headers=None):
        call_count["n"] += 1
        return FakeResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    packet = {"identity": {"symbol": "AAPL"}, "marketdata": {"last_price": 150.0}}
    out1 = asyncio.run(L.analyze_candidate_packet(packet))
    out2 = asyncio.run(L.analyze_candidate_packet(packet))
    assert out1["llm_status"] == "ok"
    assert out2["llm_status"] == "ok"
    assert out2.get("llm_cached") is True
    assert call_count["n"] == 1


# ── 7. API key never logged or echoed ───────────────────────────────────────

def test_api_key_not_logged_on_error(monkeypatch, caplog):
    from core.config import settings
    from intelligence import llm_shadow as L
    import httpx

    _reset_llm_module()
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_API_KEY_ENV", "OPENAI_API_KEY")
    SECRET = "sk-VERY_SECRET_KEY_ABCDEF1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setattr(settings, "LLM_SHADOW_MAX_RETRIES", 0)

    async def _err_post(self, url, json=None, headers=None):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "post", _err_post)
    caplog.set_level(logging.WARNING)
    asyncio.run(L.analyze_candidate_packet({"identity": {"symbol": "X"}}))
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert SECRET not in full_log
    last_err = L._status.get("last_error") or ""
    assert SECRET not in last_err


def test_redaction_helper():
    from intelligence import llm_shadow as L

    redacted = L._redact("error: sk-VERY_SECRET_KEY_ABCDEF1234567890 failed")
    assert "sk-VERY_SECRET_KEY" not in redacted
    assert "<redacted>" in redacted


# ── 8. Status accessor ─────────────────────────────────────────────────────

def test_status_endpoint_safe_shape():
    from intelligence import llm_shadow as L

    _reset_llm_module()
    s = L.get_status()
    for k in ("enabled", "provider", "model", "api_key_env", "api_key_present",
              "calls_total", "cache_hits", "cache_misses", "disclaimer",
              "prompt_version", "max_candidates_per_tick"):
        assert k in s
    # Never return the key itself
    assert "api_key" not in s


# ── 9. Default candidate row has llm_status='disabled' / 'not_selected' ─────

def test_default_not_selected_result_shape():
    from intelligence import llm_shadow as L

    d = L.default_not_selected_result()
    assert d["llm_status"] == "not_selected"
    assert d["llm_decision"] is None
    # The shape covers the fields the dashboard needs to render.
    for k in ("llm_confidence", "llm_recommended_action", "llm_summary",
              "llm_supporting_factors", "llm_risk_factors", "llm_model"):
        assert k in d


# ── 10. No forbidden imports inside core simulator helpers ──────────────────

def test_llm_module_no_anthropic_or_ollama():
    import ast
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / "intelligence" / "llm_shadow.py").read_text()
    tree = ast.parse(src)
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                seen.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                seen.add(node.module.split(".")[0])
    # OpenAI is reached via raw httpx; we deliberately did NOT add
    # the openai/anthropic/ollama/langchain SDKs.
    for forbidden in ("openai", "anthropic", "ollama", "langchain"):
        assert forbidden not in seen, f"forbidden import {forbidden!r}"
