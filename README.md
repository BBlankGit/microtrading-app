# Microtrading App

A cloud-only automated U.S. equities microtrading research platform.

## Current Status

| Setting | Value |
|---|---|
| Trading Mode | **Paper trading only** |
| Broker Connection | **Not connected** |
| Live Orders | **Disabled** |
| Real-Money Execution | **Disabled** |

> **Important:** AI may interpret catalysts and recommend opportunities to the engine.  
> AI may **not** execute trades directly.  
> The **Risk Manager has absolute veto power** over all trade decisions.

---

## Core Modules

| Module | Description |
|---|---|
| `backend/api/` | FastAPI route handlers |
| `backend/engine/` | Signal evaluation and trade decision engine |
| `backend/catalysts/` | Catalyst collection and normalization |
| `backend/ai/` | NLP/AI interpretation of catalysts |
| `backend/risk/` | Risk manager — veto authority over all trades |
| `backend/execution/` | Paper trade execution layer |
| `backend/data/` | Market data ingestion (Polygon REST + WebSocket) |
| `backend/database/` | DB models, migrations, connection pooling |
| `frontend/dashboard/` | Next.js research and monitoring dashboard |
| `infra/docker/` | Docker Compose stack |
| `docs/` | Architecture, trading rules, risk policy, AI layer docs |
| `tests/` | Unit and integration tests |

---

## Quickstart

```bash
cp .env.example .env
# Edit .env and add your API keys
cd infra/docker
docker-compose up --build
```

Test endpoints:
- `http://SERVER_IP:8000/health`
- `http://SERVER_IP:8000/api/status`
- `http://SERVER_IP:3000`

See [docs/setup.md](docs/setup.md) for full instructions.

---

## Phase Roadmap

| Phase | Description |
|---|---|
| **Phase 0** | Foundation — no broker, no live trading (current) |
| Phase 1 | Polygon data ingestion + catalyst collection |
| Phase 2 | AI/NLP catalyst scoring |
| Phase 3 | Paper trade engine + risk manager |
| Phase 4 | Dashboard analytics and P&L tracking |
