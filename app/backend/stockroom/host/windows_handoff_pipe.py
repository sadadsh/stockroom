"""PID-bound, current-user Windows named pipes for window-host handoff.

The pipe name is deliberately non-secret.  Authority comes from three
independent checks:

* the server creates one first-instance pipe with a protected DACL containing
  only the verified current Windows SID;
* the server verifies ``GetNamedPipeClientProcessId`` against the exact child
  it launched, while the child verifies ``GetNamedPipeServerProcessId``
  against the exact parent PID passed on its command line; and
* every bounded JSON message carries one handoff UUID, an exact monotonic
  sequence, and a short deadline.

Fresh handoff and API credentials are payload data sent only after those
kernel checks.  They never belong in the pipe name, argv, environment, URL, or
logs.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import struct
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from ctypes import wintypes
from dataclasses import dataclass, field
from types import TracebackType
from typing import Protocol, Self, cast

from stockroom.service.ports import (
    CurrentIdentityPort,
    WindowsCurrentIdentity,
    is_windows_sid,
)

HANDOFF_SCHEMA = "stockroom.window-handoff"
HANDOFF_VERSION = 1
MAX_JSON_FRAME_BYTES = 64 * 1024
MAX_DEADLINE_HORIZON_MS = 5 * 60 * 1000

_PIPE_PREFIX = "Stockroom.WindowHandoff."
_PIPE_NAME_PATTERN = re.compile(
    rf"{re.escape(_PIPE_PREFIX)}[0-9a-f]{{32}}",
    re.ASCII,
)
_HANDOFF_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,63}", re.ASCII)
_MAX_SEQUENCE = (1 << 63) - 1
_MAX_JSON_DEPTH = 16
_MAX_JSON_ITEMS = 4096
_MAX_STRING_LENGTH = 48 * 1024

_PIPE_ACCESS_DUPLEX = 0x00000003
_FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_ERROR_PIPE_CONNECTED = 535
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_SDDL_REVISION_1 = 1
_PIPE_ACCESS_MASK = 0x0012019F


class HandoffPipeError(RuntimeError):
    """Base error for the native transport boundary."""


class HandoffPipeSecurityError(HandoffPipeError):
    """The pipe ACL, name, or exact peer process was not trustworthy."""


class HandoffProtocolError(HandoffPipeError):
    """A frame violated the bounded handoff protocol."""


class HandoffDeadlineExpired(HandoffProtocolError):
    """A validly encoded message arrived after its declared deadline."""


class ByteTransport(Protocol):
    """The framed channel's small blocking-byte transport."""

    @property
    def peer_process_id(self) -> int: ...

    def read_exact(self, size: int) -> bytes: ...

    def write_all(self, data: bytes) -> None: ...

    def close(self) -> None: ...


def _now_unix_ms() -> int:
    return time.time_ns() // 1_000_000


def new_pipe_name() -> str:
    """Return a fresh, non-secret local pipe name safe for argv."""

    return _PIPE_PREFIX + uuid.uuid4().hex


def validate_pipe_name(value: object) -> str:
    if type(value) is not str or _PIPE_NAME_PATTERN.fullmatch(value) is None:
        raise HandoffPipeSecurityError("window-handoff pipe name is invalid")
    return value


def _full_pipe_name(name: str) -> str:
    return rf"\\.\pipe\{validate_pipe_name(name)}"


def validate_process_id(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0 or value > 0xFFFFFFFF:
        raise HandoffPipeSecurityError(f"{label} must be a positive Windows process ID")
    return value


def validate_handoff_id(value: object) -> str:
    if type(value) is not str:
        raise HandoffProtocolError("handoff_id must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HandoffProtocolError("handoff_id must be a canonical UUID") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise HandoffProtocolError("handoff_id must be a canonical UUIDv4")
    return value


def _validate_message_name(value: object) -> str:
    if type(value) is not str or _HANDOFF_NAME_PATTERN.fullmatch(value) is None:
        raise HandoffProtocolError("message name is invalid")
    return value


def _validate_json_value(value: object, *, depth: int = 0) -> int:
    if depth > _MAX_JSON_DEPTH:
        raise HandoffProtocolError("message payload nesting exceeds the limit")
    if value is None or type(value) in {bool, int}:
        return 1
    if type(value) is float:
        if not math.isfinite(cast(float, value)):
            raise HandoffProtocolError("message payload contains a non-finite number")
        return 1
    if type(value) is str:
        if len(value) > _MAX_STRING_LENGTH:
            raise HandoffProtocolError("message payload string exceeds the limit")
        return 1
    if type(value) is list:
        total = 1
        for item in cast(list[object], value):
            total += _validate_json_value(item, depth=depth + 1)
            if total > _MAX_JSON_ITEMS:
                raise HandoffProtocolError("message payload contains too many values")
        return total
    if type(value) is dict:
        total = 1
        for key, item in cast(dict[object, object], value).items():
            if type(key) is not str or not key or len(key) > 128:
                raise HandoffProtocolError("message payload contains an invalid object key")
            total += _validate_json_value(item, depth=depth + 1)
            if total > _MAX_JSON_ITEMS:
                raise HandoffProtocolError("message payload contains too many values")
        return total
    raise HandoffProtocolError("message payload contains a non-JSON value")


def _strict_object(
    value: object,
    *,
    label: str,
    keys: frozenset[str],
) -> dict[str, object]:
    if type(value) is not dict:
        raise HandoffProtocolError(f"{label} must be an object")
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping):
        raise HandoffProtocolError(f"{label} keys must be strings")
    actual = frozenset(cast(str, key) for key in mapping)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        raise HandoffProtocolError(f"{label} has invalid fields: {', '.join(details)}")
    return cast(dict[str, object], mapping)


@dataclass(frozen=True, slots=True)
class HandoffMessage:
    """One fully validated handoff message."""

    handoff_id: str
    sequence: int
    deadline_unix_ms: int
    name: str
    payload: dict[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        validate_handoff_id(self.handoff_id)
        if type(self.sequence) is not int or not 1 <= self.sequence <= _MAX_SEQUENCE:
            raise HandoffProtocolError("sequence must be a supported positive integer")
        if type(self.deadline_unix_ms) is not int or self.deadline_unix_ms <= 0:
            raise HandoffProtocolError("deadline_unix_ms must be a positive integer")
        _validate_message_name(self.name)
        if type(self.payload) is not dict:
            raise HandoffProtocolError("payload must be an object")
        _validate_json_value(self.payload)

    def encode(self, *, now_unix_ms: int | None = None) -> bytes:
        now = _now_unix_ms() if now_unix_ms is None else now_unix_ms
        _validate_deadline(self.deadline_unix_ms, now_unix_ms=now)
        document = {
            "schema": HANDOFF_SCHEMA,
            "version": HANDOFF_VERSION,
            "handoff_id": self.handoff_id,
            "sequence": self.sequence,
            "deadline_unix_ms": self.deadline_unix_ms,
            "name": self.name,
            "payload": self.payload,
        }
        try:
            encoded = json.dumps(
                document,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        except (TypeError, ValueError, RecursionError) as exc:
            raise HandoffProtocolError("message could not be encoded as strict JSON") from exc
        if not encoded or len(encoded) > MAX_JSON_FRAME_BYTES:
            raise HandoffProtocolError("message exceeds the JSON frame limit")
        return encoded

    @classmethod
    def decode(
        cls,
        encoded: bytes,
        *,
        now_unix_ms: int | None = None,
    ) -> HandoffMessage:
        if type(encoded) is not bytes or not encoded or len(encoded) > MAX_JSON_FRAME_BYTES:
            raise HandoffProtocolError("message exceeds the JSON frame limit")

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise HandoffProtocolError("message contains duplicate object keys")
                result[key] = value
            return result

        def reject_constant(value: str) -> None:
            raise HandoffProtocolError(f"message contains invalid JSON constant {value}")

        try:
            decoded = json.loads(
                encoded.decode("utf-8"),
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_constant,
            )
        except HandoffProtocolError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise HandoffProtocolError("message is not strict UTF-8 JSON") from exc
        mapping = _strict_object(
            decoded,
            label="message",
            keys=frozenset(
                {
                    "schema",
                    "version",
                    "handoff_id",
                    "sequence",
                    "deadline_unix_ms",
                    "name",
                    "payload",
                }
            ),
        )
        if mapping["schema"] != HANDOFF_SCHEMA:
            raise HandoffProtocolError("message schema is unsupported")
        if type(mapping["version"]) is not int or mapping["version"] != HANDOFF_VERSION:
            raise HandoffProtocolError("message version is unsupported")
        if type(mapping["sequence"]) is not int:
            raise HandoffProtocolError("sequence must be an integer")
        if type(mapping["deadline_unix_ms"]) is not int:
            raise HandoffProtocolError("deadline_unix_ms must be an integer")
        if type(mapping["payload"]) is not dict:
            raise HandoffProtocolError("payload must be an object")
        message = cls(
            handoff_id=validate_handoff_id(mapping["handoff_id"]),
            sequence=mapping["sequence"],
            deadline_unix_ms=mapping["deadline_unix_ms"],
            name=_validate_message_name(mapping["name"]),
            payload=cast(dict[str, object], mapping["payload"]),
        )
        now = _now_unix_ms() if now_unix_ms is None else now_unix_ms
        _validate_deadline(message.deadline_unix_ms, now_unix_ms=now)
        return message


def _validate_deadline(deadline_unix_ms: int, *, now_unix_ms: int) -> None:
    if type(now_unix_ms) is not int or now_unix_ms <= 0:
        raise HandoffProtocolError("current clock value is invalid")
    if deadline_unix_ms < now_unix_ms:
        raise HandoffDeadlineExpired("message deadline expired")
    if deadline_unix_ms > now_unix_ms + MAX_DEADLINE_HORIZON_MS:
        raise HandoffProtocolError("message deadline exceeds the allowed horizon")


class HandoffChannel:
    """A strictly sequenced framed channel over one verified pipe connection."""

    def __init__(
        self,
        transport: ByteTransport,
        *,
        expected_handoff_id: str | None,
        clock: Callable[[], int] = _now_unix_ms,
    ) -> None:
        self._transport = transport
        self._handoff_id = (
            None if expected_handoff_id is None else validate_handoff_id(expected_handoff_id)
        )
        self._clock = clock
        self._next_incoming_sequence = 1
        self._next_outgoing_sequence = 1
        self._closed = False

    @property
    def handoff_id(self) -> str:
        if self._handoff_id is None:
            raise HandoffProtocolError("handoff_id is not bound until the first message")
        return self._handoff_id

    @property
    def peer_process_id(self) -> int:
        return self._transport.peer_process_id

    def send(
        self,
        name: str,
        payload: Mapping[str, object],
        *,
        deadline_unix_ms: int,
    ) -> HandoffMessage:
        if self._closed:
            raise HandoffPipeError("handoff channel is closed")
        if self._handoff_id is None:
            raise HandoffProtocolError("a receiving client cannot send before bootstrap")
        if type(payload) is not dict:
            payload = dict(payload)
        message = HandoffMessage(
            handoff_id=self._handoff_id,
            sequence=self._next_outgoing_sequence,
            deadline_unix_ms=deadline_unix_ms,
            name=name,
            payload=cast(dict[str, object], payload),
        )
        body = message.encode(now_unix_ms=self._clock())
        self._transport.write_all(struct.pack("<I", len(body)) + body)
        self._next_outgoing_sequence += 1
        return message

    def receive(
        self,
        *,
        expected_names: Collection[str] | None = None,
    ) -> HandoffMessage:
        if self._closed:
            raise HandoffPipeError("handoff channel is closed")
        prefix = self._transport.read_exact(4)
        if len(prefix) != 4:
            raise HandoffPipeError("handoff pipe closed inside a frame prefix")
        (length,) = struct.unpack("<I", prefix)
        if length == 0 or length > MAX_JSON_FRAME_BYTES:
            raise HandoffProtocolError("incoming JSON frame length is invalid")
        body = self._transport.read_exact(length)
        if len(body) != length:
            raise HandoffPipeError("handoff pipe closed inside a JSON frame")
        message = HandoffMessage.decode(body, now_unix_ms=self._clock())
        if self._handoff_id is None:
            self._handoff_id = message.handoff_id
        elif message.handoff_id != self._handoff_id:
            raise HandoffProtocolError("handoff_id changed inside one channel")
        if message.sequence != self._next_incoming_sequence:
            if message.sequence < self._next_incoming_sequence:
                raise HandoffProtocolError("message sequence was replayed")
            raise HandoffProtocolError("message sequence has a gap")
        if expected_names is not None and message.name not in expected_names:
            raise HandoffProtocolError("message name is not valid in the current state")
        self._next_incoming_sequence += 1
        return message

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def __enter__(self) -> Self:
        if self._closed:
            raise HandoffPipeError("handoff channel is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class WindowsPipeApi(Protocol):
    """Injectable native calls used by the server/client ownership wrappers."""

    def create_server(self, full_name: str, *, sid: str) -> int: ...

    def accept_server(self, handle: int) -> None: ...

    def open_client(self, full_name: str, *, timeout_ms: int) -> int: ...

    def client_process_id(self, handle: int) -> int: ...

    def server_process_id(self, handle: int) -> int: ...

    def read(self, handle: int, size: int) -> bytes: ...

    def write(self, handle: int, data: bytes) -> int: ...

    def disconnect(self, handle: int) -> None: ...

    def close(self, handle: int) -> None: ...


class _WindowsPipeApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise HandoffPipeError("Windows named pipes are unavailable")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]

        self._create_named_pipe = self._kernel32.CreateNamedPipeW
        self._create_named_pipe.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SecurityAttributes),
        ]
        self._create_named_pipe.restype = wintypes.HANDLE
        self._connect_named_pipe = self._kernel32.ConnectNamedPipe
        self._connect_named_pipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self._connect_named_pipe.restype = wintypes.BOOL
        self._disconnect_named_pipe = self._kernel32.DisconnectNamedPipe
        self._disconnect_named_pipe.argtypes = [wintypes.HANDLE]
        self._disconnect_named_pipe.restype = wintypes.BOOL
        self._wait_named_pipe = self._kernel32.WaitNamedPipeW
        self._wait_named_pipe.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        self._wait_named_pipe.restype = wintypes.BOOL
        self._create_file = self._kernel32.CreateFileW
        self._create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self._create_file.restype = wintypes.HANDLE
        self._get_client_pid = self._kernel32.GetNamedPipeClientProcessId
        self._get_client_pid.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.ULONG),
        ]
        self._get_client_pid.restype = wintypes.BOOL
        self._get_server_pid = self._kernel32.GetNamedPipeServerProcessId
        self._get_server_pid.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.ULONG),
        ]
        self._get_server_pid.restype = wintypes.BOOL
        self._read_file = self._kernel32.ReadFile
        self._read_file.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self._read_file.restype = wintypes.BOOL
        self._write_file = self._kernel32.WriteFile
        self._write_file.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self._write_file.restype = wintypes.BOOL
        self._close_handle = self._kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL
        self._local_free = self._kernel32.LocalFree
        self._local_free.argtypes = [ctypes.c_void_p]
        self._local_free.restype = ctypes.c_void_p
        self._to_security_descriptor = (
            self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
        )
        self._to_security_descriptor.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._to_security_descriptor.restype = wintypes.BOOL

    def _raise_last_error(self, message: str) -> HandoffPipeError:
        return HandoffPipeError(f"{message} (Win32 error {ctypes.get_last_error()})")

    def create_server(self, full_name: str, *, sid: str) -> int:
        if not is_windows_sid(sid):
            raise HandoffPipeSecurityError("window-handoff SID is invalid")
        security_descriptor = ctypes.c_void_p()
        descriptor_size = wintypes.DWORD()
        sddl = f"D:P(A;;0x{_PIPE_ACCESS_MASK:08x};;;{sid})"
        if not self._to_security_descriptor(
            sddl,
            _SDDL_REVISION_1,
            ctypes.byref(security_descriptor),
            ctypes.byref(descriptor_size),
        ):
            raise self._raise_last_error("window-handoff pipe DACL could not be created")
        try:
            attributes = _SecurityAttributes(
                nLength=ctypes.sizeof(_SecurityAttributes),
                lpSecurityDescriptor=security_descriptor,
                bInheritHandle=False,
            )
            ctypes.set_last_error(0)
            raw_handle = self._create_named_pipe(
                full_name,
                _PIPE_ACCESS_DUPLEX | _FILE_FLAG_FIRST_PIPE_INSTANCE,
                _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT | _PIPE_REJECT_REMOTE_CLIENTS,
                1,
                MAX_JSON_FRAME_BYTES + 4,
                MAX_JSON_FRAME_BYTES + 4,
                5_000,
                ctypes.byref(attributes),
            )
            handle = int(raw_handle or 0)
            if not handle or handle == _INVALID_HANDLE_VALUE:
                raise self._raise_last_error("window-handoff pipe could not be created")
            return handle
        finally:
            if security_descriptor.value:
                self._local_free(security_descriptor)

    def accept_server(self, handle: int) -> None:
        ctypes.set_last_error(0)
        if self._connect_named_pipe(handle, None):
            return
        if ctypes.get_last_error() != _ERROR_PIPE_CONNECTED:
            raise self._raise_last_error("window-handoff client could not connect")

    def open_client(self, full_name: str, *, timeout_ms: int) -> int:
        if not self._wait_named_pipe(full_name, timeout_ms):
            raise self._raise_last_error("window-handoff server was not available")
        raw_handle = self._create_file(
            full_name,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        handle = int(raw_handle or 0)
        if not handle or handle == _INVALID_HANDLE_VALUE:
            raise self._raise_last_error("window-handoff client could not open the pipe")
        return handle

    def client_process_id(self, handle: int) -> int:
        process_id = wintypes.ULONG()
        if not self._get_client_pid(handle, ctypes.byref(process_id)):
            raise self._raise_last_error("window-handoff client PID could not be verified")
        return int(process_id.value)

    def server_process_id(self, handle: int) -> int:
        process_id = wintypes.ULONG()
        if not self._get_server_pid(handle, ctypes.byref(process_id)):
            raise self._raise_last_error("window-handoff server PID could not be verified")
        return int(process_id.value)

    def read(self, handle: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        transferred = wintypes.DWORD()
        if not self._read_file(
            handle,
            buffer,
            size,
            ctypes.byref(transferred),
            None,
        ):
            raise self._raise_last_error("window-handoff pipe read failed")
        return bytes(buffer.raw[: transferred.value])

    def write(self, handle: int, data: bytes) -> int:
        transferred = wintypes.DWORD()
        if not self._write_file(
            handle,
            data,
            len(data),
            ctypes.byref(transferred),
            None,
        ):
            raise self._raise_last_error("window-handoff pipe write failed")
        return int(transferred.value)

    def disconnect(self, handle: int) -> None:
        self._disconnect_named_pipe(handle)

    def close(self, handle: int) -> None:
        if not self._close_handle(handle):
            raise self._raise_last_error("window-handoff pipe handle could not be closed")


class WindowsNamedPipeConnection:
    """One PID-verified byte stream with exact close ownership."""

    def __init__(
        self,
        api: WindowsPipeApi,
        handle: int,
        *,
        peer_process_id: int,
        server_side: bool,
    ) -> None:
        self._api = api
        self._handle = handle
        self._peer_process_id = validate_process_id(
            peer_process_id,
            label="peer process ID",
        )
        self._server_side = server_side
        self._closed = False

    @property
    def peer_process_id(self) -> int:
        return self._peer_process_id

    def read_exact(self, size: int) -> bytes:
        if self._closed:
            raise HandoffPipeError("window-handoff pipe is closed")
        if type(size) is not int or size <= 0 or size > MAX_JSON_FRAME_BYTES:
            raise HandoffProtocolError("requested pipe read size is invalid")
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self._api.read(self._handle, remaining)
            if not chunk:
                raise HandoffPipeError("window-handoff peer closed the pipe")
            if len(chunk) > remaining:
                raise HandoffPipeError("window-handoff pipe returned too many bytes")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def write_all(self, data: bytes) -> None:
        if self._closed:
            raise HandoffPipeError("window-handoff pipe is closed")
        if type(data) is not bytes or not data or len(data) > MAX_JSON_FRAME_BYTES + 4:
            raise HandoffProtocolError("outgoing pipe frame size is invalid")
        offset = 0
        while offset < len(data):
            written = self._api.write(self._handle, data[offset:])
            if written <= 0 or written > len(data) - offset:
                raise HandoffPipeError("window-handoff pipe write made invalid progress")
            offset += written

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failure: BaseException | None = None
        if self._server_side:
            try:
                self._api.disconnect(self._handle)
            except BaseException as exc:
                failure = exc
        try:
            self._api.close(self._handle)
        except BaseException as exc:
            if failure is None:
                failure = exc
        if failure is not None:
            raise failure


class WindowsNamedPipeServer:
    """A current-user-only first-instance server awaiting one exact child PID."""

    def __init__(self, api: WindowsPipeApi, handle: int, *, pipe_name: str) -> None:
        self._api = api
        self._handle = handle
        self.pipe_name = pipe_name
        self._closed = False

    def accept(self, *, expected_client_pid: int) -> WindowsNamedPipeConnection:
        if self._closed:
            raise HandoffPipeError("window-handoff server is closed")
        expected = validate_process_id(expected_client_pid, label="expected client PID")
        try:
            self._api.accept_server(self._handle)
            actual = self._api.client_process_id(self._handle)
            if actual != expected:
                raise HandoffPipeSecurityError(
                    "window-handoff client PID did not match the launched child"
                )
        except BaseException:
            self.close()
            raise
        handle = self._handle
        self._handle = 0
        self._closed = True
        return WindowsNamedPipeConnection(
            self._api,
            handle,
            peer_process_id=actual,
            server_side=True,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failure: BaseException | None = None
        try:
            self._api.disconnect(self._handle)
        except BaseException as exc:
            failure = exc
        try:
            self._api.close(self._handle)
        except BaseException as exc:
            if failure is None:
                failure = exc
        self._handle = 0
        if failure is not None:
            raise failure

    def __enter__(self) -> Self:
        if self._closed:
            raise HandoffPipeError("window-handoff server is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def create_windows_named_pipe_server(
    pipe_name: str,
    *,
    api: WindowsPipeApi | None = None,
    identity: CurrentIdentityPort | None = None,
) -> WindowsNamedPipeServer:
    """Create the protected server before launching the expected child."""

    name = validate_pipe_name(pipe_name)
    native = api or _WindowsPipeApi()
    sid = (identity or WindowsCurrentIdentity()).current_sid()
    if not is_windows_sid(sid):
        raise HandoffPipeSecurityError("current Windows SID is invalid")
    handle = native.create_server(_full_pipe_name(name), sid=sid)
    return WindowsNamedPipeServer(native, handle, pipe_name=name)


def connect_windows_named_pipe(
    pipe_name: str,
    *,
    expected_server_pid: int,
    timeout_ms: int = 15_000,
    api: WindowsPipeApi | None = None,
) -> WindowsNamedPipeConnection:
    """Connect as the child and verify the exact parent PID before any read."""

    name = validate_pipe_name(pipe_name)
    expected = validate_process_id(expected_server_pid, label="expected server PID")
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 60_000:
        raise HandoffPipeError("window-handoff connection timeout is invalid")
    native = api or _WindowsPipeApi()
    handle = native.open_client(_full_pipe_name(name), timeout_ms=timeout_ms)
    try:
        actual = native.server_process_id(handle)
        if actual != expected:
            raise HandoffPipeSecurityError(
                "window-handoff server PID did not match the expected parent"
            )
    except BaseException:
        native.close(handle)
        raise
    return WindowsNamedPipeConnection(
        native,
        handle,
        peer_process_id=actual,
        server_side=False,
    )


__all__ = [
    "ByteTransport",
    "HANDOFF_SCHEMA",
    "HANDOFF_VERSION",
    "HandoffChannel",
    "HandoffDeadlineExpired",
    "HandoffMessage",
    "HandoffPipeError",
    "HandoffPipeSecurityError",
    "HandoffProtocolError",
    "MAX_DEADLINE_HORIZON_MS",
    "MAX_JSON_FRAME_BYTES",
    "WindowsNamedPipeConnection",
    "WindowsNamedPipeServer",
    "WindowsPipeApi",
    "connect_windows_named_pipe",
    "create_windows_named_pipe_server",
    "new_pipe_name",
    "validate_handoff_id",
    "validate_pipe_name",
    "validate_process_id",
]
