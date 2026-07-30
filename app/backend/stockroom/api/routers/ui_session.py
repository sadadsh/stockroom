"""Token-protected UI continuity and Add-a-Part draft endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from stockroom.api.errors import ApiError
from stockroom.store.ui_session import (
    MAX_DRAFT_BYTES,
    MAX_SESSION_BYTES,
    UiSessionConflict,
    create_draft,
    decode_json,
    delete_draft,
    load_draft,
    load_snapshot,
    save_snapshot,
    update_draft,
)


async def _bounded_json(request: Request, *, maximum: int, field: str) -> object:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > maximum:
                raise ApiError(413, "request body is too large")
        except ValueError:
            raise ApiError(400, "request body is invalid") from None

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise ApiError(413, "request body is too large")
    if not body:
        raise ApiError(400, "request body is invalid")
    return decode_json(bytes(body), maximum=maximum, field=field)


def ui_session_router(require_token) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @router.get("/ui-session")
    def get_ui_session(request: Request) -> dict:
        return load_snapshot(request.app.state.ctx.config)

    @router.put("/ui-session")
    async def put_ui_session(request: Request) -> dict:
        document = await _bounded_json(
            request,
            maximum=MAX_SESSION_BYTES,
            field="ui_session",
        )
        return save_snapshot(document, request.app.state.ctx.config)

    @router.post("/intake-drafts")
    async def post_intake_draft(request: Request) -> dict:
        document = await _bounded_json(
            request,
            maximum=MAX_DRAFT_BYTES,
            field="intake_draft",
        )
        return create_draft(document, request.app.state.ctx.config)

    @router.get("/intake-drafts/{draft_id}")
    def get_intake_draft(
        draft_id: str,
        request: Request,
        revision: int | None = Query(default=None, ge=1),
    ) -> dict:
        return load_draft(draft_id, revision, request.app.state.ctx.config)

    @router.put("/intake-drafts/{draft_id}")
    async def put_intake_draft(draft_id: str, request: Request) -> dict:
        document = await _bounded_json(
            request,
            maximum=MAX_DRAFT_BYTES,
            field="intake_draft",
        )
        try:
            return update_draft(
                draft_id,
                document,
                request.app.state.ctx.config,
            )
        except UiSessionConflict:
            raise ApiError(409, "intake draft revision is stale") from None

    @router.delete("/intake-drafts/{draft_id}")
    def remove_intake_draft(draft_id: str, request: Request) -> dict:
        delete_draft(draft_id, request.app.state.ctx.config)
        return {"deleted": True}

    return router
