from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def _reset_db_pool_between_tests():
    """Phase G1B-H12: the asyncpg pool cached on paper.db._pool can go
    stale between tests because the FastAPI TestClient lifecycle closes
    connections but the module-level cache survives. Reset before each
    test so endpoint calls get a freshly-built pool."""
    from paper import db as _db
    _db._pool = None
    yield


@pytest.fixture(autouse=True)
def _mock_reddit_redis_save():
    """Prevent test-generated ApeWisdom data from being written to real Redis."""
    with patch("intelligence.reddit._redis_save", new=AsyncMock(return_value=None)):
        yield


@pytest.fixture(autouse=True)
def _reset_full_premarket_snapshot():
    """
    Clear the full_premarket in-memory snapshot cache before each test so that
    market-movers injection in run_tick() sees no cached data and returns early.
    Tests that need specific snapshot data set fp._snapshot themselves;
    tests that test get_snapshot() directly are unaffected because the real
    function still runs (we only clear the state, not replace the function).
    """
    import intelligence.full_premarket as _fp
    orig_snapshot = dict(_fp._snapshot)
    orig_fetched_at = _fp._fetched_at
    _fp._snapshot.clear()
    _fp._fetched_at = 0.0
    yield
    _fp._snapshot.clear()
    _fp._snapshot.update(orig_snapshot)
    _fp._fetched_at = orig_fetched_at


@pytest.fixture
def client():
    # Patch restore_paper_session, _save_state, and start_collector to no-ops
    # so tests are isolated from real Redis state and live Polygon connections.
    # _save_state must be patched to prevent test-generated account state from
    # leaking into the production paper:prod:state Redis key (Phase 2U).
    with patch(
        "paper.simulator.restore_paper_session",
        new=AsyncMock(return_value={"source": "none"}),
    ), patch(
        "paper.simulator._save_state",
        new=AsyncMock(return_value=None),
    ), patch(
        "marketdata.service.start_collector",
        new=AsyncMock(return_value={"started": True, "symbols": []}),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
