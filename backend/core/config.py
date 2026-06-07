from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    POLYGON_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    TRADING_MODE: str = "research"
    LIVE_TRADING_ENABLED: bool = False

    # Security / operational
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    ADMIN_API_TOKEN: str = ""
    EXPOSE_KEY_PREVIEW: bool = False

    # Paper simulator
    PAPER_STARTING_CASH: float = 1000.0
    PAPER_MAX_POSITIONS: int = 2
    PAPER_MAX_TRADES_PER_DAY: int = 20
    PAPER_MAX_POSITION_SIZE_USD: float = 250.0
    PAPER_TAKE_PROFIT_PERCENT: float = 0.60
    PAPER_STOP_LOSS_PERCENT: float = 0.35
    PAPER_MAX_HOLD_MINUTES: int = 15
    PAPER_POLL_INTERVAL_SECONDS: int = 60
    PAPER_DEFAULT_UNIVERSE: str = "AAPL,MSFT,NVDA,TSLA,AMD,META,AMZN,GOOGL,PLTR,SOFI"
    PAPER_ENTRY_SCORE_THRESHOLD: int = 70

    def paper_universe_list(self) -> list[str]:
        return [s.strip().upper() for s in self.PAPER_DEFAULT_UNIVERSE.split(",") if s.strip()]

    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

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
