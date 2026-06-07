import json

from fastapi import APIRouter, HTTPException

import redis.asyncio as aioredis

from core.config import settings
from data import polygon_ws

router = APIRouter(prefix="/api/stream")


def _make_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def _redis_connected() -> bool:
    r = _make_redis()
    try:
        await r.ping()
        return True
    except Exception:
        return False
    finally:
        await r.aclose()


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
    status["redis_connected"] = await _redis_connected()
    return status


@router.post("/start")
async def stream_start():
    try:
        await polygon_ws.start_stream()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    status = _build_status()
    status["redis_connected"] = await _redis_connected()
    return status


@router.post("/stop")
async def stream_stop():
    await polygon_ws.stop_stream()
    status = _build_status()
    status["redis_connected"] = await _redis_connected()
    return status


@router.get("/latest/{symbol}")
async def stream_latest(symbol: str):
    sym = symbol.upper().strip()
    r = _make_redis()
    try:
        trade_raw = await r.get(f"stream:latest:{sym}:trade")
        quote_raw = await r.get(f"stream:latest:{sym}:quote")
        agg_raw = await r.get(f"stream:latest:{sym}:aggregate")
    finally:
        await r.aclose()

    return {
        "symbol": sym,
        "trade": json.loads(trade_raw) if trade_raw else None,
        "quote": json.loads(quote_raw) if quote_raw else None,
        "aggregate": json.loads(agg_raw) if agg_raw else None,
    }
