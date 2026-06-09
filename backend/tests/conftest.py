from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    # Patch restore_paper_session and start_collector to no-ops so tests are
    # isolated from real Redis state and live Polygon connections.
    with patch(
        "paper.simulator.restore_paper_session",
        new=AsyncMock(return_value={"source": "none"}),
    ), patch(
        "marketdata.service.start_collector",
        new=AsyncMock(return_value={"started": True, "symbols": []}),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
