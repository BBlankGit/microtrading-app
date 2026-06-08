"""
Polygon REST data source for the market data collector. Phase D1.
No broker. No live trading. No real orders. No real-money execution.
"""

import logging
from datetime import datetime, timezone

from core.config import settings
from data import polygon_client
from data.schemas import normalize_bulk_ticker_entry
from marketdata.models import SymbolPayload, make_error_payload

logger = logging.getLogger(__name__)


def _snap_to_payload(snap: dict, ttl: int) -> SymbolPayload:
    """Convert a normalized snapshot dict to a SymbolPayload."""
    symbol = snap.get("symbol", "")
    last_trade = snap.get("last_trade") or {}
    last_quote = snap.get("last_quote") or {}
    day = snap.get("day") or {}
    prev_day = snap.get("prev_day") or {}

    last_price: float | None = last_trade.get("price")
    bid: float | None = last_quote.get("bid")
    ask: float | None = last_quote.get("ask")

    spread_percent: float | None = None
    if bid and ask and bid > 0 and ask > bid:
        mid = (bid + ask) / 2.0
        spread_percent = round((ask - bid) / mid * 100, 4)

    now_iso = datetime.now(timezone.utc).isoformat()

    return SymbolPayload(
        symbol=symbol.upper(),
        source="polygon",
        as_of=now_iso,
        fetched_at=now_iso,
        ttl_seconds=ttl,
        last_price=last_price,
        bid=bid,
        ask=ask,
        spread_percent=spread_percent,
        day_volume=day.get("volume"),
        volume_ratio=None,
        change_percent=snap.get("change_percent"),
        prev_close=prev_day.get("close"),
        minute_high=None,
        minute_low=None,
        minute_close=None,
        raw_status="ok",
        error=None,
    )


async def fetch_bulk_snapshots(symbols: list[str], ttl: int) -> list[SymbolPayload]:
    """
    Fetch snapshots for all symbols in one Polygon bulk request.
    Returns one SymbolPayload per symbol that Polygon returns data for.
    Raises PolygonError / Exception on network or API failure — caller handles retry.
    No broker. Research only.
    """
    if not symbols:
        return []
    raw_tickers = await polygon_client.get_bulk_ticker_snapshots(
        symbols,
        timeout=settings.MARKETDATA_REQUEST_TIMEOUT_SECONDS,
    )
    payloads: list[SymbolPayload] = []
    for entry in raw_tickers:
        try:
            snap = normalize_bulk_ticker_entry(entry)
            payloads.append(_snap_to_payload(snap, ttl))
        except Exception as exc:
            sym = entry.get("ticker", "?")
            logger.debug("normalize failed for %s: %s", sym, exc)
            payloads.append(make_error_payload(sym, str(exc), ttl))
    return payloads
