"""
Minimal Finnhub REST client for the intelligence layer.

No broker. No live trading. No real orders. No AI/LLM.
Read-only API access; never logs the API key.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubError(Exception):
    def __init__(self, message: str, status_code: int = 0, rate_limited: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.rate_limited = rate_limited


def is_configured() -> bool:
    """True iff FINNHUB_API_KEY is set to a non-placeholder value."""
    key = (settings.FINNHUB_API_KEY or "").strip()
    if not key:
        return False
    return key.upper() not in {"PASTE_YOUR_KEY_HERE", "CHANGEME", "NONE", "NULL"}


def _sanitize_for_log(url: str) -> str:
    """Strip token=... query param from URLs before they reach a log line."""
    if "token=" not in url:
        return url
    parts = url.split("?", 1)
    if len(parts) != 2:
        return parts[0]
    pairs = []
    for kv in parts[1].split("&"):
        if kv.startswith("token="):
            pairs.append("token=<redacted>")
        else:
            pairs.append(kv)
    return parts[0] + "?" + "&".join(pairs)


async def get(path: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
    """
    GET helper. Token is injected via query param; never logged.
    Raises FinnhubError on non-2xx; rate_limited=True on 429.
    """
    if not is_configured():
        raise FinnhubError("FINNHUB_API_KEY not configured", status_code=0)
    q = dict(params or {})
    q["token"] = settings.FINNHUB_API_KEY
    url = f"{_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=q)
    except httpx.RequestError as exc:
        logger.warning("Finnhub request error for %s: %s", _sanitize_for_log(path), type(exc).__name__)
        raise FinnhubError(f"network: {type(exc).__name__}", status_code=0)

    if resp.status_code == 429:
        raise FinnhubError("rate limited", status_code=429, rate_limited=True)
    if resp.status_code >= 400:
        # Never log resp.text — Finnhub error payloads can include the token on
        # some endpoints. Log the status only.
        logger.warning("Finnhub %s returned %d", _sanitize_for_log(path), resp.status_code)
        raise FinnhubError(f"http {resp.status_code}", status_code=resp.status_code)
    try:
        return resp.json()
    except Exception as exc:
        raise FinnhubError(f"json decode: {exc}", status_code=resp.status_code)
