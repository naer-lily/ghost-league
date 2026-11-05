"""Bearer-token authentication for the print queue service."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

MISSING_TOKEN = "missing_token"
INVALID_AUTHORIZATION = "invalid_authorization"
INVALID_TOKEN = "invalid_token"
TOKEN_NOT_CONFIGURED = "service_token_not_configured"


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail=MISSING_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=401,
            detail=INVALID_AUTHORIZATION,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()


def require_token(expected: str | None):
    """Return a FastAPI dependency enforcing a configured bearer token.

    A missing server-side token fails closed: every request to an
    authenticated route gets 503 instead of being allowed through.
    """

    def dependency(authorization: str | None = Header(default=None)) -> None:
        if not expected:
            raise HTTPException(
                status_code=503,
                detail=TOKEN_NOT_CONFIGURED,
            )
        token = _bearer_token(authorization)
        if not hmac.compare_digest(token, expected):
            raise HTTPException(
                status_code=401,
                detail=INVALID_TOKEN,
                headers={"WWW-Authenticate": "Bearer"},
            )

    return dependency
