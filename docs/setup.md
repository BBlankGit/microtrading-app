# Setup Guide

## Phase 0 — Foundation Only

Phase 0 does not connect to Polygon, any broker, or any live trading system.

## Phase 1A — Polygon REST Data Foundation

Phase 1A adds Polygon REST connectivity. A real `POLYGON_API_KEY` is required to use
the market data endpoints. The stack runs without it, but market endpoints will return
an error until the key is set.

---

## VM Setup

```bash
# Clone the repo
git clone https://github.com/BBlankGit/microtrading-app.git
cd microtrading-app

# Set up environment
cp .env.example .env

# Edit .env — set your Polygon API key:
#   POLYGON_API_KEY=your_actual_key_here

# Build and start all services
cd infra/docker
docker-compose up --build
```

---

## Verify the Stack — Phase 0

```bash
# Backend health
curl http://SERVER_IP:8000/health

# Backend status
curl http://SERVER_IP:8000/api/status

# Frontend (open in browser)
http://SERVER_IP:3000
```

---

## Verify the Stack — Phase 1A

```bash
# Data layer status (shows masked key preview, never full key)
curl http://SERVER_IP:8000/api/data/status

# Previous session close for AAPL
curl http://SERVER_IP:8000/api/market/ticker/AAPL/previous-close

# Latest 5 news articles for AAPL
curl "http://SERVER_IP:8000/api/market/ticker/AAPL/news?limit=5"

# Real-time snapshot for AAPL (requires market hours or recent data)
curl http://SERVER_IP:8000/api/market/ticker/AAPL/snapshot
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

## Verify the Stack — Phase 1B (WebSocket Stream)

```bash
# Check stream status (not running yet)
curl http://SERVER_IP:8000/api/stream/status

# Start the WebSocket stream for test tickers: AAPL, MSFT, NVDA, TSLA, AMD
curl -X POST http://SERVER_IP:8000/api/stream/start

# Check status again — connected and messages_received should increment during market hours
curl http://SERVER_IP:8000/api/stream/status

# Retrieve latest streamed data for a symbol (wait 30-60s during market hours first)
curl http://SERVER_IP:8000/api/stream/latest/AAPL

# Stop the stream
curl -X POST http://SERVER_IP:8000/api/stream/stop
```

---

## Verify the Stack — Phase 1D (Tradable Universe Builder)

```bash
# Evaluate the full default universe (AAPL, MSFT, NVDA, TSLA, AMD, META, AMZN, GOOGL, PLTR, SOFI)
curl http://SERVER_IP:8000/api/universe/default

# Evaluate a custom symbol list
curl "http://SERVER_IP:8000/api/universe/check?symbols=AAPL,NVDA,SOFI"

# Mixed valid/invalid symbols — invalid symbols appear in errors, valid ones are evaluated
curl "http://SERVER_IP:8000/api/universe/check?symbols=AAPL,INVALID123,NVDA"
```

---

## Verify the Stack — Phase 1C (Market Quality Gate)

```bash
# Evaluate market quality for AAPL
curl http://SERVER_IP:8000/api/quality/ticker/AAPL

# Evaluate market quality for NVDA
curl http://SERVER_IP:8000/api/quality/ticker/NVDA

# Test an invalid symbol (expects error response)
curl http://SERVER_IP:8000/api/quality/ticker/INVALID123
```

---

## Troubleshooting — WebSocket Policy Violation

If `/api/stream/start` returns or logs a Polygon 1008 policy violation, the API key/account likely does not have WebSocket subscription permission for the requested channels. REST may still work while WebSocket streaming is blocked.

To resolve, upgrade the Polygon account to Starter tier or higher, which includes real-time WebSocket access.

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
