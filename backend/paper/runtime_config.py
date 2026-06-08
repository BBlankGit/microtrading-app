"""
Runtime strategy configuration for the fake-money paper simulator.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. Configuration affects fake-money simulation parameters only.

Provides a two-layer config system:
  1. Base settings from .env / Settings (read-only, via core.config.settings)
  2. Runtime overrides stored in memory and persisted to Postgres

Effective value = runtime override if present, else base setting.
All changes are admin-protected, bounded, and auditable.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── In-memory override store ──────────────────────────────────────────────────

_runtime_overrides: dict[str, Any] = {}
_persistent: bool = False
_persistence_warning: str | None = None

# ── Schema definition ─────────────────────────────────────────────────────────

# Each field: (type, min, max, description)
# bool fields have min/max = None
_SCHEMA: dict[str, dict] = {
    "PAPER_ENTRY_SCORE_THRESHOLD": {
        "type": "int", "min": 0, "max": 100,
        "description": "Minimum score (0-100) for a candidate to pass entry evaluation.",
        "category": "trading",
        "runtime_applied": True, "applies_to": "scoring", "restart_required": False,
    },
    "PAPER_TAKE_PROFIT_PERCENT": {
        "type": "float", "min": 0.05, "max": 20.0,
        "description": "Take-profit exit trigger as percent above entry price.",
        "category": "trading",
        "runtime_applied": True, "applies_to": "risk", "restart_required": False,
    },
    "PAPER_STOP_LOSS_PERCENT": {
        "type": "float", "min": 0.05, "max": 20.0,
        "description": "Stop-loss exit trigger as percent below entry price.",
        "category": "trading",
        "runtime_applied": True, "applies_to": "risk", "restart_required": False,
    },
    "PAPER_MAX_HOLD_MINUTES": {
        "type": "int", "min": 1, "max": 390,
        "description": "Maximum hold time in minutes before forced exit.",
        "category": "trading",
        "runtime_applied": True, "applies_to": "risk", "restart_required": False,
    },
    "PAPER_MAX_OPEN_POSITIONS": {
        "type": "int", "min": 1, "max": 50,
        "description": "Maximum number of simultaneous open positions.",
        "category": "trading",
        "runtime_applied": True, "applies_to": "position_sizing", "restart_required": False,
    },
    "PAPER_MAX_TRADES_PER_DAY": {
        "type": "int", "min": 1, "max": 500,
        "description": "Maximum trades allowed per calendar day.",
        "category": "trading",
        "runtime_applied": True, "applies_to": "position_sizing", "restart_required": False,
    },
    "PAPER_POSITION_SIZE_PERCENT": {
        "type": "float", "min": 1.0, "max": 100.0,
        "description": "Position size as percent of available cash (capped by PAPER_MAX_POSITION_SIZE_USD).",
        "category": "trading",
        "runtime_applied": True, "applies_to": "position_sizing", "restart_required": False,
    },
    "PAPER_REJECT_STRONG_BEARISH_CATALYST": {
        "type": "bool", "min": None, "max": None,
        "description": "Hard-reject candidates with strong bearish catalyst sentiment.",
        "category": "catalyst",
        "runtime_applied": True, "applies_to": "scoring", "restart_required": False,
    },
    "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY": {
        "type": "float", "min": 0.0, "max": 1.0,
        "description": "Materiality threshold (0.0-1.0) for strong-bearish hard rejection.",
        "category": "catalyst",
        "runtime_applied": True, "applies_to": "scoring", "restart_required": False,
    },
    "PAPER_MAX_UNIVERSE_SIZE": {
        "type": "int", "min": 10, "max": 1000,
        "description": "Maximum symbols in the universe candidate pool.",
        "category": "universe",
        "runtime_applied": True, "applies_to": "universe", "restart_required": False,
    },
    "PAPER_MAX_SYMBOLS_PER_TICK": {
        "type": "int", "min": 1, "max": 300,
        "description": "Maximum active symbols evaluated each tick.",
        "category": "universe",
        "runtime_applied": True, "applies_to": "universe", "restart_required": False,
    },
    "PAPER_DYNAMIC_UNIVERSE_ENABLED": {
        "type": "bool", "min": None, "max": None,
        "description": "Enable dynamic universe ranking and filtering.",
        "category": "universe",
        "runtime_applied": True, "applies_to": "universe", "restart_required": False,
    },
    "PAPER_DYNAMIC_REFRESH_SECONDS": {
        "type": "int", "min": 10, "max": 3600,
        "description": "Universe cache TTL in seconds.",
        "category": "universe",
        "runtime_applied": True, "applies_to": "universe", "restart_required": False,
    },
    "PAPER_MARKET_DISCOVERY_ENABLED": {
        "type": "bool", "min": None, "max": None,
        "description": "Enable market-wide movers discovery (gainers/losers expansion).",
        "category": "discovery",
        "runtime_applied": True, "applies_to": "discovery", "restart_required": False,
    },
    "PAPER_MARKET_DISCOVERY_MAX_SYMBOLS": {
        "type": "int", "min": 0, "max": 500,
        "description": "Maximum symbols to pull from discovery sources.",
        "category": "discovery",
        "runtime_applied": True, "applies_to": "discovery", "restart_required": False,
    },
    "PAPER_MARKET_DISCOVERY_REFRESH_SECONDS": {
        "type": "int", "min": 10, "max": 3600,
        "description": "Discovery cache TTL in seconds.",
        "category": "discovery",
        "runtime_applied": True, "applies_to": "discovery", "restart_required": False,
    },
    "PAPER_MARKET_DISCOVERY_MIN_PRICE": {
        "type": "float", "min": 0.01, "max": 9999.0,
        "description": "Minimum price filter for discovered symbols.",
        "category": "discovery",
        "runtime_applied": True, "applies_to": "discovery", "restart_required": False,
    },
    "PAPER_MARKET_DISCOVERY_MAX_PRICE": {
        "type": "float", "min": 0.01, "max": 9999.0,
        "description": "Maximum price filter for discovered symbols.",
        "category": "discovery",
        "runtime_applied": True, "applies_to": "discovery", "restart_required": False,
    },
    "PAPER_MARKET_DISCOVERY_MIN_VOLUME": {
        "type": "int", "min": 0, "max": 1_000_000_000,
        "description": "Minimum daily volume for discovered symbols.",
        "category": "discovery",
        "runtime_applied": True, "applies_to": "discovery", "restart_required": False,
    },
    "PAPER_MARKET_DISCOVERY_MIN_ABS_CHANGE_PERCENT": {
        "type": "float", "min": 0.0, "max": 100.0,
        "description": "Minimum absolute change % for discovered symbols.",
        "category": "discovery",
        "runtime_applied": True, "applies_to": "discovery", "restart_required": False,
    },
    "MARKET_REGIME_ENABLED": {
        "type": "bool", "min": None, "max": None,
        "description": "Enable market regime monitoring (observational only).",
        "category": "regime",
        "runtime_applied": True, "applies_to": "market_regime", "restart_required": False,
    },
    "MARKET_REGIME_REFRESH_SECONDS": {
        "type": "int", "min": 10, "max": 3600,
        "description": "Regime cache TTL in seconds.",
        "category": "regime",
        "runtime_applied": True, "applies_to": "market_regime", "restart_required": False,
    },
    "MARKET_REGIME_MIN_RISK_ON_SCORE": {
        "type": "int", "min": 0, "max": 100,
        "description": "Minimum score to classify as risk-on regime.",
        "category": "regime",
        "runtime_applied": True, "applies_to": "market_regime", "restart_required": False,
    },
    "MARKET_REGIME_MAX_RISK_OFF_SCORE": {
        "type": "int", "min": 0, "max": 100,
        "description": "Maximum score to classify as risk-off regime.",
        "category": "regime",
        "runtime_applied": True, "applies_to": "market_regime", "restart_required": False,
    },
    "PAPER_MOMENTUM_MODE_ENABLED": {
        "type": "bool", "min": None, "max": None,
        "description": "Enable momentum entry mode fallback (disabled by default). No broker, no real orders.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD": {
        "type": "int", "min": 0, "max": 100,
        "description": "Minimum momentum score (0-100) required for momentum-mode entry.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_MIN_CHANGE_PERCENT": {
        "type": "float", "min": 0.0, "max": 20.0,
        "description": "Minimum price change % required for momentum-mode entry.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_MIN_VOLUME_RATIO": {
        "type": "float", "min": 0.0, "max": 100.0,
        "description": "Minimum volume ratio required for momentum-mode entry.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_MAX_SPREAD_PERCENT": {
        "type": "float", "min": 0.01, "max": 5.0,
        "description": "Maximum spread % allowed for momentum-mode entry.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON": {
        "type": "bool", "min": None, "max": None,
        "description": "Require risk-on market regime for momentum-mode entries.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE": {
        "type": "int", "min": 0, "max": 100,
        "description": "Minimum market risk-on score for momentum-mode entry.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER": {
        "type": "float", "min": 0.1, "max": 1.0,
        "description": "Position size multiplier for momentum entries (fraction of normal size).",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    "PAPER_MOMENTUM_MAX_TRADES_PER_DAY": {
        "type": "int", "min": 0, "max": 300,
        "description": "Maximum momentum-mode entries per calendar day.",
        "category": "momentum",
        "runtime_applied": True, "applies_to": "momentum", "restart_required": False,
    },
    # Volume hard gate (Phase 2O — runtime configurable, no broker, no real orders)
    "PAPER_MIN_VOLUME_RATIO": {
        "type": "float", "min": 0.0, "max": 5.0,
        "description": (
            "Minimum relative volume ratio required before opening a fake-money position. "
            "Candidates with volume_ratio below this threshold are hard-rejected. "
            "Lower values allow early-session entries with below-average volume."
        ),
        "category": "quality",
        "runtime_applied": True, "applies_to": "scoring", "restart_required": False,
    },
    # Daily loss guard (Phase 2N — fake-money only, no broker, no real orders)
    "PAPER_DAILY_MAX_LOSS_ENABLED": {
        "type": "bool", "min": None, "max": None,
        "description": (
            "Enable daily max loss guard for fake-money simulation. "
            "Blocks new entries when daily P&L falls below threshold. "
            "Never prevents exits. No broker, no real orders."
        ),
        "category": "risk",
        "runtime_applied": True, "applies_to": "risk", "restart_required": False,
    },
    "PAPER_DAILY_MAX_LOSS_PERCENT": {
        "type": "float", "min": 0.1, "max": 20.0,
        "description": (
            "Daily max loss as percent of starting cash. "
            "Guard triggers when daily P&L < -threshold%. Fake-money only."
        ),
        "category": "risk",
        "runtime_applied": True, "applies_to": "risk", "restart_required": False,
    },
    "PAPER_DAILY_MAX_LOSS_USD": {
        "type": "float", "min": 0.0, "max": 1_000_000.0,
        "description": (
            "Daily max loss in USD. If <= 0, USD threshold is ignored. "
            "Guard triggers when either percent or USD threshold is breached. Fake-money only."
        ),
        "category": "risk",
        "runtime_applied": True, "applies_to": "risk", "restart_required": False,
    },
}

# Sentinel: fields that map to settings attributes under different names
_SETTINGS_ALIAS: dict[str, str] = {
    "PAPER_MAX_OPEN_POSITIONS": "PAPER_MAX_POSITIONS",
    "PAPER_POSITION_SIZE_PERCENT": None,  # computed from PAPER_MAX_POSITION_SIZE_USD
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_runtime_config() -> dict[str, Any]:
    """Return current in-memory runtime overrides."""
    return dict(_runtime_overrides)


def get_base_config() -> dict[str, Any]:
    """Return base config values from settings for all managed fields."""
    from core.config import settings
    base: dict[str, Any] = {}
    for field in _SCHEMA:
        alias = _SETTINGS_ALIAS.get(field)
        if alias is None and field == "PAPER_POSITION_SIZE_PERCENT":
            # Derive from position size USD and starting cash
            pct = (settings.PAPER_MAX_POSITION_SIZE_USD / settings.PAPER_STARTING_CASH * 100.0
                   if settings.PAPER_STARTING_CASH > 0 else 25.0)
            base[field] = round(pct, 2)
        elif alias is not None:
            base[field] = getattr(settings, alias, None)
        else:
            base[field] = getattr(settings, field, None)
    return base


def get_effective_config() -> dict[str, Any]:
    """Return merged config: runtime override if present, else base."""
    effective = get_base_config()
    effective.update(_runtime_overrides)
    return effective


def effective_value(field: str) -> Any:
    """Return the effective value for a single field."""
    if field in _runtime_overrides:
        return _runtime_overrides[field]
    from core.config import settings
    alias = _SETTINGS_ALIAS.get(field)
    if alias is None and field == "PAPER_POSITION_SIZE_PERCENT":
        pct = (settings.PAPER_MAX_POSITION_SIZE_USD / settings.PAPER_STARTING_CASH * 100.0
               if settings.PAPER_STARTING_CASH > 0 else 25.0)
        return round(pct, 2)
    if alias is not None:
        return getattr(settings, alias, None)
    return getattr(settings, field, None)


def validate_runtime_config(updates: dict) -> tuple[bool, list[str]]:
    """
    Validate a set of proposed updates.
    Returns (ok: bool, errors: list[str]).
    All fields must pass; no partial application on failure.
    """
    errors: list[str] = []

    for key, value in updates.items():
        if key not in _SCHEMA:
            errors.append(f"Unknown field: {key!r}")
            continue

        spec = _SCHEMA[key]
        expected_type = spec["type"]

        if expected_type == "bool":
            if not isinstance(value, bool):
                errors.append(f"{key}: expected bool, got {type(value).__name__}")
        elif expected_type == "int":
            if isinstance(value, float) and value == int(value):
                value = int(value)  # accept 75.0 as 75
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"{key}: expected int, got {type(value).__name__}")
            elif spec["min"] is not None and value < spec["min"]:
                errors.append(f"{key}: {value} is below minimum {spec['min']}")
            elif spec["max"] is not None and value > spec["max"]:
                errors.append(f"{key}: {value} exceeds maximum {spec['max']}")
        elif expected_type == "float":
            if isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if not isinstance(value, float):
                errors.append(f"{key}: expected float, got {type(value).__name__}")
            elif spec["min"] is not None and value < spec["min"]:
                errors.append(f"{key}: {value} is below minimum {spec['min']}")
            elif spec["max"] is not None and value > spec["max"]:
                errors.append(f"{key}: {value} exceeds maximum {spec['max']}")

    # Cross-field: discovery price min < max
    min_price = updates.get("PAPER_MARKET_DISCOVERY_MIN_PRICE",
                            _runtime_overrides.get("PAPER_MARKET_DISCOVERY_MIN_PRICE",
                            effective_value("PAPER_MARKET_DISCOVERY_MIN_PRICE")))
    max_price = updates.get("PAPER_MARKET_DISCOVERY_MAX_PRICE",
                            _runtime_overrides.get("PAPER_MARKET_DISCOVERY_MAX_PRICE",
                            effective_value("PAPER_MARKET_DISCOVERY_MAX_PRICE")))
    if (min_price is not None and max_price is not None and
            not errors and min_price >= max_price):
        errors.append(
            f"PAPER_MARKET_DISCOVERY_MIN_PRICE ({min_price}) must be less than "
            f"PAPER_MARKET_DISCOVERY_MAX_PRICE ({max_price})"
        )

    # Cross-field: regime risk_off < risk_on
    risk_on = updates.get("MARKET_REGIME_MIN_RISK_ON_SCORE",
                          _runtime_overrides.get("MARKET_REGIME_MIN_RISK_ON_SCORE",
                          effective_value("MARKET_REGIME_MIN_RISK_ON_SCORE")))
    risk_off = updates.get("MARKET_REGIME_MAX_RISK_OFF_SCORE",
                           _runtime_overrides.get("MARKET_REGIME_MAX_RISK_OFF_SCORE",
                           effective_value("MARKET_REGIME_MAX_RISK_OFF_SCORE")))
    if (risk_on is not None and risk_off is not None and
            not errors and risk_off >= risk_on):
        errors.append(
            f"MARKET_REGIME_MAX_RISK_OFF_SCORE ({risk_off}) must be less than "
            f"MARKET_REGIME_MIN_RISK_ON_SCORE ({risk_on})"
        )

    return len(errors) == 0, errors


async def update_runtime_config(
    updates: dict,
    updated_by: str | None = None,
) -> dict[str, Any]:
    """
    Validate and apply updates atomically.
    Returns the new effective config. Raises ValueError on validation failure.
    """
    global _runtime_overrides, _persistent, _persistence_warning

    ok, errors = validate_runtime_config(updates)
    if not ok:
        raise ValueError(errors)

    # Coerce types before storing
    coerced: dict[str, Any] = {}
    for key, value in updates.items():
        spec = _SCHEMA[key]
        if spec["type"] == "int" and isinstance(value, float):
            value = int(value)
        elif spec["type"] == "float" and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        coerced[key] = value

    old_overrides = dict(_runtime_overrides)
    _runtime_overrides.update(coerced)

    # Persist to Postgres
    await _persist_to_db(coerced, old_overrides, updated_by)

    return get_effective_config()


async def reset_runtime_config(updated_by: str | None = None) -> dict[str, Any]:
    """Clear all runtime overrides and return the base effective config."""
    global _runtime_overrides
    old = dict(_runtime_overrides)
    _runtime_overrides = {}
    await _persist_reset_to_db(old, updated_by)
    return get_effective_config()


def get_schema() -> dict[str, Any]:
    """Return field schema with base values. Does not expose secrets."""
    base = get_base_config()
    out: dict[str, Any] = {}
    for field, spec in _SCHEMA.items():
        out[field] = {
            "type": spec["type"],
            "description": spec["description"],
            "category": spec["category"],
            "min": spec["min"],
            "max": spec["max"],
            "runtime_applied": spec.get("runtime_applied", True),
            "applies_to": spec.get("applies_to"),
            "restart_required": spec.get("restart_required", False),
            "base_value": base.get(field),
            "runtime_override": _runtime_overrides.get(field),
            "effective_value": effective_value(field),
        }
    return out


def get_runtime_status() -> dict[str, Any]:
    """Summary for monitoring endpoint."""
    return {
        "overrides_active": len(_runtime_overrides) > 0,
        "override_count": len(_runtime_overrides),
        "persistent": _persistent,
        "warnings": [_persistence_warning] if _persistence_warning else [],
    }


# ── Postgres persistence ──────────────────────────────────────────────────────

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS paper_runtime_config (
    key         TEXT PRIMARY KEY,
    value_json  JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  TEXT
);

CREATE TABLE IF NOT EXISTS paper_runtime_config_audit (
    id              SERIAL PRIMARY KEY,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    key             TEXT NOT NULL,
    old_value_json  JSONB,
    new_value_json  JSONB,
    updated_by      TEXT,
    source          TEXT DEFAULT 'api'
);
"""


async def init_runtime_config_tables() -> bool:
    """Create tables and load any persisted overrides into memory. Never raises."""
    global _persistent, _persistence_warning
    try:
        from paper.db import get_pool
        pool = await get_pool()
        if pool is None:
            _persistence_warning = "DB unavailable — runtime config is memory-only."
            logger.warning("Runtime config: DB unavailable, using memory-only.")
            return False
        async with pool.acquire() as conn:
            await conn.execute(_INIT_SQL)
            rows = await conn.fetch("SELECT key, value_json FROM paper_runtime_config")
            for row in rows:
                key = row["key"]
                if key in _SCHEMA:
                    try:
                        _runtime_overrides[key] = json.loads(row["value_json"])
                    except Exception:
                        pass
        _persistent = True
        _persistence_warning = None
        logger.info("Runtime config: tables ready, %d overrides loaded.", len(_runtime_overrides))
        return True
    except Exception as exc:
        _persistence_warning = f"DB persistence unavailable: {type(exc).__name__}: {exc}"
        logger.warning("Runtime config: table init failed: %s", exc)
        return False


async def _persist_to_db(
    updates: dict,
    old_overrides: dict,
    updated_by: str | None,
) -> None:
    global _persistent, _persistence_warning
    try:
        from paper.db import get_pool
        pool = await get_pool()
        if pool is None:
            _persistence_warning = "DB unavailable — runtime config is memory-only."
            return
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            async with conn.transaction():
                for key, value in updates.items():
                    value_json = json.dumps(value)
                    old_json = json.dumps(old_overrides.get(key))
                    await conn.execute(
                        """
                        INSERT INTO paper_runtime_config (key, value_json, updated_at, updated_by)
                        VALUES ($1, $2::jsonb, $3, $4)
                        ON CONFLICT (key) DO UPDATE
                            SET value_json = EXCLUDED.value_json,
                                updated_at = EXCLUDED.updated_at,
                                updated_by = EXCLUDED.updated_by
                        """,
                        key, value_json, now, updated_by,
                    )
                    await conn.execute(
                        """
                        INSERT INTO paper_runtime_config_audit
                            (changed_at, key, old_value_json, new_value_json, updated_by, source)
                        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
                        """,
                        now, key, old_json, value_json, updated_by, "api",
                    )
        _persistent = True
        _persistence_warning = None
    except Exception as exc:
        _persistence_warning = f"Persist failed: {type(exc).__name__}: {exc}"
        logger.warning("Runtime config: persist failed: %s", exc)


async def _persist_reset_to_db(old_overrides: dict, updated_by: str | None) -> None:
    global _persistence_warning
    try:
        from paper.db import get_pool
        pool = await get_pool()
        if pool is None:
            return
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            async with conn.transaction():
                for key, old_val in old_overrides.items():
                    old_json = json.dumps(old_val)
                    await conn.execute(
                        "DELETE FROM paper_runtime_config WHERE key = $1", key
                    )
                    await conn.execute(
                        """
                        INSERT INTO paper_runtime_config_audit
                            (changed_at, key, old_value_json, new_value_json, updated_by, source)
                        VALUES ($1, $2, $3::jsonb, NULL, $4, $5)
                        """,
                        now, key, old_json, updated_by, "reset",
                    )
        _persistence_warning = None
    except Exception as exc:
        _persistence_warning = f"Reset persist failed: {type(exc).__name__}: {exc}"
        logger.warning("Runtime config: reset persist failed: %s", exc)
