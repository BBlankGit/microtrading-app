from fastapi import APIRouter, Depends

from api.dependencies import require_admin_token
from paper import simulator

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


@router.get("/dashboard")
async def paper_dashboard():
    return {
        "status": simulator.get_status(),
        "positions": simulator.get_positions(),
        "trades": simulator.get_trades(),
        "last_candidates": simulator.get_state()["last_candidates"],
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
