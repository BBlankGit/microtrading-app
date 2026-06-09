"""
Phase D4-H1 tests — marketdata collector auto-start after backend restart.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM/Ollama. All Polygon calls mocked. No real Redis in tests.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_svc_status(**overrides) -> dict:
    base = {
        "running": True,
        "started_at": "2026-06-09T16:00:00+00:00",
        "auto_started": True,
        "symbols": ["AMD", "NVDA", "SPY"],
        "last_cycle_at": "2026-06-09T16:00:10+00:00",
        "last_success_at": "2026-06-09T16:00:10+00:00",
        "last_error": None,
        "cycles_last_minute": 2,
        "polygon_attempts_last_minute": 2,
        "retries_last_minute": 0,
        "skipped_due_to_rate_limit_last_minute": 0,
        "timeouts_last_minute": 0,
        "errors_last_minute": 0,
        "universe_info": {
            "paper_universe_count": 10,
            "v5_symbols_count": 5,
            "total_collector_symbols": 18,
            "skipped_due_to_budget": 0,
            "skipped_by_tier": {},
        },
    }
    base.update(overrides)
    return base


async def _noop_lifespan_deps():
    """Patch set used for all lifespan-based tests."""
    return {
        "paper.journal.init_journal": AsyncMock(),
        "paper.runtime_config.init_runtime_config_tables": AsyncMock(),
        "paper.simulator.restore_paper_session": AsyncMock(
            return_value={"source": "none"}
        ),
    }


# ── Test 1: Auto-start fires when MARKETDATA_COLLECTOR_ENABLED=True ───────────

@pytest.mark.asyncio
async def test_collector_auto_starts_when_enabled():
    """Lifespan calls start_collector(auto_started=True) when enabled=True."""
    from main import lifespan
    from fastapi import FastAPI

    mock_start = AsyncMock(return_value={"started": True, "symbols": []})

    with (
        patch.object(settings, "MARKETDATA_COLLECTOR_ENABLED", True),
        patch("marketdata.service.start_collector", mock_start),
        patch("paper.journal.init_journal", AsyncMock()),
        patch("paper.runtime_config.init_runtime_config_tables", AsyncMock()),
        patch("paper.simulator.restore_paper_session", AsyncMock(return_value={"source": "none"})),
        patch("marketdata.universe_builder.register_open_positions_provider"),
        patch("marketdata.service.stop_collector", AsyncMock(return_value={"stopped": True})),
        patch("marketdata.service.is_running", return_value=False),
    ):
        app = FastAPI()
        async with lifespan(app):
            pass

    mock_start.assert_called_once()
    _, kwargs = mock_start.call_args
    assert kwargs.get("auto_started") is True, (
        "start_collector must be called with auto_started=True from lifespan"
    )


# ── Test 2: No auto-start when disabled ───────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_does_not_auto_start_when_disabled():
    """Lifespan does NOT call start_collector when enabled=False."""
    from main import lifespan
    from fastapi import FastAPI

    mock_start = AsyncMock(return_value={"started": True, "symbols": []})

    with (
        patch.object(settings, "MARKETDATA_COLLECTOR_ENABLED", False),
        patch("marketdata.service.start_collector", mock_start),
        patch("paper.journal.init_journal", AsyncMock()),
        patch("paper.runtime_config.init_runtime_config_tables", AsyncMock()),
        patch("paper.simulator.restore_paper_session", AsyncMock(return_value={"source": "none"})),
        patch("marketdata.universe_builder.register_open_positions_provider"),
        patch("marketdata.service.stop_collector", AsyncMock(return_value={"stopped": True})),
        patch("marketdata.service.is_running", return_value=False),
    ):
        app = FastAPI()
        async with lifespan(app):
            pass

    mock_start.assert_not_called()


# ── Test 3: Health shows enabled+running+auto_started correctly ───────────────

@pytest.mark.asyncio
async def test_health_shows_enabled_running_auto_started():
    """/health reflects enabled, running, started_at, auto_started from service."""
    from marketdata.health import get_health

    svc_status = _make_svc_status(running=True, auto_started=True)

    # health.py imports service and cache inside the function, so patch at source
    with (
        patch.object(settings, "MARKETDATA_COLLECTOR_ENABLED", True),
        patch("marketdata.service.get_service_status", return_value=svc_status),
        patch("marketdata.cache.read_symbol", AsyncMock(return_value=None)),
        patch(
            "data.redis_client.redis_ping_status",
            AsyncMock(return_value={"redis_connected": True}),
        ),
    ):
        h = await get_health()

    assert h["enabled"] is True
    assert h["running"] is True
    assert h["auto_started"] is True
    assert h["started_at"] == "2026-06-09T16:00:00+00:00"
    assert h["last_cycle_at"] == "2026-06-09T16:00:10+00:00"


# ── Test 4: Health shows not-running state correctly ─────────────────────────

@pytest.mark.asyncio
async def test_health_shows_not_running():
    """/health correctly shows running=False when collector is stopped."""
    from marketdata.health import get_health

    svc_status = _make_svc_status(
        running=False, started_at=None, auto_started=False,
        last_cycle_at=None, last_success_at=None,
    )

    with (
        patch.object(settings, "MARKETDATA_COLLECTOR_ENABLED", True),
        patch("marketdata.service.get_service_status", return_value=svc_status),
        patch("marketdata.cache.read_symbol", AsyncMock(return_value=None)),
        patch(
            "data.redis_client.redis_ping_status",
            AsyncMock(return_value={"redis_connected": True}),
        ),
    ):
        h = await get_health()

    assert h["enabled"] is True
    assert h["running"] is False
    assert h["auto_started"] is False
    assert h["started_at"] is None


# ── Test 5: Manual start still works (auto_started=False) ────────────────────

@pytest.mark.asyncio
async def test_manual_start_sets_auto_started_false():
    """start_collector() called without auto_started records auto_started=False."""
    import marketdata.service as svc

    mock_collector = MagicMock()
    mock_collector._symbols = ["AMD"]
    mock_collector.run = AsyncMock()

    with patch("marketdata.service.asyncio.create_task") as mock_task:
        mock_task.return_value = MagicMock(done=lambda: False)
        with patch("marketdata.collector.MarketDataCollector", return_value=mock_collector):
            # Reset service state
            svc._task = None
            svc._started_at = None
            svc._auto_started = False

            result = await svc.start_collector()  # no auto_started kwarg → defaults False

    assert result["started"] is True
    assert svc._auto_started is False
    assert svc._started_at is not None


# ── Test 6: Manual stop clears started_at and auto_started ───────────────────

@pytest.mark.asyncio
async def test_stop_clears_started_at_and_auto_started():
    """stop_collector() resets _started_at and _auto_started to None/False."""
    import marketdata.service as svc
    from datetime import datetime, timezone

    svc._started_at = datetime.now(timezone.utc)
    svc._auto_started = True
    svc._task = MagicMock()
    svc._task.done.return_value = True  # already done, cancel path skipped

    result = await svc.stop_collector()

    assert result["stopped"] is True
    assert svc._started_at is None
    assert svc._auto_started is False


# ── Test 7: No broker/live-trading/AI/Ollama imports in service module ────────

def test_no_broker_or_ai_imports_in_service():
    """service.py must not import broker, live-trading, or AI/LLM modules."""
    src = Path("marketdata/service.py").read_text()
    tree = ast.parse(src)
    banned = {
        "alpaca", "broker", "openai", "anthropic", "langchain",
        "ollama", "live_trading", "real_order",
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                for b in banned:
                    assert b not in (name or "").lower(), (
                        f"Banned import '{name}' found in service.py"
                    )
