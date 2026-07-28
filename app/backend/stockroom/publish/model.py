"""Strict caller-supplied contract for one prepared component publication."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}", re.ASCII)
_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,255}", re.ASCII)
_TRAILER_KEYS = (
    "stockroom-publish-id:",
    "stockroom-component-id:",
)
_WINDOWS_FORBIDDEN_PATH_CHARACTERS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_PATH_STEMS = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
        "com¹",
        "com²",
        "com³",
        "lpt¹",
        "lpt²",
        "lpt³",
    }
)
_ACTIVATION_ONLY_FILENAMES = frozenset(
    {
        "catalog.sqlite",
        "catalog.sqlite-shm",
        "catalog.sqlite-wal",
        "stockroom.dblib",
    }
)


class PublishError(RuntimeError):
    """Base class for scoped publication failures."""


class ManifestValidationError(PublishError):
    """A prepared manifest or staged artifact failed a strict invariant."""


class PublishConflict(PublishError):
    """Current Git/workflow state no longer matches the immutable plan."""


class PublishAmbiguity(PublishError):
    """Evidence admits more than one unsafe interpretation."""


class PublishCheckpoint(StrEnum):
    """Crash-injection boundaries after each durable or external fence."""

    COMMIT_FENCED = "commit_fenced"
    MATERIALIZATION_PROGRESS = "materialization_progress"
    GIT_COMMIT_CREATED = "git_commit_created"
    GIT_COMMIT_RECORDED = "git_commit_recorded"
    CATALOG_ACTIVATED = "catalog_activated"
    CATALOG_RECORDED = "catalog_recorded"


def _strict_identifier(value: object, name: str) -> str:
    if type(value) is not str or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ManifestValidationError(f"{name} is not a canonical identifier")
    return value


def _strict_digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ManifestValidationError(f"{name} is not a lowercase SHA-256 digest")
    return value


def _strict_relative_path(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 768
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
        or any(character in _WINDOWS_FORBIDDEN_PATH_CHARACTERS for character in value)
        or unicodedata.normalize("NFC", value) != value
    ):
        raise ManifestValidationError(f"{name} is not a canonical relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part.casefold() == ".git" for part in path.parts)
        or any(part.endswith((" ", ".")) for part in path.parts)
        or any(
            part.split(".", 1)[0].rstrip(" .").casefold() in _WINDOWS_RESERVED_PATH_STEMS
            for part in path.parts
        )
    ):
        raise ManifestValidationError(f"{name} is not a canonical relative path")
    return value


@dataclass(frozen=True, slots=True)
class PreparedTarget:
    """One staged file and its exact repository-relative destination."""

    target_path: str
    sha256: str

    def __post_init__(self) -> None:
        _strict_relative_path(self.target_path, "target_path")
        _strict_digest(self.sha256, "target sha256")


@dataclass(frozen=True, slots=True)
class PreparedPublicationManifest:
    """Immutable publication inputs supplied by an upstream preparation stage.

    Each prepared target is read from ``staging_root / target_path``.  Tracked
    files are the complete Git allowlist.  Machine-local files and the staged
    catalog are activation-only projections and can never enter that commit.
    """

    publication_id: str
    component_id: str
    staging_root: Path
    tracked_files: tuple[PreparedTarget, ...]
    machine_local_files: tuple[PreparedTarget, ...]
    catalog_staged_path: str
    catalog_sha256: str
    catalog_revision: str
    catalog_semantic_digest: str
    commit_message: str

    def __post_init__(self) -> None:
        _strict_identifier(self.publication_id, "publication_id")
        _strict_identifier(self.component_id, "component_id")
        if not isinstance(self.staging_root, Path) or not self.staging_root.is_absolute():
            raise ManifestValidationError("staging_root must be an absolute Path")
        if (
            type(self.tracked_files) is not tuple
            or not 1 <= len(self.tracked_files) <= 1_000
            or type(self.machine_local_files) is not tuple
            or len(self.machine_local_files) > 1_000
        ):
            raise ManifestValidationError(
                "prepared file collections must be immutable bounded tuples"
            )
        all_files = (*self.tracked_files, *self.machine_local_files)
        if any(type(target) is not PreparedTarget for target in all_files):
            raise ManifestValidationError(
                "prepared file collections must contain PreparedTarget values"
            )

        tracked_folded = [target.target_path.casefold() for target in self.tracked_files]
        machine_folded = [target.target_path.casefold() for target in self.machine_local_files]
        if len(tracked_folded) != len(set(tracked_folded)) or len(machine_folded) != len(
            set(machine_folded)
        ):
            raise ManifestValidationError(
                "prepared paths contain a duplicate or Windows case collision"
            )
        if set(tracked_folded) & set(machine_folded):
            raise ManifestValidationError(
                "tracked and machine-local staged sources must be distinct"
            )
        for target in self.tracked_files:
            filename = PurePosixPath(target.target_path).name.casefold()
            if (
                filename in _ACTIVATION_ONLY_FILENAMES
                or filename.endswith(".dblib")
                or filename.endswith("-wal")
                or filename.endswith("-shm")
            ):
                raise ManifestValidationError(
                    "activation-only projection paths cannot enter the Git allowlist"
                )

        catalog_path = _strict_relative_path(
            self.catalog_staged_path,
            "catalog_staged_path",
        )
        staged_sources = {target.target_path.casefold() for target in all_files}
        if catalog_path.casefold() in staged_sources:
            raise ManifestValidationError(
                "staged catalog path collides with another staged projection"
            )
        _strict_digest(self.catalog_sha256, "catalog sha256")
        _strict_identifier(self.catalog_revision, "catalog_revision")
        _strict_digest(
            self.catalog_semantic_digest,
            "catalog_semantic_digest",
        )

        message = self.commit_message
        if (
            type(message) is not str
            or not message
            or message != message.strip()
            or "\x00" in message
            or "\r" in message
            or len(message.encode("utf-8")) > 16_384
        ):
            raise ManifestValidationError("commit_message is not canonical UTF-8 text")
        for line in message.splitlines():
            folded = line.strip().casefold()
            if any(folded.startswith(key) for key in _TRAILER_KEYS):
                raise ManifestValidationError(
                    "commit_message must not supply reserved Stockroom trailers"
                )

    @property
    def digest(self) -> str:
        """Return the machine-independent workflow manifest digest."""

        payload = {
            "catalog": {
                "revision": self.catalog_revision,
                "semantic_digest": self.catalog_semantic_digest,
            },
            "commit_message": self.commit_message,
            "component_id": self.component_id,
            "publication_id": self.publication_id,
            "tracked_files": [
                {
                    "path": target.target_path,
                    "sha256": target.sha256,
                }
                for target in sorted(
                    self.tracked_files,
                    key=lambda target: target.target_path.casefold(),
                )
            ],
            "version": 1,
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @property
    def local_preparation_digest(self) -> str:
        """Bind machine-local and SQLite byte proofs without changing global identity."""

        payload = {
            "catalog": {
                "sha256": self.catalog_sha256,
                "staged_path": self.catalog_staged_path,
            },
            "machine_local_files": [
                {
                    "path": target.target_path,
                    "sha256": target.sha256,
                }
                for target in sorted(
                    self.machine_local_files,
                    key=lambda target: target.target_path.casefold(),
                )
            ],
            "workflow_manifest_digest": self.digest,
            "version": 1,
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @property
    def final_commit_message(self) -> str:
        return (
            f"{self.commit_message}\n\n"
            f"Stockroom-Publish-ID: {self.publication_id}\n"
            f"Stockroom-Component-ID: {self.component_id}"
        )


__all__ = [
    "ManifestValidationError",
    "PreparedPublicationManifest",
    "PreparedTarget",
    "PublishAmbiguity",
    "PublishCheckpoint",
    "PublishConflict",
    "PublishError",
]
