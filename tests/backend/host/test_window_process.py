from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from stockroom.host.window_process import (
    WindowHostArguments,
    WindowHostBootstrap,
    WindowHostCommandError,
    WindowHostError,
    bootstrap_proof,
    create_unique_window_profile,
    parse_bootstrap,
    parse_window_host_arguments,
    run_window_host,
)
from stockroom.host.windows_handoff_pipe import (
    HandoffMessage,
    HandoffProtocolError,
)

_HANDOFF_ID = "2ed594a5-e46d-4fc0-aecb-17ca94aab32f"
_PIPE_NAME = "Stockroom.WindowHandoff." + "a" * 32
_API_CREDENTIAL = "A" * 43
_HANDOFF_CREDENTIAL = "B" * 42 + "Q"
_NOW = 1_800_000_000_000
_PARENT_PID = 111
_CHILD_PID = 222


def _message(
    sequence: int,
    name: str,
    payload: dict[str, object] | None = None,
) -> HandoffMessage:
    return HandoffMessage(
        handoff_id=_HANDOFF_ID,
        sequence=sequence,
        deadline_unix_ms=_NOW + 30_000,
        name=name,
        payload=payload or {},
    )


def _bootstrap_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "release_id": "release-v2",
        "base_url": "http://127.0.0.1:43210/",
        "api_credential": _API_CREDENTIAL,
        "handoff_credential": _HANDOFF_CREDENTIAL,
    }
    payload.update(changes)
    return payload


def _frame(message: HandoffMessage) -> bytes:
    body = message.encode(now_unix_ms=_NOW)
    return struct.pack("<I", len(body)) + body


def _decode_frames(data: bytes) -> list[HandoffMessage]:
    messages: list[HandoffMessage] = []
    offset = 0
    while offset < len(data):
        (size,) = struct.unpack("<I", data[offset : offset + 4])
        offset += 4
        body = data[offset : offset + size]
        offset += size
        messages.append(HandoffMessage.decode(body, now_unix_ms=_NOW))
    assert offset == len(data)
    return messages


@dataclass
class _Connection:
    incoming: bytearray
    peer_process_id: int = _PARENT_PID
    written: bytearray = field(default_factory=bytearray)
    closed: bool = False

    def read_exact(self, size: int) -> bytes:
        result = bytes(self.incoming[:size])
        del self.incoming[:size]
        return result

    def write_all(self, data: bytes) -> None:
        self.written.extend(data)

    def close(self) -> None:
        self.closed = True


@dataclass
class _Connector:
    connection: _Connection
    calls: list[tuple[str, int]] = field(default_factory=list)

    def __call__(
        self,
        pipe_name: str,
        *,
        expected_server_pid: int,
        timeout_ms: int = 15_000,
    ) -> _Connection:
        assert timeout_ms == 15_000
        self.calls.append((pipe_name, expected_server_pid))
        return self.connection


@dataclass
class _Controller:
    window_handle: int = 4500
    operations: list[object] = field(default_factory=list)
    health_result: dict[str, object] = field(
        default_factory=lambda: {
            "release_id": "release-v2",
            "hidden": True,
            "visible": False,
            "current_url": "http://127.0.0.1:43210",
            "renderer": "edgechromium",
        }
    )
    export_result: object = field(
        default_factory=lambda: {
            "schema": "stockroom.ui-session",
            "version": 1,
        }
    )

    def prepare_hidden(self, *, deadline_unix_ms: int) -> None:
        self.operations.append(("prepare-hidden", deadline_unix_ms))

    def show(self) -> None:
        self.operations.append("show")

    def focus(self) -> None:
        self.operations.append("focus")

    def health(self) -> dict[str, object]:
        self.operations.append("health")
        return self.health_result

    def export_session(self) -> object:
        self.operations.append("export")
        return self.export_result

    def shutdown(self) -> None:
        self.operations.append("shutdown")


@dataclass
class _Runner:
    controller: _Controller
    calls: list[dict[str, object]] = field(default_factory=list)
    invoke_loop: bool = True

    def __call__(
        self,
        *,
        base_url: str,
        api_credential: str,
        profile_dir: Path,
        command_loop,
    ) -> None:
        self.calls.append(
            {
                "base_url": base_url,
                "api_credential": api_credential,
                "profile_dir": profile_dir,
            }
        )
        if self.invoke_loop:
            command_loop(self.controller)


def _connection_with_commands(
    *commands: tuple[str, dict[str, object]],
    bootstrap_payload: dict[str, object] | None = None,
) -> _Connection:
    messages = [
        _message(
            1,
            "bootstrap",
            bootstrap_payload or _bootstrap_payload(),
        )
    ]
    messages.extend(
        _message(index, name, payload) for index, (name, payload) in enumerate(commands, start=2)
    )
    return _Connection(incoming=bytearray(b"".join(_frame(message) for message in messages)))


def test_exact_window_host_argv_contains_only_pipe_name_and_parent_pid() -> None:
    parsed = parse_window_host_arguments(
        [
            "--window-host",
            "--handoff-pipe",
            _PIPE_NAME,
            "--parent-pid",
            str(_PARENT_PID),
        ]
    )

    assert parsed == WindowHostArguments(
        pipe_name=_PIPE_NAME,
        parent_process_id=_PARENT_PID,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--window-host", "--handoff-pipe", _PIPE_NAME],
        [
            "--window-host",
            "--handoff-pipe",
            _PIPE_NAME,
            "--parent-pid",
            "0",
        ],
        [
            "--window-host",
            "--handoff-pipe",
            _PIPE_NAME,
            "--parent-pid",
            "111",
            "--api-token",
            "secret",
        ],
    ],
)
def test_window_host_argv_rejects_missing_invalid_or_secret_extra_arguments(
    arguments: list[str],
) -> None:
    with pytest.raises((SystemExit, HandoffProtocolError, WindowHostError, RuntimeError)):
        parse_window_host_arguments(arguments)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"future": True}, "invalid fields"),
        ({"api_credential": "short"}, "256-bit"),
        ({"handoff_credential": _API_CREDENTIAL}, "independent"),
        ({"base_url": "https://127.0.0.1:43210/"}, "loopback"),
        ({"base_url": "http://localhost:43210/"}, "loopback"),
        ({"base_url": "http://127.0.0.1:43210/path"}, "loopback"),
        ({"release_id": "../release"}, "release_id"),
    ],
)
def test_bootstrap_rejects_unknown_or_untrusted_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    payload = _bootstrap_payload()
    payload.update(changes)
    bootstrap = _message(1, "bootstrap", payload)

    with pytest.raises(HandoffProtocolError, match=message):
        parse_bootstrap(bootstrap)


def test_bootstrap_proof_binds_handoff_release_and_both_exact_processes() -> None:
    parsed = parse_bootstrap(_message(1, "bootstrap", _bootstrap_payload()))

    proof = bootstrap_proof(
        parsed,
        parent_process_id=_PARENT_PID,
        child_process_id=_CHILD_PID,
    )

    assert proof == bootstrap_proof(
        parsed,
        parent_process_id=_PARENT_PID,
        child_process_id=_CHILD_PID,
    )
    assert proof != bootstrap_proof(
        parsed,
        parent_process_id=_PARENT_PID,
        child_process_id=_CHILD_PID + 1,
    )
    assert _HANDOFF_CREDENTIAL not in proof


def test_unique_profile_is_bounded_to_the_exact_root_and_never_reused(tmp_path: Path) -> None:
    ids = iter(["1" * 32, "1" * 32, "2" * 32])

    first = create_unique_window_profile(
        root=tmp_path,
        id_factory=lambda: next(ids),
    )
    second = create_unique_window_profile(
        root=tmp_path,
        id_factory=lambda: next(ids),
    )

    assert first.profile_id == "window-" + "1" * 32
    assert second.profile_id == "window-" + "2" * 32
    assert first.directory.parent == tmp_path.resolve()
    assert second.directory.parent == tmp_path.resolve()
    assert first.directory.is_dir()
    assert second.directory.is_dir()


def test_child_serves_the_complete_authenticated_command_set_without_leaking_credentials(
    tmp_path: Path,
) -> None:
    connection = _connection_with_commands(
        ("prepare-hidden", {}),
        ("health", {}),
        ("export", {}),
        ("show", {}),
        ("focus", {}),
        ("shutdown", {}),
    )
    connector = _Connector(connection)
    controller = _Controller()
    runner = _Runner(controller)

    run_window_host(
        WindowHostArguments(_PIPE_NAME, _PARENT_PID),
        connector=connector,
        window_runner=runner,
        profile_root=tmp_path,
        profile_id_factory=lambda: "c" * 32,
        process_id=lambda: _CHILD_PID,
        clock=lambda: _NOW,
    )

    assert connector.calls == [(_PIPE_NAME, _PARENT_PID)]
    assert runner.calls == [
        {
            "base_url": "http://127.0.0.1:43210",
            "api_credential": _API_CREDENTIAL,
            "profile_dir": tmp_path.resolve() / ("window-" + "c" * 32),
        }
    ]
    assert controller.operations == [
        ("prepare-hidden", _NOW + 30_000),
        "health",
        "export",
        "show",
        "focus",
        "shutdown",
    ]
    responses = _decode_frames(bytes(connection.written))
    assert [message.name for message in responses] == [
        "hello-hidden",
        "prepared-hidden",
        "health",
        "exported",
        "shown",
        "focused",
        "stopping",
    ]
    assert [message.sequence for message in responses] == list(range(1, 8))
    assert [message.payload["request_sequence"] for message in responses] == list(range(1, 8))
    hello = responses[0].payload["result"]
    assert isinstance(hello, dict)
    hello_payload = cast(dict[str, object], hello)
    assert hello_payload["process_id"] == _CHILD_PID
    assert hello_payload["parent_process_id"] == _PARENT_PID
    assert hello_payload["window_handle"] == 4500
    assert hello_payload["hidden"] is True
    assert _API_CREDENTIAL.encode() not in connection.written
    assert _HANDOFF_CREDENTIAL.encode() not in connection.written
    assert connection.closed


def test_show_before_prepare_returns_sanitized_error_and_fails_the_candidate(
    tmp_path: Path,
) -> None:
    connection = _connection_with_commands(("show", {}))
    controller = _Controller()

    with pytest.raises(WindowHostCommandError, match="command 'show' failed") as error:
        run_window_host(
            WindowHostArguments(_PIPE_NAME, _PARENT_PID),
            connector=_Connector(connection),
            window_runner=_Runner(controller),
            profile_root=tmp_path,
            process_id=lambda: _CHILD_PID,
            clock=lambda: _NOW,
        )

    assert isinstance(error.value.__cause__, HandoffProtocolError)
    assert controller.operations == []
    responses = _decode_frames(bytes(connection.written))
    assert [message.name for message in responses] == [
        "hello-hidden",
        "command-error",
    ]
    assert responses[-1].payload["result"] == {
        "command": "show",
        "code": "candidate-command-failed",
    }


def test_controller_cannot_reflect_either_credential_into_health(
    tmp_path: Path,
) -> None:
    connection = _connection_with_commands(("health", {}))
    controller = _Controller(health_result={"debug": _API_CREDENTIAL})

    with pytest.raises(WindowHostError):
        run_window_host(
            WindowHostArguments(_PIPE_NAME, _PARENT_PID),
            connector=_Connector(connection),
            window_runner=_Runner(controller),
            profile_root=tmp_path,
            process_id=lambda: _CHILD_PID,
            clock=lambda: _NOW,
        )

    assert _API_CREDENTIAL.encode() not in connection.written
    assert _HANDOFF_CREDENTIAL.encode() not in connection.written
    assert _decode_frames(bytes(connection.written))[-1].name == "command-error"


def test_command_that_finishes_after_its_deadline_fails_the_candidate(
    tmp_path: Path,
) -> None:
    connection = _connection_with_commands(("health", {}))
    current_time = [_NOW]

    class _SlowHealth(_Controller):
        def health(self) -> dict[str, object]:
            result = super().health()
            current_time[0] = _NOW + 30_001
            return result

    with pytest.raises(WindowHostCommandError):
        run_window_host(
            WindowHostArguments(_PIPE_NAME, _PARENT_PID),
            connector=_Connector(connection),
            window_runner=_Runner(_SlowHealth()),
            profile_root=tmp_path,
            process_id=lambda: _CHILD_PID,
            clock=lambda: current_time[0],
        )

    assert [message.name for message in _decode_frames(bytes(connection.written))] == [
        "hello-hidden",
        "command-error",
    ]


def test_unknown_command_payload_field_is_rejected_before_native_work(
    tmp_path: Path,
) -> None:
    connection = _connection_with_commands(("prepare-hidden", {"future": True}))
    controller = _Controller()

    with pytest.raises(WindowHostError):
        run_window_host(
            WindowHostArguments(_PIPE_NAME, _PARENT_PID),
            connector=_Connector(connection),
            window_runner=_Runner(controller),
            profile_root=tmp_path,
            process_id=lambda: _CHILD_PID,
            clock=lambda: _NOW,
        )

    assert controller.operations == []
    assert [message.name for message in _decode_frames(bytes(connection.written))] == [
        "hello-hidden"
    ]


def test_native_runner_return_before_authenticated_shutdown_is_a_failure(
    tmp_path: Path,
) -> None:
    connection = _connection_with_commands()
    runner = _Runner(_Controller(), invoke_loop=False)

    with pytest.raises(WindowHostError, match="authenticated shutdown"):
        run_window_host(
            WindowHostArguments(_PIPE_NAME, _PARENT_PID),
            connector=_Connector(connection),
            window_runner=runner,
            profile_root=tmp_path,
            process_id=lambda: _CHILD_PID,
            clock=lambda: _NOW,
        )

    assert connection.closed


def test_parse_bootstrap_normalizes_the_loopback_origin() -> None:
    parsed = parse_bootstrap(_message(1, "bootstrap", _bootstrap_payload()))

    assert _API_CREDENTIAL not in repr(parsed)
    assert _HANDOFF_CREDENTIAL not in repr(parsed)
    assert parsed == WindowHostBootstrap(
        handoff_id=_HANDOFF_ID,
        release_id="release-v2",
        base_url="http://127.0.0.1:43210",
        api_credential=_API_CREDENTIAL,
        handoff_credential=_HANDOFF_CREDENTIAL,
    )
