"""Production host boundary for immutable Stockroom release activation.

The update core owns trust, immutable bytes, and generation-fenced sequencing.
This module owns the effects that only the persistent Windows host can prove:
real worker lifetime, health identity, request drain, stable-origin adoption,
window reload, and exact route rollback.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from stockroom import __protocol_version__, __version__
from stockroom.host.proxy import (
    BackendAdoptionReceipt,
    BackendDrainReceipt,
    SwitchableBackendProxy,
)
from stockroom.host.service_authority import (
    SERVICE_CONTROL_HEADER,
    SERVICE_CONTROL_PREFIX,
    ContextServiceAuthority,
    ContextServiceLifecycle,
    ServiceAuthoritySnapshot,
)
from stockroom.host.windows_job import (
    WindowsProcessJob,
    WindowsProcessJobError,
    launch_in_windows_job,
)
from stockroom.service import (
    CoordinatorStatus,
    GenerationFence,
    ServiceControl,
    ServiceMode,
    WindowsCurrentIdentity,
    WindowsNamedMutexFactory,
)
from stockroom.update import (
    AcceptedRelease,
    ActiveReleaseState,
    ImmutableReleaseStore,
    ReleaseActivationPhase,
    ReleaseActivationRole,
    ReleaseActivator,
    ReleaseHealthStage,
    ReleaseStoreUninitialized,
    TrustedReleaseRepository,
    UpdateBroker,
    UpdateBrokerHandle,
    UpdateBrokerPhase,
    UpdateBrokerRole,
    VerifiedReleaseSet,
    verify_local_release_set,
)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_MAX_HEALTH_BYTES = 64 * 1024
_MISSING_CONTEXT_ATTRIBUTE = object()
PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS = 60.0


class HostReleaseBoundaryError(RuntimeError):
    """The host could not prove a release-boundary operation."""


class HostReleaseProcessError(HostReleaseBoundaryError):
    """A release worker could not be launched or stopped safely."""


class HostReleaseHealthError(HostReleaseBoundaryError):
    """A worker failed a bounded identity-aware health gate."""


class HostReleaseRouteError(HostReleaseBoundaryError):
    """The stable route could not be adopted or rolled back exactly."""


class HostReleaseCompatibilityError(HostReleaseBoundaryError):
    """A candidate cannot cross the current release's rollback window."""


class HostUpdateMode(str, Enum):
    """Cryptographically distinct production and mutable-source modes."""

    PRODUCTION = "production"
    DEVELOPMENT_SOURCE = "development_source"


class ProductionUpdateConfigurationError(HostReleaseBoundaryError):
    """The signed host payload lacks a complete production feed configuration."""


@dataclass(slots=True)
class HostBackendProcess:
    """One real windowless release worker."""

    release_id: str
    base_url: str
    process: subprocess.Popen[bytes]
    generation: int
    directory: Path
    service_generation: int
    service_mode: str
    process_job: WindowsProcessJob | None = None


@dataclass(frozen=True, slots=True)
class HostDrainReceipt:
    """The release identity paired with the proxy's exact drain proof."""

    release_id: str
    generation: int
    service_generation: int
    proxy: BackendDrainReceipt


@dataclass(frozen=True, slots=True)
class HostAdoptionReceipt:
    """Everything needed to restore the exact pre-adoption host route."""

    candidate_release_id: str
    current_release_id: str
    generation: int
    candidate_service_generation: int
    current_service_generation: int
    proxy: BackendAdoptionReceipt
    window: object | None = None


class HostWindowReplacement(Protocol):
    """Two-phase native window replacement owned by the stable host."""

    def begin(self, target_release: AcceptedRelease) -> object: ...

    def commit(self, adoption: object) -> object: ...

    def rollback(self, adoption: object) -> None: ...

    def start_initial(self, release: AcceptedRelease | None = None) -> object: ...

    def wait_until_closed(self) -> int: ...

    def close(self) -> None: ...


def _positive_finite(value: float, name: str) -> float:
    if type(value) not in {int, float}:
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _backend_command(candidate: AcceptedRelease, port: int) -> list[str]:
    backend = [
        candidate.members[member.path]
        for member in candidate.manifest.members
        if member.kind == "backend"
    ]
    if len(backend) != 1:
        raise HostReleaseProcessError("release manifest must contain exactly one backend member")
    executable = backend[0]
    suffix = executable.suffix.casefold()
    if suffix == ".exe":
        return [str(executable), "--port", str(port)]
    if suffix == ".pyz":
        runtimes = [
            candidate.members[member.path]
            for member in candidate.manifest.members
            if member.kind == "python-runtime"
        ]
        if len(runtimes) != 1 or runtimes[0].name.casefold() not in {"python.exe", "pythonw.exe"}:
            raise HostReleaseProcessError(
                "release zipapp requires one immutable Python runtime member"
            )
        return [str(runtimes[0]), str(executable), "--port", str(port)]
    if (
        suffix == ".py"
        and not bool(getattr(sys, "frozen", False))
        and (os.environ.get("STOCKROOM_UPDATE_MODE", "").strip().casefold() != "production")
    ):
        # Source-only executable seam used by integration tests and local release
        # authoring. Production never borrows the mutable host interpreter.
        return [sys.executable, str(executable), "--port", str(port)]
    raise HostReleaseProcessError("release backend member has an unsupported format")


def _numeric_version(value: str) -> tuple[int, ...]:
    if re.fullmatch(r"\d+(?:\.\d+)*", value) is None:
        raise HostReleaseCompatibilityError("release host version requirement is not canonical")
    parts = tuple(int(part) for part in value.split("."))
    # Packaged identities use Windows' four-part version form while source
    # builds historically use three parts. Compare the same semantic version
    # equally across both hosts instead of treating one trailing zero as newer.
    return parts + (0,) * max(0, 4 - len(parts))


def _strict_health_document(data: bytes) -> dict[str, object]:
    if not data or len(data) > _MAX_HEALTH_BYTES:
        raise HostReleaseHealthError("release worker health response is invalid")

    def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise HostReleaseHealthError("release worker health response is invalid") from exc
    if type(value) is not dict:
        raise HostReleaseHealthError("release worker health response is invalid")
    return value


class HostManifestRehearsal:
    """Pure compatibility rehearsal before any candidate process is launched."""

    def rehearse(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> None:
        if type(generation) is not int or generation <= 0:
            raise HostReleaseCompatibilityError("service generation is invalid")
        manifest = candidate.manifest
        prior = current.manifest
        if not manifest.supports_direct_activation_from(current.release_id):
            raise HostReleaseCompatibilityError(
                "candidate is not compatible with the current release"
            )
        if _numeric_version(manifest.minimum_host_version) > _numeric_version(__version__):
            raise HostReleaseCompatibilityError("candidate requires a newer stable host")
        if manifest.protocol_version != prior.protocol_version:
            raise HostReleaseCompatibilityError("candidate service protocol is incompatible")
        if manifest.protocol_version != __protocol_version__:
            raise HostReleaseCompatibilityError(
                "candidate service protocol is incompatible with the stable host"
            )
        if not (
            manifest.api_compatibility.minimum
            <= prior.protocol_version
            <= manifest.api_compatibility.maximum
        ):
            raise HostReleaseCompatibilityError(
                "candidate API range excludes the running host protocol"
            )
        if (
            manifest.migration.catalog.source != prior.migration.catalog.target
            or manifest.migration.control.source != prior.migration.control.target
        ):
            raise HostReleaseCompatibilityError(
                "candidate migration does not start at the active schemas"
            )
        for name, version in prior.workflow_code_versions.items():
            candidate_version = manifest.workflow_code_versions.get(name)
            if candidate_version is None or candidate_version < version:
                raise HostReleaseCompatibilityError(
                    "candidate removes an active workflow compatibility version"
                )
        # Resolve the executable contract now, without spawning it, so a bad
        # bundle fails in rehearsal rather than at the live handoff boundary.
        _backend_command(candidate, 1)

    def rehearse_rollback(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> None:
        """Prove an older signed release can safely run the current data."""

        if type(generation) is not int or generation <= 0:
            raise HostReleaseCompatibilityError("service generation is invalid")
        manifest = candidate.manifest
        active = current.manifest
        if (
            active.rollback_release_id.casefold() != candidate.release_id.casefold()
            or not active.supports_direct_activation_from(candidate.release_id)
        ):
            raise HostReleaseCompatibilityError(
                "active release does not authorize this rollback target"
            )
        if _numeric_version(manifest.minimum_host_version) > _numeric_version(__version__):
            raise HostReleaseCompatibilityError("rollback target requires a newer stable host")
        if manifest.protocol_version != active.protocol_version:
            raise HostReleaseCompatibilityError("rollback service protocol is incompatible")
        if manifest.protocol_version != __protocol_version__:
            raise HostReleaseCompatibilityError(
                "rollback service protocol is incompatible with the stable host"
            )
        if not (
            manifest.api_compatibility.minimum
            <= active.protocol_version
            <= manifest.api_compatibility.maximum
        ):
            raise HostReleaseCompatibilityError(
                "rollback API range excludes the running host protocol"
            )
        for name in ("catalog", "control"):
            active_schema = getattr(active.migration, name).target
            compatibility = getattr(manifest.schema_compatibility, name)
            if not compatibility.minimum <= active_schema <= compatibility.maximum:
                raise HostReleaseCompatibilityError(
                    "rollback target cannot read the active schemas"
                )
        for name, version in active.workflow_code_versions.items():
            rollback_version = manifest.workflow_code_versions.get(name)
            if rollback_version is None or rollback_version < version:
                raise HostReleaseCompatibilityError(
                    "rollback target cannot resume active workflow versions"
                )
        _backend_command(candidate, 1)


def _prefer_newer_packaged_release(
    store: ImmutableReleaseStore,
    active: ActiveReleaseState,
    packaged: AcceptedRelease,
    *,
    control: ServiceControl,
    fence: GenerationFence,
) -> ActiveReleaseState:
    """Adopt a newer installed package without displacing a newer downloaded release."""

    if _numeric_version(packaged.manifest.package_version) <= _numeric_version(
        active.current.manifest.package_version
    ):
        return active
    HostManifestRehearsal().rehearse(
        packaged,
        active.current,
        generation=fence.generation,
    )
    return store.select_active(
        packaged,
        previous=active.current,
        selection_reason="activate",
        control=control,
        fence=fence,
    )


class HostReleaseBoundary:
    """Concrete launch, health, drain, and adoption ports for ``ReleaseActivator``."""

    def __init__(
        self,
        proxy: SwitchableBackendProxy,
        *,
        public_base_url: str,
        token: str,
        local_release_id: str,
        reload_window: Callable[[str], None],
        window_replacement: HostWindowReplacement | None = None,
        local_service_authority: ContextServiceAuthority | None = None,
        workflow_database: Path | None = None,
        control_database: Path | None = None,
        convergence_status_path: Path | None = None,
        startup_timeout_seconds: float = 30.0,
        post_adoption_probes: int = 3,
        probe_interval_seconds: float = 0.1,
        drain_timeout_seconds: float = 120.0,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        if not isinstance(proxy, SwitchableBackendProxy):
            raise TypeError("proxy must be a SwitchableBackendProxy")
        if not public_base_url.startswith("http://127.0.0.1:"):
            raise ValueError("public_base_url must be a loopback HTTP endpoint")
        if not token:
            raise ValueError("token must not be empty")
        if not local_release_id:
            raise ValueError("local_release_id must not be empty")
        if not callable(reload_window):
            raise TypeError("reload_window must be callable")
        self._validate_window_replacement(window_replacement)
        if type(post_adoption_probes) is not int or post_adoption_probes <= 0:
            raise ValueError("post_adoption_probes must be a positive integer")

        self._proxy = proxy
        self._public_base_url = public_base_url.rstrip("/")
        self._token = token
        self._local_release_id = local_release_id
        self._reload_window = reload_window
        self._window_replacement = window_replacement
        self._local_service_authority = local_service_authority
        if local_service_authority is not None:
            service_database = local_service_authority.database
            if control_database is not None and (
                Path(control_database).resolve() != service_database
            ):
                raise ValueError("control_database must match local_service_authority")
            if workflow_database is None:
                raise ValueError("managed service handoff requires workflow_database")
            snapshot = local_service_authority.snapshot()
            if (
                snapshot.release_id != local_release_id
                or snapshot.mode is not ServiceMode.COORDINATOR
                or snapshot.status.value != "active"
            ):
                raise ValueError("local service authority must hold the active coordinator lease")
            self._control_database = service_database
            self._workflow_database = Path(workflow_database).resolve()
            self._service_control_token = secrets.token_urlsafe(32)
        else:
            self._control_database = (
                None if control_database is None else Path(control_database).resolve()
            )
            self._workflow_database = (
                None if workflow_database is None else Path(workflow_database).resolve()
            )
            self._service_control_token = ""
        self._convergence_status_path = convergence_status_path
        self._startup_timeout = _positive_finite(startup_timeout_seconds, "startup_timeout_seconds")
        self._post_adoption_probes = post_adoption_probes
        self._probe_interval = _positive_finite(probe_interval_seconds, "probe_interval_seconds")
        self._drain_timeout = _positive_finite(drain_timeout_seconds, "drain_timeout_seconds")
        self._stop_timeout = _positive_finite(stop_timeout_seconds, "stop_timeout_seconds")
        self._lock = threading.RLock()
        self._workers: dict[str, HostBackendProcess] = {}
        self._active_release_id = local_release_id
        self._closed = False

    @staticmethod
    def _validate_window_replacement(
        window_replacement: HostWindowReplacement | None,
    ) -> None:
        if window_replacement is not None and any(
            not callable(getattr(window_replacement, method, None))
            for method in (
                "begin",
                "commit",
                "rollback",
                "start_initial",
                "wait_until_closed",
                "close",
            )
        ):
            raise TypeError("window_replacement must implement the native host boundary")

    def attach_window_replacement(
        self,
        window_replacement: HostWindowReplacement,
    ) -> None:
        """Attach the native window runtime after startup route recovery.

        The durable release pointer may select a downloaded release before the
        first window exists. Startup first restores that backend route without
        pretending there is an old window to replace, then this one-time seam
        binds the selected release's initial native window.
        """

        self._validate_window_replacement(window_replacement)
        with self._lock:
            self._require_open()
            if self._window_replacement is not None:
                raise HostReleaseBoundaryError("window replacement is already attached")
            self._window_replacement = window_replacement

    @property
    def active_release_id(self) -> str:
        with self._lock:
            return self._active_release_id

    @property
    def live_process_count(self) -> int:
        with self._lock:
            return sum(worker.process.poll() is None for worker in self._workers.values())

    @property
    def live_process_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                worker.process.pid
                for worker in self._workers.values()
                if worker.process.poll() is None
            )

    @property
    def shutdown_wait_seconds(self) -> float:
        return self._startup_timeout + self._drain_timeout + 2 * self._stop_timeout + 5.0

    def _require_open(self) -> None:
        if self._closed:
            raise HostReleaseBoundaryError("release host boundary is closed")

    def _target_for(self, release_id: str) -> str | None:
        if release_id == self._local_release_id:
            return None
        worker = self._workers.get(release_id)
        if worker is None or worker.process.poll() is not None:
            raise HostReleaseProcessError("release worker is not available")
        return worker.base_url

    def _service_generation_for(self, release_id: str) -> int:
        authority = self._local_service_authority
        if authority is None:
            return 0
        if release_id == self._local_release_id:
            snapshot = authority.snapshot()
            return snapshot.generation
        worker = self._workers.get(release_id)
        if worker is None:
            raise HostReleaseProcessError("release worker is not available")
        return worker.service_generation

    def _observed_service_generation(self) -> int:
        authority = self._local_service_authority
        if authority is None:
            raise HostReleaseProcessError("managed service authority is unavailable")
        return authority.snapshot().generation

    def launch_shadow(
        self,
        candidate: AcceptedRelease,
        *,
        generation: int,
    ) -> HostBackendProcess:
        """Launch the candidate from its immutable backend member."""

        if type(generation) is not int or generation <= 0:
            raise HostReleaseProcessError("service generation is invalid")
        with self._lock:
            self._require_open()
            prior = self._workers.get(candidate.release_id)
            if prior is not None and prior.process.poll() is None:
                if prior.generation != generation:
                    raise HostReleaseProcessError("release worker belongs to another generation")
                return prior
            if prior is not None:
                self._workers.pop(candidate.release_id, None)

            port = _free_port()
            command = _backend_command(candidate, port)
            environment = os.environ.copy()
            environment["STOCKROOM_HANDOFF_TOKEN"] = self._token
            environment["STOCKROOM_PUBLIC_BASE_URL"] = self._public_base_url
            environment["STOCKROOM_RELEASE_ID"] = candidate.release_id
            service_generation = (
                self._observed_service_generation()
                if self._local_service_authority is not None
                else generation
            )
            environment["STOCKROOM_SERVICE_GENERATION"] = str(service_generation)
            environment["STOCKROOM_SERVICE_MODE"] = "shadow"
            if self._control_database is not None:
                environment["STOCKROOM_CONTROL_DATABASE"] = str(self._control_database)
            if self._local_service_authority is not None:
                assert self._workflow_database is not None
                environment["STOCKROOM_SERVICE_CONTROL_TOKEN"] = self._service_control_token
                environment["STOCKROOM_WORKFLOW_DATABASE"] = str(self._workflow_database)
            if self._convergence_status_path is not None:
                environment["STOCKROOM_CONVERGENCE_STATUS"] = str(self._convergence_status_path)
            process_job = None
            try:
                if os.name == "nt":
                    process, process_job = launch_in_windows_job(
                        command,
                        cwd=candidate.directory,
                        environment=environment,
                        creationflags=_NO_WINDOW,
                    )
                else:
                    process = subprocess.Popen(
                        command,
                        cwd=str(candidate.directory),
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=_NO_WINDOW,
                    )
            except (OSError, subprocess.SubprocessError, WindowsProcessJobError) as exc:
                raise HostReleaseProcessError("release worker could not be launched") from exc
            worker = HostBackendProcess(
                release_id=candidate.release_id,
                base_url=f"http://127.0.0.1:{port}",
                process=process,
                generation=generation,
                directory=candidate.directory,
                service_generation=service_generation,
                service_mode="shadow",
                process_job=process_job,
            )
            self._workers[candidate.release_id] = worker
            return worker

    def stop_shadow(
        self,
        launch_handle: object,
        *,
        generation: int,
    ) -> None:
        worker = self._worker(launch_handle, generation=generation)
        self._stop(worker)
        with self._lock:
            if self._workers.get(worker.release_id) is worker:
                self._workers.pop(worker.release_id, None)

    def _stop(self, worker: HostBackendProcess) -> None:
        process = worker.process
        if worker.process_job is not None:
            try:
                worker.process_job.terminate_all(timeout=self._stop_timeout)
            except WindowsProcessJobError as exc:
                raise HostReleaseProcessError(
                    "release worker process tree could not be stopped"
                ) from exc
            try:
                process.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired as exc:
                raise HostReleaseProcessError(
                    "release worker root did not stop before the deadline"
                ) from exc
            return
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                stopped = subprocess.run(
                    [
                        "taskkill.exe",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self._stop_timeout,
                    creationflags=_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                try:
                    process.kill()
                    process.wait(timeout=self._stop_timeout)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                raise HostReleaseProcessError(
                    "release worker process tree could not be stopped"
                ) from exc
            if stopped.returncode != 0:
                try:
                    process.kill()
                    process.wait(timeout=self._stop_timeout)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                raise HostReleaseProcessError("release worker process tree could not be stopped")
            try:
                process.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired as exc:
                raise HostReleaseProcessError(
                    "release worker process tree did not stop before the deadline"
                ) from exc
            return
        process.terminate()
        try:
            process.wait(timeout=self._stop_timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired as exc:
                raise HostReleaseProcessError(
                    "release worker did not stop before the deadline"
                ) from exc

    @staticmethod
    def _worker(
        launch_handle: object,
        *,
        generation: int,
    ) -> HostBackendProcess:
        if type(launch_handle) is not HostBackendProcess:
            raise HostReleaseProcessError("launch handle is invalid")
        if launch_handle.generation != generation:
            raise HostReleaseProcessError("launch handle generation is stale")
        return launch_handle

    def _probe(
        self,
        base_url: str,
        *,
        release_id: str,
        service_generation: int,
        service_mode: str,
        timeout: float,
    ) -> None:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/health",
            headers={"X-Stockroom-Token": self._token},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise HostReleaseHealthError("release worker health status is not successful")
                document = _strict_health_document(response.read(_MAX_HEALTH_BYTES + 1))
        except (OSError, urllib.error.URLError) as exc:
            raise HostReleaseHealthError("release worker health endpoint is unavailable") from exc
        if (
            document.get("status") != "ok"
            or document.get("release_id") != release_id
            or document.get("service_generation") != service_generation
            or document.get("service_mode") != service_mode
            or (
                self._control_database is not None
                and document.get("coordinator_status") != "active"
            )
        ):
            raise HostReleaseHealthError(
                "release worker health identity does not match the candidate"
            )

    def _service_transition(
        self,
        worker: HostBackendProcess,
        *,
        action: str,
        expected_generation: int,
    ) -> ServiceAuthoritySnapshot:
        authority = self._local_service_authority
        if authority is None or not self._service_control_token:
            raise HostReleaseRouteError("managed service authority is unavailable")
        if action not in {"promote", "demote"}:
            raise ValueError("service transition action is invalid")
        body = json.dumps(
            {"expected_generation": expected_generation},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        request = urllib.request.Request(
            f"{worker.base_url}{SERVICE_CONTROL_PREFIX}/{action}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                SERVICE_CONTROL_HEADER: self._service_control_token,
            },
        )
        document: dict[str, object] | None = None
        try:
            with urllib.request.urlopen(
                request,
                timeout=self._startup_timeout,
            ) as response:
                if response.status != 200:
                    raise HostReleaseRouteError(f"service {action} did not return a success status")
                document = _strict_health_document(response.read(_MAX_HEALTH_BYTES + 1))
        except (OSError, urllib.error.URLError) as exc:
            # A response can be lost after the worker committed its mutex/SQLite
            # transition. Reconcile from the durable row and direct worker
            # identity before deciding whether retrying is safe.
            observed = authority.snapshot()
            if (
                action == "demote"
                and observed.status is CoordinatorStatus.RELEASED
                and observed.generation == expected_generation
            ):
                worker.service_mode = ServiceMode.SHADOW.value
                worker.service_generation = observed.generation
                return ServiceAuthoritySnapshot(
                    release_id=worker.release_id,
                    mode=ServiceMode.SHADOW,
                    status=observed.status,
                    generation=observed.generation,
                )
            if (
                action == "promote"
                and observed.status is CoordinatorStatus.ACTIVE
                and observed.generation == expected_generation + 1
                and worker.process.poll() is None
            ):
                try:
                    self._probe(
                        worker.base_url,
                        release_id=worker.release_id,
                        service_generation=observed.generation,
                        service_mode=ServiceMode.COORDINATOR.value,
                        timeout=min(1.0, self._startup_timeout),
                    )
                except HostReleaseHealthError:
                    pass
                else:
                    worker.service_mode = ServiceMode.COORDINATOR.value
                    worker.service_generation = observed.generation
                    return ServiceAuthoritySnapshot(
                        release_id=worker.release_id,
                        mode=ServiceMode.COORDINATOR,
                        status=observed.status,
                        generation=observed.generation,
                    )
            raise HostReleaseRouteError(f"release worker service {action} failed") from exc
        assert document is not None
        expected_mode = ServiceMode.COORDINATOR if action == "promote" else ServiceMode.SHADOW
        expected_status = (
            CoordinatorStatus.ACTIVE if action == "promote" else CoordinatorStatus.RELEASED
        )
        try:
            if set(document) != {
                "coordinator_status",
                "release_id",
                "service_generation",
                "service_mode",
            }:
                raise ValueError("unexpected response fields")
            raw_generation = document["service_generation"]
            raw_release_id = document["release_id"]
            raw_mode = document["service_mode"]
            raw_status = document["coordinator_status"]
            if type(raw_generation) is not int or type(raw_release_id) is not str:
                raise ValueError("invalid response identity")
            if type(raw_mode) is not str or type(raw_status) is not str:
                raise ValueError("invalid response state")
            snapshot = ServiceAuthoritySnapshot(
                release_id=raw_release_id,
                mode=ServiceMode(raw_mode),
                status=CoordinatorStatus(raw_status),
                generation=raw_generation,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HostReleaseRouteError(
                f"release worker service {action} response is invalid"
            ) from exc
        if (
            snapshot.release_id != worker.release_id
            or snapshot.mode is not expected_mode
            or snapshot.status is not expected_status
            or (action == "promote" and snapshot.generation != expected_generation + 1)
            or (action == "demote" and snapshot.generation != expected_generation)
        ):
            raise HostReleaseRouteError(f"release worker service {action} response is incoherent")
        worker.service_mode = snapshot.mode.value
        worker.service_generation = snapshot.generation
        return snapshot

    def _demote_release(self, release_id: str) -> int:
        authority = self._local_service_authority
        if authority is None:
            return 0
        if release_id == self._local_release_id:
            current = authority.snapshot()
            demoted = authority.demote(expected_generation=current.generation)
            return demoted.generation
        worker = self._workers.get(release_id)
        if worker is None:
            raise HostReleaseProcessError("active release worker is unavailable")
        try:
            demoted = self._service_transition(
                worker,
                action="demote",
                expected_generation=worker.service_generation,
            )
            return demoted.generation
        except HostReleaseRouteError:
            # Remote demotion is only used while rejecting, rolling back, or
            # shutting down this worker. If its private control plane cannot
            # prove release, terminate it before allowing the prior release to
            # attempt abandoned/cold-crash recovery. A live ambiguous owner
            # must never coexist with a reopened route.
            self._stop(worker)
            if worker.process.poll() is None:
                raise HostReleaseProcessError("release worker remained alive after failed demotion")
            worker.service_mode = ServiceMode.SHADOW.value
            return worker.service_generation

    def _promote_release(self, release_id: str) -> int:
        authority = self._local_service_authority
        if authority is None:
            return 0
        expected = authority.snapshot().generation
        if release_id == self._local_release_id:
            promoted = authority.promote(expected_generation=expected)
            return promoted.generation
        worker = self._workers.get(release_id)
        if worker is None or worker.process.poll() is not None:
            raise HostReleaseProcessError("release worker is unavailable for promotion")
        promoted = self._service_transition(
            worker,
            action="promote",
            expected_generation=expected,
        )
        return promoted.generation

    def _release_is_authoritative(self, release_id: str) -> bool:
        authority = self._local_service_authority
        if authority is None:
            return True
        observed = authority.snapshot()
        if observed.status is not CoordinatorStatus.ACTIVE or observed.generation <= 0:
            return False
        if release_id == self._local_release_id:
            return (
                observed.mode is ServiceMode.COORDINATOR
                and observed.generation == self._service_generation_for(release_id)
            )
        worker = self._workers.get(release_id)
        return (
            worker is not None
            and worker.process.poll() is None
            and worker.service_mode == ServiceMode.COORDINATOR.value
            and worker.service_generation == observed.generation
        )

    def check(
        self,
        candidate: AcceptedRelease,
        launch_handle: object,
        *,
        stage: ReleaseHealthStage,
        generation: int,
    ) -> None:
        worker = self._worker(launch_handle, generation=generation)
        if worker.release_id != candidate.release_id:
            raise HostReleaseHealthError("release worker identity is invalid")
        probes = 1 if stage is ReleaseHealthStage.PRE_ADOPTION else self._post_adoption_probes
        deadline = time.monotonic() + self._startup_timeout
        for index in range(probes):
            while True:
                if worker.process.poll() is not None:
                    raise HostReleaseHealthError("release worker exited during its health gate")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HostReleaseHealthError(
                        "release worker did not become healthy before the deadline"
                    )
                try:
                    self._probe(
                        worker.base_url,
                        release_id=candidate.release_id,
                        service_generation=worker.service_generation,
                        service_mode=worker.service_mode,
                        timeout=min(1.0, remaining),
                    )
                    if stage is ReleaseHealthStage.POST_ADOPTION:
                        self._probe(
                            self._public_base_url,
                            release_id=candidate.release_id,
                            service_generation=worker.service_generation,
                            service_mode=worker.service_mode,
                            timeout=min(1.0, remaining),
                        )
                    break
                except HostReleaseHealthError:
                    time.sleep(min(self._probe_interval, max(0.0, remaining)))
            if index + 1 < probes:
                time.sleep(self._probe_interval)

    def drain(
        self,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> HostDrainReceipt:
        with self._lock:
            self._require_open()
            if current.release_id != self._active_release_id:
                raise HostReleaseRouteError("active host route does not match the current release")
            expected_target = self._target_for(current.release_id)
        receipt = self._proxy.drain(timeout=self._drain_timeout)
        if receipt.target != expected_target:
            self._proxy.resume(receipt)
            raise HostReleaseRouteError("drained proxy route does not match the current release")
        return HostDrainReceipt(
            release_id=current.release_id,
            generation=generation,
            service_generation=self._service_generation_for(current.release_id),
            proxy=receipt,
        )

    def resume(
        self,
        current: AcceptedRelease,
        drain_receipt: object,
        *,
        generation: int,
    ) -> None:
        if type(drain_receipt) is not HostDrainReceipt:
            raise HostReleaseRouteError("drain receipt is invalid")
        if drain_receipt.release_id != current.release_id or drain_receipt.generation != generation:
            raise HostReleaseRouteError("drain receipt generation is stale")
        if not self._release_is_authoritative(current.release_id):
            raise HostReleaseRouteError("the prior route cannot resume without service authority")
        self._proxy.resume(drain_receipt.proxy)

    def adopt(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        launch_handle: object,
        drain_receipt: object,
        *,
        generation: int,
    ) -> HostAdoptionReceipt:
        worker = self._worker(launch_handle, generation=generation)
        if type(drain_receipt) is not HostDrainReceipt:
            raise HostReleaseRouteError("drain receipt is invalid")
        if (
            worker.release_id != candidate.release_id
            or drain_receipt.release_id != current.release_id
            or drain_receipt.generation != generation
        ):
            raise HostReleaseRouteError("adoption inputs are incoherent")
        managed = self._local_service_authority is not None
        current_service_generation = drain_receipt.service_generation
        candidate_service_generation = worker.service_generation
        if managed:
            self._demote_release(current.release_id)
            try:
                candidate_service_generation = self._promote_release(candidate.release_id)
            except BaseException as promotion_error:
                try:
                    # Promotion can commit and lose its response immediately
                    # before the candidate crashes or becomes unobservable.
                    # Terminating the rejected shadow/candidate makes the
                    # kernel mutex state discriminating before prior takeover.
                    self._stop(worker)
                    self._promote_release(current.release_id)
                except BaseException as restore_error:
                    raise HostReleaseRouteError(
                        "candidate promotion failed and prior service authority "
                        "could not be restored"
                    ) from restore_error
                raise HostReleaseRouteError(
                    "candidate could not acquire service authority"
                ) from promotion_error
        try:
            proxy_receipt = self._proxy.adopt_drained(
                worker.base_url,
                drain_receipt.proxy,
            )
        except BaseException as adoption_error:
            if managed:
                try:
                    self._demote_release(candidate.release_id)
                    self._promote_release(current.release_id)
                except BaseException as restore_error:
                    raise HostReleaseRouteError(
                        "route adoption failed and prior service authority could not be restored"
                    ) from restore_error
            raise HostReleaseRouteError("candidate route could not be adopted") from adoption_error
        window_receipt: object | None = None
        try:
            replacement = self._window_replacement
            if replacement is None:
                self._reload_window(self._public_base_url)
            else:
                window_receipt = replacement.begin(candidate)
        except BaseException as exc:
            try:
                rollback_drain = self._proxy.drain_adoption(
                    proxy_receipt,
                    timeout=self._drain_timeout,
                )
                if managed:
                    self._demote_release(candidate.release_id)
                    self._promote_release(current.release_id)
                self._proxy.restore_drained_adoption(
                    proxy_receipt,
                    rollback_drain,
                )
            except BaseException as rollback_error:
                raise HostReleaseRouteError(
                    "window adoption failed and the prior route/authority could not be restored"
                ) from rollback_error
            raise HostReleaseRouteError("window did not adopt the candidate route") from exc
        with self._lock:
            self._active_release_id = candidate.release_id
        return HostAdoptionReceipt(
            candidate_release_id=candidate.release_id,
            current_release_id=current.release_id,
            generation=generation,
            candidate_service_generation=candidate_service_generation,
            current_service_generation=current_service_generation,
            proxy=proxy_receipt,
            window=window_receipt,
        )

    def commit(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        adoption_receipt: object,
        *,
        generation: int,
    ) -> None:
        """Validate the post-pointer host boundary before old-release retirement.

        The legacy in-process window has no separate process to retire.  The
        replacement-window adapter will use this exact post-pointer hook to
        make candidate ownership durable and then retire the hidden old host.
        """

        if type(adoption_receipt) is not HostAdoptionReceipt:
            raise HostReleaseRouteError("adoption receipt is invalid")
        if (
            adoption_receipt.candidate_release_id != candidate.release_id
            or adoption_receipt.current_release_id != current.release_id
            or adoption_receipt.generation != generation
        ):
            raise HostReleaseRouteError("adoption receipt generation is stale")
        with self._lock:
            if self._active_release_id != candidate.release_id:
                raise HostReleaseRouteError(
                    "active host route does not match the committed release"
                )
        replacement = self._window_replacement
        if replacement is not None:
            if adoption_receipt.window is None:
                raise HostReleaseRouteError(
                    "window adoption receipt is missing from the committed release"
                )
            try:
                replacement.commit(adoption_receipt.window)
            except BaseException as exc:
                raise HostReleaseRouteError(
                    "replacement window could not commit after the release pointer"
                ) from exc
        elif adoption_receipt.window is not None:
            raise HostReleaseRouteError("unexpected window adoption receipt")

    def rollback(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        adoption_receipt: object,
        *,
        generation: int,
    ) -> None:
        if type(adoption_receipt) is not HostAdoptionReceipt:
            raise HostReleaseRouteError("adoption receipt is invalid")
        if (
            adoption_receipt.candidate_release_id != candidate.release_id
            or adoption_receipt.current_release_id != current.release_id
            or adoption_receipt.generation != generation
        ):
            raise HostReleaseRouteError("adoption receipt generation is stale")
        rollback_drain = self._proxy.drain_adoption(
            adoption_receipt.proxy,
            timeout=self._drain_timeout,
        )
        if self._local_service_authority is not None:
            try:
                self._demote_release(candidate.release_id)
                self._promote_release(current.release_id)
            except BaseException as exc:
                raise HostReleaseRouteError(
                    "candidate rollback could not restore prior service authority"
                ) from exc
        self._proxy.restore_drained_adoption(
            adoption_receipt.proxy,
            rollback_drain,
        )
        replacement = self._window_replacement
        if replacement is None:
            self._reload_window(self._public_base_url)
        else:
            if adoption_receipt.window is None:
                raise HostReleaseRouteError(
                    "window adoption receipt is missing from rollback"
                )
            try:
                replacement.rollback(adoption_receipt.window)
            except BaseException as exc:
                raise HostReleaseRouteError(
                    "replacement window rollback could not restore the old host"
                ) from exc
        with self._lock:
            self._active_release_id = current.release_id

    def close(self) -> None:
        """Stop every child this host launched; never leave a release worker behind."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = list(self._workers.values())
            self._workers.clear()
            active_release_id = self._active_release_id
        first_error: BaseException | None = None
        replacement = self._window_replacement
        if replacement is not None:
            try:
                replacement.close()
            except BaseException as exc:
                first_error = first_error or exc
        authority = self._local_service_authority
        if authority is not None:
            if active_release_id == self._local_release_id:
                try:
                    authority.close()
                except BaseException as exc:
                    first_error = first_error or exc
            else:
                active_worker = next(
                    (worker for worker in workers if worker.release_id == active_release_id),
                    None,
                )
                try:
                    if active_worker is None:
                        raise HostReleaseProcessError(
                            "active release worker is missing during shutdown"
                        )
                    self._service_transition(
                        active_worker,
                        action="demote",
                        expected_generation=active_worker.service_generation,
                    )
                except BaseException as exc:
                    first_error = first_error or exc
                    if active_worker is not None:
                        try:
                            self._stop(active_worker)
                        except BaseException as stop_error:
                            first_error = first_error or stop_error
                    try:
                        authority.recover_released_state()
                    except BaseException as recovery_error:
                        first_error = first_error or recovery_error
                try:
                    authority.close()
                except BaseException as exc:
                    first_error = first_error or exc
        for worker in workers:
            try:
                self._stop(worker)
            except BaseException as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    def retain(self, release_ids: set[str]) -> None:
        """Stop workers outside the active release and its one rollback target."""

        with self._lock:
            obsolete = [
                worker
                for release_id, worker in self._workers.items()
                if release_id not in release_ids
            ]
        for worker in obsolete:
            self._stop(worker)
            with self._lock:
                if self._workers.get(worker.release_id) is worker:
                    self._workers.pop(worker.release_id, None)


class ProductionUpdateRuntime:
    """Join the TUF broker to generation-fenced host activation."""

    _ACTIVE_PHASES = frozenset(
        {
            ReleaseActivationPhase.VERIFYING,
            ReleaseActivationPhase.REHEARSING,
            ReleaseActivationPhase.LAUNCHING,
            ReleaseActivationPhase.PRE_ADOPTION_HEALTH,
            ReleaseActivationPhase.DRAINING,
            ReleaseActivationPhase.ADOPTING,
            ReleaseActivationPhase.POST_ADOPTION_HEALTH,
            ReleaseActivationPhase.COMMITTING,
            ReleaseActivationPhase.ROLLING_BACK,
        }
    )

    def __init__(
        self,
        control: ServiceControl,
        fence: GenerationFence,
        store: ImmutableReleaseStore,
        repository: TrustedReleaseRepository,
        boundary: HostReleaseBoundary,
        *,
        initial_state: ActiveReleaseState,
        status_path: Path,
        window_replacement: HostWindowReplacement | None = None,
        refresh_interval_seconds: float = PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS,
        attempt_deadline_seconds: float = 10 * 60,
        minimum_retry_backoff_seconds: float = 5.0,
        maximum_retry_backoff_seconds: float = 5 * 60,
    ) -> None:
        self._control = control
        self._fence = fence
        self._store = store
        self._boundary = boundary
        self._initial_release = initial_state.current
        self._window_replacement = window_replacement
        self._status_path = Path(status_path)
        self._refresh_interval = _positive_finite(
            refresh_interval_seconds,
            "refresh_interval_seconds",
        )
        self._current_release_id = initial_state.current.release_id
        self._previous_release_id = (
            None if initial_state.previous is None else initial_state.previous.release_id
        )
        self._condition = threading.Condition()
        self._pending: VerifiedReleaseSet | None = None
        self._stop = False
        self._started = False
        self._closed = False
        self._thread: threading.Thread | None = None
        self._broker_handle: UpdateBrokerHandle | None = None

        self._activator = ReleaseActivator(
            control,
            store,
            role=ReleaseActivationRole.COORDINATOR,
            fence=fence,
            rehearsal=HostManifestRehearsal(),
            launcher=boundary,
            health=boundary,
            drain=boundary,
            adoption=boundary,
        )
        self._broker = UpdateBroker(
            control,
            role=UpdateBrokerRole.COORDINATOR,
            repository=repository,
            fence=fence,
            verified_release_sink=self._offer_verified_release,
            refresh_interval_seconds=self._refresh_interval,
            attempt_deadline_seconds=attempt_deadline_seconds,
            minimum_retry_backoff_seconds=minimum_retry_backoff_seconds,
            maximum_retry_backoff_seconds=maximum_retry_backoff_seconds,
        )

    def _offer_verified_release(self, release: VerifiedReleaseSet) -> None:
        with self._condition:
            if self._stop:
                return
            self._pending = release
            self._condition.notify_all()

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise HostReleaseBoundaryError("production update runtime is already closed")
            if self._started:
                raise HostReleaseBoundaryError("production update runtime is already started")
            self._started = True
        replacement = self._window_replacement
        try:
            if replacement is not None:
                replacement.start_initial(self._initial_release)
        except BaseException:
            with self._condition:
                self._started = False
            raise
        with self._condition:
            thread = threading.Thread(
                target=self._activate_loop,
                name=f"stockroom-release-activation-{self._fence.generation}",
                daemon=False,
            )
            self._thread = thread
        thread.start()
        try:
            self._broker_handle = self._broker.start()
        except BaseException:
            with self._condition:
                self._stop = True
                self._condition.notify_all()
            thread.join(timeout=5.0)
            raise
        self._write_status()

    @property
    def owns_native_window(self) -> bool:
        return self._window_replacement is not None

    def wait_until_window_closed(self) -> int:
        replacement = self._window_replacement
        if replacement is None:
            raise HostReleaseBoundaryError("production native window is unavailable")
        return replacement.wait_until_closed()

    def _activate_loop(self) -> None:
        while True:
            with self._condition:
                if self._pending is None and not self._stop:
                    self._condition.wait(0.25)
                if self._stop and self._pending is None:
                    return
                release = self._pending
                self._pending = None
            self._write_status()
            if release is None:
                continue
            try:
                state = self._activator.activate(release)
            except BaseException:
                # The activator persisted a bounded blocker and proved either
                # pre-adoption recovery or explicit rollback failure.
                self._write_status()
                continue
            with self._condition:
                self._current_release_id = state.current.release_id
                self._previous_release_id = (
                    None if state.previous is None else state.previous.release_id
                )
            retained = {state.current.release_id}
            if state.previous is not None:
                retained.add(state.previous.release_id)
            self._boundary.retain(retained)
            self._write_status()

    def status(self) -> dict[str, object]:
        broker = self._broker.status()
        activation = self._activator.status()
        with self._condition:
            current = self._current_release_id
        target = (
            activation.candidate_release_id
            or broker.target_release_id
            or broker.last_verified_release_id
            or ""
        )
        blocker = activation.blocking_reason or broker.blocking_reason
        if activation.phase in self._ACTIVE_PHASES:
            phase = activation.phase.value
            state = "updating"
        elif activation.phase in {
            ReleaseActivationPhase.FAILED,
            ReleaseActivationPhase.ROLLED_BACK,
            ReleaseActivationPhase.STALE,
        }:
            phase = activation.phase.value
            state = "blocked"
        elif broker.phase is UpdateBrokerPhase.RETRY_WAIT:
            phase = broker.phase.value
            state = "offline" if blocker == "repository_offline" else "blocked"
        elif broker.phase is UpdateBrokerPhase.STAGED and target and target == current:
            phase = ReleaseActivationPhase.ACTIVE.value
            state = "up_to_date"
        elif broker.phase is UpdateBrokerPhase.CHECKING:
            phase = broker.phase.value
            state = "checking"
        elif broker.phase in {UpdateBrokerPhase.FAULTED, UpdateBrokerPhase.STALE}:
            phase = broker.phase.value
            state = "blocked"
        else:
            phase = broker.phase.value
            state = "checking"
        update_available = bool(target and target != current)
        detail = (
            f"Automatic release convergence is blocked: {blocker}."
            if blocker
            else (
                "A verified release is being adopted automatically."
                if state == "updating"
                else (
                    "The signed release repository confirms this installation is current."
                    if state == "up_to_date"
                    else "Checking the signed release repository."
                )
            )
        )
        return {
            "automatic_apply": True,
            "automatic_on_launch": True,
            "blocking_reason": blocker,
            "channel": "production",
            "check_interval_seconds": self._refresh_interval,
            "convergence_phase": phase,
            "current_release_id": current,
            "current_revision": current,
            "detail": detail,
            "generation": self._fence.generation,
            "next_attempt_at": broker.next_attempt_at,
            "retry_attempt": broker.attempt,
            "state": state,
            "target_release_id": target,
            "target_revision": target,
            "update_available": update_available,
        }

    def _write_status(self) -> None:
        try:
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".Update Status-",
                suffix=".json",
                dir=self._status_path.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(
                        self.status(),
                        stream,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._status_path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        except OSError:
            # The authenticated in-process API still exposes the same projection;
            # failure to mirror observability must not interrupt an activation.
            return

    def close(self) -> None:
        """Join broker and activation ownership, then release every child and fence."""

        with self._condition:
            if self._closed:
                return
            self._closed = True
        errors: list[BaseException] = []
        handle = self._broker_handle
        if handle is not None:
            try:
                handle.cancel()
                handle.join(timeout=15.0)
            except BaseException as exc:
                errors.append(exc)
        with self._condition:
            self._stop = True
            self._pending = None
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=self._boundary.shutdown_wait_seconds)
            if thread.is_alive():
                errors.append(
                    HostReleaseProcessError("release activation did not stop before shutdown")
                )
        try:
            self._boundary.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._control.release(self._fence)
        except BaseException as exc:
            errors.append(exc)
        else:
            try:
                self._control.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise errors[0]


class UnavailableProductionUpdateRuntime:
    """Fail-closed production observability when packaged trust inputs are absent."""

    def __init__(
        self,
        *,
        blocker: str = "production_feed_unavailable",
        release_id: str = "",
    ) -> None:
        self._blocker = blocker
        self._release_id = release_id

    def start(self) -> None:
        return

    @property
    def owns_native_window(self) -> bool:
        return False

    def wait_until_window_closed(self) -> int:
        raise HostReleaseBoundaryError("production native window is unavailable")

    def close(self) -> None:
        return

    def status(self) -> dict[str, object]:
        return {
            "automatic_apply": True,
            "automatic_on_launch": True,
            "blocking_reason": self._blocker,
            "channel": "production",
            "check_interval_seconds": PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS,
            "convergence_phase": "blocked",
            "current_release_id": self._release_id,
            "current_revision": self._release_id,
            "detail": ("Automatic signed-release convergence is unavailable in this installation."),
            "next_attempt_at": None,
            "retry_attempt": 0,
            "state": "blocked",
            "target_release_id": "",
            "target_revision": "",
            "update_available": False,
        }


def host_update_mode() -> HostUpdateMode:
    """Select production without ever allowing a frozen install to fall back to Git."""

    if bool(getattr(sys, "frozen", False)):
        return HostUpdateMode.PRODUCTION
    requested = os.environ.get("STOCKROOM_UPDATE_MODE", "").strip().casefold()
    if not requested or requested in {"development", "development_source"}:
        return HostUpdateMode.DEVELOPMENT_SOURCE
    if requested == "production":
        return HostUpdateMode.PRODUCTION
    raise ProductionUpdateConfigurationError("update mode is invalid")


def _strict_feed_descriptor(path: Path) -> dict[str, str]:
    def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ProductionUpdateConfigurationError("packaged update descriptor is invalid") from exc
    expected = {
        "current_manifest_sha256",
        "current_release_id",
        "metadata_base_url",
        "schema_version",
        "target_base_url",
    }
    if type(value) is not dict or set(value) != expected or value["schema_version"] != 1:
        raise ProductionUpdateConfigurationError("packaged update descriptor fields are invalid")
    strings: dict[str, str] = {}
    for key in expected - {"schema_version"}:
        item = value[key]
        if type(item) is not str or not item:
            raise ProductionUpdateConfigurationError(
                "packaged update descriptor values are invalid"
            )
        strings[key] = item
    return strings


def _production_bundle_root(bundle_root: Path | None = None) -> Path:
    if bundle_root is not None:
        return Path(bundle_root).resolve()
    if bool(getattr(sys, "frozen", False)):
        return Path(sys.executable).resolve().parent / "Update"
    configured = os.environ.get("STOCKROOM_UPDATE_BUNDLE_ROOT", "")
    if not configured:
        raise ProductionUpdateConfigurationError("production update bundle root is unavailable")
    return Path(configured).resolve()


def production_data_root(data_root: Path | None = None) -> Path:
    """Resolve the one shared production state root used by host and bootstrap."""

    if data_root is not None:
        return Path(data_root).resolve()
    configured = os.environ.get("STOCKROOM_UPDATE_DATA_ROOT", "")
    if configured and not bool(getattr(sys, "frozen", False)):
        return Path(configured).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        raise ProductionUpdateConfigurationError("production update data root is unavailable")
    return (Path(local_app_data) / "Stockroom").resolve()


def verified_packaged_release_identity(
    bundle_root: Path | None = None,
) -> str:
    """Return the exact built-in release only after its complete set verifies.

    The containing MSIX/EXE signature authenticates these packaged bytes.  This
    check additionally binds the descriptor digest to the strict release
    manifest and every declared immutable member before the identity is shown
    during degraded startup.
    """

    root = _production_bundle_root(bundle_root)
    descriptor = _strict_feed_descriptor(root / "Update Feed.json")
    release_id = descriptor["current_release_id"]
    verify_local_release_set(
        root / "Initial Release" / release_id,
        expected_release_id=release_id,
        expected_manifest_sha256=descriptor["current_manifest_sha256"],
    )
    return release_id


def _seed_packaged_release(
    source: Path,
    destination: Path,
    *,
    release_id: str,
    manifest_sha256: str,
) -> VerifiedReleaseSet:
    verified_source = verify_local_release_set(
        source,
        expected_release_id=release_id,
        expected_manifest_sha256=manifest_sha256,
    )
    del verified_source
    if destination.exists() or destination.is_symlink():
        return verify_local_release_set(
            destination,
            expected_release_id=release_id,
            expected_manifest_sha256=manifest_sha256,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".Packaged Release-", dir=destination.parent))
    try:
        shutil.copytree(source, temporary, dirs_exist_ok=True, symlinks=True)
        verify_local_release_set(
            temporary,
            expected_release_id=release_id,
            expected_manifest_sha256=manifest_sha256,
        )
        try:
            temporary.rename(destination)
        except FileExistsError:
            return verify_local_release_set(
                destination,
                expected_release_id=release_id,
                expected_manifest_sha256=manifest_sha256,
            )
        return verify_local_release_set(
            destination,
            expected_release_id=release_id,
            expected_manifest_sha256=manifest_sha256,
        )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _context_release_identity_restorer(context: object) -> Callable[[], None]:
    """Capture service identity before production authority binds the context."""

    attribute_names = {
        "release_id",
        "service_generation",
        "service_mode",
        "service_control",
        "service_fence",
        "service_authority_required",
        "service_degraded_reason",
        "workflow_coordinator",
    }
    prior = {name: getattr(context, name, _MISSING_CONTEXT_ATTRIBUTE) for name in attribute_names}

    def restore() -> None:
        for name, value in prior.items():
            if value is _MISSING_CONTEXT_ATTRIBUTE:
                try:
                    delattr(context, name)
                except AttributeError:
                    pass
            else:
                setattr(context, name, value)

    return restore


def create_production_update_runtime(
    proxy: SwitchableBackendProxy,
    *,
    context: object,
    public_base_url: str,
    token: str,
    reload_window: Callable[[str], None],
    manage_native_window: bool = True,
    bundle_root: Path | None = None,
    data_root: Path | None = None,
) -> ProductionUpdateRuntime:
    """Compose the production TUF/store/activator boundary from packaged inputs."""

    if type(manage_native_window) is not bool:
        raise TypeError("manage_native_window must be a boolean")
    bundle_root = _production_bundle_root(bundle_root)
    descriptor = _strict_feed_descriptor(bundle_root / "Update Feed.json")
    root_path = bundle_root / "Root.json"
    try:
        bootstrap_root = root_path.read_bytes()
    except OSError as exc:
        raise ProductionUpdateConfigurationError(
            "pinned production TUF root is unavailable"
        ) from exc

    data_root = production_data_root(data_root)
    releases_directory = data_root / "Releases"
    state_directory = data_root / "Update State"
    release_id = descriptor["current_release_id"]
    packaged = _seed_packaged_release(
        bundle_root / "Initial Release" / release_id,
        releases_directory / release_id,
        release_id=release_id,
        manifest_sha256=descriptor["current_manifest_sha256"],
    )

    from stockroom.planning.production_composition import (
        build_production_workflow_registry_for_context,
    )

    service_state_directory = data_root / "Service State"
    workflow_database = service_state_directory / "Workflow.sqlite"
    lifecycle = ContextServiceLifecycle(
        context,
        workflow_database=workflow_database,
        workflow_registry_factory=build_production_workflow_registry_for_context,
        enable_altium=True,
        require_publication_executor=True,
    )

    update_control = ServiceControl(
        state_directory / "Broker Control" / "Control.sqlite",
        mode=ServiceMode.COORDINATOR,
        identity=WindowsCurrentIdentity(),
        mutex_factory=WindowsNamedMutexFactory(purpose="UpdateBroker"),
        authority_scope="UpdateBroker",
    )
    update_fence = update_control.acquire()
    service_authority: ContextServiceAuthority | None = None
    boundary: HostReleaseBoundary | None = None
    window_replacement = None
    restore_context = _context_release_identity_restorer(context)
    try:
        store = ImmutableReleaseStore(
            releases_directory=releases_directory,
            state_directory=state_directory / "Release Store",
        )
        accepted_packaged = store.accept_verified(
            packaged,
            control=update_control,
            fence=update_fence,
        )
        try:
            active = store.verify_startup(update_control)
        except ReleaseStoreUninitialized:
            active = store.select_active(
                accepted_packaged,
                previous=None,
                selection_reason="initialize",
                control=update_control,
                fence=update_fence,
            )
        else:
            active = _prefer_newer_packaged_release(
                store,
                active,
                accepted_packaged,
                control=update_control,
                fence=update_fence,
            )

        service_authority = ContextServiceAuthority(
            context,
            release_id=release_id,
            control_database=service_state_directory / "Control.sqlite",
            lifecycle=lifecycle,
            start_as_coordinator=True,
        )
        status_path = state_directory / "Update Status.json"
        boundary = HostReleaseBoundary(
            proxy,
            public_base_url=public_base_url,
            token=token,
            local_release_id=release_id,
            reload_window=reload_window,
            local_service_authority=service_authority,
            workflow_database=workflow_database,
            convergence_status_path=status_path,
        )
        if active.current.release_id != release_id:
            handle = None
            drained = None
            adoption = None
            try:
                handle = boundary.launch_shadow(
                    active.current,
                    generation=update_fence.generation,
                )
                boundary.check(
                    active.current,
                    handle,
                    stage=ReleaseHealthStage.PRE_ADOPTION,
                    generation=update_fence.generation,
                )
                drained = boundary.drain(
                    accepted_packaged,
                    generation=update_fence.generation,
                )
                adoption = boundary.adopt(
                    active.current,
                    accepted_packaged,
                    handle,
                    drained,
                    generation=update_fence.generation,
                )
                boundary.check(
                    active.current,
                    handle,
                    stage=ReleaseHealthStage.POST_ADOPTION,
                    generation=update_fence.generation,
                )
            except BaseException:
                if adoption is not None:
                    boundary.rollback(
                        active.current,
                        accepted_packaged,
                        adoption,
                        generation=update_fence.generation,
                    )
                elif drained is not None:
                    boundary.resume(
                        accepted_packaged,
                        drained,
                        generation=update_fence.generation,
                    )
                if handle is not None:
                    boundary.stop_shadow(
                        handle,
                        generation=update_fence.generation,
                    )
                raise
        retained = {active.current.release_id}
        if active.previous is not None:
            retained.add(active.previous.release_id)
        boundary.retain(retained)

        repository = TrustedReleaseRepository(
            bootstrap_root=bootstrap_root,
            metadata_base_url=descriptor["metadata_base_url"],
            target_base_url=descriptor["target_base_url"],
            state_directory=state_directory / "TUF",
            staging_directory=releases_directory,
        )
        if manage_native_window:
            from stockroom.host.window_runtime import ProductionWindowReplacement

            config = getattr(context, "config", None)
            window_replacement = ProductionWindowReplacement(
                active.current,
                public_base_url=public_base_url,
                api_credential=token,
                config=config,
            )
            boundary.attach_window_replacement(window_replacement)
        return ProductionUpdateRuntime(
            update_control,
            update_fence,
            store,
            repository,
            boundary,
            initial_state=active,
            status_path=status_path,
            window_replacement=window_replacement,
        )
    except BaseException:
        if boundary is not None:
            try:
                boundary.close()
            except BaseException:
                pass
        elif service_authority is not None:
            try:
                service_authority.close()
            except BaseException:
                pass
        try:
            update_control.release(update_fence)
        except BaseException:
            pass
        else:
            try:
                update_control.close()
            except BaseException:
                pass
        restore_context()
        raise


__all__ = [
    "HostAdoptionReceipt",
    "HostBackendProcess",
    "HostDrainReceipt",
    "HostReleaseBoundary",
    "HostReleaseBoundaryError",
    "HostReleaseCompatibilityError",
    "HostReleaseHealthError",
    "HostManifestRehearsal",
    "HostReleaseProcessError",
    "HostReleaseRouteError",
    "HostWindowReplacement",
    "HostUpdateMode",
    "ProductionUpdateConfigurationError",
    "PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS",
    "ProductionUpdateRuntime",
    "UnavailableProductionUpdateRuntime",
    "create_production_update_runtime",
    "host_update_mode",
    "production_data_root",
    "verified_packaged_release_identity",
]
