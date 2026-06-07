"""
Runtime strategy configuration API.

No broker. No live trading. No real orders. No real-money execution.
Configuration affects fake-money paper simulation parameters only.

GET  /api/config/runtime        — read-only, no auth
PATCH /api/config/runtime       — admin-protected
POST /api/config/runtime/reset  — admin-protected
GET  /api/config/runtime/schema — read-only, no auth
"""

from fastapi import APIRouter, Body, Depends, HTTPException

from api.dependencies import require_admin_token
from paper import runtime_config as rc

router = APIRouter(prefix="/api/config", tags=["runtime_config"])

DISCLAIMER = (
    "Runtime settings affect fake-money simulation only. "
    "No broker, no live trading, no real orders."
)


@router.get("/runtime")
async def get_runtime_config():
    """
    Read-only. Returns runtime overrides, base config, and effective config.
    No admin token required.
    """
    return {
        "runtime_overrides": rc.get_runtime_config(),
        "base_config": rc.get_base_config(),
        "effective_config": rc.get_effective_config(),
        "persistent": rc._persistent,
        "warnings": [rc._persistence_warning] if rc._persistence_warning else [],
        "disclaimer": DISCLAIMER,
    }


@router.patch("/runtime")
async def patch_runtime_config(
    payload: dict = Body(...),
    _: None = Depends(require_admin_token),
):
    """
    Apply runtime overrides. Admin token required.
    Body: {"updates": {...}, "updated_by": "optional_label"}
    Returns 400 with validation errors if any field is invalid.
    All fields must be valid — no partial application on failure.
    """
    updates = payload.get("updates")
    if not isinstance(updates, dict) or not updates:
        raise HTTPException(status_code=400, detail="Body must contain a non-empty 'updates' dict.")

    updated_by: str | None = payload.get("updated_by")

    ok, errors = rc.validate_runtime_config(updates)
    if not ok:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    try:
        effective = await rc.update_runtime_config(updates, updated_by=updated_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"validation_errors": list(exc.args[0])})

    return {
        "ok": True,
        "applied": updates,
        "effective_config": effective,
        "persistent": rc._persistent,
        "warnings": [rc._persistence_warning] if rc._persistence_warning else [],
        "disclaimer": DISCLAIMER,
    }


@router.post("/runtime/reset")
async def reset_runtime_config(
    payload: dict = Body(default={}),
    _: None = Depends(require_admin_token),
):
    """
    Clear all runtime overrides. Admin token required.
    Returns effective config (all base values).
    """
    updated_by: str | None = payload.get("updated_by") if isinstance(payload, dict) else None
    effective = await rc.reset_runtime_config(updated_by=updated_by)
    return {
        "ok": True,
        "overrides_cleared": True,
        "effective_config": effective,
        "persistent": rc._persistent,
        "warnings": [rc._persistence_warning] if rc._persistence_warning else [],
        "disclaimer": DISCLAIMER,
    }


@router.get("/runtime/schema")
async def get_runtime_schema():
    """
    Read-only schema for all configurable fields.
    Returns types, bounds, descriptions, and current values.
    Never exposes secrets.
    """
    return {
        "fields": rc.get_schema(),
        "disclaimer": DISCLAIMER,
        "note": "Secrets (API keys, tokens, DB URLs) are never included in this schema.",
    }
