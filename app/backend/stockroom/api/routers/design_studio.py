"""Authenticated, machine-scoped Design Studio persistence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from stockroom.api.errors import ApiError
from stockroom.design_studio.personal import (
    PersonalDesignConflict,
    PersonalDesignValidationError,
    delete_personal_design,
    load_personal_design,
    save_personal_design,
)


class PersonalDesignSaveBody(BaseModel):
    """The complete document and the revision it was edited from."""

    model_config = ConfigDict(extra="forbid", strict=True)

    document: dict[str, object]
    expected_revision: str | None


class PersonalDesignDeleteBody(BaseModel):
    """The revision that authorizes removal of the current document."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: str | None


class PersonalDesignResponse(BaseModel):
    """The whole current personal design, or explicit absence."""

    model_config = ConfigDict(extra="forbid", strict=True)

    revision: str | None
    document: dict[str, object] | None


class PersonalDesignDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ok: bool


def _response() -> PersonalDesignResponse:
    record = load_personal_design()
    if record is None:
        return PersonalDesignResponse(revision=None, document=None)
    return PersonalDesignResponse(revision=record.revision, document=record.document)


def design_studio_router(require_token) -> APIRouter:
    router = APIRouter(prefix="/api/design-studio", dependencies=[Depends(require_token)])

    @router.get("/personal", response_model=PersonalDesignResponse)
    def get_personal_design(request: Request) -> PersonalDesignResponse:
        del request
        try:
            return _response()
        except PersonalDesignValidationError as exc:
            raise ApiError(422, str(exc)) from exc

    @router.put("/personal", response_model=PersonalDesignResponse)
    def put_personal_design(
        request: Request, body: PersonalDesignSaveBody
    ) -> PersonalDesignResponse:
        del request
        try:
            record = save_personal_design(body.document, body.expected_revision)
        except PersonalDesignConflict as exc:
            raise ApiError(409, str(exc)) from exc
        except PersonalDesignValidationError as exc:
            raise ApiError(422, str(exc)) from exc
        return PersonalDesignResponse(revision=record.revision, document=record.document)

    @router.delete("/personal", response_model=PersonalDesignDeleteResponse)
    def remove_personal_design(
        request: Request, body: PersonalDesignDeleteBody
    ) -> PersonalDesignDeleteResponse:
        del request
        try:
            delete_personal_design(body.expected_revision)
        except PersonalDesignConflict as exc:
            raise ApiError(409, str(exc)) from exc
        except PersonalDesignValidationError as exc:
            raise ApiError(422, str(exc)) from exc
        return PersonalDesignDeleteResponse(ok=True)

    return router
