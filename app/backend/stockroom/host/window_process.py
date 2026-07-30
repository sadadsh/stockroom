"""Isolated release-owned Stockroom window-host child.

The stable supervisor launches this entry through the frozen executable's
``--window-host`` mode.  Argv contains only a non-secret pipe name and the
expected parent PID.  The child verifies that PID through Windows, receives
fresh handoff/API credentials inside the verified pipe, creates one unique
WebView profile, and serves a deliberately small command set.

The native GUI loop is a port so command/state behavior is testable without
opening WebView2.  The production port lives in ``stockroom.host.window``;
that boundary must keep the API credential in native memory until a
synchronous WebView2 request-header adapter is qualified.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Never, Protocol, cast
from urllib.parse import urlsplit

from stockroom.host.windows_handoff_pipe import (
    ByteTransport,
    HandoffChannel,
    HandoffDeadlineExpired,
    HandoffMessage,
    HandoffPipeError,
    HandoffProtocolError,
    connect_windows_named_pipe,
    validate_pipe_name,
    validate_process_id,
)
from stockroom.store.machine_config import config_dir

_CREDENTIAL_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
_RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)
_PROFILE_ID_PATTERN = re.compile(r"window-[0-9a-f]{32}", re.ASCII)
_RESPONSE_WINDOW_MS = 10_000
_COMMANDS = frozenset(
    {
        "prepare-hidden",
        "show",
        "focus",
        "health",
        "export",
        "shutdown",
    }
)


class WindowHostError(RuntimeError):
    """The isolated window child could not reach or retain a safe state."""


class WindowHostCommandError(WindowHostError):
    """One authenticated command failed and the candidate must be discarded."""


@dataclass(frozen=True, slots=True)
class WindowHostArguments:
    pipe_name: str
    parent_process_id: int


@dataclass(frozen=True, slots=True)
class WindowHostBootstrap:
    handoff_id: str
    release_id: str
    base_url: str
    api_credential: str = field(repr=False)
    handoff_credential: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class WindowProfile:
    profile_id: str
    directory: Path


class ManagedWindowController(Protocol):
    """Native window operations exposed to the authenticated command loop."""

    @property
    def window_handle(self) -> int: ...

    def prepare_hidden(self, *, deadline_unix_ms: int) -> None: ...

    def show(self) -> None: ...

    def focus(self) -> None: ...

    def health(self) -> Mapping[str, object]: ...

    def export_session(self) -> object: ...

    def shutdown(self) -> None: ...


class ManagedWindowRunner(Protocol):
    """Create the hidden native window, then run commands after HWND readiness."""

    def __call__(
        self,
        *,
        base_url: str,
        api_credential: str,
        profile_dir: Path,
        command_loop: Callable[[ManagedWindowController], None],
    ) -> None: ...


class PipeConnector(Protocol):
    def __call__(
        self,
        pipe_name: str,
        *,
        expected_server_pid: int,
        timeout_ms: int = 15_000,
    ) -> ByteTransport: ...


class _SafeArgumentParser(argparse.ArgumentParser):
    """Reject malformed child argv without reflecting its raw values."""

    def error(self, message: str) -> Never:
        del message
        raise WindowHostError("window-host arguments are invalid")


def _now_unix_ms() -> int:
    return time.time_ns() // 1_000_000


def parse_window_host_arguments(arguments: Sequence[str]) -> WindowHostArguments:
    """Parse the exact non-secret child argv contract."""

    parser = _SafeArgumentParser(prog="Stockroom.exe --window-host")
    parser.add_argument("--window-host", action="store_true", required=True)
    parser.add_argument("--handoff-pipe", required=True)
    parser.add_argument("--parent-pid", required=True, type=int)
    parsed = parser.parse_args(list(arguments))
    return WindowHostArguments(
        pipe_name=validate_pipe_name(parsed.handoff_pipe),
        parent_process_id=validate_process_id(
            parsed.parent_pid,
            label="parent process ID",
        ),
    )


def _strict_payload(
    message: HandoffMessage,
    *,
    keys: frozenset[str],
) -> dict[str, object]:
    payload = message.payload
    actual = frozenset(payload)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        detail: list[str] = []
        if missing:
            detail.append(f"missing {missing}")
        if unknown:
            detail.append(f"unknown {unknown}")
        raise HandoffProtocolError(
            f"{message.name} payload has invalid fields: {', '.join(detail)}"
        )
    return payload


def _credential(value: object, *, label: str) -> str:
    if type(value) is not str or _CREDENTIAL_PATTERN.fullmatch(value) is None:
        raise HandoffProtocolError(f"{label} must be a 256-bit base64url credential")
    try:
        decoded = base64.b64decode(
            value + "=",
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise HandoffProtocolError(f"{label} must be a 256-bit base64url credential") from exc
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if len(decoded) != 32 or not secrets.compare_digest(canonical, value):
        raise HandoffProtocolError(f"{label} must be a 256-bit base64url credential")
    return value


def _release_id(value: object) -> str:
    if type(value) is not str or _RELEASE_ID_PATTERN.fullmatch(value) is None:
        raise HandoffProtocolError("release_id is invalid")
    return value


def _base_url(value: object) -> str:
    if type(value) is not str or len(value) > 128:
        raise HandoffProtocolError("base_url is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise HandoffProtocolError("base_url is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise HandoffProtocolError("base_url must be an exact IPv4 loopback origin")
    return f"http://127.0.0.1:{port}"


def parse_bootstrap(message: HandoffMessage) -> WindowHostBootstrap:
    if message.name != "bootstrap":
        raise HandoffProtocolError("the first window-host message must be bootstrap")
    payload = _strict_payload(
        message,
        keys=frozenset(
            {
                "release_id",
                "base_url",
                "api_credential",
                "handoff_credential",
            }
        ),
    )
    api_credential = _credential(
        payload["api_credential"],
        label="api_credential",
    )
    handoff_credential = _credential(
        payload["handoff_credential"],
        label="handoff_credential",
    )
    if secrets.compare_digest(api_credential, handoff_credential):
        raise HandoffProtocolError("handoff and API credentials must be independent")
    return WindowHostBootstrap(
        handoff_id=message.handoff_id,
        release_id=_release_id(payload["release_id"]),
        base_url=_base_url(payload["base_url"]),
        api_credential=api_credential,
        handoff_credential=handoff_credential,
    )


def create_unique_window_profile(
    *,
    root: Path | None = None,
    id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> WindowProfile:
    """Create one non-shared profile below the exact machine-local root."""

    profile_root = (
        root if root is not None else config_dir() / "Host State" / "WebView Profiles"
    ).resolve(strict=False)
    profile_root.mkdir(parents=True, exist_ok=True)
    for _attempt in range(8):
        suffix = id_factory()
        profile_id = f"window-{suffix}"
        if _PROFILE_ID_PATTERN.fullmatch(profile_id) is None:
            raise WindowHostError("profile id factory returned an invalid value")
        directory = (profile_root / profile_id).resolve(strict=False)
        if directory.parent != profile_root:
            raise WindowHostError("window profile escaped its machine-local root")
        try:
            directory.mkdir()
        except FileExistsError:
            continue
        return WindowProfile(profile_id=profile_id, directory=directory)
    raise WindowHostError("a unique window profile could not be allocated")


def bootstrap_proof(
    bootstrap: WindowHostBootstrap,
    *,
    parent_process_id: int,
    child_process_id: int,
) -> str:
    """Prove receipt of the one-use handoff credential without echoing it."""

    parent = validate_process_id(parent_process_id, label="parent process ID")
    child = validate_process_id(child_process_id, label="child process ID")
    context = f"{bootstrap.handoff_id}\0{bootstrap.release_id}\0{parent}\0{child}".encode("ascii")
    return hmac.new(
        bootstrap.handoff_credential.encode("ascii"),
        context,
        hashlib.sha256,
    ).hexdigest()


def _contains_credential(value: object, credentials: tuple[str, str]) -> bool:
    if type(value) is str:
        return any(credential in value for credential in credentials)
    if type(value) is list:
        return any(_contains_credential(item, credentials) for item in cast(list[object], value))
    if type(value) is dict:
        return any(
            _contains_credential(key, credentials) or _contains_credential(item, credentials)
            for key, item in cast(dict[object, object], value).items()
        )
    return False


def _response_deadline(clock: Callable[[], int]) -> int:
    return clock() + _RESPONSE_WINDOW_MS


def _response_payload(
    request: HandoffMessage,
    result: Mapping[str, object],
) -> dict[str, object]:
    return {
        "request_sequence": request.sequence,
        "result": dict(result),
    }


def _run_command_loop(
    controller: ManagedWindowController,
    *,
    channel: HandoffChannel,
    bootstrap: WindowHostBootstrap,
    profile: WindowProfile,
    parent_process_id: int,
    child_process_id: int,
    clock: Callable[[], int],
) -> None:
    window_handle = controller.window_handle
    if type(window_handle) is not int or not 0 < window_handle <= 0xFFFFFFFFFFFFFFFF:
        raise WindowHostError("window handle is invalid")
    hello_request_sequence = 1
    channel.send(
        "hello-hidden",
        {
            "request_sequence": hello_request_sequence,
            "result": {
                "release_id": bootstrap.release_id,
                "process_id": child_process_id,
                "parent_process_id": parent_process_id,
                "window_handle": window_handle,
                "profile_id": profile.profile_id,
                "renderer": "edgechromium",
                "hidden": True,
                "proof": bootstrap_proof(
                    bootstrap,
                    parent_process_id=parent_process_id,
                    child_process_id=child_process_id,
                ),
            },
        },
        deadline_unix_ms=_response_deadline(clock),
    )

    prepared = False
    visible = False
    while True:
        request = channel.receive(expected_names=_COMMANDS)
        _strict_payload(request, keys=frozenset())
        try:
            if request.name == "prepare-hidden":
                controller.prepare_hidden(
                    deadline_unix_ms=request.deadline_unix_ms,
                )
                prepared = True
                visible = False
                result: dict[str, object] = {"hidden": True}
                response_name = "prepared-hidden"
            elif request.name == "show":
                if not prepared:
                    raise HandoffProtocolError("show requires a prepared hidden window")
                controller.show()
                visible = True
                result = {"visible": True}
                response_name = "shown"
            elif request.name == "focus":
                if not visible:
                    raise HandoffProtocolError("focus requires a visible window")
                controller.focus()
                result = {"focused": True}
                response_name = "focused"
            elif request.name == "health":
                result = dict(controller.health())
                response_name = "health"
            elif request.name == "export":
                if not prepared:
                    raise HandoffProtocolError("export requires a prepared window")
                exported = controller.export_session()
                result = {"snapshot": exported}
                response_name = "exported"
            elif request.name == "shutdown":
                result = {"stopping": True}
                response_name = "stopping"
            else:  # pragma: no cover - receive() already enforces the command set
                raise HandoffProtocolError("window-host command is unsupported")

            if clock() > request.deadline_unix_ms:
                raise HandoffDeadlineExpired(
                    f"window-host command {request.name!r} exceeded its deadline"
                )
            if _contains_credential(
                result,
                (
                    bootstrap.api_credential,
                    bootstrap.handoff_credential,
                ),
            ):
                raise HandoffProtocolError("window-host response contained a credential")
            channel.send(
                response_name,
                _response_payload(request, result),
                deadline_unix_ms=_response_deadline(clock),
            )
            if request.name == "shutdown":
                controller.shutdown()
                return
        except BaseException as exc:
            try:
                channel.send(
                    "command-error",
                    {
                        "request_sequence": request.sequence,
                        "result": {
                            "command": request.name,
                            "code": "candidate-command-failed",
                        },
                    },
                    deadline_unix_ms=_response_deadline(clock),
                )
            except BaseException:
                pass
            raise WindowHostCommandError(f"window-host command {request.name!r} failed") from exc


def _native_window_runner(
    *,
    base_url: str,
    api_credential: str,
    profile_dir: Path,
    command_loop: Callable[[ManagedWindowController], None],
) -> None:
    """Load the native window port lazily so protocol tests never import GUI code."""

    from stockroom.host import window

    run_managed = getattr(window, "run_managed_window", None)
    if not callable(run_managed):
        raise WindowHostError("the managed native-window port is unavailable")
    run_managed(
        base_url=base_url,
        api_credential=api_credential,
        profile_dir=profile_dir,
        command_loop=command_loop,
    )


def run_window_host(
    arguments: WindowHostArguments,
    *,
    connector: PipeConnector = connect_windows_named_pipe,
    window_runner: ManagedWindowRunner = _native_window_runner,
    profile_root: Path | None = None,
    profile_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    process_id: Callable[[], int] = os.getpid,
    clock: Callable[[], int] = _now_unix_ms,
) -> None:
    """Run one verified child until shutdown or a fail-closed disconnect."""

    if type(arguments) is not WindowHostArguments:
        raise WindowHostError("window-host arguments are invalid")
    connection = connector(
        arguments.pipe_name,
        expected_server_pid=arguments.parent_process_id,
    )
    channel = HandoffChannel(
        connection,
        expected_handoff_id=None,
        clock=clock,
    )
    try:
        bootstrap_message = channel.receive(expected_names={"bootstrap"})
        bootstrap = parse_bootstrap(bootstrap_message)
        child_process_id = validate_process_id(
            process_id(),
            label="child process ID",
        )
        profile = create_unique_window_profile(
            root=profile_root,
            id_factory=profile_id_factory,
        )
        completed_shutdown = False

        def command_loop(controller: ManagedWindowController) -> None:
            nonlocal completed_shutdown
            _run_command_loop(
                controller,
                channel=channel,
                bootstrap=bootstrap,
                profile=profile,
                parent_process_id=arguments.parent_process_id,
                child_process_id=child_process_id,
                clock=clock,
            )
            completed_shutdown = True

        try:
            window_runner(
                base_url=bootstrap.base_url,
                api_credential=bootstrap.api_credential,
                profile_dir=profile.directory,
                command_loop=command_loop,
            )
            if not completed_shutdown:
                raise WindowHostError("managed native window exited before authenticated shutdown")
        except WindowHostError:
            raise
        except BaseException as exc:
            raise WindowHostError("managed native window failed") from exc
    finally:
        channel.close()


def main(arguments: Sequence[str] | None = None) -> None:
    parsed = parse_window_host_arguments(list(arguments) if arguments is not None else sys.argv[1:])
    try:
        run_window_host(parsed)
    except (HandoffPipeError, WindowHostError) as exc:
        raise WindowHostError("window-host child failed safely") from exc


__all__ = [
    "ManagedWindowController",
    "ManagedWindowRunner",
    "PipeConnector",
    "WindowHostArguments",
    "WindowHostBootstrap",
    "WindowHostCommandError",
    "WindowHostError",
    "WindowProfile",
    "bootstrap_proof",
    "create_unique_window_profile",
    "main",
    "parse_bootstrap",
    "parse_window_host_arguments",
    "run_window_host",
]
