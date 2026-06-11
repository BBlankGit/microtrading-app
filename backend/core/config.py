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
    PAPER_MAX_POSITIONS: int = 5
    PAPER_MAX_TRADES_PER_DAY: int = 100
    PAPER_MAX_POSITION_SIZE_USD: float = 250.0
    PAPER_TAKE_PROFIT_PERCENT: float = 0.60
    PAPER_STOP_LOSS_PERCENT: float = 0.35
    PAPER_MAX_HOLD_MINUTES: int = 15
    PAPER_POLL_INTERVAL_SECONDS: int = 60
    JOURNAL_RETRY_SECONDS: int = 30
    JOURNAL_RETENTION_DAYS: int = 14
    PAPER_DEFAULT_UNIVERSE: str = "AAPL,MSFT,NVDA,TSLA,AMD,META,AMZN,GOOGL,PLTR,SOFI"
    PAPER_ENTRY_SCORE_THRESHOLD: int = 70

    # Phase I6 — Earnings calendar (fake-money scoring only, no broker)
    PAPER_EARNINGS_SCORING_ENABLED: bool = True
    PAPER_EARNINGS_BLOCK_WITHIN_DAYS: int = 0  # 0 = penalize only, do not hard-block
    PAPER_EARNINGS_STRONG_PENALTY_WITHIN_DAYS: int = 1
    PAPER_EARNINGS_MEDIUM_PENALTY_WITHIN_DAYS: int = 2
    PAPER_EARNINGS_LIGHT_PENALTY_WITHIN_DAYS: int = 3
    PAPER_EARNINGS_STRONG_PENALTY_POINTS: int = -10
    PAPER_EARNINGS_MEDIUM_PENALTY_POINTS: int = -5
    PAPER_EARNINGS_LIGHT_PENALTY_POINTS: int = -3
    EARNINGS_DATA_PROVIDER: str = "none"  # "polygon" | "finnhub" | "none"
    EARNINGS_CACHE_TTL_SECONDS: int = 7200  # 2 hours
    EARNINGS_LOOKAHEAD_DAYS: int = 30

    # Phase I6 — Insider transactions (fake-money scoring only, no broker)
    PAPER_INSIDER_SCORING_ENABLED: bool = True
    PAPER_INSIDER_LOOKBACK_DAYS: int = 7
    PAPER_INSIDER_MIN_BUY_VALUE: float = 50000.0
    PAPER_INSIDER_STRONG_BUY_VALUE: float = 250000.0
    PAPER_INSIDER_BUY_BOOST_POINTS: int = 5
    PAPER_INSIDER_STRONG_BUY_BOOST_POINTS: int = 10
    PAPER_INSIDER_SELL_PENALTY_POINTS: int = 0  # 0 = informational only, no penalty
    PAPER_INSIDER_IGNORE_NON_DISCRETIONARY: bool = True
    INSIDER_DATA_PROVIDER: str = "none"  # "polygon" | "finnhub" | "none"
    INSIDER_CACHE_TTL_SECONDS: int = 1800  # 30 minutes

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

    # Market regime monitor (Phase 2H — observational only, no strategy changes)
    MARKET_REGIME_ENABLED: bool = True
    MARKET_REGIME_SYMBOLS: str = "SPY,QQQ,IWM,DIA,XLK,XLF,XLE,XLY,XLI,XLU"
    MARKET_REGIME_REFRESH_SECONDS: int = 60
    MARKET_REGIME_MIN_RISK_ON_SCORE: int = 60
    MARKET_REGIME_MAX_RISK_OFF_SCORE: int = 40

    # Catalyst sentiment (Phase 2I — no AI/LLM, deterministic rules only)
    PAPER_REJECT_STRONG_BEARISH_CATALYST: bool = True
    PAPER_BEARISH_CATALYST_REJECT_MATERIALITY: float = 0.8

    # Paper Redis state namespace (Phase 2U — namespace isolation, no broker, no real orders)
    PAPER_STATE_REDIS_NAMESPACE: str = "paper:prod"

    # Catalyst type performance guard (Phase 2T — fake-money only, no broker, no real orders)
    PAPER_BLOCKED_CATALYST_TYPES: str = "fda_regulatory"
    PAPER_CATALYST_TYPE_WEIGHTS: str = "{}"
    PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES: bool = True

    # Momentum entry mode (Phase 2M — disabled by default, no broker, no real orders)
    PAPER_MOMENTUM_MODE_ENABLED: bool = False
    PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD: int = 85
    PAPER_MOMENTUM_MIN_CHANGE_PERCENT: float = 1.5
    PAPER_MOMENTUM_MIN_VOLUME_RATIO: float = 2.0
    PAPER_MOMENTUM_MAX_SPREAD_PERCENT: float = 0.25
    PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON: bool = True
    PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE: int = 60
    PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER: float = 0.5
    PAPER_MOMENTUM_MAX_TRADES_PER_DAY: int = 30

    # Volume hard gate (Phase 2O — runtime configurable, no broker, no real orders)
    PAPER_MIN_VOLUME_RATIO: float = 0.8

    # Daily loss guard (Phase 2N — fake-money only, no broker, no real orders)
    PAPER_DAILY_MAX_LOSS_ENABLED: bool = True
    PAPER_DAILY_MAX_LOSS_PERCENT: float = 2.0
    PAPER_DAILY_MAX_LOSS_USD: float = 0.0

    # Market-wide movers discovery (Phase 2J — no broker, no real orders)
    PAPER_MARKET_DISCOVERY_ENABLED: bool = True
    PAPER_MARKET_DISCOVERY_MAX_SYMBOLS: int = 100
    PAPER_MARKET_DISCOVERY_REFRESH_SECONDS: int = 300
    PAPER_MARKET_DISCOVERY_INCLUDE_GAINERS: bool = True
    PAPER_MARKET_DISCOVERY_INCLUDE_LOSERS: bool = True
    PAPER_MARKET_DISCOVERY_INCLUDE_MOST_ACTIVE: bool = True
    PAPER_MARKET_DISCOVERY_MIN_PRICE: float = 1.00
    PAPER_MARKET_DISCOVERY_MAX_PRICE: float = 1000.00
    PAPER_MARKET_DISCOVERY_MIN_VOLUME: int = 500_000
    PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT: float = 1.0

    def paper_blocked_catalyst_types_list(self) -> list[str]:
        return [s.strip().lower() for s in self.PAPER_BLOCKED_CATALYST_TYPES.split(",") if s.strip()]

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

    # ── Full-universe premarket scanner (Phase I3-B — read-only, no broker, no live trading) ─
    PREMARKET_SCANNER_ENABLED: bool = True
    PREMARKET_SCANNER_CHUNK_SIZE: int = 200
    PREMARKET_SCANNER_MAX_CONCURRENT_CHUNKS: int = 5
    PREMARKET_SCANNER_INTERVAL_PREMARKET_SECONDS: int = 60
    PREMARKET_SCANNER_INTERVAL_REGULAR_SECONDS: int = 180
    PREMARKET_SCANNER_MIN_PRICE: float = 3.0
    PREMARKET_SCANNER_TOP_N: int = 50
    PREMARKET_SCANNER_TOP_MOVERS_N: int = 100
    PREMARKET_SCANNER_UNIVERSE_TTL_SECONDS: int = 86400
    PREMARKET_SCANNER_RESULT_TTL_SECONDS: int = 90
    PREMARKET_SCANNER_REQUEST_TIMEOUT_SECONDS: float = 15.0
    PREMARKET_SCANNER_SAFETY_COOLDOWN_SECONDS: int = 30
    PREMARKET_SCANNER_MAX_UNIVERSE_SIZE: int = 10000

    # ── Market data collector (Phase D1 — read-only, no broker, no live trading) ─
    MARKETDATA_COLLECTOR_ENABLED: bool = False
    MARKETDATA_BASE_SYMBOLS: str = "AMD,NVDA,TSLA,SMCI,AAPL,MSFT,QQQ,SPY,IWM"
    MARKETDATA_POLL_INTERVAL_SECONDS: int = 10
    MARKETDATA_BULK_SNAPSHOT_INTERVAL_SECONDS: int = 10
    MARKETDATA_AGG1M_INTERVAL_SECONDS: int = 30
    MARKETDATA_CACHE_TTL_SECONDS: int = 30
    MARKETDATA_REQUEST_TIMEOUT_SECONDS: int = 8
    MARKETDATA_MAX_REQUESTS_PER_MINUTE: int = 50
    MARKETDATA_RETRY_COUNT: int = 1
    MARKETDATA_RETRY_BACKOFF_SECONDS: float = 2.0

    def marketdata_base_symbols_list(self) -> list[str]:
        return [s.strip().upper() for s in self.MARKETDATA_BASE_SYMBOLS.split(",") if s.strip()]

    # Dynamic universe coverage (Phase D4 — no broker, no live trading, no real orders)
    MARKETDATA_INCLUDE_PAPER_UNIVERSE: bool = True
    MARKETDATA_INCLUDE_V5_UNIVERSE: bool = True
    MARKETDATA_V5_SYMBOLS: str = (
        "BBAI,RKLB,IONQ,SMCI,SERV,CLSK,SOUN,ASTS,PLTR,AMD,"
        "MARA,RIOT,HUT,BTDR,CIFR,WULF,AI,PATH,UPST,AFRM,"
        "HOOD,COIN,RIVN,LCID,CAVA,CVNA,ROKU,U,"
        "NEXT,MKSI,APLD,LUNR,METC,WVE,AXTI,SPIR,TSLR,"
        "DXYZ,SOC,AEVA,AAOI,AXON,CORT,COGT,ADMA,XPO,JOBY,"
        "QQQ,IWM,SPY"
    )
    MARKETDATA_V5_SYMBOLS_FILE: str = ""
    MARKETDATA_EXTRA_SYMBOLS: str = ""
    MARKETDATA_MAX_SYMBOLS_PER_CYCLE: int = 100

    def marketdata_v5_symbols_list(self) -> list[str]:
        if self.MARKETDATA_V5_SYMBOLS_FILE:
            try:
                from pathlib import Path
                text = Path(self.MARKETDATA_V5_SYMBOLS_FILE).read_text()
                return [s.strip().upper() for s in text.replace("\n", ",").split(",") if s.strip()]
            except Exception:
                pass
        return [s.strip().upper() for s in self.MARKETDATA_V5_SYMBOLS.split(",") if s.strip()]

    def marketdata_extra_symbols_list(self) -> list[str]:
        return [s.strip().upper() for s in self.MARKETDATA_EXTRA_SYMBOLS.split(",") if s.strip()]

    # No-catalyst momentum entry mode (Phase 2R — disabled by default, no broker, no real orders)
    PAPER_NO_CATALYST_ENTRY_ENABLED: bool = False
    PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH: bool = True
    PAPER_NO_CATALYST_MIN_SCORE: int = 80
    PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE: int = 20
    PAPER_NO_CATALYST_MIN_CHANGE_PERCENT: float = 2.0
    PAPER_NO_CATALYST_MIN_VOLUME_RATIO: float = 1.5
    PAPER_NO_CATALYST_MAX_SPREAD_PERCENT: float = 0.20
    PAPER_NO_CATALYST_REQUIRE_RISK_ON: bool = True
    PAPER_NO_CATALYST_MIN_RISK_SCORE: int = 60
    PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER: float = 0.5
    PAPER_NO_CATALYST_MAX_TRADES_PER_DAY: int = 20

    # Paper simulator market-data cache integration (Phase D2 — no broker, no real orders)
    PAPER_USE_MARKETDATA_CACHE: bool = True
    PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS: int = 30
    PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED: bool = True
    PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY: bool = True

    # Full-market movers candidate injection (Phase I4-B — fake-money only, no broker, no real orders)
    PAPER_MARKET_MOVERS_CANDIDATES_ENABLED: bool = True
    PAPER_MARKET_MOVERS_CANDIDATES_TOP_N: int = 50
    PAPER_MARKET_MOVERS_CANDIDATES_MIN_GAP_PERCENT: float = 2.0
    PAPER_MARKET_MOVERS_CANDIDATES_MAX_GAP_PERCENT: float = 40.0
    PAPER_MARKET_MOVERS_CANDIDATES_REQUIRE_FULL_UNIVERSE: bool = True

    # Time-adjusted relative volume gate (Phase S1-V1 — no broker, no real orders)
    PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO: bool = True
    PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR: float = 0.05
    PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN: float = 0.8

    # Session-aware market mover no-catalyst entry path (Phase N1 — fake-money only, no broker, no real orders)
    PAPER_MARKET_MOVER_ENTRY_ENABLED: bool = True
    PAPER_MARKET_MOVER_ALLOWED_SESSIONS: str = "premarket,regular"
    PAPER_MARKET_MOVER_TOP_RANK_MAX: int = 30
    PAPER_MARKET_MOVER_MIN_CHANGE_PERCENT: float = 5.0
    PAPER_MARKET_MOVER_MAX_CHANGE_PERCENT: float = 80.0
    PAPER_MARKET_MOVER_MIN_TIME_ADJ_VOLUME_RATIO: float = 2.0
    PAPER_MARKET_MOVER_MIN_PREMARKET_VOLUME_VS_PREV_DAY_RATIO: float = 0.02
    PAPER_MARKET_MOVER_MIN_DOLLAR_VOLUME: int = 1_000_000
    PAPER_MARKET_MOVER_MAX_SPREAD_PERCENT: float = 0.35
    PAPER_MARKET_MOVER_MIN_SCORE: int = 55
    PAPER_MARKET_MOVER_POSITION_SIZE_MULTIPLIER: float = 0.25
    PAPER_MARKET_MOVER_MAX_TRADES_PER_DAY: int = 10
    PAPER_MARKET_MOVER_BLOCK_IF_ANY_BEARISH: bool = True
    PAPER_MARKET_MOVER_ALLOW_RISK_OFF: bool = True


settings = Settings()
