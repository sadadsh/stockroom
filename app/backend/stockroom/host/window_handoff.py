"""Fail-safe orchestration for a side-by-side Stockroom window replacement.

This module owns ordering, validation, receipts, and rollback.  Process launch,
the same-user pipe, and WebView lifecycle remain behind
:class:`WindowHandoffPorts`, so the safety sequence can be fault-tested without
opening a native window.  The release activator remains the sole owner of the
durable release pointer.

The old window is never hidden until the candidate is both hidden-ready and
visibly verified.  ``begin`` returns only after a post-cutover health proof
matches the durable UI continuity digest, but it deliberately does not commit
the candidate.  The release activator durably selects the candidate release and
then calls ``commit``.  Every failure before that durable selection can call
``rollback`` to restore and verify the old window before the candidate is
stopped.  Once ``commit`` succeeds, retirement failure is cleanup debt, not
permission to roll the visible application back across an already-committed
boundary.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from stockroom.host.window_geometry import WindowGeometry

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ROUTES = frozenset({"components", "stm", "settings"})
_THEMES = frozenset({"dark", "light"})


class WindowHandoffError(RuntimeError):
    """A replacement could not become active or restore the old window."""

    def __init__(
        self,
        phase: str,
        *,
        cause: BaseException,
        rollback_errors: tuple[str, ...] = (),
    ) -> None:
        detail = f"window handoff failed during {phase}"
        if rollback_errors:
            detail += "; rollback failed: " + ", ".join(rollback_errors)
        super().__init__(detail)
        self.phase = phase
        self.cause = cause
        self.rollback_errors = rollback_errors


class WindowHandoffState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    PREPARING = "preparing"
    READY_HIDDEN = "ready-hidden"
    VISIBLE_TRIAL = "visible-trial"
    COMMITTED = "committed"
    ACTIVE = "active"
    ACTIVE_RETIREMENT_PENDING = "active-retirement-pending"
    ROLLED_BACK = "rolled-back"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WindowContinuity:
    """Non-secret identity that the candidate must reproduce exactly."""

    session_digest: str
    geometry: WindowGeometry
    theme: str
    route: str
    selected_ids_digest: str
    workflow_batch: str | None
    event_sequence: int

    def __post_init__(self) -> None:
        if not _DIGEST.fullmatch(self.session_digest):
            raise ValueError("session_digest must be a lowercase SHA-256 digest")
        if type(self.geometry) is not WindowGeometry:
            raise ValueError("geometry must be a WindowGeometry")
        if self.theme not in _THEMES:
            raise ValueError("theme is unsupported")
        if self.route not in _ROUTES:
            raise ValueError("route is unsupported")
        if not _DIGEST.fullmatch(self.selected_ids_digest):
            raise ValueError("selected_ids_digest must be a lowercase SHA-256 digest")
        if self.workflow_batch is not None and (
            type(self.workflow_batch) is not str
            or not self.workflow_batch
            or len(self.workflow_batch) > 192
        ):
            raise ValueError("workflow_batch is invalid")
        if (
            type(self.event_sequence) is not int
            or self.event_sequence < 0
            or self.event_sequence > (1 << 63) - 1
        ):
            raise ValueError("event_sequence is invalid")


@dataclass(frozen=True, slots=True)
class WindowCandidate:
    release_id: str
    process_id: int
    window_handle: int
    profile_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("release_id", self.release_id),
            ("profile_id", self.profile_id),
        ):
            if type(value) is not str or not value or len(value) > 256:
                raise ValueError(f"{label} is invalid")
        if type(self.process_id) is not int or self.process_id <= 0:
            raise ValueError("process_id is invalid")
        if type(self.window_handle) is not int or self.window_handle <= 0:
            raise ValueError("window_handle is invalid")


@dataclass(frozen=True, slots=True)
class WindowProof:
    """One candidate observation at a visibility/health boundary."""

    release_id: str
    process_id: int
    window_handle: int
    session_digest: str
    geometry: WindowGeometry
    theme: str
    route: str
    selected_ids_digest: str
    workflow_batch: str | None
    event_sequence: int
    hidden: bool
    visible: bool
    api_healthy: bool
    event_stream_healthy: bool

    def __post_init__(self) -> None:
        if type(self.hidden) is not bool or type(self.visible) is not bool:
            raise ValueError("window visibility proof is invalid")
        if self.hidden == self.visible:
            raise ValueError("a window proof must be exactly hidden or visible")
        if type(self.api_healthy) is not bool or type(self.event_stream_healthy) is not bool:
            raise ValueError("window health proof is invalid")


@dataclass(frozen=True, slots=True)
class WindowHandoffEvent:
    phase: str
    monotonic_seconds: float


@dataclass(frozen=True, slots=True)
class WindowHandoffReceipt:
    schema: str
    version: int
    handoff_id: str
    release_id: str
    candidate_process_id: int
    candidate_window_handle: int
    session_digest: str
    event_sequence: int
    state: WindowHandoffState
    retirement_pending: bool
    events: tuple[WindowHandoffEvent, ...]


@dataclass(frozen=True, slots=True)
class WindowHandoffAdoption:
    """Reversible visible trial returned before the release pointer commits."""

    schema: str
    version: int
    handoff_id: str
    release_id: str
    candidate: WindowCandidate
    continuity: WindowContinuity
    events: tuple[WindowHandoffEvent, ...]


class WindowHandoffPorts(Protocol):
    """Native/update operations needed by the ordered handoff."""

    def capture_continuity(self) -> WindowContinuity: ...

    def spawn_hidden(
        self,
        handoff_id: str,
        target_release_id: str,
        continuity: WindowContinuity,
    ) -> WindowCandidate: ...

    def wait_hidden_ready(
        self,
        candidate: WindowCandidate,
        continuity: WindowContinuity,
    ) -> WindowProof: ...

    def show_candidate(self, candidate: WindowCandidate) -> None: ...

    def verify_visible(
        self,
        candidate: WindowCandidate,
        continuity: WindowContinuity,
    ) -> WindowProof: ...

    def hide_old(self) -> None: ...

    def verify_post_cutover(
        self,
        candidate: WindowCandidate,
        continuity: WindowContinuity,
    ) -> WindowProof: ...

    def commit_candidate(self, candidate: WindowCandidate) -> None: ...

    def retire_old(self) -> None: ...

    def rollback_candidate(self, candidate: WindowCandidate) -> None: ...

    def show_old(self) -> None: ...

    def verify_old_usable(self, continuity: WindowContinuity) -> None: ...

    def stop_candidate(self, candidate: WindowCandidate) -> None: ...


def _validate_proof(
    proof: WindowProof,
    candidate: WindowCandidate,
    continuity: WindowContinuity,
    *,
    visible: bool,
) -> None:
    if (
        proof.release_id != candidate.release_id
        or proof.process_id != candidate.process_id
        or proof.window_handle != candidate.window_handle
    ):
        raise ValueError("candidate proof identity is incoherent")
    if (
        proof.session_digest != continuity.session_digest
        or proof.geometry != continuity.geometry
        or proof.theme != continuity.theme
        or proof.route != continuity.route
        or proof.selected_ids_digest != continuity.selected_ids_digest
        or proof.workflow_batch != continuity.workflow_batch
        or proof.event_sequence != continuity.event_sequence
    ):
        raise ValueError("candidate continuity proof does not match the durable session")
    if proof.visible is not visible or proof.hidden is visible:
        raise ValueError("candidate visibility proof is incoherent")
    if not proof.api_healthy or not proof.event_stream_healthy:
        raise ValueError("candidate health proof is not ready")


class ManagedWindowHandoff:
    """Execute one non-overlapping, two-phase window replacement."""

    def __init__(
        self,
        ports: WindowHandoffPorts,
        *,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._ports = ports
        self._clock = clock
        self._id_factory = id_factory
        self._state = WindowHandoffState.IDLE
        self._active: WindowHandoffAdoption | None = None

    @property
    def state(self) -> WindowHandoffState:
        return self._state

    def _validate_adoption(self, adoption: WindowHandoffAdoption) -> None:
        if type(adoption) is not WindowHandoffAdoption:
            raise TypeError("adoption must be a WindowHandoffAdoption")
        if self._active is not adoption:
            raise RuntimeError("window handoff adoption is stale")
        if self._state is not WindowHandoffState.VISIBLE_TRIAL:
            raise RuntimeError("window handoff is not awaiting commit")

    def _restore_old(
        self,
        *,
        candidate: WindowCandidate,
        continuity: WindowContinuity,
        old_hidden: bool,
    ) -> tuple[str, ...]:
        rollback_errors: list[str] = []
        try:
            self._ports.rollback_candidate(candidate)
        except BaseException as rollback_error:
            rollback_errors.append(
                f"candidate route: {type(rollback_error).__name__}"
            )
        if old_hidden:
            try:
                self._ports.show_old()
            except BaseException as rollback_error:
                rollback_errors.append(f"show old: {type(rollback_error).__name__}")
        try:
            self._ports.verify_old_usable(continuity)
        except BaseException as rollback_error:
            rollback_errors.append(f"old health: {type(rollback_error).__name__}")
        try:
            self._ports.stop_candidate(candidate)
        except BaseException as rollback_error:
            rollback_errors.append(f"stop candidate: {type(rollback_error).__name__}")
        self._active = None
        self._state = (
            WindowHandoffState.FAILED
            if rollback_errors
            else WindowHandoffState.ROLLED_BACK
        )
        return tuple(rollback_errors)

    def begin(self, target_release_id: str) -> WindowHandoffAdoption:
        """Create and prove one visible candidate without committing it."""

        if self._state not in {
            WindowHandoffState.IDLE,
            WindowHandoffState.ACTIVE,
            WindowHandoffState.ROLLED_BACK,
        }:
            raise RuntimeError("a window handoff is already active")
        if (
            type(target_release_id) is not str
            or not target_release_id
            or len(target_release_id) > 256
        ):
            raise ValueError("target_release_id is invalid")

        handoff_id = self._id_factory()
        try:
            handoff_id = str(uuid.UUID(handoff_id))
        except (ValueError, AttributeError):
            raise ValueError("id_factory returned an invalid handoff id") from None

        events: list[WindowHandoffEvent] = []
        candidate: WindowCandidate | None = None
        continuity: WindowContinuity | None = None
        old_hidden = False
        phase = "capture-continuity"

        def mark(name: str) -> None:
            events.append(WindowHandoffEvent(name, self._clock()))

        self._state = WindowHandoffState.STARTING
        mark("starting")
        try:
            continuity = self._ports.capture_continuity()
            if type(continuity) is not WindowContinuity:
                raise ValueError("continuity capture returned an invalid document")
            mark("durable-session")

            phase = "spawn-hidden"
            self._state = WindowHandoffState.PREPARING
            candidate = self._ports.spawn_hidden(
                handoff_id,
                target_release_id,
                continuity,
            )
            if type(candidate) is not WindowCandidate:
                raise ValueError("candidate spawn returned an invalid identity")
            if candidate.release_id != target_release_id:
                raise ValueError("candidate release does not match the target")
            mark("candidate-started")

            phase = "hidden-ready"
            ready = self._ports.wait_hidden_ready(candidate, continuity)
            if type(ready) is not WindowProof:
                raise ValueError("hidden readiness returned an invalid proof")
            _validate_proof(ready, candidate, continuity, visible=False)
            self._state = WindowHandoffState.READY_HIDDEN
            mark("hidden-ready")

            phase = "show-candidate"
            self._ports.show_candidate(candidate)
            self._state = WindowHandoffState.VISIBLE_TRIAL
            mark("candidate-show-requested")

            phase = "visible-proof"
            visible_proof = self._ports.verify_visible(candidate, continuity)
            if type(visible_proof) is not WindowProof:
                raise ValueError("visible readiness returned an invalid proof")
            _validate_proof(visible_proof, candidate, continuity, visible=True)
            mark("candidate-visible")

            phase = "hide-old"
            # Treat a failing native call as potentially partially applied.
            # Showing an already-visible old window is safe; failing to show a
            # partially hidden one is not.
            old_hidden = True
            self._ports.hide_old()
            mark("old-hidden")

            phase = "post-cutover-health"
            post_cutover = self._ports.verify_post_cutover(candidate, continuity)
            if type(post_cutover) is not WindowProof:
                raise ValueError("post-cutover readiness returned an invalid proof")
            _validate_proof(post_cutover, candidate, continuity, visible=True)
            mark("post-cutover-healthy")
        except BaseException as exc:
            if candidate is not None:
                assert continuity is not None
                rollback_errors = self._restore_old(
                    candidate=candidate,
                    continuity=continuity,
                    old_hidden=old_hidden,
                )
            else:
                rollback_errors = ()
                if continuity is not None:
                    try:
                        self._ports.verify_old_usable(continuity)
                    except BaseException as rollback_error:
                        rollback_errors = (
                            f"old health: {type(rollback_error).__name__}",
                        )
                self._state = (
                    WindowHandoffState.FAILED
                    if rollback_errors
                    else WindowHandoffState.ROLLED_BACK
                )
            raise WindowHandoffError(
                phase,
                cause=exc,
                rollback_errors=rollback_errors,
            ) from exc

        assert candidate is not None
        assert continuity is not None
        adoption = WindowHandoffAdoption(
            schema="stockroom.window-handoff-adoption",
            version=1,
            handoff_id=handoff_id,
            release_id=candidate.release_id,
            candidate=candidate,
            continuity=continuity,
            events=tuple(events),
        )
        self._active = adoption
        return adoption

    def rollback(self, adoption: WindowHandoffAdoption) -> None:
        """Restore the old window after the release activator rolls back."""

        self._validate_adoption(adoption)
        rollback_errors = self._restore_old(
            candidate=adoption.candidate,
            continuity=adoption.continuity,
            old_hidden=True,
        )
        if rollback_errors:
            cause = RuntimeError("window handoff rollback was incomplete")
            raise WindowHandoffError(
                "rollback",
                cause=cause,
                rollback_errors=rollback_errors,
            ) from cause

    def commit(self, adoption: WindowHandoffAdoption) -> WindowHandoffReceipt:
        """Finalize candidate ownership after the release pointer is durable."""

        self._validate_adoption(adoption)
        events = list(adoption.events)

        def mark(name: str) -> None:
            events.append(WindowHandoffEvent(name, self._clock()))

        try:
            self._ports.commit_candidate(adoption.candidate)
        except BaseException as exc:
            # The release pointer owner must first enter its rollback sequence.
            # Keep this reversible trial registered so its subsequent
            # ``rollback`` call can restore the old window exactly once.
            raise WindowHandoffError(
                "commit-candidate",
                cause=exc,
                rollback_errors=(),
            ) from exc
        self._state = WindowHandoffState.COMMITTED
        mark("pointer-committed")

        try:
            self._ports.retire_old()
        except BaseException:
            # The new release is already committed and visibly healthy.  Rolling
            # the pointer back here would create the mixed-version boundary the
            # handoff exists to prevent.  Keep the old hidden and retry its
            # reference-counted retirement from convergence maintenance.
            self._state = WindowHandoffState.ACTIVE_RETIREMENT_PENDING
            mark("old-retirement-pending")
            retirement_pending = True
        else:
            self._state = WindowHandoffState.ACTIVE
            mark("old-retired")
            retirement_pending = False
        self._active = None

        return WindowHandoffReceipt(
            schema="stockroom.window-handoff-receipt",
            version=1,
            handoff_id=adoption.handoff_id,
            release_id=adoption.release_id,
            candidate_process_id=adoption.candidate.process_id,
            candidate_window_handle=adoption.candidate.window_handle,
            session_digest=adoption.continuity.session_digest,
            event_sequence=adoption.continuity.event_sequence,
            state=self._state,
            retirement_pending=retirement_pending,
            events=tuple(events),
        )


__all__ = [
    "ManagedWindowHandoff",
    "WindowCandidate",
    "WindowContinuity",
    "WindowHandoffAdoption",
    "WindowHandoffError",
    "WindowHandoffEvent",
    "WindowHandoffPorts",
    "WindowHandoffReceipt",
    "WindowHandoffState",
    "WindowProof",
]
