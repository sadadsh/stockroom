"""Authenticated, machine-scoped Design Studio persistence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from stockroom.api.errors import ApiError
from stockroom.design_studio.personal import (
    PersonalDesignConflict,
    PersonalDesignValidationError,
    apply_local_design,
    delete_applied_design,
    delete_personal_design,
    load_applied_design,
    load_personal_design,
    save_personal_design,
    save_personal_design_for_page_exit,
)


class PersonalDesignSaveBody(BaseModel):
    """The complete document and the revision it was edited from."""

    model_config = ConfigDict(extra="forbid", strict=True)

    document: dict[str, object]
    expected_revision: str | None


class PersonalDesignPageExitBody(PersonalDesignSaveBody):
    """Newest closing draft plus the one ordinary save it may supersede."""

    superseded_document: dict[str, object] | None = None


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


class AppliedDesignBody(BaseModel):
    """The complete personal document explicitly activated on this machine."""

    model_config = ConfigDict(extra="forbid", strict=True)

    document: dict[str, object]


def _response() -> PersonalDesignResponse:
    record = load_personal_design()
    if record is None:
        return PersonalDesignResponse(revision=None, document=None)
    return PersonalDesignResponse(revision=record.revision, document=record.document)


def _applied_response() -> PersonalDesignResponse:
    record = load_applied_design()
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

    @router.put("/personal/page-exit", response_model=PersonalDesignResponse)
    def put_personal_design_for_page_exit(
        request: Request, body: PersonalDesignPageExitBody
    ) -> PersonalDesignResponse:
        del request
        try:
            record = save_personal_design_for_page_exit(
                body.document,
                body.expected_revision,
                body.superseded_document,
            )
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

    @router.get("/applied-local", response_model=PersonalDesignResponse)
    def get_applied_design(request: Request) -> PersonalDesignResponse:
        del request
        try:
            return _applied_response()
        except PersonalDesignValidationError as exc:
            raise ApiError(422, str(exc)) from exc

    @router.post("/apply-local", response_model=PersonalDesignResponse)
    def apply_design_locally(
        request: Request, body: AppliedDesignBody
    ) -> PersonalDesignResponse:
        del request
        try:
            record = apply_local_design(body.document)
        except PersonalDesignValidationError as exc:
            raise ApiError(422, str(exc)) from exc
        return PersonalDesignResponse(revision=record.revision, document=record.document)

    @router.delete("/apply-local", response_model=PersonalDesignDeleteResponse)
    def reset_applied_design(request: Request) -> PersonalDesignDeleteResponse:
        del request
        try:
            delete_applied_design()
        except PersonalDesignValidationError as exc:
            raise ApiError(422, str(exc)) from exc
        return PersonalDesignDeleteResponse(ok=True)

    return router
