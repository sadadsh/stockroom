"""Synchronous typed dispatch over the durable :mod:`stockroom.workflow` store.

The runtime deliberately performs one claim per poll.  It owns no threads,
provider policy, artifact I/O, or publication side effects.  A publish handler
may only propose a candidate and join the component-global publication
operation; a separate publisher owns Git and catalog mutation.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, TypeAlias, TypedDict

from .model import (
    DecisionKind,
    ItemRecord,
    JsonScalar,
    JsonValue,
    StageRecord,
    StageStatus,
    WorkflowConflict,
)
from .planner import StageName, default_stage_plan
from .store import WorkflowStore

FrozenJson: TypeAlias = JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
PriorStageResults: TypeAlias = Mapping[StageName, FrozenJson]


def _never_stop() -> bool:
    return False


@dataclass(frozen=True, slots=True)
class StageContext:
    """Immutable inputs visible to one stage handler.

    ``prior_results`` contains only completed transitive dependencies of this
    stage.  Independent branches are excluded so handler output cannot depend
    on scheduler timing.
    """

    item: ItemRecord
    stage: StageRecord
    prior_results: PriorStageResults
    should_stop: Callable[[], bool] = field(
        default=_never_stop,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class ExactIdentityOutcome:
    authoritative_manufacturer_key: str
    mpn_canonical: str
    registry_revision: str
    rule_revision: str
    evidence: object


@dataclass(frozen=True, slots=True)
class CompletionOutcome:
    result: object


@dataclass(frozen=True, slots=True)
class RetryOutcome:
    error: object
    retry_at: float


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    kind: DecisionKind
    prompt: object


@dataclass(frozen=True, slots=True)
class PermanentFailureOutcome:
    error: object


@dataclass(frozen=True, slots=True)
class PublicationProposalOutcome:
    candidate_digest: str
    manifest_digest: str
    expected_base_commit: str
    expected_head_publication_id: str | None = None


StageOutcome: TypeAlias = (
    ExactIdentityOutcome
    | CompletionOutcome
    | RetryOutcome
    | DecisionOutcome
    | PermanentFailureOutcome
    | PublicationProposalOutcome
)


class StageHandler(Protocol):
    def __call__(self, context: StageContext, /) -> StageOutcome: ...


@dataclass(frozen=True, slots=True)
class DispatchRecord:
    item_id: str
    stage_id: str
    stage_name: StageName
    outcome: StageOutcome


class StageHandlerError(RuntimeError):
    """A handler raised after its running stage was durably failed."""


class InvalidStageOutcome(RuntimeError):
    """A handler returned an unknown or stage-incompatible outcome."""


class StageLeaseLost(WorkflowConflict):
    """This worker's lease was lost while its handler was still running.

    Cooperative handlers can stop through :attr:`StageContext.should_stop`.
    A handler that cannot stop is allowed to finish, but its terminal
    transition is skipped because its fence is no longer authoritative.
    """


class _LeaseKwargs(TypedDict):
    lease_token: str
    lease_generation: int


@dataclass(slots=True)
class _Heartbeat:
    """Mutable liveness report shared with one lease-renewal thread."""

    lost: BaseException | None = None


_MAX_CONSECUTIVE_HEARTBEAT_FAILURES = 2
_HEARTBEAT_JOIN_SECONDS = 5.0


_PLAN = default_stage_plan()
_DIRECT_DEPENDENCIES = {spec.name: spec.dependencies for spec in _PLAN}


def _dependency_ancestors(name: StageName) -> frozenset[StageName]:
    found: set[StageName] = set()
    remaining = list(_DIRECT_DEPENDENCIES[name])
    while remaining:
        dependency = remaining.pop()
        if dependency in found:
            continue
        found.add(dependency)
        remaining.extend(_DIRECT_DEPENDENCIES[dependency])
    return frozenset(found)


_ANCESTORS = {name: _dependency_ancestors(name) for name in StageName}


def _freeze_json(value: JsonValue) -> FrozenJson:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


class WorkflowRuntime:
    """Claim and synchronously dispatch one dependency-ready stage per poll."""

    def __init__(
        self,
        store: WorkflowStore,
        handlers: Mapping[StageName, StageHandler],
        *,
        heartbeat_seconds: float | None = None,
    ):
        if not isinstance(store, WorkflowStore):
            raise TypeError("store must be a WorkflowStore")
        registered: dict[StageName, StageHandler] = {}
        for raw_name, handler in handlers.items():
            name = StageName(raw_name)
            if not callable(handler):
                raise TypeError(f"handler for {name.value} must be callable")
            registered[name] = handler
        if heartbeat_seconds is not None:
            if type(heartbeat_seconds) not in {int, float}:
                raise TypeError("heartbeat_seconds must be a number")
            heartbeat_seconds = float(heartbeat_seconds)
            if not math.isfinite(heartbeat_seconds) or heartbeat_seconds <= 0:
                raise ValueError("heartbeat_seconds must be positive and finite")
        self._store = store
        self._handlers = MappingProxyType(registered)
        self._heartbeat_seconds = heartbeat_seconds

    @property
    def handlers(self) -> Mapping[StageName, StageHandler]:
        return self._handlers

    def poll_once(
        self,
        worker_id: str,
        *,
        now: float | None = None,
        lease_seconds: float = 60.0,
    ) -> DispatchRecord | None:
        """Claim and dispatch at most one stage, returning ``None`` when idle."""

        claimed = self._store.claim_ready(
            worker_id,
            now=now,
            lease_seconds=lease_seconds,
            limit=1,
        )
        if not claimed:
            return None
        return self.dispatch_claim(
            claimed[0],
            worker_id,
            now=now,
            lease_seconds=lease_seconds,
        )

    def dispatch_claim(
        self,
        claim: StageRecord,
        worker_id: str,
        *,
        now: float | None = None,
        lease_seconds: float = 60.0,
    ) -> DispatchRecord:
        """Dispatch a claim returned by :meth:`WorkflowStore.claim_ready`.

        Exact successful replays retain the store's idempotent behavior.  A
        superseded lease is rejected before its handler is called.  When this
        runtime was built with a heartbeat, the lease is renewed for as long as
        the handler runs so a legitimately slow stage is never recovered and
        re-dispatched underneath itself.
        """

        current = self._require_current_claim(claim, worker_id, now)
        context = self._context_for(claim)
        handler = self._handlers.get(claim.name)
        beat = _Heartbeat()
        if handler is None:
            outcome = PermanentFailureOutcome(
                {
                    "kind": "missing_stage_handler",
                    "stage": claim.name.value,
                }
            )
        else:
            try:
                with self._heartbeat(claim, worker_id, lease_seconds) as beat:
                    outcome = handler(context)
            except Exception as exc:
                # A lost lease makes every fenced transition fail, so failing
                # the stage here would only raise a second, confusing conflict
                # over the handler's real error.
                if beat.lost is None and current.status is StageStatus.RUNNING:
                    self._store.fail_stage(
                        claim.id,
                        worker_id,
                        {
                            "exception_type": type(exc).__name__,
                            "kind": "stage_handler_exception",
                            "message": str(exc),
                            "stage": claim.name.value,
                        },
                        **self._lease(claim),
                        now=now,
                    )
                raise StageHandlerError(f"handler for {claim.name.value} raised") from exc

        if beat.lost is not None:
            raise StageLeaseLost(
                f"{claim.name.value} lost its lease while its handler was running"
            ) from beat.lost

        if not isinstance(
            outcome,
            (
                ExactIdentityOutcome,
                CompletionOutcome,
                RetryOutcome,
                DecisionOutcome,
                PermanentFailureOutcome,
                PublicationProposalOutcome,
            ),
        ):
            self._reject_invalid_outcome(
                claim,
                worker_id,
                current,
                outcome,
                now=now,
            )

        if not self._outcome_allowed(claim.name, outcome):
            self._reject_invalid_outcome(
                claim,
                worker_id,
                current,
                outcome,
                now=now,
            )

        self._apply_outcome(claim, worker_id, outcome, now=now)
        return DispatchRecord(
            item_id=claim.item_id,
            stage_id=claim.id,
            stage_name=claim.name,
            outcome=outcome,
        )

    @contextmanager
    def _heartbeat(
        self,
        claim: StageRecord,
        worker_id: str,
        lease_seconds: float,
    ) -> Iterator[_Heartbeat]:
        """Renew this claim's lease until the handler returns.

        Renewals run on their own thread against their own sqlite connection,
        never inside another store transaction, and never rotate the fence, so
        the caller's original claim stays valid for its terminal transition.
        """

        beat = _Heartbeat()
        token = claim.lease_token
        if self._heartbeat_seconds is None or token is None:
            yield beat
            return

        interval = self._heartbeat_seconds
        stop = threading.Event()

        def renew() -> None:
            failures = 0
            while not stop.wait(interval):
                try:
                    self._store.renew_lease(
                        claim.id,
                        worker_id,
                        lease_token=token,
                        lease_generation=claim.lease_generation,
                        lease_seconds=lease_seconds,
                        emit_event=False,
                    )
                except WorkflowConflict as exc:
                    beat.lost = exc
                    return
                except BaseException as exc:
                    # A heartbeat that dies quietly reintroduces the very
                    # recovery race it exists to prevent, so a persistently
                    # failing renewal is reported as a lost lease.
                    failures += 1
                    if failures > _MAX_CONSECUTIVE_HEARTBEAT_FAILURES:
                        beat.lost = exc
                        return
                    continue
                failures = 0

        thread = threading.Thread(
            target=renew,
            name="stockroom-workflow-lease-heartbeat",
            daemon=True,
        )
        thread.start()
        try:
            yield beat
        finally:
            stop.set()
            thread.join(_HEARTBEAT_JOIN_SECONDS)

    def _context_for(self, claim: StageRecord) -> StageContext:
        ancestors = _ANCESTORS[claim.name]
        item, persisted_results = self._store.get_item_with_completed_results(
            claim.item_id,
            tuple(sorted(ancestors, key=lambda name: name.value)),
        )
        results = {
            name: _freeze_json(result)
            for name, result in persisted_results.items()
        }
        if set(results) != set(ancestors):
            raise WorkflowConflict(f"{claim.name.value} was claimed without all dependency results")
        return StageContext(
            item=item,
            stage=claim,
            prior_results=MappingProxyType(results),
            should_stop=lambda: self._store.get_batch_cancellation(item.batch_id) is not None,
        )

    def _require_current_claim(
        self,
        claim: StageRecord,
        worker_id: str,
        now: float | None,
    ) -> StageRecord:
        current = self._store.get_stage(claim.id)
        if (
            current.lease_token != claim.lease_token
            or current.lease_generation != claim.lease_generation
        ):
            raise WorkflowConflict("stage lease fence is stale")

        if current.status is StageStatus.RUNNING:
            if current.lease_owner != worker_id:
                raise WorkflowConflict("stage is leased by another worker")
            timestamp = time.time() if now is None else float(now)
            if not math.isfinite(timestamp):
                raise ValueError("now must be finite")
            if current.lease_expires_at is None or current.lease_expires_at <= timestamp:
                raise WorkflowConflict("stage lease has expired")
            return current

        replayable = current.status is StageStatus.COMPLETED or (
            claim.name is StageName.PUBLISH and current.status is StageStatus.BLOCKED
        )
        if not replayable:
            raise WorkflowConflict(f"stage is {current.status.value}, not running")
        return current

    @staticmethod
    def _lease(claim: StageRecord) -> _LeaseKwargs:
        if claim.lease_token is None or claim.lease_generation <= 0:
            raise WorkflowConflict("stage lease fence is stale")
        return {
            "lease_token": claim.lease_token,
            "lease_generation": claim.lease_generation,
        }

    @staticmethod
    def _outcome_allowed(name: StageName, outcome: StageOutcome) -> bool:
        if isinstance(outcome, ExactIdentityOutcome):
            return name is StageName.IDENTITY_DEDUPE
        if isinstance(outcome, CompletionOutcome):
            return name not in {
                StageName.IDENTITY_DEDUPE,
                StageName.PUBLISH,
            }
        if isinstance(outcome, PublicationProposalOutcome):
            return name is StageName.PUBLISH
        return True

    def _reject_invalid_outcome(
        self,
        claim: StageRecord,
        worker_id: str,
        current: StageRecord,
        outcome: object,
        *,
        now: float | None,
    ) -> None:
        outcome_name = type(outcome).__name__
        if current.status is StageStatus.RUNNING:
            self._store.fail_stage(
                claim.id,
                worker_id,
                {
                    "kind": "invalid_stage_outcome",
                    "outcome": outcome_name,
                    "stage": claim.name.value,
                },
                **self._lease(claim),
                now=now,
            )
        raise InvalidStageOutcome(f"{outcome_name} is not valid for {claim.name.value}")

    def _apply_outcome(
        self,
        claim: StageRecord,
        worker_id: str,
        outcome: StageOutcome,
        *,
        now: float | None,
    ) -> None:
        lease = self._lease(claim)
        if isinstance(outcome, ExactIdentityOutcome):
            self._store.resolve_exact_identity(
                claim.id,
                worker_id,
                authoritative_manufacturer_key=outcome.authoritative_manufacturer_key,
                mpn_canonical=outcome.mpn_canonical,
                registry_revision=outcome.registry_revision,
                rule_revision=outcome.rule_revision,
                evidence=outcome.evidence,
                **lease,
                now=now,
            )
        elif isinstance(outcome, CompletionOutcome):
            self._store.complete_stage(
                claim.id,
                worker_id,
                outcome.result,
                **lease,
                now=now,
            )
        elif isinstance(outcome, RetryOutcome):
            self._store.retry_stage(
                claim.id,
                worker_id,
                outcome.error,
                retry_at=outcome.retry_at,
                **lease,
                now=now,
            )
        elif isinstance(outcome, DecisionOutcome):
            self._store.block_for_decision(
                claim.id,
                worker_id,
                outcome.kind,
                outcome.prompt,
                **lease,
                now=now,
            )
        elif isinstance(outcome, PermanentFailureOutcome):
            self._store.fail_stage(
                claim.id,
                worker_id,
                outcome.error,
                **lease,
                now=now,
            )
        else:
            self._store.join_publication(
                claim.id,
                worker_id,
                candidate_digest=outcome.candidate_digest,
                manifest_digest=outcome.manifest_digest,
                expected_base_commit=outcome.expected_base_commit,
                expected_head_publication_id=outcome.expected_head_publication_id,
                **lease,
                now=now,
            )


StageHandlerRegistry: TypeAlias = Mapping[StageName, StageHandler]
