import core.config as config_module


def test_data_status_no_key_preview_by_default(client):
    resp = client.get("/api/data/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "polygon_key_preview" not in data, (
        "polygon_key_preview must not be exposed when EXPOSE_KEY_PREVIEW is false"
    )


def test_data_status_includes_key_preview_when_enabled(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "EXPOSE_KEY_PREVIEW", True)
    monkeypatch.setattr(config_module.settings, "POLYGON_API_KEY", "TESTKEY1234")
    resp = client.get("/api/data/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "polygon_key_preview" in data
    # Must be masked, never the full key
    assert data["polygon_key_preview"] != "TESTKEY1234"
    assert "1234" in data["polygon_key_preview"]


def test_data_status_never_returns_full_key(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "EXPOSE_KEY_PREVIEW", True)
    monkeypatch.setattr(config_module.settings, "POLYGON_API_KEY", "SECRET_FULL_KEY_XYZ")
    resp = client.get("/api/data/status")
    assert resp.status_code == 200
    body = resp.text
    assert "SECRET_FULL_KEY_XYZ" not in body, "Full API key must never appear in any response"
