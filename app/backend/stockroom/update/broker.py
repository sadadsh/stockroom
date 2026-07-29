"""Generation-fenced background broker for TUF-verified release staging.

The broker owns discovery cadence, retry policy, sanitized durable status, and
one joinable supervisor thread.  It deliberately has no activation, Git,
signing-key, trust-root generation, host, or process-handoff behavior.
"""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from tuf.api import exceptions as tuf_exceptions

from stockroom.service import (
    CoordinatorConflict,
    CoordinatorStatus,
    GenerationFence,
    ServiceControl,
    ServiceMode,
)
from stockroom.service.control import JsonValue

from .trusted_repository import (
    ReleaseSetVerificationError,
    RepositoryRefreshError,
    TrustedReleaseRepository,
    TrustedRepositoryError,
    VerifiedReleaseSet,
)

_STATUS_EVENT = "update_broker_status"
_RELEASE_EVENT = "update_release_staged"
_EVENT_SCHEMA_VERSION = 1
_EVENT_PAGE_SIZE = 1_000
_MAX_ATTEMPT = 2**63 - 1
_RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ACTIVE_BROKERS_LOCK = threading.Lock()
_ACTIVE_BROKERS: set[tuple[str, int, str]] = set()
_BLOCKING_REASONS = frozenset(
    {
        "attempt_deadline_exceeded",
        "interrupted_attempt",
        "release_verification_failed",
        "repository_offline",
        "repository_refresh_rejected",
        "trusted_repository_failure",
        "tuf_metadata_expired",
        "unexpected_broker_failure",
    }
)


class UpdateBrokerRole(str, Enum):
    """Explicit broker authority role."""

    SHADOW = "shadow"
    COORDINATOR = "coordinator"


class UpdateBrokerPhase(str, Enum):
    """Sanitized update convergence phases implemented by this foundation."""

    IDLE = "idle"
    CHECKING = "checking"
    STAGED = "staged"
    RETRY_WAIT = "retry_wait"
    STOPPED = "stopped"
    STALE = "stale"
    FAULTED = "faulted"


class UpdateBrokerError(RuntimeError):
    """Base class for safe update-broker failures."""


class UpdateBrokerRoleError(UpdateBrokerError):
    """A shadow/coordinator authority boundary was violated."""


class UpdateBrokerLifecycleError(UpdateBrokerError):
    """The one-shot broker or its owned handle was used incorrectly."""


class UpdateBrokerJoinTimeout(UpdateBrokerError):
    """The broker did not finish its current bounded operation before timeout."""


class UpdateBrokerStateError(UpdateBrokerError):
    """Persisted broker events are semantically invalid."""


@dataclass(frozen=True, slots=True)
class UpdateBrokerStatus:
    """Credential-free update status suitable for shadow inspection."""

    role: UpdateBrokerRole
    phase: UpdateBrokerPhase
    generation: int
    attempt: int
    target_release_id: str | None
    last_verified_release_id: str | None
    blocking_reason: str | None
    phase_started_at: float | None
    deadline_at: float | None
    next_attempt_at: float | None
    thread_alive: bool


@dataclass(frozen=True, slots=True)
class _DurableProjection:
    phase: UpdateBrokerPhase
    attempt: int
    target_release_id: str | None
    last_verified_release_id: str | None
    blocking_reason: str | None
    phase_started_at: float | None
    deadline_at: float | None
    next_attempt_at: float | None
    event_generation: int | None
    event_sequence: int


class UpdateBrokerHandle:
    """The sole cancellation and join handle for a started broker."""

    def __init__(self, broker: UpdateBroker, thread: threading.Thread) -> None:
        self._broker = broker
        self._thread = thread

    def cancel(self) -> None:
        """Request cooperative cancellation without discarding the join handle."""

        self._broker._request_cancel()

    def join(self, *, timeout: float = 10.0) -> None:
        """Join the owned supervisor thread or report an honest timeout."""

        timeout_seconds = _positive_finite(timeout, "timeout")
        if self._thread is threading.current_thread():
            raise UpdateBrokerLifecycleError("update broker cannot join its own thread")
        self._thread.join(timeout_seconds)
        if self._thread.is_alive():
            raise UpdateBrokerJoinTimeout(
                "update broker still has an in-flight repository operation"
            )

    def status(self) -> UpdateBrokerStatus:
        """Return the broker's sanitized status."""

        return self._broker.status()


class UpdateBroker:
    """Continuously stage signed release sets under one coordinator generation."""

    def __init__(
        self,
        control: ServiceControl,
        *,
        role: UpdateBrokerRole,
        repository: TrustedReleaseRepository | None = None,
        fence: GenerationFence | None = None,
        verified_release_sink: Callable[[VerifiedReleaseSet], None] | None = None,
        refresh_interval_seconds: float = 15 * 60,
        attempt_deadline_seconds: float = 10 * 60,
        minimum_retry_backoff_seconds: float = 5.0,
        maximum_retry_backoff_seconds: float = 5 * 60,
        retry_backoff_multiplier: float = 2.0,
    ) -> None:
        if not isinstance(control, ServiceControl):
            raise TypeError("control must be a ServiceControl")
        if type(role) is not UpdateBrokerRole:
            raise TypeError("role must be an UpdateBrokerRole")
        expected_mode = (
            ServiceMode.COORDINATOR
            if role is UpdateBrokerRole.COORDINATOR
            else ServiceMode.SHADOW
        )
        if control.mode is not expected_mode:
            raise UpdateBrokerRoleError("broker role must match ServiceControl mode")

        self._control = control
        self._role = role
        self._repository = repository
        self._fence = fence
        self._verified_release_sink = verified_release_sink
        self._refresh_interval = _positive_finite(
            refresh_interval_seconds, "refresh_interval_seconds"
        )
        self._attempt_deadline = _positive_finite(
            attempt_deadline_seconds, "attempt_deadline_seconds"
        )
        self._minimum_backoff = _positive_finite(
            minimum_retry_backoff_seconds, "minimum_retry_backoff_seconds"
        )
        self._maximum_backoff = _positive_finite(
            maximum_retry_backoff_seconds, "maximum_retry_backoff_seconds"
        )
        self._backoff_multiplier = _positive_finite(
            retry_backoff_multiplier, "retry_backoff_multiplier"
        )
        if self._maximum_backoff < self._minimum_backoff:
            raise ValueError("maximum retry backoff must be at least the minimum")
        if self._backoff_multiplier < 1:
            raise ValueError("retry_backoff_multiplier must be at least 1")

        if role is UpdateBrokerRole.SHADOW:
            if (
                repository is not None
                or fence is not None
                or verified_release_sink is not None
            ):
                raise UpdateBrokerRoleError(
                    "shadow broker cannot receive repository or generation authority"
                )
        else:
            if not isinstance(repository, TrustedReleaseRepository):
                raise TypeError(
                    "coordinator broker requires a TrustedReleaseRepository"
                )
            if type(fence) is not GenerationFence:
                raise TypeError("coordinator broker requires a GenerationFence")
            if verified_release_sink is not None and not callable(
                verified_release_sink
            ):
                raise TypeError("verified_release_sink must be callable")
            self._require_active_fence()

        projection = _read_durable_projection(control)
        if (
            role is UpdateBrokerRole.COORDINATOR
            and projection.phase is UpdateBrokerPhase.CHECKING
        ):
            projection = _DurableProjection(
                phase=UpdateBrokerPhase.RETRY_WAIT,
                attempt=projection.attempt,
                target_release_id=None,
                last_verified_release_id=projection.last_verified_release_id,
                blocking_reason="interrupted_attempt",
                phase_started_at=time.time(),
                deadline_at=None,
                next_attempt_at=time.time(),
                event_generation=projection.event_generation,
                event_sequence=projection.event_sequence,
            )

        self._lock = threading.Lock()
        self._cancel_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._registration_key: tuple[str, int, str] | None = None
        self._started_once = False
        self._phase = projection.phase
        self._attempt = projection.attempt
        self._target_release_id = projection.target_release_id
        self._last_verified_release_id = projection.last_verified_release_id
        self._blocking_reason = projection.blocking_reason
        self._phase_started_at = projection.phase_started_at
        self._deadline_at = projection.deadline_at
        self._next_attempt_at = projection.next_attempt_at

    def start(self) -> UpdateBrokerHandle:
        """Start one joinable coordinator loop; shadow brokers never start."""

        if self._role is not UpdateBrokerRole.COORDINATOR:
            raise UpdateBrokerRoleError("shadow broker cannot fetch or stage releases")
        self._require_active_fence()
        registration_key = self._coordinator_registration_key()
        with _ACTIVE_BROKERS_LOCK:
            if registration_key in _ACTIVE_BROKERS:
                raise UpdateBrokerLifecycleError(
                    "this coordinator generation already has an update broker"
                )
            _ACTIVE_BROKERS.add(registration_key)
        with self._lock:
            if self._started_once:
                with _ACTIVE_BROKERS_LOCK:
                    _ACTIVE_BROKERS.discard(registration_key)
                raise UpdateBrokerLifecycleError("update broker instances are one-shot")
            self._started_once = True
            self._registration_key = registration_key
            thread = threading.Thread(
                target=self._supervise,
                name=f"stockroom-update-broker-{self._generation()}",
                daemon=False,
            )
            self._thread = thread
            handle = UpdateBrokerHandle(self, thread)
        try:
            thread.start()
        except BaseException:
            with _ACTIVE_BROKERS_LOCK:
                _ACTIVE_BROKERS.discard(registration_key)
            with self._lock:
                self._thread = None
                self._registration_key = None
                self._phase = UpdateBrokerPhase.FAULTED
                self._blocking_reason = "unexpected_broker_failure"
                self._phase_started_at = time.time()
            raise
        return handle

    def status(self) -> UpdateBrokerStatus:
        """Return local coordinator status or durable read-only shadow status."""

        if self._role is UpdateBrokerRole.SHADOW:
            projection = _read_durable_projection(self._control)
            control_snapshot = self._control.snapshot()
            phase = projection.phase
            blocking_reason = projection.blocking_reason
            if (
                projection.event_generation is not None
                and projection.event_generation < control_snapshot.generation
                and phase is UpdateBrokerPhase.CHECKING
            ):
                phase = UpdateBrokerPhase.STALE
                blocking_reason = "interrupted_attempt"
            blocking_reason = _visible_blocking_reason(
                phase,
                deadline_at=projection.deadline_at,
                blocking_reason=blocking_reason,
            )
            return UpdateBrokerStatus(
                role=self._role,
                phase=phase,
                generation=control_snapshot.generation,
                attempt=projection.attempt,
                target_release_id=projection.target_release_id,
                last_verified_release_id=projection.last_verified_release_id,
                blocking_reason=blocking_reason,
                phase_started_at=projection.phase_started_at,
                deadline_at=projection.deadline_at,
                next_attempt_at=projection.next_attempt_at,
                thread_alive=False,
            )

        with self._lock:
            thread = self._thread
            blocking_reason = _visible_blocking_reason(
                self._phase,
                deadline_at=self._deadline_at,
                blocking_reason=self._blocking_reason,
            )
            return UpdateBrokerStatus(
                role=self._role,
                phase=self._phase,
                generation=self._generation(),
                attempt=self._attempt,
                target_release_id=self._target_release_id,
                last_verified_release_id=self._last_verified_release_id,
                blocking_reason=blocking_reason,
                phase_started_at=self._phase_started_at,
                deadline_at=self._deadline_at,
                next_attempt_at=self._next_attempt_at,
                thread_alive=thread is not None and thread.is_alive(),
            )

    def _generation(self) -> int:
        if self._fence is None:
            return self._control.snapshot().generation
        return self._fence.generation

    def _coordinator_registration_key(self) -> tuple[str, int, str]:
        fence = self._fence
        if type(fence) is not GenerationFence:
            raise CoordinatorConflict("update broker generation fence is unavailable")
        return (str(self._control.database), fence.generation, fence.owner_id)

    def _request_cancel(self) -> None:
        if self._role is not UpdateBrokerRole.COORDINATOR:
            raise UpdateBrokerRoleError("shadow broker has no work to cancel")
        self._cancel_requested.set()

    def _require_active_fence(self) -> None:
        fence = self._fence
        if type(fence) is not GenerationFence:
            raise CoordinatorConflict("update broker generation fence is unavailable")
        snapshot = self._control.snapshot()
        if (
            snapshot.mode is not ServiceMode.COORDINATOR
            or snapshot.status is not CoordinatorStatus.ACTIVE
            or snapshot.generation != fence.generation
            or snapshot.owner_id != fence.owner_id
        ):
            raise CoordinatorConflict("update broker generation fence is stale")

    def _supervise(self) -> None:
        terminal_phase = UpdateBrokerPhase.STOPPED
        terminal_reason: str | None = None
        backoff = self._minimum_backoff
        try:
            self._resume_persisted_backoff()
            while not self._cancel_requested.is_set():
                self._require_active_fence()
                attempt = self._next_attempt()
                phase_started_at = time.time()
                deadline_at = phase_started_at + self._attempt_deadline
                deadline_monotonic = time.monotonic() + self._attempt_deadline
                self._transition(
                    UpdateBrokerPhase.CHECKING,
                    attempt=attempt,
                    target_release_id=None,
                    blocking_reason=None,
                    phase_started_at=phase_started_at,
                    deadline_at=deadline_at,
                    next_attempt_at=None,
                )

                try:
                    release = self._stage_release()
                except TrustedRepositoryError as exc:
                    reason = _repository_failure_code(exc)
                    retry_at = time.time() + backoff
                    self._transition(
                        UpdateBrokerPhase.RETRY_WAIT,
                        attempt=attempt,
                        target_release_id=None,
                        blocking_reason=reason,
                        phase_started_at=time.time(),
                        deadline_at=retry_at,
                        next_attempt_at=retry_at,
                    )
                    if self._cancel_requested.wait(backoff):
                        break
                    backoff = min(
                        self._maximum_backoff,
                        backoff * self._backoff_multiplier,
                    )
                    continue

                self._require_active_fence()
                self._record_verified_release(release, attempt=attempt)
                sink = self._verified_release_sink
                if sink is not None:
                    sink(release)
                if self._cancel_requested.is_set():
                    break
                if time.monotonic() > deadline_monotonic:
                    retry_at = time.time() + backoff
                    self._transition(
                        UpdateBrokerPhase.RETRY_WAIT,
                        attempt=attempt,
                        target_release_id=release.release_id,
                        blocking_reason="attempt_deadline_exceeded",
                        phase_started_at=time.time(),
                        deadline_at=retry_at,
                        next_attempt_at=retry_at,
                    )
                    if self._cancel_requested.wait(backoff):
                        break
                    backoff = min(
                        self._maximum_backoff,
                        backoff * self._backoff_multiplier,
                    )
                    continue

                backoff = self._minimum_backoff
                next_check_at = time.time() + self._refresh_interval
                self._transition(
                    UpdateBrokerPhase.STAGED,
                    attempt=attempt,
                    target_release_id=release.release_id,
                    blocking_reason=None,
                    phase_started_at=time.time(),
                    deadline_at=next_check_at,
                    next_attempt_at=next_check_at,
                )
                if self._cancel_requested.wait(self._refresh_interval):
                    break
        except CoordinatorConflict:
            terminal_phase = UpdateBrokerPhase.STALE
            terminal_reason = "interrupted_attempt"
        except BaseException:
            terminal_phase = UpdateBrokerPhase.FAULTED
            terminal_reason = "unexpected_broker_failure"
        finally:
            self._cancel_requested.set()
            try:
                self._finish(terminal_phase, terminal_reason)
            finally:
                self._release_registration()

    def _release_registration(self) -> None:
        with self._lock:
            registration_key = self._registration_key
            self._registration_key = None
        if registration_key is not None:
            with _ACTIVE_BROKERS_LOCK:
                _ACTIVE_BROKERS.discard(registration_key)

    def _resume_persisted_backoff(self) -> None:
        with self._lock:
            phase = self._phase
            retry_at = self._next_attempt_at
            reason = self._blocking_reason
            attempt = self._attempt
            last_release = self._last_verified_release_id
        if phase is not UpdateBrokerPhase.RETRY_WAIT or retry_at is None:
            return
        remaining = max(0.0, retry_at - time.time())
        if remaining <= 0:
            return
        self._transition(
            UpdateBrokerPhase.RETRY_WAIT,
            attempt=attempt,
            target_release_id=None,
            blocking_reason=reason,
            phase_started_at=time.time(),
            deadline_at=retry_at,
            next_attempt_at=retry_at,
            last_verified_release_id=last_release,
        )
        self._cancel_requested.wait(remaining)

    def _next_attempt(self) -> int:
        with self._lock:
            if self._attempt >= _MAX_ATTEMPT:
                raise UpdateBrokerStateError("update broker attempt counter exhausted")
            return self._attempt + 1

    def _stage_release(self) -> VerifiedReleaseSet:
        repository = self._repository
        if not isinstance(repository, TrustedReleaseRepository):
            raise UpdateBrokerRoleError(
                "coordinator broker lost its trusted repository boundary"
            )
        return repository.stage_release()

    def _record_verified_release(
        self, release: VerifiedReleaseSet, *, attempt: int
    ) -> None:
        fence = self._fence
        if type(fence) is not GenerationFence:
            raise CoordinatorConflict("update broker generation fence is unavailable")
        payload: dict[str, JsonValue] = {
            "attempt": attempt,
            "manifest_sha256": release.manifest_sha256,
            "package_version": release.manifest.package_version,
            "protocol_version": release.manifest.protocol_version,
            "release_id": release.release_id,
            "schema_version": _EVENT_SCHEMA_VERSION,
        }
        self._control.record_event(fence, _RELEASE_EVENT, payload)
        with self._lock:
            self._last_verified_release_id = release.release_id
            self._target_release_id = release.release_id

    def _transition(
        self,
        phase: UpdateBrokerPhase,
        *,
        attempt: int,
        target_release_id: str | None,
        blocking_reason: str | None,
        phase_started_at: float,
        deadline_at: float | None,
        next_attempt_at: float | None,
        last_verified_release_id: str | None = None,
    ) -> None:
        fence = self._fence
        if type(fence) is not GenerationFence:
            raise CoordinatorConflict("update broker generation fence is unavailable")
        if last_verified_release_id is None:
            with self._lock:
                last_verified_release_id = self._last_verified_release_id
        payload: dict[str, JsonValue] = {
            "attempt": attempt,
            "blocking_reason": blocking_reason,
            "deadline_at": deadline_at,
            "last_verified_release_id": last_verified_release_id,
            "next_attempt_at": next_attempt_at,
            "phase": phase.value,
            "phase_started_at": phase_started_at,
            "schema_version": _EVENT_SCHEMA_VERSION,
            "target_release_id": target_release_id,
        }
        self._control.record_event(fence, _STATUS_EVENT, payload)
        with self._lock:
            self._phase = phase
            self._attempt = attempt
            self._target_release_id = target_release_id
            self._last_verified_release_id = last_verified_release_id
            self._blocking_reason = blocking_reason
            self._phase_started_at = phase_started_at
            self._deadline_at = deadline_at
            self._next_attempt_at = next_attempt_at

    def _finish(
        self,
        phase: UpdateBrokerPhase,
        blocking_reason: str | None,
    ) -> None:
        if phase is UpdateBrokerPhase.STALE:
            with self._lock:
                self._phase = phase
                self._blocking_reason = blocking_reason
                self._phase_started_at = time.time()
                self._deadline_at = None
                self._next_attempt_at = None
            return
        try:
            self._require_active_fence()
            with self._lock:
                attempt = self._attempt
                target_release_id = self._target_release_id
            self._transition(
                phase,
                attempt=attempt,
                target_release_id=target_release_id,
                blocking_reason=blocking_reason,
                phase_started_at=time.time(),
                deadline_at=None,
                next_attempt_at=None,
            )
        except CoordinatorConflict:
            with self._lock:
                self._phase = UpdateBrokerPhase.STALE
                self._blocking_reason = "interrupted_attempt"
                self._phase_started_at = time.time()
                self._deadline_at = None
                self._next_attempt_at = None
        except BaseException:
            with self._lock:
                self._phase = UpdateBrokerPhase.FAULTED
                self._blocking_reason = "unexpected_broker_failure"
                self._phase_started_at = time.time()
                self._deadline_at = None
                self._next_attempt_at = None


def _positive_finite(value: float, name: str) -> float:
    if type(value) not in {int, float}:
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def _repository_failure_code(error: TrustedRepositoryError) -> str:
    chain: list[BaseException] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__
    if any(isinstance(item, tuf_exceptions.ExpiredMetadataError) for item in chain):
        return "tuf_metadata_expired"
    if any(isinstance(item, tuf_exceptions.DownloadError) for item in chain):
        return "repository_offline"
    if isinstance(error, RepositoryRefreshError):
        return "repository_refresh_rejected"
    if isinstance(error, ReleaseSetVerificationError):
        return "release_verification_failed"
    return "trusted_repository_failure"


def _visible_blocking_reason(
    phase: UpdateBrokerPhase,
    *,
    deadline_at: float | None,
    blocking_reason: str | None,
) -> str | None:
    if (
        phase is UpdateBrokerPhase.CHECKING
        and deadline_at is not None
        and time.time() > deadline_at
    ):
        return "attempt_deadline_exceeded"
    return blocking_reason


def _read_durable_projection(control: ServiceControl) -> _DurableProjection:
    projection = _DurableProjection(
        phase=UpdateBrokerPhase.IDLE,
        attempt=0,
        target_release_id=None,
        last_verified_release_id=None,
        blocking_reason=None,
        phase_started_at=None,
        deadline_at=None,
        next_attempt_at=None,
        event_generation=None,
        event_sequence=0,
    )
    latest_release_id: str | None = None
    latest_release_attempt = 0
    latest_release_generation: int | None = None
    latest_release_occurred_at: float | None = None
    latest_release_sequence = 0
    after_sequence = 0
    while True:
        events = control.events(
            after_sequence=after_sequence,
            limit=_EVENT_PAGE_SIZE,
        )
        if not events:
            break
        for event in events:
            if event.event_type == _RELEASE_EVENT:
                latest_release_id, latest_release_attempt = _parse_release_event(
                    event.payload
                )
                latest_release_generation = event.generation
                latest_release_occurred_at = event.occurred_at
                latest_release_sequence = event.sequence
            elif event.event_type == _STATUS_EVENT:
                projection = _parse_status_event(
                    event.payload,
                    generation=event.generation,
                    sequence=event.sequence,
                )
        after_sequence = events[-1].sequence
        if len(events) < _EVENT_PAGE_SIZE:
            break

    if latest_release_id is not None and latest_release_sequence > projection.event_sequence:
        projection = _DurableProjection(
            phase=UpdateBrokerPhase.STAGED,
            attempt=latest_release_attempt,
            target_release_id=latest_release_id,
            last_verified_release_id=latest_release_id,
            blocking_reason=None,
            phase_started_at=latest_release_occurred_at,
            deadline_at=None,
            next_attempt_at=None,
            event_generation=latest_release_generation,
            event_sequence=latest_release_sequence,
        )
    elif (
        latest_release_id is not None
        and projection.last_verified_release_id != latest_release_id
    ):
        raise UpdateBrokerStateError(
            "persisted update status lost the latest verified release"
        )
    return projection


def _parse_release_event(payload: dict[str, JsonValue]) -> tuple[str, int]:
    expected = {
        "attempt",
        "manifest_sha256",
        "package_version",
        "protocol_version",
        "release_id",
        "schema_version",
    }
    if set(payload) != expected:
        raise UpdateBrokerStateError("persisted staged-release event fields are invalid")
    attempt = _stored_int(payload["attempt"], "release attempt", minimum=1)
    _stored_int(payload["protocol_version"], "protocol version", minimum=1)
    if payload["schema_version"] != _EVENT_SCHEMA_VERSION:
        raise UpdateBrokerStateError("persisted staged-release schema is unsupported")
    release_id = _stored_release_id(payload["release_id"], "release ID")
    package_version = payload["package_version"]
    manifest_sha256 = payload["manifest_sha256"]
    if (
        type(package_version) is not str
        or _VERSION_PATTERN.fullmatch(package_version) is None
        or type(manifest_sha256) is not str
        or _SHA256_PATTERN.fullmatch(manifest_sha256) is None
    ):
        raise UpdateBrokerStateError("persisted staged-release event is invalid")
    return release_id, attempt


def _parse_status_event(
    payload: dict[str, JsonValue],
    *,
    generation: int,
    sequence: int,
) -> _DurableProjection:
    expected = {
        "attempt",
        "blocking_reason",
        "deadline_at",
        "last_verified_release_id",
        "next_attempt_at",
        "phase",
        "phase_started_at",
        "schema_version",
        "target_release_id",
    }
    if set(payload) != expected:
        raise UpdateBrokerStateError("persisted update-broker status fields are invalid")
    if payload["schema_version"] != _EVENT_SCHEMA_VERSION:
        raise UpdateBrokerStateError("persisted update-broker status schema is unsupported")
    try:
        phase = UpdateBrokerPhase(payload["phase"])
    except (TypeError, ValueError) as exc:
        raise UpdateBrokerStateError("persisted update-broker phase is invalid") from exc
    if phase is UpdateBrokerPhase.STALE:
        raise UpdateBrokerStateError("stale status cannot be persisted by a fenced-out broker")

    attempt = _stored_int(payload["attempt"], "update attempt", minimum=0)
    blocking_reason = payload["blocking_reason"]
    if blocking_reason is not None and (
        type(blocking_reason) is not str or blocking_reason not in _BLOCKING_REASONS
    ):
        raise UpdateBrokerStateError("persisted update blocking reason is invalid")
    if phase in {UpdateBrokerPhase.RETRY_WAIT, UpdateBrokerPhase.FAULTED}:
        if blocking_reason is None:
            raise UpdateBrokerStateError("persisted blocked phase lacks a reason")
    elif blocking_reason is not None:
        raise UpdateBrokerStateError("persisted unblocked phase contains a reason")

    target_release_id = _stored_optional_release_id(
        payload["target_release_id"], "target release ID"
    )
    last_verified_release_id = _stored_optional_release_id(
        payload["last_verified_release_id"], "last verified release ID"
    )
    phase_started_at = _stored_time(payload["phase_started_at"], "phase start")
    deadline_at = _stored_optional_time(payload["deadline_at"], "phase deadline")
    next_attempt_at = _stored_optional_time(
        payload["next_attempt_at"], "next attempt"
    )
    if phase in {UpdateBrokerPhase.CHECKING, UpdateBrokerPhase.STAGED}:
        if deadline_at is None:
            raise UpdateBrokerStateError("persisted bounded phase lacks a deadline")
    if phase is UpdateBrokerPhase.RETRY_WAIT:
        if deadline_at is None or next_attempt_at is None or deadline_at != next_attempt_at:
            raise UpdateBrokerStateError("persisted retry deadline is invalid")
    elif phase is not UpdateBrokerPhase.STAGED and next_attempt_at is not None:
        raise UpdateBrokerStateError("persisted phase has an invalid next-attempt time")
    if phase is UpdateBrokerPhase.STAGED and (
        target_release_id is None
        or last_verified_release_id is None
        or target_release_id != last_verified_release_id
        or next_attempt_at is None
    ):
        raise UpdateBrokerStateError("persisted staged status is incoherent")

    return _DurableProjection(
        phase=phase,
        attempt=attempt,
        target_release_id=target_release_id,
        last_verified_release_id=last_verified_release_id,
        blocking_reason=blocking_reason,
        phase_started_at=phase_started_at,
        deadline_at=deadline_at,
        next_attempt_at=next_attempt_at,
        event_generation=generation,
        event_sequence=sequence,
    )


def _stored_int(value: JsonValue, context: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum or value > _MAX_ATTEMPT:
        raise UpdateBrokerStateError(f"persisted {context} is invalid")
    return value


def _stored_release_id(value: JsonValue, context: str) -> str:
    if type(value) is not str or _RELEASE_ID_PATTERN.fullmatch(value) is None:
        raise UpdateBrokerStateError(f"persisted {context} is invalid")
    return value


def _stored_optional_release_id(value: JsonValue, context: str) -> str | None:
    if value is None:
        return None
    return _stored_release_id(value, context)


def _stored_time(value: JsonValue, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UpdateBrokerStateError(f"persisted {context} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise UpdateBrokerStateError(f"persisted {context} is invalid")
    return result


def _stored_optional_time(value: JsonValue, context: str) -> float | None:
    if value is None:
        return None
    return _stored_time(value, context)


__all__ = [
    "UpdateBroker",
    "UpdateBrokerError",
    "UpdateBrokerHandle",
    "UpdateBrokerJoinTimeout",
    "UpdateBrokerLifecycleError",
    "UpdateBrokerPhase",
    "UpdateBrokerRole",
    "UpdateBrokerRoleError",
    "UpdateBrokerStateError",
    "UpdateBrokerStatus",
]
