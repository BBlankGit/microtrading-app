from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.data_status import router as data_status_router
from api.market import router as market_router
from api.stream import router as stream_router

app = FastAPI(
    title="Microtrading App",
    description="Cloud-only automated U.S. equities microtrading research platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_status_router)
app.include_router(market_router)
app.include_router(stream_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    return {
        "app_name": "Microtrading App",
        "version": "0.1.0",
        "mode": "paper",
        "live_trading_enabled": False,
        "broker_connected": False,
        "message": (
            "Phase 0 foundation is running. "
            "No live trading is enabled. "
            "Paper trading only — no broker connection, no real-money execution."
        ),
    }
