from fastapi import APIRouter, HTTPException, Query

from data.universe import DEFAULT_UNIVERSE
from catalysts.news_collector import collect_news_for_symbols

router = APIRouter(prefix="/api/catalysts")

_MAX_SYMBOLS = 25


@router.get("/news/default")
async def catalysts_news_default(
    apply_filter: bool = Query(default=False),
    max_age_hours: int = Query(default=24, ge=1, le=168),
):
    return await collect_news_for_symbols(
        DEFAULT_UNIVERSE,
        limit_per_symbol=5,
        apply_filter=apply_filter,
        max_age_hours=max_age_hours,
    )


@router.get("/news/check")
async def catalysts_news_check(
    symbols: str = Query(..., description="Comma-separated ticker list"),
    limit: int = Query(default=5, ge=1, le=20),
    apply_filter: bool = Query(default=False),
    max_age_hours: int = Query(default=24, ge=1, le=168),
):
    parts = [s.strip().upper() for s in symbols.split(",")]
    valid = [s for s in parts if s]

    if not valid:
        raise HTTPException(status_code=400, detail="No valid symbols provided.")

    if len(valid) > _MAX_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Symbol list exceeds maximum of {_MAX_SYMBOLS}.",
        )

    return await collect_news_for_symbols(
        valid,
        limit_per_symbol=limit,
        apply_filter=apply_filter,
        max_age_hours=max_age_hours,
    )
