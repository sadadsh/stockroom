"""Authenticated Assets Catalog Build status and explicit mutation."""

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError
from stockroom.catalog.build import catalog_build_status, run_catalog_build


def catalog_build_router(require_token) -> APIRouter:
    router = APIRouter(prefix="/api/catalog-build", dependencies=[Depends(require_token)])

    @router.get("/status")
    def status(request: Request) -> dict:
        return catalog_build_status(request.app.state.ctx)

    @router.post("")
    def build(request: Request, body: dict | None = None) -> dict:
        if (body or {}).get("confirmed") is not True:
            raise ApiError(422, "Confirm Build Now before starting the Catalog Build.")
        try:
            return run_catalog_build(request.app.state.ctx)
        except RuntimeError as exc:
            raise ApiError(409, str(exc)) from exc
        except ValueError as exc:
            raise ApiError(422, str(exc)) from exc

    return router
