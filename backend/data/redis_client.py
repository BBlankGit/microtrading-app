import logging
from urllib.parse import urlparse
from typing import Any

import redis.asyncio as aioredis

from core.config import settings

logger = logging.getLogger(__name__)


def redis_url_configured() -> bool:
    return bool(settings.REDIS_URL and settings.REDIS_URL.strip())


def redis_url_valid() -> bool:
    if not redis_url_configured():
        return False
    try:
        parsed = urlparse(settings.REDIS_URL)
        return parsed.scheme in ("redis", "rediss")
    except Exception:
        return False


async def redis_ping_status() -> dict[str, Any]:
    """Return a connectivity status dict. Never raises."""
    if not redis_url_configured() or not redis_url_valid():
        return {"redis_connected": False, "redis_error": "REDIS_URL is missing or invalid"}
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.ping()
        return {"redis_connected": True, "redis_error": None}
    except Exception as exc:
        return {"redis_connected": False, "redis_error": str(exc)}
    finally:
        await r.aclose()


def make_redis() -> aioredis.Redis:
    """
    Create a Redis client from the configured URL.

    Raises ValueError if REDIS_URL is missing or invalid.
    Best-effort cache callers should wrap in try/except Exception.
    """
    if not redis_url_configured() or not redis_url_valid():
        raise ValueError("REDIS_URL is missing or invalid")
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)
