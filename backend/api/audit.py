"""
Phase G1B Part B — admin audit endpoints.

Two endpoints:
  - POST /api/audit/outcomes/resolve (admin)
      Triggers a rate-safe resolver pass for pending forward-return rows.
  - GET /api/audit/persistence/status
      Snapshot of candidate/outcome counts for the freeze readiness check.

Read-only with respect to broker logic. No real orders. Fake-money only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.dependencies import require_admin_token
from paper import outcome_resolver as _resolver

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.post("/outcomes/resolve", dependencies=[Depends(require_admin_token)])
async def resolve_outcomes(
    max_rows: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Resolve up to `max_rows` pending forward-return outcomes (admin)."""
    return await _resolver.resolve_pending(max_rows=max_rows)


@router.get("/persistence/status")
async def persistence_status() -> dict:
    """Public snapshot of persistence coverage (no broker data)."""
    return await _resolver.persistence_status()
