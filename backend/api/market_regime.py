"""
Market regime API — observational only.
No broker. No live trading. No real orders. No real-money execution.
Provides read-only access to market breadth/risk context data.
"""

from fastapi import APIRouter, Depends

from api.dependencies import require_admin_token
from core.config import settings
from paper.runtime_config import effective_value as _cfg

router = APIRouter(prefix="/api/market/regime", tags=["market_regime"])


@router.get("")
async def get_market_regime():
    """
    Return current market regime data (cached, refreshes on TTL expiry).
    No auth required — read-only observational data.
    """
    if not _cfg("MARKET_REGIME_ENABLED"):
        return {
            "enabled": False,
            "regime": None,
            "risk_on_score": None,
            "confidence": None,
            "as_of": None,
            "disclaimer": "Market regime monitor is disabled (MARKET_REGIME_ENABLED=False).",
        }
    from market.regime import get_market_regime as _get_regime
    data = await _get_regime()
    return {**data, "enabled": True}


@router.post("/refresh")
async def refresh_market_regime(_: None = Depends(require_admin_token)):
    """
    Force-refresh cached market regime data.
    Requires ADMIN_API_TOKEN.
    """
    if not _cfg("MARKET_REGIME_ENABLED"):
        return {
            "enabled": False,
            "refreshed": False,
            "reason": "Market regime monitor is disabled.",
        }
    from market.regime import get_market_regime as _get_regime
    data = await _get_regime(force_refresh=True)
    return {**data, "enabled": True, "refreshed": True}
