from fastapi import APIRouter

from core.config import settings
from data import polygon_client

router = APIRouter()


@router.get("/api/data/status")
async def data_status():
    result = {
        "polygon_configured": polygon_client.is_configured(),
        "trading_mode": settings.TRADING_MODE,
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "message": (
            "Data layer initialized. "
            "Polygon REST connectivity available if API key is configured."
        ),
    }
    if settings.EXPOSE_KEY_PREVIEW:
        result["polygon_key_preview"] = settings.polygon_key_preview()
    return result
