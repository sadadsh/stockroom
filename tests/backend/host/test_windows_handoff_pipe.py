from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import cast

import pytest

from stockroom.host import windows_handoff_pipe as pipe_module
from stockroom.host.windows_handoff_pipe import (
    HANDOFF_SCHEMA,
    HANDOFF_VERSION,
    MAX_DEADLINE_HORIZON_MS,
    MAX_JSON_FRAME_BYTES,
    HandoffChannel,
    HandoffDeadlineExpired,
    HandoffMessage,
    HandoffPipeError,
    HandoffPipeSecurityError,
    HandoffProtocolError,
    WindowsNamedPipeConnection,
    connect_windows_named_pipe,
    create_windows_named_pipe_server,
    new_pipe_name,
    validate_pipe_name,
)

_HANDOFF_ID = "2ed594a5-e46d-4fc0-aecb-17ca94aab32f"
_OTHER_HANDOFF_ID = "af209d62-44da-4f35-b128-1595fa8ac1c7"
_NOW = 1_800_000_000_000
_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"


def _message(
    *,
    sequence: int = 1,
    handoff_id: str = _HANDOFF_ID,
    deadline: int = _NOW + 5_000,
    name: str = "health",
    payload: dict[str, object] | None = None,
) -> HandoffMessage:
    return HandoffMessage(
        handoff_id=handoff_id,
        sequence=sequence,
        deadline_unix_ms=deadline,
        name=name,
        payload=payload or {},
    )


def _frame(message: HandoffMessage) -> bytes:
    body = message.encode(now_unix_ms=_NOW)
    return struct.pack("<I", len(body)) + body


@dataclass
class _MemoryTransport:
    incoming: bytearray = field(default_factory=bytearray)
    peer_process_id: int = 200
    written: bytearray = field(default_factory=bytearray)
    closed: bool = False
    read_requests: list[int] = field(default_factory=list)

    def read_exact(self, size: int) -> bytes:
        self.read_requests.append(size)
        if len(self.incoming) < size:
            result = bytes(self.incoming)
            self.incoming.clear()
            return result
        result = bytes(self.incoming[:size])
        del self.incoming[:size]
        return result

    def write_all(self, data: bytes) -> None:
        self.written.extend(data)

    def close(self) -> None:
        self.closed = True


def test_message_round_trip_is_canonical_bounded_json() -> None:
    expected = _message(
        name="bootstrap",
        payload={"release_id": "release-v2", "flags": [True, 7, None]},
    )

    encoded = expected.encode(now_unix_ms=_NOW)
    decoded = HandoffMessage.decode(encoded, now_unix_ms=_NOW)

    assert decoded == expected
    assert "release-v2" not in repr(decoded)
    assert len(encoded) <= MAX_JSON_FRAME_BYTES
    assert encoded == json.dumps(
        {
            "schema": HANDOFF_SCHEMA,
            "version": HANDOFF_VERSION,
            "handoff_id": _HANDOFF_ID,
            "sequence": 1,
            "deadline_unix_ms": _NOW + 5_000,
            "name": "bootstrap",
            "payload": {"release_id": "release-v2", "flags": [True, 7, None]},
        },
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update({"future": 1}), "invalid fields"),
        (lambda value: value.pop("payload"), "invalid fields"),
        (lambda value: value.update({"version": True}), "version is unsupported"),
        (lambda value: value.update({"schema": "other"}), "schema is unsupported"),
        (lambda value: value.update({"sequence": True}), "sequence must be an integer"),
        (lambda value: value.update({"name": "Show"}), "message name is invalid"),
        (lambda value: value.update({"payload": []}), "payload must be an object"),
    ],
)
def test_message_decode_rejects_unknown_missing_or_weakly_typed_fields(
    change,
    message: str,
) -> None:
    document = json.loads(_message().encode(now_unix_ms=_NOW))
    change(document)

    with pytest.raises(HandoffProtocolError, match=message):
        HandoffMessage.decode(
            json.dumps(document, separators=(",", ":")).encode(),
            now_unix_ms=_NOW,
        )


def test_message_decode_rejects_duplicate_keys_and_nonfinite_numbers() -> None:
    duplicate = (
        b'{"schema":"stockroom.window-handoff","schema":"stockroom.window-handoff",'
        b'"version":1,"handoff_id":"2ed594a5-e46d-4fc0-aecb-17ca94aab32f",'
        b'"sequence":1,"deadline_unix_ms":1800000005000,"name":"health","payload":{}}'
    )
    nonfinite = (
        _message(payload={"value": 1})
        .encode(now_unix_ms=_NOW)
        .replace(
            b'"value":1',
            b'"value":NaN',
        )
    )

    with pytest.raises(HandoffProtocolError, match="duplicate"):
        HandoffMessage.decode(duplicate, now_unix_ms=_NOW)
    with pytest.raises(HandoffProtocolError, match="invalid JSON constant"):
        HandoffMessage.decode(nonfinite, now_unix_ms=_NOW)


def test_deadline_must_be_current_and_short_lived() -> None:
    with pytest.raises(HandoffDeadlineExpired, match="expired"):
        _message(deadline=_NOW - 1).encode(now_unix_ms=_NOW)
    with pytest.raises(HandoffProtocolError, match="allowed horizon"):
        _message(deadline=_NOW + MAX_DEADLINE_HORIZON_MS + 1).encode(now_unix_ms=_NOW)


def test_channel_binds_client_handoff_on_bootstrap_and_sequences_each_direction() -> None:
    transport = _MemoryTransport(incoming=bytearray(_frame(_message(name="bootstrap"))))
    channel = HandoffChannel(
        transport,
        expected_handoff_id=None,
        clock=lambda: _NOW,
    )

    bootstrap = channel.receive(expected_names={"bootstrap"})
    reply = channel.send(
        "hello-hidden",
        {"child_pid": 200},
        deadline_unix_ms=_NOW + 5_000,
    )

    assert bootstrap.handoff_id == _HANDOFF_ID
    assert channel.handoff_id == _HANDOFF_ID
    assert channel.peer_process_id == 200
    assert reply.sequence == 1
    encoded_reply_length = struct.unpack("<I", transport.written[:4])[0]
    encoded_reply = bytes(transport.written[4:])
    assert encoded_reply_length == len(encoded_reply)
    assert HandoffMessage.decode(encoded_reply, now_unix_ms=_NOW) == reply


@pytest.mark.parametrize(
    ("incoming_sequence", "message"),
    [
        (1, "replayed"),
        (3, "gap"),
    ],
)
def test_channel_rejects_replay_and_sequence_gaps(
    incoming_sequence: int,
    message: str,
) -> None:
    transport = _MemoryTransport(
        incoming=bytearray(
            _frame(_message(sequence=1)) + _frame(_message(sequence=incoming_sequence))
        )
    )
    channel = HandoffChannel(
        transport,
        expected_handoff_id=_HANDOFF_ID,
        clock=lambda: _NOW,
    )
    channel.receive()

    with pytest.raises(HandoffProtocolError, match=message):
        channel.receive()


def test_channel_rejects_handoff_change_and_wrong_state_name() -> None:
    changed = _MemoryTransport(incoming=bytearray(_frame(_message(handoff_id=_OTHER_HANDOFF_ID))))
    channel = HandoffChannel(
        changed,
        expected_handoff_id=_HANDOFF_ID,
        clock=lambda: _NOW,
    )
    with pytest.raises(HandoffProtocolError, match="changed"):
        channel.receive()

    wrong_name = _MemoryTransport(incoming=bytearray(_frame(_message(name="show"))))
    channel = HandoffChannel(
        wrong_name,
        expected_handoff_id=_HANDOFF_ID,
        clock=lambda: _NOW,
    )
    with pytest.raises(HandoffProtocolError, match="current state"):
        channel.receive(expected_names={"bootstrap"})


def test_oversize_length_is_rejected_before_the_body_is_read() -> None:
    transport = _MemoryTransport(incoming=bytearray(struct.pack("<I", MAX_JSON_FRAME_BYTES + 1)))
    channel = HandoffChannel(
        transport,
        expected_handoff_id=_HANDOFF_ID,
        clock=lambda: _NOW,
    )

    with pytest.raises(HandoffProtocolError, match="length is invalid"):
        channel.receive()

    assert transport.read_requests == [4]


def test_channel_close_is_idempotent_and_blocks_later_io() -> None:
    transport = _MemoryTransport()
    channel = HandoffChannel(
        transport,
        expected_handoff_id=_HANDOFF_ID,
        clock=lambda: _NOW,
    )

    channel.close()
    channel.close()

    assert transport.closed
    with pytest.raises(HandoffPipeError, match="closed"):
        channel.send("health", {}, deadline_unix_ms=_NOW + 1_000)


@dataclass
class _Identity:
    sid: str = _SID

    def current_sid(self) -> str:
        return self.sid


@dataclass
class _FakePipeApi:
    client_pid: int = 222
    server_pid: int = 111
    server_handle: int = 80
    client_handle: int = 81
    create_calls: list[tuple[str, str]] = field(default_factory=list)
    open_calls: list[tuple[str, int]] = field(default_factory=list)
    accepted: list[int] = field(default_factory=list)
    disconnected: list[int] = field(default_factory=list)
    closed: list[int] = field(default_factory=list)
    reads: bytearray = field(default_factory=bytearray)
    writes: bytearray = field(default_factory=bytearray)
    max_write: int | None = None

    def create_server(self, full_name: str, *, sid: str) -> int:
        self.create_calls.append((full_name, sid))
        return self.server_handle

    def accept_server(self, handle: int) -> None:
        self.accepted.append(handle)

    def open_client(self, full_name: str, *, timeout_ms: int) -> int:
        self.open_calls.append((full_name, timeout_ms))
        return self.client_handle

    def client_process_id(self, handle: int) -> int:
        assert handle == self.server_handle
        return self.client_pid

    def server_process_id(self, handle: int) -> int:
        assert handle == self.client_handle
        return self.server_pid

    def read(self, handle: int, size: int) -> bytes:
        assert handle in {self.server_handle, self.client_handle}
        take = min(size, 2, len(self.reads))
        result = bytes(self.reads[:take])
        del self.reads[:take]
        return result

    def write(self, handle: int, data: bytes) -> int:
        assert handle in {self.server_handle, self.client_handle}
        take = min(len(data), self.max_write or len(data))
        self.writes.extend(data[:take])
        return take

    def disconnect(self, handle: int) -> None:
        self.disconnected.append(handle)

    def close(self, handle: int) -> None:
        self.closed.append(handle)


def test_server_uses_current_sid_and_accepts_only_the_exact_launched_child_pid() -> None:
    name = new_pipe_name()
    api = _FakePipeApi(client_pid=222)
    server = create_windows_named_pipe_server(
        name,
        api=api,
        identity=_Identity(),
    )

    connection = server.accept(expected_client_pid=222)

    assert api.create_calls == [(rf"\\.\pipe\{name}", _SID)]
    assert api.accepted == [80]
    assert connection.peer_process_id == 222
    connection.close()
    assert api.disconnected == [80]
    assert api.closed == [80]


def test_server_rejects_a_different_client_pid_and_closes_the_instance() -> None:
    api = _FakePipeApi(client_pid=333)
    server = create_windows_named_pipe_server(
        new_pipe_name(),
        api=api,
        identity=_Identity(),
    )

    with pytest.raises(HandoffPipeSecurityError, match="launched child"):
        server.accept(expected_client_pid=222)

    assert api.disconnected == [80]
    assert api.closed == [80]


def test_client_verifies_exact_parent_pid_before_returning_the_pipe() -> None:
    name = new_pipe_name()
    api = _FakePipeApi(server_pid=111)

    connection = connect_windows_named_pipe(
        name,
        expected_server_pid=111,
        timeout_ms=4_000,
        api=api,
    )

    assert api.open_calls == [(rf"\\.\pipe\{name}", 4_000)]
    assert connection.peer_process_id == 111
    connection.close()
    assert api.disconnected == []
    assert api.closed == [81]


def test_client_rejects_a_different_server_pid_before_any_read() -> None:
    api = _FakePipeApi(server_pid=999)

    with pytest.raises(HandoffPipeSecurityError, match="expected parent"):
        connect_windows_named_pipe(
            new_pipe_name(),
            expected_server_pid=111,
            api=api,
        )

    assert api.closed == [81]


def test_verified_connection_completes_partial_reads_and_writes() -> None:
    api = _FakePipeApi(reads=bytearray(b"abcdef"), max_write=2)
    connection = WindowsNamedPipeConnection(
        api,
        81,
        peer_process_id=111,
        server_side=False,
    )

    assert connection.read_exact(6) == b"abcdef"
    connection.write_all(b"uvwxyz")

    assert api.writes == b"uvwxyz"


@pytest.mark.parametrize(
    "name",
    [
        "Stockroom.WindowHandoff.not-hex",
        r"\\.\pipe\Stockroom.WindowHandoff." + "a" * 32,
        "Stockroom.WindowHandoff." + "A" * 32,
        "Other." + "a" * 32,
    ],
)
def test_only_canonical_nonsecret_pipe_names_are_accepted(name: str) -> None:
    with pytest.raises(HandoffPipeSecurityError, match="name is invalid"):
        validate_pipe_name(name)


def test_native_server_descriptor_grants_only_current_sid_and_is_not_inheritable() -> None:
    api = object.__new__(pipe_module._WindowsPipeApi)
    observed: dict[str, object] = {}

    def make_descriptor(sddl, revision, descriptor, size) -> bool:
        observed["sddl"] = sddl
        observed["revision"] = revision
        descriptor._obj.value = 1234
        size._obj.value = 64
        return True

    def make_pipe(
        full_name,
        access,
        mode,
        instances,
        output_size,
        input_size,
        timeout,
        attributes,
    ) -> int:
        observed.update(
            {
                "full_name": full_name,
                "access": access,
                "mode": mode,
                "instances": instances,
                "output_size": output_size,
                "input_size": input_size,
                "timeout": timeout,
                "inherit": bool(attributes._obj.bInheritHandle),
            }
        )
        return 90

    freed: list[int] = []
    api._to_security_descriptor = make_descriptor
    api._create_named_pipe = make_pipe
    api._local_free = lambda pointer: freed.append(pointer.value)

    handle = api.create_server(r"\\.\pipe\Stockroom.WindowHandoff." + "a" * 32, sid=_SID)

    assert handle == 90
    assert observed["sddl"] == f"D:P(A;;0x0012019f;;;{_SID})"
    assert "SY" not in str(observed["sddl"])
    assert "BA" not in str(observed["sddl"])
    assert observed["instances"] == 1
    assert observed["inherit"] is False
    assert cast(int, observed["access"]) & pipe_module._FILE_FLAG_FIRST_PIPE_INSTANCE
    assert cast(int, observed["mode"]) & pipe_module._PIPE_REJECT_REMOTE_CLIENTS
    assert observed["output_size"] == MAX_JSON_FRAME_BYTES + 4
    assert observed["input_size"] == MAX_JSON_FRAME_BYTES + 4
    assert freed == [1234]
