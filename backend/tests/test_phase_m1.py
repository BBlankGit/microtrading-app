"""
Phase M1 — Market Regime Trend Momentum (ETF proxies only).

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM. Verifies the rolling history, delta computation, classification,
and the trend adjustment flowing into entry-path scoring.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


def _snap(risk_on_score, qqq, spy=None, iwm=None, as_of="2026-06-11T10:00:00+00:00"):
    """Helper: build a regime_data-shaped dict for record_snapshot."""
    return {
        "as_of": as_of,
        "risk": {"risk_on_score": risk_on_score, "regime": "neutral", "confidence": "high"},
        "breadth": {"positive_percent": 50.0},
        "leaders": {
            "data": {
                "QQQ": {"change_percent": qqq, "last_trade_price": None} if qqq is not None else None,
                "SPY": {"change_percent": spy, "last_trade_price": None} if spy is not None else None,
                "IWM": {"change_percent": iwm, "last_trade_price": None} if iwm is not None else None,
            },
            "bullish_count": 0,
            "bearish_count": 0,
        },
    }


def _reset_trend():
    from market import trend
    trend.clear()


# ── 1. record_snapshot: respects interval ────────────────────────────────────

def test_record_snapshot_respects_interval():
    from core.config import settings
    from market import trend

    _reset_trend()
    with patch.object(settings, "MARKET_TREND_SNAPSHOT_INTERVAL_SECONDS", 60), \
         patch.object(settings, "MARKET_TREND_ENABLED", True):
        assert trend.record_snapshot(_snap(50, 0.5)) is True
        # Immediate second call should be skipped — still inside the interval.
        assert trend.record_snapshot(_snap(60, 0.6)) is False
        assert len(trend._history) == 1


# ── 2. record_snapshot honors disabled flag ──────────────────────────────────

def test_record_snapshot_disabled_does_nothing():
    from core.config import settings
    from market import trend

    _reset_trend()
    with patch.object(settings, "MARKET_TREND_ENABLED", False):
        assert trend.record_snapshot(_snap(50, 0.5)) is False
        assert len(trend._history) == 0


# ── 3. _prune drops old snapshots ────────────────────────────────────────────

def test_prune_drops_old_snapshots():
    from core.config import settings
    from market import trend

    _reset_trend()
    with patch.object(settings, "MARKET_TREND_HISTORY_MINUTES", 30):
        now = time.monotonic()
        # Two snapshots manually injected with crafted timestamps.
        trend._history.append({
            "timestamp_monotonic": now - 31 * 60,
            "as_of": "old", "risk_on_score": 10, "regime": "x", "confidence": "x",
            "breadth_positive_percent": 0, "leader_count": 0,
            "primary_change": {}, "primary_price": {},
        })
        trend._history.append({
            "timestamp_monotonic": now - 5 * 60,
            "as_of": "recent", "risk_on_score": 50, "regime": "x", "confidence": "x",
            "breadth_positive_percent": 0, "leader_count": 0,
            "primary_change": {}, "primary_price": {},
        })
        trend._prune()
        assert len(trend._history) == 1
        assert trend._history[0]["as_of"] == "recent"


# ── 4–7. Trend classification ────────────────────────────────────────────────

def _inject(snapshots: list[tuple[float, dict]]):
    """Manually inject snapshots with relative ages (seconds in the past)."""
    from market import trend
    _reset_trend()
    now = time.monotonic()
    for age_s, snap in snapshots:
        snap["timestamp_monotonic"] = now - age_s
        trend._history.append(snap)


def test_classify_strong_improving():
    from core.config import settings
    from market import trend

    with patch.object(settings, "MARKET_TREND_MIN_SNAPSHOTS", 2):
        _inject([
            (10 * 60, {"as_of": "t-10", "risk_on_score": 40, "regime": "x", "confidence": "x",
                       "breadth_positive_percent": 0, "leader_count": 0,
                       "primary_change": {"QQQ": 0.0, "SPY": 0.0, "IWM": 0.0}, "primary_price": {}}),
            (0, {"as_of": "now", "risk_on_score": 60, "regime": "x", "confidence": "x",
                 "breadth_positive_percent": 0, "leader_count": 0,
                 "primary_change": {"QQQ": 0.5, "SPY": 0.5, "IWM": 0.5}, "primary_price": {}}),
        ])
        t = trend.get_trend()
    assert t["trend_direction"] == "improving"
    assert t["trend_strength"] == "strong"
    assert t["market_trend_adjustment"] == 8


def test_classify_strong_deteriorating():
    from core.config import settings
    from market import trend

    with patch.object(settings, "MARKET_TREND_MIN_SNAPSHOTS", 2):
        _inject([
            (10 * 60, {"as_of": "t-10", "risk_on_score": 80, "regime": "x", "confidence": "x",
                       "breadth_positive_percent": 0, "leader_count": 0,
                       "primary_change": {"QQQ": 0.5, "SPY": 0.5, "IWM": 0.5}, "primary_price": {}}),
            (0, {"as_of": "now", "risk_on_score": 60, "regime": "x", "confidence": "x",
                 "breadth_positive_percent": 0, "leader_count": 0,
                 "primary_change": {"QQQ": 0.0, "SPY": 0.0, "IWM": 0.0}, "primary_price": {}}),
        ])
        t = trend.get_trend()
    assert t["trend_direction"] == "deteriorating"
    assert t["trend_strength"] == "strong"
    assert t["market_trend_adjustment"] == -10


def test_classify_flat():
    from core.config import settings
    from market import trend

    with patch.object(settings, "MARKET_TREND_MIN_SNAPSHOTS", 2):
        _inject([
            (10 * 60, {"as_of": "t-10", "risk_on_score": 50, "regime": "x", "confidence": "x",
                       "breadth_positive_percent": 0, "leader_count": 0,
                       "primary_change": {"QQQ": 0.0, "SPY": 0.0, "IWM": 0.0}, "primary_price": {}}),
            (0, {"as_of": "now", "risk_on_score": 50, "regime": "x", "confidence": "x",
                 "breadth_positive_percent": 0, "leader_count": 0,
                 "primary_change": {"QQQ": 0.0, "SPY": 0.0, "IWM": 0.0}, "primary_price": {}}),
        ])
        t = trend.get_trend()
    assert t["trend_direction"] == "flat"
    assert t["market_trend_adjustment"] == 0


def test_insufficient_snapshots_returns_unknown():
    from core.config import settings
    from market import trend

    _reset_trend()
    with patch.object(settings, "MARKET_TREND_MIN_SNAPSHOTS", 5):
        # Only inject 1 snapshot
        _inject([
            (0, {"as_of": "now", "risk_on_score": 50, "regime": "x", "confidence": "x",
                 "breadth_positive_percent": 0, "leader_count": 0,
                 "primary_change": {}, "primary_price": {}}),
        ])
        t = trend.get_trend()
    assert t["trend_direction"] == "unknown"
    assert t["trend_strength"] == "unknown"
    assert t["market_trend_adjustment"] == 0


# ── 8. Adjusted score is clamped 0..100 and reflects adjustment ──────────────

def test_adjusted_score_clamped_and_applied():
    from core.config import settings
    from market import trend

    with patch.object(settings, "MARKET_TREND_MIN_SNAPSHOTS", 2):
        _inject([
            (10 * 60, {"as_of": "t-10", "risk_on_score": 80, "regime": "x", "confidence": "x",
                       "breadth_positive_percent": 0, "leader_count": 0,
                       "primary_change": {"QQQ": 1.0, "SPY": 0, "IWM": 0}, "primary_price": {}}),
            (0, {"as_of": "now", "risk_on_score": 100, "regime": "x", "confidence": "x",
                 "breadth_positive_percent": 0, "leader_count": 0,
                 "primary_change": {"QQQ": 1.6, "SPY": 0, "IWM": 0}, "primary_price": {}}),
        ])
        t = trend.get_trend()
    # qqq_delta_10 = 0.6 → strong improving → +8
    assert t["market_trend_adjustment"] == 8
    # Clamp: 100 + 8 → 100
    assert t["market_regime_score_after_trend"] == 100
    assert t["market_regime_score_before_trend"] == 100


# ── 9. Provider status reports ETF proxy and futures unavailable ─────────────

def test_provider_status_uses_etf_proxy_and_no_futures():
    from market import trend

    _reset_trend()
    t = trend.get_trend()
    assert t["source"] == "etf_proxy"
    assert t["provider_status"] == "using_etf_proxy"
    assert t["futures_available"] is False
    assert any("ETF proxies" in w for w in (t.get("warnings") or []))


# ── 10. Primary symbols include QQQ/SPY/IWM by default ───────────────────────

def test_primary_symbols_default_qqq_spy_iwm():
    from market import trend

    syms = trend._primary_symbols()
    assert "QQQ" in syms and "SPY" in syms and "IWM" in syms


# ── 11. build_trend_overlay returns the expected compact shape ───────────────

def test_build_trend_overlay_shape():
    from market import trend

    _reset_trend()
    o = trend.build_trend_overlay()
    for k in (
        "market_trend_enabled", "market_trend_source", "market_trend_primary_symbols",
        "market_trend_direction", "market_trend_strength", "market_trend_adjustment",
        "market_trend_reason", "market_regime_score_before_trend",
        "market_regime_score_after_trend", "market_trend_snapshot_count",
    ):
        assert k in o, f"missing key {k}"


# ── 12. No imports of forbidden modules in market/trend.py ───────────────────

def test_trend_module_no_forbidden_imports():
    """AST-check that market/trend.py imports no forbidden modules."""
    import ast
    import pathlib

    src = (pathlib.Path(__file__).parent.parent / "market" / "trend.py").read_text()
    tree = ast.parse(src)
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                seen.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                seen.add(node.module.split(".")[0])
    for forbidden in ("openai", "anthropic", "ollama", "langchain", "alpaca"):
        assert forbidden not in seen, f"forbidden import {forbidden!r}"


# ── 13. record_snapshot mutates primary_change correctly ─────────────────────

def test_record_snapshot_captures_primary_change():
    from core.config import settings
    from market import trend

    _reset_trend()
    with patch.object(settings, "MARKET_TREND_SNAPSHOT_INTERVAL_SECONDS", 1):
        trend.record_snapshot(_snap(55, 0.3, spy=0.2, iwm=0.4))
    assert len(trend._history) == 1
    pc = trend._history[0]["primary_change"]
    assert pc.get("QQQ") == 0.3
    assert pc.get("SPY") == 0.2
    assert pc.get("IWM") == 0.4
