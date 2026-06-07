import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from core.config import settings
from data import polygon_client
from data.polygon_client import PolygonError
from data.market_quality import evaluate_market_quality

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE: list[str] = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMD",
    "META", "AMZN", "GOOGL", "PLTR", "SOFI",
]

_REDIS_KEY = "universe:latest"
_REDIS_TTL = 300


async def _evaluate_symbol(symbol: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Fetch and quality-evaluate one symbol. Never raises — errors are returned as strings."""
    try:
        snapshot = await polygon_client.get_ticker_snapshot(symbol)
        previous_close = await polygon_client.get_previous_close(symbol)
        return symbol, evaluate_market_quality(snapshot, previous_close), None
    except PolygonError as exc:
        return symbol, None, str(exc)
    except Exception as exc:
        return symbol, None, f"{type(exc).__name__}: {exc}"


async def build_universe(symbols: list[str] | None = None) -> dict[str, Any]:
    """
    Evaluate each symbol against the market quality gate.

    Uses DEFAULT_UNIVERSE when symbols is None.
    Continues processing remaining symbols if any individual symbol fails.
    Caches the result in Redis under universe:latest (best-effort, TTL 300s).
    """
    targets = symbols if symbols is not None else DEFAULT_UNIVERSE

    outcomes = await asyncio.gather(*[_evaluate_symbol(sym) for sym in targets])

    tradable: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for sym, quality, error in outcomes:
        if error is not None:
            errors.append({"symbol": sym, "error": error})
        elif quality["tradable"]:
            tradable.append(quality)
        else:
            rejected.append(quality)

    result: dict[str, Any] = {
        "total": len(targets),
        "tradable_count": len(tradable),
        "rejected_count": len(rejected),
        "error_count": len(errors),
        "tradable": tradable,
        "rejected": rejected,
        "errors": errors,
    }

    # Best-effort Redis cache — never fail the caller if Redis is unavailable
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.setex(_REDIS_KEY, _REDIS_TTL, json.dumps(result))
        await r.aclose()
    except Exception as exc:
        logger.warning("Universe Redis cache write failed: %s", exc)

    return result
