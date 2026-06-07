from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_trade(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": msg.get("sym"),
        "event_type": "trade",
        "raw_event_type": msg.get("ev"),
        "received_at": _now_iso(),
        "source": "polygon_ws",
        "price": msg.get("p"),
        "size": msg.get("s"),
        "timestamp": msg.get("t"),
        "exchange_id": msg.get("x"),
        "conditions": msg.get("c", []),
    }


def normalize_quote(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": msg.get("sym"),
        "event_type": "quote",
        "raw_event_type": msg.get("ev"),
        "received_at": _now_iso(),
        "source": "polygon_ws",
        "bid": msg.get("bp"),
        "ask": msg.get("ap"),
        "bid_size": msg.get("bs"),
        "ask_size": msg.get("as"),
        "timestamp": msg.get("t"),
        "bid_exchange_id": msg.get("bx"),
        "ask_exchange_id": msg.get("ax"),
    }


def normalize_aggregate(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": msg.get("sym"),
        "event_type": "aggregate",
        "raw_event_type": msg.get("ev"),
        "received_at": _now_iso(),
        "source": "polygon_ws",
        "open": msg.get("o"),
        "high": msg.get("h"),
        "low": msg.get("l"),
        "close": msg.get("c"),
        "volume": msg.get("v"),
        "accumulated_volume": msg.get("av"),
        "vwap": msg.get("vw"),
        "start_timestamp": msg.get("s"),
        "end_timestamp": msg.get("e"),
    }


_NORMALIZERS = {
    "T": normalize_trade,
    "Q": normalize_quote,
    "AM": normalize_aggregate,
}


def normalize_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Return a normalized dict for T/Q/AM messages, or None for unrecognized events."""
    ev = msg.get("ev")
    normalizer = _NORMALIZERS.get(ev)
    if normalizer is None:
        return None
    return normalizer(msg)
