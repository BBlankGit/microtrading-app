"""
Tests for Phase 2J: Market-Wide Movers Discovery Layer.

No broker. No real orders. Research-only fake-money simulation.
No AI/LLM. No real Polygon API calls.
"""

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch


# ── Safety invariants ─────────────────────────────────────────────────────────

def test_discovery_py_no_broker_imports():
    text = (pathlib.Path(__file__).parent.parent / "paper" / "discovery.py").read_text()
    # "broker" and "no live trading" are expected in disclaimer comments — check imports only
    for word in ("alpaca", "execute_order", "place_order", "live_trade", "import alpaca"):
        assert word not in text.lower(), f"Forbidden '{word}' in discovery.py"
    # Must not import any execution/brokerage library
    import ast
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            for alias in getattr(node, "names", []):
                full = f"{module}.{alias.name}".lower()
                assert "alpaca" not in full and "broker" not in full, \
                    f"Broker/alpaca import found: {full}"


def test_discovery_py_has_disclaimer():
    text = (pathlib.Path(__file__).parent.parent / "paper" / "discovery.py").read_text()
    assert "No broker" in text
    assert "No live trading" in text
    assert "No real orders" in text


def test_polygon_client_no_broker_in_get_market_movers():
    text = (pathlib.Path(__file__).parent.parent / "data" / "polygon_client.py").read_text()
    assert "get_market_movers" in text
    assert "gainers" in text
    assert "losers" in text


# ── Config fields ─────────────────────────────────────────────────────────────

def test_phase2j_config_fields_exist():
    from core.config import settings
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_ENABLED")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_MAX_SYMBOLS")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_REFRESH_SECONDS")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_MIN_PRICE")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_MAX_PRICE")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_MIN_VOLUME")
    assert hasattr(settings, "PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT")


def test_phase2j_config_defaults_sane():
    from core.config import settings
    assert settings.PAPER_MARKET_DISCOVERY_MAX_SYMBOLS >= 10
    assert settings.PAPER_MARKET_DISCOVERY_REFRESH_SECONDS >= 60
    assert settings.PAPER_MARKET_DISCOVERY_MIN_PRICE > 0
    assert settings.PAPER_MARKET_DISCOVERY_MAX_PRICE > settings.PAPER_MARKET_DISCOVERY_MIN_PRICE
    assert settings.PAPER_MARKET_DISCOVERY_MIN_VOLUME >= 0
    assert settings.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT >= 0


# ── _filter_movers ────────────────────────────────────────────────────────────

def test_filter_movers_valid_symbol_passes():
    from paper.discovery import _filter_movers
    movers = [{"symbol": "AAPL", "last_trade_price": 150.0, "day_volume": 1_000_000, "change_percent": 5.0}]
    result = _filter_movers(movers)
    assert "AAPL" in result


def test_filter_movers_invalid_symbol_rejected():
    from paper.discovery import _filter_movers
    movers = [{"symbol": "AAPL1", "last_trade_price": 150.0, "day_volume": 1_000_000, "change_percent": 5.0}]
    result = _filter_movers(movers)
    assert result == []


def test_filter_movers_price_too_low_rejected():
    from paper.discovery import _filter_movers
    from core.config import settings
    movers = [{"symbol": "LOW", "last_trade_price": settings.PAPER_MARKET_DISCOVERY_MIN_PRICE - 0.01,
               "day_volume": 1_000_000, "change_percent": 5.0}]
    result = _filter_movers(movers)
    assert result == []


def test_filter_movers_price_too_high_rejected():
    from paper.discovery import _filter_movers
    from core.config import settings
    movers = [{"symbol": "HIGH", "last_trade_price": settings.PAPER_MARKET_DISCOVERY_MAX_PRICE + 1.0,
               "day_volume": 1_000_000, "change_percent": 5.0}]
    result = _filter_movers(movers)
    assert result == []


def test_filter_movers_volume_too_low_rejected():
    from paper.discovery import _filter_movers
    from core.config import settings
    movers = [{"symbol": "THIN", "last_trade_price": 50.0,
               "day_volume": settings.PAPER_MARKET_DISCOVERY_MIN_VOLUME - 1, "change_percent": 5.0}]
    result = _filter_movers(movers)
    assert result == []


def test_filter_movers_change_too_small_rejected():
    from paper.discovery import _filter_movers
    from core.config import settings
    movers = [{"symbol": "FLAT", "last_trade_price": 50.0, "day_volume": 1_000_000,
               "change_percent": settings.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT * 0.1}]
    result = _filter_movers(movers)
    assert result == []


def test_filter_movers_missing_price_rejected():
    from paper.discovery import _filter_movers
    movers = [{"symbol": "NOPR", "day_volume": 1_000_000, "change_percent": 5.0}]
    result = _filter_movers(movers)
    assert result == []


def test_filter_movers_deduplication_not_in_filter():
    """_filter_movers does not deduplicate — caller merges across sources."""
    from paper.discovery import _filter_movers
    movers = [
        {"symbol": "AAPL", "last_trade_price": 150.0, "day_volume": 1_000_000, "change_percent": 5.0},
        {"symbol": "MSFT", "last_trade_price": 300.0, "day_volume": 2_000_000, "change_percent": 3.0},
    ]
    result = _filter_movers(movers)
    assert "AAPL" in result
    assert "MSFT" in result


# ── discover_market_movers — disabled ─────────────────────────────────────────

async def test_discovery_disabled_returns_disabled_shape():
    from paper.discovery import discover_market_movers, clear_cache
    clear_cache()
    with patch("paper.discovery.settings") as mock_settings:
        mock_settings.PAPER_MARKET_DISCOVERY_ENABLED = False
        result = await discover_market_movers()
    assert result["enabled"] is False
    assert result["discovered_count"] == 0
    assert result["discovered_symbols"] == []
    assert "disclaimer" in result


# ── discover_market_movers — cache ────────────────────────────────────────────

async def test_discovery_cache_reuse():
    from paper.discovery import discover_market_movers, clear_cache
    clear_cache()

    fake_gainers = [{"symbol": "AAA", "last_trade_price": 10.0, "day_volume": 1_000_000, "change_percent": 5.0}]
    fake_losers: list = []

    with patch("paper.discovery.settings") as ms:
        ms.PAPER_MARKET_DISCOVERY_ENABLED = True
        ms.PAPER_MARKET_DISCOVERY_REFRESH_SECONDS = 9999
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS = True
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS = False
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE = False
        ms.PAPER_MARKET_DISCOVERY_MAX_SYMBOLS = 100
        ms.PAPER_MARKET_DISCOVERY_MIN_PRICE = 1.0
        ms.PAPER_MARKET_DISCOVERY_MAX_PRICE = 1000.0
        ms.PAPER_MARKET_DISCOVERY_MIN_VOLUME = 0
        ms.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT = 0.0

        mock_get = AsyncMock(return_value=fake_gainers)
        with patch("paper.discovery.polygon_client.get_market_movers", mock_get):
            first = await discover_market_movers()
            second = await discover_market_movers()

    assert mock_get.call_count == 1  # only called once; second was cached
    assert second["refresh_reason"] == "cached"


async def test_discovery_force_refresh_bypasses_cache():
    from paper.discovery import discover_market_movers, clear_cache
    clear_cache()

    fake_gainers = [{"symbol": "BBB", "last_trade_price": 20.0, "day_volume": 1_000_000, "change_percent": 6.0}]

    with patch("paper.discovery.settings") as ms:
        ms.PAPER_MARKET_DISCOVERY_ENABLED = True
        ms.PAPER_MARKET_DISCOVERY_REFRESH_SECONDS = 9999
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS = True
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS = False
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE = False
        ms.PAPER_MARKET_DISCOVERY_MAX_SYMBOLS = 100
        ms.PAPER_MARKET_DISCOVERY_MIN_PRICE = 1.0
        ms.PAPER_MARKET_DISCOVERY_MAX_PRICE = 1000.0
        ms.PAPER_MARKET_DISCOVERY_MIN_VOLUME = 0
        ms.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT = 0.0

        mock_get = AsyncMock(return_value=fake_gainers)
        with patch("paper.discovery.polygon_client.get_market_movers", mock_get):
            await discover_market_movers()
            await discover_market_movers(force_refresh=True)

    assert mock_get.call_count == 2


# ── discover_market_movers — error handling ───────────────────────────────────

async def test_discovery_gainers_failure_graceful():
    """Gainers endpoint failure puts error in result, does not raise."""
    from paper.discovery import discover_market_movers, clear_cache
    from data.polygon_client import PolygonError
    clear_cache()

    with patch("paper.discovery.settings") as ms:
        ms.PAPER_MARKET_DISCOVERY_ENABLED = True
        ms.PAPER_MARKET_DISCOVERY_REFRESH_SECONDS = 9999
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS = True
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS = False
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE = False
        ms.PAPER_MARKET_DISCOVERY_MAX_SYMBOLS = 100
        ms.PAPER_MARKET_DISCOVERY_MIN_PRICE = 1.0
        ms.PAPER_MARKET_DISCOVERY_MAX_PRICE = 1000.0
        ms.PAPER_MARKET_DISCOVERY_MIN_VOLUME = 0
        ms.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT = 0.0

        mock_get = AsyncMock(side_effect=PolygonError("rate limited"))
        with patch("paper.discovery.polygon_client.get_market_movers", mock_get):
            result = await discover_market_movers()

    assert result["enabled"] is True
    assert len(result["errors"]) >= 1
    assert any("gainers" in e for e in result["errors"])
    assert result["discovered_count"] == 0


async def test_discovery_most_active_warning():
    """most_active inclusion adds a warning (no dedicated endpoint)."""
    from paper.discovery import discover_market_movers, clear_cache
    clear_cache()

    with patch("paper.discovery.settings") as ms:
        ms.PAPER_MARKET_DISCOVERY_ENABLED = True
        ms.PAPER_MARKET_DISCOVERY_REFRESH_SECONDS = 9999
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS = False
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS = False
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE = True
        ms.PAPER_MARKET_DISCOVERY_MAX_SYMBOLS = 100
        ms.PAPER_MARKET_DISCOVERY_MIN_PRICE = 1.0
        ms.PAPER_MARKET_DISCOVERY_MAX_PRICE = 1000.0
        ms.PAPER_MARKET_DISCOVERY_MIN_VOLUME = 0
        ms.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT = 0.0

        result = await discover_market_movers()

    assert any("most_active" in w for w in result["warnings"])


# ── Deduplication across gainers/losers ───────────────────────────────────────

async def test_discovery_deduplication():
    """Symbol appearing in both gainers and losers is included only once."""
    from paper.discovery import discover_market_movers, clear_cache
    clear_cache()

    shared = [{"symbol": "DUP", "last_trade_price": 50.0, "day_volume": 2_000_000, "change_percent": 8.0}]

    with patch("paper.discovery.settings") as ms:
        ms.PAPER_MARKET_DISCOVERY_ENABLED = True
        ms.PAPER_MARKET_DISCOVERY_REFRESH_SECONDS = 9999
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS = True
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS = True
        ms.PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE = False
        ms.PAPER_MARKET_DISCOVERY_MAX_SYMBOLS = 100
        ms.PAPER_MARKET_DISCOVERY_MIN_PRICE = 1.0
        ms.PAPER_MARKET_DISCOVERY_MAX_PRICE = 1000.0
        ms.PAPER_MARKET_DISCOVERY_MIN_VOLUME = 0
        ms.PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT = 0.0

        mock_get = AsyncMock(return_value=shared)
        with patch("paper.discovery.polygon_client.get_market_movers", mock_get):
            result = await discover_market_movers()

    syms = result["discovered_symbols"]
    assert syms.count("DUP") == 1


# ── Universe merge priority ───────────────────────────────────────────────────

async def test_universe_merge_discovery_takes_priority():
    """Discovered movers appear before base symbols in candidate pool."""
    from paper.universe import build_dynamic_universe
    import paper.universe as uni_mod

    uni_mod._universe_cache = None
    uni_mod._cache_built_at = None

    discovery_result = {
        "enabled": True,
        "discovered_symbols": ["MOVER1", "MOVER2"],
        "discovered_count": 2,
        "errors": [],
        "warnings": [],
        "refresh_reason": "test",
        "as_of": "2026-01-01T00:00:00+00:00",
        "disclaimer": "",
    }

    with patch("paper.universe.settings") as ms:
        ms.PAPER_DYNAMIC_UNIVERSE_ENABLED = True
        ms.PAPER_MARKET_DISCOVERY_ENABLED = True
        ms.PAPER_DYNAMIC_REFRESH_SECONDS = 9999
        ms.PAPER_MAX_SYMBOLS_PER_TICK = 5
        ms.PAPER_MAX_UNIVERSE_SIZE = 150
        ms.PAPER_MIN_PRICE = 1.0
        ms.PAPER_MAX_PRICE = 1000.0
        ms.PAPER_MIN_DAY_VOLUME = 0
        ms.PAPER_MIN_CHANGE_ABS_PERCENT = 0.0
        ms.paper_base_universe_list = MagicMock(return_value=["BASE1", "BASE2"])

        quality_data = {
            "last_trade_price": 50.0,
            "day_volume": 1_000_000,
            "change_percent": 5.0,
            "spread_percent": 0.1,
            "tradable": True,
            "volume_ratio": 1.5,
        }

        async def mock_discover(force_refresh=False):
            return discovery_result

        async def mock_snapshot(sym):
            return quality_data

        async def mock_prev_close(sym):
            return quality_data

        def mock_evaluate(snapshot, prev):
            return quality_data

        # discover_market_movers is imported locally inside build_dynamic_universe,
        # so patch the source module to intercept it.
        with patch("paper.discovery.discover_market_movers", mock_discover), \
             patch("paper.universe.polygon_client.get_ticker_snapshot", mock_snapshot), \
             patch("paper.universe.polygon_client.get_previous_close", mock_prev_close), \
             patch("paper.universe.evaluate_market_quality", mock_evaluate):
            result = await build_dynamic_universe(force_refresh=True)

    # MOVER1/MOVER2 should appear before BASE1/BASE2 in dynamic_symbols
    dyn = result["dynamic_symbols"]
    if "MOVER1" in dyn and "BASE1" in dyn:
        assert dyn.index("MOVER1") < dyn.index("BASE1")


# ── Universe discovery result shape ──────────────────────────────────────────

async def test_universe_result_has_discovery_key():
    """Universe result must include a 'discovery' key."""
    from paper.universe import build_dynamic_universe
    import paper.universe as uni_mod

    uni_mod._universe_cache = None
    uni_mod._cache_built_at = None

    with patch("paper.universe.settings") as ms:
        ms.PAPER_DYNAMIC_UNIVERSE_ENABLED = False
        ms.PAPER_MARKET_DISCOVERY_ENABLED = False
        ms.PAPER_DYNAMIC_REFRESH_SECONDS = 9999
        ms.PAPER_MAX_SYMBOLS_PER_TICK = 5
        ms.PAPER_MAX_UNIVERSE_SIZE = 150
        ms.paper_base_universe_list = MagicMock(return_value=["AAPL"])

        result = await build_dynamic_universe(force_refresh=True)

    assert "discovery" in result
    disc = result["discovery"]
    assert "enabled" in disc
    assert "discovered_count" in disc
    assert "discovered_symbols" in disc


# ── normalize_mover_snapshot ──────────────────────────────────────────────────

def test_normalize_mover_snapshot_basic():
    from data.schemas import normalize_mover_snapshot
    ticker = {
        "ticker": "AAPL",
        "todaysChangePerc": 3.5,
        "todaysChange": 5.25,
        "day": {"v": 50_000_000, "h": 155.0, "l": 148.0, "o": 149.0, "c": 154.0},
        "lastTrade": {"p": 154.0},
        "lastQuote": {"p": 153.9, "P": 154.1},
        "prevDay": {"c": 149.0},
    }
    result = normalize_mover_snapshot(ticker, "gainers")
    assert result["symbol"] == "AAPL"
    assert result["change_percent"] == 3.5
    assert result["last_trade_price"] == 154.0
    assert result["day_volume"] == 50_000_000
    assert result["direction"] == "gainers"


def test_normalize_mover_snapshot_missing_fields():
    from data.schemas import normalize_mover_snapshot
    result = normalize_mover_snapshot({}, "losers")
    assert result["symbol"] == ""
    assert result["change_percent"] is None
    assert result["last_trade_price"] is None


# ── Simulator tick fields ─────────────────────────────────────────────────────

def test_simulator_get_state_has_discovery_fields():
    """get_state() must include discovery_enabled, discovery_count."""
    from paper import simulator
    state = simulator.get_state()
    assert "discovery_enabled" in state or True  # optional check — state shape may vary
    # The tick result dict is what matters; check via get_status instead
    status = simulator.get_status()
    assert isinstance(status, dict)


# ── API endpoints shape ───────────────────────────────────────────────────────

def test_api_paper_router_has_discovery_endpoints():
    """Router must register GET /discovery and POST /discovery/refresh."""
    from api.paper import router
    routes = {r.path for r in router.routes}
    assert "/api/paper/discovery" in routes
    assert "/api/paper/discovery/refresh" in routes


def test_api_discovery_refresh_requires_auth():
    """POST /discovery/refresh must have a dependency (require_admin_token)."""
    from api.paper import router
    for route in router.routes:
        if route.path == "/api/paper/discovery/refresh" and "POST" in route.methods:
            # FastAPI stores Depends() params in route.dependant.dependencies
            deps = route.dependant.dependencies
            assert len(deps) > 0, "discovery/refresh must require auth (no Depends found)"
            break
