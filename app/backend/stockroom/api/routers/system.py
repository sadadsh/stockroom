"""Liveness and a small system-info readout. /api/health is the one unauthenticated
route (the host polls it to know the server is up before opening the window)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.kicad.config import detect_running_kicad

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _ctx(request: Request):
    return request.app.state.ctx


def system_info_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/system", dependencies=[Depends(require_token)])

    @r.get("/info")
    def info(request: Request) -> dict:
        ctx = _ctx(request)
        return {
            "active_profile": ctx.profile.name,
            "part_count": ctx.index.count(),
            "kicad_config_dir": ctx.kicad_dir.as_posix(),
            "kicad_running": detect_running_kicad(),
            # so the UI can honestly surface when previews/import are unavailable
            "kicad_cli_available": ctx.cli.available,
            "kicad_cli_path": ctx.cli.binary or "",
        }

    return r
