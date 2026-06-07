from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.catalysts import router as catalysts_router
from api.data_status import router as data_status_router
from api.journal import router as journal_router
from api.market import router as market_router
from api.market_regime import router as market_regime_router
from api.monitoring import router as monitoring_router
from api.paper import router as paper_router
from api.quality import router as quality_router
from api.runtime_config import router as runtime_config_router
from api.stream import router as stream_router
from api.universe import router as universe_router
from core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    from paper.journal import init_journal
    from paper.runtime_config import init_runtime_config_tables
    await init_journal()
    await init_runtime_config_tables()
    yield


app = FastAPI(
    title="Microtrading App",
    description="Cloud-only automated U.S. equities microtrading research platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(catalysts_router)
app.include_router(data_status_router)
app.include_router(journal_router)
app.include_router(market_router)
app.include_router(market_regime_router)
app.include_router(monitoring_router)
app.include_router(paper_router)
app.include_router(quality_router)
app.include_router(runtime_config_router)
app.include_router(stream_router)
app.include_router(universe_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    return {
        "app_name": "Microtrading App",
        "version": "0.1.0",
        "mode": "research",
        "execution_enabled": False,
        "paper_simulator_available": True,
        "paper_trading_real_broker": False,
        "live_trading_enabled": False,
        "broker_connected": False,
        "message": (
            "Research-only foundation is running. "
            "A fake-money paper simulator is available. "
            "No broker connection, live trading, real orders, or real-money execution is implemented."
        ),
    }
