import pytest

import core.config as config_module
from data.redis_client import redis_ping_status


# ── Endpoint-level tests (via TestClient) ────────────────────────────────────

def test_stream_status_no_crash_when_redis_url_empty(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "")
    resp = client.get("/api/stream/status")
    assert resp.status_code == 200


def test_stream_status_redis_connected_false_when_url_empty(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "")
    resp = client.get("/api/stream/status")
    data = resp.json()
    assert data["redis_connected"] is False


def test_stream_status_redis_error_field_when_url_invalid(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "not-a-url")
    resp = client.get("/api/stream/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["redis_connected"] is False
    assert "redis_error" in data


def test_stream_status_no_crash_when_redis_url_invalid_scheme(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "http://localhost:6379")
    resp = client.get("/api/stream/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["redis_connected"] is False


def test_stream_status_no_crash_when_redis_url_malformed_port(client, monkeypatch):
    """Regression: redis://localhost:notaport/0 caused aioredis.from_url to raise
    before entering the try block, resulting in HTTP 500."""
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "redis://localhost:notaport/0")
    resp = client.get("/api/stream/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["redis_connected"] is False
    assert "redis_error" in data


# ── Unit tests for redis_ping_status() directly ──────────────────────────────

@pytest.mark.asyncio
async def test_redis_ping_status_never_raises_on_empty_url(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "")
    result = await redis_ping_status()
    assert result["redis_connected"] is False
    assert "redis_error" in result


@pytest.mark.asyncio
async def test_redis_ping_status_never_raises_on_malformed_port(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "redis://localhost:notaport/0")
    result = await redis_ping_status()
    assert result["redis_connected"] is False
    assert "redis_error" in result


@pytest.mark.asyncio
async def test_redis_ping_status_never_raises_on_unreachable_host(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REDIS_URL", "redis://127.0.0.1:19999/0")
    result = await redis_ping_status()
    assert result["redis_connected"] is False
    assert "redis_error" in result
