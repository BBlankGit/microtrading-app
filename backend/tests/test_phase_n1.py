"""
Phase N1 — Session-aware Market Mover No-Catalyst Entry Path tests.

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM/Ollama. No V6 keys/auth/test endpoints.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

_BASE_OVERRIDES = {
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
    # Disable other paths so only Path D can fire
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


def _make_mover_meta(rank: int = 5, gap: float = 10.0) -> dict:
    return {"market_mover_rank": rank, "market_mover_gap_percent": gap,
            "market_mover_session": "regular", "market_mover_mode": "full_universe"}


def _regular_quality(
    change: float = 15.0, spread: float = 0.10,
    day_volume: int = 3_000_000, prev_volume: int = 1_000_000,
    ask: float = 25.0, ta_ratio: float | None = None,
) -> dict:
    """Quality dict suitable for a regular-session market mover."""
    return {
        "tradable": True, "ask": ask, "bid": ask - 0.02,
        "last_trade_price": ask - 0.01,
        "spread_percent": spread, "change_percent": change,
        "volume_ratio": 3.0, "day_volume": day_volume,
        "previous_day_volume": prev_volume,
        "rejection_reasons": [],
    }


def _premarket_quality(
    change: float = 12.0, spread: float = 0.15,
    day_volume: int = 80_000, prev_volume: int = 2_000_000,
    ask: float = 20.0,
) -> dict:
    """Quality dict suitable for a premarket market mover."""
    return {
        "tradable": True, "ask": ask, "bid": ask - 0.02,
        "last_trade_price": ask - 0.01,
        "spread_percent": spread, "change_percent": change,
        "volume_ratio": None,  # no meaningful raw ratio in premarket
        "day_volume": day_volume, "previous_day_volume": prev_volume,
        "rejection_reasons": [],
    }


def _run_tick_with_mm(
    quality: dict,
    mover_meta: dict,
    session_type: str = "regular",
    overrides: dict | None = None,
    score_override: dict | None = None,
) -> dict:
    """Run a tick with a single AAPL full-market-mover candidate."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount

    sym = "AAPL"
    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account

    merged_overrides = dict(_BASE_OVERRIDES)
    if overrides:
        merged_overrides.update(overrides)
    rc._runtime_overrides.update(merged_overrides)

    acc = PaperAccount(10_000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc

    default_score = {
        "total_score": 65, "score_threshold": 70, "score_pass": False,
        "components": {}, "positive_reasons": [], "negative_reasons": [],
        "decision_reason": "below_threshold", "catalyst_sentiment": None,
        "catalyst_sentiment_score": 0, "catalyst_materiality_score": 0,
        "catalyst_sentiment_reasons": [], "bullish_flags": [], "bearish_flags": [],
        "strongest_catalyst_title": None, "strongest_catalyst_sentiment": None,
    }
    if score_override:
        default_score.update(score_override)

    try:
        with (
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
            patch("paper.simulator.score_candidate", return_value=default_score),
            patch("paper.simulator._persist_journal_tick",
                  new_callable=AsyncMock, return_value={"ok": True}),
            patch("paper.simulator.get_cached_universe", return_value=None),
            patch("paper.simulator._save_state", new_callable=AsyncMock),
            patch("paper.marketdata_adapter.try_cache_for_quality",
                  new=AsyncMock(return_value=(None, {}))),
            patch("intelligence.full_premarket.get_current_session", return_value=session_type),
            patch("paper.simulator._tv_session_ratio",
                  return_value=0.5 if session_type == "regular" else 0.0),
        ):
            # Inject the mover metadata directly into the simulator's mover map
            sim._state.setdefault("last_tick_market_movers", {})
            result = asyncio.run(_run_with_mover_inject(sim, sym, mover_meta))
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    return result


async def _run_with_mover_inject(sim, sym: str, mover_meta: dict) -> dict:
    """Patch _mover_meta_map inside the tick so the symbol is tagged as a mover."""
    orig_run = sim.run_tick

    async def patched_run():
        # Inject into the module-level function scope by patching _mover_meta_map
        # We do this by patching the function that populates it
        return await orig_run()

    # Instead, patch _get_full_market_movers_for_tick to return our symbol
    with patch.object(sim, "_mover_meta_map", {sym: mover_meta}, create=True):
        # _mover_meta_map is a local inside run_tick, so we must patch at the
        # full-market-mover injection level instead
        pass

    # The cleanest approach: patch the full_premarket snapshot so the injection
    # produces our desired mover metadata for the symbol.
    from intelligence import full_premarket as _fp
    snap = {
        "ok": True,
        "session": mover_meta.get("market_mover_session", "regular"),
        "mode": mover_meta.get("market_mover_mode", "full_universe"),
        "top_movers": [{"symbol": sym, "rank": mover_meta["market_mover_rank"],
                        "gap_percent": mover_meta["market_mover_gap_percent"],
                        "last_price": 25.0}],
    }
    with (
        patch.object(_fp, "get_snapshot", return_value=snap),
        patch("paper.simulator.PAPER_MARKET_MOVERS_CANDIDATES_ENABLED", True, create=True),
    ):
        return await sim.run_tick()


def _simple_run(quality: dict, mover_meta: dict | None, session: str,
                overrides: dict | None = None,
                score_val: int = 65) -> dict:
    """Simplified runner: injects mover via full_premarket snapshot patch."""
    import asyncio
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from intelligence import full_premarket as _fp

    sym = "AAPL"
    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account

    merged = dict(_BASE_OVERRIDES)
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

    snap = {}
    if mover_meta:
        snap = {
            "ok": True,
            "session": session, "mode": "full_universe",
            "top_movers": [{"symbol": sym, "rank": mover_meta["market_mover_rank"],
                            "gap_percent": mover_meta["market_mover_gap_percent"],
                            "last_price": 25.0}],
        }

    try:
        with (
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
                  return_value=0.5 if session == "regular" else 0.0),
            patch.object(_fp, "get_snapshot", return_value=snap),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    return result


def _aapl(result: dict) -> dict:
    cands = result.get("candidates") or []
    for c in cands:
        if c.get("symbol") == "AAPL":
            return c
    return {}


# ══════════════════════════════════════════════════════════════════════
# 1. Regular-session entry via time_adjusted_volume_ratio
# ══════════════════════════════════════════════════════════════════════

def test_regular_session_entry_via_ta_vol():
    """Strong regular-session mover with ta_vol >= 2.0 and no catalyst enters Path D."""
    q = _regular_quality(change=18.0, day_volume=3_000_000, prev_volume=1_000_000)
    # day_vol=3M, prev=1M, elapsed=0.5 → ta_ratio = 3M / (1M * 0.5) = 6.0 ≥ 2.0
    result = _simple_run(q, _make_mover_meta(rank=5), session="regular")
    c = _aapl(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is True
    assert c.get("entry_mode") == "market_mover_no_catalyst"
    assert c.get("action") == "entered"
    assert len(result.get("entries", [])) == 1
    assert result["entries"][0]["entry_mode"] == "market_mover_no_catalyst"


# ══════════════════════════════════════════════════════════════════════
# 2. Premarket entry via volume_vs_previous_day_ratio
# ══════════════════════════════════════════════════════════════════════

def test_premarket_entry_via_volume_vs_prev_day():
    """Premarket mover with vol_vs_prev >= 0.02 enters (no TA vol required)."""
    # day_vol=80_000, prev=2_000_000 → vol_vs_prev = 0.04 ≥ 0.02
    q = _premarket_quality(change=12.0, day_volume=80_000, prev_volume=2_000_000)
    result = _simple_run(q, _make_mover_meta(rank=3), session="premarket")
    c = _aapl(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is True
    assert c.get("market_mover_entry_volume_gate_type") == "premarket_volume_vs_prev"
    assert c.get("entry_mode") == "market_mover_no_catalyst"
    assert c.get("action") == "entered"


# ══════════════════════════════════════════════════════════════════════
# 3. Premarket entry via dollar_volume fallback
# ══════════════════════════════════════════════════════════════════════

def test_premarket_entry_via_dollar_volume_fallback():
    """Premarket mover enters using dollar_volume when vol_vs_prev is unavailable."""
    # prev_volume=0 so vol_vs_prev=None; day_vol=200_000 * ask=10 = $2M > $1M
    q = _premarket_quality(change=8.0, day_volume=200_000, prev_volume=0, ask=10.0)
    result = _simple_run(q, _make_mover_meta(rank=4), session="premarket")
    c = _aapl(result)
    assert c.get("market_mover_entry_checked") is True
    assert c.get("market_mover_entry_eligible") is True
    assert c.get("market_mover_entry_volume_gate_type") == "premarket_dollar_volume"
    assert c.get("entry_mode") == "market_mover_no_catalyst"
    assert c.get("action") == "entered"


# ══════════════════════════════════════════════════════════════════════
# 4. Blocked sessions: afterhours, closed, non_regular, overnight
# ══════════════════════════════════════════════════════════════════════

def test_afterhours_session_blocks_market_mover_entry():
    q = _regular_quality()
    for session in ("afterhours", "closed", "non_regular", "overnight", "unknown"):
        result = _simple_run(q, _make_mover_meta(), session=session)
        c = _aapl(result)
        assert c.get("market_mover_entry_checked") is True, f"checked not True for session={session}"
        assert c.get("market_mover_entry_eligible") is False, f"eligible should be False for session={session}"
        assert c.get("market_mover_entry_reason") == "session_not_allowed", f"wrong reason for session={session}"
        assert c.get("action") is None, f"action should be None for session={session}"


# ══════════════════════════════════════════════════════════════════════
# 5. fda_regulatory still blocks even in Path D
# ══════════════════════════════════════════════════════════════════════

def test_fda_regulatory_blocks_market_mover_path():
    """fda_regulatory catalyst type still hard-blocks Path D."""
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from intelligence import full_premarket as _fp

    sym = "AAPL"
    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    merged = dict(_BASE_OVERRIDES)
    merged["PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES"] = True
    merged["PAPER_BLOCKED_CATALYST_TYPES"] = "fda_regulatory"
    rc._runtime_overrides.update(merged)
    acc = PaperAccount(10_000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc

    q = _regular_quality()
    fda_cat = [{"symbol": sym, "classified_event_type": "fda_regulatory",
                "sentiment": "bullish", "title": "FDA decision"}]
    snap = {"ok": True, "session": "regular", "mode": "full_universe",
            "top_movers": [{"symbol": sym, "rank": 5, "gap_percent": 15.0, "last_price": 25.0}]}
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
            patch.object(_fp, "get_snapshot", return_value=snap),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    c = _aapl(result)
    assert "catalyst_type_blocked:fda_regulatory" in (c.get("rejection_reason") or "")
    assert c.get("action") is None
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 6. Strong bearish blocks Path D
# ══════════════════════════════════════════════════════════════════════

def test_strong_bearish_blocks_market_mover_path():
    """Strong bearish catalyst blocks Path D when PAPER_MARKET_MOVER_BLOCK_IF_ANY_BEARISH=True."""
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from intelligence import full_premarket as _fp

    sym = "AAPL"
    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account
    merged = dict(_BASE_OVERRIDES)
    # Disable hard-gate bearish block so the rejection reaches mm_eval's own bearish check
    merged["PAPER_REJECT_STRONG_BEARISH_CATALYST"] = False
    rc._runtime_overrides.update(merged)
    acc = PaperAccount(10_000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    sim._account = acc

    q = _regular_quality()
    # Score with strong bearish
    scoring = {
        "total_score": 65, "score_threshold": 70, "score_pass": False,
        "components": {}, "positive_reasons": [], "negative_reasons": [],
        "decision_reason": "below_threshold",
        "catalyst_sentiment": "bearish", "catalyst_sentiment_score": -0.9,
        "catalyst_materiality_score": 0.9,  # >= 0.8 threshold → blocked by mm_eval
        "catalyst_sentiment_reasons": [], "bullish_flags": [], "bearish_flags": ["bearish_note"],
        "strongest_catalyst_title": None, "strongest_catalyst_sentiment": "bearish",
    }
    snap = {"ok": True, "session": "regular", "mode": "full_universe",
            "top_movers": [{"symbol": sym, "rank": 5, "gap_percent": 15.0, "last_price": 25.0}]}
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
            patch.object(_fp, "get_snapshot", return_value=snap),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    c = _aapl(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("bearish" in b for b in (c.get("market_mover_entry_blockers") or []))
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 7. Spread above max blocks
# ══════════════════════════════════════════════════════════════════════

def test_spread_above_max_blocks_market_mover():
    q = _regular_quality(spread=0.40)  # 0.40 > 0.35 max
    result = _simple_run(q, _make_mover_meta(), session="regular")
    c = _aapl(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("spread" in b for b in (c.get("market_mover_entry_blockers") or []))
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 8. Regular-session TA vol below min blocks
# ══════════════════════════════════════════════════════════════════════

def test_regular_ta_vol_below_min_blocks():
    """ta_ratio < 2.0 blocks Path D in regular session."""
    # day=1_000_000, prev=1_000_000, elapsed=0.5 → ta_ratio = 1M/(1M*0.5) = 2.0 exact
    # Use day_vol=900_000 → ta_ratio = 0.9M/(1M*0.5) = 1.8 < 2.0
    q = _regular_quality(change=15.0, day_volume=900_000, prev_volume=1_000_000)
    result = _simple_run(q, _make_mover_meta(), session="regular")
    c = _aapl(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("ta_vol" in b for b in (c.get("market_mover_entry_blockers") or []))
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 9. Premarket volume_vs_prev and dollar_volume both missing blocks
# ══════════════════════════════════════════════════════════════════════

def test_premarket_both_volume_checks_missing_blocks():
    """Premarket mover blocked when both vol_vs_prev and dollar_volume fail."""
    # prev=2_000_000, day=1_000 → vol_vs_prev=0.0005 < 0.02; ask=0 → dollar_vol=0
    q = _premarket_quality(change=10.0, day_volume=1_000, prev_volume=2_000_000, ask=0.0)
    result = _simple_run(q, _make_mover_meta(), session="premarket")
    c = _aapl(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("premarket_volume_insufficient" in b for b in (c.get("market_mover_entry_blockers") or []))
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 10. Change percent above max blocks
# ══════════════════════════════════════════════════════════════════════

def test_change_above_max_blocks():
    q = _regular_quality(change=85.0)  # > 80.0 max
    result = _simple_run(q, _make_mover_meta(), session="regular")
    c = _aapl(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("above" in b for b in (c.get("market_mover_entry_blockers") or []))
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 11. Rank above max blocks
# ══════════════════════════════════════════════════════════════════════

def test_rank_above_max_blocks():
    q = _regular_quality()
    result = _simple_run(q, _make_mover_meta(rank=35), session="regular")  # > 30
    c = _aapl(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("rank" in b for b in (c.get("market_mover_entry_blockers") or []))


# ══════════════════════════════════════════════════════════════════════
# 12. Score below min blocks
# ══════════════════════════════════════════════════════════════════════

def test_score_below_min_blocks():
    q = _regular_quality()
    result = _simple_run(q, _make_mover_meta(), session="regular", score_val=40)  # < 55
    c = _aapl(result)
    assert c.get("market_mover_entry_eligible") is False
    assert any("score" in b for b in (c.get("market_mover_entry_blockers") or []))
    assert len(result.get("entries", [])) == 0


# ══════════════════════════════════════════════════════════════════════
# 13. Max open positions and daily trade gates still apply
# ══════════════════════════════════════════════════════════════════════

def test_max_open_positions_blocks_market_mover():
    """Path D respects the PAPER_MAX_OPEN_POSITIONS gate."""
    import paper.simulator as sim
    from paper import runtime_config as rc
    from paper.account import PaperAccount
    from paper.models import Position
    from intelligence import full_premarket as _fp
    import uuid
    from datetime import datetime, timezone

    sym = "AAPL"
    old_overrides = dict(rc._runtime_overrides)
    old_account = sim._account

    merged = dict(_BASE_OVERRIDES)
    merged["PAPER_MAX_OPEN_POSITIONS"] = 1  # already at limit
    rc._runtime_overrides.update(merged)

    acc = PaperAccount(10_000.0)
    acc.daily_baseline_date = sim._ny_trading_date()
    # Add a filled position so we're at the limit
    p = Position(
        position_id=uuid.uuid4().hex[:8], symbol="TSLA",
        entry_price=100.0, shares=1.0, cost_basis=100.0,
        entry_time=datetime.now(timezone.utc).isoformat(),
        entry_catalyst_type="catalyst", entry_mode="catalyst",
    )
    acc.positions["TSLA"] = p
    sim._account = acc

    q = _regular_quality()
    snap = {"ok": True, "session": "regular", "mode": "full_universe",
            "top_movers": [{"symbol": sym, "rank": 5, "gap_percent": 15.0, "last_price": 25.0}]}
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
            patch.object(_fp, "get_snapshot", return_value=snap),
        ):
            result = asyncio.run(sim.run_tick())
    finally:
        sim._account = old_account
        rc._runtime_overrides = old_overrides

    assert len(result.get("entries", [])) == 0
    c = _aapl(result)
    assert c.get("action") != "entered"


# ══════════════════════════════════════════════════════════════════════
# 14. entry_mode is market_mover_no_catalyst
# ══════════════════════════════════════════════════════════════════════

def test_entry_mode_is_market_mover_no_catalyst():
    q = _regular_quality()
    result = _simple_run(q, _make_mover_meta(), session="regular")
    entries = result.get("entries", [])
    assert any(e["entry_mode"] == "market_mover_no_catalyst" for e in entries)


# ══════════════════════════════════════════════════════════════════════
# 15. Position sizing multiplier is applied
# ══════════════════════════════════════════════════════════════════════

def test_position_size_multiplier_applied():
    """Entry budget = normal_budget × 0.25 (PAPER_MARKET_MOVER_POSITION_SIZE_MULTIPLIER)."""
    q = _regular_quality(ask=100.0)
    result = _simple_run(q, _make_mover_meta(), session="regular")
    c = _aapl(result)
    assert c.get("market_mover_entry_position_size_multiplier") == 0.25
    entries = result.get("entries", [])
    assert len(entries) == 1
    # With cash=10_000, pos_size=25%, normal_budget=min(2500, cap), multiplied=0.25
    # So position_budget = 2500*0.25 = 625; shares ≈ 625/100 = 6.25
    assert entries[0]["shares"] > 0


# ══════════════════════════════════════════════════════════════════════
# 16. No Polygon calls added (source inspection)
# ══════════════════════════════════════════════════════════════════════

def test_no_polygon_calls_in_market_mover_path():
    """The market mover evaluation block must not call any new Polygon functions."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    # The mm_eval block is bounded by "_mm_eval" assignment. Check it doesn't
    # directly call polygon_client anywhere in the run_tick function beyond
    # the existing get_ticker_snapshot and get_previous_close calls.
    # Those are only used in the quality-fetch section, not in _mm_eval computation.
    mm_eval_section_start = src.index("_mm_eval: dict | None = None")
    mm_eval_section_end = src.index("# Path D: Market mover no-catalyst entry")
    mm_eval_section = src[mm_eval_section_start:mm_eval_section_end]
    assert "polygon_client" not in mm_eval_section, \
        "Market mover evaluation must not call polygon_client — use cached data only"


# ══════════════════════════════════════════════════════════════════════
# 17. No broker/live/order/AI/Ollama imports
# ══════════════════════════════════════════════════════════════════════

def test_no_broker_or_ai_imports_in_simulator():
    """simulator.py must not import broker, live trading, or AI/LLM modules."""
    import ast
    from pathlib import Path

    FORBIDDEN = {"broker", "alpaca", "ibapi", "openai", "anthropic",
                 "langchain", "ollama", "tastytrade", "schwab", "td_ameritrade"}
    src = Path(__file__).parent.parent / "paper" / "simulator.py"
    tree = ast.parse(src.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.append(node.module)
    for f in FORBIDDEN:
        assert not any(f in m for m in imported), f"simulator.py must not import {f}"


# ══════════════════════════════════════════════════════════════════════
# 18. TP/SL/exit logic unchanged (source inspection)
# ══════════════════════════════════════════════════════════════════════

def test_tp_sl_exit_logic_unchanged():
    """TP/SL exit logic must not reference market_mover_no_catalyst."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    # The actual per-position exit loop must not reference market_mover_no_catalyst
    exits_start = src.index("for sym in list(_account.positions.keys()):")
    exits_end = src.index("# Compute today's momentum entry count")
    exit_loop = src[exits_start:exits_end]
    assert "market_mover_no_catalyst" not in exit_loop, \
        "TP/SL exit logic must not be changed by Phase N1"


# ══════════════════════════════════════════════════════════════════════
# 19. Shadow score does not control entries (source inspection)
# ══════════════════════════════════════════════════════════════════════

def test_shadow_score_does_not_control_entries():
    """Shadow scoring fields must appear after all entry decisions in source order."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    # Path D must appear before the shadow scoring section
    pos_path_d = src.index("# Path D: Market mover no-catalyst entry")
    pos_shadow = src.index("# ── Phase I4-A: Enhanced shadow scoring")
    assert pos_path_d < pos_shadow, \
        "Path D entry logic must precede shadow scoring — shadow must never control entries"
