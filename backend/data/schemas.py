from typing import Any


def normalize_snapshot(raw: dict[str, Any], symbol: str) -> dict[str, Any]:
    ticker = raw.get("ticker", {})
    day = ticker.get("day", {})
    prev_day = ticker.get("prevDay", {})
    last_trade = ticker.get("lastTrade", {})
    last_quote = ticker.get("lastQuote", {})

    return {
        "symbol": symbol.upper(),
        "name": ticker.get("name"),
        "market_status": raw.get("status"),
        "day": {
            "open": day.get("o"),
            "high": day.get("h"),
            "low": day.get("l"),
            "close": day.get("c"),
            "volume": day.get("v"),
            "vwap": day.get("vw"),
        },
        "prev_day": {
            "open": prev_day.get("o"),
            "high": prev_day.get("h"),
            "low": prev_day.get("l"),
            "close": prev_day.get("c"),
            "volume": prev_day.get("v"),
        },
        "last_trade": {
            "price": last_trade.get("p"),
            "size": last_trade.get("s"),
            "timestamp": last_trade.get("t"),
        },
        "last_quote": {
            "bid": last_quote.get("P"),
            "ask": last_quote.get("P"),
            "bid_size": last_quote.get("S"),
        },
        "change_percent": ticker.get("todaysChangePerc"),
        "change": ticker.get("todaysChange"),
    }


def normalize_previous_close(raw: dict[str, Any], symbol: str) -> dict[str, Any]:
    results = raw.get("results", [])
    if not results:
        return {"symbol": symbol.upper(), "data": None}
    r = results[0]
    return {
        "symbol": symbol.upper(),
        "date": r.get("t"),
        "open": r.get("o"),
        "high": r.get("h"),
        "low": r.get("l"),
        "close": r.get("c"),
        "volume": r.get("v"),
        "vwap": r.get("vw"),
        "transactions": r.get("n"),
    }


def normalize_news_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "author": item.get("author"),
        "published_utc": item.get("published_utc"),
        "article_url": item.get("article_url"),
        "tickers": item.get("tickers", []),
        "description": item.get("description"),
        "keywords": item.get("keywords", []),
        "publisher": item.get("publisher", {}).get("name"),
    }
