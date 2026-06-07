from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    POLYGON_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    TRADING_MODE: str = "paper"
    LIVE_TRADING_ENABLED: bool = False

    def polygon_key_preview(self) -> str:
        """Return last-4 masked preview of the Polygon key. Never returns the full key."""
        key = self.POLYGON_API_KEY
        if not key:
            return "not configured"
        visible = key[-4:] if len(key) >= 4 else "*" * len(key)
        return f"****{visible}"

    def polygon_configured(self) -> bool:
        return bool(self.POLYGON_API_KEY)


settings = Settings()
