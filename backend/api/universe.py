from fastapi import APIRouter, HTTPException, Query

from data.universe import build_universe

router = APIRouter(prefix="/api/universe")

_MAX_SYMBOLS = 25


@router.get("/default")
async def universe_default():
    return await build_universe()


@router.get("/check")
async def universe_check(
    symbols: str = Query(..., description="Comma-separated list of ticker symbols"),
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

    return await build_universe(valid)
