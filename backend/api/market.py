from fastapi import APIRouter, HTTPException, Query

from data import polygon_client
from data.polygon_client import PolygonError

router = APIRouter(prefix="/api/market")


def _polygon_error_to_http(exc: PolygonError) -> HTTPException:
    code = exc.status_code or 502
    if code == 404:
        return HTTPException(status_code=404, detail=str(exc))
    if code == 403:
        return HTTPException(status_code=503, detail="Polygon API key invalid or unauthorized.")
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/ticker/{symbol}/snapshot")
async def ticker_snapshot(symbol: str):
    sym = symbol.upper().strip()
    try:
        return await polygon_client.get_ticker_snapshot(sym)
    except PolygonError as exc:
        raise _polygon_error_to_http(exc)


@router.get("/ticker/{symbol}/previous-close")
async def ticker_previous_close(symbol: str):
    sym = symbol.upper().strip()
    try:
        return await polygon_client.get_previous_close(sym)
    except PolygonError as exc:
        raise _polygon_error_to_http(exc)


@router.get("/ticker/{symbol}/news")
async def ticker_news(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=50),
):
    sym = symbol.upper().strip()
    try:
        return {"symbol": sym, "results": await polygon_client.get_ticker_news(sym, limit)}
    except PolygonError as exc:
        raise _polygon_error_to_http(exc)
