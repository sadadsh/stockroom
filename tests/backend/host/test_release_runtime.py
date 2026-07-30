from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.global_windows_mutex

from stockroom.api.serve import pick_free_port
from stockroom.host.proxy import SwitchableBackendProxy
from stockroom.host.release_runtime import (
    HostManifestRehearsal,
    HostReleaseBoundary,
    HostReleaseBoundaryError,
    HostReleaseCompatibilityError,
    HostReleaseRouteError,
    HostUpdateMode,
    ProductionUpdateRuntime,
    _numeric_version,
    _prefer_newer_packaged_release,
    create_production_update_runtime,
    host_update_mode,
)
from stockroom.host.run import _serve_in_thread
from stockroom.host.service_authority import ContextServiceAuthority
from stockroom.host.windows_job import launch_in_windows_job
from stockroom.service import (
    MutexAcquireResult,
    ServiceControl,
    ServiceMode,
)
from stockroom.update import (
    AcceptedRelease,
    ImmutableReleaseStore,
    ReleaseActivationFailed,
    ReleaseActivationRole,
    ReleaseActivator,
    ReleaseHealthStage,
    TrustedReleaseRepository,
    VerifiedReleaseSet,
    verify_local_release_set,
)

_SID = "S-1-5-21-111111111-222222222-333333333-1001"


class _Identity:
    def current_sid(self) -> str:
        return _SID


class _Mutex:
    def __init__(self) -> None:
        self.held = False

    def try_acquire(self) -> MutexAcquireResult:
        if self.held:
            return MutexAcquireResult.BUSY
        self.held = True
        return MutexAcquireResult.CREATED

    def release(self) -> None:
        self.held = False


class _MutexFactory:
    def __init__(self) -> None:
        self.handle = _Mutex()

    def open_current_user(self, *, name: str, sid: str) -> _Mutex:
        del name, sid
        return self.handle


class _Storage:
    def validate(self, database: Path) -> Path:
        return database.resolve(strict=False)


class _Repository(TrustedReleaseRepository):
    def __init__(self, release: VerifiedReleaseSet) -> None:
        self.release = release
        self.calls = 0

    def stage_release(self) -> VerifiedReleaseSet:
        self.calls += 1
        return self.release


_WORKER = r"""
import argparse, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = %r
parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True, type=int)
args = parser.parse_args()
release_id = os.environ["STOCKROOM_RELEASE_ID"]
generation = int(os.environ["STOCKROOM_SERVICE_GENERATION"])

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        direct = self.headers.get("Host", "") == f"127.0.0.1:{args.port}"
        if self.path == "/api/health":
            if MODE == "pre_fail" or (MODE == "post_fail" and not direct):
                self.send_response(503); self.end_headers(); return
            body = json.dumps({
                "status": "ok",
                "release_id": release_id,
                "service_generation": generation,
                "service_mode": "shadow",
                "coordinator_status": "active",
            }).encode()
        elif self.path == "/version":
            body = json.dumps({"release_id": release_id}).encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
"""

_MANAGED_WORKER = r"""
import argparse, os, subprocess, sys
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from stockroom.host.service_authority import (
    SERVICE_CONTROL_HEADER,
    SERVICE_CONTROL_PREFIX,
    ContextServiceAuthority,
)

MODE = %r
parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True, type=int)
args = parser.parse_args()
release_id = os.environ["STOCKROOM_RELEASE_ID"]
expected_generation = int(os.environ["STOCKROOM_SERVICE_GENERATION"])
database = Path(os.environ["STOCKROOM_CONTROL_DATABASE"])
secret = os.environ["STOCKROOM_SERVICE_CONTROL_TOKEN"]

class Lifecycle:
    def start(self, control, fence):
        return fence
    def stop(self, handle, *, timeout):
        return None

context = SimpleNamespace()
authority = ContextServiceAuthority(
    context,
    release_id=release_id,
    control_database=database,
    lifecycle=Lifecycle(),
)
observed = authority.snapshot()
if observed.generation != expected_generation or observed.mode.value != "shadow":
    raise SystemExit("stale managed worker")
if MODE == "reject_promote_with_child":
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        creationflags=0x08000000,
    )
    Path(__file__).with_suffix(".child.pid").write_text(
        str(child.pid),
        encoding="ascii",
    )

app = FastAPI()

def authenticate(request):
    if request.headers.get(SERVICE_CONTROL_HEADER, "") != secret:
        raise RuntimeError("unauthorized")

@app.get("/api/health")
async def health():
    snapshot = authority.snapshot()
    return {
        "status": "ok",
        "release_id": release_id,
        "service_generation": snapshot.generation,
        "service_mode": snapshot.mode.value,
        "coordinator_status": snapshot.status.value,
    }

@app.get("/version")
async def version():
    return {"release_id": release_id}

@app.post(f"{SERVICE_CONTROL_PREFIX}/promote")
async def promote(request: Request):
    authenticate(request)
    body = await request.json()
    if MODE == "reject_promote_with_child":
        raise HTTPException(status_code=503)
    snapshot = authority.promote(expected_generation=body["expected_generation"])
    if MODE == "crash_after_promote":
        os._exit(23)
    return snapshot.public()

@app.post(f"{SERVICE_CONTROL_PREFIX}/demote")
async def demote(request: Request):
    authenticate(request)
    body = await request.json()
    return authority.demote(expected_generation=body["expected_generation"]).public()

try:
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
finally:
    authority.close()
"""


def _release(
    releases: Path,
    release_id: str,
    *,
    rollback_release_id: str,
    mode: str,
    managed_mode: str | None = None,
    compatible_from_release_ids: tuple[str, ...] | None = None,
    minimum_host_version: str = "0.1.0",
    package_version: str = "0.1.0",
) -> VerifiedReleaseSet:
    directory = releases / release_id
    backend = (
        (_WORKER % mode).encode()
        if managed_mode is None
        else (_MANAGED_WORKER % managed_mode).encode()
    )
    payloads = {
        "Backend/Worker.py": (backend, "backend"),
        "Frontend/Assets.txt": (f"frontend-{release_id}".encode(), "frontend"),
        "SBOM.json": (b'{"bomFormat":"CycloneDX"}', "sbom"),
    }
    members = [
        {
            "kind": kind,
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for path, (data, kind) in payloads.items()
    ]
    sbom_sha256 = next(member["sha256"] for member in members if member["kind"] == "sbom")
    document = {
        "api_compatibility": {"maximum": 1, "minimum": 1},
        "manifest_version": 1,
        "members": members,
        "migration": {
            "catalog": {"from": 1, "to": 1},
            "control": {"from": 1, "to": 1},
        },
        "minimum_host_version": minimum_host_version,
        "package_version": package_version,
        "protocol_version": 1,
        "release_id": release_id,
        "required_eda_bridge_version": "1",
        "required_odbc_driver_version": "1",
        "rollback_release_id": rollback_release_id,
        "sbom_sha256": sbom_sha256,
        "schema_compatibility": {
            "catalog": {"maximum": 1, "minimum": 1},
            "control": {"maximum": 1, "minimum": 1},
        },
        "workflow_code_versions": {"ingest": 1},
    }
    if compatible_from_release_ids is not None:
        document["manifest_version"] = 2
        document["compatible_from_release_ids"] = list(compatible_from_release_ids)
    manifest = json.dumps(
        document, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    for path, (data, _kind) in payloads.items():
        target = directory.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (directory / "Release Manifest.json").write_bytes(manifest)
    return verify_local_release_set(
        directory,
        expected_release_id=release_id,
        expected_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
    )


def _control(tmp_path: Path):
    control = ServiceControl(
        tmp_path / "Control.sqlite",
        mode=ServiceMode.COORDINATOR,
        identity=_Identity(),
        mutex_factory=_MutexFactory(),
        storage_policy=_Storage(),
    )
    return control, control.acquire()


def _local_app(
    release_id: str,
    generation: int,
    slow_started: threading.Event | None = None,
    release_slow: threading.Event | None = None,
) -> FastAPI:
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "release_id": release_id,
            "service_generation": generation,
            "service_mode": "coordinator",
        }

    @app.get("/version")
    def version():
        return {"release_id": release_id}

    @app.get("/slow")
    def slow():
        assert slow_started is not None and release_slow is not None
        slow_started.set()
        assert release_slow.wait(5)
        return {"release_id": release_id}

    return app


class _WindowReplacement:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.events: list[tuple[str, object]] = []
        self.pointer = lambda: ""

    def begin(self, target_release: AcceptedRelease) -> object:
        receipt = object()
        self.events.append(("begin", target_release.release_id))
        return receipt

    def commit(self, adoption: object) -> object:
        self.events.append(("commit", self.pointer()))
        if self.fail_commit:
            raise RuntimeError("injected replacement commit failure")
        return adoption

    def rollback(self, adoption: object) -> None:
        self.events.append(("rollback", self.pointer()))

    def start_initial(self, release: AcceptedRelease | None = None) -> object:
        self.events.append(
            ("start", None if release is None else release.release_id)
        )
        return object()

    def wait_until_closed(self) -> int:
        self.events.append(("wait", None))
        return 0

    def close(self) -> None:
        self.events.append(("close", None))


def _runtime(
    tmp_path: Path,
    *,
    candidate_mode: str,
    slow_started: threading.Event | None = None,
    release_slow: threading.Event | None = None,
    window_replacement=None,
):
    releases = tmp_path / "Releases"
    current = _release(
        releases,
        "release-current",
        rollback_release_id="release-bootstrap",
        mode="ok",
    )
    candidate = _release(
        releases,
        "release-candidate",
        rollback_release_id=current.release_id,
        mode=candidate_mode,
    )
    control, fence = _control(tmp_path / "Control")
    store = ImmutableReleaseStore(
        releases_directory=releases.resolve(),
        state_directory=(tmp_path / "State").resolve(),
    )
    store.initialize_active(current, control=control, fence=fence)
    local = _local_app(
        current.release_id,
        fence.generation,
        slow_started,
        release_slow,
    )
    proxy = SwitchableBackendProxy(local)
    port = pick_free_port()
    stable_url = f"http://127.0.0.1:{port}"
    server, server_thread = _serve_in_thread(proxy, port)
    window = object()
    observed_window = []

    def reload_window(url: str) -> None:
        observed_window.append((window, url))

    boundary = HostReleaseBoundary(
        proxy,
        public_base_url=stable_url,
        token="host-token",
        local_release_id=current.release_id,
        reload_window=reload_window,
        window_replacement=window_replacement,
        startup_timeout_seconds=0.75,
        post_adoption_probes=2,
        probe_interval_seconds=0.02,
        drain_timeout_seconds=2.0,
        stop_timeout_seconds=2.0,
    )
    activator = ReleaseActivator(
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
    return (
        current,
        candidate,
        control,
        fence,
        store,
        proxy,
        stable_url,
        server,
        server_thread,
        window,
        observed_window,
        boundary,
        activator,
    )


def _close(server, server_thread, boundary, control, fence) -> None:
    boundary.close()
    server.should_exit = True
    server_thread.join(timeout=5)
    control.release(fence)


def test_window_replacement_can_be_attached_after_startup_route_recovery(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, candidate_mode="ok")
    boundary = runtime[11]
    replacement = _WindowReplacement()
    try:
        boundary.attach_window_replacement(replacement)
        with pytest.raises(
            HostReleaseBoundaryError,
            match="window replacement is already attached",
        ):
            boundary.attach_window_replacement(replacement)
    finally:
        _close(runtime[7], runtime[8], boundary, runtime[2], runtime[3])


def test_real_process_activation_drains_old_requests_and_never_mixes_the_route(
    tmp_path: Path,
) -> None:
    slow_started = threading.Event()
    release_slow = threading.Event()
    runtime = _runtime(
        tmp_path,
        candidate_mode="ok",
        slow_started=slow_started,
        release_slow=release_slow,
    )
    (
        current,
        candidate,
        control,
        fence,
        store,
        proxy,
        stable_url,
        server,
        server_thread,
        window,
        observed_window,
        boundary,
        activator,
    ) = runtime
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            old_request = pool.submit(lambda: httpx.get(f"{stable_url}/slow", timeout=5))
            assert slow_started.wait(2)
            activation = pool.submit(activator.activate, candidate)
            deadline = time.monotonic() + 2
            while proxy.snapshot().accepting_requests and time.monotonic() < deadline:
                time.sleep(0.005)
            assert not proxy.snapshot().accepting_requests

            after_drain = pool.submit(lambda: httpx.get(f"{stable_url}/version", timeout=5))
            time.sleep(0.1)
            assert not after_drain.done()
            release_slow.set()

            assert old_request.result().json() == {"release_id": current.release_id}
            state = activation.result()
            assert after_drain.result().json() == {"release_id": candidate.release_id}

        assert state.current.release_id == candidate.release_id
        assert store.verify_startup(control).current.release_id == candidate.release_id
        assert observed_window == [(window, stable_url)]
        assert boundary.live_process_count == 1
    finally:
        _close(server, server_thread, boundary, control, fence)
    assert boundary.live_process_count == 0


def test_pre_adoption_health_failure_never_moves_the_window_or_route(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, candidate_mode="pre_fail")
    (
        current,
        candidate,
        control,
        fence,
        store,
        _proxy,
        stable_url,
        server,
        server_thread,
        _window,
        observed_window,
        boundary,
        activator,
    ) = runtime
    try:
        with pytest.raises(ReleaseActivationFailed) as failure:
            activator.activate(candidate)
        assert failure.value.reason == "pre_adoption_health_failed"
        assert not failure.value.rolled_back
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": current.release_id}
        assert store.verify_startup(control).current.release_id == current.release_id
        assert observed_window == []
        assert boundary.live_process_count == 0
    finally:
        _close(server, server_thread, boundary, control, fence)


def test_post_adoption_failure_rolls_back_exact_route_without_closing_window(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, candidate_mode="post_fail")
    (
        current,
        candidate,
        control,
        fence,
        store,
        _proxy,
        stable_url,
        server,
        server_thread,
        window,
        observed_window,
        boundary,
        activator,
    ) = runtime
    try:
        with pytest.raises(ReleaseActivationFailed) as failure:
            activator.activate(candidate)
        assert failure.value.reason == "post_adoption_health_failed"
        assert failure.value.rolled_back
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": current.release_id}
        assert store.verify_startup(control).current.release_id == current.release_id
        assert observed_window == [(window, stable_url), (window, stable_url)]
        assert boundary.live_process_count == 0
    finally:
        _close(server, server_thread, boundary, control, fence)


def test_two_phase_window_replacement_commits_only_after_durable_release_pointer(
    tmp_path: Path,
) -> None:
    replacement = _WindowReplacement()
    runtime = _runtime(
        tmp_path,
        candidate_mode="ok",
        window_replacement=replacement,
    )
    (
        _current,
        candidate,
        control,
        fence,
        store,
        _proxy,
        _stable_url,
        server,
        server_thread,
        _window,
        observed_window,
        boundary,
        activator,
    ) = runtime
    replacement.pointer = lambda: store.verify_startup(control).current.release_id
    try:
        state = activator.activate(candidate)
        assert state.current.release_id == candidate.release_id
        assert replacement.events == [
            ("begin", candidate.release_id),
            ("commit", candidate.release_id),
        ]
        assert observed_window == []
    finally:
        _close(server, server_thread, boundary, control, fence)
    assert replacement.events[-1] == ("close", None)


def test_window_commit_failure_remains_reversible_and_restores_prior_release(
    tmp_path: Path,
) -> None:
    replacement = _WindowReplacement(fail_commit=True)
    runtime = _runtime(
        tmp_path,
        candidate_mode="ok",
        window_replacement=replacement,
    )
    (
        current,
        candidate,
        control,
        fence,
        store,
        _proxy,
        stable_url,
        server,
        server_thread,
        _window,
        observed_window,
        boundary,
        activator,
    ) = runtime
    replacement.pointer = lambda: store.verify_startup(control).current.release_id
    try:
        with pytest.raises(ReleaseActivationFailed) as failure:
            activator.activate(candidate)
        assert failure.value.reason == "adoption_commit_failed"
        assert failure.value.rolled_back
        assert replacement.events == [
            ("begin", candidate.release_id),
            ("commit", candidate.release_id),
            # The route/window rollback happens before the durable release
            # pointer is restored, so the trial must remain reversible here.
            ("rollback", candidate.release_id),
        ]
        assert store.verify_startup(control).current.release_id == current.release_id
        assert httpx.get(f"{stable_url}/version").json() == {
            "release_id": current.release_id
        }
        assert observed_window == []
    finally:
        _close(server, server_thread, boundary, control, fence)


def test_post_adoption_health_failure_rolls_back_replacement_without_commit(
    tmp_path: Path,
) -> None:
    replacement = _WindowReplacement()
    runtime = _runtime(
        tmp_path,
        candidate_mode="post_fail",
        window_replacement=replacement,
    )
    (
        current,
        candidate,
        control,
        fence,
        store,
        _proxy,
        _stable_url,
        server,
        server_thread,
        _window,
        _observed_window,
        boundary,
        activator,
    ) = runtime
    replacement.pointer = lambda: store.verify_startup(control).current.release_id
    try:
        with pytest.raises(ReleaseActivationFailed) as failure:
            activator.activate(candidate)
        assert failure.value.reason == "post_adoption_health_failed"
        assert failure.value.rolled_back
        assert replacement.events == [
            ("begin", candidate.release_id),
            ("rollback", current.release_id),
        ]
        assert store.verify_startup(control).current.release_id == current.release_id
    finally:
        _close(server, server_thread, boundary, control, fence)


def test_tuf_broker_runtime_activates_real_worker_and_exposes_sanitized_state(
    tmp_path: Path,
) -> None:
    runtime_parts = _runtime(tmp_path, candidate_mode="ok")
    (
        _current,
        candidate,
        control,
        fence,
        store,
        _proxy,
        stable_url,
        server,
        server_thread,
        window,
        observed_window,
        boundary,
        _unused_activator,
    ) = runtime_parts
    repository = _Repository(candidate)
    status_path = tmp_path / "Status" / "Update Status.json"
    runtime = ProductionUpdateRuntime(
        control,
        fence,
        store,
        repository,
        boundary,
        initial_state=store.verify_startup(control),
        status_path=status_path,
        refresh_interval_seconds=5,
        attempt_deadline_seconds=3,
        minimum_retry_backoff_seconds=0.05,
        maximum_retry_backoff_seconds=0.1,
    )
    try:
        runtime.start()
        deadline = time.monotonic() + 5
        while (
            runtime.status()["current_release_id"] != candidate.release_id
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        status = runtime.status()
        assert status["current_release_id"] == candidate.release_id, status
        assert status["current_revision"] == candidate.release_id
        assert status["target_revision"] == candidate.release_id
        assert status["state"] == "up_to_date"
        assert status["channel"] == "production"
        assert status["check_interval_seconds"] == 5
        assert status["blocking_reason"] is None
        assert "owner_id" not in json.dumps(status)
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": candidate.release_id}
        assert observed_window == [(window, stable_url)]
        assert repository.calls == 1
        assert status_path.is_file()
        assert (
            json.loads(status_path.read_text(encoding="utf-8"))["current_release_id"]
            == candidate.release_id
        )
    finally:
        runtime.close()
        runtime.close()
        server.should_exit = True
        server_thread.join(timeout=5)
    assert boundary.live_process_count == 0


def _managed_handoff(
    tmp_path: Path,
    *,
    managed_mode: str,
):
    releases = tmp_path / "Managed Releases"
    current = cast(
        AcceptedRelease,
        _release(
            releases,
            "release-current",
            rollback_release_id="release-bootstrap",
            mode="ok",
        ),
    )
    candidate = cast(
        AcceptedRelease,
        _release(
            releases,
            "release-candidate",
            rollback_release_id=current.release_id,
            mode="ok",
            managed_mode=managed_mode,
        ),
    )
    context = SimpleNamespace()
    lifecycle_events: list[tuple[str, int, int]] = []

    class Lifecycle:
        def start(self, control, fence):
            del control
            lifecycle_events.append(("start", fence.generation, threading.get_ident()))
            return fence

        def stop(self, handle, *, timeout):
            del timeout
            lifecycle_events.append(("stop", handle.generation, threading.get_ident()))

    authority = ContextServiceAuthority(
        context,
        release_id=current.release_id,
        control_database=(tmp_path / "Service State" / "Control.sqlite").resolve(),
        lifecycle=Lifecycle(),
        start_as_coordinator=True,
    )
    local = FastAPI()

    @local.get("/api/health")
    def local_health():
        snapshot = authority.snapshot()
        return {
            "status": "ok",
            "release_id": current.release_id,
            "service_generation": snapshot.generation,
            "service_mode": snapshot.mode.value,
            "coordinator_status": snapshot.status.value,
        }

    @local.get("/version")
    def local_version():
        return {"release_id": current.release_id}

    proxy = SwitchableBackendProxy(local)
    port = pick_free_port()
    stable_url = f"http://127.0.0.1:{port}"
    server, server_thread = _serve_in_thread(proxy, port)
    boundary = HostReleaseBoundary(
        proxy,
        public_base_url=stable_url,
        token="managed-host-token",
        local_release_id=current.release_id,
        reload_window=lambda _url: None,
        local_service_authority=authority,
        workflow_database=(tmp_path / "Service State" / "Workflow.sqlite").resolve(),
        startup_timeout_seconds=5.0,
        post_adoption_probes=1,
        probe_interval_seconds=0.02,
        drain_timeout_seconds=2.0,
        stop_timeout_seconds=2.0,
    )
    return (
        current,
        candidate,
        authority,
        lifecycle_events,
        stable_url,
        server,
        server_thread,
        boundary,
    )


def _win32_process_is_running(process_id: int) -> bool:
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 worker job")
def test_worker_job_stops_payload_after_the_tracked_root_already_exited(
    tmp_path: Path,
) -> None:
    child_pid_path = tmp_path / "Child PID.txt"
    parent = tmp_path / "Parent.py"
    parent.write_text(
        "\n".join(
            [
                "import subprocess, sys",
                "from pathlib import Path",
                "child = subprocess.Popen(",
                "    [sys.executable, '-c', 'import time; time.sleep(300)'],",
                "    creationflags=0x08000000,",
                ")",
                "Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii')",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    process, job = launch_in_windows_job(
        [sys.executable, str(parent), str(child_pid_path)],
        cwd=tmp_path,
        environment=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    child_pid: int | None = None
    try:
        assert process.wait(timeout=10.0) == 0
        child_pid = int(child_pid_path.read_text(encoding="ascii"))
        assert _win32_process_is_running(child_pid)

        job.terminate_all(timeout=5.0)

        assert not _win32_process_is_running(child_pid)
    finally:
        try:
            job.terminate_all(timeout=5.0)
        finally:
            if child_pid is not None and _win32_process_is_running(child_pid):
                subprocess.run(
                    [
                        "taskkill.exe",
                        "/PID",
                        str(child_pid),
                        "/T",
                        "/F",
                    ],
                    check=False,
                    capture_output=True,
                    timeout=5.0,
                )


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 named-mutex handoff")
def test_candidate_takes_service_authority_and_rollback_restores_next_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STOCKROOM_UPDATE_MODE", raising=False)
    (
        current,
        candidate,
        authority,
        lifecycle_events,
        stable_url,
        server,
        server_thread,
        boundary,
    ) = _managed_handoff(tmp_path, managed_mode="ok")
    worker = None
    try:
        worker = boundary.launch_shadow(candidate, generation=11)
        boundary.check(
            candidate,
            worker,
            stage=ReleaseHealthStage.PRE_ADOPTION,
            generation=11,
        )
        drained = boundary.drain(current, generation=11)
        adoption = boundary.adopt(
            candidate,
            current,
            worker,
            drained,
            generation=11,
        )

        assert adoption.current_service_generation == 1
        assert adoption.candidate_service_generation == 2
        assert authority.snapshot().mode is ServiceMode.SHADOW
        assert authority.snapshot().generation == 2
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": candidate.release_id}

        boundary.rollback(
            candidate,
            current,
            adoption,
            generation=11,
        )
        assert authority.snapshot().mode is ServiceMode.COORDINATOR
        assert authority.snapshot().generation == 3
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": current.release_id}
        boundary.stop_shadow(worker, generation=11)
        worker = None
    finally:
        boundary.close()
        server.should_exit = True
        server_thread.join(timeout=5.0)
    assert worker is None
    assert [event[:2] for event in lifecycle_events] == [
        ("start", 1),
        ("stop", 1),
        ("start", 3),
        ("stop", 3),
    ]
    assert len({event[2] for event in lifecycle_events}) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 worker-tree teardown")
def test_failed_promotion_stops_the_complete_worker_tree_before_restoring_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STOCKROOM_UPDATE_MODE", raising=False)
    (
        current,
        candidate,
        authority,
        _lifecycle_events,
        stable_url,
        server,
        server_thread,
        boundary,
    ) = _managed_handoff(
        tmp_path,
        managed_mode="reject_promote_with_child",
    )
    child_pid: int | None = None
    try:
        worker = boundary.launch_shadow(candidate, generation=13)
        boundary.check(
            candidate,
            worker,
            stage=ReleaseHealthStage.PRE_ADOPTION,
            generation=13,
        )
        child_pid_path = candidate.directory / "Backend" / "Worker.child.pid"
        child_pid = int(child_pid_path.read_text(encoding="ascii"))
        assert _win32_process_is_running(child_pid)
        drained = boundary.drain(current, generation=13)

        with pytest.raises(HostReleaseRouteError, match="could not acquire"):
            boundary.adopt(
                candidate,
                current,
                worker,
                drained,
                generation=13,
            )

        snapshot = authority.snapshot()
        assert snapshot.mode is ServiceMode.COORDINATOR
        assert snapshot.generation == 2
        assert worker.process.poll() is not None
        assert boundary.live_process_count == 0
        assert not _win32_process_is_running(child_pid)
        boundary.resume(current, drained, generation=13)
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": current.release_id}
    finally:
        try:
            boundary.close()
        finally:
            if child_pid is not None and _win32_process_is_running(child_pid):
                subprocess.run(
                    [
                        "taskkill.exe",
                        "/PID",
                        str(child_pid),
                        "/T",
                        "/F",
                    ],
                    check=False,
                    capture_output=True,
                    timeout=5.0,
                )
            server.should_exit = True
            server_thread.join(timeout=5.0)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 managed rollback handoff")
def test_release_activator_post_adoption_failure_restores_managed_prior_exactly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STOCKROOM_UPDATE_MODE", raising=False)
    (
        current,
        candidate,
        authority,
        lifecycle_events,
        stable_url,
        server,
        server_thread,
        boundary,
    ) = _managed_handoff(tmp_path, managed_mode="ok")
    update_control, update_fence = _control(tmp_path / "Update Authority")
    store = ImmutableReleaseStore(
        releases_directory=current.directory.parent,
        state_directory=(tmp_path / "Update State").resolve(),
    )
    store.initialize_active(current, control=update_control, fence=update_fence)

    class FailAfterRealPostAdoptionHealth:
        def check(self, release, handle, *, stage, generation):
            boundary.check(
                release,
                handle,
                stage=stage,
                generation=generation,
            )
            if stage is ReleaseHealthStage.POST_ADOPTION:
                raise RuntimeError("injected post-adoption failure")

    activator = ReleaseActivator(
        update_control,
        store,
        role=ReleaseActivationRole.COORDINATOR,
        fence=update_fence,
        rehearsal=HostManifestRehearsal(),
        launcher=boundary,
        health=FailAfterRealPostAdoptionHealth(),
        drain=boundary,
        adoption=boundary,
    )
    try:
        with pytest.raises(ReleaseActivationFailed) as failure:
            activator.activate(candidate)
        assert failure.value.reason == "post_adoption_health_failed"
        assert failure.value.rolled_back is True
        restored = store.verify_startup(update_control)
        assert restored.current.release_id == current.release_id
        assert restored.previous is None
        assert restored.selection_reason == "rollback"
        snapshot = authority.snapshot()
        assert snapshot.mode is ServiceMode.COORDINATOR
        assert snapshot.generation == 3
        assert boundary.live_process_count == 0
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": current.release_id}
    finally:
        boundary.close()
        server.should_exit = True
        server_thread.join(timeout=5.0)
        update_control.release(update_fence)
        update_control.close()
    assert [event[:2] for event in lifecycle_events] == [
        ("start", 1),
        ("stop", 1),
        ("start", 3),
        ("stop", 3),
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 named-mutex crash recovery")
def test_candidate_crash_after_promotion_restores_prior_before_route_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STOCKROOM_UPDATE_MODE", raising=False)
    (
        current,
        candidate,
        authority,
        _lifecycle_events,
        stable_url,
        server,
        server_thread,
        boundary,
    ) = _managed_handoff(tmp_path, managed_mode="crash_after_promote")
    try:
        worker = boundary.launch_shadow(candidate, generation=12)
        boundary.check(
            candidate,
            worker,
            stage=ReleaseHealthStage.PRE_ADOPTION,
            generation=12,
        )
        drained = boundary.drain(current, generation=12)

        with pytest.raises(HostReleaseRouteError, match="could not acquire"):
            boundary.adopt(
                candidate,
                current,
                worker,
                drained,
                generation=12,
            )

        # adopt() has already reacquired the abandoned generation for the prior
        # context, but intentionally leaves the proxy drained for its caller.
        assert authority.snapshot().mode is ServiceMode.COORDINATOR
        assert authority.snapshot().generation == 3
        assert worker.process.poll() == 23
        boundary.resume(current, drained, generation=12)
        assert httpx.get(f"{stable_url}/version").json() == {"release_id": current.release_id}
    finally:
        boundary.close()
        server.should_exit = True
        server_thread.join(timeout=5.0)


def test_failed_production_bootstrap_restores_exact_context_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from stockroom.host import release_runtime

    release = _release(
        tmp_path / "Data" / "Releases",
        "release-packaged",
        rollback_release_id="release-bootstrap",
        mode="ok",
    )
    control, prior_fence = _control(tmp_path / "Control")
    control.release(prior_fence)
    context = SimpleNamespace(service_mode="prior-mode")
    bundle_root = tmp_path / "Bundle"
    bundle_root.mkdir()
    (bundle_root / "Root.json").write_bytes(b"test-root")
    descriptor = {
        "current_manifest_sha256": release.manifest_sha256,
        "current_release_id": release.release_id,
        "metadata_base_url": "https://updates.example.invalid/metadata/",
        "target_base_url": "https://updates.example.invalid/targets/",
    }
    monkeypatch.setattr(
        release_runtime,
        "_strict_feed_descriptor",
        lambda _path: descriptor,
    )
    monkeypatch.setattr(
        release_runtime,
        "_seed_packaged_release",
        lambda *args, **kwargs: release,
    )
    monkeypatch.setattr(
        release_runtime,
        "ServiceControl",
        lambda *args, **kwargs: control,
    )

    class Lifecycle:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def start(self, service_control, service_fence):
            del service_control
            return service_fence

        def stop(self, handle, *, timeout):
            del handle, timeout

    monkeypatch.setattr(release_runtime, "ContextServiceLifecycle", Lifecycle)

    def reject_repository(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("repository setup failed")

    monkeypatch.setattr(
        release_runtime,
        "TrustedReleaseRepository",
        reject_repository,
    )
    proxy = SwitchableBackendProxy(_local_app(release.release_id, 1))

    with pytest.raises(RuntimeError, match="repository setup failed"):
        create_production_update_runtime(
            proxy,
            context=context,
            public_base_url="http://127.0.0.1:12345",
            token="host-token",
            reload_window=lambda _url: None,
            bundle_root=bundle_root,
            data_root=tmp_path / "Data",
        )

    assert context.service_mode == "prior-mode"
    assert not hasattr(context, "release_id")
    assert not hasattr(context, "service_generation")
    assert not hasattr(context, "service_control")
    assert control.snapshot().status.value == "released"


def test_frozen_product_identity_cannot_be_downgraded_to_source_git(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("STOCKROOM_UPDATE_MODE", "development")

    assert host_update_mode() is HostUpdateMode.PRODUCTION


def test_host_rehearsal_accepts_signed_direct_compatibility_across_skipped_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STOCKROOM_UPDATE_MODE", raising=False)
    releases = tmp_path / "Releases"
    current = _release(
        releases,
        "release-current",
        rollback_release_id="release-bootstrap",
        mode="ok",
    )
    candidate = _release(
        releases,
        "release-candidate",
        rollback_release_id="release-uninstalled-predecessor",
        compatible_from_release_ids=(
            "release-uninstalled-predecessor",
            current.release_id,
        ),
        mode="ok",
    )

    HostManifestRehearsal().rehearse(
        cast(AcceptedRelease, candidate),
        cast(AcceptedRelease, current),
        generation=1,
    )


def test_frozen_v1_host_rejects_v2_candidate_that_requires_v2_broker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import stockroom.host.release_runtime as release_runtime

    releases = tmp_path / "Releases"
    current = _release(
        releases,
        "release-1.9.0.0",
        rollback_release_id="release-bootstrap",
        mode="ok",
        minimum_host_version="1.0.0.0",
    )
    candidate = _release(
        releases,
        "release-2.0.0.0",
        rollback_release_id=current.release_id,
        compatible_from_release_ids=(current.release_id,),
        mode="ok",
        minimum_host_version="2.0.0.0",
    )
    monkeypatch.setattr(release_runtime, "__version__", "1.9.0.0")

    with pytest.raises(
        HostReleaseCompatibilityError,
        match="newer stable host",
    ):
        HostManifestRehearsal().rehearse(
            cast(AcceptedRelease, candidate),
            cast(AcceptedRelease, current),
            generation=1,
        )


def test_frozen_v1_host_accepts_v2_candidate_supported_by_v1_broker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import stockroom.host.release_runtime as release_runtime

    releases = tmp_path / "Releases"
    current = _release(
        releases,
        "release-1.0.0.0",
        rollback_release_id="release-bootstrap",
        mode="ok",
        minimum_host_version="1.0.0.0",
    )
    candidate = _release(
        releases,
        "release-2.0.0.0",
        rollback_release_id=current.release_id,
        compatible_from_release_ids=(current.release_id,),
        mode="ok",
        minimum_host_version="1.0.0.0",
    )
    monkeypatch.setattr(release_runtime, "__version__", "1.0.0.0")

    HostManifestRehearsal().rehearse(
        cast(AcceptedRelease, candidate),
        cast(AcceptedRelease, current),
        generation=1,
    )


def test_numeric_host_versions_pad_missing_windows_components() -> None:
    assert _numeric_version("0.1.0") == _numeric_version("0.1.0.0")
    assert _numeric_version("1.2") < _numeric_version("1.2.0.1")


def test_newer_packaged_release_supersedes_stale_pointer_but_not_newer_download(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STOCKROOM_UPDATE_MODE", raising=False)
    releases = tmp_path / "Releases"
    prior = _release(
        releases,
        "release-0.1.7.0",
        rollback_release_id="release-0.1.6.0",
        mode="ok",
        package_version="0.1.7.0",
    )
    packaged = _release(
        releases,
        "release-0.1.8.0",
        rollback_release_id=prior.release_id,
        compatible_from_release_ids=(prior.release_id,),
        mode="ok",
        package_version="0.1.8.0",
    )
    control, fence = _control(tmp_path / "Control")
    store = ImmutableReleaseStore(
        releases_directory=releases,
        state_directory=tmp_path / "State",
    )
    try:
        accepted_prior = store.accept_verified(prior, control=control, fence=fence)
        active = store.select_active(
            accepted_prior,
            previous=None,
            selection_reason="initialize",
            control=control,
            fence=fence,
        )
        accepted_packaged = store.accept_verified(
            packaged,
            control=control,
            fence=fence,
        )

        upgraded = _prefer_newer_packaged_release(
            store,
            active,
            accepted_packaged,
            control=control,
            fence=fence,
        )
        unchanged = _prefer_newer_packaged_release(
            store,
            upgraded,
            accepted_prior,
            control=control,
            fence=fence,
        )

        assert upgraded.current.release_id == packaged.release_id
        assert upgraded.previous is not None
        assert upgraded.previous.release_id == prior.release_id
        assert unchanged == upgraded
    finally:
        control.release(fence)
        control.close()
