"""Liveness and a small system-info readout. /api/health is the one unauthenticated
route (the host polls it to know the server is up before opening the window)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from stockroom import BUILD_IDENTITY
from stockroom.api.errors import ApiError
from stockroom.kicad.config import detect_running_kicad
from stockroom.service import CoordinatorStatus

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request) -> JSONResponse:
    """Process identity as well as liveness for host-gated release adoption."""

    ctx = request.app.state.ctx
    expected_generation = getattr(ctx, "service_generation", 0)
    expected_mode = getattr(ctx, "service_mode", "standalone")
    status_code = 200
    payload: dict[str, object] = {
        "status": "ok",
        "release_id": getattr(ctx, "release_id", ""),
        "service_generation": expected_generation,
        "service_mode": expected_mode,
        "coordinator_status": "unmanaged",
    }
    # The native host has not sent its API bearer when it performs this probe. Instead it supplies
    # a fresh public nonce and verifies this HMAC against an independent one-use startup secret
    # inherited only by the process it spawned. Binding the exact PID and release prevents a local
    # process that won the reserved loopback port from impersonating a ready packaged worker and
    # receiving the real bearer during WebView navigation.
    startup_nonce = request.headers.get("X-Stockroom-Startup-Nonce", "")
    startup_secret = getattr(ctx, "startup_proof_token", "")
    if (
        isinstance(startup_secret, str)
        and startup_secret
        and re.fullmatch(r"[0-9a-f]{64}", startup_nonce)
    ):
        process_id = os.getpid()
        proof_message = (
            f"stockroom-packaged-worker-v1\0{payload['release_id']}\0"
            f"{process_id}\0{startup_nonce}"
        ).encode("ascii")
        payload["startup_process_id"] = process_id
        payload["startup_proof"] = hmac.new(
            startup_secret.encode("ascii"),
            proof_message,
            hashlib.sha256,
        ).hexdigest()
    control = getattr(ctx, "service_control", None)
    authority_required = bool(
        getattr(ctx, "service_authority_required", False)
    )
    if authority_required and control is None:
        payload["status"] = "degraded"
        payload["coordinator_status"] = "unavailable"
        payload["blocking_reason"] = (
            getattr(ctx, "service_degraded_reason", "")
            or "service_authority_unavailable"
        )
        status_code = 503
    elif control is not None:
        snapshot = control.snapshot()
        payload["service_generation"] = snapshot.generation
        payload["coordinator_status"] = snapshot.status.value
        if (
            snapshot.status is not CoordinatorStatus.ACTIVE
            or snapshot.generation != expected_generation
            or snapshot.mode.value != expected_mode
        ):
            payload["status"] = "stale"
            status_code = 503
    return JSONResponse(status_code=status_code, content=payload)


def _ctx(request: Request):
    return request.app.state.ctx


def system_info_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/system", dependencies=[Depends(require_token)])

    @r.get("/identity")
    def identity(request: Request) -> dict:
        """Return the immutable build and active service identity.

        Unlike ``/api/health``, this authenticated endpoint is an acceptance
        surface: release rehearsals can prove which manifest-bound backend is
        actually serving the stable window without treating liveness as build
        identity.
        """

        ctx = _ctx(request)
        return {
            "release_id": getattr(ctx, "release_id", "")
            or BUILD_IDENTITY.release_id,
            "build_release_id": BUILD_IDENTITY.release_id,
            "package_version": BUILD_IDENTITY.package_version,
            "protocol_version": BUILD_IDENTITY.protocol_version,
            "source_revision": BUILD_IDENTITY.source_revision,
            "service_generation": getattr(ctx, "service_generation", 0),
            "service_mode": getattr(ctx, "service_mode", "standalone"),
        }

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
