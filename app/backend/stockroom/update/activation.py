"""Generation-fenced activation of immutable TUF-verified release sets.

The real service/host handoff is an injected boundary.  This module sequences
and fences it, but never claims that a process, WebView, or request route was
switched unless the injected adoption port returns successfully.
"""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from stockroom.service import (
    CoordinatorConflict,
    CoordinatorStatus,
    GenerationFence,
    ServiceControl,
    ServiceMode,
)
from stockroom.service.control import JsonValue

from .immutable_store import (
    AcceptedRelease,
    ActiveReleaseState,
    ImmutableReleaseStore,
    ImmutableReleaseStoreError,
    ReleaseStoreAuthorityError,
)
from .trusted_repository import VerifiedReleaseSet

_STATUS_EVENT = "release_activation_status"
_STATUS_SCHEMA_VERSION = 1
_EVENT_PAGE_SIZE = 1_000
_RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_ACTIVE_ACTIVATIONS_LOCK = threading.Lock()
_ACTIVE_ACTIVATIONS: set[tuple[str, int, str]] = set()
_BLOCKING_REASONS = frozenset(
    {
        "adoption_failed",
        "adoption_commit_failed",
        "candidate_verification_failed",
        "current_release_verification_failed",
        "drain_failed",
        "launch_failed",
        "pointer_commit_failed",
        "post_adoption_health_failed",
        "pre_adoption_health_failed",
        "rehearsal_failed",
        "rollback_failed",
        "rollback_target_incompatible",
        "rollback_target_unauthorized",
        "rollback_target_unavailable",
        "rollback_target_verification_failed",
        "stale_generation",
    }
)


class ReleaseActivationRole(str, Enum):
    """Explicit activation authority role."""

    SHADOW = "shadow"
    COORDINATOR = "coordinator"


class ReleaseActivationPhase(str, Enum):
    """Durable high-level activation phases."""

    IDLE = "idle"
    VERIFYING = "verifying"
    REHEARSING = "rehearsing"
    LAUNCHING = "launching"
    PRE_ADOPTION_HEALTH = "pre_adoption_health"
    DRAINING = "draining"
    ADOPTING = "adopting"
    POST_ADOPTION_HEALTH = "post_adoption_health"
    COMMITTING = "committing"
    FINALIZING = "finalizing"
    ACTIVE = "active"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    STALE = "stale"


class ReleaseHealthStage(str, Enum):
    """Health boundary exercised against the candidate."""

    PRE_ADOPTION = "pre_adoption"
    POST_ADOPTION = "post_adoption"


class ReleaseActivationError(RuntimeError):
    """Base class for safe activation failures."""


class ReleaseActivationRoleError(ReleaseActivationError):
    """A shadow attempted to gain activation authority."""


class ReleaseActivationBusy(ReleaseActivationError):
    """The coordinator generation already has an activation in progress."""


class ReleaseActivationFailed(ReleaseActivationError):
    """Activation failed safely, with the prior release still selected."""

    def __init__(self, reason: str, *, rolled_back: bool) -> None:
        super().__init__(f"release activation failed: {reason}")
        self.reason = reason
        self.rolled_back = rolled_back


class ReleaseRollbackFailed(ReleaseActivationError):
    """The injected recovery seam could not prove rollback completion."""


@dataclass(frozen=True, slots=True)
class ReleaseActivationStatus:
    """Credential-free activation status for coordinator or shadow inspection."""

    role: ReleaseActivationRole
    phase: ReleaseActivationPhase
    generation: int
    candidate_release_id: str | None
    current_release_id: str | None
    blocking_reason: str | None
    phase_started_at: float | None


@dataclass(frozen=True, slots=True)
class _PersistedStatus:
    phase: ReleaseActivationPhase
    generation: int | None
    candidate_release_id: str | None
    current_release_id: str | None
    blocking_reason: str | None
    phase_started_at: float | None


class ReleaseRehearsalPort(Protocol):
    """Rehearse schemas, workflows, adapters, and migrations without adoption."""

    def rehearse(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> None: ...

    def rehearse_rollback(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> None: ...


class ReleaseLaunchPort(Protocol):
    """Launch and clean up a non-coordinator candidate service."""

    def launch_shadow(
        self,
        candidate: AcceptedRelease,
        *,
        generation: int,
    ) -> object: ...

    def stop_shadow(
        self,
        launch_handle: object,
        *,
        generation: int,
    ) -> None: ...


class ReleaseHealthPort(Protocol):
    """Exercise candidate health before and after live route adoption."""

    def check(
        self,
        candidate: AcceptedRelease,
        launch_handle: object,
        *,
        stage: ReleaseHealthStage,
        generation: int,
    ) -> None: ...


class ReleaseDrainPort(Protocol):
    """Reach and recover a cancellable safe checkpoint in the current service."""

    def drain(
        self,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> object: ...

    def resume(
        self,
        current: AcceptedRelease,
        drain_receipt: object,
        *,
        generation: int,
    ) -> None: ...


class ReleaseAdoptionPort(Protocol):
    """The absent host/service boundary for one atomic live route switch.

    ``adopt`` must return only after the existing window and request injection
    route use ``candidate``.  If it raises, it must guarantee that no adoption
    occurred.  ``rollback`` must atomically reconnect that same route to
    ``current`` before returning.  These are production obligations of the
    future host adapter, not behavior simulated by this foundation.
    """

    def adopt(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        launch_handle: object,
        drain_receipt: object,
        *,
        generation: int,
    ) -> object: ...

    def rollback(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        adoption_receipt: object,
        *,
        generation: int,
    ) -> None: ...

    def commit(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        adoption_receipt: object,
        *,
        generation: int,
    ) -> None:
        """Finalize irreversible host retirement after the release pointer commits."""
        ...


class _StageFailure(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReleaseActivator:
    """Sequence one immutable release activation under a durable fence."""

    def __init__(
        self,
        control: ServiceControl,
        store: ImmutableReleaseStore,
        *,
        role: ReleaseActivationRole,
        fence: GenerationFence | None = None,
        rehearsal: ReleaseRehearsalPort | None = None,
        launcher: ReleaseLaunchPort | None = None,
        health: ReleaseHealthPort | None = None,
        drain: ReleaseDrainPort | None = None,
        adoption: ReleaseAdoptionPort | None = None,
    ) -> None:
        if not isinstance(control, ServiceControl):
            raise TypeError("control must be a ServiceControl")
        if not isinstance(store, ImmutableReleaseStore):
            raise TypeError("store must be an ImmutableReleaseStore")
        if type(role) is not ReleaseActivationRole:
            raise TypeError("role must be a ReleaseActivationRole")
        expected_mode = (
            ServiceMode.COORDINATOR
            if role is ReleaseActivationRole.COORDINATOR
            else ServiceMode.SHADOW
        )
        if control.mode is not expected_mode:
            raise ReleaseActivationRoleError(
                "activation role must match ServiceControl mode"
            )
        if role is ReleaseActivationRole.SHADOW:
            if any(
                value is not None
                for value in (fence, rehearsal, launcher, health, drain, adoption)
            ):
                raise ReleaseActivationRoleError(
                    "shadow activator cannot receive mutation or handoff authority"
                )
        else:
            if type(fence) is not GenerationFence:
                raise TypeError("coordinator activator requires a GenerationFence")
            for name, value in (
                ("rehearsal", rehearsal),
                ("launcher", launcher),
                ("health", health),
                ("drain", drain),
                ("adoption", adoption),
            ):
                if value is None:
                    raise TypeError(
                        f"coordinator activator requires the injected {name} seam"
                    )

        self._control = control
        self._store = store
        self._role = role
        self._fence = fence
        self._rehearsal = rehearsal
        self._launcher = launcher
        self._health = health
        self._drain = drain
        self._adoption = adoption
        self._lock = threading.Lock()
        persisted = _read_persisted_status(control)
        self._phase = persisted.phase
        self._candidate_release_id = persisted.candidate_release_id
        self._current_release_id = persisted.current_release_id
        self._blocking_reason = persisted.blocking_reason
        self._phase_started_at = persisted.phase_started_at
        if role is ReleaseActivationRole.COORDINATOR:
            self._require_active_fence()

    def verify_startup(self) -> ActiveReleaseState:
        """Re-hash current and previous accepted bytes without mutating state."""

        return self._store.verify_startup(self._control)

    def status(self) -> ReleaseActivationStatus:
        """Return local coordinator status or a fresh durable shadow projection."""

        control_snapshot = self._control.snapshot()
        if self._role is ReleaseActivationRole.SHADOW:
            persisted = _read_persisted_status(self._control)
            phase = persisted.phase
            blocking_reason = persisted.blocking_reason
            if (
                persisted.generation is not None
                and persisted.generation < control_snapshot.generation
                and phase
                not in {
                    ReleaseActivationPhase.ACTIVE,
                    ReleaseActivationPhase.FAILED,
                    ReleaseActivationPhase.ROLLED_BACK,
                }
            ):
                phase = ReleaseActivationPhase.STALE
                blocking_reason = "stale_generation"
            return ReleaseActivationStatus(
                role=self._role,
                phase=phase,
                generation=control_snapshot.generation,
                candidate_release_id=persisted.candidate_release_id,
                current_release_id=persisted.current_release_id,
                blocking_reason=blocking_reason,
                phase_started_at=persisted.phase_started_at,
            )
        with self._lock:
            return ReleaseActivationStatus(
                role=self._role,
                phase=self._phase,
                generation=self._generation(),
                candidate_release_id=self._candidate_release_id,
                current_release_id=self._current_release_id,
                blocking_reason=self._blocking_reason,
                phase_started_at=self._phase_started_at,
            )

    def activate(self, candidate: VerifiedReleaseSet) -> ActiveReleaseState:
        """Activate one candidate or prove the prior healthy set was restored."""

        if self._role is not ReleaseActivationRole.COORDINATOR:
            raise ReleaseActivationRoleError("shadow activator cannot activate releases")
        if not isinstance(candidate, VerifiedReleaseSet):
            raise TypeError("candidate must be a VerifiedReleaseSet")
        if (
            _optional_release_id(candidate.release_id) != candidate.release_id
            or candidate.manifest.release_id != candidate.release_id
        ):
            raise ReleaseActivationError("candidate release identity is invalid")
        registration_key = self._registration_key()
        with _ACTIVE_ACTIVATIONS_LOCK:
            if registration_key in _ACTIVE_ACTIVATIONS:
                raise ReleaseActivationBusy(
                    "coordinator generation already has an activation in progress"
                )
            _ACTIVE_ACTIVATIONS.add(registration_key)
        try:
            return self._activate(candidate)
        finally:
            with _ACTIVE_ACTIVATIONS_LOCK:
                _ACTIVE_ACTIVATIONS.discard(registration_key)

    def rollback_to_previous(self) -> ActiveReleaseState:
        """Commit the signed rollback target as a fresh active release."""

        if self._role is not ReleaseActivationRole.COORDINATOR:
            raise ReleaseActivationRoleError(
                "shadow activator cannot roll back releases"
            )
        registration_key = self._registration_key()
        with _ACTIVE_ACTIVATIONS_LOCK:
            if registration_key in _ACTIVE_ACTIVATIONS:
                raise ReleaseActivationBusy(
                    "coordinator generation already has an activation in progress"
                )
            _ACTIVE_ACTIVATIONS.add(registration_key)
        try:
            return self._activate_previous()
        finally:
            with _ACTIVE_ACTIVATIONS_LOCK:
                _ACTIVE_ACTIVATIONS.discard(registration_key)

    def _activate(self, candidate: VerifiedReleaseSet) -> ActiveReleaseState:
        try:
            self._transition(
                ReleaseActivationPhase.VERIFYING,
                candidate_release_id=candidate.release_id,
                current_release_id=None,
                blocking_reason=None,
            )
            try:
                original = self._store.verify_startup(self._control)
            except ImmutableReleaseStoreError as exc:
                raise _StageFailure("current_release_verification_failed") from exc
            self._require_active_fence()
            with self._lock:
                self._current_release_id = original.current.release_id
            try:
                accepted_candidate = self._store.accept_verified(
                    candidate,
                    control=self._control,
                    fence=self._required_fence(),
                )
            except ReleaseStoreAuthorityError:
                raise
            except ImmutableReleaseStoreError as exc:
                raise _StageFailure("candidate_verification_failed") from exc

            if (
                accepted_candidate.release_id == original.current.release_id
                and accepted_candidate.manifest_sha256
                == original.current.manifest_sha256
            ):
                self._transition(
                    ReleaseActivationPhase.ACTIVE,
                    candidate_release_id=accepted_candidate.release_id,
                    current_release_id=original.current.release_id,
                    blocking_reason=None,
                )
                return original
            if not accepted_candidate.manifest.supports_direct_activation_from(
                original.current.release_id
            ):
                raise _StageFailure("rollback_target_incompatible")
        except CoordinatorConflict:
            self._set_stale()
            raise
        except ReleaseStoreAuthorityError as exc:
            self._set_stale()
            raise CoordinatorConflict(
                "release activation generation fence is stale"
            ) from exc
        except _StageFailure as failure:
            self._set_failed(failure.reason)
            raise ReleaseActivationFailed(
                failure.reason,
                rolled_back=False,
            ) from failure
        except BaseException as exc:
            self._set_failed("candidate_verification_failed")
            raise ReleaseActivationFailed(
                "candidate_verification_failed",
                rolled_back=False,
            ) from exc

        return self._activate_accepted(
            accepted_candidate,
            original,
            selection_reason="activate",
            rollback_rehearsal=False,
        )

    def _activate_previous(self) -> ActiveReleaseState:
        try:
            self._transition(
                ReleaseActivationPhase.VERIFYING,
                candidate_release_id=None,
                current_release_id=None,
                blocking_reason=None,
            )
            try:
                original = self._store.verify_startup(self._control)
            except ImmutableReleaseStoreError as exc:
                raise _StageFailure("rollback_target_verification_failed") from exc
            self._require_active_fence()
            with self._lock:
                self._current_release_id = original.current.release_id
            accepted_candidate = original.previous
            if accepted_candidate is None:
                raise _StageFailure("rollback_target_unavailable")
            current_manifest = original.current.manifest
            if (
                current_manifest.rollback_release_id.casefold()
                != accepted_candidate.release_id.casefold()
                or not current_manifest.supports_direct_activation_from(
                    accepted_candidate.release_id
                )
            ):
                raise _StageFailure("rollback_target_unauthorized")
        except CoordinatorConflict:
            self._set_stale()
            raise
        except ReleaseStoreAuthorityError as exc:
            self._set_stale()
            raise CoordinatorConflict(
                "release activation generation fence is stale"
            ) from exc
        except _StageFailure as failure:
            self._set_failed(failure.reason)
            raise ReleaseActivationFailed(
                failure.reason,
                rolled_back=False,
            ) from failure
        except BaseException as exc:
            self._set_failed("rollback_target_verification_failed")
            raise ReleaseActivationFailed(
                "rollback_target_verification_failed",
                rolled_back=False,
            ) from exc

        return self._activate_accepted(
            accepted_candidate,
            original,
            selection_reason="rollback",
            rollback_rehearsal=True,
        )

    def _activate_accepted(
        self,
        accepted_candidate: AcceptedRelease,
        original: ActiveReleaseState,
        *,
        selection_reason: str,
        rollback_rehearsal: bool,
    ) -> ActiveReleaseState:
        launch_handle: object | None = None
        drain_receipt: object | None = None
        adoption_receipt: object | None = None
        adopted = False
        failure_reason = "rehearsal_failed"

        try:
            self._transition(
                ReleaseActivationPhase.REHEARSING,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=None,
            )
            self._call_rehearsal(
                accepted_candidate,
                original.current,
                rollback=rollback_rehearsal,
            )

            self._transition(
                ReleaseActivationPhase.LAUNCHING,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=None,
            )
            launch_handle = self._call_launch(accepted_candidate)

            self._transition(
                ReleaseActivationPhase.PRE_ADOPTION_HEALTH,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=None,
            )
            self._call_health(
                accepted_candidate,
                launch_handle,
                stage=ReleaseHealthStage.PRE_ADOPTION,
                failure_reason="pre_adoption_health_failed",
            )

            self._transition(
                ReleaseActivationPhase.DRAINING,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=None,
            )
            drain_receipt = self._call_drain(original.current)

            self._transition(
                ReleaseActivationPhase.ADOPTING,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=None,
            )
            adoption_receipt = self._call_adopt(
                accepted_candidate,
                original.current,
                launch_handle,
                drain_receipt,
            )
            adopted = True

            self._transition(
                ReleaseActivationPhase.POST_ADOPTION_HEALTH,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=None,
            )
            self._call_health(
                accepted_candidate,
                launch_handle,
                stage=ReleaseHealthStage.POST_ADOPTION,
                failure_reason="post_adoption_health_failed",
            )

            self._transition(
                ReleaseActivationPhase.COMMITTING,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=None,
            )
            try:
                activated = self._store.select_active(
                    accepted_candidate,
                    previous=original.current,
                    selection_reason=selection_reason,
                    control=self._control,
                    fence=self._required_fence(),
                )
            except ReleaseStoreAuthorityError:
                raise
            except ImmutableReleaseStoreError as exc:
                raise _StageFailure("pointer_commit_failed") from exc

            self._transition(
                ReleaseActivationPhase.FINALIZING,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=accepted_candidate.release_id,
                blocking_reason=None,
            )
            self._call_commit(
                accepted_candidate,
                original.current,
                adoption_receipt,
            )

            self._transition(
                ReleaseActivationPhase.ACTIVE,
                candidate_release_id=accepted_candidate.release_id,
                current_release_id=accepted_candidate.release_id,
                blocking_reason=None,
            )
            return activated
        except CoordinatorConflict:
            self._set_stale()
            raise
        except ReleaseStoreAuthorityError as exc:
            self._set_stale()
            raise CoordinatorConflict(
                "release activation generation fence is stale"
            ) from exc
        except _StageFailure as failure:
            failure_reason = failure.reason
            if adopted:
                if (
                    launch_handle is None
                    or drain_receipt is None
                    or adoption_receipt is None
                ):
                    self._set_failed("rollback_failed")
                    raise ReleaseRollbackFailed(
                        "post-adoption rollback context is incomplete"
                    ) from failure
                self._rollback(
                    candidate=accepted_candidate,
                    original=original,
                    launch_handle=launch_handle,
                    drain_receipt=drain_receipt,
                    adoption_receipt=adoption_receipt,
                    failure_reason=failure_reason,
                )
                raise ReleaseActivationFailed(
                    failure_reason,
                    rolled_back=True,
                ) from failure
            self._recover_pre_adoption(
                current=original.current if "original" in locals() else None,
                launch_handle=launch_handle,
                drain_receipt=drain_receipt,
            )
            self._set_failed(failure_reason)
            raise ReleaseActivationFailed(
                failure_reason,
                rolled_back=False,
            ) from failure
        except BaseException as exc:
            if adopted:
                try:
                    self._rollback(
                        candidate=accepted_candidate,
                        original=original,
                        launch_handle=launch_handle,
                        drain_receipt=drain_receipt,
                        adoption_receipt=adoption_receipt,
                        failure_reason=failure_reason,
                    )
                except BaseException:
                    self._set_failed("rollback_failed")
                    raise ReleaseRollbackFailed(
                        "post-adoption rollback could not be proven"
                    ) from exc
                raise ReleaseActivationFailed(
                    failure_reason,
                    rolled_back=True,
                ) from exc
            self._recover_pre_adoption(
                current=original.current if "original" in locals() else None,
                launch_handle=launch_handle,
                drain_receipt=drain_receipt,
            )
            self._set_failed(failure_reason)
            raise ReleaseActivationFailed(
                failure_reason,
                rolled_back=False,
            ) from exc

    def _call_rehearsal(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        *,
        rollback: bool,
    ) -> None:
        rehearsal = self._rehearsal
        if rehearsal is None:
            raise _StageFailure("rehearsal_failed")
        self._require_active_fence()
        try:
            if rollback:
                rehearsal.rehearse_rollback(
                    candidate,
                    current,
                    generation=self._generation(),
                )
            else:
                rehearsal.rehearse(
                    candidate,
                    current,
                    generation=self._generation(),
                )
        except CoordinatorConflict:
            raise
        except BaseException as exc:
            raise _StageFailure("rehearsal_failed") from exc
        self._require_active_fence()

    def _call_launch(self, candidate: AcceptedRelease) -> object:
        launcher = self._launcher
        if launcher is None:
            raise _StageFailure("launch_failed")
        self._require_active_fence()
        try:
            handle = launcher.launch_shadow(
                candidate,
                generation=self._generation(),
            )
        except CoordinatorConflict:
            raise
        except BaseException as exc:
            raise _StageFailure("launch_failed") from exc
        self._require_active_fence()
        return handle

    def _call_health(
        self,
        candidate: AcceptedRelease,
        launch_handle: object,
        *,
        stage: ReleaseHealthStage,
        failure_reason: str,
    ) -> None:
        health = self._health
        if health is None:
            raise _StageFailure(failure_reason)
        self._require_active_fence()
        try:
            health.check(
                candidate,
                launch_handle,
                stage=stage,
                generation=self._generation(),
            )
        except CoordinatorConflict:
            raise
        except BaseException as exc:
            raise _StageFailure(failure_reason) from exc
        self._require_active_fence()

    def _call_drain(self, current: AcceptedRelease) -> object:
        drain = self._drain
        if drain is None:
            raise _StageFailure("drain_failed")
        self._require_active_fence()
        try:
            receipt = drain.drain(current, generation=self._generation())
        except CoordinatorConflict:
            raise
        except BaseException as exc:
            raise _StageFailure("drain_failed") from exc
        self._require_active_fence()
        return receipt

    def _call_adopt(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        launch_handle: object,
        drain_receipt: object,
    ) -> object:
        adoption = self._adoption
        if adoption is None:
            raise _StageFailure("adoption_failed")
        self._require_active_fence()
        try:
            receipt = adoption.adopt(
                candidate,
                current,
                launch_handle,
                drain_receipt,
                generation=self._generation(),
            )
        except CoordinatorConflict:
            raise
        except BaseException as exc:
            raise _StageFailure("adoption_failed") from exc
        self._require_active_fence()
        return receipt

    def _call_commit(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        adoption_receipt: object,
    ) -> None:
        adoption = self._adoption
        if adoption is None:
            raise _StageFailure("adoption_commit_failed")
        self._require_active_fence()
        try:
            adoption.commit(
                candidate,
                current,
                adoption_receipt,
                generation=self._generation(),
            )
        except CoordinatorConflict:
            raise
        except BaseException as exc:
            raise _StageFailure("adoption_commit_failed") from exc
        self._require_active_fence()

    def _recover_pre_adoption(
        self,
        *,
        current: AcceptedRelease | None,
        launch_handle: object | None,
        drain_receipt: object | None,
    ) -> None:
        try:
            if current is not None and drain_receipt is not None:
                self._resume_current(current, drain_receipt)
            if launch_handle is not None:
                self._stop_shadow(launch_handle)
        except CoordinatorConflict:
            self._set_stale()
            raise
        except BaseException as exc:
            self._set_failed("rollback_failed")
            raise ReleaseRollbackFailed(
                "pre-adoption recovery could not be proven"
            ) from exc

    def _rollback(
        self,
        *,
        candidate: AcceptedRelease,
        original: ActiveReleaseState,
        launch_handle: object,
        drain_receipt: object,
        adoption_receipt: object,
        failure_reason: str,
    ) -> ActiveReleaseState:
        self._transition(
            ReleaseActivationPhase.ROLLING_BACK,
            candidate_release_id=candidate.release_id,
            current_release_id=original.current.release_id,
            blocking_reason=failure_reason,
        )
        try:
            adoption = self._adoption
            if adoption is None:
                raise ReleaseRollbackFailed("adoption rollback seam is unavailable")
            self._require_active_fence()
            # Adoption transfers both the public route and, in managed mode,
            # service authority to the candidate. Restore that boundary first:
            # the prior release cannot truthfully resume while the candidate
            # still owns the service generation.
            adoption.rollback(
                candidate,
                original.current,
                adoption_receipt,
                generation=self._generation(),
            )
            self._require_active_fence()
            self._resume_current(original.current, drain_receipt)
            restored = self._store.select_active(
                original.current,
                previous=original.previous,
                selection_reason="rollback",
                control=self._control,
                fence=self._required_fence(),
            )
            self._stop_shadow(launch_handle)
            self._transition(
                ReleaseActivationPhase.ROLLED_BACK,
                candidate_release_id=candidate.release_id,
                current_release_id=original.current.release_id,
                blocking_reason=failure_reason,
            )
            return restored
        except CoordinatorConflict:
            self._set_stale()
            raise
        except BaseException as exc:
            self._set_failed("rollback_failed")
            raise ReleaseRollbackFailed(
                "post-adoption rollback could not be proven"
            ) from exc

    def _resume_current(
        self,
        current: AcceptedRelease,
        drain_receipt: object,
    ) -> None:
        drain = self._drain
        if drain is None:
            raise ReleaseRollbackFailed("drain recovery seam is unavailable")
        self._require_active_fence()
        drain.resume(
            current,
            drain_receipt,
            generation=self._generation(),
        )
        self._require_active_fence()

    def _stop_shadow(self, launch_handle: object) -> None:
        launcher = self._launcher
        if launcher is None:
            raise ReleaseRollbackFailed("candidate cleanup seam is unavailable")
        self._require_active_fence()
        launcher.stop_shadow(
            launch_handle,
            generation=self._generation(),
        )
        self._require_active_fence()

    def _transition(
        self,
        phase: ReleaseActivationPhase,
        *,
        candidate_release_id: str | None,
        current_release_id: str | None,
        blocking_reason: str | None,
    ) -> None:
        fence = self._required_fence()
        if type(phase) is not ReleaseActivationPhase:
            raise TypeError("phase must be a ReleaseActivationPhase")
        _optional_release_id(candidate_release_id)
        _optional_release_id(current_release_id)
        if blocking_reason is not None and blocking_reason not in _BLOCKING_REASONS:
            raise ValueError("blocking_reason is invalid")
        phase_started_at = time.time()
        payload: dict[str, JsonValue] = {
            "blocking_reason": blocking_reason,
            "candidate_release_id": candidate_release_id,
            "current_release_id": current_release_id,
            "phase": phase.value,
            "phase_started_at": phase_started_at,
            "schema_version": _STATUS_SCHEMA_VERSION,
        }
        self._control.record_event(fence, _STATUS_EVENT, payload)
        with self._lock:
            self._phase = phase
            self._candidate_release_id = candidate_release_id
            self._current_release_id = current_release_id
            self._blocking_reason = blocking_reason
            self._phase_started_at = phase_started_at

    def _set_failed(self, reason: str) -> None:
        try:
            self._transition(
                ReleaseActivationPhase.FAILED,
                candidate_release_id=self._candidate_release_id,
                current_release_id=self._current_release_id,
                blocking_reason=reason,
            )
        except CoordinatorConflict:
            self._set_stale()

    def _set_stale(self) -> None:
        with self._lock:
            self._phase = ReleaseActivationPhase.STALE
            self._blocking_reason = "stale_generation"
            self._phase_started_at = time.time()

    def _required_fence(self) -> GenerationFence:
        if type(self._fence) is not GenerationFence:
            raise CoordinatorConflict("release activation generation fence is unavailable")
        return self._fence

    def _generation(self) -> int:
        return self._required_fence().generation

    def _registration_key(self) -> tuple[str, int, str]:
        fence = self._required_fence()
        return (str(self._control.database), fence.generation, fence.owner_id)

    def _require_active_fence(self) -> None:
        fence = self._required_fence()
        snapshot = self._control.snapshot()
        if (
            snapshot.mode is not ServiceMode.COORDINATOR
            or snapshot.status is not CoordinatorStatus.ACTIVE
            or snapshot.generation != fence.generation
            or snapshot.owner_id != fence.owner_id
        ):
            raise CoordinatorConflict("release activation generation fence is stale")


def _read_persisted_status(control: ServiceControl) -> _PersistedStatus:
    latest = _PersistedStatus(
        phase=ReleaseActivationPhase.IDLE,
        generation=None,
        candidate_release_id=None,
        current_release_id=None,
        blocking_reason=None,
        phase_started_at=None,
    )
    after_sequence = 0
    while True:
        events = control.events(after_sequence=after_sequence, limit=_EVENT_PAGE_SIZE)
        if not events:
            break
        for event in events:
            if event.event_type == _STATUS_EVENT:
                latest = _parse_status_event(
                    event.payload,
                    generation=event.generation,
                )
        after_sequence = events[-1].sequence
        if len(events) < _EVENT_PAGE_SIZE:
            break
    return latest


def _parse_status_event(
    payload: dict[str, JsonValue],
    *,
    generation: int,
) -> _PersistedStatus:
    expected = {
        "blocking_reason",
        "candidate_release_id",
        "current_release_id",
        "phase",
        "phase_started_at",
        "schema_version",
    }
    if set(payload) != expected or payload["schema_version"] != _STATUS_SCHEMA_VERSION:
        raise ReleaseActivationError("persisted activation status is invalid")
    try:
        phase = ReleaseActivationPhase(payload["phase"])
    except (TypeError, ValueError) as exc:
        raise ReleaseActivationError("persisted activation phase is invalid") from exc
    if phase is ReleaseActivationPhase.STALE:
        raise ReleaseActivationError("stale activation status cannot be persisted")
    candidate_release_id = _optional_release_id(payload["candidate_release_id"])
    current_release_id = _optional_release_id(payload["current_release_id"])
    blocking_reason = payload["blocking_reason"]
    if blocking_reason is not None and (
        type(blocking_reason) is not str or blocking_reason not in _BLOCKING_REASONS
    ):
        raise ReleaseActivationError("persisted activation reason is invalid")
    if phase in {
        ReleaseActivationPhase.FAILED,
        ReleaseActivationPhase.ROLLING_BACK,
        ReleaseActivationPhase.ROLLED_BACK,
    }:
        if blocking_reason is None:
            raise ReleaseActivationError("persisted blocked activation lacks a reason")
    elif blocking_reason is not None:
        raise ReleaseActivationError(
            "persisted unblocked activation contains a reason"
        )
    phase_started_at = payload["phase_started_at"]
    if (
        isinstance(phase_started_at, bool)
        or not isinstance(phase_started_at, (int, float))
        or not math.isfinite(float(phase_started_at))
    ):
        raise ReleaseActivationError("persisted activation timestamp is invalid")
    return _PersistedStatus(
        phase=phase,
        generation=generation,
        candidate_release_id=candidate_release_id,
        current_release_id=current_release_id,
        blocking_reason=blocking_reason,
        phase_started_at=float(phase_started_at),
    )


def _optional_release_id(value: JsonValue) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _RELEASE_ID_PATTERN.fullmatch(value) is None:
        raise ReleaseActivationError("persisted activation release ID is invalid")
    return value


__all__ = [
    "ReleaseActivationBusy",
    "ReleaseActivationError",
    "ReleaseActivationFailed",
    "ReleaseActivationPhase",
    "ReleaseActivationRole",
    "ReleaseActivationRoleError",
    "ReleaseActivationStatus",
    "ReleaseActivator",
    "ReleaseAdoptionPort",
    "ReleaseDrainPort",
    "ReleaseHealthPort",
    "ReleaseHealthStage",
    "ReleaseLaunchPort",
    "ReleaseRehearsalPort",
    "ReleaseRollbackFailed",
]
