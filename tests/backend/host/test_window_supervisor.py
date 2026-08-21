from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import traceback
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from stockroom.host import window_supervisor as supervisor_module
from stockroom.host.window_process import bootstrap_proof, parse_bootstrap
from stockroom.host.window_supervisor import (
    WindowHostClient,
    WindowHostHealth,
    WindowHostLaunch,
    WindowHostSupervisor,
    WindowSupervisorError,
    WindowSupervisorProcessError,
    WindowSupervisorProtocolError,
    WindowSupervisorTimeout,
    connect_attached_window_host,
    sanitized_window_host_environment,
)
from stockroom.host.windows_handoff_pipe import (
    ByteTransport,
    HandoffDeadlineExpired,
    HandoffMessage,
    HandoffPipeError,
)
from stockroom.host.windows_job import launch_in_windows_job
from stockroom.update import AcceptedRelease
from stockroom.update.manifest import ReleaseManifest, ReleaseMember

_HANDOFF_ID = "2ed594a5-e46d-4fc0-aecb-17ca94aab32f"
_PIPE_NAME = "Stockroom.WindowHandoff." + "a" * 32
_API_CREDENTIAL = "A" * 43
_HANDOFF_CREDENTIAL = "B" * 42 + "Q"
_NOW = 1_800_000_000_000
_PARENT_PID = 111
_CHILD_PID = 222
_BASE_URL = "http://127.0.0.1:43210"
_STAGING_ROOT = str(Path(tempfile.gettempdir()).resolve() / "Stockroom Staging")
# The shell bridge's two roots and the exact targets inside them. Built from the platform's own
# temp root so the absolute-path rule holds on whichever machine runs the suite.
_LIBRARY_ROOT = str(Path(tempfile.gettempdir()).resolve() / "Stockroom Library")
_COMPONENT_DIRECTORY = str(Path(_LIBRARY_ROOT) / "sourced" / "part-1")
_EXPORT_ROOT = str(Path(tempfile.gettempdir()).resolve() / "Component Exports")
_EXPORTED_FILE = str(Path(_EXPORT_ROOT) / "part-1" / "kicad" / "part-1.kicad_sym")


@dataclass
class _Transport:
    peer_process_id: int = _CHILD_PID
    closed: bool = False
    close_error: BaseException | None = None
    closed_event: threading.Event = field(default_factory=threading.Event)

    def read_exact(self, size: int) -> bytes:
        del size
        raise AssertionError("the fake channel owns protocol I/O")

    def write_all(self, data: bytes) -> None:
        del data
        raise AssertionError("the fake channel owns protocol I/O")

    def close(self) -> None:
        self.closed = True
        self.closed_event.set()
        if self.close_error is not None:
            raise self.close_error


@dataclass
class _Server:
    transport: _Transport = field(default_factory=_Transport)
    accepted_pids: list[int] = field(default_factory=list)
    close_calls: int = 0

    def accept(self, *, expected_client_pid: int) -> ByteTransport:
        self.accepted_pids.append(expected_client_pid)
        return self.transport

    def close(self) -> None:
        self.close_calls += 1


class _BlockingServer(_Server):
    def __init__(self, *, return_after_close: bool) -> None:
        super().__init__()
        self._released = threading.Event()
        self.return_after_close = return_after_close

    def accept(self, *, expected_client_pid: int) -> ByteTransport:
        self.accepted_pids.append(expected_client_pid)
        self._released.wait()
        if self.return_after_close:
            return self.transport
        raise HandoffPipeError("accept cancelled")

    def close(self) -> None:
        super().close()
        self._released.set()


class _StubbornServer(_Server):
    def __init__(self) -> None:
        super().__init__()
        self._released = threading.Event()

    def accept(self, *, expected_client_pid: int) -> ByteTransport:
        self.accepted_pids.append(expected_client_pid)
        self._released.wait()
        return self.transport

    def release(self) -> None:
        self._released.set()


@dataclass
class _Process:
    pid: int = _CHILD_PID
    wait_plan: list[object] = field(default_factory=lambda: [0])
    wait_calls: list[float | None] = field(default_factory=list)
    kill_calls: int = 0
    poll_result: int | None = None
    poll_plan: list[object] = field(default_factory=list)
    on_wait: Callable[[float | None], None] | None = None
    on_kill: Callable[[], None] | None = None

    def poll(self) -> int | None:
        if self.poll_plan:
            outcome = self.poll_plan.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            assert outcome is None or type(outcome) is int or type(outcome) is bool
            return outcome
        return self.poll_result

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.on_wait is not None:
            self.on_wait(timeout)
        outcome = self.wait_plan.pop(0) if self.wait_plan else 0
        if isinstance(outcome, BaseException):
            raise outcome
        assert type(outcome) in {int, bool}
        exit_code = cast(int, outcome)
        self.poll_result = exit_code
        return exit_code

    def kill(self) -> None:
        self.kill_calls += 1
        if self.on_kill is not None:
            self.on_kill()


@dataclass
class _Job:
    errors: list[BaseException] = field(default_factory=list)
    timeout_calls: list[float] = field(default_factory=list)
    on_terminate: Callable[[float], None] | None = None

    def terminate_all(self, *, timeout: float) -> None:
        self.timeout_calls.append(timeout)
        if self.on_terminate is not None:
            self.on_terminate(timeout)
        if self.errors:
            raise self.errors.pop(0)


@dataclass
class _Launcher:
    process: _Process = field(default_factory=_Process)
    job: _Job = field(default_factory=_Job)
    error: BaseException | None = None
    calls: list[tuple[tuple[str, ...], Path, dict[str, str], int]] = field(default_factory=list)

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        creationflags: int,
    ) -> tuple[_Process, _Job]:
        self.calls.append(
            (
                tuple(command),
                cwd,
                dict(environment),
                creationflags,
            )
        )
        if self.error is not None:
            raise self.error
        return self.process, self.job


class _Channel:
    def __init__(
        self,
        *,
        handoff_id: str = _HANDOFF_ID,
        peer_process_id: int = _CHILD_PID,
        hello_changes: Mapping[str, object] | None = None,
        response_changes: Mapping[str, Mapping[str, object]] | None = None,
        response_name_changes: Mapping[str, str] | None = None,
        response_sequence_changes: Mapping[str, int] | None = None,
        command_errors: set[str] | None = None,
        block_on: str | None = None,
        receive_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self._handoff_id = handoff_id
        self._peer_process_id = peer_process_id
        self.hello_changes = dict(hello_changes or {})
        self.response_changes = {
            key: dict(value) for key, value in (response_changes or {}).items()
        }
        self.response_name_changes = dict(response_name_changes or {})
        self.response_sequence_changes = dict(response_sequence_changes or {})
        self.command_errors = set(command_errors or set())
        self.block_on = block_on
        self.receive_error = receive_error
        self.close_error = close_error
        self.sent: list[HandoffMessage] = []
        self.expect_lease_scope: dict[str, object] = {
            "lease_id": "11111111-1111-4111-8111-111111111111",
            "staging_root": _STAGING_ROOT,
            "component_id": "component-9",
            "manufacturer": "Exact Manufacturer",
            "mpn": "MPN-9",
            "provider_id": "digikey",
        }
        self.expected_names: list[frozenset[str] | None] = []
        self.closed = False
        self._closed_event = threading.Event()
        self._incoming_sequence = 1
        self.visible = False
        self.prepared = False

    @property
    def handoff_id(self) -> str:
        return self._handoff_id

    @property
    def peer_process_id(self) -> int:
        return self._peer_process_id

    def send(
        self,
        name: str,
        payload: Mapping[str, object],
        *,
        deadline_unix_ms: int,
    ) -> HandoffMessage:
        message = HandoffMessage(
            handoff_id=self._handoff_id,
            sequence=len(self.sent) + 1,
            deadline_unix_ms=deadline_unix_ms,
            name=name,
            payload=dict(payload),
        )
        self.sent.append(message)
        return message


    def _hello(self, request: HandoffMessage) -> HandoffMessage:
        bootstrap = parse_bootstrap(request)
        result: dict[str, object] = {
            "release_id": bootstrap.release_id,
            "process_id": _CHILD_PID,
            "parent_process_id": _PARENT_PID,
            "window_handle": 4500,
            "profile_id": "window-" + "c" * 32,
            "renderer": "edgechromium",
            "hidden": True,
            "proof": bootstrap_proof(
                bootstrap,
                parent_process_id=_PARENT_PID,
                child_process_id=_CHILD_PID,
            ),
        }
        result.update(self.hello_changes)
        return self._response(
            request,
            name=self.response_name_changes.get("bootstrap", "hello-hidden"),
            result=result,
        )

    def _command_result(self, request: HandoffMessage) -> tuple[str, dict[str, object]]:
        if request.name == "prepare-hidden":
            self.prepared = True
            self.visible = False
            return "prepared-hidden", {"hidden": True}
        if request.name == "show":
            self.visible = True
            return "shown", {"visible": True}
        if request.name == "focus":
            return "focused", {"focused": True}
        if request.name == "provider-lease-begin":
            assert request.payload == self.expect_lease_scope
            return "provider-lease-begun", {
                "lease_id": "11111111-1111-4111-8111-111111111111",
                "generation": 7,
            }
        if request.name == "provider-download-cancel":
            return "provider-download-cancelled", {
                "lease_id": request.payload["lease_id"],
                "generation": request.payload["generation"],
                "cancelled": 2,
            }
        if request.name == "provider-download-events":
            return "provider-download-events", {
                "lease_id": request.payload["lease_id"],
                "generation": request.payload["generation"],
                "events": [
                    {
                        "sequence": 19,
                        "lease_id": request.payload["lease_id"],
                        "generation": request.payload["generation"],
                        "component_id": "component-9",
                        "manufacturer": "Exact Manufacturer",
                        "mpn": "MPN-9",
                        "provider_id": "digikey",
                        "operation_id": "operation-1",
                        "phase": "terminal",
                        "state": "completed",
                        "uri": "https://provider.example.test/model.zip",
                        "suggested_file_name": "model.zip",
                        "result_file_path": r"C:\Capture\model.zip",
                        "mime_type": "application/zip",
                        "interrupt_reason": "",
                        "total_bytes": 120,
                        "bytes_received": 120,
                    }
                ],
            }
        if request.name == "eda-applications":
            return "eda-applications", {
                "applications": [
                    {"id": "kicad", "name": "KiCad 9.0", "version": "9.0.1"},
                ]
            }
        if request.name == "shell-reveal":
            assert request.payload == {
                "root": _LIBRARY_ROOT,
                "path": _COMPONENT_DIRECTORY,
            }
            return "shell-revealed", {"revealed": True}
        if request.name == "eda-open":
            assert request.payload == {
                "application_id": "kicad",
                "root": _EXPORT_ROOT,
                "path": _EXPORTED_FILE,
            }
            return "eda-opened", {"opened": True}
        if request.name == "provider-lease-release":
            return "provider-lease-released", {
                "lease_id": request.payload["lease_id"],
                "generation": request.payload["generation"],
                "released": True,
            }
        if request.name == "provider-show":
            assert request.payload == {
                "lease_id": "11111111-1111-4111-8111-111111111111",
                "generation": 7,
            }
            return "provider-shown", {"visible": True}
        if request.name == "provider-hide":
            assert request.payload == {
                "lease_id": "11111111-1111-4111-8111-111111111111",
                "generation": 7,
            }
            return "provider-hidden", {"visible": False}
        if request.name == "provider-current-url":
            assert request.payload == {
                "lease_id": "11111111-1111-4111-8111-111111111111",
                "generation": 7,
            }
            return "provider-current-url", {"url": "https://provider.example.test/part"}
        if request.name == "provider-navigate":
            assert request.payload == {
                "lease_id": "11111111-1111-4111-8111-111111111111",
                "generation": 7,
                "url": "https://provider.example.test/next",
            }
            return "provider-navigated", {"navigated": True}
        if request.name == "provider-document-state":
            assert request.payload == {
                "lease_id": "11111111-1111-4111-8111-111111111111",
                "generation": 7,
                "ready_selectors": ["#download"],
                "ready_texts": ["download"],
            }
            return (
                "provider-document-state",
                {
                    "ready": True,
                    "challenge": False,
                    "account_verification": False,
                    "provider_error": False,
                    "provider_ready": True,
                },
            )
        if request.name == "health":
            return (
                "health",
                {
                    "hwnd": 4500,
                    "current_url": f"{_BASE_URL}/#/components",
                    "hidden": not self.visible,
                    "visible": self.visible,
                    "renderer": "edgechromium",
                    "close_requested": False,
                },
            )
        if request.name == "export":
            return "exported", {"snapshot": {"route": "components", "event": 7}}
        if request.name == "shutdown":
            return "stopping", {"stopping": True}
        raise AssertionError(f"unexpected command {request.name}")

    def _response(
        self,
        request: HandoffMessage,
        *,
        name: str,
        result: dict[str, object],
    ) -> HandoffMessage:
        sequence = self._incoming_sequence
        self._incoming_sequence += 1
        return HandoffMessage(
            handoff_id=self._handoff_id,
            sequence=sequence,
            deadline_unix_ms=_NOW + 5_000,
            name=name,
            payload={
                "request_sequence": self.response_sequence_changes.get(
                    request.name,
                    request.sequence,
                ),
                "result": result,
            },
        )

    def receive(
        self,
        *,
        expected_names: Collection[str] | None = None,
    ) -> HandoffMessage:
        self.expected_names.append(None if expected_names is None else frozenset(expected_names))
        request = self.sent[-1]
        if self.block_on == request.name:
            self._closed_event.wait()
            raise HandoffPipeError("pipe closed")
        if self.receive_error is not None:
            raise self.receive_error
        if request.name == "bootstrap":
            return self._hello(request)
        if request.name in self.command_errors:
            return self._response(
                request,
                name="command-error",
                result={
                    "command": request.name,
                    "code": "candidate-command-failed",
                },
            )
        response_name, result = self._command_result(request)
        result.update(self.response_changes.get(request.name, {}))
        response_name = self.response_name_changes.get(request.name, response_name)
        return self._response(request, name=response_name, result=result)

    def close(self) -> None:
        self.closed = True
        self._closed_event.set()
        if self.close_error is not None:
            raise self.close_error


def test_attached_window_bootstrap_survives_packaged_worker_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Transport(peer_process_id=_CHILD_PID)
    channel = _Channel(handoff_id=_HANDOFF_ID, peer_process_id=_CHILD_PID)

    def connect(pipe_name: str, *, expected_server_pid: int) -> _Transport:
        assert pipe_name == _PIPE_NAME
        assert expected_server_pid == _CHILD_PID
        return connection

    def channel_factory(
        transport: _Transport,
        *,
        expected_handoff_id: str,
    ) -> _Channel:
        assert transport is connection
        assert expected_handoff_id == _HANDOFF_ID
        return channel

    monkeypatch.setattr(supervisor_module, "connect_windows_named_pipe", connect)
    monkeypatch.setattr(supervisor_module, "HandoffChannel", channel_factory)
    monkeypatch.setattr(supervisor_module.uuid, "uuid4", lambda: _HANDOFF_ID)
    monkeypatch.setattr(supervisor_module.os, "getpid", lambda: _PARENT_PID)
    monkeypatch.setattr(supervisor_module, "_now_unix_ms", lambda: _NOW)

    client = connect_attached_window_host(
        _PIPE_NAME,
        expected_host_process_id=_CHILD_PID,
        release_id="release-1.0.0.0",
        base_url=_BASE_URL,
        api_credential=_API_CREDENTIAL,
    )

    assert channel.sent[0].name == "bootstrap"
    assert channel.sent[0].deadline_unix_ms == _NOW + 120_000
    assert [message.name for message in channel.sent] == [
        "bootstrap",
        "prepare-hidden",
        "show",
    ]
    client.close()


@dataclass
class _ChannelFactory:
    channel: _Channel
    calls: list[tuple[ByteTransport, str | None]] = field(default_factory=list)

    def __call__(
        self,
        transport: ByteTransport,
        *,
        expected_handoff_id: str | None,
        clock: Callable[[], int],
    ) -> _Channel:
        del clock
        self.calls.append((transport, expected_handoff_id))
        return self.channel


@dataclass
class _ManualClock:
    value: float = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _launch_definition(
    tmp_path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> WindowHostLaunch:
    return WindowHostLaunch(
        release_id="release-v2",
        command_prefix=(str(tmp_path / "Stockroom.WindowHost.exe"),),
        working_directory=tmp_path,
        environment=environment,
    )


def _supervisor(
    *,
    server: _Server | None = None,
    launcher: _Launcher | None = None,
    channel: _Channel | None = None,
    credential_factory: Callable[[], str] = lambda: _HANDOFF_CREDENTIAL,
    startup_timeout: float = 0.2,
    command_timeout: float = 0.2,
    stop_timeout: float = 0.2,
    monotonic_clock: Callable[[], float] = supervisor_module.time.monotonic,
    process_id: Callable[[], int] = lambda: _PARENT_PID,
) -> tuple[WindowHostSupervisor, _Server, _Launcher, _Channel]:
    resolved_server = server or _Server()
    resolved_launcher = launcher or _Launcher()
    resolved_channel = channel or _Channel()
    return (
        WindowHostSupervisor(
            pipe_server_factory=lambda pipe_name: (
                resolved_server if pipe_name == _PIPE_NAME else pytest.fail("unexpected pipe name")
            ),
            process_launcher=resolved_launcher,
            channel_factory=_ChannelFactory(resolved_channel),
            pipe_name_factory=lambda: _PIPE_NAME,
            credential_factory=credential_factory,
            process_id=process_id,
            wall_clock=lambda: _NOW,
            monotonic_clock=monotonic_clock,
            startup_timeout_seconds=startup_timeout,
            command_timeout_seconds=command_timeout,
            stop_timeout_seconds=stop_timeout,
        ),
        resolved_server,
        resolved_launcher,
        resolved_channel,
    )


def _launch(
    tmp_path: Path,
    *,
    server: _Server | None = None,
    launcher: _Launcher | None = None,
    channel: _Channel | None = None,
    environment: Mapping[str, str] | None = None,
    credential_factory: Callable[[], str] = lambda: _HANDOFF_CREDENTIAL,
    startup_timeout: float = 0.2,
    command_timeout: float = 0.2,
    stop_timeout: float = 0.2,
    monotonic_clock: Callable[[], float] = supervisor_module.time.monotonic,
    process_id: Callable[[], int] = lambda: _PARENT_PID,
) -> tuple[WindowHostClient, _Server, _Launcher, _Channel]:
    supervisor, resolved_server, resolved_launcher, resolved_channel = _supervisor(
        server=server,
        launcher=launcher,
        channel=channel,
        credential_factory=credential_factory,
        startup_timeout=startup_timeout,
        command_timeout=command_timeout,
        stop_timeout=stop_timeout,
        monotonic_clock=monotonic_clock,
        process_id=process_id,
    )
    client = supervisor.launch(
        _launch_definition(tmp_path, environment=environment),
        handoff_id=_HANDOFF_ID,
        base_url=_BASE_URL,
        api_credential=_API_CREDENTIAL,
    )
    return client, resolved_server, resolved_launcher, resolved_channel


def _rendered_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def test_launch_binds_exact_child_and_sends_secrets_only_in_bootstrap(
    tmp_path: Path,
) -> None:
    environment = {
        "PATH": "safe-path",
        "STOCKROOM_CONFIG_DIR": str(tmp_path / "Config"),
        "STOCKROOM_API_TOKEN": "inherited-token",
        "AWS_ACCESS_KEY_ID": "inherited-access-key",
        "AUTHORIZATION": "inherited-authorization",
        "SAFE_WITH_SECRET": f"prefix-{_API_CREDENTIAL}-suffix",
    }

    client, server, launcher, channel = _launch(
        tmp_path,
        environment=environment,
    )

    assert client.identity.release_id == "release-v2"
    assert client.identity.process_id == _CHILD_PID
    assert client.identity.parent_process_id == _PARENT_PID
    assert client.identity.window_handle == 4500
    assert client.identity.renderer == "edgechromium"
    lease = client.begin_provider_lease(
        "11111111-1111-4111-8111-111111111111",
        staging_root=_STAGING_ROOT,
        component_id="component-9",
        manufacturer="Exact Manufacturer",
        mpn="MPN-9",
        provider_id="digikey",
    )
    assert not hasattr(lease, "endpoint")
    assert lease.staging_root == _STAGING_ROOT
    assert lease.component_id == "component-9"
    assert lease.manufacturer == "Exact Manufacturer"
    assert lease.mpn == "MPN-9"
    assert lease.provider_id == "digikey"
    client.show_provider(lease.lease_id, lease.generation)
    client.hide_provider(lease.lease_id, lease.generation)
    assert client.provider_current_url(lease.lease_id, lease.generation) == (
        "https://provider.example.test/part"
    )
    client.navigate_provider(
        lease.lease_id,
        lease.generation,
        "https://provider.example.test/next",
    )
    assert client.provider_document_state(
        lease.lease_id,
        lease.generation,
        ready_selectors=("#download",),
        ready_texts=("download",),
    )["provider_ready"] is True
    assert client.cancel_provider_downloads(lease.lease_id, lease.generation) == 2
    events = client.provider_download_events(lease.lease_id, lease.generation)
    assert events[0].operation_id == "operation-1"
    assert events[0].result_file_path == r"C:\Capture\model.zip"
    assert events[0].component_id == "component-9"
    assert events[0].manufacturer == "Exact Manufacturer"
    assert events[0].mpn == "MPN-9"
    assert events[0].provider_id == "digikey"
    assert client.release_provider_lease(lease.lease_id, lease.generation) is True
    assert [message.name for message in channel.sent[-9:]] == [
        "provider-lease-begin",
        "provider-show",
        "provider-hide",
        "provider-current-url",
        "provider-navigate",
        "provider-document-state",
        "provider-download-cancel",
        "provider-download-events",
        "provider-lease-release",
    ]
    assert server.accepted_pids == [_CHILD_PID]
    assert channel.expected_names[0] == frozenset({"hello-hidden"})
    bootstrap = channel.sent[0]
    assert bootstrap.name == "bootstrap"
    assert bootstrap.sequence == 1
    assert bootstrap.payload == {
        "release_id": "release-v2",
        "base_url": _BASE_URL,
        "api_credential": _API_CREDENTIAL,
        "handoff_credential": _HANDOFF_CREDENTIAL,
    }
    command, cwd, launched_environment, _flags = launcher.calls[0]
    assert command == (
        str(tmp_path / "Stockroom.WindowHost.exe"),
        "--window-host",
        "--handoff-pipe",
        _PIPE_NAME,
        "--parent-pid",
        str(_PARENT_PID),
    )
    assert cwd == tmp_path.resolve()
    assert launched_environment == {
        "PATH": "safe-path",
        "STOCKROOM_CONFIG_DIR": str(tmp_path / "Config"),
    }
    assert _API_CREDENTIAL not in repr(client)
    assert _HANDOFF_CREDENTIAL not in repr(client)
    assert _API_CREDENTIAL not in repr(bootstrap)
    assert _HANDOFF_CREDENTIAL not in repr(bootstrap)

    client.close()


def test_full_typed_command_surface_and_graceful_shutdown(
    tmp_path: Path,
) -> None:
    client, _server, launcher, channel = _launch(tmp_path)

    client.prepare_hidden()
    hidden_health = client.health()
    snapshot = client.export_session()
    client.show()
    client.focus()
    visible_health = client.health()
    client.shutdown()

    assert hidden_health == WindowHostHealth(
        window_handle=4500,
        current_url=f"{_BASE_URL}/#/components",
        hidden=True,
        visible=False,
        renderer="edgechromium",
    )
    assert snapshot == {"route": "components", "event": 7}
    assert visible_health.hidden is False
    assert visible_health.visible is True
    assert [message.name for message in channel.sent] == [
        "bootstrap",
        "prepare-hidden",
        "health",
        "export",
        "show",
        "focus",
        "health",
        "shutdown",
    ]
    assert [message.sequence for message in channel.sent] == list(range(1, 9))
    assert all(message.deadline_unix_ms == _NOW + 200 for message in channel.sent[1:])
    assert channel.closed
    assert launcher.process.wait_calls
    assert len(launcher.job.timeout_calls) == 1
    assert not client.active
    with pytest.raises(WindowSupervisorError, match="not active"):
        client.health()
    client.close()
    assert len(launcher.job.timeout_calls) == 1


def test_context_manager_forcibly_reaps_the_exact_child(tmp_path: Path) -> None:
    client, _server, launcher, channel = _launch(tmp_path)

    with client as entered:
        assert entered is client
        entered.prepare_hidden()

    assert channel.closed
    assert len(launcher.job.timeout_calls) == 1
    assert launcher.process.wait_calls
    assert not client.active


def test_wait_for_exit_blocks_on_the_exact_child_and_finalizes_clean_exit(
    tmp_path: Path,
) -> None:
    process = _Process(wait_plan=[0])
    launcher = _Launcher(process=process)
    client, _server, _launcher, channel = _launch(
        tmp_path,
        launcher=launcher,
    )

    exit_code = client.wait_for_exit()

    assert exit_code == 0
    assert process.wait_calls == [None]
    assert len(launcher.job.timeout_calls) == 1
    assert channel.closed
    assert not client.active
    assert "state='stopped'" in repr(client)
    assert client.wait_for_exit(timeout=0) == 0
    assert process.wait_calls == [None]


def test_wait_for_exit_timeout_is_distinct_and_nonbusy(
    tmp_path: Path,
) -> None:
    process = _Process(
        wait_plan=[
            subprocess.TimeoutExpired("child", 0.05),
            0,
        ]
    )
    launcher = _Launcher(process=process)
    client, *_ = _launch(tmp_path, launcher=launcher)

    assert client.wait_for_exit(timeout=0.05) is None

    assert client.active
    assert process.wait_calls == [0.05]
    assert launcher.job.timeout_calls == []
    assert client.wait_for_exit(timeout=1.0) == 0
    assert process.wait_calls == [0.05, 1.0]


def test_wait_for_exit_marks_unauthenticated_user_close_failed(
    tmp_path: Path,
) -> None:
    process = _Process(wait_plan=[1])
    launcher = _Launcher(process=process)
    client, *_ = _launch(tmp_path, launcher=launcher)

    assert client.wait_for_exit(timeout=1.0) == 1

    assert not client.active
    assert "state='failed'" in repr(client)
    assert launcher.job.timeout_calls


def test_wait_for_exit_invalid_process_result_fails_closed_and_reaps(
    tmp_path: Path,
) -> None:
    process = _Process(wait_plan=[True, 1])
    launcher = _Launcher(process=process)
    client, *_ = _launch(tmp_path, launcher=launcher)

    with pytest.raises(
        WindowSupervisorProcessError,
        match="invalid exit status",
    ):
        client.wait_for_exit(timeout=1.0)

    assert not client.active
    assert launcher.job.timeout_calls
    assert len(process.wait_calls) == 2


def test_wait_for_exit_retries_job_cleanup_after_observing_child_exit(
    tmp_path: Path,
) -> None:
    process = _Process(wait_plan=[0, 0])
    job = _Job(errors=[RuntimeError("first job close failed")])
    launcher = _Launcher(process=process, job=job)
    client, *_ = _launch(tmp_path, launcher=launcher)

    with pytest.raises(
        WindowSupervisorProcessError,
        match="job could not be closed",
    ):
        client.wait_for_exit(timeout=1.0)

    assert len(job.timeout_calls) == 2
    assert len(process.wait_calls) == 2
    assert not client.active


def test_blocking_wait_is_released_by_concurrent_forced_close(
    tmp_path: Path,
) -> None:
    class _ConcurrentProcess(_Process):
        def __init__(self) -> None:
            super().__init__()
            self.wait_started = threading.Event()
            self.release_wait = threading.Event()

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls.append(timeout)
            self.wait_started.set()
            wait_seconds = 2.0 if timeout is None else timeout
            if not self.release_wait.wait(wait_seconds):
                raise subprocess.TimeoutExpired("child", wait_seconds)
            self.poll_result = 1
            return 1

    process = _ConcurrentProcess()
    job = _Job(on_terminate=lambda timeout: process.release_wait.set())
    launcher = _Launcher(process=process, job=job)
    client, *_ = _launch(tmp_path, launcher=launcher)
    results: list[int | None] = []
    failures: list[BaseException] = []

    def wait_for_child() -> None:
        try:
            results.append(client.wait_for_exit())
        except BaseException as exc:
            failures.append(exc)

    waiter = threading.Thread(target=wait_for_child)
    waiter.start()
    assert process.wait_started.wait(1.0)

    client.close()
    waiter.join(1.0)

    assert not waiter.is_alive()
    assert failures == []
    assert results == [1]
    assert not client.active


@pytest.mark.parametrize("timeout", [-1, float("inf"), 301, "1"])
def test_wait_for_exit_rejects_invalid_timeout_without_touching_process(
    tmp_path: Path,
    timeout: object,
) -> None:
    launcher = _Launcher()
    client, *_ = _launch(tmp_path, launcher=launcher)

    with pytest.raises(ValueError, match="nonnegative"):
        client.wait_for_exit(cast(float, timeout))

    assert launcher.process.wait_calls == []
    assert client.active
    client.close()


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--window-host", "--window-host=true"),
        ("--handoff-pipe", "--handoff-pipe=attacker"),
        ("--parent-pid", "--parent-pid=999"),
    ],
)
def test_command_prefix_cannot_smuggle_reserved_child_flags(
    tmp_path: Path,
    flag: str,
    value: str,
) -> None:
    del flag
    with pytest.raises(ValueError, match="command prefix"):
        WindowHostLaunch(
            release_id="release-v2",
            command_prefix=("Stockroom.WindowHost.exe", value),
            working_directory=tmp_path,
        )


def test_environment_sanitizer_removes_credential_like_keys_and_values() -> None:
    result = sanitized_window_host_environment(
        {
            "PATH": "safe",
            "API-KEY": "value",
            "PRIVATE_KEY_FILE": "value",
            "Authorization": "value",
            "Cookie": "value",
            "SAFE": f"x{_API_CREDENTIAL}y",
        },
        forbidden_values=(_API_CREDENTIAL,),
    )

    assert result == {"PATH": "safe"}


@pytest.mark.parametrize(
    ("hello_change", "message"),
    [
        ({"hidden": False}, "start hidden"),
        ({"release_id": "other-release"}, "identity is incoherent"),
        ({"process_id": 999}, "identity is incoherent"),
        ({"parent_process_id": 999}, "identity is incoherent"),
        ({"window_handle": 0}, "identity values are invalid"),
        ({"profile_id": "shared"}, "identity values are invalid"),
        ({"renderer": "cef"}, "identity values are invalid"),
        ({"proof": "0" * 64}, "proof is invalid"),
    ],
)
def test_invalid_hello_fails_closed_and_reaps_child(
    tmp_path: Path,
    hello_change: dict[str, object],
    message: str,
) -> None:
    launcher = _Launcher()
    channel = _Channel(hello_changes=hello_change)

    with pytest.raises(WindowSupervisorProtocolError, match=message):
        _launch(tmp_path, launcher=launcher, channel=channel)

    assert channel.closed
    assert len(launcher.job.timeout_calls) == 1
    assert len(launcher.process.wait_calls) == 1


def test_channel_peer_identity_change_fails_closed(tmp_path: Path) -> None:
    launcher = _Launcher()
    channel = _Channel(peer_process_id=999)

    with pytest.raises(WindowSupervisorProtocolError, match="identity changed"):
        _launch(tmp_path, launcher=launcher, channel=channel)

    assert channel.closed
    assert len(launcher.job.timeout_calls) == 1
    assert launcher.process.wait_calls


@pytest.mark.parametrize(
    ("poll_plan", "message", "bootstrap_count"),
    [
        ([3], "pipe connection", 0),
        ([None, 3], "credential bootstrap", 0),
        ([None, None, 3], "client adoption", 1),
        ([True], "state was invalid", 0),
    ],
)
def test_child_must_still_be_the_live_launched_process_at_each_startup_boundary(
    tmp_path: Path,
    poll_plan: list[object],
    message: str,
    bootstrap_count: int,
) -> None:
    process = _Process(poll_plan=list(poll_plan))
    launcher = _Launcher(process=process)
    channel = _Channel()

    with pytest.raises(WindowSupervisorProcessError, match=message):
        _launch(tmp_path, launcher=launcher, channel=channel)

    assert len(channel.sent) == bootstrap_count
    assert launcher.job.timeout_calls
    assert launcher.process.wait_calls


@pytest.mark.parametrize(
    ("channel", "message"),
    [
        (
            _Channel(response_name_changes={"bootstrap": "health"}),
            "hello name is invalid",
        ),
        (
            _Channel(
                hello_changes={"future": True},
            ),
            "result fields are invalid",
        ),
    ],
)
def test_hello_protocol_shape_is_strict(
    tmp_path: Path,
    channel: _Channel,
    message: str,
) -> None:
    launcher = _Launcher()

    with pytest.raises(WindowSupervisorProtocolError, match=message):
        _launch(tmp_path, launcher=launcher, channel=channel)

    assert channel.closed
    assert launcher.process.wait_calls


@pytest.mark.parametrize(
    ("channel", "message"),
    [
        (
            _Channel(response_sequence_changes={"health": 999}),
            "correlation is invalid",
        ),
        (
            _Channel(response_name_changes={"health": "shown"}),
            "response name is invalid",
        ),
        (
            _Channel(response_changes={"health": {"future": True}}),
            "result fields are invalid",
        ),
        (
            _Channel(response_changes={"health": {"hwnd": 999}}),
            "identity is incoherent",
        ),
        (
            _Channel(response_changes={"health": {"current_url": "http://127.0.0.1:9999/"}}),
            "identity is incoherent",
        ),
        (
            _Channel(response_changes={"health": {"hidden": True, "visible": True}}),
            "values are invalid",
        ),
    ],
)
def test_command_protocol_failures_abort_and_reap(
    tmp_path: Path,
    channel: _Channel,
    message: str,
) -> None:
    launcher = _Launcher()
    client, _server, _launcher, _channel = _launch(
        tmp_path,
        launcher=launcher,
        channel=channel,
    )

    with pytest.raises(WindowSupervisorProtocolError, match=message):
        client.health()

    assert channel.closed
    assert launcher.job.timeout_calls
    assert launcher.process.wait_calls
    assert not client.active


def test_sanitized_child_command_error_aborts_and_reaps(tmp_path: Path) -> None:
    launcher = _Launcher()
    channel = _Channel(command_errors={"show"})
    client, *_ = _launch(tmp_path, launcher=launcher, channel=channel)

    with pytest.raises(
        WindowSupervisorProtocolError,
        match="child rejected a command",
    ):
        client.show()

    assert channel.closed
    assert launcher.job.timeout_calls
    assert launcher.process.wait_calls


@pytest.mark.parametrize("reflected", [_API_CREDENTIAL, _HANDOFF_CREDENTIAL])
def test_child_cannot_reflect_credentials_through_export(
    tmp_path: Path,
    reflected: str,
) -> None:
    launcher = _Launcher()
    channel = _Channel(response_changes={"export": {"snapshot": {"debug": reflected}}})
    client, *_ = _launch(tmp_path, launcher=launcher, channel=channel)

    with pytest.raises(
        WindowSupervisorProtocolError,
        match="contained a credential",
    ) as error:
        client.export_session()

    rendered = _rendered_exception(error.value)
    assert _API_CREDENTIAL not in rendered
    assert _HANDOFF_CREDENTIAL not in rendered
    assert channel.closed
    assert launcher.process.wait_calls


def test_child_cannot_reflect_credentials_through_hello(tmp_path: Path) -> None:
    launcher = _Launcher()
    channel = _Channel(hello_changes={"profile_id": _API_CREDENTIAL})

    with pytest.raises(
        WindowSupervisorProtocolError,
        match="contained a credential",
    ) as error:
        _launch(tmp_path, launcher=launcher, channel=channel)

    assert _API_CREDENTIAL not in _rendered_exception(error.value)
    assert channel.closed
    assert launcher.process.wait_calls


def test_accept_timeout_closes_late_connection_and_reaps_once(
    tmp_path: Path,
) -> None:
    server = _BlockingServer(return_after_close=True)
    launcher = _Launcher()
    supervisor, *_ = _supervisor(
        server=server,
        launcher=launcher,
        startup_timeout=0.01,
        stop_timeout=0.1,
    )

    with pytest.raises(WindowSupervisorTimeout) as error:
        supervisor.launch(
            _launch_definition(tmp_path),
            handoff_id=_HANDOFF_ID,
            base_url=_BASE_URL,
            api_credential=_API_CREDENTIAL,
        )

    assert error.value.phase == "pipe-accept"
    assert server.close_calls >= 1
    assert server.transport.closed
    assert len(launcher.job.timeout_calls) == 1
    assert len(launcher.process.wait_calls) == 1
    assert launcher.process.kill_calls == 0


def test_accept_timeout_reports_a_late_connection_disposal_failure(
    tmp_path: Path,
) -> None:
    server = _BlockingServer(return_after_close=True)
    server.transport.close_error = RuntimeError("close failed")
    launcher = _Launcher()
    supervisor, *_ = _supervisor(
        server=server,
        launcher=launcher,
        startup_timeout=0.01,
        stop_timeout=0.1,
    )

    with pytest.raises(
        WindowSupervisorProcessError,
        match="timeout cleanup failed during pipe-accept",
    ):
        supervisor.launch(
            _launch_definition(tmp_path),
            handoff_id=_HANDOFF_ID,
            base_url=_BASE_URL,
            api_credential=_API_CREDENTIAL,
        )

    assert server.transport.closed
    assert launcher.process.wait_calls


def test_accept_timeout_does_not_silently_ignore_a_stuck_pipe_worker(
    tmp_path: Path,
) -> None:
    server = _StubbornServer()
    launcher = _Launcher()
    supervisor, *_ = _supervisor(
        server=server,
        launcher=launcher,
        startup_timeout=0.01,
        stop_timeout=0.1,
    )

    try:
        with pytest.raises(
            WindowSupervisorProcessError,
            match="timeout cleanup failed during pipe-accept",
        ):
            supervisor.launch(
                _launch_definition(tmp_path),
                handoff_id=_HANDOFF_ID,
                base_url=_BASE_URL,
                api_credential=_API_CREDENTIAL,
            )
    finally:
        server.release()

    assert server.transport.closed_event.wait(1.0)
    assert launcher.process.wait_calls


def test_command_timeout_closes_pipe_and_reaps_exact_child(
    tmp_path: Path,
) -> None:
    launcher = _Launcher()
    channel = _Channel(block_on="health")
    client, *_ = _launch(
        tmp_path,
        launcher=launcher,
        channel=channel,
        command_timeout=0.01,
        stop_timeout=0.1,
    )

    with pytest.raises(WindowSupervisorTimeout) as error:
        client.health()

    assert error.value.phase == "health"
    assert channel.closed
    assert len(launcher.job.timeout_calls) == 1
    assert len(launcher.process.wait_calls) == 1
    assert not client.active


def test_expired_pipe_message_is_protocol_failure_and_reaps_child(
    tmp_path: Path,
) -> None:
    launcher = _Launcher()
    channel = _Channel(receive_error=HandoffDeadlineExpired("message deadline expired"))

    with pytest.raises(WindowSupervisorProtocolError, match="launch protocol"):
        _launch(tmp_path, launcher=launcher, channel=channel)

    assert channel.closed
    assert launcher.process.wait_calls


def test_forced_cleanup_uses_one_total_stop_budget(tmp_path: Path) -> None:
    clock = _ManualClock()
    process = _Process()
    job = _Job(on_terminate=clock.advance)
    launcher = _Launcher(process=process, job=job)
    client, *_ = _launch(
        tmp_path,
        launcher=launcher,
        stop_timeout=0.2,
        monotonic_clock=clock,
    )

    client.close()

    assert job.timeout_calls == pytest.approx([0.15])
    assert process.wait_calls == pytest.approx([0.05])
    assert sum(cast(list[float], job.timeout_calls + process.wait_calls)) == pytest.approx(0.2)


def test_wait_failure_kills_and_reaps_root_within_remaining_budget(
    tmp_path: Path,
) -> None:
    timeout = subprocess.TimeoutExpired("child", 0.1)
    process = _Process(wait_plan=[timeout, 1])
    launcher = _Launcher(process=process)
    client, *_ = _launch(tmp_path, launcher=launcher)

    client.close()

    assert process.kill_calls == 1
    assert len(process.wait_calls) == 2


def test_failed_cleanup_can_be_retried_by_close(tmp_path: Path) -> None:
    process = _Process(
        wait_plan=[
            subprocess.TimeoutExpired("child", 0.1),
            subprocess.TimeoutExpired("child", 0.1),
            1,
        ],
        on_kill=lambda: (
            (_ for _ in ()).throw(RuntimeError("first kill failed"))
            if process.kill_calls == 1
            else None
        ),
    )
    job = _Job(errors=[RuntimeError("first job failure")])
    launcher = _Launcher(process=process, job=job)
    client, *_ = _launch(tmp_path, launcher=launcher)

    with pytest.raises(WindowSupervisorProcessError, match="cleanup was incomplete"):
        client.close()

    client.close()

    assert len(job.timeout_calls) == 2
    assert process.kill_calls == 2
    assert len(process.wait_calls) == 3
    assert not client.active


@pytest.mark.parametrize(
    "source",
    [
        "credential-factory",
        "process-launcher",
        "typed-process-launcher",
        "process-id",
        "process-poll",
        "command-channel",
        "shutdown-channel",
        "cleanup-job",
    ],
)
def test_dependency_errors_cannot_leak_fresh_credentials(
    tmp_path: Path,
    source: str,
) -> None:
    secret_error = RuntimeError(f"dependency echoed {_API_CREDENTIAL} and {_HANDOFF_CREDENTIAL}")
    launcher = _Launcher()
    channel = _Channel()

    with pytest.raises(WindowSupervisorError) as captured:
        if source == "credential-factory":
            _launch(
                tmp_path,
                credential_factory=lambda: (_ for _ in ()).throw(secret_error),
            )
        elif source == "process-launcher":
            launcher.error = secret_error
            _launch(tmp_path, launcher=launcher)
        elif source == "typed-process-launcher":
            launcher.error = WindowSupervisorProcessError(str(secret_error))
            _launch(tmp_path, launcher=launcher)
        elif source == "process-id":
            _launch(
                tmp_path,
                process_id=lambda: (_ for _ in ()).throw(secret_error),
            )
        elif source == "process-poll":
            launcher.process.poll_plan.append(secret_error)
            _launch(tmp_path, launcher=launcher)
        elif source == "command-channel":
            client, *_ = _launch(tmp_path, launcher=launcher, channel=channel)
            channel.receive_error = secret_error
            client.health()
        elif source == "shutdown-channel":
            client, *_ = _launch(tmp_path, launcher=launcher, channel=channel)
            channel.close_error = WindowSupervisorProtocolError(str(secret_error))
            client.shutdown()
        else:
            client, *_ = _launch(tmp_path, launcher=launcher, channel=channel)
            launcher.job.errors.append(secret_error)
            client.close()

    rendered = _rendered_exception(captured.value)
    assert _API_CREDENTIAL not in rendered
    assert _HANDOFF_CREDENTIAL not in rendered


def _accepted_release(
    root: Path,
    *,
    release_id: str = "release-v2",
    window_host_paths: tuple[str, ...] = ("WindowHost/Stockroom.WindowHost.exe",),
    member_kind: str = "window-host",
    member_map: Mapping[str, Path] | None = None,
    manifest_release_id: str | None = None,
) -> AcceptedRelease:
    members = tuple(
        ReleaseMember(
            path=path,
            size=0,
            sha256="0" * 64,
            kind=member_kind,
        )
        for path in window_host_paths
    )
    manifest = cast(
        ReleaseManifest,
        SimpleNamespace(
            release_id=manifest_release_id or release_id,
            members=members,
        ),
    )
    mapping = (
        {path: root.joinpath(*path.split("/")) for path in window_host_paths}
        if member_map is None
        else dict(member_map)
    )
    return AcceptedRelease(
        release_id=release_id,
        directory=root,
        manifest_path=root / "Release Manifest.json",
        manifest_sha256="1" * 64,
        manifest=manifest,
        members=mapping,
    )


def test_window_launch_resolves_exact_accepted_native_member(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release-v2"
    executable = root / "WindowHost" / "Stockroom.WindowHost.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"frozen")
    release = _accepted_release(root)

    launch = WindowHostLaunch.from_release(release)

    assert launch == WindowHostLaunch(
        release_id="release-v2",
        command_prefix=(str(executable.resolve()),),
        working_directory=root.resolve(),
    )


@pytest.mark.parametrize(
    ("window_host_paths", "message"),
    [
        ((), "exactly one"),
        (
            (
                "WindowHost/Stockroom.WindowHost.exe",
                "Other/Stockroom.WindowHost.exe",
            ),
            "exactly one",
        ),
    ],
)
def test_accepted_release_requires_exactly_one_native_window_host(
    tmp_path: Path,
    window_host_paths: tuple[str, ...],
    message: str,
) -> None:
    release = _accepted_release(
        tmp_path,
        window_host_paths=window_host_paths,
    )

    with pytest.raises(WindowSupervisorProcessError, match=message):
        WindowHostLaunch.from_release(release)


def test_accepted_release_never_falls_back_to_the_legacy_backend_worker(
    tmp_path: Path,
) -> None:
    release = _accepted_release(
        tmp_path,
        member_kind="backend",
    )

    with pytest.raises(WindowSupervisorProcessError, match="exactly one"):
        WindowHostLaunch.from_release(release)


def test_accepted_release_requires_the_canonical_native_member_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release-v2"
    executable = root / "Other" / "Stockroom.WindowHost.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"native")
    release = _accepted_release(
        root,
        window_host_paths=("Other/Stockroom.WindowHost.exe",),
    )

    with pytest.raises(WindowSupervisorProcessError, match="canonical native"):
        WindowHostLaunch.from_release(release)


def test_accepted_release_member_map_must_match_declared_exact_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release-v2"
    declared = root / "WindowHost" / "Stockroom.WindowHost.exe"
    substituted = root / "Other" / "Stockroom.WindowHost.exe"
    declared.parent.mkdir(parents=True)
    substituted.parent.mkdir(parents=True)
    declared.write_bytes(b"declared")
    substituted.write_bytes(b"substituted")
    release = _accepted_release(
        root,
        member_map={"WindowHost/Stockroom.WindowHost.exe": substituted},
    )

    with pytest.raises(WindowSupervisorProcessError, match="exact frozen"):
        WindowHostLaunch.from_release(release)


def test_accepted_release_rejects_missing_outside_or_wrong_member(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release-v2"
    root.mkdir()
    missing = _accepted_release(root, member_map={})
    declared = root / "WindowHost" / "Stockroom.WindowHost.exe"
    declared.parent.mkdir()
    declared.write_bytes(b"declared")
    outside_path = tmp_path / "Stockroom.WindowHost.exe"
    outside_path.write_bytes(b"outside")
    outside = _accepted_release(
        root,
        member_map={"WindowHost/Stockroom.WindowHost.exe": outside_path},
    )
    wrong = root / "WindowHost" / "Other.exe"
    wrong.write_bytes(b"wrong")
    wrong_name = _accepted_release(
        root,
        member_map={"WindowHost/Stockroom.WindowHost.exe": wrong},
    )

    with pytest.raises(WindowSupervisorProcessError, match="not accepted"):
        WindowHostLaunch.from_release(missing)
    with pytest.raises(WindowSupervisorProcessError, match="escaped"):
        WindowHostLaunch.from_release(outside)
    with pytest.raises(WindowSupervisorProcessError, match="exact frozen"):
        WindowHostLaunch.from_release(wrong_name)


def test_accepted_release_identity_must_be_coherent(tmp_path: Path) -> None:
    release = _accepted_release(tmp_path, manifest_release_id="other-release")

    with pytest.raises(WindowSupervisorProcessError, match="identity is incoherent"):
        WindowHostLaunch.from_release(release)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("startup_timeout_seconds", 0),
        ("command_timeout_seconds", float("inf")),
        ("stop_timeout_seconds", 301),
    ],
)
def test_supervisor_rejects_invalid_timeout_configuration(
    name: str,
    value: float,
) -> None:
    with pytest.raises(ValueError, match="positive"):
        if name == "startup_timeout_seconds":
            WindowHostSupervisor(startup_timeout_seconds=value)
        elif name == "command_timeout_seconds":
            WindowHostSupervisor(command_timeout_seconds=value)
        else:
            WindowHostSupervisor(stop_timeout_seconds=value)


def _download_event(**changes: object) -> dict[str, object]:
    event: dict[str, object] = {
        "sequence": 19,
        "lease_id": "lease-a",
        "generation": 7,
        "component_id": "component-9",
        "manufacturer": "Exact Manufacturer",
        "mpn": "MPN-9",
        "provider_id": "digikey",
        "operation_id": "operation-1",
        "phase": "progress",
        "state": "in_progress",
        "uri": "https://provider.example.test/model.zip",
        "suggested_file_name": "CON.step",
        "result_file_path": r"C:\Capture\Downloads\task-1\operation-1\_CON.step",
        "mime_type": "application/zip",
        "interrupt_reason": "",
        "total_bytes": 120,
        "bytes_received": 60,
    }
    event.update(changes)
    return event


@pytest.mark.parametrize("phase", ["started", "progress", "terminal"])
def test_download_event_phase_vocabulary_includes_bounded_progress(phase: str) -> None:
    parsed = supervisor_module._parse_provider_download_event(
        _download_event(phase=phase),
        "lease-a",
        7,
    )

    assert parsed.phase == phase
    assert parsed.component_id == "component-9"
    assert parsed.manufacturer == "Exact Manufacturer"
    assert parsed.mpn == "MPN-9"
    assert parsed.provider_id == "digikey"
    # The sanitized name on disk never overwrites the name the provider actually suggested.
    assert parsed.suggested_file_name == "CON.step"
    assert parsed.result_file_path.endswith("_CON.step")


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"phase": "cancelled"}, "state is invalid"),
        ({"phase": ""}, "state is invalid"),
        ({"state": "downloading"}, "state is invalid"),
        ({"component_id": None}, "text is invalid"),
        ({"manufacturer": 7}, "text is invalid"),
        ({"mpn": ["MPN-9"]}, "text is invalid"),
        ({"provider_id": b"digikey"}, "text is invalid"),
        ({"component_id": "a" * 257}, "component identity is invalid"),
        ({"manufacturer": "Exact\u0000Manufacturer"}, "component identity is invalid"),
        ({"mpn": "MPN\u001f9"}, "component identity is invalid"),
        ({"provider_id": "digikey\u007f"}, "component identity is invalid"),
    ],
)
def test_malformed_download_event_fields_raise_instead_of_passing_through(
    changes: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(WindowSupervisorProtocolError, match=match):
        supervisor_module._parse_provider_download_event(
            _download_event(**changes),
            "lease-a",
            7,
        )


@pytest.mark.parametrize("name", ["component_id", "manufacturer", "mpn", "provider_id"])
def test_a_download_event_missing_its_component_identity_is_refused(name: str) -> None:
    event = _download_event()
    del event[name]

    with pytest.raises(WindowSupervisorProtocolError, match="fields are invalid"):
        supervisor_module._parse_provider_download_event(event, "lease-a", 7)


def test_a_late_download_event_never_attaches_to_another_lease_or_generation() -> None:
    late = _download_event(phase="terminal", state="interrupted")

    with pytest.raises(WindowSupervisorProtocolError, match="lease is invalid"):
        supervisor_module._parse_provider_download_event(late, "lease-a", 8)
    with pytest.raises(WindowSupervisorProtocolError, match="lease is invalid"):
        supervisor_module._parse_provider_download_event(late, "lease-b", 7)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("staging_root", "Relative/Staging"),
        ("staging_root", " " + _STAGING_ROOT),
        ("staging_root", _STAGING_ROOT + "\u0001"),
        ("staging_root", str(Path(_STAGING_ROOT) / ("a" * 240))),
        ("staging_root", 7),
        ("component_id", "a" * 257),
        ("manufacturer", "Exact\u0000Manufacturer"),
        ("mpn", None),
        ("provider_id", "digikey\u007f"),
    ],
)
def test_lease_handshake_refuses_a_malformed_scope_before_touching_the_child(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    client, _server, _launcher, channel = _launch(tmp_path)
    before = len(channel.sent)

    with pytest.raises(ValueError):
        client.begin_provider_lease(
            "11111111-1111-4111-8111-111111111111",
            **{field_name: value},
        )

    assert len(channel.sent) == before
    client.close()


def test_lease_handshake_allows_an_unknown_staging_root_and_sends_it_empty(
    tmp_path: Path,
) -> None:
    channel = _Channel()
    channel.expect_lease_scope = {
        "lease_id": "11111111-1111-4111-8111-111111111111",
        "staging_root": "",
        "component_id": "",
        "manufacturer": "",
        "mpn": "",
        "provider_id": "",
    }
    client, _server, _launcher, _channel = _launch(tmp_path, channel=channel)

    lease = client.begin_provider_lease("11111111-1111-4111-8111-111111111111")

    assert lease.staging_root == ""
    assert lease.component_id == ""
    assert channel.sent[-1].payload == channel.expect_lease_scope
    client.close()


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows process job")
def test_real_windows_job_termination_reaps_the_launched_root(
    tmp_path: Path,
) -> None:
    process, job = launch_in_windows_job(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ],
        cwd=tmp_path,
        environment={"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows")},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    owned = supervisor_module._OwnedWindowProcess(
        process,
        job,
        monotonic_clock=supervisor_module.time.monotonic,
    )
    try:
        owned.terminate_and_reap(timeout=5.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)

    assert process.poll() is not None


def test_shell_bridge_carries_a_resolved_root_and_never_a_program_path(
    tmp_path: Path,
) -> None:
    """The three shell commands, and the shape of what they are allowed to send.

    The window host resolves an application id to a binary itself, so nothing this client sends
    names a program. Every path it sends arrives with the root it must stay inside, which is what
    lets the far side refuse an escape independently rather than trusting this one.
    """

    client, _server, _launcher, channel = _launch(tmp_path)

    assert client.detected_eda_applications() == (
        {"id": "kicad", "name": "KiCad 9.0", "version": "9.0.1"},
    )
    client.reveal_directory(_LIBRARY_ROOT, _COMPONENT_DIRECTORY)
    client.open_file_with_eda_application("kicad", _EXPORT_ROOT, _EXPORTED_FILE)

    assert [message.name for message in channel.sent[-3:]] == [
        "eda-applications",
        "shell-reveal",
        "eda-open",
    ]
    shell_messages = [
        message
        for message in channel.sent
        if message.name in {"eda-applications", "shell-reveal", "eda-open"}
    ]
    assert shell_messages
    assert all(".exe" not in str(message.payload).lower() for message in shell_messages)


@pytest.mark.parametrize(
    "path",
    [
        "",
        # Relative: what it means depends on the host's working directory.
        r"sourced\part-1",
        # A UNC share is not a local path and can be anything on any machine.
        r"\\server\share\part-1",
        # The Win32 device namespace bypasses normalisation entirely.
        r"\\?\C:\part-1",
        # A traversal segment, which is the shape the boundary exists for.
        r"C:\Libraries\..\Windows",
        # Quotes and wildcards have no business in a resolved path.
        r'C:\Libraries\"quoted"',
        r"C:\Libraries\*",
        # A control character truncates the string for anything below the managed layer.
        "C:\\Libraries\\a\tb",
        # Untrimmed: an exact path has no surrounding whitespace.
        r" C:\Libraries ",
    ],
)
def test_reveal_refuses_a_path_that_is_not_an_exact_absolute_local_path(
    tmp_path: Path,
    path: str,
) -> None:
    client, _server, _launcher, channel = _launch(tmp_path)
    before = len(channel.sent)

    with pytest.raises(ValueError):
        client.reveal_directory(_LIBRARY_ROOT, path)

    # Refused BEFORE anything went down the pipe. A rejected path is never a message the host
    # has to be trusted to turn down.
    assert len(channel.sent) == before


def test_open_refuses_an_application_id_that_is_not_a_stable_identifier(
    tmp_path: Path,
) -> None:
    client, _server, _launcher, channel = _launch(tmp_path)
    before = len(channel.sent)

    for application_id in ("", r"C:\Windows\System32\cmd.exe", "KiCad", "kicad;calc"):
        with pytest.raises(ValueError):
            client.open_file_with_eda_application(
                application_id,
                _EXPORT_ROOT,
                _EXPORTED_FILE,
            )

    assert len(channel.sent) == before
