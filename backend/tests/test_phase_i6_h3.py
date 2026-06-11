"""
Phase I6-H3 — Stale-cache metadata honesty for earnings/insiders.

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM/Ollama. Verifies that after a failed Finnhub refresh:
  - prior cache rows are preserved
  - prior cache age is preserved (_cache_time NOT reset)
  - serving_stale_cache=true
  - last_refresh_status reflects the failure
And when no prior cache exists + refresh fails:
  - results=[], available=false, serving_stale_cache=false
"""
from __future__ import annotations

import asyncio
import time

import pytest


def _reset_earnings():
    from intelligence import earnings as e
    e._cache = None
    e._cache_time = None
    e._last_attempt_iso = None
    e._last_successful_iso = None
    e._last_refresh_status = "never"
    e._last_refresh_error = None


def _reset_insiders():
    from intelligence import insiders as ins
    ins._cache = None
    ins._cache_time = None
    ins._last_attempt_iso = None
    ins._last_successful_iso = None
    ins._last_refresh_status = "never"
    ins._last_refresh_error = None


# ── Earnings: success path sets all timestamps ───────────────────────────────

@pytest.mark.asyncio
async def test_earnings_success_marks_fresh_cache(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e

    _reset_earnings()

    async def _fake_get(path, params=None, timeout=8.0):
        return {"earningsCalendar": [
            {"symbol": "AAPL", "date": "2026-07-31", "hour": "amc", "epsEstimate": 2.1},
        ]}

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _fake_get)

    snap = await e.fetch_and_refresh(force=True)
    assert snap["provider_status"] == "active"
    assert snap["available"] is True
    assert snap["serving_stale_cache"] is False
    assert snap["last_refresh_status"] == "success"
    assert snap["last_refresh_error"] is None
    assert snap["last_attempted_at"] is not None
    assert snap["last_successful_fetched_at"] == snap["fetched_at"]
    assert e._cache_time is not None


# ── Earnings: rate-limit with prior cache preserves age ──────────────────────

@pytest.mark.asyncio
async def test_earnings_rate_limit_preserves_cache_age(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e
    from intelligence.finnhub_client import FinnhubError

    _reset_earnings()
    call_count = {"n": 0}

    async def _seq_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"earningsCalendar": [
                {"symbol": "AAPL", "date": "2026-07-31", "hour": "amc", "epsEstimate": 2.1},
            ]}
        raise FinnhubError("rate limited", status_code=429, rate_limited=True)

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _seq_get)

    snap1 = await e.fetch_and_refresh(force=True)
    fetched_at_1 = snap1["fetched_at"]
    cache_time_1 = e._cache_time
    assert snap1["serving_stale_cache"] is False
    # Force a small monotonic gap so we can detect any reset.
    await asyncio.sleep(0.01)

    snap2 = await e.fetch_and_refresh(force=True)
    assert snap2["provider_status"] == "rate_limited"
    assert snap2["serving_stale_cache"] is True
    assert snap2["last_refresh_status"] == "rate_limited"
    # Prior rows AND prior fetched_at AND prior cache_time preserved.
    assert snap2["fetched_at"] == fetched_at_1
    assert len(snap2["results"]) == 1
    assert e._cache_time == cache_time_1, "_cache_time must NOT be reset on failure"
    assert snap2["last_successful_fetched_at"] == fetched_at_1


# ── Earnings: error with prior cache sets serving_stale_cache ────────────────

@pytest.mark.asyncio
async def test_earnings_error_with_prior_cache(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e
    from intelligence.finnhub_client import FinnhubError

    _reset_earnings()
    call_count = {"n": 0}

    async def _seq_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"earningsCalendar": [
                {"symbol": "MSFT", "date": "2026-07-31", "hour": "amc", "epsEstimate": 3.0},
            ]}
        raise FinnhubError("http 500", status_code=500)

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _seq_get)

    snap1 = await e.fetch_and_refresh(force=True)
    cache_time_1 = e._cache_time
    snap2 = await e.fetch_and_refresh(force=True)
    assert snap2["provider_status"] == "error"
    assert snap2["serving_stale_cache"] is True
    assert snap2["last_refresh_status"] == "error"
    assert snap2["last_refresh_error"] is not None
    # Rows preserved
    assert len(snap2["results"]) == 1
    assert e._cache_time == cache_time_1


# ── Earnings: no prior cache + error → available=false ───────────────────────

@pytest.mark.asyncio
async def test_earnings_error_without_prior_cache(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e
    from intelligence.finnhub_client import FinnhubError

    _reset_earnings()

    async def _err_get(path, params=None, timeout=8.0):
        raise FinnhubError("http 500", status_code=500)

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _err_get)

    snap = await e.fetch_and_refresh(force=True)
    assert snap["available"] is False
    assert snap["results"] == []
    assert snap["serving_stale_cache"] is False
    assert snap["provider_status"] == "error"


# ── cache_age_seconds does not reset to ~0 after a failed refresh ────────────

@pytest.mark.asyncio
async def test_earnings_cache_age_not_reset_after_failure(monkeypatch):
    from core.config import settings
    from intelligence import earnings as e
    from intelligence.finnhub_client import FinnhubError

    _reset_earnings()
    call_count = {"n": 0}

    async def _seq_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"earningsCalendar": [
                {"symbol": "AAPL", "date": "2026-07-31", "hour": "amc", "epsEstimate": 2.1},
            ]}
        raise FinnhubError("rate limited", status_code=429, rate_limited=True)

    monkeypatch.setattr(settings, "EARNINGS_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr("intelligence.earnings.finnhub_get", _seq_get)

    await e.fetch_and_refresh(force=True)
    age_after_success = e.cache_age_seconds()
    # Wait a bit so the clock visibly advances.
    await asyncio.sleep(0.05)
    age_before_fail = e.cache_age_seconds()
    await e.fetch_and_refresh(force=True)  # failure path
    age_after_fail = e.cache_age_seconds()
    assert age_after_fail is not None
    # If _cache_time had been reset, age_after_fail would drop close to 0.
    assert age_after_fail >= age_before_fail, (
        f"cache age should not regress after a failed refresh "
        f"(was {age_before_fail}, became {age_after_fail})"
    )


# ── Same matrix for insiders ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insiders_success_marks_fresh_cache(monkeypatch):
    from core.config import settings
    from intelligence import insiders as ins

    _reset_insiders()

    async def _fake_get(path, params=None, timeout=8.0):
        return {"data": []}

    monkeypatch.setattr(settings, "INSIDER_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 2)
    monkeypatch.setattr(settings, "INSIDER_FETCH_INTERSYMBOL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("intelligence.insiders.finnhub_get", _fake_get)

    snap = await ins.fetch_and_refresh(force=True)
    assert snap["provider_status"] == "active"
    assert snap["serving_stale_cache"] is False
    assert snap["last_refresh_status"] == "success"
    assert snap["last_successful_fetched_at"] == snap["fetched_at"]


@pytest.mark.asyncio
async def test_insiders_rate_limit_preserves_cache_age(monkeypatch):
    from core.config import settings
    from intelligence import insiders as ins
    from intelligence.finnhub_client import FinnhubError

    _reset_insiders()
    call_count = {"n": 0}

    async def _seq_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        sym = (params or {}).get("symbol")
        if call_count["n"] == 1:
            return {"data": [{"name": "X", "transactionDate": "2026-06-08",
                              "transactionCode": "P", "share": 100, "price": 50.0}]}
        if call_count["n"] == 2:
            return {"data": []}
        # All later calls 429.
        raise FinnhubError("rate limited", status_code=429, rate_limited=True)

    monkeypatch.setattr(settings, "INSIDER_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 2)
    monkeypatch.setattr(settings, "INSIDER_FETCH_INTERSYMBOL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("intelligence.insiders.finnhub_get", _seq_get)

    snap1 = await ins.fetch_and_refresh(force=True)
    fetched_at_1 = snap1["fetched_at"]
    cache_time_1 = ins._cache_time
    assert len(snap1["results"]) == 1

    await asyncio.sleep(0.01)
    snap2 = await ins.fetch_and_refresh(force=True)
    assert snap2["provider_status"] == "rate_limited"
    assert snap2["serving_stale_cache"] is True
    assert snap2["fetched_at"] == fetched_at_1
    assert len(snap2["results"]) == 1
    assert ins._cache_time == cache_time_1


@pytest.mark.asyncio
async def test_insiders_error_with_prior_cache(monkeypatch):
    from core.config import settings
    from intelligence import insiders as ins
    from intelligence.finnhub_client import FinnhubError

    _reset_insiders()
    call_count = {"n": 0}

    async def _seq_get(path, params=None, timeout=8.0):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"data": [{"name": "Y", "transactionDate": "2026-06-08",
                              "transactionCode": "P", "share": 50, "price": 10.0}]}
        if call_count["n"] == 2:
            return {"data": []}
        raise FinnhubError("http 500", status_code=500)

    monkeypatch.setattr(settings, "INSIDER_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 2)
    monkeypatch.setattr(settings, "INSIDER_FETCH_INTERSYMBOL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("intelligence.insiders.finnhub_get", _seq_get)

    await ins.fetch_and_refresh(force=True)
    cache_time_1 = ins._cache_time
    snap2 = await ins.fetch_and_refresh(force=True)
    assert snap2["provider_status"] == "error"
    assert snap2["serving_stale_cache"] is True
    assert len(snap2["results"]) == 1
    assert ins._cache_time == cache_time_1


@pytest.mark.asyncio
async def test_insiders_error_without_prior_cache(monkeypatch):
    from core.config import settings
    from intelligence import insiders as ins
    from intelligence.finnhub_client import FinnhubError

    _reset_insiders()

    async def _err_get(path, params=None, timeout=8.0):
        raise FinnhubError("http 500", status_code=500)

    monkeypatch.setattr(settings, "INSIDER_DATA_PROVIDER", "finnhub")
    monkeypatch.setattr(settings, "FINNHUB_API_KEY", "k")
    monkeypatch.setattr(settings, "INSIDER_MAX_SYMBOLS_PER_REFRESH", 1)
    monkeypatch.setattr(settings, "INSIDER_FETCH_INTERSYMBOL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr("intelligence.insiders.finnhub_get", _err_get)

    snap = await ins.fetch_and_refresh(force=True)
    assert snap["available"] is False
    assert snap["results"] == []
    assert snap["serving_stale_cache"] is False
    assert snap["provider_status"] == "error"
