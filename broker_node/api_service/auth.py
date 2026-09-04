from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Header, HTTPException


def require_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "AUTH_FAILED", "message": "Bearer token is required"})
    expected = os.environ.get("BROKER_NODE_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "API token is not configured"})
    provided = authorization[7:]
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail={"code": "AUTH_FAILED", "message": "Invalid bearer token"})
