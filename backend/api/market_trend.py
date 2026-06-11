"""
Market trend API — ETF-proxy rolling trend layer (Phase M1).

Read-only observational. No broker. No live trading. No real orders.
No AI/LLM.

True Nasdaq/SPX futures are NOT supported here. Provider status is fixed
to "using_etf_proxy" and futures_available is always false in this phase.
"""
from fastapi import APIRouter

from market import trend as _trend
from market.regime import get_market_regime as _get_regime

router = APIRouter(prefix="/api/market/trend", tags=["market_trend"])


@router.get("")
async def get_market_trend():
    """
    Return the latest market trend snapshot + 5/10/15-minute deltas.

    Calls the cached regime fetcher to ensure the latest snapshot is
    recorded into the rolling history before computing trend.
    """
    # Ensure the trend buffer has the freshest snapshot we can offer.
    try:
        await _get_regime()
    except Exception:
        pass
    return _trend.get_trend()
