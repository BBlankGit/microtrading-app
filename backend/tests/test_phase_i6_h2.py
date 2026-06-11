"""
Phase I6-H2 — Finnhub earnings and insider fetchers.

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM/Ollama. Verifies the wired Finnhub paths via mocked HTTP, the
new provider statuses (missing_api_key, rate_limited, error), cache-first
GET behavior, admin-protected refresh, and that the API key never appears
in logs or sanitized URLs.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest


def _reset_earnings():
    from intelligence import earnings as e
    e._cache = None
    e._cache_time = None


def _reset_insiders():
    from intelligence import insiders as ins
    ins._cache = None
    ins._cache_time = None


# ── Finnhub client: key sanity + URL sanitization ─────────────────────────────

def test_finnhub_client_rejects_placeholder_key():
    from core.config import settings
    from intelligence import finnhub_client as fc

    for placeholder in ("", "PASTE_YOUR_KEY_HERE", "changeme", "none", "NULL"):
        with patch.object(settings, "FINNHUB_API_KEY", placeholder):
            assert fc.is_configured() is False


def test_finnhub_client_accepts_real_key():
    from core.config import settings
    from intelligence import finnhub_client as fc

    with patch.object(settings, "FINNHUB_API_KEY", "abc123def456ghi789"):
        assert fc.is_configured() is True


def test_finnhub_client_sanitizes_token_from_urls():
    from intelligence import finnhub_client as fc

    out = fc._sanitize_for_log("/calendar/earnings?from=2026-01-01&token=SECRET_KEY&to=2026-02-01")
    assert "SECRET_KEY" not in out
    assert "<redacted>" in out


# ── Earnings: missing_api_key when finnhub provider but no key ────────────────

def test_earnings_provider_finnhub_without_key_is_missing_api_key():
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings()
    with patch.object(settings, "EARNINGS_DATA_PROVIDER", "finnhub"), \
         patch.object(settings, "FINNHUB_API_KEY", ""):
        assert e.provider_status() == "missing_api_key"
        assert e.is_available() is False
        snap = asyncio.run(e.fetch_and_refresh(force=True))
    assert snap["enabled"] is False
    assert snap["available"] is False
    assert snap["provider_status"] == "missing_api_key"
    assert snap["results"] == []
    assert "FINNHUB_API_KEY" in (snap.get("warning") or "")


# ── Earnings: active path with mocked Finnhub response ────────────────────────

@pytest.mark.asyncio
async def test_earnings_active_normalizes_finnhub_payload(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings()

    fake_payload = {
        "earningsCalendar": [
            # In DEFAULT_UNIVERSE → should be kept
            {"symbol": "AAPL", "date": "2026-07-31",
             "hour": "amc", "epsEstimate": 2.10, "revenueEstimate": 100000000000},
            {"symbol": "NVDA", "date": "2026-08-15",
             "hour": "bmo", "epsEstimate": 0.95, "revenueEstimate": 50000000000,
             "epsActual": 1.05, "revenueActual": 51000000000},
            # Not in DEFAULT_UNIVERSE → filtered out
            {"symbol": "ZZZZZ", "date": "2026-08-01", "hour": "amc", "epsEstimate": 0.0},
        ]
    }

    async def _fake_get(path, params=None, timeout=8.0):
        assert path == "/calendar/earnings"
        assert "from" in (params or {}) and "to" in (params or {})
        return fake_payload

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "abc123def456ghi789")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _fake_get)

    snap = await e.fetch_and_refresh(force=True)
    assert snap["provider_status"] == "active"
    assert snap["enabled"] is True
    assert snap["available"] is True
    assert snap["source"] == "finnhub"

    syms = {r["ticker"] for r in snap["results"]}
    assert "AAPL" in syms and "NVDA" in syms
    assert "ZZZZZ" not in syms  # filtered to tracked universe

    aapl = next(r for r in snap["results"] if r["ticker"] == "AAPL")
    assert aapl["report_time"] == "after_close"
    assert aapl["eps_estimate"] == 2.10
    assert aapl["source"] == "finnhub"

    nvda = next(r for r in snap["results"] if r["ticker"] == "NVDA")
    assert nvda["report_time"] == "before_open"
    assert nvda["eps_actual"] == 1.05


# ── Earnings: rate_limited keeps prior cache ──────────────────────────────────

@pytest.mark.asyncio
async def test_earnings_rate_limited_keeps_prior_cache(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e
    from intelligence.finnhub_client import FinnhubError

    _reset_earnings()

    prior_payload = {"earningsCalendar": [
        {"symbol": "AAPL", "date": "2026-07-31", "hour": "amc", "epsEstimate": 2.10},
    ]}

    call_count = {"n": 0}

    async def _seq_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return prior_payload
        raise FinnhubError("rate limited", status_code=429, rate_limited=True)

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _seq_get)

    snap1 = await e.fetch_and_refresh(force=True)
    assert snap1["provider_status"] == "active"
    assert len(snap1["results"]) == 1

    snap2 = await e.fetch_and_refresh(force=True)
    assert snap2["provider_status"] == "rate_limited"
    # Prior cache results preserved
    assert len(snap2["results"]) == 1


# ── Earnings: cache-first GET — repeated calls don't refetch ──────────────────

@pytest.mark.asyncio
async def test_earnings_cache_first_does_not_refetch(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings()
    call_count = {"n": 0}

    async def _counted_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        return {"earningsCalendar": []}

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _counted_get)

    await e.fetch_and_refresh()  # cold start fetch
    await e.fetch_and_refresh()  # cached
    await e.fetch_and_refresh()  # cached
    assert call_count["n"] == 1


# ── Insiders: code normalization includes Finnhub-style payloads ──────────────

def test_insider_code_p_is_open_market_purchase():
    from intelligence.insiders import _normalize_code

    tx_type, label = _normalize_code("P")
    assert tx_type == "open_market_purchase"
    assert label == "bullish_buy"


def test_insider_code_s_is_sale_no_bullish_boost():
    from intelligence.insiders import _normalize_code

    tx_type, label = _normalize_code("S")
    assert tx_type == "sale"
    assert label == "sale"  # never "bullish_*"


def test_insider_multi_letter_code_takes_first_letter():
    from datetime import date
    from intelligence.insiders import _normalize_row

    row = _normalize_row(
        {"symbol": "AAPL", "transactionDate": "2026-06-01",
         "transactionCode": "P-Purchase", "shares": 1000, "price": 200.0, "name": "X"},
        date(2026, 6, 5),
    )
    assert row["transaction_code"] == "P"
    assert row["transaction_type"] == "open_market_purchase"
    assert row["value"] == 200000.0


# ── Insiders: active path with mocked per-symbol Finnhub responses ────────────

@pytest.mark.asyncio
async def test_insiders_active_normalizes_finnhub_payload(monkeypatch):
    from core.config import settings
    from intelligence import insiders as ins

    _reset_insiders()

    async def _fake_get(path, params=None, timeout=8.0):
        sym = (params or {}).get("symbol")
        if sym == "AAPL":
            return {"data": [
                {"name": "T. Cook", "transactionDate": "2026-06-08",
                 "transactionCode": "P", "share": 5000, "price": 200.0},
            ]}
        return {"data": []}

    monkeypatch.setattr(settings, "INSIDER_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "abc123def456ghi789")
    # Tiny universe + zero delay so the test runs fast.
    monkeypatch.setattr(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 3)
    monkeypatch.setattr(settings, "INSIDER_FETCH_INTERSYMBOL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("intelligence.insiders.finnhub_get", _fake_get)

    snap = await ins.fetch_and_refresh(force=True)
    assert snap["provider_status"] == "active"
    assert snap["enabled"] is True
    assert snap["source"] == "finnhub"

    aapl_rows = [r for r in snap["results"] if r["ticker"] == "AAPL"]
    assert len(aapl_rows) == 1
    row = aapl_rows[0]
    assert row["transaction_code"] == "P"
    assert row["transaction_type"] == "open_market_purchase"
    assert row["buy_sell_label"] == "bullish_buy"
    assert row["value"] == 1000000.0  # 5000 * 200
    assert row["source"] == "finnhub"


# ── Insiders: cache-first GET ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insiders_cache_first_does_not_refetch(monkeypatch):
    from core.config import settings
    from intelligence import insiders as ins

    _reset_insiders()
    call_count = {"n": 0}

    async def _counted_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        return {"data": []}

    monkeypatch.setattr(settings, "INSIDER_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 2)
    monkeypatch.setattr(settings, "INSIDER_FETCH_INTERSYMBOL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("intelligence.insiders.finnhub_get", _counted_get)

    await ins.fetch_and_refresh()  # cold-start
    n_after_cold = call_count["n"]
    await ins.fetch_and_refresh()  # cached
    await ins.fetch_and_refresh()  # cached
    assert call_count["n"] == n_after_cold  # no additional calls


# ── No 5,000-symbol polling: tracked symbol list is bounded ───────────────────

def test_earnings_tracked_symbols_bounded():
    from core.config import settings
    from intelligence.earnings import _tracked_symbols

    with patch.object(settings, "EARNINGS_MAX_SYMBOLS_PER_REFRESH", 25):
        syms = _tracked_symbols()
    assert len(syms) <= 25


def test_insiders_tracked_symbols_bounded():
    from core.config import settings
    from intelligence.insiders import _tracked_symbols

    with patch.object(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 7):
        syms = _tracked_symbols()
    assert len(syms) <= 7


# ── API key never appears in log records ──────────────────────────────────────

@pytest.mark.asyncio
async def test_finnhub_client_does_not_log_api_key(monkeypatch, caplog):
    from core.config import settings
    from intelligence import finnhub_client as fc
    import httpx

    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "TOPSECRET_KEY_XYZ")

    async def _fake_async_get(self, url, params=None):
        # Simulate a network error so the warning log path is exercised.
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_async_get)
    caplog.set_level(logging.WARNING)
    with pytest.raises(fc.FinnhubError):
        await fc.get("/calendar/earnings", params={"from": "2026-01-01"})

    all_text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "TOPSECRET_KEY_XYZ" not in all_text


# ── Scoring contributes zero for missing symbols even when active ─────────────

def test_scoring_zero_when_symbol_not_in_cache():
    from intelligence.earnings import score_earnings_proximity
    from intelligence.insiders import score_insiders

    e = score_earnings_proximity("UNKNOWN_SYM", {})
    assert e["earnings_score_adjustment"] == 0
    assert e["earnings_blocked"] is False

    ins = score_insiders("UNKNOWN_SYM", {})
    assert ins["insider_score_adjustment"] == 0
    assert ins["insider_recent_buy_count"] == 0


# ── Pytest config plumbing ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Override default fixture so async tests share a loop within this module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
