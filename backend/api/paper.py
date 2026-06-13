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
    """
    from paper import shadow_wallets as _sw
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
    }


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
    if wallet_id == "engine":
        positions, warnings = _annotate_stale_overnight(engine_positions)
        return {"wallet_id": "engine", "positions": positions, "warnings": warnings}
    if wallet_id == _sw.WALLET_DETERMINISTIC:
        positions, warnings = _annotate_stale_overnight(
            _sw.get_positions(_sw.WALLET_DETERMINISTIC)
        )
        return {
            "wallet_id": _sw.WALLET_DETERMINISTIC,
            "positions": positions,
            "warnings": warnings,
        }
    if wallet_id == _sw.WALLET_AI:
        positions, warnings = _annotate_stale_overnight(
            _sw.get_positions(_sw.WALLET_AI)
        )
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
    positions, warnings = _annotate_stale_overnight(all_positions)
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
