"""Atomic, revisioned storage for a person's Design Studio document.

The design belongs to the current machine, never the component-library repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from typing import BinaryIO
from dataclasses import dataclass
from pathlib import Path

from stockroom.store.machine_config import config_dir

MAX_PERSONAL_DESIGN_BYTES = 2 * 1024 * 1024
PERSONAL_DESIGN_FILENAME = "design-studio.json"
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_RETRY_SECONDS = 0.01


class PersonalDesignConflict(Exception):
    """The document changed after the caller read its revision."""


class PersonalDesignValidationError(ValueError):
    """The document cannot be safely persisted as a personal design."""


@dataclass(frozen=True)
class PersonalDesignRecord:
    revision: str
    document: dict[str, object]


def _path(root: Path | None) -> Path:
    return (Path(root) if root is not None else config_dir()) / PERSONAL_DESIGN_FILENAME


@contextmanager
def _exclusive_lock(path: Path):
    """Serialize compare-and-replace/delete across threads and processes."""

    lock_path = path.with_name(f".{path.name}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    with lock_path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\\0")
            stream.flush()
        while True:
            try:
                _try_lock(stream)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise PersonalDesignConflict("personal design is busy") from None
                time.sleep(_LOCK_RETRY_SECONDS)
        try:
            yield
        finally:
            _unlock(stream)


def _try_lock(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _reject_json_constant(value: str) -> object:
    raise PersonalDesignValidationError(f"personal design contains invalid JSON constant {value}")


def _validate_document(document: object) -> bytes:
    if type(document) is not dict:
        raise PersonalDesignValidationError("personal design document must be a JSON object")
    schema_version = document.get("schemaVersion")
    if type(schema_version) is not int or schema_version < 1:
        raise PersonalDesignValidationError("personal design schemaVersion must be a positive integer")
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PersonalDesignValidationError("personal design must be JSON serializable") from exc
    if len(encoded) > MAX_PERSONAL_DESIGN_BYTES:
        raise PersonalDesignValidationError("personal design is too large")
    return encoded


def _record_from_bytes(payload: bytes) -> PersonalDesignRecord:
    if len(payload) > MAX_PERSONAL_DESIGN_BYTES:
        raise PersonalDesignValidationError("personal design is too large")
    try:
        document = json.loads(payload, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonalDesignValidationError("personal design is not valid JSON") from exc
    _validate_document(document)
    return PersonalDesignRecord(
        revision=hashlib.sha256(payload).hexdigest(),
        document=document,
    )


def load_personal_design(root: Path | None = None) -> PersonalDesignRecord | None:
    path = _path(root)
    if not path.exists():
        return None
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return None
    return _record_from_bytes(payload)


def _require_revision(current: PersonalDesignRecord | None, expected_revision: str | None) -> None:
    current_revision = current.revision if current is not None else None
    if current_revision != expected_revision:
        raise PersonalDesignConflict("personal design revision is stale")


def save_personal_design(
    document: dict[str, object],
    expected_revision: str | None,
    root: Path | None = None,
) -> PersonalDesignRecord:
    payload = _validate_document(document)
    path = _path(root)
    with _exclusive_lock(path):
        current = load_personal_design(root)
        _require_revision(current, expected_revision)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return _record_from_bytes(payload)


def delete_personal_design(
    expected_revision: str | None,
    root: Path | None = None,
) -> None:
    path = _path(root)
    with _exclusive_lock(path):
        current = load_personal_design(root)
        _require_revision(current, expected_revision)
        if current is not None:
            path.unlink()
