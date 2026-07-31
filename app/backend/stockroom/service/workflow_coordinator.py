"""Generation-fenced background dispatch for the durable workflow runtime.

The coordinator owns threads and polling policy only.  Workflow state,
dependency ordering, leases, retries, and handler outcomes remain authoritative
in :mod:`stockroom.workflow`.  Provider policy, publication side effects, API
mounting, and UI integration belong to later service seams.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock, Thread, current_thread

from stockroom.workflow import (
    BatchCancellationRecord,
    BatchRecord,
    DispatchRecord,
    IntakeIdentity,
    ItemRecord,
    ItemStatus,
    StageHandlerError,
    StageRecord,
    WorkflowConflict,
    WorkflowEvent,
    WorkflowRuntime,
    WorkflowStore,
)

from .control import (
    CoordinatorConflict,
    CoordinatorStatus,
    GenerationFence,
    JsonValue,
    ServiceControl,
    ServiceMode,
)

_MAX_WORKERS = 64


class WorkflowCoordinatorState(str, Enum):
    """Sanitized lifecycle states exposed to service supervision."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STALE = "stale"
    FAULTED = "faulted"


class WorkflowCoordinatorError(RuntimeError):
    """Base class for safe workflow-coordinator failures."""


class WorkflowCoordinatorLifecycleError(WorkflowCoordinatorError):
    """The one-shot coordinator was started or stopped incorrectly."""


class WorkflowCoordinatorStopTimeout(WorkflowCoordinatorError):
    """The coordinator did not finish its in-flight bounded work in time."""


@dataclass(frozen=True, slots=True)
class WorkflowCoordinatorStatus:
    """Payload-free operational counters suitable for a local health surface."""

    state: WorkflowCoordinatorState
    generation: int
    worker_limit: int
    in_flight: int
    peak_in_flight: int
    poll_round_count: int
    poll_count: int
    dispatch_count: int
    idle_poll_count: int
    recovered_claim_count: int
    handler_error_count: int
    lease_lost_count: int
    unexpected_error_count: int
    idle_round_count: int
    current_backoff_seconds: float
    minimum_worker_polls: int
    maximum_worker_polls: int
    started_at: float | None
    last_activity_at: float | None
    stopped_at: float | None
    last_error_code: str | None
    thread_alive: bool


class _PollOutcome(str, Enum):
    IDLE = "idle"
    DISPATCHED = "dispatched"
    HANDLER_ERROR = "handler_error"


class WorkflowCoordinator:
    """Own a bounded, fair polling pool under one durable generation fence."""

    def __init__(
        self,
        control: ServiceControl,
        fence: GenerationFence,
        store: WorkflowStore,
        runtime: WorkflowRuntime,
        *,
        worker_count: int = 4,
        lease_seconds: float = 60.0,
        minimum_idle_backoff_seconds: float = 0.01,
        maximum_idle_backoff_seconds: float = 0.5,
        idle_backoff_multiplier: float = 2.0,
    ):
        if not isinstance(control, ServiceControl):
            raise TypeError("control must be a ServiceControl")
        if control.mode is not ServiceMode.COORDINATOR:
            raise ValueError("workflow coordinator requires coordinator service mode")
        if type(fence) is not GenerationFence:
            raise TypeError("fence must be a GenerationFence")
        if not isinstance(store, WorkflowStore):
            raise TypeError("store must be a WorkflowStore")
        if not isinstance(runtime, WorkflowRuntime):
            raise TypeError("runtime must be a WorkflowRuntime")
        if getattr(runtime, "_store", None) is not store:
            raise ValueError("runtime and coordinator must own the same WorkflowStore")
        if type(worker_count) is not int or not 1 <= worker_count <= _MAX_WORKERS:
            raise ValueError(f"worker_count must be between 1 and {_MAX_WORKERS}")

        minimum_backoff = self._positive_finite(
            minimum_idle_backoff_seconds,
            "minimum_idle_backoff_seconds",
        )
        maximum_backoff = self._positive_finite(
            maximum_idle_backoff_seconds,
            "maximum_idle_backoff_seconds",
        )
        multiplier = self._positive_finite(
            idle_backoff_multiplier,
            "idle_backoff_multiplier",
        )
        lease_duration = self._positive_finite(lease_seconds, "lease_seconds")
        if maximum_backoff < minimum_backoff:
            raise ValueError("maximum_idle_backoff_seconds must be at least the minimum")
        if multiplier < 1.0:
            raise ValueError("idle_backoff_multiplier must be at least 1")

        self._control = control
        self._fence = fence
        self._store = store
        self._runtime = runtime
        self._worker_count = worker_count
        self._lease_seconds = lease_duration
        self._minimum_backoff = minimum_backoff
        self._maximum_backoff = maximum_backoff
        self._backoff_multiplier = multiplier

        self._lock = Lock()
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._started_once = False
        self._state = WorkflowCoordinatorState.STOPPED
        self._in_flight = 0
        self._peak_in_flight = 0
        self._poll_round_count = 0
        self._poll_count = 0
        self._dispatch_count = 0
        self._idle_poll_count = 0
        self._recovered_claim_count = 0
        self._handler_error_count = 0
        self._lease_lost_count = 0
        self._unexpected_error_count = 0
        self._idle_round_count = 0
        self._current_backoff_seconds = 0.0
        self._worker_poll_counts = [0] * worker_count
        self._started_at: float | None = None
        self._last_activity_at: float | None = None
        self._stopped_at: float | None = None
        self._last_error_code: str | None = None

    @staticmethod
    def _positive_finite(value: float, name: str) -> float:
        if type(value) not in {int, float}:
            raise TypeError(f"{name} must be a number")
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{name} must be positive and finite")
        return number

    def start(self) -> None:
        """Recover expired claims and start one background supervisor thread."""

        with self._lock:
            if self._started_once:
                raise WorkflowCoordinatorLifecycleError(
                    "workflow coordinator instances are one-shot"
                )
            self._started_once = True
            self._state = WorkflowCoordinatorState.STARTING
            self._started_at = time.time()

        try:
            self._require_active_fence()
            self._control.record_event(
                self._fence,
                "workflow_coordinator_starting",
                {"worker_limit": self._worker_count},
            )
            recovered = self._store.recover_expired_leases()
            with self._lock:
                self._recovered_claim_count = recovered
            self._require_active_fence()
            self._control.record_event(
                self._fence,
                "workflow_coordinator_started",
                {
                    "recovered_claim_count": recovered,
                    "worker_limit": self._worker_count,
                },
            )
        except CoordinatorConflict:
            self._finish_start_failure(
                WorkflowCoordinatorState.STALE,
                "stale_generation",
            )
            raise
        except BaseException:
            self._finish_start_failure(
                WorkflowCoordinatorState.FAULTED,
                "workflow_recovery_failure",
            )
            raise

        thread = Thread(
            target=self._supervise,
            name="stockroom-workflow-coordinator",
            daemon=False,
        )
        with self._lock:
            self._state = WorkflowCoordinatorState.RUNNING
            self._thread = thread
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._thread = None
            self._finish_start_failure(
                WorkflowCoordinatorState.FAULTED,
                "coordinator_thread_start_failure",
            )
            raise

    def _finish_start_failure(
        self,
        state: WorkflowCoordinatorState,
        error_code: str,
    ) -> None:
        self._stop_requested.set()
        with self._lock:
            self._state = state
            self._last_error_code = error_code
            self._stopped_at = time.time()

    def stop(self, *, timeout: float = 10.0) -> None:
        """Stop new polls and wait for already-running handlers to finish."""

        timeout_seconds = self._positive_finite(timeout, "timeout")
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            if thread is current_thread():
                raise WorkflowCoordinatorLifecycleError(
                    "workflow coordinator cannot join its own supervisor thread"
                )
            if self._state in {
                WorkflowCoordinatorState.STARTING,
                WorkflowCoordinatorState.RUNNING,
            }:
                self._state = WorkflowCoordinatorState.STOPPING
            self._stop_requested.set()

        thread.join(timeout_seconds)
        if thread.is_alive():
            raise WorkflowCoordinatorStopTimeout("workflow coordinator still has in-flight work")

    def status(self) -> WorkflowCoordinatorStatus:
        """Return counters only; no workflow IDs, payloads, owners, or errors."""

        with self._lock:
            thread = self._thread
            minimum_worker_polls = min(self._worker_poll_counts)
            maximum_worker_polls = max(self._worker_poll_counts)
            return WorkflowCoordinatorStatus(
                state=self._state,
                generation=self._fence.generation,
                worker_limit=self._worker_count,
                in_flight=self._in_flight,
                peak_in_flight=self._peak_in_flight,
                poll_round_count=self._poll_round_count,
                poll_count=self._poll_count,
                dispatch_count=self._dispatch_count,
                idle_poll_count=self._idle_poll_count,
                recovered_claim_count=self._recovered_claim_count,
                handler_error_count=self._handler_error_count,
                lease_lost_count=self._lease_lost_count,
                unexpected_error_count=self._unexpected_error_count,
                idle_round_count=self._idle_round_count,
                current_backoff_seconds=self._current_backoff_seconds,
                minimum_worker_polls=minimum_worker_polls,
                maximum_worker_polls=maximum_worker_polls,
                started_at=self._started_at,
                last_activity_at=self._last_activity_at,
                stopped_at=self._stopped_at,
                last_error_code=self._last_error_code,
                thread_alive=thread is not None and thread.is_alive(),
            )

    def get_batch(self, batch_id: str) -> BatchRecord:
        """Read one durable batch through the active service authority."""

        self._require_api_authority()
        return self._store.get_batch(batch_id)

    def submit_batch(
        self,
        identities: Sequence[IntakeIdentity],
        *,
        idempotency_key: str | None = None,
    ) -> BatchRecord:
        """Persist one intake batch only while this coordinator owns authority.

        The store owns atomicity and request idempotency.  Keeping submission
        behind the same live-generation check as workflow reads and controls
        prevents an API process from enqueueing work through a stale owner.
        """

        self._require_api_authority()
        return self._store.submit_batch(
            identities,
            idempotency_key=idempotency_key,
        )

    def list_items(self, batch_id: str) -> list[ItemRecord]:
        """Read batch items; callers must project away raw identity and payload."""

        self._require_api_authority()
        return self._store.list_items(batch_id)

    def item_status_counts(self, batch_id: str) -> dict[ItemStatus, int]:
        self._require_api_authority()
        return self._store.item_status_counts(batch_id)

    def list_stages(self, item_id: str) -> list[StageRecord]:
        """Read item stages; callers must not expose results, errors, or leases."""

        self._require_api_authority()
        return self._store.list_stages(item_id)

    def events(
        self,
        batch_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 10_000,
    ) -> list[WorkflowEvent]:
        """Replay durable events through the active service authority."""

        self._require_api_authority()
        return self._store.events(
            batch_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def latest_event_sequence(self, batch_id: str) -> int:
        self._require_api_authority()
        return self._store.latest_event_sequence(batch_id)

    def get_batch_cancellation(
        self,
        batch_id: str,
    ) -> BatchCancellationRecord | None:
        self._require_api_authority()
        return self._store.get_batch_cancellation(batch_id)

    def pause_batch(self, batch_id: str) -> BatchRecord:
        self._require_api_authority()
        return self._store.pause_batch(batch_id)

    def resume_batch(self, batch_id: str) -> BatchRecord:
        self._require_api_authority()
        return self._store.resume_batch(batch_id)

    def retry_batch(self, batch_id: str) -> BatchRecord:
        self._require_api_authority()
        return self._store.retry_batch(batch_id)

    def cancel_batch(self, batch_id: str) -> BatchRecord:
        self._require_api_authority()
        return self._store.cancel_batch(batch_id)

    def _require_api_authority(self) -> None:
        """Reject reads and controls from a stopped or stale coordinator."""

        with self._lock:
            state = self._state
            thread = self._thread
        if state is not WorkflowCoordinatorState.RUNNING or thread is None or not thread.is_alive():
            raise WorkflowCoordinatorLifecycleError(
                "workflow coordinator is not accepting API requests"
            )
        try:
            self._require_active_fence()
        except CoordinatorConflict as exc:
            # API callers understand coordinator availability failures, not
            # service-control internals.  Preserve the original conflict as
            # the cause while mapping the public seam to the established 503.
            raise WorkflowCoordinatorLifecycleError(
                "workflow coordinator generation fence is stale"
            ) from exc

    def _supervise(self) -> None:
        terminal_state = WorkflowCoordinatorState.STOPPED
        terminal_error: str | None = None
        backoff = self._minimum_backoff
        try:
            with ThreadPoolExecutor(
                max_workers=self._worker_count,
                thread_name_prefix="stockroom-workflow-worker",
            ) as executor:
                while not self._stop_requested.is_set():
                    self._require_active_fence()
                    with self._lock:
                        self._poll_round_count += 1

                    futures = [
                        executor.submit(self._poll_worker, worker_ordinal)
                        for worker_ordinal in range(self._worker_count)
                    ]
                    outcomes, failure = self._collect_round(futures)
                    if failure is not None:
                        raise failure

                    if any(outcome is not _PollOutcome.IDLE for outcome in outcomes):
                        backoff = self._minimum_backoff
                        with self._lock:
                            self._current_backoff_seconds = 0.0
                        continue

                    with self._lock:
                        self._idle_round_count += 1
                        self._current_backoff_seconds = backoff
                    self._stop_requested.wait(backoff)
                    backoff = min(
                        self._maximum_backoff,
                        backoff * self._backoff_multiplier,
                    )
        except CoordinatorConflict:
            terminal_state = WorkflowCoordinatorState.STALE
            terminal_error = "stale_generation"
        except BaseException:
            terminal_state = WorkflowCoordinatorState.FAULTED
            terminal_error = "workflow_runtime_failure"
            with self._lock:
                self._unexpected_error_count += 1
        finally:
            self._stop_requested.set()
            terminal_state, terminal_error = self._record_terminal_event(
                terminal_state,
                terminal_error,
            )
            with self._lock:
                self._state = terminal_state
                self._last_error_code = terminal_error
                self._current_backoff_seconds = 0.0
                self._stopped_at = time.time()

    @staticmethod
    def _collect_round(
        futures: list[Future[_PollOutcome]],
    ) -> tuple[list[_PollOutcome], BaseException | None]:
        outcomes: list[_PollOutcome] = []
        first_failure: BaseException | None = None
        for future in futures:
            try:
                outcomes.append(future.result())
            except BaseException as exc:
                if first_failure is None:
                    first_failure = exc
        return outcomes, first_failure

    def _poll_worker(self, worker_ordinal: int) -> _PollOutcome:
        with self._lock:
            self._poll_count += 1
            self._worker_poll_counts[worker_ordinal] += 1
            self._in_flight += 1
            self._peak_in_flight = max(self._peak_in_flight, self._in_flight)
        try:
            dispatch = self._runtime.poll_once(
                f"workflow-generation-{self._fence.generation}-worker-{worker_ordinal}",
                lease_seconds=self._lease_seconds,
            )
        except (StageHandlerError, WorkflowConflict) as exc:
            # A lost or superseded fence is ordinary contention over durable
            # state, not a runtime defect: it must never fault the coordinator
            # and take the whole dispatch loop down with it.
            with self._lock:
                if isinstance(exc, WorkflowConflict):
                    self._lease_lost_count += 1
                else:
                    self._handler_error_count += 1
                self._dispatch_count += 1
                self._last_activity_at = time.time()
            return _PollOutcome.HANDLER_ERROR
        finally:
            with self._lock:
                self._in_flight -= 1

        if dispatch is None:
            with self._lock:
                self._idle_poll_count += 1
            return _PollOutcome.IDLE
        self._record_dispatch(dispatch)
        return _PollOutcome.DISPATCHED

    def _record_dispatch(self, dispatch: DispatchRecord) -> None:
        # The dispatch object deliberately remains local; only aggregate counts
        # cross the service-status boundary.
        del dispatch
        with self._lock:
            self._dispatch_count += 1
            self._last_activity_at = time.time()

    def _require_active_fence(self) -> None:
        snapshot = self._control.snapshot()
        if (
            snapshot.mode is not ServiceMode.COORDINATOR
            or snapshot.status is not CoordinatorStatus.ACTIVE
            or snapshot.generation != self._fence.generation
            or snapshot.owner_id != self._fence.owner_id
        ):
            raise CoordinatorConflict("workflow coordinator generation fence is stale")

    def _record_terminal_event(
        self,
        state: WorkflowCoordinatorState,
        error_code: str | None,
    ) -> tuple[WorkflowCoordinatorState, str | None]:
        try:
            self._require_active_fence()
            if state is WorkflowCoordinatorState.STOPPED:
                self._control.record_event(
                    self._fence,
                    "workflow_coordinator_stopped",
                    self._terminal_counters(),
                )
            elif state is WorkflowCoordinatorState.FAULTED:
                self._control.record_event(
                    self._fence,
                    "workflow_coordinator_faulted",
                    {
                        **self._terminal_counters(),
                        "error_code": error_code,
                    },
                )
        except CoordinatorConflict:
            return WorkflowCoordinatorState.STALE, "stale_generation"
        except BaseException:
            if state is not WorkflowCoordinatorState.STALE:
                return WorkflowCoordinatorState.FAULTED, "control_event_failure"
        return state, error_code

    def _terminal_counters(self) -> dict[str, JsonValue]:
        with self._lock:
            return {
                "dispatch_count": self._dispatch_count,
                "handler_error_count": self._handler_error_count,
                "poll_count": self._poll_count,
            }


__all__ = [
    "WorkflowCoordinator",
    "WorkflowCoordinatorError",
    "WorkflowCoordinatorLifecycleError",
    "WorkflowCoordinatorState",
    "WorkflowCoordinatorStatus",
    "WorkflowCoordinatorStopTimeout",
]
