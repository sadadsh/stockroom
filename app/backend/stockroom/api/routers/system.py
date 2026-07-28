"""Liveness and a small system-info readout. /api/health is the one unauthenticated
route (the host polls it to know the server is up before opening the window)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError
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

    @r.get("/workflow-coordinator")
    def workflow_coordinator(request: Request) -> dict:
        coordinator = _ctx(request).workflow_coordinator
        if coordinator is None:
            raise ApiError(503, "The durable workflow coordinator is not mounted.")
        status = coordinator.status()
        return {
            "state": status.state.value,
            "generation": status.generation,
            "worker_limit": status.worker_limit,
            "in_flight": status.in_flight,
            "peak_in_flight": status.peak_in_flight,
            "poll_round_count": status.poll_round_count,
            "poll_count": status.poll_count,
            "dispatch_count": status.dispatch_count,
            "idle_poll_count": status.idle_poll_count,
            "recovered_claim_count": status.recovered_claim_count,
            "handler_error_count": status.handler_error_count,
            "unexpected_error_count": status.unexpected_error_count,
            "idle_round_count": status.idle_round_count,
            "current_backoff_seconds": status.current_backoff_seconds,
            "minimum_worker_polls": status.minimum_worker_polls,
            "maximum_worker_polls": status.maximum_worker_polls,
            "started_at": status.started_at,
            "last_activity_at": status.last_activity_at,
            "stopped_at": status.stopped_at,
            "last_error_code": status.last_error_code,
            "thread_alive": status.thread_alive,
        }

    return r
