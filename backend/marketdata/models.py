"""
Market data payload models. Phase D1.
No broker. No live trading. No real orders. No real-money execution.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class SymbolPayload:
    symbol: str
    source: str                # "polygon"
    as_of: str                 # ISO UTC — data timestamp
    fetched_at: str            # ISO UTC — when we fetched it
    ttl_seconds: int
    last_price: float | None
    bid: float | None
    ask: float | None
    spread_percent: float | None
    day_volume: float | None
    volume_ratio: float | None  # requires avg volume — None in D1
    change_percent: float | None
    prev_close: float | None
    minute_high: float | None   # from 1-min agg; None in D1 bulk-only path
    minute_low: float | None
    minute_close: float | None
    raw_status: str            # "ok" | "stale" | "error"
    error: str | None
    prev_day_volume: float | None = None  # previous session volume; populated D2+

    def to_dict(self) -> dict:
        return asdict(self)

    def is_fresh(self) -> bool:
        try:
            fetched = datetime.fromisoformat(self.fetched_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - fetched).total_seconds()
            return age <= self.ttl_seconds
        except Exception:
            return False


def make_error_payload(symbol: str, error: str, ttl: int) -> SymbolPayload:
    now = datetime.now(timezone.utc).isoformat()
    return SymbolPayload(
        symbol=symbol.upper(),
        source="polygon",
        as_of=now,
        fetched_at=now,
        ttl_seconds=ttl,
        last_price=None,
        bid=None,
        ask=None,
        spread_percent=None,
        day_volume=None,
        volume_ratio=None,
        change_percent=None,
        prev_close=None,
        minute_high=None,
        minute_low=None,
        minute_close=None,
        raw_status="error",
        error=error,
    )
