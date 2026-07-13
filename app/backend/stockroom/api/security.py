"""Per-launch bearer-token guard (defense in depth, spec section 2.2).

The primary boundary is the loopback bind (127.0.0.1 only); this token stops
another local process on the machine from driving the library through the API.
The token is minted fresh at app construction and handed to the renderer by the
host, so it never persists and never leaves the machine. Compared in constant
time so the check is not timing-leaky."""

from __future__ import annotations

import secrets
from typing import Callable

from fastapi import Request

from stockroom.api.errors import ApiError


def mint_token() -> str:
    return secrets.token_urlsafe(32)


def _presented(request) -> str:
    auth = request.headers.get("Authorization", "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-Stockroom-Token", "") or "").strip()


def make_require_token(expected: str) -> Callable:
    def require_token(request: Request) -> None:
        presented = _presented(request)
        if not presented or not secrets.compare_digest(presented, expected):
            raise ApiError(401, "missing or invalid API token")

    return require_token
