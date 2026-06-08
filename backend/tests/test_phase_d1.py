"""
Phase D1: Shared Market Data Collector tests.
No broker. No live trading. No real orders. No real-money execution.
No AI/LLM/Ollama. All Polygon calls mocked.
"""

import ast
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_payload_dict(**overrides) -> dict:
    base = {
        "symbol": "AMD",
        "source": "polygon",
        "as_of": "2026-06-08T15:00:00+00:00",
        "fetched_at": "2026-06-08T15:00:00+00:00",
        "ttl_seconds": 30,
        "last_price": 490.25,
        "bid": 490.10,
        "ask": 490.40,
        "spread_percent": 0.0612,
        "day_volume": 5_000_000.0,
        "volume_ratio": None,
        "change_percent": 1.5,
        "prev_close": 483.0,
        "minute_high": None,
        "minute_low": None,
        "minute_close": None,
        "raw_status": "ok",
        "error": None,
    }
    base.update(overrides)
    return base


def _make_redis_mock(get_return=None) -> AsyncMock:
    r = AsyncMock()
    r.get.return_value = json.dumps(get_return) if get_return is not None else None
    r.set.return_value = True
    r.aclose.return_value = None
    return r


# ── Test 1: Redis key serialization / deserialization ─────────────────────────

async def test_redis_key_serialization():
    from marketdata.models import SymbolPayload

    payload = SymbolPayload(**{k: v for k, v in _make_payload_dict().items()})
    d = payload.to_dict()

    mock_r = _make_redis_mock()
    with patch("data.redis_client.make_redis", return_value=mock_r):
        from marketdata import cache
        await cache.write_cycle_results([d], {}, ttl=30)

    mock_r.set.assert_called()
    # First call should be the snapshot key
    first_call_args = mock_r.set.call_args_list[0][0]
    assert first_call_args[0] == "market:snapshot:AMD"
    stored = json.loads(first_call_args[1])
    assert stored["symbol"] == "AMD"
    assert stored["last_price"] == 490.25


async def test_redis_key_deserialization():
    payload_dict = _make_payload_dict()
    mock_r = _make_redis_mock(get_return=payload_dict)

    with patch("data.redis_client.make_redis", return_value=mock_r):
        from marketdata import cache
        result = await cache.read_symbol("AMD")

    assert result is not None
    assert result["symbol"] == "AMD"
    assert result["source"] == "polygon"
    mock_r.get.assert_called_once_with("market:snapshot:AMD")


# ── Test 2: Symbol payload schema has all required fields ─────────────────────

def test_symbol_payload_schema_fields():
    from marketdata.models import SymbolPayload

    p = SymbolPayload(**_make_payload_dict())
    d = p.to_dict()

    required = [
        "symbol", "source", "as_of", "fetched_at", "ttl_seconds",
        "last_price", "bid", "ask", "spread_percent", "day_volume",
        "volume_ratio", "change_percent", "prev_close",
        "minute_high", "minute_low", "minute_close",
        "raw_status", "error",
    ]
    for field in required:
        assert field in d, f"Missing field: {field}"


def test_symbol_payload_is_fresh_and_stale():
    from marketdata.models import SymbolPayload
    from datetime import datetime, timezone, timedelta

    fresh_ts = datetime.now(timezone.utc).isoformat()
    p_fresh = SymbolPayload(**_make_payload_dict(fetched_at=fresh_ts, ttl_seconds=30))
    assert p_fresh.is_fresh() is True

    stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    p_stale = SymbolPayload(**_make_payload_dict(fetched_at=stale_ts, ttl_seconds=30))
    assert p_stale.is_fresh() is False


# ── Test 3: Health endpoint returns expected structure ─────────────────────────

async def test_health_endpoint_structure(client):
    with (
        patch("data.redis_client.redis_ping_status", new=AsyncMock(return_value={"redis_connected": True})),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=None)),
        patch("marketdata.cache.read_active_symbols", new=AsyncMock(return_value=[])),
    ):
        resp = client.get("/api/marketdata/health")

    assert resp.status_code == 200
    data = resp.json()
    required_keys = [
        "enabled", "running", "source", "symbols_total", "symbols_fresh",
        "symbols_stale", "last_cycle_at", "last_success_at", "last_error",
        "requests_last_minute", "timeouts_last_minute", "errors_last_minute",
        "cache_ttl_seconds", "redis_connected",
    ]
    for key in required_keys:
        assert key in data, f"Missing key in health response: {key}"
    assert data["source"] == "polygon"
    assert isinstance(data["enabled"], bool)
    assert isinstance(data["redis_connected"], bool)


# ── Test 4: Symbol endpoint returns cached data ───────────────────────────────

async def test_symbol_endpoint_returns_cached_data(client):
    payload = _make_payload_dict(symbol="QQQ", last_price=455.10)
    with patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=payload)):
        resp = client.get("/api/marketdata/symbol/QQQ")

    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "QQQ"
    assert data["last_price"] == 455.10
    assert data["source"] == "polygon"


# ── Test 5: Missing symbol returns 404 ───────────────────────────────────────

async def test_symbol_endpoint_missing_returns_404(client):
    with patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=None)):
        resp = client.get("/api/marketdata/symbol/ZZZZ")

    assert resp.status_code == 404
    assert "ZZZZ" in resp.json()["detail"]


# ── Test 6: Collector handles Polygon timeout without crashing ────────────────

async def test_collector_handles_polygon_timeout_without_crashing():
    from marketdata.collector import MarketDataCollector

    collector = MarketDataCollector(symbols=["AMD"])

    async def _fake_write(*args, **kwargs):
        pass

    with (
        patch("marketdata.polygon_source.fetch_bulk_snapshots",
              new=AsyncMock(side_effect=Exception("Polygon request timed out after 8.0s"))),
        patch("marketdata.cache.write_cycle_results", new=AsyncMock(side_effect=_fake_write)),
    ):
        # Should not raise
        await collector._cycle()

    # Cycle completed without crashing; error recorded
    assert collector._last_error is not None


# ── Test 7: Timeout counter increments on timeout error ──────────────────────

async def test_timeout_counter_increments():
    from marketdata.collector import MarketDataCollector

    collector = MarketDataCollector(symbols=["AMD"])
    assert collector._count_recent(collector._timeout_ts) == 0

    with (
        patch("marketdata.polygon_source.fetch_bulk_snapshots",
              new=AsyncMock(side_effect=Exception("Polygon request timed out after 8.0s"))),
        patch("marketdata.cache.write_cycle_results", new=AsyncMock()),
    ):
        await collector._cycle()

    # RETRY_COUNT=1 means up to 2 attempts; each timeout increments the counter
    assert collector._count_recent(collector._timeout_ts) >= 1


# ── Test 8: Rate limiter skips cycle when budget exhausted ────────────────────

async def test_rate_limiter_skips_cycle_when_budget_exhausted():
    from marketdata.collector import MarketDataCollector
    from core.config import settings

    collector = MarketDataCollector(symbols=["AMD"])
    # Fill the sliding window beyond the per-minute limit
    now = time.monotonic()
    for _ in range(settings.MARKETDATA_MAX_REQUESTS_PER_MINUTE + 1):
        collector._request_ts.append(now)

    fetch_mock = AsyncMock()
    with patch("marketdata.polygon_source.fetch_bulk_snapshots", new=fetch_mock):
        await collector._cycle()

    # Polygon should NOT have been called
    fetch_mock.assert_not_called()


# ── Test 9: Cache freshness / stale detection ─────────────────────────────────

async def test_cache_freshness_stale_in_health():
    from datetime import datetime, timezone, timedelta

    stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    stale_payload = _make_payload_dict(fetched_at=stale_ts, ttl_seconds=30)

    with (
        patch("data.redis_client.redis_ping_status",
              new=AsyncMock(return_value={"redis_connected": True})),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=stale_payload)),
        patch("marketdata.cache.read_active_symbols", new=AsyncMock(return_value=[])),
    ):
        from marketdata.health import get_health
        h = await get_health()

    # At least one symbol should be stale since fetched_at is 120s ago vs ttl=30
    assert h["symbols_stale"] >= 1
    assert h["symbols_fresh"] == 0


# ── Test 10: No broker / order / live-trading imports in marketdata/ ──────────

def test_no_broker_or_trading_imports_in_marketdata():
    forbidden = {
        "broker", "alpaca", "td_ameritrade", "order_manager",
        "live_trading", "execution", "real_money",
    }
    marketdata_dir = Path(__file__).parent.parent / "marketdata"
    for py_file in marketdata_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for name in names:
                    for bad in forbidden:
                        assert bad not in (name or "").lower(), (
                            f"{py_file.name}: forbidden import '{name}'"
                        )


# ── Test 11: No AI / LLM / Ollama imports in marketdata/ ─────────────────────

def test_no_ai_llm_ollama_imports_in_marketdata():
    forbidden = {"openai", "anthropic", "ollama", "langchain", "transformers", "llm"}
    marketdata_dir = Path(__file__).parent.parent / "marketdata"
    for py_file in marketdata_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for name in names:
                    for bad in forbidden:
                        assert bad not in (name or "").lower(), (
                            f"{py_file.name}: forbidden import '{name}'"
                        )


# ── Test 12: No real Polygon calls — all fetches mocked ──────────────────────

async def test_no_real_polygon_calls_in_fetch():
    """polygon_source.fetch_bulk_snapshots must use polygon_client (mockable), not httpx directly."""
    from marketdata import polygon_source

    fake_tickers = [
        {
            "ticker": "AMD",
            "todaysChangePerc": 1.5,
            "todaysChange": 7.3,
            "day": {"o": 480.0, "h": 495.0, "l": 478.0, "c": 490.0, "v": 5_000_000.0, "vw": 488.0},
            "prevDay": {"c": 483.0},
            "lastTrade": {"p": 490.25, "s": 100},
            "lastQuote": {"p": 490.10, "P": 490.40},
        }
    ]

    with patch(
        "data.polygon_client.get_bulk_ticker_snapshots",
        new=AsyncMock(return_value=fake_tickers),
    ):
        payloads = await polygon_source.fetch_bulk_snapshots(["AMD"], ttl=30)

    assert len(payloads) == 1
    p = payloads[0]
    assert p.symbol == "AMD"
    assert p.last_price == 490.25
    assert p.bid == 490.10
    assert p.ask == 490.40
    assert p.change_percent == 1.5
    assert p.prev_close == 483.0
    assert p.raw_status == "ok"
    assert p.error is None
    # Volume and spread computed
    assert p.day_volume == 5_000_000.0
    assert p.spread_percent is not None and p.spread_percent > 0
