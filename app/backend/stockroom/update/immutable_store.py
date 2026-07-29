"""Immutable accepted-release storage with an atomic Control.sqlite selector.

Release directories are never edited or deleted here.  The authoritative
active-release pointer is the latest generation-fenced ``active_release_selected``
event: one SQLite transaction selects the complete current and previous sets.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from stockroom.service import GenerationFence, ServiceControl, ServiceMode
from stockroom.service.control import JsonValue

from .manifest import (
    RELEASE_MANIFEST_NAME,
    ReleaseManifest,
    ReleaseManifestError,
)
from .trusted_repository import VerifiedReleaseSet

_RECEIPT_SCHEMA_VERSION = 1
_POINTER_SCHEMA_VERSION = 1
_EVENT_PAGE_SIZE = 1_000
_ACCEPTED_EVENT = "release_store_accepted"
_POINTER_EVENT = "active_release_selected"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SELECTION_REASONS = frozenset({"activate", "initialize", "rollback"})


class ImmutableReleaseStoreError(RuntimeError):
    """Base error for immutable accepted-release state."""


class ReleaseStoreAuthorityError(ImmutableReleaseStoreError):
    """A caller lacks a live coordinator generation fence."""


class ReleaseStoreUninitialized(ImmutableReleaseStoreError):
    """No active-release pointer has been initialized."""


class AcceptedReleaseCorruption(ImmutableReleaseStoreError):
    """An accepted receipt, manifest, or release member failed verification."""


class ActiveReleasePointerCorruption(ImmutableReleaseStoreError):
    """The durable active-release selector is malformed or incoherent."""


class ReleaseIdentityConflict(ImmutableReleaseStoreError):
    """One immutable release ID was presented with different bytes."""


@dataclass(frozen=True, slots=True)
class AcceptedRelease:
    """One startup-reverified immutable release set."""

    release_id: str
    directory: Path
    manifest_path: Path
    manifest_sha256: str
    manifest: ReleaseManifest
    members: Mapping[str, Path]


@dataclass(frozen=True, slots=True)
class ActiveReleaseState:
    """The atomically selected current and previous healthy release sets."""

    current: AcceptedRelease
    previous: AcceptedRelease | None
    generation: int
    event_sequence: int
    selection_reason: str


@dataclass(frozen=True, slots=True)
class _ReleaseReference:
    release_id: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class _PointerRecord:
    current: _ReleaseReference
    previous: _ReleaseReference | None
    generation: int
    event_sequence: int
    selection_reason: str


class ImmutableReleaseStore:
    """Accept TUF-verified sets and resolve the durable active selector."""

    def __init__(
        self,
        *,
        releases_directory: Path,
        state_directory: Path,
    ) -> None:
        releases = Path(releases_directory)
        state = Path(state_directory)
        if not releases.is_absolute() or not state.is_absolute():
            raise ValueError("release and state directories must be absolute")
        self.releases_directory = releases.resolve()
        self.state_directory = state.resolve()
        if (
            self.releases_directory == self.state_directory
            or self.releases_directory.is_relative_to(self.state_directory)
            or self.state_directory.is_relative_to(self.releases_directory)
        ):
            raise ValueError("release bytes and mutable state need disjoint directories")
        self._receipts_directory = self.state_directory / "Accepted Releases"

    def accept_verified(
        self,
        release: VerifiedReleaseSet,
        *,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> AcceptedRelease:
        """Re-verify and durably accept a TUF-verified release without selecting it."""

        _require_active_fence(control, fence)
        accepted = self._verify_verified_release(release)
        receipt_path = self._receipt_path(accepted.release_id)
        if receipt_path.exists() or receipt_path.is_symlink():
            existing = self._load_receipt(accepted.release_id)
            if existing.manifest_sha256 != accepted.manifest_sha256:
                raise ReleaseIdentityConflict(
                    "immutable release ID already names a different manifest"
                )
            self._record_acceptance(existing, control=control, fence=fence)
            return existing

        accepted_at = time.time()
        payload = {
            "accepted_at": accepted_at,
            "accepted_generation": fence.generation,
            "manifest_sha256": accepted.manifest_sha256,
            "release_id": accepted.release_id,
            "schema_version": _RECEIPT_SCHEMA_VERSION,
        }
        _atomic_json_write(receipt_path, payload)
        self._record_acceptance(accepted, control=control, fence=fence)
        return accepted

    @staticmethod
    def _record_acceptance(
        accepted: AcceptedRelease,
        *,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> None:
        try:
            control.record_event(
                fence,
                _ACCEPTED_EVENT,
                {
                    "manifest_sha256": accepted.manifest_sha256,
                    "release_id": accepted.release_id,
                    "schema_version": _RECEIPT_SCHEMA_VERSION,
                },
            )
        except BaseException:
            # The unselected receipt is harmless and lets a later fenced retry
            # complete acceptance under its own current generation.
            raise

    def initialize_active(
        self,
        release: VerifiedReleaseSet,
        *,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> ActiveReleaseState:
        """Select the already-running built-in release exactly once."""

        _require_active_fence(control, fence)
        try:
            self._latest_pointer(control)
        except ReleaseStoreUninitialized:
            pass
        else:
            raise ReleaseIdentityConflict("active release store is already initialized")
        accepted = self.accept_verified(release, control=control, fence=fence)
        return self.select_active(
            accepted,
            previous=None,
            selection_reason="initialize",
            control=control,
            fence=fence,
        )

    def select_active(
        self,
        current: AcceptedRelease,
        *,
        previous: AcceptedRelease | None,
        selection_reason: str,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> ActiveReleaseState:
        """Atomically select one whole current set and one healthy fallback."""

        _require_active_fence(control, fence)
        if selection_reason not in _SELECTION_REASONS:
            raise ValueError("selection_reason is invalid")
        verified_current = self._load_receipt(
            current.release_id,
            expected_manifest_sha256=current.manifest_sha256,
        )
        verified_previous: AcceptedRelease | None = None
        if previous is not None:
            verified_previous = self._load_receipt(
                previous.release_id,
                expected_manifest_sha256=previous.manifest_sha256,
            )
            if verified_previous.release_id == verified_current.release_id:
                raise ReleaseIdentityConflict(
                    "current and previous releases must be distinct"
                )

        payload: dict[str, JsonValue] = {
            "current_manifest_sha256": verified_current.manifest_sha256,
            "current_release_id": verified_current.release_id,
            "previous_manifest_sha256": (
                None
                if verified_previous is None
                else verified_previous.manifest_sha256
            ),
            "previous_release_id": (
                None if verified_previous is None else verified_previous.release_id
            ),
            "schema_version": _POINTER_SCHEMA_VERSION,
            "selection_reason": selection_reason,
        }
        sequence = control.record_event(fence, _POINTER_EVENT, payload)
        return ActiveReleaseState(
            current=verified_current,
            previous=verified_previous,
            generation=fence.generation,
            event_sequence=sequence,
            selection_reason=selection_reason,
        )

    def verify_startup(self, control: ServiceControl) -> ActiveReleaseState:
        """Resolve the atomic pointer and re-hash current and previous bytes."""

        pointer = self._latest_pointer(control)
        current = self._load_receipt(
            pointer.current.release_id,
            expected_manifest_sha256=pointer.current.manifest_sha256,
        )
        previous: AcceptedRelease | None = None
        if pointer.previous is not None:
            previous = self._load_receipt(
                pointer.previous.release_id,
                expected_manifest_sha256=pointer.previous.manifest_sha256,
            )
        return ActiveReleaseState(
            current=current,
            previous=previous,
            generation=pointer.generation,
            event_sequence=pointer.event_sequence,
            selection_reason=pointer.selection_reason,
        )

    def _verify_verified_release(
        self, release: VerifiedReleaseSet
    ) -> AcceptedRelease:
        if not isinstance(release, VerifiedReleaseSet):
            raise TypeError("release must be a VerifiedReleaseSet")
        expected_directory = self.releases_directory / release.release_id
        if release.directory.resolve() != expected_directory:
            raise AcceptedReleaseCorruption(
                "verified release is outside the immutable release directory"
            )
        accepted = _verify_release_directory(
            expected_directory,
            expected_release_id=release.release_id,
            expected_manifest_sha256=release.manifest_sha256,
        )
        if accepted.manifest != release.manifest:
            raise AcceptedReleaseCorruption(
                "verified release manifest object does not match its bytes"
            )
        if set(release.members) != set(accepted.members):
            raise AcceptedReleaseCorruption(
                "verified release member map is incomplete"
            )
        for path, member_path in release.members.items():
            if member_path.resolve() != accepted.members[path]:
                raise AcceptedReleaseCorruption(
                    "verified release member map points outside the release set"
                )
        return accepted

    def _receipt_path(self, release_id: str) -> Path:
        _validate_release_id(release_id)
        return self._receipts_directory / f"{release_id}.json"

    def _load_receipt(
        self,
        release_id: str,
        *,
        expected_manifest_sha256: str | None = None,
    ) -> AcceptedRelease:
        receipt_path = self._receipt_path(release_id)
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise AcceptedReleaseCorruption("accepted release receipt is missing or unsafe")
        try:
            payload = _strict_json_object(receipt_path.read_bytes(), "accepted release receipt")
        except OSError as exc:
            raise AcceptedReleaseCorruption("accepted release receipt could not be read") from exc
        expected_fields = {
            "accepted_at",
            "accepted_generation",
            "manifest_sha256",
            "release_id",
            "schema_version",
        }
        if set(payload) != expected_fields:
            raise AcceptedReleaseCorruption("accepted release receipt fields are invalid")
        if payload["schema_version"] != _RECEIPT_SCHEMA_VERSION:
            raise AcceptedReleaseCorruption("accepted release receipt schema is unsupported")
        stored_release_id = _validate_release_id(payload["release_id"])
        if stored_release_id != release_id:
            raise AcceptedReleaseCorruption("accepted release receipt identity is invalid")
        manifest_sha256 = _validate_sha256(payload["manifest_sha256"])
        if (
            expected_manifest_sha256 is not None
            and manifest_sha256 != expected_manifest_sha256
        ):
            raise ReleaseIdentityConflict(
                "active pointer and accepted manifest digest disagree"
            )
        accepted_generation = payload["accepted_generation"]
        if type(accepted_generation) is not int or accepted_generation <= 0:
            raise AcceptedReleaseCorruption(
                "accepted release generation is invalid"
            )
        accepted_at = payload["accepted_at"]
        if (
            isinstance(accepted_at, bool)
            or not isinstance(accepted_at, (int, float))
            or not math.isfinite(float(accepted_at))
        ):
            raise AcceptedReleaseCorruption(
                "accepted release timestamp is invalid"
            )
        return _verify_release_directory(
            self.releases_directory / release_id,
            expected_release_id=release_id,
            expected_manifest_sha256=manifest_sha256,
        )

    @staticmethod
    def _latest_pointer(control: ServiceControl) -> _PointerRecord:
        latest: _PointerRecord | None = None
        after_sequence = 0
        while True:
            events = control.events(
                after_sequence=after_sequence,
                limit=_EVENT_PAGE_SIZE,
            )
            if not events:
                break
            for event in events:
                if event.event_type == _POINTER_EVENT:
                    latest = _parse_pointer_event(
                        event.payload,
                        generation=event.generation,
                        sequence=event.sequence,
                    )
            after_sequence = events[-1].sequence
            if len(events) < _EVENT_PAGE_SIZE:
                break
        if latest is None:
            raise ReleaseStoreUninitialized("active release store is not initialized")
        return latest


def _require_active_fence(control: ServiceControl, fence: GenerationFence) -> None:
    if not isinstance(control, ServiceControl):
        raise TypeError("control must be a ServiceControl")
    if control.mode is not ServiceMode.COORDINATOR:
        raise ReleaseStoreAuthorityError(
            "release-store mutation requires coordinator service mode"
        )
    if type(fence) is not GenerationFence:
        raise ReleaseStoreAuthorityError(
            "release-store mutation requires a generation fence"
        )
    snapshot = control.snapshot()
    if (
        snapshot.mode is not ServiceMode.COORDINATOR
        or snapshot.generation != fence.generation
        or snapshot.owner_id != fence.owner_id
    ):
        raise ReleaseStoreAuthorityError("release-store generation fence is stale")


def _verify_release_directory(
    directory: Path,
    *,
    expected_release_id: str,
    expected_manifest_sha256: str,
) -> AcceptedRelease:
    if directory.is_symlink() or not directory.is_dir():
        raise AcceptedReleaseCorruption("immutable release directory is missing or unsafe")
    manifest_path = directory / RELEASE_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise AcceptedReleaseCorruption("immutable release manifest is missing or unsafe")
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise AcceptedReleaseCorruption("immutable release manifest could not be read") from exc
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha256 != _validate_sha256(expected_manifest_sha256):
        raise AcceptedReleaseCorruption(
            "immutable release manifest digest no longer matches accepted metadata"
        )
    try:
        manifest = ReleaseManifest.from_bytes(manifest_bytes)
    except ReleaseManifestError as exc:
        raise AcceptedReleaseCorruption("immutable release manifest is invalid") from exc
    if manifest.release_id != expected_release_id:
        raise AcceptedReleaseCorruption("immutable release manifest identity changed")

    expected_files = {RELEASE_MANIFEST_NAME}
    expected_directories: set[str] = set()
    members: dict[str, Path] = {}
    for member in manifest.members:
        expected_files.add(member.path)
        parts = member.path.split("/")
        expected_directories.update(
            "/".join(parts[:index]) for index in range(1, len(parts))
        )
        path = directory.joinpath(*parts)
        if path.is_symlink() or not path.is_file():
            raise AcceptedReleaseCorruption(
                f"immutable release member {member.path!r} is missing or unsafe"
            )
        try:
            size = path.stat().st_size
            digest = _sha256_file(path)
        except OSError as exc:
            raise AcceptedReleaseCorruption(
                f"immutable release member {member.path!r} could not be read"
            ) from exc
        if size != member.size or digest != member.sha256:
            raise AcceptedReleaseCorruption(
                f"immutable release member {member.path!r} failed byte verification"
            )
        members[member.path] = path.resolve()

    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for root, directory_names, file_names in os.walk(directory, followlinks=False):
        root_path = Path(root)
        for name in directory_names:
            path = root_path / name
            relative = path.relative_to(directory).as_posix()
            if path.is_symlink():
                raise AcceptedReleaseCorruption(
                    f"immutable release contains an unsafe link at {relative!r}"
                )
            actual_directories.add(relative)
        for name in file_names:
            path = root_path / name
            relative = path.relative_to(directory).as_posix()
            if path.is_symlink():
                raise AcceptedReleaseCorruption(
                    f"immutable release contains an unsafe link at {relative!r}"
                )
            actual_files.add(relative)
    if actual_files != expected_files or actual_directories != expected_directories:
        raise AcceptedReleaseCorruption(
            "immutable release tree contains undeclared files or directories"
        )
    return AcceptedRelease(
        release_id=manifest.release_id,
        directory=directory,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        manifest=manifest,
        members=MappingProxyType(members),
    )


def _parse_pointer_event(
    payload: dict[str, JsonValue],
    *,
    generation: int,
    sequence: int,
) -> _PointerRecord:
    expected_fields = {
        "current_manifest_sha256",
        "current_release_id",
        "previous_manifest_sha256",
        "previous_release_id",
        "schema_version",
        "selection_reason",
    }
    if set(payload) != expected_fields:
        raise ActiveReleasePointerCorruption(
            "active release pointer fields are invalid"
        )
    if payload["schema_version"] != _POINTER_SCHEMA_VERSION:
        raise ActiveReleasePointerCorruption(
            "active release pointer schema is unsupported"
        )
    selection_reason = payload["selection_reason"]
    if type(selection_reason) is not str or selection_reason not in _SELECTION_REASONS:
        raise ActiveReleasePointerCorruption(
            "active release pointer reason is invalid"
        )
    current = _ReleaseReference(
        release_id=_validate_release_id(payload["current_release_id"]),
        manifest_sha256=_validate_sha256(payload["current_manifest_sha256"]),
    )
    previous_release_id = payload["previous_release_id"]
    previous_manifest_sha256 = payload["previous_manifest_sha256"]
    if previous_release_id is None and previous_manifest_sha256 is None:
        previous = None
    elif previous_release_id is not None and previous_manifest_sha256 is not None:
        previous = _ReleaseReference(
            release_id=_validate_release_id(previous_release_id),
            manifest_sha256=_validate_sha256(previous_manifest_sha256),
        )
        if previous.release_id == current.release_id:
            raise ActiveReleasePointerCorruption(
                "active release pointer selects the same current and previous set"
            )
    else:
        raise ActiveReleasePointerCorruption(
            "active release pointer has an incomplete previous set"
        )
    return _PointerRecord(
        current=current,
        previous=previous,
        generation=generation,
        event_sequence=sequence,
        selection_reason=selection_reason,
    )


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise AcceptedReleaseCorruption("accepted release receipt path is unsafe")
    data = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".Accepted-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _strict_json_object(data: bytes, context: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptedReleaseCorruption(f"{context} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AcceptedReleaseCorruption(f"{context} is not a JSON object")
    return value


def _validate_release_id(value: object) -> str:
    if type(value) is not str or _RELEASE_ID_PATTERN.fullmatch(value) is None:
        raise ActiveReleasePointerCorruption("release ID is invalid")
    return value


def _validate_sha256(value: object) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ActiveReleasePointerCorruption("manifest SHA-256 is invalid")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AcceptedRelease",
    "AcceptedReleaseCorruption",
    "ActiveReleasePointerCorruption",
    "ActiveReleaseState",
    "ImmutableReleaseStore",
    "ImmutableReleaseStoreError",
    "ReleaseIdentityConflict",
    "ReleaseStoreAuthorityError",
    "ReleaseStoreUninitialized",
]
