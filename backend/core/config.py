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
    JOURNAL_RETRY_SECONDS: int = 30
    JOURNAL_RETENTION_DAYS: int = 14
    PAPER_DEFAULT_UNIVERSE: str = "AAPL,MSFT,NVDA,TSLA,AMD,META,AMZN,GOOGL,PLTR,SOFI"
    PAPER_ENTRY_SCORE_THRESHOLD: int = 70

    # Dynamic universe (Phase 2C)
    PAPER_BASE_UNIVERSE: str = (
        "AAPL,MSFT,NVDA,TSLA,AMD,META,AMZN,GOOGL,PLTR,SOFI,"
        "SMCI,AVGO,ARM,MU,INTC,COIN,MARA,RIOT,MSTR,HOOD,"
        "RBLX,SHOP,XYZ,PYPL,UBER,LYFT,RIVN,LCID,F,GM,"
        "NIO,XPEV,LI,BABA,JD,PDD,TSM,ASML,QCOM,MRVL,"
        "CRWD,PANW,NET,DDOG,SNOW,MDB,AI,SOUN,BBAI,IONQ,"
        "RGTI,QBTS,QUBT,RKLB,LUNR,PL,SPIR,ASTS,SATL,RDW,"
        "OKLO,NNE,SMR,CCJ,UUUU,LEU,DNN,FCX,NEM,GLD,"
        "SLV,JPM,BAC,C,WFC,GS,MS,V,MA,AFRM,"
        "UPST,RDDT,SNAP,PINS,DIS,NFLX,ROKU,TTD,APP,CELH,"
        "ELF,LULU,NKE,SBUX,MCD,WMT,COST,TGT,XOM,CVX"
    )
    PAPER_MAX_UNIVERSE_SIZE: int = 150
    PAPER_MAX_SYMBOLS_PER_TICK: int = 50
    PAPER_DYNAMIC_UNIVERSE_ENABLED: bool = True
    PAPER_DYNAMIC_REFRESH_SECONDS: int = 300
    PAPER_MIN_PRICE: float = 1.00
    PAPER_MAX_PRICE: float = 1000.00
    PAPER_MIN_DAY_VOLUME: int = 500_000
    PAPER_MIN_CHANGE_ABS_PERCENT: float = 0.5

    def paper_universe_list(self) -> list[str]:
        return [s.strip().upper() for s in self.PAPER_DEFAULT_UNIVERSE.split(",") if s.strip()]

    def paper_base_universe_list(self) -> list[str]:
        raw = [s.strip().upper() for s in self.PAPER_BASE_UNIVERSE.split(",") if s.strip()]
        seen: set[str] = set()
        deduped: list[str] = []
        for sym in raw:
            if sym not in seen:
                seen.add(sym)
                deduped.append(sym)
        return deduped[:self.PAPER_MAX_UNIVERSE_SIZE]

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
