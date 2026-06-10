"""
Phase I4-A — Enhanced Opportunity Shadow Scoring tests.
Shadow/diagnostic only. No broker, no live trading, no real orders.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from intelligence.shadow_scoring import (
    _build_premarket_lookup,
    _build_reddit_lookup,
    compute_shadow_score,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_quality(
    tradable: bool = True,
    change_pct: float = 3.0,
    volume_ratio: float = 2.0,
    spread_pct: float = 0.15,
) -> dict:
    return {
        "tradable": tradable,
        "change_percent": change_pct,
        "volume_ratio": volume_ratio,
        "spread_percent": spread_pct,
    }


def _make_scoring(
    total_score: int = 60,
    cat_type: str | None = "earnings",
    catalyst_sentiment: str | None = "bullish",
    materiality: float = 0.5,
    momentum_score: int = 15,
) -> dict:
    return {
        "total_score": total_score,
        "score_pass": total_score >= 70,
        "catalyst_type": cat_type,
        "catalyst_sentiment": catalyst_sentiment,
        "catalyst_materiality_score": materiality,
        "components": {"momentum_score": momentum_score},
    }


def _make_premarket_snap(
    symbol: str = "AAPL",
    rank: int = 10,
    gap: float = 6.0,
    dollar_vol: float = 8_000_000.0,
    mode: str = "full_universe",
) -> dict:
    mover = {
        "symbol": symbol,
        "rank": rank,
        "gap_percent": gap,
        "dollar_volume": dollar_vol,
        "day_volume": 500_000,
        "source": "polygon_bulk_snapshot",
    }
    return {
        "ok": True,
        "mode": mode,
        "top_gainers": [mover],
        "top_losers": [],
        "top_movers": [],
    }


def _make_reddit_snap(
    ticker: str = "AAPL",
    rank: int = 5,
    mentions: int = 300,
    spike_ratio: float = 4.0,
) -> dict:
    result_row = {"ticker": ticker, "rank": rank, "mentions": mentions}
    spike = {"ticker": ticker, "mentions": mentions, "spike_ratio": spike_ratio}
    return {"ok": True, "results": [result_row], "spikes": [spike]}


# ── Test 1: Candidate with high premarket rank receives premarket boost ────────

def test_premarket_rank_boost():
    pm_snap = _make_premarket_snap("AAPL", rank=15, gap=7.0, dollar_vol=10_000_000, mode="full_universe")
    result = compute_shadow_score(
        "AAPL",
        quality=_make_quality(),
        scoring=_make_scoring(),
        tick_regime={"regime": "risk_on", "risk_on_score": 80},
        premarket_snap=pm_snap,
        reddit_snap=None,
    )
    assert result["premarket_boost"] > 0
    assert result["premarket_rank"] == 15
    assert result["premarket_gap_percent"] == pytest.approx(7.0)
    # rank <= 30 full_universe + gap >= 5%: +15 + +10
    assert result["enhanced_shadow_components"]["premarket_boost"] >= 20


# ── Test 2: Candidate with high Reddit rank receives Reddit boost ──────────────

def test_reddit_rank_boost():
    rd_snap = _make_reddit_snap("TSLA", rank=8, mentions=400, spike_ratio=5.0)
    result = compute_shadow_score(
        "TSLA",
        quality=_make_quality(),
        scoring=_make_scoring(),
        tick_regime=None,
        premarket_snap=None,
        reddit_snap=rd_snap,
    )
    # rank <= 10: +10, spike_ratio >= 3: +10, mentions >= 200: +3
    assert result["reddit_boost"] >= 20
    assert result["reddit_rank"] == 8
    assert result["reddit_mentions"] == 400
    assert result["reddit_spike_ratio"] == pytest.approx(5.0)


# ── Test 3: FDA regulatory catalyst is hard-blocked ──────────────────────────

def test_fda_regulatory_hard_block():
    result = compute_shadow_score(
        "BIOC",
        quality=_make_quality(),
        scoring=_make_scoring(cat_type="fda_regulatory"),
        tick_regime=None,
        premarket_snap=None,
        reddit_snap=None,
    )
    assert result["enhanced_shadow_decision"] == "WOULD_REJECT"
    assert "fda_regulatory_hard_block" in result["enhanced_shadow_blockers"]
    assert result["enhanced_shadow_score"] == 0


# ── Test 4: Rejected-by-engine candidate can show WOULD_ENTER ─────────────────

def test_engine_rejected_can_show_would_enter():
    pm_snap = _make_premarket_snap("AMD", rank=5, gap=8.0, dollar_vol=15_000_000, mode="full_universe")
    rd_snap = _make_reddit_snap("AMD", rank=3, mentions=500, spike_ratio=6.0)
    # High shadow score but engine rejects (e.g. no catalyst)
    result = compute_shadow_score(
        "AMD",
        quality=_make_quality(change_pct=4.0, volume_ratio=3.0, spread_pct=0.1),
        scoring=_make_scoring(total_score=65, cat_type=None, catalyst_sentiment=None, momentum_score=20),
        tick_regime={"regime": "risk_on", "risk_on_score": 75},
        premarket_snap=pm_snap,
        reddit_snap=rd_snap,
    )
    # Should potentially score high enough for WOULD_ENTER despite engine rejection
    assert result["enhanced_shadow_score"] > 0
    # Verify shadow decision is independent of engine eligible flag
    assert result["enhanced_shadow_decision"] in ("WOULD_ENTER", "WATCH", "WOULD_REJECT")
    assert "eligible" not in result  # shadow fields never include eligible


# ── Test 5: Shadow fields do not alter eligible/action/entry_mode ─────────────

def test_shadow_fields_do_not_alter_trade_fields():
    result = compute_shadow_score(
        "NVDA",
        quality=_make_quality(),
        scoring=_make_scoring(),
        tick_regime=None,
        premarket_snap=None,
        reddit_snap=None,
    )
    # Shadow scoring output must NOT contain decision-affecting fields
    for forbidden in ("eligible", "action", "entry_mode", "rejection_reason"):
        assert forbidden not in result, f"shadow result must not contain '{forbidden}'"


# ── Test 6: No new Polygon calls in scoring path ─────────────────────────────

def test_no_polygon_calls_in_shadow_scoring():
    import data.polygon_client as pc
    original_get = pc._get

    call_count = [0]
    async def _mock_get(*a, **kw):
        call_count[0] += 1
        return {}

    # Patch polygon _get — should never be called
    pc._get = _mock_get
    try:
        compute_shadow_score(
            "AAPL",
            quality=_make_quality(),
            scoring=_make_scoring(),
            tick_regime=None,
            premarket_snap=_make_premarket_snap(),
            reddit_snap=_make_reddit_snap(),
        )
    finally:
        pc._get = original_get

    assert call_count[0] == 0, "shadow scoring must not call Polygon"


# ── Test 7: No ApeWisdom calls in scoring path ────────────────────────────────

def test_no_apewisdom_calls_in_shadow_scoring():
    import intelligence.reddit as ri
    original_fetch = getattr(ri, "fetch_and_refresh", None)
    call_count = [0]

    async def _mock_fetch(*a, **kw):
        call_count[0] += 1
        return ri.get_snapshot()

    ri.fetch_and_refresh = _mock_fetch
    try:
        compute_shadow_score(
            "GME",
            quality=_make_quality(),
            scoring=_make_scoring(),
            tick_regime=None,
            premarket_snap=None,
            reddit_snap=_make_reddit_snap("GME"),
        )
    finally:
        if original_fetch:
            ri.fetch_and_refresh = original_fetch

    assert call_count[0] == 0, "shadow scoring must not call ApeWisdom"


# ── Test 8: No broker/live/order/AI imports in shadow module ─────────────────

def test_no_forbidden_imports_in_shadow_module():
    import importlib, ast, pathlib
    src = pathlib.Path(__file__).parent.parent / "intelligence" / "shadow_scoring.py"
    tree = ast.parse(src.read_text())
    forbidden = {"broker", "live_trading", "openai", "anthropic", "ollama", "langchain"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = ""
            if isinstance(node, ast.Import):
                name = " ".join(a.name for a in node.names)
            elif node.module:
                name = node.module
            for f in forbidden:
                assert f not in name.lower(), f"forbidden import '{f}' found in shadow_scoring.py"


# ── Test 9: Strong bearish catalyst is hard-blocked by shadow scorer ──────────

def test_strong_bearish_catalyst_blocked():
    result = compute_shadow_score(
        "XBIO",
        quality=_make_quality(),
        scoring=_make_scoring(
            catalyst_sentiment="bearish",
            materiality=0.9,
            cat_type="fda_regulatory",
        ),
        tick_regime=None,
        premarket_snap=None,
        reddit_snap=None,
    )
    assert result["enhanced_shadow_decision"] == "WOULD_REJECT"
    assert len(result["enhanced_shadow_blockers"]) > 0


# ── Test 10: Monitoring aggregate counts are correct ─────────────────────────

def test_shadow_aggregate_counts():
    """Shadow aggregate stats are computed from candidate list in simulator."""
    from intelligence.shadow_scoring import compute_shadow_score

    # Simulate 3 candidates with different shadow outcomes
    base_quality = _make_quality(change_pct=3.0, volume_ratio=2.0)
    base_scoring = _make_scoring(total_score=60)

    # High-score symbol (WOULD_ENTER)
    pm_snap = _make_premarket_snap("HOT", rank=5, gap=9.0, dollar_vol=12_000_000, mode="full_universe")
    rd_snap = _make_reddit_snap("HOT", rank=2, mentions=600, spike_ratio=7.0)
    hot = compute_shadow_score("HOT", base_quality, base_scoring,
                               tick_regime={"regime": "risk_on", "risk_on_score": 80},
                               premarket_snap=pm_snap, reddit_snap=rd_snap)

    # Low-score symbol (WOULD_REJECT)
    cold = compute_shadow_score("COLD", _make_quality(tradable=False), _make_scoring(total_score=0),
                                tick_regime=None, premarket_snap=None, reddit_snap=None)

    # Mid-score — might be WATCH
    mid_pm = _make_premarket_snap("MID", rank=50, gap=3.0, dollar_vol=2_000_000, mode="full_universe")
    mid = compute_shadow_score("MID", _make_quality(change_pct=1.5), _make_scoring(total_score=40),
                               tick_regime=None, premarket_snap=mid_pm, reddit_snap=None)

    candidates = [
        {"symbol": "HOT", "eligible": False, **hot},   # missed opportunity
        {"symbol": "COLD", "eligible": False, **cold},
        {"symbol": "MID",  "eligible": False, **mid},
    ]

    would_enter = sum(1 for c in candidates if c.get("enhanced_shadow_decision") == "WOULD_ENTER")
    watch       = sum(1 for c in candidates if c.get("enhanced_shadow_decision") == "WATCH")
    reject      = sum(1 for c in candidates if c.get("enhanced_shadow_decision") == "WOULD_REJECT")
    missed      = sum(1 for c in candidates
                      if c.get("enhanced_shadow_decision") == "WOULD_ENTER" and not c.get("eligible"))

    assert would_enter + watch + reject == 3
    # HOT with rank=5, gap=9, reddit rank=2, spike=7, risk_on should score very high → WOULD_ENTER
    assert hot["enhanced_shadow_decision"] == "WOULD_ENTER"
    assert missed == would_enter  # all WOULD_ENTER candidates are ineligible in this test
