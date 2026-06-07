import core.config as config_module


# ── Helper ──────────────────────────────────────────────────────────────────

def _set_token(monkeypatch, value: str):
    monkeypatch.setattr(config_module.settings, "ADMIN_API_TOKEN", value)


# ── POST /api/stream/start ───────────────────────────────────────────────────

def test_stream_start_503_when_token_empty(client, monkeypatch):
    _set_token(monkeypatch, "")
    resp = client.post("/api/stream/start")
    assert resp.status_code == 503
    assert "ADMIN_API_TOKEN" in resp.json()["detail"]


def test_stream_start_503_when_token_is_sentinel(client, monkeypatch):
    _set_token(monkeypatch, "replace_me_for_admin_operations")
    resp = client.post("/api/stream/start")
    assert resp.status_code == 503


def test_stream_start_401_when_header_missing(client, monkeypatch):
    _set_token(monkeypatch, "real-secret-token")
    resp = client.post("/api/stream/start")
    assert resp.status_code == 401


def test_stream_start_401_when_token_wrong(client, monkeypatch):
    _set_token(monkeypatch, "real-secret-token")
    resp = client.post("/api/stream/start", headers={"Authorization": "Bearer wrongtoken"})
    assert resp.status_code == 401


def test_stream_start_401_when_bearer_missing(client, monkeypatch):
    _set_token(monkeypatch, "real-secret-token")
    resp = client.post("/api/stream/start", headers={"Authorization": "real-secret-token"})
    assert resp.status_code == 401


# ── POST /api/stream/stop ────────────────────────────────────────────────────

def test_stream_stop_503_when_token_empty(client, monkeypatch):
    _set_token(monkeypatch, "")
    resp = client.post("/api/stream/stop")
    assert resp.status_code == 503


def test_stream_stop_401_when_header_missing(client, monkeypatch):
    _set_token(monkeypatch, "real-secret-token")
    resp = client.post("/api/stream/stop")
    assert resp.status_code == 401


def test_stream_stop_401_when_token_wrong(client, monkeypatch):
    _set_token(monkeypatch, "real-secret-token")
    resp = client.post("/api/stream/stop", headers={"Authorization": "Bearer wrongtoken"})
    assert resp.status_code == 401


# ── Read-only endpoints are unprotected ─────────────────────────────────────

def test_stream_status_no_auth_required(client):
    resp = client.get("/api/stream/status")
    # Should not return 401 or 503 from auth
    assert resp.status_code not in (401, 403)
