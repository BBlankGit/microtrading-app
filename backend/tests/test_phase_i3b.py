"""
Phase I3-B — Full-Universe Premarket Scanner tests.
Read-only intelligence. No broker, no live trading, no real orders.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import intelligence.full_premarket as fp


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_entry(
    ticker: str = "SMCI",
    last_price: float = 36.0,
    prev_close: float = 40.0,
    change_pct: float = -10.0,
    day_volume: float = 1_200_000,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "lastTrade": {"p": last_price},
        "prevDay":   {"c": prev_close},
        "day":       {"v": day_volume},
        "todaysChangePerc": change_pct,
    }


# ── _safe_float ───────────────────────────────────────────────────────────────

def test_safe_float_valid_int():
    assert fp._safe_float(5) == 5.0

def test_safe_float_valid_string():
    assert fp._safe_float("3.14") == pytest.approx(3.14)

def test_safe_float_none_returns_none():
    assert fp._safe_float(None) is None

def test_safe_float_nan_returns_none():
    assert fp._safe_float(float("nan")) is None

def test_safe_float_inf_returns_none():
    assert fp._safe_float(float("inf")) is None

def test_safe_float_non_numeric_string_returns_none():
    assert fp._safe_float("abc") is None


# ── _entry_to_mover ───────────────────────────────────────────────────────────

def test_entry_to_mover_valid():
    entry = _make_entry("SMCI", last_price=36.0, prev_close=40.0, change_pct=-10.0)
    mover = fp._entry_to_mover(entry)
    assert mover is not None
    assert mover["symbol"] == "SMCI"
    assert mover["last_price"] == pytest.approx(36.0)
    assert mover["previous_close"] == pytest.approx(40.0)
    assert mover["source"] == "polygon_bulk_snapshot"


def test_entry_to_mover_gap_percent_computed_from_prices():
    entry = _make_entry(last_price=110.0, prev_close=100.0, change_pct=10.5)
    mover = fp._entry_to_mover(entry)
    assert mover is not None
    assert mover["gap_percent"] == pytest.approx(10.0, abs=0.01)
    assert mover["raw_change_percent"] == pytest.approx(10.5)


def test_entry_to_mover_excludes_below_min_price(monkeypatch):
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_MIN_PRICE", 3.0)
    entry = _make_entry(last_price=1.50, prev_close=2.00, change_pct=-25.0)
    assert fp._entry_to_mover(entry) is None


def test_entry_to_mover_excludes_none_prev_close():
    entry = _make_entry()
    entry["prevDay"]["c"] = None
    assert fp._entry_to_mover(entry) is None


def test_entry_to_mover_excludes_zero_prev_close():
    entry = _make_entry()
    entry["prevDay"]["c"] = 0
    assert fp._entry_to_mover(entry) is None


def test_entry_to_mover_excludes_missing_change_pct():
    entry = _make_entry()
    entry["todaysChangePerc"] = None
    assert fp._entry_to_mover(entry) is None


def test_entry_to_mover_malformed_does_not_raise():
    assert fp._entry_to_mover({"ticker": "BAD", "lastTrade": "corrupt"}) is None
    assert fp._entry_to_mover({}) is None


# ── get_snapshot ──────────────────────────────────────────────────────────────

def test_get_snapshot_returns_empty_dict_when_no_data():
    original = fp._snapshot.copy()
    fp._snapshot.clear()
    try:
        assert fp.get_snapshot() == {}
    finally:
        fp._snapshot.update(original)


def test_get_snapshot_injects_age_fields():
    import time
    fp._snapshot["ok"] = True
    fp._snapshot["top_gainers"] = []
    fp._snapshot["top_losers"] = []
    fp._snapshot["top_movers"] = []
    fp._fetched_at = time.time() - 10
    snap = fp.get_snapshot()
    assert "age_seconds" in snap
    assert "ttl_seconds" in snap
    assert snap["age_seconds"] >= 10
    fp._snapshot.clear()
    fp._fetched_at = 0.0


# ── fetch_and_refresh ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_and_refresh_disabled_returns_error(monkeypatch):
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_ENABLED", False)
    result = await fp.fetch_and_refresh()
    assert result.get("ok") is False
    assert "PREMARKET_SCANNER_ENABLED=False" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_fetch_and_refresh_uses_ttl_guard(monkeypatch):
    import time
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_ENABLED", True)
    monkeypatch.setattr(
        "intelligence.full_premarket.settings.PREMARKET_SCANNER_RESULT_TTL_SECONDS", 300
    )
    fp._snapshot = {"ok": True, "top_gainers": [], "top_losers": [], "top_movers": []}
    fp._fetched_at = time.time()

    called = []
    async def mock_scan(symbols, session):
        called.append(True)
        return {"ok": True, "top_gainers": [], "top_losers": [], "top_movers": []}

    with patch.object(fp, "_scan_universe", mock_scan), \
         patch.object(fp, "get_universe", AsyncMock(return_value=["AAPL"])):
        await fp.fetch_and_refresh()

    assert not called, "scan should not run when TTL is still fresh"
    fp._snapshot.clear()
    fp._fetched_at = 0.0


@pytest.mark.asyncio
async def test_fetch_and_refresh_force_bypasses_ttl(monkeypatch):
    import time
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_ENABLED", True)
    monkeypatch.setattr(
        "intelligence.full_premarket.settings.PREMARKET_SCANNER_RESULT_TTL_SECONDS", 300
    )
    fp._snapshot = {"ok": True, "top_gainers": [], "top_losers": [], "top_movers": []}
    fp._fetched_at = time.time()

    called = []
    scan_result = {
        "ok": True, "mode": "full_universe", "session": "premarket",
        "source": "polygon_bulk_snapshot",
        "universe_count": 1, "symbols_requested": 1,
        "symbols_returned": 1, "valid_movers_count": 1,
        "skipped_count": 0, "scan_duration_ms": 100,
        "top_gainers": [], "top_losers": [], "top_movers": [],
        "error": None, "warnings": [],
    }
    async def mock_scan(symbols, session):
        called.append(True)
        return scan_result

    with patch.object(fp, "_scan_universe", mock_scan), \
         patch.object(fp, "get_universe", AsyncMock(return_value=["AAPL"])), \
         patch.object(fp, "_redis_save_result", AsyncMock()):
        await fp.fetch_and_refresh(force=True)

    assert called, "force=True should bypass TTL guard and run scan"
    fp._snapshot.clear()
    fp._fetched_at = 0.0


# ── Scan produces correct gainers/losers split ────────────────────────────────

@pytest.mark.asyncio
async def test_scan_universe_splits_gainers_losers(monkeypatch):
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_CHUNK_SIZE", 200)
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_MAX_CONCURRENT_CHUNKS", 5)
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_REQUEST_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_TOP_N", 50)
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_TOP_MOVERS_N", 100)
    monkeypatch.setattr("intelligence.full_premarket.settings.PREMARKET_SCANNER_MIN_PRICE", 3.0)

    entries = [
        _make_entry("GAIN1", last_price=10.0, prev_close=8.0,  change_pct=25.0),
        _make_entry("GAIN2", last_price=20.0, prev_close=18.0, change_pct=11.0),
        _make_entry("LOSE1", last_price=5.0,  prev_close=8.0,  change_pct=-37.5),
    ]

    with patch(
        "data.polygon_client.get_bulk_ticker_snapshots",
        AsyncMock(return_value=entries),
    ):
        result = await fp._scan_universe(["GAIN1", "GAIN2", "LOSE1"], "premarket")

    assert result["ok"] is True
    assert len(result["top_gainers"]) == 2
    assert len(result["top_losers"]) == 1
    assert result["top_gainers"][0]["symbol"] == "GAIN1"
    assert result["top_losers"][0]["symbol"] == "LOSE1"


# ── ensure_loaded ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_loaded_skips_if_already_populated():
    fp._snapshot = {"ok": True, "top_gainers": []}
    fp._fetched_at = 1.0
    called = []

    async def mock_load():
        called.append(True)
        return None

    with patch.object(fp, "_redis_load_result", mock_load):
        await fp.ensure_loaded()

    assert not called, "ensure_loaded should not hit Redis when snapshot is already populated"
    fp._snapshot.clear()
    fp._fetched_at = 0.0
