from fastapi import APIRouter, Depends

from api.dependencies import require_admin_token
from paper import simulator
from paper.analytics import get_trade_analytics
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


@router.post("/tick")
async def paper_tick(_: None = Depends(require_admin_token)):
    tick_result = await simulator.run_tick()
    return {
        "tick": tick_result,
        "status": simulator.get_status(),
    }
