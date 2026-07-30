"""Stable-supervisor client for one release-owned window-host process.

This module owns the side of the handoff that must remain alive across release
changes.  It creates the current-user pipe, launches the exact immutable
release member in a kill-on-close job, binds the accepted pipe to that PID,
bootstraps credentials through the verified pipe, and exposes a typed bounded
command surface.

Every potentially blocking pipe operation runs behind a supervisor deadline.
On timeout, protocol failure, or identity mismatch, the pipe is closed, the
exact job is terminated, and the launched root is reaped.  Fresh API/handoff
credentials never enter argv, the environment, representations, errors,
receipts, or logs.
"""

from __future__ import annotations

import base64
import binascii
import math
import os
import re
import secrets
import subprocess
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, TypeVar, cast
from urllib.parse import urlsplit

from stockroom.host.window_process import (
    WindowHostBootstrap,
    bootstrap_proof,
    parse_bootstrap,
)
from stockroom.host.windows_handoff_pipe import (
    ByteTransport,
    HandoffChannel,
    HandoffMessage,
    HandoffPipeError,
    HandoffProtocolError,
    create_windows_named_pipe_server,
    new_pipe_name,
    validate_handoff_id,
    validate_pipe_name,
    validate_process_id,
)
from stockroom.host.windows_job import (
    WindowsProcessJob,
    launch_in_windows_job,
)
from stockroom.update import AcceptedRelease

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PROFILE_ID_PATTERN = re.compile(r"window-[0-9a-f]{32}", re.ASCII)
_RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
_WINDOW_HOST_MEMBER_KIND = "window-host"
_WINDOW_HOST_MEMBER_PATH = "WindowHost/Stockroom.WindowHost.exe"
_SENSITIVE_ENVIRONMENT_FRAGMENT = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|API[_-]?KEY|ACCESS[_-]?KEY|"
    r"AUTHORIZATION|PRIVATE[_-]?KEY|COOKIE)",
    re.IGNORECASE | re.ASCII,
)
_WINDOW_HOST_FLAGS = frozenset(
    {
        "--window-host",
        "--handoff-pipe",
        "--parent-pid",
    }
)
_MAX_COMMAND_PREFIX = 8
_MAX_ARGUMENT_LENGTH = 32_768
_THREAD_SETTLE_SECONDS = 0.1
_JOB_TIMEOUT_FRACTION = 0.75

_T = TypeVar("_T")


class WindowSupervisorError(RuntimeError):
    """Base failure for the stable window-host supervisor boundary."""


class WindowSupervisorTimeout(WindowSupervisorError):
    """A bounded native operation did not complete before its deadline."""

    def __init__(self, phase: str) -> None:
        super().__init__(f"window-host operation timed out during {phase}")
        self.phase = phase


class WindowSupervisorProtocolError(WindowSupervisorError):
    """The child returned an invalid identity or response."""


class WindowSupervisorProcessError(WindowSupervisorError):
    """The exact child could not be launched, stopped, or reaped."""


class ProcessPort(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


class ProcessJobPort(Protocol):
    def terminate_all(self, *, timeout: float) -> None: ...


class ProcessLauncher(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        creationflags: int,
    ) -> tuple[ProcessPort, ProcessJobPort]: ...


class PipeServerFactory(Protocol):
    def __call__(self, pipe_name: str) -> PipeServerPort: ...


class PipeServerPort(Protocol):
    def accept(self, *, expected_client_pid: int) -> ByteTransport: ...

    def close(self) -> None: ...


class ChannelPort(Protocol):
    @property
    def handoff_id(self) -> str: ...

    @property
    def peer_process_id(self) -> int: ...

    def send(
        self,
        name: str,
        payload: Mapping[str, object],
        *,
        deadline_unix_ms: int,
    ) -> HandoffMessage: ...

    def receive(
        self,
        *,
        expected_names: Collection[str] | None = None,
    ) -> HandoffMessage: ...

    def close(self) -> None: ...


class ChannelFactory(Protocol):
    def __call__(
        self,
        transport: ByteTransport,
        *,
        expected_handoff_id: str | None,
        clock: Callable[[], int],
    ) -> ChannelPort: ...


def _default_channel_factory(
    transport: ByteTransport,
    *,
    expected_handoff_id: str | None,
    clock: Callable[[], int],
) -> HandoffChannel:
    return HandoffChannel(
        transport,
        expected_handoff_id=expected_handoff_id,
        clock=clock,
    )


def _now_unix_ms() -> int:
    return time.time_ns() // 1_000_000


def _positive_timeout(value: object, *, label: str) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"{label} must be positive and finite")
    result = float(cast(int | float, value))
    if not math.isfinite(result) or result <= 0 or result > 300:
        raise ValueError(f"{label} must be positive, finite, and at most 300 seconds")
    return result


def _wait_timeout(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        raise ValueError("timeout must be nonnegative, finite, and at most 300 seconds")
    result = float(cast(int | float, value))
    if not math.isfinite(result) or result < 0 or result > 300:
        raise ValueError("timeout must be nonnegative, finite, and at most 300 seconds")
    return result


def _validate_release_id(value: object) -> str:
    if type(value) is not str or _RELEASE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("release_id is invalid")
    return value


def _canonical_credential(value: object, *, label: str) -> str:
    if type(value) is not str or len(value) != 43:
        raise ValueError(f"{label} must be a canonical 256-bit base64url credential")
    try:
        decoded = base64.b64decode(
            value + "=",
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{label} must be a canonical 256-bit base64url credential") from exc
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if len(decoded) != 32 or not secrets.compare_digest(canonical, value):
        raise ValueError(f"{label} must be a canonical 256-bit base64url credential")
    return value


def _contains_forbidden_value(
    value: object,
    forbidden_values: Sequence[str],
) -> bool:
    if type(value) is str:
        return any(secret in value for secret in forbidden_values)
    if type(value) is list:
        return any(
            _contains_forbidden_value(item, forbidden_values) for item in cast(list[object], value)
        )
    if type(value) is dict:
        return any(
            _contains_forbidden_value(key, forbidden_values)
            or _contains_forbidden_value(item, forbidden_values)
            for key, item in cast(dict[object, object], value).items()
        )
    return False


def _exception_contains_forbidden_value(
    error: BaseException,
    forbidden_values: Sequence[str],
) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        try:
            rendered = str(current)
        except BaseException:
            rendered = ""
        string_arguments = [argument for argument in current.args if type(argument) is str]
        if _contains_forbidden_value(
            [rendered, *string_arguments],
            forbidden_values,
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _require_running_process(process: ProcessPort, *, phase: str) -> None:
    try:
        exit_code = process.poll()
    except BaseException:
        raise WindowSupervisorProcessError(
            f"window-host child state could not be read before {phase}"
        ) from None
    if exit_code is None:
        return
    if type(exit_code) is not int:
        raise WindowSupervisorProcessError(f"window-host child state was invalid before {phase}")
    raise WindowSupervisorProcessError(f"window-host child exited before {phase}")


def _strict_result(
    response: HandoffMessage,
    *,
    request_sequence: int,
    keys: frozenset[str],
) -> dict[str, object]:
    payload = response.payload
    if frozenset(payload) != frozenset({"request_sequence", "result"}):
        raise WindowSupervisorProtocolError("window-host response fields are invalid")
    if type(payload["request_sequence"]) is not int or payload["request_sequence"] != (
        request_sequence
    ):
        raise WindowSupervisorProtocolError("window-host response correlation is invalid")
    result = payload["result"]
    if type(result) is not dict:
        raise WindowSupervisorProtocolError("window-host response result is invalid")
    typed_result = cast(dict[str, object], result)
    if frozenset(typed_result) != keys:
        raise WindowSupervisorProtocolError("window-host response result fields are invalid")
    return typed_result


def _reject_command_error(
    response: HandoffMessage,
    *,
    request_sequence: int,
    command: str,
) -> None:
    if response.name != "command-error":
        return
    result = _strict_result(
        response,
        request_sequence=request_sequence,
        keys=frozenset({"command", "code"}),
    )
    if (
        type(result["command"]) is not str
        or type(result["code"]) is not str
        or result["command"] != command
        or result["code"] != "candidate-command-failed"
    ):
        raise WindowSupervisorProtocolError("window-host command error is invalid")
    raise WindowSupervisorProtocolError("window-host child rejected a command")


@dataclass(frozen=True, slots=True)
class WindowHostLaunch:
    """Exact command prefix and working directory for one release member."""

    release_id: str
    command_prefix: tuple[str, ...]
    working_directory: Path
    environment: Mapping[str, str] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validate_release_id(self.release_id)
        if (
            type(self.command_prefix) is not tuple
            or not self.command_prefix
            or len(self.command_prefix) > _MAX_COMMAND_PREFIX
        ):
            raise ValueError("window-host command prefix is invalid")
        for argument in self.command_prefix:
            if (
                type(argument) is not str
                or not argument
                or len(argument) > _MAX_ARGUMENT_LENGTH
                or "\x00" in argument
                or any(
                    argument == flag or argument.startswith(f"{flag}=")
                    for flag in _WINDOW_HOST_FLAGS
                )
            ):
                raise ValueError("window-host command prefix is invalid")
        directory = Path(self.working_directory)
        if not directory.is_absolute():
            raise ValueError("window-host working directory must be absolute")
        if self.environment is not None:
            for key, value in self.environment.items():
                if (
                    type(key) is not str
                    or type(value) is not str
                    or not key
                    or "\x00" in key
                    or "\x00" in value
                ):
                    raise ValueError("window-host environment is invalid")

    @classmethod
    def from_release(cls, release: AcceptedRelease) -> WindowHostLaunch:
        """Resolve the one immutable native member used by ``--window-host``."""

        if not isinstance(release, AcceptedRelease):
            raise TypeError("release must be an AcceptedRelease")
        if release.manifest.release_id != release.release_id:
            raise WindowSupervisorProcessError("accepted release identity is incoherent")
        if (
            not release.directory.is_absolute()
            or release.directory.is_symlink()
            or not release.directory.is_dir()
        ):
            raise WindowSupervisorProcessError("accepted release directory is missing or unsafe")
        window_host_paths = [
            member.path
            for member in release.manifest.members
            if member.kind == _WINDOW_HOST_MEMBER_KIND
        ]
        if len(window_host_paths) != 1:
            raise WindowSupervisorProcessError(
                "release must contain exactly one native window-host member"
            )
        member_path = window_host_paths[0]
        if member_path != _WINDOW_HOST_MEMBER_PATH:
            raise WindowSupervisorProcessError(
                "release window host path is not the canonical native member"
            )
        executable = release.members.get(member_path)
        if executable is None:
            raise WindowSupervisorProcessError("release window-host member is not accepted")
        executable_path = Path(executable)
        if not executable_path.is_absolute() or executable_path.is_symlink():
            raise WindowSupervisorProcessError("release window-host member is missing or unsafe")
        try:
            release_root = release.directory.resolve(strict=True)
            resolved = executable_path.resolve(strict=True)
            declared_path = release_root.joinpath(*member_path.split("/"))
            if declared_path.is_symlink():
                raise WindowSupervisorProcessError(
                    "release window-host member is missing or unsafe"
                )
            declared = declared_path.resolve(strict=True)
        except OSError as exc:
            raise WindowSupervisorProcessError("release window host could not be resolved") from exc
        try:
            resolved.relative_to(release_root)
        except ValueError as exc:
            raise WindowSupervisorProcessError(
                "release window-host member escaped the immutable release"
            ) from exc
        if (
            resolved != declared
            or resolved.suffix.casefold() != ".exe"
            or resolved.name != "Stockroom.WindowHost.exe"
            or not resolved.is_file()
        ):
            raise WindowSupervisorProcessError(
                "release window host must be the exact frozen native executable"
            )
        return cls(
            release_id=release.release_id,
            command_prefix=(str(resolved),),
            working_directory=release_root,
        )

    def command(
        self,
        *,
        pipe_name: str,
        parent_process_id: int,
    ) -> tuple[str, ...]:
        pipe = validate_pipe_name(pipe_name)
        parent = validate_process_id(parent_process_id, label="parent process ID")
        return (
            *self.command_prefix,
            "--window-host",
            "--handoff-pipe",
            pipe,
            "--parent-pid",
            str(parent),
        )


def sanitized_window_host_environment(
    source: Mapping[str, str],
    *,
    forbidden_values: Sequence[str] = (),
) -> dict[str, str]:
    """Remove credential-like variables and exact handoff secrets."""

    sanitized: dict[str, str] = {}
    forbidden = tuple(value for value in forbidden_values if value)
    for key, value in source.items():
        if (
            type(key) is not str
            or type(value) is not str
            or not key
            or "\x00" in key
            or "\x00" in value
        ):
            raise ValueError("window-host environment is invalid")
        if _SENSITIVE_ENVIRONMENT_FRAGMENT.search(key):
            continue
        if any(secret in key or secret in value for secret in forbidden):
            continue
        sanitized[key] = value
    return sanitized


def _same_origin(value: str, expected_origin: str) -> bool:
    try:
        actual = urlsplit(value)
        expected = urlsplit(expected_origin)
        actual_port = actual.port
        expected_port = expected.port
    except (TypeError, ValueError):
        return False
    return (
        actual.scheme == expected.scheme == "http"
        and actual.hostname == expected.hostname == "127.0.0.1"
        and actual_port == expected_port
        and actual.username is None
        and actual.password is None
    )


@dataclass(frozen=True, slots=True)
class WindowHostIdentity:
    release_id: str
    process_id: int
    parent_process_id: int
    window_handle: int
    profile_id: str
    renderer: str

    def __post_init__(self) -> None:
        _validate_release_id(self.release_id)
        validate_process_id(self.process_id, label="child process ID")
        validate_process_id(self.parent_process_id, label="parent process ID")
        if type(self.window_handle) is not int or not 0 < self.window_handle <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("window_handle is invalid")
        if (
            type(self.profile_id) is not str
            or _PROFILE_ID_PATTERN.fullmatch(self.profile_id) is None
        ):
            raise ValueError("profile_id is invalid")
        if self.renderer != "edgechromium":
            raise ValueError("renderer is unsupported")


@dataclass(frozen=True, slots=True)
class WindowHostHealth:
    window_handle: int
    current_url: str
    hidden: bool
    visible: bool
    renderer: str
    close_requested: bool = False

    def __post_init__(self) -> None:
        if type(self.window_handle) is not int or not 0 < self.window_handle <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("health window handle is invalid")
        if type(self.current_url) is not str or not self.current_url:
            raise ValueError("health current URL is invalid")
        if type(self.hidden) is not bool or type(self.visible) is not bool:
            raise ValueError("health visibility is invalid")
        if self.hidden == self.visible:
            raise ValueError("health visibility must be exactly hidden or visible")
        if self.renderer != "edgechromium":
            raise ValueError("health renderer is unsupported")
        if type(self.close_requested) is not bool:
            raise ValueError("health close-request state is invalid")


class _OwnedWindowProcess:
    def __init__(
        self,
        process: ProcessPort,
        job: ProcessJobPort,
        *,
        monotonic_clock: Callable[[], float],
    ) -> None:
        self.process = process
        self.job = job
        self._monotonic_clock = monotonic_clock
        self._closed = False
        self._exit_code: int | None = None
        self._lock = threading.Lock()

    def _remaining(self, deadline: float) -> float:
        return max(0.0, deadline - self._monotonic_clock())

    def _terminate_and_reap_locked(self, *, deadline: float) -> None:
        errors: list[BaseException] = []
        job_closed = False
        try:
            remaining = self._remaining(deadline)
            self.job.terminate_all(timeout=remaining * _JOB_TIMEOUT_FRACTION)
            job_closed = True
        except BaseException as exc:
            errors.append(exc)
        reaped = False
        try:
            exit_code = self.process.wait(timeout=self._remaining(deadline))
            reaped = type(exit_code) is int
            if reaped:
                self._exit_code = exit_code
            else:
                errors.append(
                    WindowSupervisorProcessError(
                        "window-host child returned an invalid exit status"
                    )
                )
        except BaseException:
            try:
                self.process.kill()
                exit_code = self.process.wait(timeout=self._remaining(deadline))
                reaped = type(exit_code) is int
                if reaped:
                    self._exit_code = exit_code
                else:
                    errors.append(
                        WindowSupervisorProcessError(
                            "window-host child returned an invalid exit status"
                        )
                    )
            except BaseException as kill_error:
                errors.append(kill_error)
        if reaped and job_closed:
            self._closed = True
        if errors:
            raise WindowSupervisorProcessError(
                "window-host child could not be terminated and reaped"
            ) from None

    def terminate_and_reap(self, *, timeout: float) -> None:
        with self._lock:
            if self._closed:
                return
            deadline = self._monotonic_clock() + timeout
            self._terminate_and_reap_locked(deadline=deadline)

    def reap_after_shutdown(self, *, timeout: float) -> None:
        with self._lock:
            if self._closed:
                return
            deadline = self._monotonic_clock() + timeout
            try:
                exit_code = self.process.wait(timeout=timeout * _JOB_TIMEOUT_FRACTION)
            except BaseException:
                self._terminate_and_reap_locked(deadline=deadline)
                self._closed = True
                raise WindowSupervisorProcessError(
                    "window-host child did not exit after shutdown"
                ) from None
            valid_exit_code = type(exit_code) is int
            # Close the kill-on-close job handle after the root and descendants
            # are already gone. ``terminate_all`` is idempotent and owns that
            # close.
            try:
                self.job.terminate_all(timeout=self._remaining(deadline))
            except BaseException:
                if valid_exit_code:
                    self._exit_code = exit_code
                raise WindowSupervisorProcessError(
                    "window-host job could not be closed after shutdown"
                ) from None
            self._closed = True
            if valid_exit_code:
                self._exit_code = exit_code
        if not valid_exit_code or exit_code != 0:
            raise WindowSupervisorProcessError(
                "window-host child exited unsuccessfully after shutdown"
            ) from None

    def wait_for_exit(
        self,
        *,
        timeout: float | None,
        cleanup_timeout: float,
    ) -> int | None:
        with self._lock:
            if self._exit_code is not None and self._closed:
                return self._exit_code
            observed_exit_code = self._exit_code
        if observed_exit_code is None:
            try:
                exit_code = self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return None
            except BaseException:
                raise WindowSupervisorProcessError("window-host child wait failed") from None
            if type(exit_code) is not int:
                raise WindowSupervisorProcessError(
                    "window-host child returned an invalid exit status"
                )
        else:
            exit_code = observed_exit_code
        with self._lock:
            if self._exit_code is not None and self._closed:
                return self._exit_code
            self._exit_code = exit_code
            if not self._closed:
                try:
                    self.job.terminate_all(timeout=cleanup_timeout)
                except BaseException:
                    raise WindowSupervisorProcessError(
                        "window-host job could not be closed after child exit"
                    ) from None
                self._closed = True
        return exit_code


def _bounded_call(
    operation: Callable[[], _T],
    *,
    timeout: float,
    phase: str,
    on_timeout: Callable[[], None],
    dispose_late_result: Callable[[_T], None] | None = None,
) -> _T:
    result: list[_T] = []
    errors: list[BaseException] = []
    disposal_errors: list[BaseException] = []
    done = threading.Event()
    state_lock = threading.Lock()
    cancelled = False

    def invoke() -> None:
        nonlocal cancelled
        try:
            value = operation()
            with state_lock:
                dispose = cancelled
                if not dispose:
                    result.append(value)
            if dispose and dispose_late_result is not None:
                try:
                    dispose_late_result(value)
                except BaseException as exc:
                    disposal_errors.append(exc)
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(
        target=invoke,
        name=f"Stockroom Window {phase}",
        daemon=True,
    )
    thread.start()
    if not done.wait(timeout):
        with state_lock:
            cancelled = True
            completed_results = tuple(result)
            result.clear()
        cleanup_error: BaseException | None = None
        for value in completed_results:
            try:
                if dispose_late_result is not None:
                    dispose_late_result(value)
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        try:
            on_timeout()
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        settled = done.wait(_THREAD_SETTLE_SECONDS)
        timeout_error = WindowSupervisorTimeout(phase)
        if cleanup_error is not None or disposal_errors or not settled:
            raise WindowSupervisorProcessError(
                f"window-host timeout cleanup failed during {phase}"
            ) from None
        raise timeout_error
    if errors:
        raise errors[0]
    if len(result) != 1:
        raise WindowSupervisorError(f"window-host operation returned no result during {phase}")
    return result[0]


class WindowHostClient:
    """Typed bounded command client for one verified child identity."""

    __slots__ = (
        "_base_url",
        "_channel",
        "_command_timeout",
        "_forbidden_values",
        "_identity",
        "_lock",
        "_owned_process",
        "_state",
        "_stop_timeout",
        "_wall_clock",
    )

    def __init__(
        self,
        identity: WindowHostIdentity,
        *,
        base_url: str,
        channel: ChannelPort,
        owned_process: _OwnedWindowProcess,
        command_timeout: float,
        forbidden_values: Sequence[str],
        stop_timeout: float,
        wall_clock: Callable[[], int],
    ) -> None:
        self._identity = identity
        self._base_url = base_url
        self._channel = channel
        self._owned_process = owned_process
        self._command_timeout = command_timeout
        self._forbidden_values = tuple(forbidden_values)
        self._stop_timeout = stop_timeout
        self._wall_clock = wall_clock
        self._state = "active"
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return (
            "WindowHostClient("
            f"release_id={self._identity.release_id!r}, "
            f"process_id={self._identity.process_id}, "
            f"state={self._state!r})"
        )

    @property
    def identity(self) -> WindowHostIdentity:
        return self._identity

    @property
    def process_id(self) -> int:
        return self._identity.process_id

    @property
    def active(self) -> bool:
        return self._state == "active"

    def _require_active(self) -> None:
        if self._state != "active":
            raise WindowSupervisorError("window-host client is not active")

    def _abort(self) -> None:
        if self._state == "stopped":
            return
        self._state = "failed"
        errors: list[BaseException] = []
        try:
            self._channel.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._owned_process.terminate_and_reap(timeout=self._stop_timeout)
        except BaseException as exc:
            errors.append(exc)
        self._forbidden_values = ()
        if errors:
            raise WindowSupervisorProcessError(
                "window-host failure cleanup was incomplete"
            ) from None

    def _command(
        self,
        name: str,
        expected_response: str,
        parse: Callable[[HandoffMessage, int], _T],
    ) -> _T:
        with self._lock:
            self._require_active()

            def exchange() -> _T:
                deadline = self._wall_clock() + math.ceil(self._command_timeout * 1000)
                request = self._channel.send(
                    name,
                    {},
                    deadline_unix_ms=deadline,
                )
                response = self._channel.receive(
                    expected_names={expected_response, "command-error"}
                )
                if response.name not in {expected_response, "command-error"}:
                    raise WindowSupervisorProtocolError("window-host response name is invalid")
                if _contains_forbidden_value(
                    response.payload,
                    self._forbidden_values,
                ):
                    raise WindowSupervisorProtocolError(
                        "window-host response contained a credential"
                    )
                _reject_command_error(
                    response,
                    request_sequence=request.sequence,
                    command=name,
                )
                return parse(response, request.sequence)

            try:
                return _bounded_call(
                    exchange,
                    timeout=self._command_timeout,
                    phase=name,
                    on_timeout=self._abort,
                )
            except WindowSupervisorTimeout:
                raise
            except BaseException as exc:
                try:
                    self._abort()
                except WindowSupervisorProcessError as cleanup_error:
                    raise cleanup_error from None
                if isinstance(exc, WindowSupervisorError):
                    if _exception_contains_forbidden_value(
                        exc,
                        self._forbidden_values,
                    ):
                        raise WindowSupervisorError(
                            f"window-host command failed during {name}"
                        ) from None
                    raise
                if isinstance(exc, (HandoffPipeError, HandoffProtocolError)):
                    raise WindowSupervisorProtocolError(
                        f"window-host protocol failed during {name}"
                    ) from None
                raise WindowSupervisorError(f"window-host command failed during {name}") from None

    def prepare_hidden(self) -> None:
        def parse(response: HandoffMessage, sequence: int) -> None:
            result = _strict_result(
                response,
                request_sequence=sequence,
                keys=frozenset({"hidden"}),
            )
            if result["hidden"] is not True:
                raise WindowSupervisorProtocolError("window-host did not remain hidden")

        self._command("prepare-hidden", "prepared-hidden", parse)

    def show(self) -> None:
        def parse(response: HandoffMessage, sequence: int) -> None:
            result = _strict_result(
                response,
                request_sequence=sequence,
                keys=frozenset({"visible"}),
            )
            if result["visible"] is not True:
                raise WindowSupervisorProtocolError("window-host did not report visible")

        self._command("show", "shown", parse)

    def focus(self) -> None:
        def parse(response: HandoffMessage, sequence: int) -> None:
            result = _strict_result(
                response,
                request_sequence=sequence,
                keys=frozenset({"focused"}),
            )
            if result["focused"] is not True:
                raise WindowSupervisorProtocolError("window-host did not report focused")

        self._command("focus", "focused", parse)

    def health(self) -> WindowHostHealth:
        def parse(response: HandoffMessage, sequence: int) -> WindowHostHealth:
            result = _strict_result(
                response,
                request_sequence=sequence,
                keys=frozenset(
                    {
                        "hwnd",
                        "current_url",
                        "hidden",
                        "visible",
                        "renderer",
                        "close_requested",
                    }
                ),
            )
            try:
                health = WindowHostHealth(
                    window_handle=cast(int, result["hwnd"]),
                    current_url=cast(str, result["current_url"]),
                    hidden=cast(bool, result["hidden"]),
                    visible=cast(bool, result["visible"]),
                    renderer=cast(str, result["renderer"]),
                    close_requested=cast(bool, result["close_requested"]),
                )
            except ValueError as exc:
                raise WindowSupervisorProtocolError(
                    "window-host health values are invalid"
                ) from exc
            if (
                health.window_handle != self._identity.window_handle
                or health.renderer != self._identity.renderer
                or not _same_origin(health.current_url, self._base_url)
            ):
                raise WindowSupervisorProtocolError("window-host health identity is incoherent")
            return health

        return self._command("health", "health", parse)

    def export_session(self) -> object:
        def parse(response: HandoffMessage, sequence: int) -> object:
            result = _strict_result(
                response,
                request_sequence=sequence,
                keys=frozenset({"snapshot"}),
            )
            return result["snapshot"]

        return self._command("export", "exported", parse)

    def wait_for_exit(self, timeout: float | None = None) -> int | None:
        """Block without polling until the exact child exits or timeout elapses."""

        validated_timeout = _wait_timeout(timeout)
        try:
            exit_code = self._owned_process.wait_for_exit(
                timeout=validated_timeout,
                cleanup_timeout=self._stop_timeout,
            )
        except WindowSupervisorProcessError:
            with self._lock:
                try:
                    self._abort()
                except WindowSupervisorProcessError as cleanup_error:
                    raise cleanup_error from None
            raise
        if exit_code is None:
            return None
        with self._lock:
            prior_state = self._state
            try:
                self._channel.close()
            except BaseException:
                self._state = "failed"
                self._forbidden_values = ()
                raise WindowSupervisorProcessError(
                    "window-host channel could not be closed after child exit"
                ) from None
            self._forbidden_values = ()
            if prior_state == "stopped":
                self._state = "stopped"
            elif prior_state == "active" and exit_code == 0:
                self._state = "stopped"
            else:
                self._state = "failed"
        return exit_code

    def shutdown(self) -> None:
        with self._lock:
            self._require_active()

            def parse(response: HandoffMessage, sequence: int) -> None:
                result = _strict_result(
                    response,
                    request_sequence=sequence,
                    keys=frozenset({"stopping"}),
                )
                if result["stopping"] is not True:
                    raise WindowSupervisorProtocolError("window-host did not acknowledge shutdown")

            self._command("shutdown", "stopping", parse)
            self._state = "stopping"
            forbidden_values = self._forbidden_values
            try:
                self._channel.close()
                self._owned_process.reap_after_shutdown(timeout=self._stop_timeout)
            except BaseException as exc:
                self._state = "failed"
                try:
                    self._owned_process.terminate_and_reap(timeout=self._stop_timeout)
                except BaseException:
                    pass
                self._forbidden_values = ()
                if isinstance(exc, WindowSupervisorError):
                    if _exception_contains_forbidden_value(
                        exc,
                        forbidden_values,
                    ):
                        raise WindowSupervisorProcessError(
                            "window-host shutdown could not be completed"
                        ) from None
                    raise
                raise WindowSupervisorProcessError(
                    "window-host shutdown could not be completed"
                ) from None
            self._forbidden_values = ()
            self._state = "stopped"

    def close(self) -> None:
        with self._lock:
            if self._state == "stopped":
                return
            try:
                self._abort()
            except WindowSupervisorProcessError:
                raise

    def __enter__(self) -> Self:
        self._require_active()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class WindowHostSupervisor:
    """Launch and verify release-owned window children for later handoff use."""

    def __init__(
        self,
        *,
        pipe_server_factory: PipeServerFactory = create_windows_named_pipe_server,
        process_launcher: ProcessLauncher = launch_in_windows_job,
        channel_factory: ChannelFactory = _default_channel_factory,
        pipe_name_factory: Callable[[], str] = new_pipe_name,
        credential_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        process_id: Callable[[], int] = os.getpid,
        wall_clock: Callable[[], int] = _now_unix_ms,
        monotonic_clock: Callable[[], float] = time.monotonic,
        startup_timeout_seconds: float = 15.0,
        command_timeout_seconds: float = 10.0,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        self._pipe_server_factory = pipe_server_factory
        self._process_launcher = process_launcher
        self._channel_factory = channel_factory
        self._pipe_name_factory = pipe_name_factory
        self._credential_factory = credential_factory
        self._process_id = process_id
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._startup_timeout = _positive_timeout(
            startup_timeout_seconds,
            label="startup_timeout_seconds",
        )
        self._command_timeout = _positive_timeout(
            command_timeout_seconds,
            label="command_timeout_seconds",
        )
        self._stop_timeout = _positive_timeout(
            stop_timeout_seconds,
            label="stop_timeout_seconds",
        )

    def _fresh_handoff_credential(self, api_credential: str) -> str:
        for _attempt in range(8):
            try:
                candidate = _canonical_credential(
                    self._credential_factory(),
                    label="handoff credential",
                )
            except BaseException:
                raise WindowSupervisorError("handoff credential could not be generated") from None
            if not secrets.compare_digest(candidate, api_credential):
                return candidate
        raise WindowSupervisorError("independent handoff credential could not be generated")

    def launch(
        self,
        launch: WindowHostLaunch,
        *,
        handoff_id: str,
        base_url: str,
        api_credential: str,
    ) -> WindowHostClient:
        """Launch, mutually bind, bootstrap, and verify one hidden child."""

        if type(launch) is not WindowHostLaunch:
            raise TypeError("launch must be a WindowHostLaunch")
        validated_handoff_id = validate_handoff_id(handoff_id)
        validated_api_credential = _canonical_credential(
            api_credential,
            label="API credential",
        )
        handoff_credential = self._fresh_handoff_credential(validated_api_credential)
        try:
            parent_process_id = validate_process_id(
                self._process_id(),
                label="parent process ID",
            )
            pipe_name = validate_pipe_name(self._pipe_name_factory())
            deadline = self._wall_clock() + math.ceil(self._startup_timeout * 1000)
            bootstrap_message = HandoffMessage(
                handoff_id=validated_handoff_id,
                sequence=1,
                deadline_unix_ms=deadline,
                name="bootstrap",
                payload={
                    "release_id": launch.release_id,
                    "base_url": base_url,
                    "api_credential": validated_api_credential,
                    "handoff_credential": handoff_credential,
                },
            )
            bootstrap = parse_bootstrap(bootstrap_message)
        except (HandoffPipeError, HandoffProtocolError, ValueError):
            raise WindowSupervisorProtocolError(
                "window-host launch parameters are invalid"
            ) from None
        except BaseException:
            raise WindowSupervisorProcessError("window-host launch prerequisites failed") from None
        server: PipeServerPort | None = None
        process: ProcessPort | None = None
        owned: _OwnedWindowProcess | None = None
        channel: ChannelPort | None = None
        try:
            server = self._pipe_server_factory(pipe_name)
            command = launch.command(
                pipe_name=pipe_name,
                parent_process_id=parent_process_id,
            )
            source_environment = os.environ if launch.environment is None else launch.environment
            environment = sanitized_window_host_environment(
                source_environment,
                forbidden_values=(
                    validated_api_credential,
                    handoff_credential,
                ),
            )
            for secret in (validated_api_credential, handoff_credential):
                if any(secret in argument for argument in command) or any(
                    secret in value for value in environment.values()
                ):
                    raise WindowSupervisorError(
                        "window-host credential crossed the process boundary"
                    )
            process, job = self._process_launcher(
                command,
                cwd=launch.working_directory.resolve(),
                environment=environment,
                creationflags=_NO_WINDOW,
            )
            owned = _OwnedWindowProcess(
                process,
                job,
                monotonic_clock=self._monotonic_clock,
            )
            child_process_id = validate_process_id(
                process.pid,
                label="child process ID",
            )
            _require_running_process(
                process,
                phase="pipe connection",
            )

            def abort_accept() -> None:
                errors: list[BaseException] = []
                try:
                    server.close()
                except BaseException as exc:
                    errors.append(exc)
                try:
                    owned.terminate_and_reap(timeout=self._stop_timeout)
                except BaseException as exc:
                    errors.append(exc)
                if errors:
                    raise errors[0]

            connection = _bounded_call(
                lambda: server.accept(expected_client_pid=child_process_id),
                timeout=self._startup_timeout,
                phase="pipe-accept",
                on_timeout=abort_accept,
                dispose_late_result=lambda connection: connection.close(),
            )
            channel = self._channel_factory(
                connection,
                expected_handoff_id=validated_handoff_id,
                clock=self._wall_clock,
            )
            if (
                channel.handoff_id != validated_handoff_id
                or channel.peer_process_id != child_process_id
            ):
                raise WindowSupervisorProtocolError("window-host channel identity changed")
            _require_running_process(
                process,
                phase="credential bootstrap",
            )

            def bootstrap_exchange() -> HandoffMessage:
                sent = channel.send(
                    "bootstrap",
                    bootstrap_message.payload,
                    deadline_unix_ms=deadline,
                )
                if sent.sequence != 1:
                    raise WindowSupervisorProtocolError("window-host bootstrap sequence is invalid")
                return channel.receive(expected_names={"hello-hidden"})

            def abort_bootstrap() -> None:
                errors: list[BaseException] = []
                try:
                    channel.close()
                except BaseException as exc:
                    errors.append(exc)
                try:
                    owned.terminate_and_reap(timeout=self._stop_timeout)
                except BaseException as exc:
                    errors.append(exc)
                if errors:
                    raise errors[0]

            hello = _bounded_call(
                bootstrap_exchange,
                timeout=self._startup_timeout,
                phase="bootstrap",
                on_timeout=abort_bootstrap,
            )
            if hello.name != "hello-hidden":
                raise WindowSupervisorProtocolError("window-host hello name is invalid")
            if _contains_forbidden_value(
                hello.payload,
                (validated_api_credential, handoff_credential),
            ):
                raise WindowSupervisorProtocolError("window-host hello contained a credential")
            identity = self._verify_hello(
                hello,
                bootstrap=bootstrap,
                parent_process_id=parent_process_id,
                child_process_id=child_process_id,
            )
            _require_running_process(
                process,
                phase="client adoption",
            )
            return WindowHostClient(
                identity,
                base_url=bootstrap.base_url,
                channel=channel,
                owned_process=owned,
                command_timeout=self._command_timeout,
                forbidden_values=(
                    validated_api_credential,
                    handoff_credential,
                ),
                stop_timeout=self._stop_timeout,
                wall_clock=self._wall_clock,
            )
        except BaseException as exc:
            cleanup_errors: list[BaseException] = []
            if channel is not None:
                try:
                    channel.close()
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            elif server is not None:
                try:
                    server.close()
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if owned is not None:
                try:
                    owned.terminate_and_reap(timeout=self._stop_timeout)
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if cleanup_errors:
                raise WindowSupervisorProcessError(
                    "window-host launch cleanup was incomplete"
                ) from None
            if isinstance(exc, WindowSupervisorError):
                if _exception_contains_forbidden_value(
                    exc,
                    (validated_api_credential, handoff_credential),
                ):
                    raise WindowSupervisorProcessError(
                        "window-host process could not be launched"
                    ) from None
                raise
            if isinstance(exc, (HandoffPipeError, HandoffProtocolError)):
                raise WindowSupervisorProtocolError("window-host launch protocol failed") from None
            raise WindowSupervisorProcessError(
                "window-host process could not be launched"
            ) from None

    @staticmethod
    def _verify_hello(
        hello: HandoffMessage,
        *,
        bootstrap: WindowHostBootstrap,
        parent_process_id: int,
        child_process_id: int,
    ) -> WindowHostIdentity:
        result = _strict_result(
            hello,
            request_sequence=1,
            keys=frozenset(
                {
                    "release_id",
                    "process_id",
                    "parent_process_id",
                    "window_handle",
                    "profile_id",
                    "renderer",
                    "hidden",
                    "proof",
                }
            ),
        )
        if result["hidden"] is not True:
            raise WindowSupervisorProtocolError("window-host did not start hidden")
        try:
            identity = WindowHostIdentity(
                release_id=cast(str, result["release_id"]),
                process_id=cast(int, result["process_id"]),
                parent_process_id=cast(int, result["parent_process_id"]),
                window_handle=cast(int, result["window_handle"]),
                profile_id=cast(str, result["profile_id"]),
                renderer=cast(str, result["renderer"]),
            )
        except (HandoffPipeError, ValueError) as exc:
            raise WindowSupervisorProtocolError(
                "window-host hello identity values are invalid"
            ) from exc
        if (
            identity.release_id != bootstrap.release_id
            or identity.process_id != child_process_id
            or identity.parent_process_id != parent_process_id
        ):
            raise WindowSupervisorProtocolError("window-host hello identity is incoherent")
        proof = result["proof"]
        expected_proof = bootstrap_proof(
            bootstrap,
            parent_process_id=parent_process_id,
            child_process_id=child_process_id,
        )
        if (
            type(proof) is not str
            or _DIGEST_PATTERN.fullmatch(proof) is None
            or not secrets.compare_digest(proof, expected_proof)
        ):
            raise WindowSupervisorProtocolError("window-host bootstrap proof is invalid")
        return identity


__all__ = [
    "ChannelFactory",
    "ChannelPort",
    "PipeServerFactory",
    "ProcessJobPort",
    "ProcessLauncher",
    "ProcessPort",
    "WindowHostClient",
    "WindowHostHealth",
    "WindowHostIdentity",
    "WindowHostLaunch",
    "WindowHostSupervisor",
    "WindowSupervisorError",
    "WindowSupervisorProcessError",
    "WindowSupervisorProtocolError",
    "WindowSupervisorTimeout",
    "sanitized_window_host_environment",
]
