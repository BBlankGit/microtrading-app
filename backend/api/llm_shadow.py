"""
LLM Shadow Analyst API (Phase L1) — read-only status + admin diagnostic.

GET endpoints never trigger an LLM call. The admin diagnostic POST
endpoint allows targeted single-candidate analysis for debugging.

No broker. No live trading. No real orders. LLM output is shadow only.
The API key is never returned, never logged.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from api.dependencies import require_admin_token
from intelligence import llm_shadow as _llm

router = APIRouter(prefix="/api/intelligence/llm", tags=["llm_shadow"])


@router.get("/status")
async def get_llm_status():
    """
    Read-only LLM shadow analyst status. Never triggers an LLM call.
    Safe for dashboard polling.
    """
    return _llm.get_status()


@router.post("/analyze-candidate", dependencies=[Depends(require_admin_token)])
async def analyze_candidate(packet: dict = Body(...)):
    """
    Admin-only diagnostic: analyze a candidate packet directly.

    Bypasses simulator selection logic. Useful for verifying provider
    wiring and the response schema with a known input.
    """
    if not isinstance(packet, dict) or not packet:
        raise HTTPException(status_code=400, detail="packet must be a non-empty JSON object")
    return await _llm.analyze_candidate_packet(packet)
