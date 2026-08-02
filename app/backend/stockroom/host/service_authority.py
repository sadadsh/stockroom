"""Live-service authority and lifecycle transfer for immutable release workers.

The stable update broker and the replaceable application service are separate
authorities.  This module owns only the application-service side: one context
is either a read-only shadow or the sole coordinator under the per-user Windows
mutex and durable ``Control.sqlite`` generation.
"""

from __future__ import annotations

import math
import queue
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from fastapi import FastAPI, Request

from stockroom.api.errors import ApiError
from stockroom.api.jobs import JobRunner
from stockroom.service import (
    CoordinatorConflict,
    CoordinatorStatus,
    GenerationFence,
    ServiceControl,
    ServiceMode,
    WindowsCurrentIdentity,
    WorkflowCoordinator,
    secure_windows_mutex_factory,
)
from stockroom.workflow import (
    PublicationLease,
    StageHandler,
    StageName,
    WorkflowRuntime,
    WorkflowStore,
)

SERVICE_CONTROL_PREFIX = "/_stockroom/service-control"
SERVICE_CONTROL_HEADER = "X-Stockroom-Service-Control"


class ServiceAuthorityError(RuntimeError):
    """The service lease could not be transferred exactly."""


class ServiceLifecycleError(ServiceAuthorityError):
    """Coordinator-owned application work could not start or reach a safe stop."""


class ServicePromotionError(ServiceAuthorityError):
    """A shadow could not become the next coordinator generation."""


class ServiceDemotionError(ServiceAuthorityError):
    """A coordinator could not stop and release its exact generation."""


class ServiceLifecyclePort(Protocol):
    """Start and stop every activity that is allowed to mutate service state."""

    def start(
        self,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> object: ...

    def stop(self, handle: object, *, timeout: float) -> None: ...


class WorkflowRegistryFactory(Protocol):
    """Build one complete registry over the exact lifecycle-owned store."""

    def __call__(
        self,
        context: Any,
        workflow_store: WorkflowStore,
    ) -> Mapping[StageName, StageHandler]: ...


@dataclass(frozen=True, slots=True)
class ServiceAuthoritySnapshot:
    release_id: str
    mode: ServiceMode
    status: CoordinatorStatus
    generation: int

    def public(self) -> dict[str, object]:
        return {
            "release_id": self.release_id,
            "service_mode": self.mode.value,
            "coordinator_status": self.status.value,
            "service_generation": self.generation,
        }


@dataclass(slots=True)
class _ContextLifecycleHandle:
    workflow_store: WorkflowStore
    workflow_registry: Mapping[StageName, StageHandler]
    coordinator: WorkflowCoordinator
    publication_worker: _PublicationWorker | None
    background_sync: _ActivityHandle
    launch_sync: _ActivityHandle
    altium_service: object | None
    altium_stop: object | None
    jobs: JobRunner | None
    generation: int
    stopped: bool = False


class _ActivityHandle(Protocol):
    """One lifecycle-owned activity with cancellation and completion proof."""

    def cancel(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def is_alive(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class _ThreadActivity:
    stop: threading.Event
    thread: threading.Thread

    def cancel(self) -> None:
        self.stop.set()

    def join(self, timeout: float | None = None) -> None:
        self.thread.join(timeout)

    def is_alive(self) -> bool:
        return self.thread.is_alive()


@dataclass(frozen=True, slots=True)
class _ExternalActivity:
    """Adapt a context hook while keeping legacy Event-shaped tests compatible."""

    handle: object

    def cancel(self) -> None:
        cancel = getattr(self.handle, "cancel", None)
        if callable(cancel):
            cancel()
            return
        set_stop = getattr(self.handle, "set", None)
        if not callable(set_stop):
            raise ServiceLifecycleError(
                "background activity has no cancellation handle"
            )
        set_stop()

    def join(self, timeout: float | None = None) -> None:
        join = getattr(self.handle, "join", None)
        if callable(join):
            join(timeout)

    def is_alive(self) -> bool:
        is_alive = getattr(self.handle, "is_alive", None)
        return bool(is_alive()) if callable(is_alive) else False


@dataclass(slots=True)
class _AuthorityCommand:
    """One operation executed by the mutex-owning authority thread."""

    operation: Callable[[], object]
    done: threading.Event = field(default_factory=threading.Event)
    result: object | None = None
    error: BaseException | None = None


class _PublicationExecutionPort(Protocol):
    def execute_publication(
        self,
        lease: PublicationLease,
        *,
        now: float | None = None,
    ) -> object: ...


class _PublicationWorker:
    """Claim and execute durable publications only under the live service fence."""

    def __init__(
        self,
        control: ServiceControl,
        fence: GenerationFence,
        store: WorkflowStore,
        executor: _PublicationExecutionPort,
        after_publication: Callable[[], None] | None = None,
    ) -> None:
        self._control = control
        self._fence = fence
        self._store = store
        self._executor = executor
        self._after_publication = after_publication
        self._refresh_pending = False
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"stockroom-publication-worker-{fence.generation}",
            daemon=False,
        )

    def start(self) -> None:
        self._require_active_fence()
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread.ident is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self, *, timeout: float) -> None:
        timeout_seconds = _positive_finite(timeout, "timeout")
        self.request_stop()
        self._thread.join(timeout_seconds)
        if self._thread.is_alive():
            raise ServiceLifecycleError(
                "publication worker did not stop before service transfer"
            )

    def _require_active_fence(self) -> None:
        snapshot = self._control.snapshot()
        if (
            snapshot.status is not CoordinatorStatus.ACTIVE
            or snapshot.generation != self._fence.generation
            or snapshot.owner_id != self._fence.owner_id
        ):
            raise CoordinatorConflict("publication worker generation fence is stale")

    def _run(self) -> None:
        worker_id = f"publication-generation-{self._fence.generation}"
        while not self._stop.is_set():
            try:
                self._require_active_fence()
                if self._refresh_pending and self._after_publication is not None:
                    self._after_publication()
                    self._refresh_pending = False
                leases = self._store.claim_publications(
                    worker_id,
                    lease_seconds=60.0,
                    limit=1,
                )
                if not leases:
                    self._stop.wait(0.1)
                    continue
                # A claimed lease is always reconciled once, even if shutdown
                # begins immediately after its durable claim. Demotion waits for
                # this call and refuses to release the service fence on timeout.
                self._executor.execute_publication(leases[0])
                # Publication mutates canonical files and completes durably inside the
                # executor. Refresh the process-local derived index before claiming more
                # work; retain a pending flag so a transient refresh error is retried instead
                # of leaving the running UI stale until restart.
                self._refresh_pending = self._after_publication is not None
                if self._refresh_pending:
                    assert self._after_publication is not None
                    self._after_publication()
                    self._refresh_pending = False
            except CoordinatorConflict:
                return
            except BaseException:
                # The durable lease expires and is reclaimed. Never busy-loop a
                # failing publication or invent success outside the publisher.
                self._stop.wait(0.25)


def _positive_finite(value: float, name: str) -> float:
    if type(value) not in {int, float}:
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def _complete_handler_registry(
    handlers: Mapping[StageName, StageHandler],
) -> dict[StageName, StageHandler]:
    if not isinstance(handlers, Mapping):
        raise ServiceLifecycleError("workflow handlers are unavailable")
    normalized: dict[StageName, StageHandler] = {}
    for raw_name, handler in handlers.items():
        try:
            name = StageName(raw_name)
        except ValueError as exc:
            raise ServiceLifecycleError(
                "workflow handler registry contains an unknown stage"
            ) from exc
        if not callable(handler):
            raise ServiceLifecycleError(
                f"workflow handler for {name.value} is not callable"
            )
        normalized[name] = handler
    missing = set(StageName) - set(normalized)
    if missing:
        raise ServiceLifecycleError(
            "workflow handler registry is incomplete: "
            + ", ".join(sorted(stage.value for stage in missing))
        )
    return normalized


class ContextServiceLifecycle:
    """Mount real workflow authority plus automatic sync/EDA background owners."""

    def __init__(
        self,
        context: object,
        *,
        workflow_database: Path,
        workflow_registry_factory: WorkflowRegistryFactory,
        enable_altium: bool,
        require_publication_executor: bool = False,
    ) -> None:
        if not callable(workflow_registry_factory):
            raise TypeError("workflow_registry_factory must be callable")
        self._context = context
        self._workflow_database = Path(workflow_database).resolve()
        # Construction is deliberately descriptive only. WorkflowStore creates
        # and migrates SQLite, while the production registry creates staging and
        # activation directories. A managed shadow must do neither. Both are
        # materialized in start(), after the exact coordinator fence is held.
        self._workflow_registry_factory = workflow_registry_factory
        self._require_publication_executor = bool(require_publication_executor)
        self._enable_altium = bool(enable_altium)
        self._lock = threading.Lock()
        self._active_handle: _ContextLifecycleHandle | None = None
        jobs = getattr(context, "jobs", None)
        self._jobs = jobs if isinstance(jobs, JobRunner) else None
        if self._jobs is not None:
            # A managed shadow is never allowed to accept work merely because
            # its object graph exists. The exact acquired generation opens it.
            self._jobs.require_managed_generation()

    @staticmethod
    def _require_active_fence(
        control: ServiceControl,
        fence: GenerationFence,
    ) -> None:
        snapshot = control.snapshot()
        if (
            control.mode is not ServiceMode.COORDINATOR
            or snapshot.status is not CoordinatorStatus.ACTIVE
            or snapshot.generation != fence.generation
            or snapshot.owner_id != fence.owner_id
        ):
            raise CoordinatorConflict("service lifecycle generation fence is stale")

    def _reconcile_managed_context(
        self,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> None:
        self._require_active_fence(control, fence)
        reconcile = getattr(self._context, "reconcile_managed_boot", None)
        if callable(reconcile):
            reconcile()
        self._require_active_fence(control, fence)

    def _new_altium_service(self) -> object | None:
        if not self._enable_altium:
            return None
        from stockroom.altium.convergence import AltiumLibraryConvergenceService

        context = self._context

        def target() -> Path | None:
            profile = getattr(context, "profile", None)
            if profile is None:
                return None
            return Path(profile.root) / "altium" / "Stockroom.DbLib"

        def record(result: object) -> None:
            setattr(context, "last_altium_convergence", result)

        return AltiumLibraryConvergenceService(target, result_sink=record)

    @staticmethod
    def _activity(handle: object) -> _ActivityHandle:
        return _ExternalActivity(handle)

    def _start_launch_sync(self, generation: int) -> _ActivityHandle:
        stop = threading.Event()
        sync = getattr(self._context, "sync_on_launch")

        def run() -> None:
            if not stop.is_set():
                sync()

        thread = threading.Thread(
            target=run,
            name=f"stockroom-launch-sync-{generation}",
            daemon=False,
        )
        thread.start()
        return _ThreadActivity(stop, thread)

    @staticmethod
    def _signal_altium_stop(altium_stop: object | None) -> None:
        if altium_stop is None:
            return
        cancel = getattr(altium_stop, "cancel", None)
        if callable(cancel):
            cancel()
            return
        set_stop = getattr(altium_stop, "set", None)
        if callable(set_stop):
            set_stop()

    def _quiesce_failed_start(
        self,
        *,
        coordinator: WorkflowCoordinator,
        publication_worker: _PublicationWorker | None,
        background_sync: _ActivityHandle | None,
        launch_sync: _ActivityHandle | None,
        altium_service: object | None,
        altium_stop: object | None,
        jobs_activated: bool,
        generation: int,
    ) -> None:
        """Do not return a failed promotion while any candidate writer remains.

        Authority releases the candidate fence when ``start`` raises. This cleanup
        is therefore deliberately unbounded: liveness may fail, but two release
        generations can never overlap. Normal demotion remains deadline-bounded
        and retains the old fence when its proof cannot complete.
        """

        if background_sync is not None:
            background_sync.cancel()
        if launch_sync is not None:
            launch_sync.cancel()
        self._signal_altium_stop(altium_stop)
        if publication_worker is not None:
            publication_worker.request_stop()
        if jobs_activated and self._jobs is not None:
            self._jobs.begin_generation_quiescence(generation)

        # Signal and join the coordinator. Its bounded API is retried because a
        # handler may still be returning from a safe cooperative boundary.
        while coordinator.status().thread_alive:
            try:
                coordinator.stop(timeout=10.0)
            except BaseException:
                continue
        if publication_worker is not None:
            publication_worker.join()
        if altium_service is not None:
            altium_thread = getattr(altium_service, "_thread", None)
            if isinstance(altium_thread, threading.Thread):
                if altium_thread.ident is not None:
                    altium_thread.join()
            else:
                stop_altium = getattr(altium_service, "stop", None)
                if callable(stop_altium):
                    stop_altium(timeout=10.0)
        if background_sync is not None:
            background_sync.join()
        if launch_sync is not None:
            launch_sync.join()
        if jobs_activated and self._jobs is not None:
            self._jobs.await_generation_quiescence(generation, timeout=None)

    def start(
        self,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> _ContextLifecycleHandle:
        with self._lock:
            if self._active_handle is not None:
                raise ServiceLifecycleError("service lifecycle is already active")

        self._reconcile_managed_context(control, fence)
        store = WorkflowStore(self._workflow_database)
        workflow_registry = self._workflow_registry_factory(
            self._context,
            store,
        )
        _complete_handler_registry(workflow_registry)
        publication_executor = getattr(
            workflow_registry,
            "execute_publication",
            None,
        )
        if self._require_publication_executor and not callable(publication_executor):
            raise ServiceLifecycleError(
                "production workflow publication executor is unavailable"
            )
        typed_publication_executor = (
            cast(_PublicationExecutionPort, workflow_registry)
            if callable(publication_executor)
            else None
        )
        self._require_active_fence(control, fence)
        # One third of the coordinator's 60s lease, so an assisted capture that
        # legitimately holds a browser window open for minutes keeps its lease
        # across two missed beats instead of being recovered and re-dispatched.
        runtime = WorkflowRuntime(
            store,
            workflow_registry,
            heartbeat_seconds=20.0,
        )
        coordinator = WorkflowCoordinator(control, fence, store, runtime)
        background_sync: _ActivityHandle | None = None
        launch_sync: _ActivityHandle | None = None
        publication_worker: _PublicationWorker | None = None
        altium_service = None
        altium_stop = None
        jobs_activated = False
        try:
            coordinator.start()
            setattr(self._context, "workflow_coordinator", coordinator)
            if typed_publication_executor is not None:
                rebuild_index = getattr(self._context, "rebuild_index", None)
                publication_worker = _PublicationWorker(
                    control,
                    fence,
                    store,
                    typed_publication_executor,
                    rebuild_index if callable(rebuild_index) else None,
                )
                publication_worker.start()

            altium_service = self._new_altium_service()
            if altium_service is not None:
                altium_stop = getattr(altium_service, "start")()

            if self._jobs is not None:
                self._jobs.activate_generation(fence.generation)
                jobs_activated = True

            background_sync = self._activity(
                getattr(
                    self._context,
                    "start_background_sync",
                )()
            )
            # Launch reconciliation is deliberately last. Once this thread is
            # reachable, no later startup operation can fail without first
            # cancelling and joining it.
            launch_sync = self._start_launch_sync(fence.generation)
        except BaseException:
            self._quiesce_failed_start(
                coordinator=coordinator,
                publication_worker=publication_worker,
                background_sync=background_sync,
                launch_sync=launch_sync,
                altium_service=altium_service,
                altium_stop=altium_stop,
                jobs_activated=jobs_activated,
                generation=fence.generation,
            )
            setattr(self._context, "workflow_coordinator", None)
            raise

        if background_sync is None or launch_sync is None:
            raise ServiceLifecycleError(
                "service background activities did not start"
            )
        handle = _ContextLifecycleHandle(
            workflow_store=store,
            workflow_registry=workflow_registry,
            coordinator=coordinator,
            publication_worker=publication_worker,
            background_sync=background_sync,
            launch_sync=launch_sync,
            altium_service=altium_service,
            altium_stop=altium_stop,
            jobs=self._jobs,
            generation=fence.generation,
        )
        with self._lock:
            if self._active_handle is not None:
                # This cannot happen without an internal lifecycle bug. Keep the
                # candidate fence safe by quiescing the just-started handle before
                # surfacing it.
                self._quiesce_failed_start(
                    coordinator=coordinator,
                    publication_worker=publication_worker,
                    background_sync=background_sync,
                    launch_sync=launch_sync,
                    altium_service=altium_service,
                    altium_stop=altium_stop,
                    jobs_activated=jobs_activated,
                    generation=fence.generation,
                )
                raise ServiceLifecycleError(
                    "service lifecycle was activated concurrently"
                )
            self._active_handle = handle
        return handle

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.001, deadline - time.monotonic())

    @staticmethod
    def _join_activity(
        activity: _ActivityHandle,
        *,
        deadline: float,
        label: str,
    ) -> None:
        activity.join(max(0.0, deadline - time.monotonic()))
        if activity.is_alive():
            raise ServiceLifecycleError(
                f"{label} did not stop before service transfer"
            )

    def stop(self, handle: object, *, timeout: float) -> None:
        timeout_seconds = _positive_finite(timeout, "timeout")
        if type(handle) is not _ContextLifecycleHandle:
            raise ServiceLifecycleError("service lifecycle handle is invalid")
        with self._lock:
            if handle.stopped:
                return
            if self._active_handle is not handle:
                raise ServiceLifecycleError("service lifecycle handle is stale")

        deadline = time.monotonic() + timeout_seconds
        errors: list[BaseException] = []

        def attempt(operation: Callable[[], None]) -> None:
            try:
                operation()
            except BaseException as exc:
                errors.append(exc)

        # Phase one closes every admission gate and signals every activity before
        # waiting on any one of them. A slow coordinator cannot leave sync or jobs
        # accepting work for the rest of the deadline.
        attempt(handle.background_sync.cancel)
        attempt(handle.launch_sync.cancel)
        self._signal_altium_stop(handle.altium_stop)
        if handle.publication_worker is not None:
            handle.publication_worker.request_stop()
        jobs = handle.jobs
        if jobs is not None:
            attempt(
                lambda: jobs.begin_generation_quiescence(handle.generation)
            )

        if handle.altium_service is not None:
            attempt(
                lambda: getattr(handle.altium_service, "stop")(
                    timeout=self._remaining(deadline)
                )
            )
            altium_thread = getattr(handle.altium_service, "_thread", None)
            if (
                isinstance(altium_thread, threading.Thread)
                and altium_thread.is_alive()
            ):
                errors.append(
                    ServiceLifecycleError(
                        "Altium convergence did not stop before service transfer"
                    )
                )

        attempt(
            lambda: handle.coordinator.stop(
                timeout=self._remaining(deadline)
            )
        )
        publication_worker = handle.publication_worker
        if publication_worker is not None:
            attempt(
                lambda: publication_worker.stop(
                    timeout=self._remaining(deadline)
                )
            )
        attempt(
            lambda: self._join_activity(
                handle.background_sync,
                deadline=deadline,
                label="background reconciliation",
            )
        )
        attempt(
            lambda: self._join_activity(
                handle.launch_sync,
                deadline=deadline,
                label="launch reconciliation",
            )
        )
        if jobs is not None:
            attempt(
                lambda: jobs.await_generation_quiescence(
                    handle.generation,
                    timeout=self._remaining(deadline),
                )
            )

        if errors:
            raise ServiceLifecycleError(
                "service lifecycle did not quiesce before transfer"
            ) from errors[0]

        setattr(self._context, "workflow_coordinator", None)
        with self._lock:
            handle.stopped = True
            self._active_handle = None


class ContextServiceAuthority:
    """Transition one context between shadow and coordinator roles.

    A Windows mutex is owned by the thread that acquired it, not merely by the
    process. Promotion, demotion, crash recovery, and final release therefore
    run on one dedicated thread for the entire lifetime of this object. API and
    update-broker threads submit bounded commands to that owner.
    """

    def __init__(
        self,
        context: object,
        *,
        release_id: str,
        control_database: Path,
        lifecycle: ServiceLifecyclePort,
        start_as_coordinator: bool = False,
        transition_timeout_seconds: float = 120.0,
        shadow_factory: Callable[[], ServiceControl] | None = None,
        coordinator_factory: Callable[[], ServiceControl] | None = None,
    ) -> None:
        if not release_id:
            raise ValueError("release_id must not be empty")
        if not callable(getattr(lifecycle, "start", None)) or not callable(
            getattr(lifecycle, "stop", None)
        ):
            raise TypeError("lifecycle must implement ServiceLifecyclePort")
        self._context = context
        self._release_id = release_id
        self._database = Path(control_database).resolve()
        self._lifecycle = lifecycle
        self._transition_timeout = _positive_finite(
            transition_timeout_seconds,
            "transition_timeout_seconds",
        )
        self._shadow_factory = shadow_factory
        self._coordinator_factory = coordinator_factory
        self._lock = threading.RLock()
        self._control: ServiceControl
        self._fence: GenerationFence | None = None
        self._lifecycle_handle: object | None = None
        self._closed = False
        self._commands: queue.Queue[_AuthorityCommand | None] = queue.Queue()
        self._owner_thread = threading.Thread(
            target=self._run_owner,
            name=f"stockroom-service-authority-{release_id}",
            daemon=False,
        )
        self._owner_thread.start()
        try:
            self._dispatch(
                lambda: self._initialize_owned(
                    start_as_coordinator=start_as_coordinator
                )
            )
        except BaseException:
            self._commands.put(None)
            self._owner_thread.join(timeout=5.0)
            raise

    @property
    def database(self) -> Path:
        return self._database

    def _run_owner(self) -> None:
        while True:
            command = self._commands.get()
            if command is None:
                return
            try:
                command.result = command.operation()
            except BaseException as exc:
                command.error = exc
            finally:
                command.done.set()

    def _dispatch(self, operation: Callable[[], object]) -> object:
        if threading.current_thread() is self._owner_thread:
            return operation()
        if not self._owner_thread.is_alive():
            raise ServiceAuthorityError("service authority owner thread is unavailable")
        command = _AuthorityCommand(operation)
        self._commands.put(command)
        if not command.done.wait(self._transition_timeout + 5.0):
            raise ServiceAuthorityError("service authority transition timed out")
        if command.error is not None:
            raise command.error
        return command.result

    def _initialize_owned(self, *, start_as_coordinator: bool) -> None:
        if start_as_coordinator:
            coordinator = self._new_coordinator()
            fence: GenerationFence | None = None
            try:
                fence = coordinator.acquire()
                self._control = coordinator
                self._fence = fence
                handle = self._lifecycle.start(coordinator, fence)
            except BaseException as exc:
                if fence is not None:
                    try:
                        coordinator.release(fence)
                    except BaseException:
                        pass
                try:
                    coordinator.close()
                except BaseException:
                    pass
                if self._database.is_file():
                    self._control = self._new_shadow()
                    snapshot = self._control.snapshot()
                    self._bind(
                        mode=ServiceMode.SHADOW,
                        generation=snapshot.generation,
                        fence=None,
                    )
                if isinstance(exc, ServiceAuthorityError):
                    raise
                raise ServicePromotionError(
                    "initial service lifecycle could not start"
                ) from exc
            self._lifecycle_handle = handle
            self._bind(
                mode=ServiceMode.COORDINATOR,
                generation=fence.generation,
                fence=fence,
            )
            return
        self._control = self._new_shadow()
        snapshot = self._control.snapshot()
        self._bind(
            mode=ServiceMode.SHADOW,
            generation=snapshot.generation,
            fence=None,
        )

    def _new_shadow(self) -> ServiceControl:
        if self._shadow_factory is not None:
            control = self._shadow_factory()
            if not isinstance(control, ServiceControl):
                raise TypeError("shadow_factory returned an invalid control")
            if control.mode is not ServiceMode.SHADOW:
                raise TypeError("shadow_factory must return shadow control")
            return control
        return ServiceControl(
            self._database,
            mode=ServiceMode.SHADOW,
            identity=WindowsCurrentIdentity(),
        )

    def _new_coordinator(self) -> ServiceControl:
        if self._coordinator_factory is not None:
            control = self._coordinator_factory()
            if not isinstance(control, ServiceControl):
                raise TypeError("coordinator_factory returned an invalid control")
            if control.mode is not ServiceMode.COORDINATOR:
                raise TypeError("coordinator_factory must return coordinator control")
            return control
        return ServiceControl(
            self._database,
            mode=ServiceMode.COORDINATOR,
            identity=WindowsCurrentIdentity(),
            mutex_factory=secure_windows_mutex_factory,
        )

    def _bind(
        self,
        *,
        mode: ServiceMode,
        generation: int,
        fence: GenerationFence | None,
    ) -> None:
        setattr(self._context, "release_id", self._release_id)
        setattr(self._context, "service_generation", generation)
        setattr(self._context, "service_mode", mode.value)
        setattr(self._context, "service_control", self._control)
        setattr(self._context, "service_fence", fence)
        setattr(self._context, "service_authority_required", True)
        setattr(self._context, "service_degraded_reason", "")

    def _clear_authority(self) -> None:
        setattr(self._context, "service_fence", None)
        setattr(self._context, "service_mode", ServiceMode.SHADOW.value)

    def snapshot(self) -> ServiceAuthoritySnapshot:
        with self._lock:
            snapshot = self._control.snapshot()
            mode = (
                ServiceMode.COORDINATOR
                if self._fence is not None
                else ServiceMode.SHADOW
            )
            return ServiceAuthoritySnapshot(
                release_id=self._release_id,
                mode=mode,
                status=snapshot.status,
                generation=snapshot.generation,
            )

    def _promote_owned(
        self,
        *,
        expected_generation: int,
    ) -> ServiceAuthoritySnapshot:
        with self._lock:
            if self._closed:
                raise ServicePromotionError("service authority is closed")
            if self._fence is not None:
                current = self.snapshot()
                if (
                    current.status is CoordinatorStatus.ACTIVE
                    and current.generation == expected_generation
                    and getattr(self._context, "service_fence", None)
                    == self._fence
                ):
                    return current
                raise ServicePromotionError(
                    "service generation is already active or quiescing"
                )
            shadow_snapshot = self._control.snapshot()
            if (
                shadow_snapshot.status
                not in {CoordinatorStatus.RELEASED, CoordinatorStatus.ACTIVE}
                or shadow_snapshot.generation != expected_generation
            ):
                raise ServicePromotionError(
                    "service promotion does not follow the observed generation"
                )

            coordinator = self._new_coordinator()
            fence: GenerationFence | None = None
            try:
                fence = coordinator.acquire()
                if fence.generation != expected_generation + 1:
                    raise ServicePromotionError(
                        "service promotion did not acquire the next generation"
                    )
                self._control = coordinator
                self._fence = fence
                handle = self._lifecycle.start(coordinator, fence)
            except BaseException as exc:
                if fence is not None:
                    try:
                        coordinator.release(fence)
                    except BaseException:
                        pass
                try:
                    coordinator.close()
                except BaseException:
                    pass
                self._control = self._new_shadow()
                self._fence = None
                self._lifecycle_handle = None
                snapshot = self._control.snapshot()
                self._bind(
                    mode=ServiceMode.SHADOW,
                    generation=snapshot.generation,
                    fence=None,
                )
                if isinstance(exc, ServiceAuthorityError):
                    raise
                raise ServicePromotionError(
                    "service lifecycle failed during promotion"
                ) from exc
            self._lifecycle_handle = handle
            self._bind(
                mode=ServiceMode.COORDINATOR,
                generation=fence.generation,
                fence=fence,
            )
            return self.snapshot()

    def promote(self, *, expected_generation: int) -> ServiceAuthoritySnapshot:
        if type(expected_generation) is not int or expected_generation < 0:
            raise ServicePromotionError("expected service generation is invalid")
        result = self._dispatch(
            lambda: self._promote_owned(expected_generation=expected_generation)
        )
        if not isinstance(result, ServiceAuthoritySnapshot):
            raise ServicePromotionError("service promotion result is invalid")
        return result

    def _demote_owned(
        self,
        *,
        expected_generation: int,
    ) -> ServiceAuthoritySnapshot:
        with self._lock:
            if self._closed:
                raise ServiceDemotionError("service authority is closed")
            fence = self._fence
            if fence is None or fence.generation != expected_generation:
                raise ServiceDemotionError("service demotion generation is stale")
            handle = self._lifecycle_handle
            if handle is None:
                raise ServiceDemotionError("service lifecycle handle is missing")
            try:
                # Reject new mutation requests before waiting for current
                # lifecycle work to quiesce. The exact ServiceControl fence
                # remains live until stop succeeds and the durable CAS releases.
                setattr(self._context, "service_fence", None)
                self._lifecycle.stop(
                    handle,
                    timeout=self._transition_timeout,
                )
                coordinator = self._control
                coordinator.release(fence)
                coordinator.close()
            except BaseException as exc:
                raise ServiceDemotionError(
                    "service did not reach a released checkpoint"
                ) from exc
            self._fence = None
            self._lifecycle_handle = None
            self._control = self._new_shadow()
            snapshot = self._control.snapshot()
            self._bind(
                mode=ServiceMode.SHADOW,
                generation=snapshot.generation,
                fence=None,
            )
            return self.snapshot()

    def demote(self, *, expected_generation: int) -> ServiceAuthoritySnapshot:
        if type(expected_generation) is not int or expected_generation <= 0:
            raise ServiceDemotionError("expected service generation is invalid")
        result = self._dispatch(
            lambda: self._demote_owned(expected_generation=expected_generation)
        )
        if not isinstance(result, ServiceAuthoritySnapshot):
            raise ServiceDemotionError("service demotion result is invalid")
        return result

    def _close_owned(self) -> None:
        with self._lock:
            if self._closed:
                return
            fence = self._fence
            if fence is None:
                self._closed = True
                self._clear_authority()
                return
            handle = self._lifecycle_handle
            if handle is None:
                raise ServiceDemotionError("service lifecycle handle is missing")
            setattr(self._context, "service_fence", None)
            self._lifecycle.stop(handle, timeout=self._transition_timeout)
            coordinator = self._control
            coordinator.release(fence)
            coordinator.close()
            self._fence = None
            self._lifecycle_handle = None
            self._closed = True
            self._clear_authority()

    def close(self) -> None:
        with self._lock:
            if self._closed and not self._owner_thread.is_alive():
                return
        self._dispatch(self._close_owned)
        self._commands.put(None)
        self._owner_thread.join(timeout=5.0)
        if self._owner_thread.is_alive():
            raise ServiceAuthorityError(
                "service authority owner thread did not stop"
            )

    def _recover_released_state_owned(self) -> None:
        """Fence a dead external coordinator and leave the database released.

        This is a shutdown-only recovery path. The caller must first prove the
        external worker is dead; a healthy owner keeps the named mutex busy and
        this method fails without changing durable state.
        """

        with self._lock:
            if self._fence is not None:
                raise ServiceDemotionError(
                    "owned service authority must use normal close"
                )
            snapshot = self._control.snapshot()
            if snapshot.status is CoordinatorStatus.RELEASED:
                return
            coordinator = self._new_coordinator()
            try:
                fence = coordinator.acquire()
                coordinator.release(fence)
                coordinator.close()
            except BaseException as exc:
                raise ServiceDemotionError(
                    "dead service authority could not be recovered"
                ) from exc
            self._control = self._new_shadow()
            released = self._control.snapshot()
            self._bind(
                mode=ServiceMode.SHADOW,
                generation=released.generation,
                fence=None,
            )

    def recover_released_state(self) -> None:
        self._dispatch(self._recover_released_state_owned)


def has_service_mutation_authority(context: object) -> bool:
    """Return true only for the exact active fence held by this context."""

    if not bool(getattr(context, "service_authority_required", False)):
        return True
    control = getattr(context, "service_control", None)
    fence = getattr(context, "service_fence", None)
    if not isinstance(control, ServiceControl) or type(fence) is not GenerationFence:
        return False
    try:
        snapshot = control.snapshot()
    except BaseException:
        return False
    return (
        control.mode is ServiceMode.COORDINATOR
        and snapshot.status is CoordinatorStatus.ACTIVE
        and snapshot.generation == fence.generation
        and snapshot.owner_id == fence.owner_id
    )


def _control_generation(document: object) -> int:
    if type(document) is not dict or set(document) != {"expected_generation"}:
        raise ApiError(400, "service-control request is invalid")
    generation = document.get("expected_generation")
    if type(generation) is not int or generation < 0:
        raise ApiError(400, "expected_generation is invalid")
    return generation


def install_service_authority_routes(
    app: FastAPI,
    authority: ContextServiceAuthority,
    *,
    secret: str,
) -> None:
    """Install private loopback promotion/demotion routes on a release worker."""

    if not secret:
        raise ValueError("service-control secret must not be empty")

    def authenticate(request: Request) -> None:
        presented = request.headers.get(SERVICE_CONTROL_HEADER, "")
        if not presented or not secrets.compare_digest(presented, secret):
            raise ApiError(401, "invalid service-control credential")

    @app.post(
        f"{SERVICE_CONTROL_PREFIX}/promote",
        include_in_schema=False,
    )
    async def promote(request: Request) -> dict[str, object]:
        authenticate(request)
        generation = _control_generation(await request.json())
        return authority.promote(expected_generation=generation).public()

    @app.post(
        f"{SERVICE_CONTROL_PREFIX}/demote",
        include_in_schema=False,
    )
    async def demote(request: Request) -> dict[str, object]:
        authenticate(request)
        generation = _control_generation(await request.json())
        return authority.demote(expected_generation=generation).public()


__all__ = [
    "ContextServiceAuthority",
    "ContextServiceLifecycle",
    "SERVICE_CONTROL_HEADER",
    "SERVICE_CONTROL_PREFIX",
    "ServiceAuthorityError",
    "ServiceAuthoritySnapshot",
    "ServiceDemotionError",
    "ServiceLifecycleError",
    "ServiceLifecyclePort",
    "ServicePromotionError",
    "WorkflowRegistryFactory",
    "has_service_mutation_authority",
    "install_service_authority_routes",
]
