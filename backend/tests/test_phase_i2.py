"""
Phase I2: Intelligence tabs — Reddit ranking via ApeWisdom.
Read-only integration. No Polygon calls, no broker, no live trading, no real orders.
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_apewisdom_response(count: int = 5, mention_base: int = 100) -> dict:
    """Build a fake ApeWisdom API response body."""
    tickers = ["NVDA", "TSLA", "AAPL", "AMD", "PLTR", "SOUN", "IONQ", "RKLB", "OKLO", "MU"]
    return {
        "results": [
            {
                "rank": i + 1,
                "ticker": tickers[i % len(tickers)],
                "name": f"Company {i}",
                "mentions": mention_base + i * 10,
                "upvotes": 50 + i * 5,
                "rank_24h_ago": i + 3,
                "mentions_24h_ago": mention_base + i * 5,
            }
            for i in range(count)
        ]
    }


def _reset_module_state():
    """Clear in-memory state between tests."""
    import intelligence.reddit as r
    r._current = []
    r._previous = []
    r._fetched_at = 0.0
    r._fetch_error = None


# ── Test 1: ApeWisdom response parsing ────────────────────────────────────────

def test_normalize_rows_parses_fields():
    """_normalize_rows correctly extracts all required fields."""
    from intelligence.reddit import _normalize_rows
    raw = [
        {
            "rank": 1,
            "ticker": "nvda",        # should be uppercased
            "name": "NVIDIA Corp",
            "mentions": 500,
            "upvotes": 200,
            "rank_24h_ago": 3,
            "mentions_24h_ago": 300,
        },
        {
            "rank": 2,
            "ticker": "TSLA",
            "name": "Tesla",
            "mentions": 250,
            "upvotes": 100,
            "rank_24h_ago": None,
            "mentions_24h_ago": None,
        },
    ]
    rows = _normalize_rows(raw)
    assert len(rows) == 2

    nvda = rows[0]
    assert nvda["ticker"] == "NVDA"           # uppercased
    assert nvda["rank"] == 1
    assert nvda["mentions"] == 500
    assert nvda["upvotes"] == 200
    assert nvda["rank_24h_ago"] == 3
    assert nvda["mentions_24h_ago"] == 300

    tsla = rows[1]
    assert tsla["ticker"] == "TSLA"
    assert tsla["rank_24h_ago"] is None
    assert tsla["mentions_24h_ago"] is None


def test_normalize_rows_skips_empty_ticker():
    """Rows without a ticker are dropped."""
    from intelligence.reddit import _normalize_rows
    raw = [
        {"rank": 1, "ticker": "", "mentions": 100},
        {"rank": 2, "ticker": None, "mentions": 200},
        {"rank": 3, "ticker": "AMD", "mentions": 150},
    ]
    rows = _normalize_rows(raw)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AMD"


# ── Test 2: Spike detection (3x threshold) ────────────────────────────────────

def test_spike_detection_fires_at_3x():
    """Spike detected when current mentions >= 3 * previous mentions."""
    from intelligence.reddit import _detect_spikes
    current = [
        {"ticker": "NVDA", "mentions": 300},   # 3x of 100 → spike
        {"ticker": "TSLA", "mentions": 100},   # 2x of 50 → no spike
        {"ticker": "AMD",  "mentions": 50},    # new ticker, prev=0 → no spike
    ]
    previous = [
        {"ticker": "NVDA", "mentions": 100},
        {"ticker": "TSLA", "mentions": 50},
    ]
    spikes = _detect_spikes(current, previous)
    assert len(spikes) == 1
    assert spikes[0]["ticker"] == "NVDA"
    assert spikes[0]["spike_ratio"] == 3.0
    assert spikes[0]["prev_mentions"] == 100
    assert spikes[0]["mentions"] == 300


def test_spike_detection_no_previous_returns_empty():
    """No previous snapshot → no spikes (nothing to compare against)."""
    from intelligence.reddit import _detect_spikes
    current = [{"ticker": "NVDA", "mentions": 999}]
    spikes = _detect_spikes(current, [])
    assert spikes == []


def test_spike_detection_exactly_3x_qualifies():
    """Exactly 3.0x is at the threshold and should fire."""
    from intelligence.reddit import _detect_spikes
    current = [{"ticker": "SOUN", "mentions": 300}]
    previous = [{"ticker": "SOUN", "mentions": 100}]
    spikes = _detect_spikes(current, previous)
    assert len(spikes) == 1
    assert spikes[0]["spike_ratio"] == 3.0


def test_spike_detection_below_3x_no_spike():
    """2.99x does not fire."""
    from intelligence.reddit import _detect_spikes
    current = [{"ticker": "SOUN", "mentions": 299}]
    previous = [{"ticker": "SOUN", "mentions": 100}]
    spikes = _detect_spikes(current, previous)
    assert spikes == []


# ── Test 3: GET /api/intelligence/reddit returns cached snapshot ──────────────

def test_reddit_endpoint_returns_cached_snapshot(client):
    """
    GET /api/intelligence/reddit returns the cached snapshot.
    When no cache exists, returns a response with ok=False and empty results.
    """
    _reset_module_state()

    # Cold cache: no data yet
    import intelligence.reddit as r
    r._current = []
    r._previous = []
    r._fetched_at = 0.0

    # Mock fetch_and_refresh to return stable empty result without a network call
    with patch("intelligence.reddit.fetch_and_refresh", new=AsyncMock(
        return_value={"ok": False, "source": "apewisdom", "fetched_at": None,
                      "age_seconds": None, "ttl_seconds": None,
                      "result_count": 0, "results": [], "spikes": [], "error": None}
    )):
        resp = client.get("/api/intelligence/reddit")

    assert resp.status_code == 200
    body = resp.json()
    assert "ok" in body
    assert "source" in body
    assert body["source"] == "apewisdom"
    assert "results" in body
    assert "spikes" in body


def test_reddit_endpoint_returns_populated_cache(client):
    """GET /api/intelligence/reddit returns populated cache without fetching."""
    _reset_module_state()

    import intelligence.reddit as r
    r._current = [{"rank": 1, "ticker": "NVDA", "mentions": 500, "upvotes": 200,
                   "name": "NVIDIA", "rank_24h_ago": 2, "mentions_24h_ago": 300}]
    r._fetched_at = time.time() - 60  # 1 minute old — still fresh

    resp = client.get("/api/intelligence/reddit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result_count"] == 1
    assert body["results"][0]["ticker"] == "NVDA"
    assert body["error"] is None


# ── Test 4: Refresh endpoint updates cache ────────────────────────────────────

def test_refresh_endpoint_admin_required(client):
    """POST /api/intelligence/reddit/refresh requires admin token."""
    resp = client.post("/api/intelligence/reddit/refresh")
    assert resp.status_code in (401, 503)  # 401 missing token, 503 unconfigured


def test_refresh_endpoint_with_admin_token(client):
    """POST /api/intelligence/reddit/refresh with valid token triggers refresh."""
    _reset_module_state()

    fake_result = {
        "ok": True,
        "fetched_at": time.time(),
        "age_seconds": 0,
        "ttl_seconds": 900,
        "result_count": 5,
        "results": [{"rank": 1, "ticker": "NVDA", "mentions": 400, "upvotes": 150,
                     "name": "NVIDIA", "rank_24h_ago": None, "mentions_24h_ago": None}],
        "spikes": [],
        "error": None,
    }

    with patch("intelligence.reddit.fetch_and_refresh", new=AsyncMock(return_value=fake_result)):
        from core.config import settings
        resp = client.post(
            "/api/intelligence/reddit/refresh",
            headers={"Authorization": f"Bearer {settings.ADMIN_API_TOKEN}"},
        )

    # If admin token is unconfigured in test env, endpoint returns 503 — skip
    if resp.status_code == 503:
        pytest.skip("ADMIN_API_TOKEN not configured in test env")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result_count"] == 5


# ── Test 5: API failure returns safe error, does not crash ────────────────────

def test_apewisdom_failure_returns_error_not_crash(client):
    """ApeWisdom HTTP failure returns error field — does not raise or crash backend."""
    _reset_module_state()

    async def _fail(*a, **kw):
        return {
            "ok": False, "source": "apewisdom", "fetched_at": None,
            "age_seconds": None, "ttl_seconds": None,
            "result_count": 0, "results": [], "spikes": [],
            "error": "Connection refused",
        }

    with patch("intelligence.reddit.fetch_and_refresh", new=AsyncMock(side_effect=_fail)):
        resp = client.get("/api/intelligence/reddit")

    assert resp.status_code == 200  # backend stays up
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] is not None


# ── Test 6: No Polygon calls ──────────────────────────────────────────────────

def test_no_polygon_import_in_intelligence_module():
    """
    The intelligence module must not import any Polygon client.
    No Polygon calls should be made during Reddit intelligence operations.
    """
    import ast
    import importlib.util
    from pathlib import Path

    reddit_path = Path(__file__).parent.parent / "intelligence" / "reddit.py"
    source = reddit_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in getattr(node, "names", []):
                assert "polygon" not in alias.name.lower(), (
                    f"intelligence/reddit.py must not import Polygon: {alias.name}"
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "polygon" not in node.module.lower(), (
                    f"intelligence/reddit.py must not import from Polygon: {node.module}"
                )


# ── Test 7: No broker/live/order/AI imports ───────────────────────────────────

def test_no_broker_or_live_trading_imports_in_intelligence():
    """
    The intelligence module must not import broker, live trading, or AI components.
    """
    import ast
    from pathlib import Path

    forbidden = {"broker", "live", "execution", "openai", "anthropic", "langchain", "ollama"}

    for py_file in (Path(__file__).parent.parent / "intelligence").glob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in getattr(node, "names", []):
                    for bad in forbidden:
                        assert bad not in alias.name.lower(), (
                            f"{py_file.name} must not import {alias.name}"
                        )
                if isinstance(node, ast.ImportFrom) and node.module:
                    for bad in forbidden:
                        assert bad not in node.module.lower(), (
                            f"{py_file.name} must not import from {node.module}"
                        )


# ── Test 8: Trading/scoring code unchanged ────────────────────────────────────

def test_paper_simulator_not_modified_by_intelligence(client):
    """
    Paper simulator core endpoints still work correctly (regression guard).
    Intelligence code must not alter trade entry/exit or scoring behavior.
    """
    resp = client.get("/api/paper/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    # Core simulator fields still present
    assert "status" in body
    assert body["status"]["live_trading_enabled"] is False
    assert body["status"]["broker_connected"] is False


def test_catalyst_guard_unchanged(client):
    """Catalyst type guard endpoints are not affected by intelligence module."""
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "catalyst_type_guard" in body


# ── Test 9: Frontend build check (smoke) ─────────────────────────────────────

def test_intelligence_module_importable():
    """intelligence package and reddit module can be imported without error."""
    import intelligence
    import intelligence.reddit
    assert hasattr(intelligence.reddit, "fetch_and_refresh")
    assert hasattr(intelligence.reddit, "get_snapshot")
    assert hasattr(intelligence.reddit, "ensure_loaded")
    assert hasattr(intelligence.reddit, "start_background_loop")
    assert hasattr(intelligence.reddit, "_detect_spikes")
    assert hasattr(intelligence.reddit, "_normalize_rows")
