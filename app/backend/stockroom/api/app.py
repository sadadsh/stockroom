"""The FastAPI app factory. Installs the single exception handler, wires the
AppContext into app.state, includes every router, and mounts the built frontend
LAST so /api/* routes always win over the SPA's catch-all (spec section 4: the
host is presentation, the API is the surface)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from stockroom.api.context import AppContext
from stockroom.api.errors import error_body, status_for
from stockroom.api.security import make_require_token
from stockroom.api.routers import system as system_router

_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend-dist"


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="Stockroom", version="0.1.0")
    app.state.ctx = context
    require_token = make_require_token(context.token)

    @app.exception_handler(Exception)
    async def _handle(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_for(exc), content=error_body(exc))

    # Register web MIME types before any static mount (the Windows mimetypes trap).
    # Safe no-op on Linux; the assertion is exercised in Task 12.
    from stockroom.host.mime import register_web_mime_types

    register_web_mime_types()

    app.include_router(system_router.router)
    app.include_router(system_router.system_info_router(require_token))

    from stockroom.api.routers import library as library_router_mod
    app.include_router(library_router_mod.library_router(require_token))

    from stockroom.api.routers import altium as altium_router_mod
    app.include_router(altium_router_mod.altium_router(require_token))

    from stockroom.api.routers import previews as previews_router_mod
    app.include_router(previews_router_mod.previews_router(require_token))

    from stockroom.api.routers import duplicates as duplicates_router_mod
    app.include_router(duplicates_router_mod.duplicates_router(require_token))

    from stockroom.api.routers import ingest as ingest_router_mod
    app.include_router(ingest_router_mod.ingest_router(require_token))

    from stockroom.api.routers import enrich as enrich_router_mod
    app.include_router(enrich_router_mod.enrich_router(require_token))

    from stockroom.api.routers import profiles as profiles_router_mod
    app.include_router(profiles_router_mod.profiles_router(require_token))

    from stockroom.api.routers import sync as sync_router_mod
    from stockroom.api.routers import doctor as doctor_router_mod
    app.include_router(sync_router_mod.sync_router(require_token))
    app.include_router(doctor_router_mod.doctor_router(require_token))

    from stockroom.api.routers import update as update_router_mod
    app.include_router(update_router_mod.update_router(require_token))

    from stockroom.api.routers import settings as settings_router_mod
    app.include_router(settings_router_mod.settings_router(require_token))

    from stockroom.api.routers import projects as projects_router_mod
    app.include_router(projects_router_mod.projects_router(require_token))

    from stockroom.api.routers import onboarding as onboarding_router_mod
    app.include_router(onboarding_router_mod.onboarding_router(require_token))

    from stockroom.api.routers import dev as dev_router_mod
    app.include_router(dev_router_mod.dev_router(require_token))

    if _FRONTEND_DIST.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="spa")
    return app
