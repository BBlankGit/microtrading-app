import core.config as config_module


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
