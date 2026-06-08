import re
from typing import Any

import httpx

from core.config import settings
from data.schemas import normalize_mover_snapshot, normalize_news_item, normalize_previous_close, normalize_snapshot

_BASE_URL = "https://api.polygon.io"
_TIMEOUT = 10.0
_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")


class PolygonError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def _assert_configured() -> None:
    if not settings.polygon_configured():
        raise PolygonError("Polygon API key is not configured. Set POLYGON_API_KEY in .env.")


def _validate_symbol(symbol: str) -> str:
    upper = symbol.upper().strip()
    if not _SYMBOL_RE.match(upper):
        raise PolygonError(f"Invalid symbol format: '{symbol}'. Must be 1-5 uppercase letters.")
    return upper


def _auth_params() -> dict[str, str]:
    return {"apiKey": settings.POLYGON_API_KEY}


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = {**(params or {}), **_auth_params()}
    try:
        async with httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT) as client:
            response = await client.get(path, params=merged)
    except httpx.TimeoutException:
        raise PolygonError(f"Polygon request timed out after {_TIMEOUT}s: {path}")
    except httpx.RequestError as exc:
        raise PolygonError(f"Polygon network error: {exc}")

    if response.status_code == 403:
        raise PolygonError("Polygon API key is invalid or unauthorized.", status_code=403)
    if response.status_code == 404:
        raise PolygonError(f"Polygon returned 404 for path: {path}", status_code=404)
    if response.status_code != 200:
        body = response.text[:200]
        raise PolygonError(
            f"Polygon returned HTTP {response.status_code}: {body}",
            status_code=response.status_code,
        )

    data = response.json()
    # Polygon uses "status": "ERROR" in some 200 payloads
    if data.get("status") == "ERROR":
        raise PolygonError(f"Polygon error payload: {data.get('error', data.get('message', 'unknown'))}")

    return data


def is_configured() -> bool:
    return settings.polygon_configured()


async def get_ticker_snapshot(symbol: str) -> dict[str, Any]:
    _assert_configured()
    sym = _validate_symbol(symbol)
    raw = await _get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{sym}")
    return normalize_snapshot(raw, sym)


async def get_previous_close(symbol: str) -> dict[str, Any]:
    _assert_configured()
    sym = _validate_symbol(symbol)
    raw = await _get(f"/v2/aggs/ticker/{sym}/prev", params={"adjusted": "true"})
    return normalize_previous_close(raw, sym)


async def get_market_movers(direction: str) -> list[dict[str, Any]]:
    """
    Fetch top gainers or losers from Polygon.
    direction must be 'gainers' or 'losers'.
    Returns list of normalized mover dicts. Never returns raw Polygon payload.
    """
    _assert_configured()
    if direction not in ("gainers", "losers"):
        raise PolygonError(f"Invalid mover direction: '{direction}'. Must be 'gainers' or 'losers'.")
    raw = await _get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")
    tickers = raw.get("tickers", [])
    return [normalize_mover_snapshot(t, direction) for t in tickers]


async def get_recent_minute_bars(
    symbol: str,
    date_str: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Fetch recent 1-minute OHLCV bars for symbol on date_str.
    Returns list sorted ascending by bar start timestamp.
    Used only for open-position intrabar TP/SL detection (Phase 2Q-Lite).
    No broker. Research only.
    """
    _assert_configured()
    sym = _validate_symbol(symbol)
    limit = max(1, min(limit, 10))
    raw = await _get(
        f"/v2/aggs/ticker/{sym}/range/1/minute/{date_str}/{date_str}",
        params={"adjusted": "true", "sort": "desc", "limit": limit},
    )
    results = raw.get("results") or []
    return sorted(results, key=lambda b: b.get("t", 0))


async def get_bulk_ticker_snapshots(symbols: list[str]) -> list[dict[str, Any]]:
    """
    Fetch snapshots for multiple tickers in one Polygon request.
    Returns list of raw ticker objects (same structure as the ticker field in single-ticker snapshot).
    Phase D1: market data collector bulk fetch.
    """
    _assert_configured()
    if not symbols:
        return []
    tickers_str = ",".join(s.upper() for s in symbols[:200])
    raw = await _get(
        "/v2/snapshot/locale/us/markets/stocks/tickers",
        params={"tickers": tickers_str},
    )
    return raw.get("tickers", [])


async def get_ticker_news(symbol: str, limit: int = 10) -> list[dict[str, Any]]:
    _assert_configured()
    sym = _validate_symbol(symbol)
    limit = max(1, min(limit, 50))
    raw = await _get("/v2/reference/news", params={"ticker": sym, "limit": limit, "order": "desc"})
    items = raw.get("results", [])
    return [normalize_news_item(item) for item in items]
