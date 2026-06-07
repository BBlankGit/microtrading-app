"""
Tests for Phase 2H: Market Regime Monitor.

No broker. No real orders. Research-only fake-money simulation.
No real Polygon API calls. All external calls are mocked.
"""

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch


# ── Safety: no broker/live-trading in new files ───────────────────────────────

def test_regime_py_no_broker():
    text = (pathlib.Path(__file__).parent.parent / "market" / "regime.py").read_text()
    for word in ("alpaca", "execute_order", "place_order", "openai", "anthropic", "langchain"):
        assert word not in text.lower(), f"Forbidden '{word}' in market/regime.py"


def test_regime_api_py_no_broker():
    text = (pathlib.Path(__file__).parent.parent / "api" / "market_regime.py").read_text()
    for word in ("alpaca", "execute_order", "place_order", "openai", "anthropic", "langchain"):
        assert word not in text.lower(), f"Forbidden '{word}' in api/market_regime.py"


def test_regime_py_has_disclaimer():
    text = (pathlib.Path(__file__).parent.parent / "market" / "regime.py").read_text()
    assert "No broker" in text or "no broker" in text.lower()
    assert "No live trading" in text or "no live trading" in text.lower()


# ── Config fields present ─────────────────────────────────────────────────────

def test_config_has_market_regime_enabled():
    from core.config import settings
    assert hasattr(settings, "MARKET_REGIME_ENABLED")
    assert isinstance(settings.MARKET_REGIME_ENABLED, bool)


def test_config_has_market_regime_symbols():
    from core.config import settings
    assert hasattr(settings, "MARKET_REGIME_SYMBOLS")
    symbols = [s.strip() for s in settings.MARKET_REGIME_SYMBOLS.split(",") if s.strip()]
    assert len(symbols) >= 5


def test_config_market_regime_symbols_valid_format():
    from core.config import settings
    import re
    pattern = re.compile(r"^[A-Z]{1,5}$")
    symbols = [s.strip() for s in settings.MARKET_REGIME_SYMBOLS.split(",") if s.strip()]
    for sym in symbols:
        assert pattern.match(sym), f"Symbol '{sym}' fails polygon regex"


def test_config_has_market_regime_refresh_seconds():
    from core.config import settings
    assert hasattr(settings, "MARKET_REGIME_REFRESH_SECONDS")
    assert settings.MARKET_REGIME_REFRESH_SECONDS > 0


def test_config_has_min_risk_on_score():
    from core.config import settings
    assert hasattr(settings, "MARKET_REGIME_MIN_RISK_ON_SCORE")
    assert 0 < settings.MARKET_REGIME_MIN_RISK_ON_SCORE <= 100


def test_config_has_max_risk_off_score():
    from core.config import settings
    assert hasattr(settings, "MARKET_REGIME_MAX_RISK_OFF_SCORE")
    assert 0 <= settings.MARKET_REGIME_MAX_RISK_OFF_SCORE < 100


def test_config_risk_thresholds_are_ordered():
    from core.config import settings
    assert settings.MARKET_REGIME_MAX_RISK_OFF_SCORE < settings.MARKET_REGIME_MIN_RISK_ON_SCORE


# ── clear_cache ───────────────────────────────────────────────────────────────

def test_clear_cache_resets_state():
    from market import regime as _regime
    _regime._cache = {"regime": "risk_on"}
    _regime._cache_time = 123.0
    _regime.clear_cache()
    assert _regime._cache is None
    assert _regime._cache_time is None


# ── _compute_breadth ─────────────────────────────────────────────────────────

def test_compute_breadth_empty():
    from market.regime import _compute_breadth
    result = _compute_breadth({})
    assert result["total"] == 0
    assert result["positive"] == 0
    assert result["positive_percent"] is None
    assert result["avg_change_percent"] is None


def test_compute_breadth_all_positive():
    from market.regime import _compute_breadth
    snaps = {
        "SPY": {"change_percent": 1.2},
        "QQQ": {"change_percent": 0.8},
        "IWM": {"change_percent": 0.5},
    }
    result = _compute_breadth(snaps)
    assert result["total"] == 3
    assert result["positive"] == 3
    assert result["negative"] == 0
    assert result["positive_percent"] == 100.0


def test_compute_breadth_all_negative():
    from market.regime import _compute_breadth
    snaps = {
        "SPY": {"change_percent": -1.2},
        "QQQ": {"change_percent": -0.8},
    }
    result = _compute_breadth(snaps)
    assert result["positive"] == 0
    assert result["negative"] == 2
    assert result["positive_percent"] == 0.0


def test_compute_breadth_mixed():
    from market.regime import _compute_breadth
    snaps = {
        "SPY": {"change_percent": 1.0},
        "QQQ": {"change_percent": -0.5},
        "IWM": {"change_percent": 0.05},   # flat (< 0.1 threshold)
        "DIA": {"change_percent": 0.8},
    }
    result = _compute_breadth(snaps)
    assert result["total"] == 4
    assert result["positive"] == 2
    assert result["negative"] == 1
    assert result["flat"] == 1
    assert result["positive_percent"] == 50.0


def test_compute_breadth_skips_none_change():
    from market.regime import _compute_breadth
    snaps = {
        "SPY": {"change_percent": None},
        "QQQ": {"change_percent": 1.0},
    }
    result = _compute_breadth(snaps)
    # total reflects number of snapshots, but changes are counted only when non-None
    assert result["total"] == 2
    assert result["positive"] == 1
    assert result["avg_change_percent"] == 1.0


# ── _compute_leaders ─────────────────────────────────────────────────────────

def test_compute_leaders_all_missing():
    from market.regime import _compute_leaders
    result = _compute_leaders({})
    assert result["bullish_count"] == 0
    assert result["bearish_count"] == 0
    assert result["data"]["SPY"] is None
    assert result["data"]["QQQ"] is None
    assert result["data"]["IWM"] is None


def test_compute_leaders_all_bullish():
    from market.regime import _compute_leaders
    snaps = {
        "SPY": {"change_percent": 1.2, "last_trade_price": 530.0},
        "QQQ": {"change_percent": 0.9, "last_trade_price": 450.0},
        "IWM": {"change_percent": 0.5, "last_trade_price": 220.0},
    }
    result = _compute_leaders(snaps)
    assert result["bullish_count"] == 3
    assert result["bearish_count"] == 0
    assert result["data"]["SPY"]["change_percent"] == 1.2
    assert result["data"]["SPY"]["last_trade_price"] == 530.0


def test_compute_leaders_mixed():
    from market.regime import _compute_leaders
    snaps = {
        "SPY": {"change_percent": -1.0, "last_trade_price": 520.0},
        "QQQ": {"change_percent": 0.8, "last_trade_price": 440.0},
        # IWM missing
    }
    result = _compute_leaders(snaps)
    assert result["bullish_count"] == 1
    assert result["bearish_count"] == 1
    assert result["data"]["IWM"] is None


# ── _compute_risk ─────────────────────────────────────────────────────────────

def test_compute_risk_risk_on():
    from market.regime import _compute_risk
    breadth = {
        "total": 10, "positive": 9, "negative": 1, "flat": 0,
        "positive_percent": 90.0, "avg_change_percent": 0.8,
    }
    leaders = {"data": {}, "bullish_count": 3, "bearish_count": 0}
    risk = _compute_risk(breadth, leaders, "high")
    assert risk["regime"] == "risk_on"
    assert risk["risk_on_score"] >= 60
    assert risk["confidence"] == "high"


def test_compute_risk_risk_off():
    from market.regime import _compute_risk
    breadth = {
        "total": 10, "positive": 1, "negative": 9, "flat": 0,
        "positive_percent": 10.0, "avg_change_percent": -0.9,
    }
    leaders = {"data": {}, "bullish_count": 0, "bearish_count": 3}
    risk = _compute_risk(breadth, leaders, "high")
    assert risk["regime"] == "risk_off"
    assert risk["risk_on_score"] <= 40


def test_compute_risk_neutral():
    from market.regime import _compute_risk
    breadth = {
        "total": 10, "positive": 5, "negative": 5, "flat": 0,
        "positive_percent": 50.0, "avg_change_percent": 0.0,
    }
    leaders = {"data": {}, "bullish_count": 1, "bearish_count": 1}
    risk = _compute_risk(breadth, leaders, "medium")
    assert risk["regime"] == "neutral"
    assert 40 < risk["risk_on_score"] < 60


def test_compute_risk_score_clamped_0_100():
    from market.regime import _compute_risk
    breadth = {
        "total": 10, "positive": 10, "negative": 0, "flat": 0,
        "positive_percent": 100.0, "avg_change_percent": 2.0,
    }
    leaders = {"data": {}, "bullish_count": 3, "bearish_count": 0}
    risk = _compute_risk(breadth, leaders, "high")
    assert 0 <= risk["risk_on_score"] <= 100


def test_compute_risk_no_breadth_data():
    from market.regime import _compute_risk
    breadth = {
        "total": 0, "positive": 0, "negative": 0, "flat": 0,
        "positive_percent": None, "avg_change_percent": None,
    }
    leaders = {"data": {}, "bullish_count": 0, "bearish_count": 0}
    risk = _compute_risk(breadth, leaders, "unknown")
    assert risk["risk_on_score"] is not None
    assert 0 <= risk["risk_on_score"] <= 100


# ── _data_confidence ─────────────────────────────────────────────────────────

def test_data_confidence_high():
    from market.regime import _data_confidence
    assert _data_confidence(1.0) == "high"
    assert _data_confidence(0.8) == "high"


def test_data_confidence_medium():
    from market.regime import _data_confidence
    assert _data_confidence(0.6) == "medium"
    assert _data_confidence(0.5) == "medium"


def test_data_confidence_low():
    from market.regime import _data_confidence
    assert _data_confidence(0.3) == "low"
    assert _data_confidence(0.25) == "low"


def test_data_confidence_unknown():
    from market.regime import _data_confidence
    assert _data_confidence(0.0) == "unknown"
    assert _data_confidence(0.1) == "unknown"


# ── get_market_regime: caching ────────────────────────────────────────────────

async def test_get_market_regime_uses_cache(monkeypatch):
    import time
    from market import regime as _regime
    _regime._cache = {
        "symbols_requested": ["SPY"],
        "symbols_fetched": ["SPY"],
        "symbols_failed": [],
        "fetch_ratio": 1.0,
        "breadth": _regime._empty_breadth(),
        "leaders": _regime._empty_leaders(),
        "risk": {"regime": "risk_on", "risk_on_score": 75, "confidence": "high", "fetched_count": 1},
        "as_of": "2026-01-01T00:00:00+00:00",
        "disclaimer": _regime.DISCLAIMER,
    }
    _regime._cache_time = time.monotonic()  # just set

    build_called = {"n": 0}
    async def mock_build():
        build_called["n"] += 1
        return dict(_regime._cache)
    monkeypatch.setattr(_regime, "_build_regime", mock_build)

    result = await _regime.get_market_regime()
    assert result["risk"]["regime"] == "risk_on"
    assert build_called["n"] == 0  # cache hit


async def test_get_market_regime_cache_miss_calls_build(monkeypatch):
    from market import regime as _regime
    _regime._cache = None
    _regime._cache_time = None

    fake_result = {
        "symbols_requested": ["SPY"],
        "symbols_fetched": ["SPY"],
        "symbols_failed": [],
        "fetch_ratio": 1.0,
        "breadth": _regime._empty_breadth(),
        "leaders": _regime._empty_leaders(),
        "risk": {"regime": "neutral", "risk_on_score": 50, "confidence": "high", "fetched_count": 1},
        "as_of": "2026-01-01T00:00:00+00:00",
        "disclaimer": _regime.DISCLAIMER,
    }
    build_called = {"n": 0}
    async def mock_build():
        build_called["n"] += 1
        return fake_result
    monkeypatch.setattr(_regime, "_build_regime", mock_build)

    result = await _regime.get_market_regime()
    assert result["risk"]["regime"] == "neutral"
    assert build_called["n"] == 1


async def test_get_market_regime_force_refresh_bypasses_cache(monkeypatch):
    import time
    from market import regime as _regime
    _regime._cache = {
        "risk": {"regime": "risk_on", "risk_on_score": 80, "confidence": "high", "fetched_count": 5},
        "as_of": "2026-01-01T00:00:00+00:00",
        "disclaimer": _regime.DISCLAIMER,
    }
    _regime._cache_time = time.monotonic()  # fresh cache

    fresh_result = {
        "symbols_requested": ["SPY"],
        "symbols_fetched": ["SPY"],
        "symbols_failed": [],
        "fetch_ratio": 1.0,
        "breadth": _regime._empty_breadth(),
        "leaders": _regime._empty_leaders(),
        "risk": {"regime": "risk_off", "risk_on_score": 30, "confidence": "high", "fetched_count": 1},
        "as_of": "2026-01-01T01:00:00+00:00",
        "disclaimer": _regime.DISCLAIMER,
    }
    build_called = {"n": 0}
    async def mock_build():
        build_called["n"] += 1
        return fresh_result
    monkeypatch.setattr(_regime, "_build_regime", mock_build)

    result = await _regime.get_market_regime(force_refresh=True)
    assert result["risk"]["regime"] == "risk_off"
    assert build_called["n"] == 1


async def test_get_market_regime_returns_error_payload_on_exception(monkeypatch):
    from market import regime as _regime
    _regime._cache = None
    _regime._cache_time = None

    async def mock_build():
        raise RuntimeError("polygon down")
    monkeypatch.setattr(_regime, "_build_regime", mock_build)

    result = await _regime.get_market_regime()
    assert "error" in result
    assert "polygon down" in result["error"]
    assert result["risk"]["regime"] == "unknown"


# ── _build_regime with mocked polygon ────────────────────────────────────────

async def test_build_regime_mocks_polygon(monkeypatch):
    from market import regime as _regime
    import core.config as _cfg

    fake_settings = MagicMock()
    fake_settings.MARKET_REGIME_SYMBOLS = "SPY,QQQ,IWM"
    fake_settings.MARKET_REGIME_REFRESH_SECONDS = 60
    fake_settings.MARKET_REGIME_MIN_RISK_ON_SCORE = 60
    fake_settings.MARKET_REGIME_MAX_RISK_OFF_SCORE = 40
    monkeypatch.setattr(_cfg, "settings", fake_settings)
    monkeypatch.setattr(_regime, "settings", fake_settings)

    async def mock_snapshot(sym):
        return {"symbol": sym, "change_percent": 0.8, "last_trade_price": 100.0}

    from data import polygon_client
    monkeypatch.setattr(polygon_client, "get_ticker_snapshot", mock_snapshot)

    result = await _regime._build_regime()
    assert "breadth" in result
    assert "leaders" in result
    assert "risk" in result
    assert result["breadth"]["total"] == 3
    assert result["breadth"]["positive"] == 3
    assert result["risk"]["regime"] == "risk_on"
    assert result["fetch_ratio"] == 1.0


async def test_build_regime_handles_partial_failures(monkeypatch):
    from market import regime as _regime
    import core.config as _cfg
    from data.polygon_client import PolygonError

    fake_settings = MagicMock()
    fake_settings.MARKET_REGIME_SYMBOLS = "SPY,QQQ,FAIL"
    fake_settings.MARKET_REGIME_REFRESH_SECONDS = 60
    fake_settings.MARKET_REGIME_MIN_RISK_ON_SCORE = 60
    fake_settings.MARKET_REGIME_MAX_RISK_OFF_SCORE = 40
    monkeypatch.setattr(_cfg, "settings", fake_settings)
    monkeypatch.setattr(_regime, "settings", fake_settings)

    async def mock_snapshot(sym):
        if sym == "FAIL":
            raise PolygonError("not found")
        return {"symbol": sym, "change_percent": 1.0, "last_trade_price": 100.0}

    from data import polygon_client
    monkeypatch.setattr(polygon_client, "get_ticker_snapshot", mock_snapshot)

    result = await _regime._build_regime()
    assert "FAIL" in result["symbols_failed"]
    assert "SPY" in result["symbols_fetched"]
    assert "QQQ" in result["symbols_fetched"]
    assert result["breadth"]["total"] == 2
    assert round(result["fetch_ratio"], 2) == round(2 / 3, 2)


# ── API endpoint structure ────────────────────────────────────────────────────

async def test_regime_api_get_returns_expected_keys(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    import core.config as _cfg

    fake_settings = MagicMock()
    fake_settings.MARKET_REGIME_ENABLED = True
    fake_settings.MARKET_REGIME_SYMBOLS = "SPY,QQQ"
    fake_settings.MARKET_REGIME_REFRESH_SECONDS = 60
    fake_settings.MARKET_REGIME_MIN_RISK_ON_SCORE = 60
    fake_settings.MARKET_REGIME_MAX_RISK_OFF_SCORE = 40
    # Keep other settings accessible
    from core.config import settings as real_settings
    fake_settings.ADMIN_API_TOKEN = real_settings.ADMIN_API_TOKEN
    fake_settings.allowed_origins_list = real_settings.allowed_origins_list
    monkeypatch.setattr(_cfg, "settings", fake_settings)

    from market import regime as _regime
    _regime._cache = None
    _regime._cache_time = None

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": ["SPY", "QQQ"],
            "symbols_fetched": ["SPY", "QQQ"],
            "symbols_failed": [],
            "fetch_ratio": 1.0,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "neutral", "risk_on_score": 50, "confidence": "high", "fetched_count": 2},
            "as_of": "2026-01-01T00:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    client = TestClient(app)
    resp = client.get("/api/market/regime")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("enabled", "breadth", "leaders", "risk", "as_of", "disclaimer"):
        assert key in data, f"Missing key: {key}"


async def test_regime_api_get_no_auth_required(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": [],
            "symbols_fetched": [],
            "symbols_failed": [],
            "fetch_ratio": 0.0,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "unknown", "risk_on_score": None, "confidence": "unknown", "fetched_count": 0},
            "as_of": "2026-01-01T00:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    client = TestClient(app)
    resp = client.get("/api/market/regime")
    # Must succeed without auth header
    assert resp.status_code == 200


def test_regime_refresh_requires_auth():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.post("/api/market/regime/refresh")
    # No auth → 401 or 503
    assert resp.status_code in (401, 503)


async def test_regime_api_disabled_returns_enabled_false(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    import core.config as _cfg
    import api.market_regime as _market_regime_api

    fake_settings = MagicMock()
    fake_settings.MARKET_REGIME_ENABLED = False
    from core.config import settings as real_settings
    fake_settings.ADMIN_API_TOKEN = real_settings.ADMIN_API_TOKEN
    fake_settings.allowed_origins_list = real_settings.allowed_origins_list
    monkeypatch.setattr(_cfg, "settings", fake_settings)
    monkeypatch.setattr(_market_regime_api, "settings", fake_settings)

    client = TestClient(app)
    resp = client.get("/api/market/regime")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False


# ── Monitoring endpoint includes market_regime ────────────────────────────────

async def test_monitoring_status_includes_market_regime_key(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": ["SPY"],
            "symbols_fetched": ["SPY"],
            "symbols_failed": [],
            "fetch_ratio": 1.0,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "neutral", "risk_on_score": 52, "confidence": "high", "fetched_count": 1},
            "as_of": "2026-01-01T00:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    client = TestClient(app)
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "market_regime" in data


async def test_monitoring_warns_regime_risk_off(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": ["SPY"],
            "symbols_fetched": ["SPY"],
            "symbols_failed": [],
            "fetch_ratio": 1.0,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "risk_off", "risk_on_score": 25, "confidence": "high", "fetched_count": 10},
            "as_of": "2026-01-01T00:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    client = TestClient(app)
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200
    data = resp.json()
    warnings = data.get("warnings", [])
    regime_warn = [w for w in warnings if "RISK_OFF" in w or "risk_off" in w.lower()]
    assert len(regime_warn) >= 1


async def test_monitoring_warns_low_confidence(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": ["SPY", "QQQ"],
            "symbols_fetched": ["SPY"],
            "symbols_failed": ["QQQ"],
            "fetch_ratio": 0.5,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "neutral", "risk_on_score": 50, "confidence": "low", "fetched_count": 1},
            "as_of": "2026-01-01T00:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    client = TestClient(app)
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200
    warnings = resp.json().get("warnings", [])
    conf_warn = [w for w in warnings if "confidence" in w.lower()]
    assert len(conf_warn) >= 1


# ── Dashboard endpoint includes market_regime ─────────────────────────────────

async def test_paper_dashboard_includes_market_regime_key(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": ["SPY"],
            "symbols_fetched": ["SPY"],
            "symbols_failed": [],
            "fetch_ratio": 1.0,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "risk_on", "risk_on_score": 70, "confidence": "high", "fetched_count": 1},
            "as_of": "2026-01-01T00:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    client = TestClient(app)
    resp = client.get("/api/paper/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "market_regime" in data


# ── Simulator tick includes market_regime ─────────────────────────────────────

async def test_simulator_tick_result_has_market_regime_key(monkeypatch):
    from paper import simulator
    import core.config as _cfg
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    fake_settings = MagicMock()
    fake_settings.MARKET_REGIME_ENABLED = True
    fake_settings.MARKET_REGIME_SYMBOLS = "SPY"
    fake_settings.MARKET_REGIME_REFRESH_SECONDS = 60
    fake_settings.MARKET_REGIME_MIN_RISK_ON_SCORE = 60
    fake_settings.MARKET_REGIME_MAX_RISK_OFF_SCORE = 40
    from core.config import settings as real_settings
    fake_settings.PAPER_POLL_INTERVAL_SECONDS = real_settings.PAPER_POLL_INTERVAL_SECONDS
    fake_settings.PAPER_MAX_POSITIONS = real_settings.PAPER_MAX_POSITIONS
    fake_settings.PAPER_MAX_TRADES_PER_DAY = real_settings.PAPER_MAX_TRADES_PER_DAY
    fake_settings.PAPER_MAX_POSITION_SIZE_USD = real_settings.PAPER_MAX_POSITION_SIZE_USD
    fake_settings.PAPER_TAKE_PROFIT_PERCENT = real_settings.PAPER_TAKE_PROFIT_PERCENT
    fake_settings.PAPER_STOP_LOSS_PERCENT = real_settings.PAPER_STOP_LOSS_PERCENT
    fake_settings.PAPER_MAX_HOLD_MINUTES = real_settings.PAPER_MAX_HOLD_MINUTES
    fake_settings.PAPER_STARTING_CASH = real_settings.PAPER_STARTING_CASH
    fake_settings.DATABASE_URL = ""
    fake_settings.paper_base_universe_list = real_settings.paper_base_universe_list
    fake_settings.PAPER_MAX_SYMBOLS_PER_TICK = 2

    monkeypatch.setattr(_cfg, "settings", fake_settings)

    async def mock_get_universe():
        return {"active_symbols": ["SPY"], "active_count": 1,
                "last_refreshed_at": None, "refresh_reason": "test"}

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": ["SPY"],
            "symbols_fetched": ["SPY"],
            "symbols_failed": [],
            "fetch_ratio": 1.0,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "neutral", "risk_on_score": 55, "confidence": "high", "fetched_count": 1},
            "as_of": "2026-01-01T00:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }

    from paper import universe as _uni
    monkeypatch.setattr(_uni, "get_active_paper_universe", mock_get_universe)
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    from data import polygon_client
    async def mock_snapshot(sym):
        return {"symbol": sym, "change_percent": 0.5, "tradable": False,
                "bid": 100.0, "ask": 100.1, "last_trade_price": 100.0,
                "rejection_reasons": ["test"]}
    async def mock_prev_close(sym):
        return {"symbol": sym, "close": 99.5}
    monkeypatch.setattr(polygon_client, "get_ticker_snapshot", mock_snapshot)
    monkeypatch.setattr(polygon_client, "get_previous_close", mock_prev_close)

    from paper import journal as _journal
    monkeypatch.setattr(_journal, "_journal_enabled", False)

    result = await simulator.run_tick()
    assert "market_regime" in result


# ── Regime summary in tick result ─────────────────────────────────────────────

async def test_tick_market_regime_contains_expected_fields(monkeypatch):
    from paper import simulator
    import core.config as _cfg
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    fake_settings = MagicMock()
    fake_settings.MARKET_REGIME_ENABLED = True
    fake_settings.MARKET_REGIME_SYMBOLS = "SPY"
    fake_settings.MARKET_REGIME_REFRESH_SECONDS = 60
    fake_settings.MARKET_REGIME_MIN_RISK_ON_SCORE = 60
    fake_settings.MARKET_REGIME_MAX_RISK_OFF_SCORE = 40
    from core.config import settings as real_settings
    fake_settings.PAPER_POLL_INTERVAL_SECONDS = real_settings.PAPER_POLL_INTERVAL_SECONDS
    fake_settings.PAPER_MAX_POSITIONS = real_settings.PAPER_MAX_POSITIONS
    fake_settings.PAPER_MAX_TRADES_PER_DAY = real_settings.PAPER_MAX_TRADES_PER_DAY
    fake_settings.PAPER_MAX_POSITION_SIZE_USD = real_settings.PAPER_MAX_POSITION_SIZE_USD
    fake_settings.PAPER_TAKE_PROFIT_PERCENT = real_settings.PAPER_TAKE_PROFIT_PERCENT
    fake_settings.PAPER_STOP_LOSS_PERCENT = real_settings.PAPER_STOP_LOSS_PERCENT
    fake_settings.PAPER_MAX_HOLD_MINUTES = real_settings.PAPER_MAX_HOLD_MINUTES
    fake_settings.PAPER_STARTING_CASH = real_settings.PAPER_STARTING_CASH
    fake_settings.DATABASE_URL = ""
    fake_settings.paper_base_universe_list = real_settings.paper_base_universe_list
    fake_settings.PAPER_MAX_SYMBOLS_PER_TICK = 1

    monkeypatch.setattr(_cfg, "settings", fake_settings)

    async def mock_get_universe():
        return {"active_symbols": ["SPY"], "active_count": 1,
                "last_refreshed_at": None, "refresh_reason": "test"}

    async def mock_get_regime(force_refresh=False):
        return {
            "symbols_requested": ["SPY"],
            "symbols_fetched": ["SPY"],
            "symbols_failed": [],
            "fetch_ratio": 1.0,
            "breadth": _regime._empty_breadth(),
            "leaders": _regime._empty_leaders(),
            "risk": {"regime": "risk_on", "risk_on_score": 72, "confidence": "high", "fetched_count": 1},
            "as_of": "2026-06-07T12:00:00+00:00",
            "disclaimer": _regime.DISCLAIMER,
        }

    from paper import universe as _uni
    monkeypatch.setattr(_uni, "get_active_paper_universe", mock_get_universe)
    monkeypatch.setattr(_regime, "get_market_regime", mock_get_regime)

    from data import polygon_client
    async def mock_snapshot(sym):
        return {"symbol": sym, "change_percent": 0.5, "tradable": False,
                "bid": 100.0, "ask": 100.1, "last_trade_price": 100.0,
                "rejection_reasons": ["test"]}
    async def mock_prev_close(sym):
        return {"symbol": sym, "close": 99.5}
    monkeypatch.setattr(polygon_client, "get_ticker_snapshot", mock_snapshot)
    monkeypatch.setattr(polygon_client, "get_previous_close", mock_prev_close)

    from paper import journal as _journal
    monkeypatch.setattr(_journal, "_journal_enabled", False)

    result = await simulator.run_tick()
    mr = result.get("market_regime")
    assert mr is not None
    assert "regime" in mr
    assert "risk_on_score" in mr
    assert "confidence" in mr
    assert "as_of" in mr
    assert mr["regime"] == "risk_on"


# ── Regime disabled: tick result market_regime is None ────────────────────────

async def test_tick_market_regime_none_when_disabled(monkeypatch):
    from paper import simulator
    import core.config as _cfg
    from market import regime as _regime

    _regime._cache = None
    _regime._cache_time = None

    fake_settings = MagicMock()
    fake_settings.MARKET_REGIME_ENABLED = False
    from core.config import settings as real_settings
    fake_settings.PAPER_POLL_INTERVAL_SECONDS = real_settings.PAPER_POLL_INTERVAL_SECONDS
    fake_settings.PAPER_MAX_POSITIONS = real_settings.PAPER_MAX_POSITIONS
    fake_settings.PAPER_MAX_TRADES_PER_DAY = real_settings.PAPER_MAX_TRADES_PER_DAY
    fake_settings.PAPER_MAX_POSITION_SIZE_USD = real_settings.PAPER_MAX_POSITION_SIZE_USD
    fake_settings.PAPER_TAKE_PROFIT_PERCENT = real_settings.PAPER_TAKE_PROFIT_PERCENT
    fake_settings.PAPER_STOP_LOSS_PERCENT = real_settings.PAPER_STOP_LOSS_PERCENT
    fake_settings.PAPER_MAX_HOLD_MINUTES = real_settings.PAPER_MAX_HOLD_MINUTES
    fake_settings.PAPER_STARTING_CASH = real_settings.PAPER_STARTING_CASH
    fake_settings.DATABASE_URL = ""
    fake_settings.paper_base_universe_list = real_settings.paper_base_universe_list
    fake_settings.PAPER_MAX_SYMBOLS_PER_TICK = 1

    monkeypatch.setattr(_cfg, "settings", fake_settings)

    async def mock_get_universe():
        return {"active_symbols": ["SPY"], "active_count": 1,
                "last_refreshed_at": None, "refresh_reason": "test"}

    from paper import universe as _uni
    monkeypatch.setattr(_uni, "get_active_paper_universe", mock_get_universe)

    from data import polygon_client
    async def mock_snapshot(sym):
        return {"symbol": sym, "change_percent": 0.5, "tradable": False,
                "bid": 100.0, "ask": 100.1, "last_trade_price": 100.0,
                "rejection_reasons": ["test"]}
    async def mock_prev_close(sym):
        return {"symbol": sym, "close": 99.5}
    monkeypatch.setattr(polygon_client, "get_ticker_snapshot", mock_snapshot)
    monkeypatch.setattr(polygon_client, "get_previous_close", mock_prev_close)

    from paper import journal as _journal
    monkeypatch.setattr(_journal, "_journal_enabled", False)

    result = await simulator.run_tick()
    assert result.get("market_regime") is None
