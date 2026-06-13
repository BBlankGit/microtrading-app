from fastapi import APIRouter, Depends

from api.dependencies import require_admin_token
from paper import simulator
from paper.analytics import get_trade_analytics
from paper.discovery import discover_market_movers
from paper.universe import build_dynamic_universe, get_active_paper_universe, get_cached_universe

router = APIRouter(prefix="/api/paper")


@router.get("/status")
async def paper_status():
    return simulator.get_status()


@router.get("/positions")
async def paper_positions():
    return {"positions": simulator.get_positions()}


@router.get("/trades")
async def paper_trades():
    return {"trades": simulator.get_trades()}


@router.get("/wallets")
async def paper_wallets():
    """
    Phase G1B Part C / G1B-H1 Part A — snapshot of all three fake wallets.

    Always returns the engine plus both shadow wallets, even when a shadow
    wallet is inactive (so dashboards never have to hide the card). Each
    bucket includes status, inactive_reason, daily_pnl, win_rate, and
    last_update_time. Read-only; fake-money only.

    Phase G1B-H3: also surfaces session status — market_session_open,
    entries_allowed, entry_block_reason — and out-of-session position counts.
    """
    from paper import shadow_wallets as _sw
    from paper import eod as _eod
    from paper.session import is_regular_session_now as _is_session_now
    engine_raw = simulator.get_status()
    engine_trades = simulator.get_trades()
    engine_wins = sum(1 for t in engine_trades if (t.get("pnl") or 0) > 0)
    engine_win_rate = (
        round(engine_wins / len(engine_trades) * 100.0, 2)
        if engine_trades
        else None
    )
    engine_last_update = None
    times = [t.get("exit_time") for t in engine_trades if t.get("exit_time")]
    times += [p.get("entry_time") for p in simulator.get_positions() if p.get("entry_time")]
    if times:
        engine_last_update = max(times)
    daily_baseline = engine_raw.get("daily_start_equity") or engine_raw.get("starting_cash")
    daily_pnl = None
    if daily_baseline:
        daily_pnl = round((engine_raw.get("equity") or 0) - float(daily_baseline), 4)
    engine = {
        **engine_raw,
        "wallet_id": "engine",
        "strategy_id": "engine",
        "status": "active",
        "inactive_reason": None,
        "daily_pnl": daily_pnl,
        "win_rate": engine_win_rate,
        "last_update_time": engine_last_update,
    }
    shadow = _sw.snapshot()
    _eb, _ebr = _eod.entries_blocked()
    all_positions = (
        simulator.get_positions()
        + _sw.get_positions(_sw.WALLET_DETERMINISTIC)
        + _sw.get_positions(_sw.WALLET_AI)
    )
    out_of_session_count = sum(
        1 for p in all_positions
        if _eod.position_entry_is_out_of_session(p.get("entry_time"))
    )
    return {
        "engine": engine,
        "deterministic_shadow": shadow.get(_sw.WALLET_DETERMINISTIC),
        "ai_shadow": shadow.get(_sw.WALLET_AI),
        "shadow_wallets_enabled": shadow.get("enabled"),
        "llm_enabled": shadow.get("llm_enabled"),
        "wallets": [
            engine,
            shadow.get(_sw.WALLET_DETERMINISTIC),
            shadow.get(_sw.WALLET_AI),
        ],
        "market_session_open": _is_session_now(),
        "entries_allowed": not _eb,
        "entry_block_reason": _ebr,
        "out_of_session_open_positions": out_of_session_count,
        "invalid_out_of_session_positions": out_of_session_count,
    }


def _annotate_out_of_session(positions: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Stamp `out_of_session: true` on positions entered outside regular US
    session hours (Mon–Fri 09:30–16:00 ET). Returns (positions, warnings).

    Phase G1B-H3 Part C: surfaces positions that will be force-closed on the
    next tick as invalid_out_of_session_entry_flatten.
    """
    from paper import eod as _eod
    warnings: list[dict] = []
    for p in positions:
        entry_time = p.get("entry_time")
        if _eod.position_entry_is_out_of_session(entry_time):
            p["out_of_session"] = True
            warnings.append({
                "wallet_id": p.get("wallet_id"),
                "strategy_id": p.get("strategy_id"),
                "symbol": p.get("symbol"),
                "entry_time": entry_time,
                "reason": "invalid_out_of_session_open_position",
                "remediation": "pending_flatten",
            })
        else:
            p["out_of_session"] = False
    return positions, warnings


def _annotate_stale_overnight(positions: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Stamp `stale_overnight: true` on positions whose entry NY trading-
    session date is strictly older than today's latest NY session (and
    PAPER_ALLOW_OVERNIGHT_POSITIONS is False). Returns (positions, warnings).

    Phase G1B-H2 Part F: the dashboard should not present a yesterday-leftover
    position as a normal open position. The simulator's next tick will
    flatten it; until then this lets the dashboard surface it as stale.
    """
    from paper import eod as _eod
    warnings: list[dict] = []
    for p in positions:
        entry_time = p.get("entry_time")
        if _eod.position_is_stale_overnight(entry_time):
            p["stale_overnight"] = True
            warnings.append({
                "wallet_id": p.get("wallet_id"),
                "symbol": p.get("symbol"),
                "entry_time": entry_time,
                "reason": "stale_overnight_pending_flatten",
            })
        else:
            p["stale_overnight"] = False
    return positions, warnings


@router.get("/wallets/positions")
async def paper_wallet_positions(wallet_id: str | None = None):
    """
    Open positions, optionally filtered by wallet_id. When `wallet_id` is
    omitted, returns positions across engine + both shadow wallets, each
    tagged with `wallet_id`/`strategy_id` and a `stale_overnight` flag.
    Backward-compatible with the existing `/api/paper/positions` endpoint
    (which still returns engine only and without the new annotations).
    """
    from paper import shadow_wallets as _sw

    engine_positions = [
        {**p, "wallet_id": "engine", "strategy_id": "engine"}
        for p in simulator.get_positions()
    ]
    def _annotate(pos_list: list[dict]) -> tuple[list[dict], list[dict]]:
        pos_list, stale_warns = _annotate_stale_overnight(pos_list)
        pos_list, oos_warns = _annotate_out_of_session(pos_list)
        return pos_list, stale_warns + oos_warns

    if wallet_id == "engine":
        positions, warnings = _annotate(engine_positions)
        return {"wallet_id": "engine", "positions": positions, "warnings": warnings}
    if wallet_id == _sw.WALLET_DETERMINISTIC:
        positions, warnings = _annotate(_sw.get_positions(_sw.WALLET_DETERMINISTIC))
        return {
            "wallet_id": _sw.WALLET_DETERMINISTIC,
            "positions": positions,
            "warnings": warnings,
        }
    if wallet_id == _sw.WALLET_AI:
        positions, warnings = _annotate(_sw.get_positions(_sw.WALLET_AI))
        return {
            "wallet_id": _sw.WALLET_AI,
            "positions": positions,
            "warnings": warnings,
        }
    all_positions = (
        engine_positions
        + _sw.get_positions(_sw.WALLET_DETERMINISTIC)
        + _sw.get_positions(_sw.WALLET_AI)
    )
    positions, warnings = _annotate(all_positions)
    return {
        "wallet_id": None,
        "positions": positions,
        "warnings": warnings,
    }


@router.get("/wallets/trades")
async def paper_wallet_trades(
    wallet_id: str | None = None,
    session_date: str | None = None,
    latest_session: bool = False,
):
    """
    Closed trades, optionally filtered by wallet_id and/or session_date.

    `session_date` is an America/New_York YYYY-MM-DD trading-session date.
    `latest_session=true` resolves automatically to the latest completed
    US session so the dashboard's "latest closed positions" view keeps
    working after 16:00 ET and over weekends. Trades are matched on the
    NY session date of their exit_time (or entry_time if exit is missing).
    """
    from paper import shadow_wallets as _sw
    from paper.session import latest_session_date_ny, session_date_for

    engine_trades = [
        {**t, "wallet_id": "engine", "strategy_id": "engine"}
        for t in simulator.get_trades()
    ]
    det_trades = _sw.get_trades(_sw.WALLET_DETERMINISTIC)
    ai_trades = _sw.get_trades(_sw.WALLET_AI)

    if wallet_id == "engine":
        trades = engine_trades
    elif wallet_id == _sw.WALLET_DETERMINISTIC:
        trades = det_trades
    elif wallet_id == _sw.WALLET_AI:
        trades = ai_trades
    else:
        trades = engine_trades + det_trades + ai_trades

    resolved_session = session_date
    if latest_session and not session_date:
        resolved_session = latest_session_date_ny()

    if resolved_session:
        def _matches(t: dict) -> bool:
            ts = t.get("exit_time") or t.get("entry_time")
            sd = session_date_for(ts)
            return sd == resolved_session
        trades = [t for t in trades if _matches(t)]

    return {
        "wallet_id": wallet_id,
        "session_date": resolved_session,
        "latest_session": bool(latest_session),
        "count": len(trades),
        "trades": trades,
    }


@router.get("/wallets/performance")
async def paper_wallet_performance(session_date: str | None = None):
    """
    Phase G1B-H4 Part A — per-wallet performance analytics for a given session.

    `session_date` defaults to the latest completed NY trading-session date
    (or pass "latest" explicitly). Returns per-wallet metrics and aggregate
    comparison fields. Fake-money paper simulation only.
    """
    from paper import shadow_wallets as _sw
    from paper import eod as _eod
    from paper.session import (
        latest_session_date_ny,
        session_date_for,
        is_regular_session_now,
    )

    resolved = (
        latest_session_date_ny()
        if (not session_date or session_date == "latest")
        else session_date
    )

    _OOS_REASON = "invalid_out_of_session_entry_flatten"

    def _build(wallet_id: str, trades_all: list, positions_all: list, snap: dict) -> dict:
        session_trades = [
            t for t in trades_all
            if session_date_for(t.get("exit_time") or t.get("entry_time")) == resolved
        ]
        # Split valid vs out-of-session trades (Part F: OOS excluded from normal metrics)
        oos_trades = [t for t in session_trades if t.get("exit_reason") == _OOS_REASON]
        valid_trades = [t for t in session_trades if t.get("exit_reason") != _OOS_REASON]

        valid_pnls = [t.get("pnl") or 0.0 for t in valid_trades]
        wins = [p for p in valid_pnls if p > 0]
        losses = [p for p in valid_pnls if p <= 0]
        realized = round(sum(valid_pnls), 6)
        unrealized = round(
            sum(p.get("unrealized_pnl") or 0.0 for p in positions_all), 6
        )
        total = round(realized + unrealized, 6)
        start = float(snap.get("starting_cash") or 1000.0)
        ret_pct = round(total / start * 100.0, 4) if start else None
        n = len(valid_trades)

        # Raw/audit fields including OOS trades
        all_pnls = [t.get("pnl") or 0.0 for t in session_trades]
        oos_pnls = [t.get("pnl") or 0.0 for t in oos_trades]
        raw_realized = round(sum(all_pnls), 6)
        raw_total = round(raw_realized + unrealized, 6)
        raw_ret_pct = round(raw_total / start * 100.0, 4) if start else None

        last_trade = (
            max((t.get("exit_time") or "" for t in session_trades), default=None) or None
        )
        return {
            "wallet_id": wallet_id,
            "strategy_id": wallet_id,
            "display_name": wallet_id.replace("_", " ").title(),
            "status": snap.get("status", "unknown"),
            "inactive_reason": snap.get("inactive_reason"),
            "session_date": resolved,
            "starting_cash": start,
            "cash": snap.get("cash"),
            "equity": snap.get("equity"),
            # Normal (OOS-excluded) performance metrics
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": total,
            "daily_pnl": snap.get("daily_pnl"),
            "return_percent": ret_pct,
            "open_positions_count": len(positions_all),
            "closed_trades_count": n,
            "winning_trades_count": len(wins),
            "losing_trades_count": len(losses),
            "win_rate": round(len(wins) / n * 100.0, 1) if n else None,
            "avg_trade_pnl": round(sum(valid_pnls) / n, 6) if n else None,
            "best_trade_pnl": round(max(valid_pnls), 6) if valid_pnls else None,
            "worst_trade_pnl": round(min(valid_pnls), 6) if valid_pnls else None,
            "max_drawdown": None,
            "eod_flatten_count": sum(
                1 for t in valid_trades
                if (t.get("exit_reason") or "").startswith("eod_flatten")
            ),
            # OOS audit fields (separate from normal metrics)
            "invalid_out_of_session_count": len(oos_trades),
            "invalid_out_of_session_realized_pnl": round(sum(oos_pnls), 6),
            "raw_realized_pnl_including_invalid": raw_realized,
            "raw_total_pnl_including_invalid": raw_total,
            "raw_return_percent_including_invalid": raw_ret_pct,
            "last_trade_time": last_trade,
            "last_update_time": snap.get("last_update_time"),
        }

    eng_raw = simulator.get_status()
    daily_baseline = eng_raw.get("daily_start_equity") or eng_raw.get("starting_cash")
    eng_daily_pnl = (
        round((eng_raw.get("equity") or 0) - float(daily_baseline), 4)
        if daily_baseline
        else None
    )
    eng_snap = {
        **eng_raw,
        "status": "active",
        "inactive_reason": None,
        "daily_pnl": eng_daily_pnl,
    }
    engine_perf = _build(
        "engine",
        [{**t, "wallet_id": "engine", "strategy_id": "engine"} for t in simulator.get_trades()],
        simulator.get_positions(),
        eng_snap,
    )

    shadow = _sw.snapshot()
    det_perf = _build(
        _sw.WALLET_DETERMINISTIC,
        _sw.get_trades(_sw.WALLET_DETERMINISTIC),
        _sw.get_positions(_sw.WALLET_DETERMINISTIC),
        shadow.get(_sw.WALLET_DETERMINISTIC) or {},
    )
    ai_perf = _build(
        _sw.WALLET_AI,
        _sw.get_trades(_sw.WALLET_AI),
        _sw.get_positions(_sw.WALLET_AI),
        shadow.get(_sw.WALLET_AI) or {},
    )

    all_perfs = [engine_perf, det_perf, ai_perf]
    ranked = sorted(all_perfs, key=lambda w: w["total_pnl"], reverse=True)
    wr_eligible = [w for w in all_perfs if (w["closed_trades_count"] or 0) >= 3]
    best_wr = (
        max(wr_eligible, key=lambda w: w["win_rate"] or 0.0)["wallet_id"]
        if wr_eligible
        else None
    )
    _eb, _ebr = _eod.entries_blocked()
    return {
        "session_date": resolved,
        "wallets": all_perfs,
        "best_wallet_by_total_pnl": ranked[0]["wallet_id"] if ranked else None,
        "best_wallet_by_return_percent": ranked[0]["wallet_id"] if ranked else None,
        "best_wallet_by_win_rate": best_wr,
        "wallets_ranked_by_total_pnl": [w["wallet_id"] for w in ranked],
        "market_session_open": is_regular_session_now(),
        "entries_allowed": not _eb,
        "session_status": _ebr or ("open" if is_regular_session_now() else "closed"),
    }


@router.get("/wallets/analytics")
async def paper_wallet_analytics():
    """
    Phase G1B-H7 Part I — same-structure decision analytics for each engine.

    Returns three analytics objects (engine, deterministic_shadow, ai_shadow)
    with comparable counts so the dashboard can render side-by-side panels
    without falling back to engine-only data for the shadows. Counts come
    from the last tick's candidate list. Fake-money paper simulation only.
    """
    from paper.analytics import get_trade_analytics
    from paper import shadow_wallets as _sw

    state = simulator.get_state()
    candidates = state.get("last_candidates") or []
    status = simulator.get_status()

    engine_analytics = get_trade_analytics(
        status,
        simulator.get_positions(),
        simulator.get_trades(),
        candidates,
        get_cached_universe(),
    )

    def _count(items, key, value):
        return sum(1 for c in items if c.get(key) == value)

    def _top_n(items, key, n=5):
        from collections import Counter
        c = Counter(c.get(key) for c in items if c.get(key))
        return [{"reason": k, "count": v} for k, v in c.most_common(n)]

    det_would_enter = _count(candidates, "enhanced_shadow_decision", "WOULD_ENTER")
    det_watch = _count(candidates, "enhanced_shadow_decision", "WATCH")
    det_would_reject = _count(candidates, "enhanced_shadow_decision", "WOULD_REJECT")
    det_unknown = sum(1 for c in candidates if not c.get("enhanced_shadow_decision"))
    det_scores = [c.get("enhanced_shadow_score") for c in candidates
                  if isinstance(c.get("enhanced_shadow_score"), (int, float))]
    det_avg_score = round(sum(det_scores) / len(det_scores), 2) if det_scores else None

    llm_status_counts = {}
    for c in candidates:
        s = c.get("llm_status") or "not_called"
        llm_status_counts[s] = llm_status_counts.get(s, 0) + 1
    ai_would_enter = _count(candidates, "llm_decision", "WOULD_ENTER")
    ai_watch = _count(candidates, "llm_decision", "WATCH")
    ai_would_reject = _count(candidates, "llm_decision", "WOULD_REJECT")
    ai_disabled = llm_status_counts.get("disabled", 0)
    ai_error = llm_status_counts.get("error", 0)
    ai_not_selected = llm_status_counts.get("not_selected", 0) + llm_status_counts.get("not_called", 0)

    shadow_snap = _sw.snapshot()
    llm_enabled = bool(shadow_snap.get("llm_enabled"))

    common = {
        "session_status": "open" if state else "unknown",
        "candidate_pool_size": len(candidates),
        "data_collected_from": "last_tick_candidates",
        "disclaimer": "Fake-money paper simulation only. No paid AI calls.",
    }

    return {
        "engine": {
            **common,
            "wallet_id": "engine",
            "strategy_id": "engine",
            "kind": "engine",
            "candidate_funnel": engine_analytics.get("candidate_funnel"),
            "score_distribution": engine_analytics.get("score_distribution"),
            "rejections": engine_analytics.get("rejections"),
            "catalysts": engine_analytics.get("catalysts"),
            "performance": engine_analytics.get("performance"),
            "available": True,
            "unavailable_reason": None,
        },
        "deterministic_shadow": {
            **common,
            "wallet_id": _sw.WALLET_DETERMINISTIC,
            "strategy_id": _sw.WALLET_DETERMINISTIC,
            "kind": "deterministic_shadow",
            "would_enter_count": det_would_enter,
            "watch_count": det_watch,
            "would_reject_count": det_would_reject,
            "no_decision_count": det_unknown,
            "average_score": det_avg_score,
            "top_rejection_reasons": _top_n(
                [c for c in candidates if c.get("enhanced_shadow_decision") == "WOULD_REJECT"],
                "enhanced_shadow_reason",
            ),
            "actual_shadow_entries_open": len(_sw.get_positions(_sw.WALLET_DETERMINISTIC)),
            "actual_shadow_trades_closed": len(_sw.get_trades(_sw.WALLET_DETERMINISTIC)),
            "available": shadow_snap.get("enabled", False) or det_would_enter + det_watch + det_would_reject > 0,
            "unavailable_reason": None if shadow_snap.get("enabled") else "shadow_wallets_disabled",
        },
        "ai_shadow": {
            **common,
            "wallet_id": _sw.WALLET_AI,
            "strategy_id": _sw.WALLET_AI,
            "kind": "ai_shadow",
            "llm_enabled": llm_enabled,
            "would_enter_count": ai_would_enter,
            "watch_count": ai_watch,
            "would_reject_count": ai_would_reject,
            "disabled_count": ai_disabled,
            "error_count": ai_error,
            "not_selected_count": ai_not_selected,
            "by_status": llm_status_counts,
            "actual_ai_entries_open": len(_sw.get_positions(_sw.WALLET_AI)),
            "actual_ai_trades_closed": len(_sw.get_trades(_sw.WALLET_AI)),
            "no_paid_ai_calls": True,
            "provider_note": "local/free LLM provider (e.g. Ollama). No external paid-provider billing.",
            "available": llm_enabled or ai_would_enter + ai_watch + ai_would_reject > 0,
            "unavailable_reason": None if llm_enabled else "LLM_SHADOW_ENABLED=false",
        },
    }


@router.get("/universe")
async def paper_universe():
    return await get_active_paper_universe()


@router.post("/universe/refresh")
async def paper_universe_refresh(_: None = Depends(require_admin_token)):
    return await build_dynamic_universe(force_refresh=True)


@router.get("/analytics")
async def paper_analytics():
    status = simulator.get_status()
    return get_trade_analytics(
        status,
        simulator.get_positions(),
        simulator.get_trades(),
        simulator.get_state()["last_candidates"],
        get_cached_universe(),
    )


@router.get("/dashboard")
async def paper_dashboard():
    status = simulator.get_status()
    positions = simulator.get_positions()
    trades = simulator.get_trades()
    candidates = simulator.get_state()["last_candidates"]
    universe = get_cached_universe()

    market_regime = None
    try:
        from core.config import settings
        if settings.MARKET_REGIME_ENABLED:
            from market.regime import get_market_regime
            market_regime = await get_market_regime()
    except Exception:
        pass

    return {
        "status": status,
        "positions": positions,
        "trades": trades,
        "last_candidates": candidates,
        "universe": universe,
        "analytics": get_trade_analytics(status, positions, trades, candidates, universe),
        "market_regime": market_regime,
        "disclaimer": (
            "Research-only fake-money simulation. "
            "No broker. No live trading. No real orders."
        ),
    }


@router.post("/start")
async def paper_start(_: None = Depends(require_admin_token)):
    await simulator.start_simulator()
    return simulator.get_status()


@router.post("/stop")
async def paper_stop(_: None = Depends(require_admin_token)):
    await simulator.stop_simulator()
    return simulator.get_status()


@router.post("/reset")
async def paper_reset(_: None = Depends(require_admin_token)):
    await simulator.reset_simulator()
    return simulator.get_status()


@router.get("/discovery")
async def paper_discovery():
    return await discover_market_movers()


@router.post("/discovery/refresh")
async def paper_discovery_refresh(_: None = Depends(require_admin_token)):
    return await discover_market_movers(force_refresh=True)


@router.post("/tick")
async def paper_tick(_: None = Depends(require_admin_token)):
    tick_result = await simulator.run_tick()
    return {
        "tick": tick_result,
        "status": simulator.get_status(),
    }
