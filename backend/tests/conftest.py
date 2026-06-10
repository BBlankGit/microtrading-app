from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


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
