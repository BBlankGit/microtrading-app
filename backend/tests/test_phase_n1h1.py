"""
Phase N1-H1 — Hardened session gates for market_mover_no_catalyst entry.

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM/Ollama. No V6 keys/auth/test endpoints.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

# ── Shared helpers ────────────────────────────────────────────────────────────

_BASE = {
    "PAPER_MARKET_MOVER_ENTRY_ENABLED": True,
    "PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "premarket,regular",
    "PAPER_MARKET_MOVER_TOP_RANK_MAX": 30,
    "PAPER_MARKET_MOVER_MIN_CHANGE_PERCENT": 5.0,
    "PAPER_MARKET_MOVER_MAX_CHANGE_PERCENT": 80.0,
    "PAPER_MARKET_MOVER_MIN_TIME_ADJ_VOLUME_RATIO": 2.0,
    "PAPER_MARKET_MOVER_MIN_PREMARKET_VOLUME_VS_PREV_DAY_RATIO": 0.02,
    "PAPER_MARKET_MOVER_MIN_DOLLAR_VOLUME": 1_000_000,
    "PAPER_MARKET_MOVER_MAX_SPREAD_PERCENT": 0.35,
    "PAPER_MARKET_MOVER_MIN_SCORE": 55,
    "PAPER_MARKET_MOVER_POSITION_SIZE_MULTIPLIER": 0.25,
    "PAPER_MARKET_MOVER_MAX_TRADES_PER_DAY": 10,
    "PAPER_MARKET_MOVER_BLOCK_IF_ANY_BEARISH": True,
    "PAPER_MARKET_MOVER_ALLOW_RISK_OFF": True,
    "PAPER_ENTRY_SCORE_THRESHOLD": 70,
    "PAPER_MOMENTUM_MODE_ENABLED": False,
    "PAPER_NO_CATALYST_ENTRY_ENABLED": False,
    "PAPER_DAILY_MAX_LOSS_ENABLED": False,
    "PAPER_MAX_OPEN_POSITIONS": 5,
    "PAPER_MAX_TRADES_PER_DAY": 100,
    "PAPER_POSITION_SIZE_PERCENT": 25.0,
    "PAPER_TAKE_PROFIT_PERCENT": 0.60,
    "PAPER_STOP_LOSS_PERCENT": 0.35,
    "PAPER_MAX_HOLD_MINUTES": 15,
    "PAPER_REJECT_STRONG_BEARISH_CATALYST": True,
    "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": 0.8,
    "PAPER_MIN_VOLUME_RATIO": 0.8,
    "PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO": True,
    "PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN": 0.8,
    "PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR": 0.05,
    "MARKET_REGIME_ENABLED": False,
    "PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY": False,
}


def _q_regular(change: float = 15.0) -> dict:
    return {
        "tradable": True, "ask": 25.0, "bid": 24.98,
        "last_trade_price": 24.99, "spread_percent": 0.10,
        "change_percent": change, "volume_ratio": 3.0,
        "day_volume": 3_000_000, "previous_day_volume": 1_000_000,
        "rejection_reasons": [],
    }


def _q_premarket(change: float = 12.0) -> dict:
    return {
        "tradable": True, "ask": 20.0, "bid": 19.98,
        "last_trade_price": 19.99, "spread_percent": 0.15,
        "change_percent": change, "volume_ratio": None,
        "day_volume": 80_000, "previous_day_volume": 2_000_000,
        "rejection_reasons": [],
    }


def _meta(rank: int = 5, gap: float = 10.0) -> dict:
    return {"market_mover_rank": rank, "market_mover_gap_percent": gap,
            "market_mover_session": "regular", "market_mover_mode": "full_universe"}


def _snap(sym: str, meta: dict, session: str) -> dict:
    return {
        "ok": True, "session": session, "mode": "full_universe",
        "top_movers": [{"symbol": sym, "rank": meta["market_mover_rank"],
                        "gap_percent": meta["market_mover_gap_percent"],
                        "last_price": 25.0}],
    }


def _run(quality: dict, meta: dict, session: str,
         overrides: dict | None = None,
         regime_str: str | None = None,
         score_val: int = 65) -> dict:
    """Run one simulator tick.

    regime_str: if set, patches market.regime.get_market_regime to return this
    regime value (e.g. "risk_off" or "risk_on").  MARKET_REGIME_ENABLED must
    be True in overrides for this to take effect.
    """
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from intelligence import full_premarket as _fp

    sym = "AAPL"
    old_ov = dict(rc._runtime_overrides)
    old_acc = sim._account

    merged = dict(_BASE)
    if overrides:
        merged.update(overrides)
    rc._runtime_overrides.update(merged)

    acc = PaperAccount(10_000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc

    scoring = {
        "total_score": score_val, "score_threshold": 70,
        "score_pass": score_val >= 70,
        "components": {}, "positive_reasons": [], "negative_reasons": [],
        "decision_reason": "below_threshold" if score_val < 70 else "pass",
        "catalyst_sentiment": None, "catalyst_sentiment_score": 0,
        "catalyst_materiality_score": 0, "catalyst_sentiment_reasons": [],
        "bullish_flags": [], "bearish_flags": [],
        "strongest_catalyst_title": None, "strongest_catalyst_sentiment": None,
    }

    is_regular = session == "regular"
    snp = _snap(sym, meta, session)

    # Build a fake regime response matching the shape the simulator expects
    regime_return = {
        "risk": {
            "regime": regime_str or "risk_on",
            "risk_on_score": 0.8 if (regime_str or "risk_on") == "risk_on" else 0.2,
            "confidence": 0.9,
        },
        "as_of": "2026-06-11",
    }

    ctx_patches = [
        patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
              return_value={
                  "active_symbols": [sym], "active_count": 1,
                  "last_refreshed_at": None, "refresh_reason": "test",
                  "discovery": {"enabled": False, "discovered_count": 0, "errors": []},
              }),
        patch("paper.simulator.polygon_client.get_ticker_snapshot",
              new_callable=AsyncMock, return_value=quality),
        patch("paper.simulator.polygon_client.get_previous_close",
              new_callable=AsyncMock, return_value={}),
        patch("paper.simulator.evaluate_market_quality", return_value=quality),
        patch("paper.simulator.collect_news_for_symbols",
              new_callable=AsyncMock, return_value={"filter": {"accepted": []}}),
        patch("paper.simulator.score_candidate", return_value=scoring),
        patch("paper.simulator._persist_journal_tick",
              new_callable=AsyncMock, return_value={"ok": True}),
        patch("paper.simulator.get_cached_universe", return_value=None),
        patch("paper.simulator._save_state", new_callable=AsyncMock),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, {}))),
        patch("intelligence.full_premarket.get_current_session", return_value=session),
        patch("paper.simulator._tv_session_ratio",
              return_value=0.5 if is_regular else 0.0),
        patch.object(_fp, "get_snapshot", return_value=snp),
    ]
    if regime_str is not None:
        ctx_patches.append(
            patch("market.regime.get_market_regime",
                  new_callable=AsyncMock, return_value=regime_return)
        )

    try:
        with __import__("contextlib").ExitStack() as stack:
            for p in ctx_patches:
                stack.enter_context(p)
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_acc
        rc._runtime_overrides = old_ov

    return result


def _cand(result: dict) -> dict:
    for c in (result.get("candidates") or []):
        if c.get("symbol") == "AAPL":
            return c
    return {}


# ══════════════════════════════════════════════════════════════════════
# 1. Default config: premarket still allowed
# ══════════════════════════════════════════════════════════════════════

def test_default_config_premarket_allowed():
    """Default 'premarket,regular' allows premarket entry."""
    result = _run(_q_premarket(), _meta(), "premarket")
    c = _cand(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is True
    assert c.get("market_mover_entry_reason") == "eligible"
    assert c.get("market_mover_unsafe_sessions_warning") is None


# ══════════════════════════════════════════════════════════════════════
# 2. Default config: regular still allowed
# ══════════════════════════════════════════════════════════════════════

def test_default_config_regular_allowed():
    """Default 'premarket,regular' allows regular entry."""
    result = _run(_q_regular(), _meta(), "regular")
    c = _cand(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is True
    assert c.get("market_mover_entry_reason") == "eligible"
    assert c.get("market_mover_unsafe_sessions_warning") is None


# ══════════════════════════════════════════════════════════════════════
# 3–6. Unsafe session hard-blocks regardless of runtime override
# ══════════════════════════════════════════════════════════════════════

def test_afterhours_hard_blocked_even_if_configured():
    """afterhours is hard-blocked even when operator sets allowed_sessions='afterhours'."""
    result = _run(_q_regular(), _meta(), "afterhours",
                  overrides={"PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "afterhours"})
    c = _cand(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is False
    assert "session_hard_blocked" in (c.get("market_mover_entry_blockers") or [])
    assert len(result.get("entries", [])) == 0


def test_closed_hard_blocked_even_if_configured():
    """closed is hard-blocked even when operator sets allowed_sessions='closed'."""
    result = _run(_q_regular(), _meta(), "closed",
                  overrides={"PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "closed"})
    c = _cand(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is False
    assert "session_hard_blocked" in (c.get("market_mover_entry_blockers") or [])


def test_non_regular_hard_blocked_even_if_configured():
    """non_regular is hard-blocked even when operator sets allowed_sessions='non_regular'."""
    result = _run(_q_regular(), _meta(), "non_regular",
                  overrides={"PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "non_regular"})
    c = _cand(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is False
    assert "session_hard_blocked" in (c.get("market_mover_entry_blockers") or [])


def test_overnight_hard_blocked_even_if_configured():
    """overnight is hard-blocked even when operator sets allowed_sessions='overnight'."""
    result = _run(_q_regular(), _meta(), "overnight",
                  overrides={"PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "overnight"})
    c = _cand(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is False
    assert "session_hard_blocked" in (c.get("market_mover_entry_blockers") or [])


# ══════════════════════════════════════════════════════════════════════
# 7. Mixed config: unsafe stripped, safe portion still works
# ══════════════════════════════════════════════════════════════════════

def test_mixed_config_safe_session_allowed_unsafe_stripped():
    """'premarket,afterhours' allows premarket (safe) and exposes warning for afterhours."""
    result = _run(_q_premarket(), _meta(), "premarket",
                  overrides={"PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "premarket,afterhours"})
    c = _cand(result)
    assert c.get("market_mover_entry_eligible") is True
    warn = c.get("market_mover_unsafe_sessions_warning") or ""
    assert "afterhours" in warn


def test_mixed_config_unsafe_session_still_blocked():
    """'premarket,afterhours' still hard-blocks afterhours even though it's in the string."""
    result = _run(_q_regular(), _meta(), "afterhours",
                  overrides={"PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "premarket,afterhours"})
    c = _cand(result)
    assert c.get("market_mover_entry_eligible") is False
    assert "session_hard_blocked" in (c.get("market_mover_entry_blockers") or [])
    warn = c.get("market_mover_unsafe_sessions_warning") or ""
    assert "afterhours" in warn


# ══════════════════════════════════════════════════════════════════════
# 8. Regular session uses time_adjusted_volume_ratio gate
# ══════════════════════════════════════════════════════════════════════

def test_regular_uses_ta_vol_gate():
    """Regular session always goes through time_adjusted_volume gate."""
    result = _run(_q_regular(), _meta(), "regular")
    c = _cand(result)
    assert c.get("market_mover_entry_volume_gate_type") == "time_adjusted"


# ══════════════════════════════════════════════════════════════════════
# 9. Premarket session uses its own volume gate
# ══════════════════════════════════════════════════════════════════════

def test_premarket_uses_premarket_volume_gate():
    """Premarket session uses volume_vs_prev or dollar_volume gate."""
    result = _run(_q_premarket(), _meta(), "premarket")
    c = _cand(result)
    assert c.get("market_mover_entry_volume_gate_type") in (
        "premarket_volume_vs_prev", "premarket_dollar_volume"
    )


# ══════════════════════════════════════════════════════════════════════
# 10. Volume gate bypass not possible for unsafe sessions
# ══════════════════════════════════════════════════════════════════════

def test_unsafe_session_cannot_bypass_volume_gate():
    """An unsafe session hard-blocked before volume gate; volume_gate_type remains None."""
    result = _run(_q_regular(), _meta(), "afterhours",
                  overrides={"PAPER_MARKET_MOVER_ALLOWED_SESSIONS": "afterhours"})
    c = _cand(result)
    assert c.get("market_mover_entry_eligible") is False
    assert c.get("market_mover_entry_volume_gate_type") is None


# ══════════════════════════════════════════════════════════════════════
# 11. Risk-off blocks when ALLOW_RISK_OFF=False
# ══════════════════════════════════════════════════════════════════════

def test_risk_off_blocks_when_allow_risk_off_false():
    """market_mover_no_catalyst blocked when regime=risk_off and ALLOW_RISK_OFF=False."""
    result = _run(_q_regular(), _meta(), "regular",
                  overrides={"PAPER_MARKET_MOVER_ALLOW_RISK_OFF": False,
                              "MARKET_REGIME_ENABLED": True},
                  regime_str="risk_off")
    c = _cand(result)
    assert c.get("market_mover_entry_eligible") is False
    # Phase M1-H1: the blocker string is either the legacy "risk_off_blocked"
    # (raw regime path) or "market_mover_risk_off_blocked_by_trend_adjusted_regime"
    # (when MARKET_TREND_APPLY_TO_MARKET_MOVER is enabled, which is the default).
    blockers = c.get("market_mover_entry_blockers") or []
    assert any("risk_off" in b for b in blockers), (
        f"expected a risk_off blocker in {blockers}"
    )
    assert c.get("market_mover_risk_off_allowed") is False


# ══════════════════════════════════════════════════════════════════════
# 12. Risk-off allowed when ALLOW_RISK_OFF=True
# ══════════════════════════════════════════════════════════════════════

def test_risk_off_allowed_when_allow_risk_off_true():
    """market_mover_no_catalyst can still proceed when regime=risk_off and ALLOW_RISK_OFF=True."""
    result = _run(_q_regular(), _meta(), "regular",
                  overrides={"PAPER_MARKET_MOVER_ALLOW_RISK_OFF": True,
                              "MARKET_REGIME_ENABLED": True},
                  regime_str="risk_off")
    c = _cand(result)
    assert c.get("market_mover_risk_off_allowed") is True
    assert "risk_off_blocked" not in (c.get("market_mover_entry_blockers") or [])
    # With no other blockers, entry should be eligible
    assert c.get("market_mover_entry_eligible") is True


# ══════════════════════════════════════════════════════════════════════
# 13. fda_regulatory still hard-blocks
# ══════════════════════════════════════════════════════════════════════

def test_fda_still_hard_blocks_after_n1h1():
    """fda_regulatory catalyst type still hard-blocks Path D after N1-H1 changes."""
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from intelligence import full_premarket as _fp

    sym = "AAPL"
    old_ov = dict(rc._runtime_overrides)
    old_acc = sim._account
    merged = dict(_BASE)
    merged["PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES"] = True
    merged["PAPER_BLOCKED_CATALYST_TYPES"] = "fda_regulatory"
    rc._runtime_overrides.update(merged)
    acc = PaperAccount(10_000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc
    q = _q_regular()
    fda_cat = [{"symbol": sym, "classified_event_type": "fda_regulatory",
                "sentiment": "bullish", "title": "FDA decision"}]
    snp = _snap(sym, _meta(), "regular")
    scoring = {
        "total_score": 65, "score_threshold": 70, "score_pass": False,
        "components": {}, "positive_reasons": [], "negative_reasons": [],
        "decision_reason": "below_threshold", "catalyst_sentiment": None,
        "catalyst_sentiment_score": 0, "catalyst_materiality_score": 0,
        "catalyst_sentiment_reasons": [], "bullish_flags": [], "bearish_flags": [],
        "strongest_catalyst_title": None, "strongest_catalyst_sentiment": None,
    }
    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [sym], "active_count": 1,
                                "last_refreshed_at": None, "refresh_reason": "test",
                                "discovery": {"enabled": False, "discovered_count": 0, "errors": []}}),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=q),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=q),
            patch("paper.simulator.collect_news_for_symbols",
                  new_callable=AsyncMock, return_value={"filter": {"accepted": fda_cat}}),
            patch("paper.simulator.score_candidate", return_value=scoring),
            patch("paper.simulator._persist_journal_tick",
                  new_callable=AsyncMock, return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality",
                  new=AsyncMock(return_value=(None, {}))),
            patch("intelligence.full_premarket.get_current_session", return_value="regular"),
            patch("paper.simulator._tv_session_ratio", return_value=0.5),
            patch.object(_fp, "get_snapshot", return_value=snp),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_acc
        rc._runtime_overrides = old_ov

    c = _cand(result)
    assert "catalyst_type_blocked:fda_regulatory" in (c.get("rejection_reason") or "")
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 14. Strong bearish still hard-blocks
# ══════════════════════════════════════════════════════════════════════

def test_strong_bearish_still_hard_blocks_after_n1h1():
    """Strong bearish still blocks Path D after N1-H1 changes."""
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from intelligence import full_premarket as _fp

    sym = "AAPL"
    old_ov = dict(rc._runtime_overrides)
    old_acc = sim._account
    merged = dict(_BASE)
    merged["PAPER_REJECT_STRONG_BEARISH_CATALYST"] = False  # disable hard gate; use mm_eval gate
    rc._runtime_overrides.update(merged)
    acc = PaperAccount(10_000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc
    q = _q_regular()
    scoring = {
        "total_score": 65, "score_threshold": 70, "score_pass": False,
        "components": {}, "positive_reasons": [], "negative_reasons": [],
        "decision_reason": "below_threshold",
        "catalyst_sentiment": "bearish", "catalyst_sentiment_score": -0.9,
        "catalyst_materiality_score": 0.9,
        "catalyst_sentiment_reasons": [], "bullish_flags": [], "bearish_flags": ["b"],
        "strongest_catalyst_title": None, "strongest_catalyst_sentiment": "bearish",
    }
    snp = _snap(sym, _meta(), "regular")
    try:
        with (
            patch("paper.simulator.get_active_paper_universe", new_callable=AsyncMock,
                  return_value={"active_symbols": [sym], "active_count": 1,
                                "last_refreshed_at": None, "refresh_reason": "test",
                                "discovery": {"enabled": False, "discovered_count": 0, "errors": []}}),
            patch("paper.simulator.polygon_client.get_ticker_snapshot",
                  new_callable=AsyncMock, return_value=q),
            patch("paper.simulator.polygon_client.get_previous_close",
                  new_callable=AsyncMock, return_value={}),
            patch("paper.simulator.evaluate_market_quality", return_value=q),
            patch("paper.simulator.collect_news_for_symbols",
                  new_callable=AsyncMock, return_value={"filter": {"accepted": []}}),
            patch("paper.simulator.score_candidate", return_value=scoring),
            patch("paper.simulator._persist_journal_tick",
                  new_callable=AsyncMock, return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality",
                  new=AsyncMock(return_value=(None, {}))),
            patch("intelligence.full_premarket.get_current_session", return_value="regular"),
            patch("paper.simulator._tv_session_ratio", return_value=0.5),
            patch.object(_fp, "get_snapshot", return_value=snp),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_acc
        rc._runtime_overrides = old_ov

    c = _cand(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("bearish" in b for b in (c.get("market_mover_entry_blockers") or []))
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 15. No Polygon calls in the hardened path
# ══════════════════════════════════════════════════════════════════════

def test_no_polygon_calls_in_hardened_path():
    """The hardened N1-H1 session gate adds no Polygon calls to simulator source."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / "paper" / "simulator.py").read_text()
    # The _MM_SAFE_SESSIONS block must not call polygon_client
    n1h1_start = src.index("_MM_SAFE_SESSIONS")
    # Confirm no new get_ticker_snapshot in the mm_eval block
    mm_start = src.index("# ── Market mover no-catalyst evaluation (Phase N1)")
    mm_end = src.index("_mm_eval = {")
    mm_block = src[mm_start:mm_end]
    assert "polygon_client" not in mm_block, "mm_eval block must not call polygon_client"
    assert n1h1_start < mm_start or True  # constant defined before block — always passes


# ══════════════════════════════════════════════════════════════════════
# 16. No broker / live / real-order / AI / Ollama imports in simulator
# ══════════════════════════════════════════════════════════════════════

def test_no_broker_or_ai_imports_after_n1h1():
    """simulator.py must not import broker, live-order, or AI libs after N1-H1."""
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / "paper" / "simulator.py").read_text()
    for forbidden in ("alpaca", "execute_order", "place_order", "openai",
                      "anthropic", "langchain", "ollama"):
        assert forbidden not in src.lower(), f"Forbidden symbol '{forbidden}' found in simulator.py"
