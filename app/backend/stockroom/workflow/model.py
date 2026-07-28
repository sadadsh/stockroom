"""Typed, JSON-only records for Stockroom's durable workflow.

The workflow database is an operational journal, not the component library.  It
keeps the user's submitted identity text byte-for-byte while deriving conservative
lookup keys that apply canonical NFC composition and surrounding-whitespace
trimming only.  Case folding and compatibility folding are forbidden: ``acme`` is
not ``ACME``, ``™`` is not ``TM``, fullwidth/circled glyphs are not their ASCII
lookalikes, and punctuation remains significant.  Those transformations can
silently merge distinct manufacturer part numbers.

Batch, item, stage, and decision identifiers are opaque UUID4 values.  Resolved
manufacturer, component, and publication identifiers are deterministic full-digest
values so independently submitted exact identities can converge without treating
mutable or sensitive component data as an identifier.  No Python-specific
serialization format is accepted.
"""

from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, TypeAlias
from uuid import uuid4

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class WorkflowConflict(RuntimeError):
    """The requested transition conflicts with durable workflow state."""


class WorkflowDataCorruption(RuntimeError):
    """Persisted workflow data is not valid inert JSON and was quarantined."""


class BatchStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_RETRY = "waiting_retry"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DecisionKind(StrEnum):
    IDENTITY = "identity"
    SAFETY = "safety"


class DecisionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class PublicationState(StrEnum):
    PREPARING = "preparing"
    CONFLICTED = "conflicted"
    COMMIT_FENCED = "commit_fenced"
    GIT_COMMITTED = "git_committed"
    CATALOG_ACTIVATED = "catalog_activated"
    COMPLETED = "completed"
    ABORTED = "aborted"


class PublicationMembershipState(StrEnum):
    WAITING = "waiting"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    CONFLICT = "conflict"


class PublicationCompletionDisposition(StrEnum):
    NORMAL = "normal"
    COMPLETED_BEFORE_CANCEL = "completed_before_cancel"


class BatchCancellationState(StrEnum):
    REQUESTED = "requested"
    COMPLETED = "completed"


def new_opaque_id() -> str:
    """Return an identity-independent UUID4 string."""

    return str(uuid4())


def identity_key(value: str) -> str:
    """Apply NFC and trim only; preserve case, compatibility, and punctuation."""

    if not isinstance(value, str):
        raise TypeError("identity fields must be strings")
    return unicodedata.normalize("NFC", value).strip()


def _validate_json_shape(
    value: object,
    *,
    active_containers: set[int] | None = None,
) -> None:
    """Reject values that Python can serialize but JSON cannot represent exactly."""

    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("workflow payloads must contain finite JSON numbers")
        return

    active = set() if active_containers is None else active_containers
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise TypeError("workflow payloads must not contain cyclic JSON arrays")
        active.add(identity)
        try:
            for item in value:
                _validate_json_shape(item, active_containers=active)
        finally:
            active.remove(identity)
        return

    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("workflow JSON object keys must be strings")
        identity = id(value)
        if identity in active:
            raise TypeError("workflow payloads must not contain cyclic JSON objects")
        active.add(identity)
        try:
            for item in value.values():
                _validate_json_shape(item, active_containers=active)
        finally:
            active.remove(identity)
        return

    raise TypeError(
        f"workflow payloads must use JSON arrays and objects, not {type(value).__name__}"
    )


def canonical_json(value: object) -> str:
    """Encode a value as deterministic standards-compliant JSON.

    ``allow_nan=False`` prevents non-standard float tokens from entering the
    durable journal.  The normalized error type gives callers one clear contract
    for sets, bytes, custom classes, NaN, and every other non-JSON value.
    """

    try:
        _validate_json_shape(value)
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise TypeError("workflow payloads must contain JSON values only") from exc


def decode_json(value: str | bytes | None) -> JsonValue | None:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
        _validate_json_shape(decoded)
        return decoded
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeDecodeError) as exc:
        raise WorkflowDataCorruption(
            "invalid JSON was quarantined in the workflow database"
        ) from exc


@dataclass(frozen=True, slots=True)
class IntakeIdentity:
    """One exact input identity submitted through the batch API.

    Manufacturer may be blank because resolving it is the identity gate's job.
    MPN must be non-blank when the batch is accepted by the store.
    """

    manufacturer: str
    mpn: str
    payload: Mapping[str, object] = field(default_factory=dict)

    @property
    def manufacturer_key(self) -> str:
        return identity_key(self.manufacturer)

    @property
    def mpn_key(self) -> str:
        return identity_key(self.mpn)


@dataclass(frozen=True, slots=True)
class BatchRecord:
    id: str
    status: BatchStatus
    created_at: float
    updated_at: float
    idempotency_key: str | None = None
    request_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ItemRecord:
    id: str
    entry_id: str
    batch_id: str
    ordinal: int
    workflow_graph_version: int
    manufacturer: str
    mpn: str
    manufacturer_key: str
    mpn_key: str
    payload: JsonValue
    status: ItemStatus
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class StageRecord:
    id: str
    item_id: str
    batch_id: str
    entry_id: str
    ordinal: int
    name: "StageName"
    status: StageStatus
    attempt_count: int
    next_attempt_at: float | None
    lease_owner: str | None
    lease_expires_at: float | None
    lease_token: str | None
    lease_generation: int
    result: JsonValue | None
    error: JsonValue | None
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    sequence: int
    batch_id: str
    item_id: str | None
    stage_id: str | None
    kind: str
    payload: JsonValue
    created_at: float


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    id: str
    item_id: str
    stage_id: str
    kind: DecisionKind
    status: DecisionStatus
    prompt: JsonValue
    resolution: JsonValue | None
    created_at: float
    resolved_at: float | None


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    id: str
    item_id: str
    stage_id: str
    entry_id: str
    payload: JsonValue
    created_at: float


@dataclass(frozen=True, slots=True)
class ResolvedComponent:
    component_id: str
    identity_digest: str
    manufacturer_id: str
    manufacturer_digest: str
    authoritative_manufacturer_key: str
    mpn_canonical: str
    created_at: float


@dataclass(frozen=True, slots=True)
class ItemComponentBinding:
    item_id: str
    identity_stage_id: str
    component_id: str
    resolution: JsonValue
    resolved_at: float


@dataclass(frozen=True, slots=True)
class PublicationOperation:
    publication_id: str
    component_id: str
    candidate_digest: str
    manifest_digest: str
    expected_head_publication_id: str | None
    expected_base_commit: str
    state: PublicationState
    lease_generation: int
    lease_owner: str | None
    lease_expires_at: float | None
    commit_fenced_at: float | None
    git_commit_oid: str | None
    verified_tree_digest: str | None
    catalog_revision: str | None
    catalog_semantic_digest: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class PublicationLease:
    publication_id: str
    component_id: str
    state: PublicationState
    worker_id: str
    lease_token: str
    lease_generation: int
    lease_expires_at: float


@dataclass(frozen=True, slots=True)
class PublicationMembership:
    item_id: str
    publish_stage_id: str
    publication_id: str
    state: PublicationMembershipState
    cancel_after_fence: bool
    completion_disposition: PublicationCompletionDisposition | None
    joined_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class ComponentPublicationReceipt:
    publication_id: str
    component_id: str
    git_commit_oid: str
    verified_tree_digest: str
    catalog_revision: str
    catalog_semantic_digest: str
    payload: JsonValue
    created_at: float


@dataclass(frozen=True, slots=True)
class BatchCancellationRecord:
    batch_id: str
    state: BatchCancellationState
    reason: JsonValue
    requested_at: float
    completed_at: float | None


# Kept at the bottom to avoid a planner -> model -> planner runtime cycle while
# retaining a precise StageRecord annotation.
from .planner import StageName  # noqa: E402
