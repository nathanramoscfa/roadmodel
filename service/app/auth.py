# service/app/auth.py
from __future__ import annotations

import hmac
import os
from typing import Final

from fastapi import HTTPException, Request

_INTERNAL_TOKEN_RAW = os.environ.get("ROADMODEL_INTERNAL_TOKEN")
if not _INTERNAL_TOKEN_RAW:
    raise RuntimeError("ROADMODEL_INTERNAL_TOKEN is required")
_INTERNAL_TOKEN: Final[str] = _INTERNAL_TOKEN_RAW


def require_bearer(request: Request) -> Request:
    authorization = request.headers.get("Authorization")
    if authorization is None:
        raise HTTPException(status_code=401, detail="invalid_or_missing_bearer")

    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        raise HTTPException(status_code=401, detail="invalid_or_missing_bearer")

    if not hmac.compare_digest(token, _INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="invalid_or_missing_bearer")

    return request
