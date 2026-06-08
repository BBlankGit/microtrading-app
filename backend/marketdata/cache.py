"""
Redis cache layer for market data. Phase D1 / D1-H1.
All keys are namespaced under "market:".
Redis connections are always closed in finally blocks to prevent leaks.
No broker. No live trading. No real orders. No real-money execution.
"""

import json
import logging

logger = logging.getLogger(__name__)

# ── Key constants ─────────────────────────────────────────────────────────────
KEY_SNAPSHOT = "market:snapshot:{}"
KEY_SYMBOLS_ACTIVE = "market:symbols:active"
KEY_METRICS = "market:metrics"
KEY_HEALTH = "market:health"


def snapshot_key(symbol: str) -> str:
    return KEY_SNAPSHOT.format(symbol.upper())


# ── Batch write (one connection per collector cycle) ──────────────────────────

async def write_cycle_results(
    payload_dicts: list[dict],
    metrics: dict,
    ttl: int,
) -> None:
    """
    Write all symbol payloads + active symbol list + metrics in one Redis connection.
    Called once per collector cycle. Safe to call with an empty list.
    Connection is always closed in a finally block.
    """
    r = None
    try:
        from data.redis_client import make_redis
        r = make_redis()
        for p in payload_dicts:
            sym = p.get("symbol", "").upper()
            if sym:
                await r.set(snapshot_key(sym), json.dumps(p), ex=ttl)
        if payload_dicts:
            await r.set(
                KEY_SYMBOLS_ACTIVE,
                json.dumps([p["symbol"] for p in payload_dicts]),
                ex=300,
            )
        await r.set(KEY_METRICS, json.dumps(metrics), ex=120)
    except Exception as exc:
        logger.warning("cache write_cycle_results failed: %s", exc)
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


# ── Individual reads (used by API endpoints, one connection per call) ─────────

async def read_symbol(symbol: str) -> dict | None:
    r = None
    try:
        from data.redis_client import make_redis
        r = make_redis()
        data = await r.get(snapshot_key(symbol))
        return json.loads(data) if data else None
    except Exception as exc:
        logger.debug("cache read_symbol failed for %s: %s", symbol, exc)
        return None
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


async def read_active_symbols() -> list[str]:
    r = None
    try:
        from data.redis_client import make_redis
        r = make_redis()
        data = await r.get(KEY_SYMBOLS_ACTIVE)
        return json.loads(data) if data else []
    except Exception:
        return []
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


async def read_metrics() -> dict | None:
    r = None
    try:
        from data.redis_client import make_redis
        r = make_redis()
        data = await r.get(KEY_METRICS)
        return json.loads(data) if data else None
    except Exception:
        return None
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
