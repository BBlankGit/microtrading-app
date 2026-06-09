"""
Phase D4: Dynamic symbol universe coverage for the shared market-data collector.
No broker. No live trading. No real orders. No real-money execution.
No AI/LLM/Ollama. All Polygon calls mocked.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.config import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _patch_universe(
    paper_enabled=False,
    v5_enabled=False,
    base="AMD",
    extra="",
    v5="",
    v5_file="",
    max_syms=100,
    positions_provider=None,
):
    """Context manager that patches all universe config to known values."""
    import contextlib, marketdata.universe_builder as _ub

    orig_provider = _ub._positions_provider

    @contextlib.contextmanager
    def _ctx():
        _ub._positions_provider = positions_provider
        try:
            with (
                patch.object(settings, "MARKETDATA_INCLUDE_PAPER_UNIVERSE", paper_enabled),
                patch.object(settings, "MARKETDATA_INCLUDE_V5_UNIVERSE", v5_enabled),
                patch.object(settings, "MARKETDATA_V5_SYMBOLS", v5),
                patch.object(settings, "MARKETDATA_V5_SYMBOLS_FILE", v5_file),
                patch.object(settings, "MARKETDATA_BASE_SYMBOLS", base),
                patch.object(settings, "MARKETDATA_EXTRA_SYMBOLS", extra),
                patch.object(settings, "MARKETDATA_MAX_SYMBOLS_PER_CYCLE", max_syms),
            ):
                yield
        finally:
            _ub._positions_provider = orig_provider

    return _ctx()


# ── Test 1: Universe merge and de-duplication ─────────────────────────────────

def test_universe_deduplication():
    """A symbol appearing in multiple tiers appears exactly once."""
    from marketdata.universe_builder import build_collector_universe

    with _patch_universe(v5_enabled=True, v5="AMD,TSLA", base="AMD,NVDA"):
        syms, info = build_collector_universe()

    assert syms.count("AMD") == 1
    assert len(syms) == len(set(syms)), "Duplicate symbols found"


# ── Test 2: Paper universe included when enabled ──────────────────────────────

def test_paper_universe_included_when_enabled():
    """Paper active symbols are merged when MARKETDATA_INCLUDE_PAPER_UNIVERSE=true."""
    from marketdata.universe_builder import build_collector_universe

    paper_syms = ["PLTR", "RKLB", "COIN"]

    with (
        _patch_universe(paper_enabled=True, base="AMD"),
        patch(
            "marketdata.universe_builder._get_paper_universe_symbols",
            return_value=paper_syms,
        ),
    ):
        syms, info = build_collector_universe()

    for s in paper_syms:
        assert s in syms
    assert info["paper_universe_count"] == len(paper_syms)


# ── Test 3: Paper universe excluded when disabled ─────────────────────────────

def test_paper_universe_excluded_when_disabled():
    """Paper symbols are NOT merged when MARKETDATA_INCLUDE_PAPER_UNIVERSE=false."""
    from marketdata.universe_builder import build_collector_universe

    with _patch_universe(paper_enabled=False, base="AMD"):
        syms, info = build_collector_universe()

    assert info["paper_universe_count"] == 0


# ── Test 4: V5 symbols included when enabled ─────────────────────────────────

def test_v5_symbols_included_when_enabled():
    """V5 tickers are merged when MARKETDATA_INCLUDE_V5_UNIVERSE=true."""
    from marketdata.universe_builder import build_collector_universe

    with _patch_universe(v5_enabled=True, v5="RKLB,IONQ,QQQ", base=""):
        syms, info = build_collector_universe()

    assert "RKLB" in syms
    assert "IONQ" in syms
    assert "QQQ" in syms
    assert info["v5_symbols_count"] == 3


# ── Test 5: V5 symbols excluded when disabled ─────────────────────────────────

def test_v5_symbols_excluded_when_disabled():
    """V5 tickers are NOT merged when MARKETDATA_INCLUDE_V5_UNIVERSE=false."""
    from marketdata.universe_builder import build_collector_universe

    with _patch_universe(v5_enabled=False, base="AMD"):
        syms, info = build_collector_universe()

    assert info["v5_symbols_count"] == 0


# ── Test 6: Extra symbols included ───────────────────────────────────────────

def test_extra_symbols_included():
    """MARKETDATA_EXTRA_SYMBOLS appear in the collector universe (Tier 3)."""
    from marketdata.universe_builder import build_collector_universe

    with _patch_universe(base="AMD", extra="TSLA,NVDA"):
        syms, info = build_collector_universe()

    assert "TSLA" in syms
    assert "NVDA" in syms


# ── Test 7: Priority tiers — open positions appear first ─────────────────────

def test_tier0_open_positions_appear_first():
    """Tier 0 (open positions) appear at the head of the symbol list."""
    from marketdata.universe_builder import build_collector_universe

    with _patch_universe(base="AMD,NVDA", positions_provider=lambda: ["MSTR", "HOOD"]):
        syms, info = build_collector_universe()

    assert syms[0] == "MSTR"
    assert syms[1] == "HOOD"
    assert info["open_positions_count"] == 2


# ── Test 8: Budget exhaustion — tier 3 dropped first ─────────────────────────

def test_budget_exhaustion_drops_tier3_first():
    """When over budget, base/extra (Tier 3) is dropped before V5 or paper."""
    from marketdata.universe_builder import build_collector_universe

    # 5 V5 (tier2) + 10 base (tier3) = 15 total; cap to 8
    with _patch_universe(v5_enabled=True, v5="A,B,C,D,E", base="F,G,H,I,J,K,L,M,N,O", max_syms=8):
        syms, info = build_collector_universe()

    assert len(syms) == 8
    for s in ["A", "B", "C", "D", "E"]:
        assert s in syms, f"V5 symbol {s} should not have been dropped"
    assert info["skipped_due_to_budget"] == 7
    assert info["skipped_by_tier"]["tier3"] == 7
    assert info["skipped_by_tier"]["tier2"] == 0


# ── Test 9: Budget exhaustion — tier 2 dropped after tier 3 exhausted ─────────

def test_budget_exhaustion_drops_tier2_after_tier3():
    """After tier3 exhausted, tier2 (V5) starts being dropped."""
    from marketdata.universe_builder import build_collector_universe

    # 3 V5 (tier2) + 2 base (tier3) = 5; cap to 3
    with _patch_universe(v5_enabled=True, v5="A,B,C", base="X,Y", max_syms=3):
        syms, info = build_collector_universe()

    assert len(syms) == 3
    assert "X" not in syms
    assert "Y" not in syms
    assert info["skipped_by_tier"]["tier3"] == 2


# ── Test 10: Tier 0 (open positions) never dropped ───────────────────────────

def test_tier0_never_dropped_by_budget():
    """Open positions are always kept regardless of budget pressure."""
    from marketdata.universe_builder import build_collector_universe

    # 2 positions + 5 base = 7 total; cap to 3 — positions must survive
    with _patch_universe(base="A,B,C,D,E", max_syms=3, positions_provider=lambda: ["POS1", "POS2"]):
        syms, info = build_collector_universe()

    assert "POS1" in syms
    assert "POS2" in syms
    assert info["open_positions_count"] == 2


# ── Test 11: Symbols normalized to uppercase ──────────────────────────────────

def test_symbols_normalized_uppercase():
    """All returned symbols are uppercase regardless of config case."""
    from marketdata.universe_builder import build_collector_universe

    with _patch_universe(base="amd,nvda,Tsla"):
        syms, _ = build_collector_universe()

    for s in syms:
        assert s == s.upper(), f"Symbol not uppercase: {s}"


# ── Test 12: Collector uses bulk snapshot — one call for expanded universe ────

async def test_collector_uses_single_bulk_snapshot_call():
    """Expanded universe still triggers exactly one fetch_bulk_snapshots call."""
    from marketdata.collector import MarketDataCollector

    big_universe = [f"SYM{i}" for i in range(25)]

    bulk_mock = AsyncMock(return_value=[])

    with (
        patch(
            "marketdata.universe_builder.build_collector_universe",
            return_value=(big_universe, {"total_collector_symbols": 25}),
        ),
        patch("marketdata.polygon_source.fetch_bulk_snapshots", new=bulk_mock),
        patch("marketdata.cache.write_cycle_results", new=AsyncMock()),
    ):
        collector = MarketDataCollector(symbols=["AMD"])
        await collector._cycle()

    bulk_mock.assert_called_once()
    call_symbols = bulk_mock.call_args[0][0]
    assert call_symbols == big_universe


# ── Test 13: Collector updates _symbols from universe builder ─────────────────

async def test_collector_updates_symbols_from_universe_builder():
    """After a cycle, collector._symbols reflects the universe builder output."""
    from marketdata.collector import MarketDataCollector

    new_universe = ["AAPL", "MSFT", "GOOGL", "TSLA"]

    with (
        patch(
            "marketdata.universe_builder.build_collector_universe",
            return_value=(new_universe, {"total_collector_symbols": 4}),
        ),
        patch("marketdata.polygon_source.fetch_bulk_snapshots", new=AsyncMock(return_value=[])),
        patch("marketdata.cache.write_cycle_results", new=AsyncMock()),
    ):
        collector = MarketDataCollector(symbols=["AMD"])
        assert collector._symbols == ["AMD"]
        await collector._cycle()
        assert collector._symbols == new_universe


# ── Test 14: universe_info in get_metrics() ───────────────────────────────────

async def test_universe_info_in_collector_metrics():
    """universe_info from the builder is stored and returned by get_metrics()."""
    from marketdata.collector import MarketDataCollector

    tier_info = {
        "total_collector_symbols": 42,
        "paper_universe_count": 20,
        "v5_symbols_count": 15,
    }

    with (
        patch(
            "marketdata.universe_builder.build_collector_universe",
            return_value=(["AMD"], tier_info),
        ),
        patch("marketdata.polygon_source.fetch_bulk_snapshots", new=AsyncMock(return_value=[])),
        patch("marketdata.cache.write_cycle_results", new=AsyncMock()),
    ):
        collector = MarketDataCollector(symbols=["AMD"])
        await collector._cycle()

    metrics = collector.get_metrics()
    assert "universe_info" in metrics
    assert metrics["universe_info"]["total_collector_symbols"] == 42
    assert metrics["universe_info"]["paper_universe_count"] == 20


# ── Test 15: No real Polygon calls in universe builder itself ─────────────────

def test_build_collector_universe_makes_no_polygon_calls():
    """build_collector_universe() reads config only — never calls Polygon."""
    from marketdata.universe_builder import build_collector_universe

    with (
        _patch_universe(base="AMD,NVDA"),
        patch("data.polygon_client.get_bulk_ticker_snapshots") as mock_poly,
    ):
        build_collector_universe()

    mock_poly.assert_not_called()


# ── Test 16: Register open positions provider ─────────────────────────────────

def test_register_open_positions_provider():
    """Registered provider is used by build_collector_universe() for Tier 0."""
    import marketdata.universe_builder as _ub
    from marketdata.universe_builder import register_open_positions_provider, build_collector_universe

    orig = _ub._positions_provider
    try:
        register_open_positions_provider(lambda: ["MSFT", "GOOGL"])
        # Patch config directly (not via _patch_universe, which would reset the provider)
        with (
            patch.object(settings, "MARKETDATA_INCLUDE_PAPER_UNIVERSE", False),
            patch.object(settings, "MARKETDATA_INCLUDE_V5_UNIVERSE", False),
            patch.object(settings, "MARKETDATA_BASE_SYMBOLS", "AMD"),
            patch.object(settings, "MARKETDATA_EXTRA_SYMBOLS", ""),
            patch.object(settings, "MARKETDATA_MAX_SYMBOLS_PER_CYCLE", 100),
        ):
            syms, info = build_collector_universe()

        assert "MSFT" in syms
        assert "GOOGL" in syms
        assert info["open_positions_count"] == 2
        assert syms.index("MSFT") < syms.index("AMD")
    finally:
        _ub._positions_provider = orig


# ── Test 17: Health endpoint includes D4 fields ───────────────────────────────

async def test_health_endpoint_includes_d4_fields(client):
    """GET /api/marketdata/health exposes per-tier composition fields."""
    with (
        patch(
            "data.redis_client.redis_ping_status",
            new=AsyncMock(return_value={"redis_connected": True}),
        ),
        patch("marketdata.cache.read_symbol", new=AsyncMock(return_value=None)),
        patch("marketdata.cache.read_active_symbols", new=AsyncMock(return_value=[])),
    ):
        resp = client.get("/api/marketdata/health")

    assert resp.status_code == 200
    d = resp.json()
    d4_keys = [
        "configured_base_symbols_count",
        "paper_universe_symbols_count",
        "v5_symbols_count",
        "extra_symbols_count",
        "total_collector_symbols",
        "skipped_due_to_budget",
        "skipped_by_tier",
    ]
    for key in d4_keys:
        assert key in d, f"Missing D4 key in health response: {key}"


# ── Test 18: Metrics endpoint includes universe_info ─────────────────────────

async def test_metrics_endpoint_includes_universe_info(client):
    """GET /api/marketdata/metrics includes universe_info dict."""
    from tests.test_phase_d1 import _make_svc_status

    svc = {**_make_svc_status(), "universe_info": {"total_collector_symbols": 55}}
    with (
        patch("marketdata.service.get_service_status", return_value=svc),
        patch("marketdata.cache.read_metrics", new=AsyncMock(return_value=None)),
    ):
        resp = client.get("/api/marketdata/metrics")

    assert resp.status_code == 200
    d = resp.json()
    assert "universe_info" in d
    assert d["universe_info"]["total_collector_symbols"] == 55


# ── Test 19: No forbidden imports in universe_builder.py ─────────────────────

def test_no_forbidden_imports_in_universe_builder():
    """universe_builder.py must not import broker, AI, or live-trading modules."""
    forbidden = {
        "broker", "alpaca", "td_ameritrade", "order_manager", "live_trading",
        "execution", "real_money", "openai", "anthropic", "ollama", "langchain",
        "transformers", "llm",
    }
    path = Path(__file__).parent.parent / "marketdata" / "universe_builder.py"
    tree = ast.parse(path.read_text())
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
                        f"universe_builder.py: forbidden import '{name}'"
                    )


# ── Test 20: V6 source directory untouched ────────────────────────────────────

def test_v6_directory_untouched():
    """Phase D4 must not modify any V6 source files."""
    v6_src = Path("/opt/nasdaq-scanner-v6/src")
    if not v6_src.exists():
        pytest.skip("V6 directory not found")

    d4_markers = [
        "universe_builder",
        "MARKETDATA_INCLUDE_PAPER_UNIVERSE",
        "MARKETDATA_V5_SYMBOLS",
        "build_collector_universe",
        "MARKETDATA_INCLUDE_V5_UNIVERSE",
    ]
    for js_file in v6_src.glob("*.js"):
        text = js_file.read_text()
        for marker in d4_markers:
            assert marker not in text, (
                f"V6 file {js_file.name} was modified with D4 marker '{marker}'"
            )


# ── Test 21: get_open_position_symbols() exists in simulator ─────────────────

def test_get_open_position_symbols_exists_in_simulator():
    """paper.simulator.get_open_position_symbols() is importable and returns a list."""
    from paper.simulator import get_open_position_symbols
    result = get_open_position_symbols()
    assert isinstance(result, list)
