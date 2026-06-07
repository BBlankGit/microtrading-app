import hmac

from fastapi import Header, HTTPException

from core.config import settings

_UNCONFIGURED_SENTINELS = {"", "replace_me_for_admin_operations"}


async def require_admin_token(authorization: str | None = Header(default=None)) -> None:
    """
    FastAPI dependency for state-changing admin endpoints (stream start/stop).

    Returns 503 if ADMIN_API_TOKEN is not properly configured.
    Returns 401 if the Authorization header is missing or the token is wrong.
    Token comparison uses hmac.compare_digest to prevent timing-based leakage.
    Never logs or returns the expected token value.
    """
    token = settings.ADMIN_API_TOKEN.strip()
    if token in _UNCONFIGURED_SENTINELS:
        raise HTTPException(
            status_code=503,
            detail="Admin operations are disabled until ADMIN_API_TOKEN is configured.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing or malformed.",
        )
    provided = authorization[len("Bearer "):]
    if not hmac.compare_digest(provided, token):
        raise HTTPException(status_code=401, detail="Invalid token.")
