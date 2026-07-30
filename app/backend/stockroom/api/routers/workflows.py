"""Authenticated, payload-free projections of Stockroom's durable workflows.

The workflow journal intentionally retains exact submitted identities, provider
results, worker owners, errors, and evidence references.  None of those raw
documents cross this API boundary.  The UI receives only bounded status
projections and an allowlisted monotonic event stream, so reconnecting from a
cursor cannot leak operational payloads or manufacture terminal evidence.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError

_SCHEMA_VERSION = 1
_MAX_EVENT_CURSOR = 9_007_199_254_740_991
_MAX_EVENT_PAGE = 500
_MAX_ITEM_ORDINAL = 999
_MAX_ITEM_PAGE = 250
_OPAQUE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)

_PUBLIC_EVENT_KINDS = frozenset(
    {
        "batch_cancel_requested",
        "batch_cancelled",
        "batch_paused",
        "batch_resumed",
        "batch_retry_requested",
        "batch_submitted",
        "decision_opened",
        "decision_resolved",
        "identity_resolved",
        "item_submitted",
        "publication_candidate_conflict",
        "publication_catalog_activated",
        "publication_cancel_after_fence",
        "publication_claimed",
        "publication_commit_fenced",
        "publication_completed",
        "publication_completed_before_cancel",
        "publication_git_committed",
        "publication_joined",
        "publication_replanned",
        "stage_claimed",
        "stage_completed",
        "stage_failed",
        "stage_lease_expired",
        "stage_lease_renewed",
        "stage_ready",
        "stage_retry_ready",
        "stage_retry_scheduled",
    }
)
_PUBLIC_EVENT_INTEGER_FIELDS = {
    "attempt": 1_000_000,
    "attempts_completed": 1_000_000,
    "failed_stage_count": 1_000,
    "item_count": 1_000,
    "ordinal": _MAX_ITEM_ORDINAL,
}
_PUBLIC_STAGE_NAMES = frozenset(
    {
        "identity_dedupe",
        "metadata",
        "datasheet",
        "existing_evidence",
        "cad_acquisition",
        "reconcile",
        "canonical_definition",
        "template_generation",
        "native_conversion_acquisition",
        "kicad_build_readback",
        "altium_build_readback",
        "cross_eda_verification",
        "catalog_link_generation",
        "publish",
    }
)


def _bounded_integer(value: int, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiError(400, f"{name} must be between {minimum} and {maximum}")
    return value


def _batch_id(value: str) -> str:
    if _OPAQUE_REFERENCE.fullmatch(value) is None:
        raise ApiError(400, "batch_id is not a valid opaque workflow identifier")
    return value


def _safe_reference(value: object) -> str | None:
    if type(value) is str and _OPAQUE_REFERENCE.fullmatch(value) is not None:
        return value
    return None


def _authority(request: Request):
    coordinator = request.app.state.ctx.workflow_coordinator
    if coordinator is None:
        raise ApiError(503, "The durable workflow coordinator is not mounted.")
    status = coordinator.status()
    state = getattr(status.state, "value", status.state)
    if state != "running" or not status.thread_alive:
        raise ApiError(503, "The durable workflow coordinator is not accepting requests.")
    return coordinator


def _actions(status: str, cancellation_state: str | None) -> dict[str, bool]:
    if cancellation_state == "requested":
        return {
            "can_pause": False,
            "can_resume": False,
            "can_retry": False,
            "can_cancel": False,
        }
    return {
        "can_pause": status in {"queued", "running", "blocked"},
        "can_resume": status == "paused",
        "can_retry": status == "failed",
        "can_cancel": status in {"queued", "running", "blocked", "paused", "failed"},
    }


def _workflow_kind(coordinator, batch_id: str) -> str:
    items = coordinator.list_items(batch_id)
    if items and all(
        isinstance(item.payload, dict) and item.payload.get("workflow_kind") == "guided_capture"
        for item in items
    ):
        return "guided_capture"
    return "completion"


def _summary(coordinator, batch_id: str) -> dict:
    batch = coordinator.get_batch(batch_id)
    counts = {
        status.value: count for status, count in coordinator.item_status_counts(batch_id).items()
    }
    cancellation = coordinator.get_batch_cancellation(batch_id)
    cancellation_state = None if cancellation is None else cancellation.state.value
    return {
        "id": batch.id,
        "kind": _workflow_kind(coordinator, batch_id),
        "status": batch.status.value,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "total_items": sum(counts.values()),
        "item_counts": counts,
        "cancellation": (
            None
            if cancellation is None
            else {
                "state": cancellation.state.value,
                "requested_at": cancellation.requested_at,
                "completed_at": cancellation.completed_at,
            }
        ),
        "actions": _actions(batch.status.value, cancellation_state),
    }


def _stage_projection(stage) -> dict:
    return {
        "id": stage.id,
        "name": stage.name.value,
        "status": stage.status.value,
        "attempt_count": stage.attempt_count,
        "next_attempt_at": stage.next_attempt_at,
    }


def _item_projection(coordinator, item) -> dict:
    return {
        "id": item.id,
        "ordinal": item.ordinal,
        "status": item.status.value,
        "stages": [_stage_projection(stage) for stage in coordinator.list_stages(item.id)],
    }


def _event_projection(event) -> dict:
    kind = event.kind if event.kind in _PUBLIC_EVENT_KINDS else "workflow_updated"
    details: dict[str, int | float | str] = {}
    payload = event.payload if isinstance(event.payload, dict) else {}
    for key, maximum in _PUBLIC_EVENT_INTEGER_FIELDS.items():
        value = payload.get(key)
        if type(value) is int and 0 <= value <= maximum:
            details[key] = value
    stage = payload.get("stage")
    if type(stage) is str and stage in _PUBLIC_STAGE_NAMES:
        details["stage"] = stage
    retry_at = payload.get("retry_at")
    if (
        not isinstance(retry_at, bool)
        and isinstance(retry_at, (int, float))
        and math.isfinite(float(retry_at))
        and retry_at >= 0
    ):
        details["retry_at"] = float(retry_at)
    return {
        "sequence": event.sequence,
        "item_id": _safe_reference(event.item_id),
        "stage_id": _safe_reference(event.stage_id),
        "kind": kind,
        "details": details,
        "created_at": event.created_at,
    }


def workflow_router(require_token: Callable) -> APIRouter:
    router = APIRouter(
        prefix="/api/workflows",
        dependencies=[Depends(require_token)],
    )

    @router.get("/batches/{batch_id}")
    def batch_snapshot(
        request: Request,
        batch_id: str,
        after_ordinal: int = -1,
        limit: int = 100,
    ) -> dict:
        identifier = _batch_id(batch_id)
        cursor = _bounded_integer(
            after_ordinal,
            "after_ordinal",
            -1,
            _MAX_ITEM_ORDINAL,
        )
        page_limit = _bounded_integer(limit, "limit", 1, _MAX_ITEM_PAGE)
        coordinator = _authority(request)
        # Sample the cursor BEFORE the projection. A concurrent transition may
        # therefore appear in both the snapshot and the next replay page, which
        # is harmless for a state projection. Sampling it afterwards could skip
        # an event that committed between the two reads.
        event_cursor = coordinator.latest_event_sequence(identifier)
        summary = _summary(coordinator, identifier)
        candidates = [item for item in coordinator.list_items(identifier) if item.ordinal > cursor]
        selected = candidates[:page_limit]
        has_more = len(candidates) > page_limit
        next_ordinal = selected[-1].ordinal if selected else cursor
        return {
            "schema_version": _SCHEMA_VERSION,
            "batch": summary,
            "event_cursor": event_cursor,
            "items": [_item_projection(coordinator, item) for item in selected],
            "page": {
                "after_ordinal": cursor,
                "next_ordinal": next_ordinal,
                "limit": page_limit,
                "has_more": has_more,
            },
        }

    @router.get("/batches/{batch_id}/events")
    def batch_events(
        request: Request,
        batch_id: str,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> dict:
        identifier = _batch_id(batch_id)
        cursor = _bounded_integer(
            after_sequence,
            "after_sequence",
            0,
            _MAX_EVENT_CURSOR,
        )
        page_limit = _bounded_integer(limit, "limit", 1, _MAX_EVENT_PAGE)
        coordinator = _authority(request)
        # Read the state projection BEFORE the journal page.  If a transition
        # commits between these reads, the page can be newer than the summary
        # and the client will poll once more.  Reading in the opposite order
        # could expose a newer terminal summary while omitting its event,
        # causing a cursor follower to stop before replaying terminal evidence.
        summary = _summary(coordinator, identifier)
        replay = coordinator.events(
            identifier,
            after_sequence=cursor,
            limit=page_limit + 1,
        )
        has_more = len(replay) > page_limit
        selected = replay[:page_limit]
        next_sequence = selected[-1].sequence if selected else cursor
        return {
            "schema_version": _SCHEMA_VERSION,
            "batch": summary,
            "events": [_event_projection(event) for event in selected],
            "cursor": {
                "after_sequence": cursor,
                "next_sequence": next_sequence,
                "limit": page_limit,
                "has_more": has_more,
            },
        }

    def apply_control(
        request: Request,
        batch_id: str,
        operation: str,
    ) -> dict:
        identifier = _batch_id(batch_id)
        coordinator = _authority(request)
        before = coordinator.get_batch(identifier)
        mutation = getattr(coordinator, f"{operation}_batch")
        result = mutation(identifier)
        return {
            "schema_version": _SCHEMA_VERSION,
            "operation": operation,
            "changed": (
                before.status is not result.status or before.updated_at != result.updated_at
            ),
            "batch": _summary(coordinator, identifier),
        }

    @router.post("/batches/{batch_id}/pause")
    def pause_batch(request: Request, batch_id: str) -> dict:
        return apply_control(request, batch_id, "pause")

    @router.post("/batches/{batch_id}/resume")
    def resume_batch(request: Request, batch_id: str) -> dict:
        return apply_control(request, batch_id, "resume")

    @router.post("/batches/{batch_id}/retry")
    def retry_batch(request: Request, batch_id: str) -> dict:
        return apply_control(request, batch_id, "retry")

    @router.post("/batches/{batch_id}/cancel")
    def cancel_batch(request: Request, batch_id: str) -> dict:
        return apply_control(request, batch_id, "cancel")

    return router


__all__ = ["workflow_router"]
