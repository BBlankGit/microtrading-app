from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    # Patch restore_paper_session to a no-op so tests are isolated from
    # real Redis state written by previous runs or live simulator ticks.
    with patch(
        "paper.simulator.restore_paper_session",
        new=AsyncMock(return_value={"source": "none"}),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
