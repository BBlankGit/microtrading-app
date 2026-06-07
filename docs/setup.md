# Setup Guide

## Phase 0 — Foundation Only

This is Phase 0. It does not connect to Polygon, any broker, or any live trading system.

---

## VM Setup

```bash
# Clone the repo
git clone https://github.com/BBlankGit/microtrading-app.git
cd microtrading-app

# Set up environment
cp .env.example .env
# Edit .env if needed (Phase 0 requires no real API keys)

# Build and start all services
cd infra/docker
docker-compose up --build
```

---

## Verify the Stack

After services start, run these checks:

```bash
# Backend health
curl http://SERVER_IP:8000/health

# Backend status
curl http://SERVER_IP:8000/api/status

# Frontend (open in browser)
http://SERVER_IP:3000
```

Expected responses:

**`/health`**
```json
{"status": "ok"}
```

**`/api/status`**
```json
{
  "app_name": "Microtrading App",
  "version": "0.1.0",
  "mode": "paper",
  "live_trading_enabled": false,
  "broker_connected": false,
  "message": "Phase 0 foundation is running. No live trading is enabled. Paper trading only — no broker connection, no real-money execution."
}
```

---

## Services

| Service | Port |
|---|---|
| Backend (FastAPI) | 8000 |
| Frontend (Next.js) | 3000 |
| PostgreSQL | 5432 |
| Redis | 6379 |

---

## Stop the Stack

```bash
cd infra/docker
docker-compose down
```

To also remove persistent volumes:

```bash
docker-compose down -v
```

---

## Do Not Proceed to Phase 1 Until Phase 0 Is Verified
