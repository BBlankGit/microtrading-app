import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from core.config import settings
from data import polygon_client
from data.polygon_client import PolygonError
from catalysts.filters import filter_catalysts
from catalysts.schemas import normalize_news_catalyst

logger = logging.getLogger(__name__)

_MAX_SYMBOLS = 25
_MAX_LIMIT = 20
_REDIS_KEY = "catalysts:latest"
_REDIS_TTL = 300


async def _collect_symbol(symbol: str, limit: int) -> tuple[str, list[dict[str, Any]], str | None]:
    """Fetch and normalize news for one symbol. Never raises — errors returned as strings."""
    try:
        news_items = await polygon_client.get_ticker_news(symbol, limit)
        catalysts = [normalize_news_catalyst(symbol, item) for item in news_items]
        return symbol, catalysts, None
    except PolygonError as exc:
        return symbol, [], str(exc)
    except Exception as exc:
        return symbol, [], f"{type(exc).__name__}: {exc}"


async def collect_news_for_symbols(
    symbols: list[str],
    limit_per_symbol: int = 5,
    apply_filter: bool = False,
    max_age_hours: int = 24,
) -> dict[str, Any]:
    """
    Collect recent news catalysts for a list of symbols.

    Deduplicates and uppercases symbols. Caps at _MAX_SYMBOLS.
    Continues processing remaining symbols if any individual symbol fails.
    When apply_filter=True, runs deterministic freshness/relevance filtering
    and adds a 'filter' key to the result.
    Caches result in Redis under catalysts:latest (best-effort, TTL 300s).
    """
    seen: set[str] = set()
    clean: list[str] = []
    for sym in symbols:
        upper = sym.upper().strip()
        if upper and upper not in seen:
            seen.add(upper)
            clean.append(upper)
    clean = clean[:_MAX_SYMBOLS]

    limit = max(1, min(limit_per_symbol, _MAX_LIMIT))

    outcomes = await asyncio.gather(*[_collect_symbol(sym, limit) for sym in clean])

    all_catalysts: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for sym, catalysts, error in outcomes:
        if error is not None:
            errors.append({"symbol": sym, "error": error})
        else:
            all_catalysts.extend(catalysts)

    result: dict[str, Any] = {
        "symbols_requested": clean,
        "total_catalysts": len(all_catalysts),
        "catalysts": all_catalysts,
        "errors": errors,
    }

    if apply_filter:
        result["filter"] = filter_catalysts(all_catalysts, max_age_hours)

    # Best-effort Redis cache — never fail the caller if Redis is unavailable
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.setex(_REDIS_KEY, _REDIS_TTL, json.dumps(result))
        await r.aclose()
    except Exception as exc:
        logger.warning("Catalysts Redis cache write failed: %s", exc)

    return result
