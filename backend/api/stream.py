import json

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin_token
from data import polygon_ws
from data.redis_client import make_redis, redis_ping_status, redis_url_valid

router = APIRouter(prefix="/api/stream")


def _build_status() -> dict:
    state = polygon_ws.get_state()
    return {
        "running": state["running"],
        "connected": state["connected"],
        "subscribed_symbols": state["subscribed_symbols"],
        "last_message_at": state["last_message_at"],
        "messages_received": state["messages_received"],
        "last_error": state["last_error"],
        "live_trading_enabled": False,
    }


@router.get("/status")
async def stream_status():
    status = _build_status()
    ping = await redis_ping_status()
    status["redis_connected"] = ping["redis_connected"]
    if not ping["redis_connected"] and ping.get("redis_error"):
        status["redis_error"] = ping["redis_error"]
    return status


@router.post("/start")
async def stream_start(_: None = Depends(require_admin_token)):
    try:
        await polygon_ws.start_stream()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    status = _build_status()
    ping = await redis_ping_status()
    status["redis_connected"] = ping["redis_connected"]
    return status


@router.post("/stop")
async def stream_stop(_: None = Depends(require_admin_token)):
    await polygon_ws.stop_stream()
    status = _build_status()
    ping = await redis_ping_status()
    status["redis_connected"] = ping["redis_connected"]
    return status


@router.get("/latest/{symbol}")
async def stream_latest(symbol: str):
    sym = symbol.upper().strip()
    if not redis_url_valid():
        raise HTTPException(
            status_code=503,
            detail="Redis is not available. Configure REDIS_URL to use stream data.",
        )
    r = make_redis()
    try:
        trade_raw = await r.get(f"stream:latest:{sym}:trade")
        quote_raw = await r.get(f"stream:latest:{sym}:quote")
        agg_raw = await r.get(f"stream:latest:{sym}:aggregate")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis error: {exc}")
    finally:
        await r.aclose()

    return {
        "symbol": sym,
        "trade": json.loads(trade_raw) if trade_raw else None,
        "quote": json.loads(quote_raw) if quote_raw else None,
        "aggregate": json.loads(agg_raw) if agg_raw else None,
    }
