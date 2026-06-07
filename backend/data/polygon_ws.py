import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from core.config import settings
from data.stream_normalizer import normalize_message

logger = logging.getLogger(__name__)

_WS_URL = "wss://socket.polygon.io/stocks"
_TEST_SYMBOLS: list[str] = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"]
_MAX_RECONNECT_DELAY = 30
_REDIS_TTL = 300  # seconds — stream data expires after 5 minutes at rest

_state: dict[str, Any] = {
    "running": False,
    "connected": False,
    "subscribed_symbols": [],
    "last_message_at": None,
    "messages_received": 0,
    "last_error": None,
}

_stream_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def get_state() -> dict[str, Any]:
    # Sync running flag if task finished unexpectedly
    if _stream_task is not None and _stream_task.done():
        _state["running"] = False
        _state["connected"] = False
    return dict(_state)


def _make_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _subscribe_params(symbols: list[str]) -> str:
    # AM (minute aggregates) requires a higher Polygon plan tier; T and Q are standard.
    channels: list[str] = []
    for sym in symbols:
        channels.extend([f"T.{sym}", f"Q.{sym}"])
    return ",".join(channels)


async def _redis_store(redis: aioredis.Redis, key: str, value: dict[str, Any]) -> None:
    try:
        await redis.setex(key, _REDIS_TTL, json.dumps(value))
    except Exception as exc:
        logger.warning("Redis write failed for %s: %s", key, exc)


async def _process_messages(redis: aioredis.Redis, raw: str) -> None:
    try:
        messages = json.loads(raw)
    except json.JSONDecodeError:
        return

    if not isinstance(messages, list):
        messages = [messages]

    for msg in messages:
        ev = msg.get("ev")

        if ev == "status":
            logger.info("Polygon WS status: %s — %s", msg.get("status"), msg.get("message", ""))
            continue

        normalized = normalize_message(msg)
        if normalized is None:
            continue

        symbol = normalized.get("symbol")
        event_type = normalized.get("event_type")
        if not symbol or not event_type:
            continue

        await _redis_store(redis, f"stream:latest:{symbol}:{event_type}", normalized)
        _state["messages_received"] += 1
        _state["last_message_at"] = datetime.now(timezone.utc).isoformat()


async def _stream_loop(symbols: list[str]) -> None:
    reconnect_delay = 1

    while not _stop_event.is_set():
        redis = _make_redis()
        try:
            logger.info("Connecting to Polygon WebSocket...")
            async with websockets.connect(
                _WS_URL,
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                reconnect_delay = 1

                # Consume the initial "connected" status frame
                await asyncio.wait_for(ws.recv(), timeout=10.0)

                # Authenticate — never log the key
                await ws.send(json.dumps({"action": "auth", "params": settings.POLYGON_API_KEY}))

                auth_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                auth_msgs = json.loads(auth_raw)
                if not isinstance(auth_msgs, list):
                    auth_msgs = [auth_msgs]

                authed = any(
                    m.get("ev") == "status" and m.get("status") == "auth_success"
                    for m in auth_msgs
                )
                if not authed:
                    err = next(
                        (m.get("message", "Auth failed") for m in auth_msgs if m.get("ev") == "status"),
                        "Auth failed",
                    )
                    _state["last_error"] = err
                    _state["connected"] = False
                    logger.error("Polygon WS auth failed: %s", err)
                    break  # Permanent failure — do not retry

                _state["connected"] = True
                _state["last_error"] = None
                logger.info("Polygon WS authenticated. Subscribing to %s", symbols)

                # Subscribe to T/Q channels for each symbol. AM aggregates are planned for a later phase.
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "params": _subscribe_params(symbols),
                }))
                _state["subscribed_symbols"] = list(symbols)

                # Main receive loop — 5 s timeout so stop_event is checked promptly
                while not _stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        await _process_messages(redis, raw)
                    except asyncio.TimeoutError:
                        continue

        except ConnectionClosed as exc:
            _state["connected"] = False
            _state["last_error"] = f"Connection closed: {exc}"
            # 1008 = policy violation — plan doesn't support this subscription; stop retrying
            rcvd = getattr(exc, "rcvd", None)
            if rcvd is not None and getattr(rcvd, "code", None) == 1008:
                logger.error("Polygon WS 1008 policy violation — check plan tier. Stopping stream.")
                break
            logger.warning("Polygon WS closed: %s", exc)

        except WebSocketException as exc:
            _state["connected"] = False
            _state["last_error"] = f"WebSocket error: {exc}"
            logger.warning("Polygon WS error: %s", exc)

        except asyncio.TimeoutError:
            _state["connected"] = False
            _state["last_error"] = "Connection timed out during handshake"
            logger.warning("Polygon WS handshake timed out")

        except Exception as exc:
            _state["connected"] = False
            _state["last_error"] = f"{type(exc).__name__}: {exc}"
            logger.error("Stream error: %s", exc, exc_info=True)

        finally:
            await redis.aclose()
            _state["connected"] = False

        if _stop_event.is_set():
            break

        logger.info("Reconnecting in %ds...", reconnect_delay)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=float(reconnect_delay))
        except asyncio.TimeoutError:
            pass
        reconnect_delay = min(reconnect_delay * 2, _MAX_RECONNECT_DELAY)

    _state["running"] = False
    _state["connected"] = False
    _state["subscribed_symbols"] = []
    logger.info("Stream loop finished.")


async def start_stream(symbols: list[str] | None = None) -> None:
    global _stream_task, _stop_event

    if _state["running"]:
        return

    # Clean up a finished task before starting a new one
    if _stream_task is not None and _stream_task.done():
        _stream_task = None
        _stop_event = None

    if not settings.polygon_configured():
        raise RuntimeError("POLYGON_API_KEY is not configured.")

    _stop_event = asyncio.Event()
    _state.update({
        "running": True,
        "connected": False,
        "subscribed_symbols": [],
        "messages_received": 0,
        "last_message_at": None,
        "last_error": None,
    })

    _stream_task = asyncio.create_task(_stream_loop(symbols or _TEST_SYMBOLS))
    logger.info("Stream task started.")


async def stop_stream() -> None:
    global _stream_task, _stop_event

    if not _state["running"] and (_stream_task is None or _stream_task.done()):
        return

    if _stop_event:
        _stop_event.set()

    if _stream_task and not _stream_task.done():
        try:
            # Shield so a request cancellation doesn't interrupt the wait
            await asyncio.wait_for(asyncio.shield(_stream_task), timeout=8.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _stream_task.cancel()
            try:
                await _stream_task
            except asyncio.CancelledError:
                pass

    _stream_task = None
    _stop_event = None
    _state["running"] = False
    _state["connected"] = False
    _state["subscribed_symbols"] = []
    logger.info("Stream stopped.")
