from core.config import Settings


def test_allowed_origins_list_single():
    s = Settings(ALLOWED_ORIGINS="http://localhost:3000")
    assert s.allowed_origins_list() == ["http://localhost:3000"]


def test_allowed_origins_list_multiple():
    s = Settings(ALLOWED_ORIGINS="http://localhost:3000,https://app.example.com")
    assert s.allowed_origins_list() == ["http://localhost:3000", "https://app.example.com"]


def test_allowed_origins_list_ignores_empty_entries():
    s = Settings(ALLOWED_ORIGINS="http://localhost:3000,,  ,https://app.example.com")
    assert s.allowed_origins_list() == ["http://localhost:3000", "https://app.example.com"]


def test_allowed_origins_default_is_not_wildcard():
    s = Settings()
    for origin in s.allowed_origins_list():
        assert origin != "*", "Default CORS must never be wildcard"


def test_polygon_key_preview_masks_key():
    s = Settings(POLYGON_API_KEY="ABCDEFGH1234")
    preview = s.polygon_key_preview()
    assert "ABCDEFGH1234" not in preview
    assert preview.startswith("****")
    assert preview.endswith("1234")


def test_polygon_key_preview_not_configured():
    s = Settings(POLYGON_API_KEY="")
    assert s.polygon_key_preview() == "not configured"


def test_expose_key_preview_default_false():
    s = Settings()
    assert s.EXPOSE_KEY_PREVIEW is False
