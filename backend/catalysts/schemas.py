import hashlib
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(symbol: str, article_id: str | None, article_url: str | None) -> str:
    if article_id:
        return f"{symbol}:{article_id}"
    url_hash = hashlib.md5((article_url or "").encode()).hexdigest()[:12]
    return f"{symbol}:{url_hash}"


def normalize_news_catalyst(symbol: str, news_item: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a Polygon news item into a structured catalyst record.

    No AI sentiment, no score, no recommended action.
    raw_relevance_hint reflects whether the queried symbol appears
    directly in the article's associated tickers list.
    """
    tickers: list[str] = news_item.get("tickers") or []
    raw_relevance_hint = "direct" if symbol in tickers else "related"

    return {
        "catalyst_id": _stable_id(symbol, news_item.get("id"), news_item.get("article_url")),
        "symbol": symbol,
        "source": "polygon_news",
        "event_type": "news",
        "title": news_item.get("title"),
        "description": news_item.get("description"),
        "publisher": news_item.get("publisher"),
        "author": news_item.get("author"),
        "article_url": news_item.get("article_url"),
        "published_utc": news_item.get("published_utc"),
        "collected_at": _now_iso(),
        "tickers": tickers,
        "keywords": news_item.get("keywords") or [],
        "raw_relevance_hint": raw_relevance_hint,
    }
