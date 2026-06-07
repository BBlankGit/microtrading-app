from fastapi import APIRouter, HTTPException

from data import polygon_client
from data.polygon_client import PolygonError
from data.market_quality import evaluate_market_quality

router = APIRouter(prefix="/api/quality")


def _polygon_error_to_http(exc: PolygonError) -> HTTPException:
    code = exc.status_code or 502
    if code == 404:
        return HTTPException(status_code=404, detail=str(exc))
    if code == 403:
        return HTTPException(status_code=503, detail="Polygon API key invalid or unauthorized.")
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/ticker/{symbol}")
async def ticker_quality(symbol: str):
    sym = symbol.upper().strip()
    try:
        snapshot = await polygon_client.get_ticker_snapshot(sym)
        previous_close = await polygon_client.get_previous_close(sym)
    except PolygonError as exc:
        raise _polygon_error_to_http(exc)
    return evaluate_market_quality(snapshot, previous_close)
