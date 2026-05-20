# service/app/auth.py
from __future__ import annotations

import hmac
import os
from typing import Final

from fastapi import HTTPException, Request


def _internal_token() -> str:
    token = os.environ.get("ROADMODEL_INTERNAL_TOKEN")
    if not token:
        raise HTTPException(
            status_code=503,
            detail="internal_token_unconfigured",
        )
    return token


def require_bearer(request: Request) -> Request:
    """Validate Authorization: Bearer against ROADMODEL_INTERNAL_TOKEN."""
    authorization = request.headers.get("Authorization")
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="invalid_or_missing_bearer",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="invalid_or_missing_bearer",
        )

    expected: Final[str] = _internal_token()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="invalid_or_missing_bearer",
        )

    return request
