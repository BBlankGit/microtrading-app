"""
asyncpg pool management and idempotent table creation for the paper journal.
Non-fatal: if Postgres is unavailable all callers degrade gracefully.
No broker. No real orders. Research-only.
"""

import logging

import asyncpg

from core.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_init_error: str | None = None
_tables_ready: bool = False

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS paper_ticks (
    id                      SERIAL PRIMARY KEY,
    tick_id                 TEXT UNIQUE NOT NULL,
    started_at              TIMESTAMPTZ NOT NULL,
    completed_at            TIMESTAMPTZ,
    symbols_evaluated       INT DEFAULT 0,
    universe_active_count   INT DEFAULT 0,
    universe_refresh_reason TEXT,
    entries_made            INT DEFAULT 0,
    exits_made              INT DEFAULT 0,
    errors_count            INT DEFAULT 0,
    account_cash            NUMERIC(12,4),
    account_equity          NUMERIC(12,4),
    realized_pnl            NUMERIC(12,4),
    unrealized_pnl          NUMERIC(12,4),
    total_pnl               NUMERIC(12,4),
    total_pnl_percent       NUMERIC(10,4),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_candidates (
    id                      SERIAL PRIMARY KEY,
    tick_id                 TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    eligible                BOOLEAN,
    action                  TEXT,
    rejection_reason        TEXT,
    quality_tradable        BOOLEAN,
    spread_percent          NUMERIC(8,4),
    change_percent          NUMERIC(8,4),
    volume_ratio            NUMERIC(8,4),
    catalyst_count          INT,
    catalyst_type           TEXT,
    total_score             INT,
    score_threshold         INT,
    score_pass              BOOLEAN,
    score_components_json   JSONB,
    positive_reasons_json   JSONB,
    negative_reasons_json   JSONB,
    decision_reason         TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_trades_journal (
    id                      SERIAL PRIMARY KEY,
    tick_id                 TEXT,
    symbol                  TEXT NOT NULL,
    side                    TEXT NOT NULL DEFAULT 'long',
    event                   TEXT NOT NULL CHECK (event IN ('entry', 'exit')),
    entry_price             NUMERIC(12,4),
    exit_price              NUMERIC(12,4),
    shares                  NUMERIC(12,6),
    cost_basis              NUMERIC(12,4),
    pnl                     NUMERIC(12,4),
    pnl_percent             NUMERIC(10,4),
    exit_reason             TEXT,
    catalyst_type           TEXT,
    total_score             INT,
    opened_at               TIMESTAMPTZ,
    closed_at               TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_universe_snapshots (
    id                      SERIAL PRIMARY KEY,
    tick_id                 TEXT,
    refreshed_at            TIMESTAMPTZ,
    active_count            INT,
    max_symbols_per_tick    INT,
    refresh_reason          TEXT,
    active_symbols_json     JSONB,
    errors_json             JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_paper_ticks_created_at
    ON paper_ticks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_candidates_tick_id
    ON paper_candidates (tick_id);
CREATE INDEX IF NOT EXISTS idx_paper_candidates_symbol
    ON paper_candidates (symbol);
CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol
    ON paper_trades_journal (symbol);
CREATE INDEX IF NOT EXISTS idx_paper_trades_created_at
    ON paper_trades_journal (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_universe_created_at
    ON paper_universe_snapshots (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_candidates_created_at
    ON paper_candidates (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_candidates_symbol_created_at
    ON paper_candidates (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_candidates_tick_created_at
    ON paper_candidates (tick_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_candidates_rejection_reason
    ON paper_candidates (rejection_reason);
CREATE INDEX IF NOT EXISTS idx_paper_trades_event_created_at
    ON paper_trades_journal (event, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_trades_event_symbol_created_at
    ON paper_trades_journal (event, symbol, created_at DESC);
"""


async def get_pool() -> asyncpg.Pool | None:
    """Return the shared connection pool, creating it on first call. Never raises."""
    global _pool, _init_error
    if _pool is not None:
        return _pool
    url = settings.DATABASE_URL
    if not url:
        _init_error = "DATABASE_URL not configured"
        return None
    try:
        _pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
        logger.info("Paper journal: asyncpg pool created.")
        return _pool
    except Exception as exc:
        _init_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Paper journal: pool creation failed: %s", exc)
        return None


async def init_tables() -> bool:
    """
    Create journal tables idempotently. Returns True on success.
    Called once at startup. Never raises.
    """
    global _tables_ready, _init_error
    pool = await get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES)
        _tables_ready = True
        logger.info("Paper journal: tables ready.")
        return True
    except Exception as exc:
        _init_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Paper journal: table init failed: %s", exc)
        return False


def pool_exists() -> bool:
    return _pool is not None


def is_ready() -> bool:
    return _tables_ready


def last_error() -> str | None:
    return _init_error
