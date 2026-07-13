"""Per-machine settings surface (spec section 11). Reads the redacted per-machine
config and writes the one field wired end-to-end today: the Mouser API key. The
key is a secret, so GET returns only presence plus a last-4 hint, never the raw
value. PATCH applies it live on the running context (the next enrich reads
ctx.config.mouser_api_key, so no restart) and persists to the config.json."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request


def _hint(key: str) -> str:
    """The last four characters, so the user can confirm which key is stored
    without the surface ever revealing the whole secret. Short keys reveal
    nothing."""
    return key[-4:] if len(key) >= 4 else ""


def _settings_dto(config) -> dict:
    return {
        "mouser_api_key_set": bool(config.mouser_api_key),
        "mouser_api_key_hint": _hint(config.mouser_api_key),
    }


def settings_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/settings", dependencies=[Depends(require_token)])

    @r.get("")
    def get_settings(request: Request) -> dict:
        ctx = request.app.state.ctx
        return _settings_dto(ctx.config)

    @r.patch("")
    def update_settings(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        # only touch a field the caller actually sent, so an empty PATCH is a
        # no-op and an unknown field is ignored rather than corrupting the config
        if "mouser_api_key" in body:
            ctx.config.mouser_api_key = str(body["mouser_api_key"] or "")
            ctx.config.save()
        return _settings_dto(ctx.config)

    return r
