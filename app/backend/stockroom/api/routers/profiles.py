"""Profile management (spec section 5.3/7). Switching profile is a synchronous
context rebuild plus a persisted active-profile flip; the derived index is rebuilt
so reads are consistent immediately (spec section 2.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from stockroom.api.errors import ApiError


def profiles_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/profiles", dependencies=[Depends(require_token)])

    @r.get("")
    def list_profiles(request: Request) -> dict:
        ctx = request.app.state.ctx
        return {"profiles": ctx.profile_store.list(), "active": ctx.profile.name}

    @r.post("")
    def create_profile(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        ctx.profile_store.create(body["name"], archive=bool(body.get("archive", False)))
        # A created profile is a library write (it commits the new libraries/<name>/ tree), so it
        # auto-pushes like a part add. Without this the profile committed only locally while the
        # app still read "synced", so a new profile silently never reached the remote.
        ctx.auto_push()
        return {"profiles": ctx.profile_store.list(), "active": ctx.profile.name}

    @r.post("/{name}/activate")
    def activate(request: Request, name: str) -> dict:
        ctx = request.app.state.ctx
        if not ctx.profile_store.exists(name):
            raise FileNotFoundError(f"no such profile: {name}")
        ctx.switch_profile(name)
        return {"active": ctx.profile.name, "part_count": ctx.index.count()}

    @r.delete("/{name}", status_code=204)
    def delete_profile(request: Request, name: str) -> Response:
        ctx = request.app.state.ctx
        if name == ctx.profile.name:
            raise ApiError(400, "cannot delete the active profile; switch first")
        ctx.profile_store.delete(name)
        ctx.auto_push()  # deleting a profile commits the removal; push it like any library write
        return Response(status_code=204)

    return r
