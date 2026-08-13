"""TUF-backed staging of complete, immutable Stockroom release sets.

This module deliberately stops at verified staging.  It has no activation,
rollback, Git, process-management, signing-key, or trust-root generation path.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from tuf.api import exceptions as tuf_exceptions
from tuf.api.metadata import Metadata, Root, TargetFile
from tuf.api.serialization import DeserializationError
from tuf.ngclient import Updater
from tuf.ngclient.fetcher import FetcherInterface

from .manifest import (
    MAX_RELEASE_MANIFEST_BYTES,
    RELEASE_MANIFEST_NAME,
    ReleaseManifest,
    ReleaseManifestError,
    ReleaseMember,
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class TrustedRepositoryError(RuntimeError):
    """Base error for trusted repository verification and staging."""


class PinnedRootError(TrustedRepositoryError):
    """The mandatory pinned TUF bootstrap root is absent or invalid."""


class RepositoryRefreshError(TrustedRepositoryError):
    """TUF could not establish one fresh, coherent repository view."""


class ReleaseSetVerificationError(TrustedRepositoryError):
    """A release target set is incomplete, mixed, unsafe, or corrupt."""


class _WindowsSafeUpdater(Updater):
    """Persist the current trusted root atomically without requiring a symlink.

    python-tuf normally exposes ``root.json`` as a symlink into ``root_history``.
    Ordinary packaged Windows applications do not have symlink privilege, so
    that final cache step can fail after the trusted history was written and
    leave update checks permanently blocked. The root bytes copied here have
    already been accepted by ``TrustedMetadataSet``; the versioned history
    remains the rotation and rollback authority.
    """

    def _update_root_symlink(self) -> None:
        version = self._trusted_set.root.version
        root_directory = Path(self._dir, "root_history")
        trusted_root = (root_directory / f"{version}.root.json").read_bytes()
        self._persist_file(os.fspath(Path(self._dir, "root.json")), trusted_root)


@dataclass(frozen=True, slots=True)
class VerifiedReleaseSet:
    """A complete verified set that has been atomically published to staging."""

    release_id: str
    directory: Path
    manifest_path: Path
    manifest_sha256: str
    manifest: ReleaseManifest
    members: Mapping[str, Path]


class TrustedReleaseRepository:
    """Refresh trusted TUF metadata and stage one coherent release set."""

    def __init__(
        self,
        *,
        bootstrap_root: bytes,
        metadata_base_url: str,
        target_base_url: str,
        state_directory: Path,
        staging_directory: Path,
        fetcher: FetcherInterface | None = None,
    ) -> None:
        self._bootstrap_root = _validate_bootstrap_root(bootstrap_root)
        self._metadata_base_url = _validate_repository_url(metadata_base_url, "metadata_base_url")
        self._target_base_url = _validate_repository_url(target_base_url, "target_base_url")
        self._metadata_directory = Path(state_directory).resolve() / "Trusted Metadata"
        self._staging_directory = Path(staging_directory).resolve()
        if self._metadata_directory == self._staging_directory:
            raise ValueError("Trusted metadata and staged releases need separate directories.")
        self._fetcher = fetcher
        self._lock = threading.Lock()

    def stage_release(self) -> VerifiedReleaseSet:
        """Download, verify, and atomically expose the current release target set."""

        with self._lock:
            self._metadata_directory.mkdir(parents=True, exist_ok=True)
            self._staging_directory.mkdir(parents=True, exist_ok=True)
            incoming_directory = Path(
                tempfile.mkdtemp(prefix=".Incoming-", dir=self._staging_directory)
            )
            try:
                updater = self._new_updater()
                self._refresh(updater)
                manifest_info = self._target_info(updater, RELEASE_MANIFEST_NAME)
                if manifest_info.length > MAX_RELEASE_MANIFEST_BYTES:
                    raise ReleaseSetVerificationError(
                        "The signed release manifest exceeds the accepted size limit."
                    )

                manifest_path = incoming_directory / RELEASE_MANIFEST_NAME
                self._download_target(updater, manifest_info, manifest_path)
                manifest_bytes = manifest_path.read_bytes()
                try:
                    manifest = ReleaseManifest.from_bytes(manifest_bytes)
                except ReleaseManifestError as exc:
                    raise ReleaseSetVerificationError(
                        "The signed release manifest is invalid."
                    ) from exc

                manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
                _verify_manifest_target_binding(manifest_info, manifest)

                for member in manifest.members:
                    target_path = manifest.target_path_for(member)
                    target_info = self._target_info(updater, target_path)
                    _verify_member_target_binding(
                        target_info,
                        member=member,
                        release_id=manifest.release_id,
                        manifest_sha256=manifest_sha256,
                    )
                    self._download_target(
                        updater,
                        target_info,
                        incoming_directory.joinpath(*member.path.split("/")),
                    )

                _verify_release_tree(
                    incoming_directory,
                    manifest=manifest,
                    manifest_bytes=manifest_bytes,
                )
                return self._publish_verified_set(
                    incoming_directory,
                    manifest=manifest,
                    manifest_bytes=manifest_bytes,
                    manifest_sha256=manifest_sha256,
                )
            except TrustedRepositoryError:
                raise
            except OSError as exc:
                raise ReleaseSetVerificationError(
                    "The verified release could not be staged atomically."
                ) from exc
            finally:
                if incoming_directory.exists():
                    shutil.rmtree(incoming_directory)

    def _new_updater(self) -> Updater:
        try:
            return _WindowsSafeUpdater(
                metadata_dir=os.fspath(self._metadata_directory),
                metadata_base_url=self._metadata_base_url,
                target_base_url=self._target_base_url,
                fetcher=self._fetcher,
                bootstrap=self._bootstrap_root,
            )
        except (OSError, tuf_exceptions.RepositoryError) as exc:
            raise RepositoryRefreshError(
                "The pinned TUF trust state could not be initialized."
            ) from exc

    @staticmethod
    def _refresh(updater: Updater) -> None:
        try:
            updater.refresh()
        except (
            OSError,
            tuf_exceptions.DownloadError,
            tuf_exceptions.RepositoryError,
        ) as exc:
            raise RepositoryRefreshError(
                "TUF rejected or could not refresh the repository metadata."
            ) from exc

    @staticmethod
    def _target_info(updater: Updater, target_path: str) -> TargetFile:
        try:
            target_info = updater.get_targetinfo(target_path)
        except (
            OSError,
            tuf_exceptions.DownloadError,
            tuf_exceptions.RepositoryError,
        ) as exc:
            raise ReleaseSetVerificationError(
                f"TUF could not verify release target {target_path!r}."
            ) from exc
        if target_info is None:
            raise ReleaseSetVerificationError(
                f"The signed repository does not contain release target {target_path!r}."
            )
        return target_info

    @staticmethod
    def _download_target(updater: Updater, target_info: TargetFile, path: Path) -> None:
        try:
            updater.download_target(target_info, filepath=os.fspath(path))
        except (
            OSError,
            tuf_exceptions.DownloadError,
            tuf_exceptions.RepositoryError,
        ) as exc:
            raise ReleaseSetVerificationError(
                f"TUF rejected release target {target_info.path!r}."
            ) from exc

    def _publish_verified_set(
        self,
        incoming_directory: Path,
        *,
        manifest: ReleaseManifest,
        manifest_bytes: bytes,
        manifest_sha256: str,
    ) -> VerifiedReleaseSet:
        release_directory = self._staging_directory / manifest.release_id
        if release_directory.exists() or release_directory.is_symlink():
            return _load_existing_verified_set(
                release_directory,
                manifest=manifest,
                manifest_bytes=manifest_bytes,
                manifest_sha256=manifest_sha256,
            )

        try:
            incoming_directory.rename(release_directory)
        except FileExistsError:
            return _load_existing_verified_set(
                release_directory,
                manifest=manifest,
                manifest_bytes=manifest_bytes,
                manifest_sha256=manifest_sha256,
            )
        return _build_verified_set(
            release_directory,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )


def verify_local_release_set(
    directory: Path,
    *,
    expected_release_id: str,
    expected_manifest_sha256: str,
) -> VerifiedReleaseSet:
    """Re-hash a package-authenticated local release into the verified-set shape.

    This performs no network trust decision. The caller must obtain the expected
    release ID and manifest digest from an authenticated package descriptor.
    """

    release_directory = Path(directory)
    if not release_directory.is_absolute():
        raise ValueError("local release directory must be absolute")
    if not expected_release_id or _SHA256_PATTERN.fullmatch(expected_manifest_sha256) is None:
        raise ReleaseSetVerificationError("The packaged release identity is invalid.")
    manifest_path = release_directory / RELEASE_MANIFEST_NAME
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ReleaseSetVerificationError(
            "The packaged release manifest could not be read."
        ) from exc
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha256 != expected_manifest_sha256:
        raise ReleaseSetVerificationError("The packaged release manifest digest is invalid.")
    try:
        manifest = ReleaseManifest.from_bytes(manifest_bytes)
    except ReleaseManifestError as exc:
        raise ReleaseSetVerificationError("The packaged release manifest is invalid.") from exc
    if manifest.release_id != expected_release_id:
        raise ReleaseSetVerificationError("The packaged release manifest identity is invalid.")
    _verify_release_tree(
        release_directory,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
    )
    return _build_verified_set(
        release_directory,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


def _validate_bootstrap_root(bootstrap_root: bytes) -> bytes:
    if not isinstance(bootstrap_root, bytes) or not bootstrap_root:
        raise PinnedRootError("A non-empty pinned TUF bootstrap root is mandatory.")
    try:
        metadata = Metadata.from_bytes(bootstrap_root)
        if not isinstance(metadata.signed, Root):
            raise PinnedRootError("Pinned TUF bootstrap metadata is not a root role.")
        metadata.signed.verify_delegate(Root.type, metadata.signed_bytes, metadata.signatures)
    except PinnedRootError:
        raise
    except (
        DeserializationError,
        KeyError,
        TypeError,
        ValueError,
        tuf_exceptions.RepositoryError,
    ) as exc:
        raise PinnedRootError("Pinned TUF bootstrap root is invalid.") from exc
    return bytes(bootstrap_root)


def _validate_repository_url(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an HTTPS URL.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field} must be an HTTPS URL without credentials, query, or fragment.")
    return value


def _verify_manifest_target_binding(target_info: TargetFile, manifest: ReleaseManifest) -> None:
    expected_custom = {
        "stockroom": {
            "kind": "release-manifest",
            "manifest_version": manifest.manifest_version,
            "release_id": manifest.release_id,
        }
    }
    if target_info.path != RELEASE_MANIFEST_NAME or target_info.custom != expected_custom:
        raise ReleaseSetVerificationError(
            "The release manifest target is not bound to the declared release."
        )


def _verify_member_target_binding(
    target_info: TargetFile,
    *,
    member: ReleaseMember,
    release_id: str,
    manifest_sha256: str,
) -> None:
    expected_path = f"Releases/{release_id}/{member.path}"
    expected_custom = {
        "stockroom": {
            "kind": member.kind,
            "manifest_sha256": manifest_sha256,
            "member_path": member.path,
            "release_id": release_id,
        }
    }
    if (
        target_info.path != expected_path
        or target_info.length != member.size
        or target_info.hashes.get("sha256") != member.sha256
        or target_info.custom != expected_custom
    ):
        raise ReleaseSetVerificationError(
            f"Release target {expected_path!r} does not match the signed manifest."
        )


def _verify_release_tree(
    directory: Path,
    *,
    manifest: ReleaseManifest,
    manifest_bytes: bytes,
) -> None:
    manifest_path = directory / RELEASE_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ReleaseSetVerificationError("The staged release manifest is missing or unsafe.")
    if manifest_path.read_bytes() != manifest_bytes:
        raise ReleaseSetVerificationError("The staged release manifest changed after download.")

    expected_files = {RELEASE_MANIFEST_NAME}
    expected_directories: set[str] = set()
    for member in manifest.members:
        expected_files.add(member.path)
        path = directory.joinpath(*member.path.split("/"))
        if path.is_symlink() or not path.is_file():
            raise ReleaseSetVerificationError(
                f"Staged release member {member.path!r} is missing or unsafe."
            )
        if path.stat().st_size != member.size or _sha256_file(path) != member.sha256:
            raise ReleaseSetVerificationError(
                f"Staged release member {member.path!r} failed final verification."
            )
        parent = _parent_directories(member.path)
        expected_directories.update(parent)

    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for root, directory_names, file_names in os.walk(directory, followlinks=False):
        root_path = Path(root)
        for name in directory_names:
            path = root_path / name
            relative = path.relative_to(directory).as_posix()
            if path.is_symlink():
                raise ReleaseSetVerificationError(
                    f"Staged release contains an unsafe link at {relative!r}."
                )
            actual_directories.add(relative)
        for name in file_names:
            path = root_path / name
            relative = path.relative_to(directory).as_posix()
            if path.is_symlink():
                raise ReleaseSetVerificationError(
                    f"Staged release contains an unsafe link at {relative!r}."
                )
            actual_files.add(relative)

    if actual_files != expected_files or actual_directories != expected_directories:
        raise ReleaseSetVerificationError(
            "The staged release tree contains undeclared files or directories."
        )


def _parent_directories(path: str) -> set[str]:
    """Return all directory prefixes for a validated POSIX relative file path."""

    parts = path.split("/")[:-1]
    return {"/".join(parts[:index]) for index in range(1, len(parts) + 1)}


def _load_existing_verified_set(
    directory: Path,
    *,
    manifest: ReleaseManifest,
    manifest_bytes: bytes,
    manifest_sha256: str,
) -> VerifiedReleaseSet:
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseSetVerificationError(
            "The existing staged release path is not a safe directory."
        )
    _verify_release_tree(
        directory,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
    )
    return _build_verified_set(
        directory,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


def _build_verified_set(
    directory: Path,
    *,
    manifest: ReleaseManifest,
    manifest_sha256: str,
) -> VerifiedReleaseSet:
    members = {
        member.path: directory.joinpath(*member.path.split("/")) for member in manifest.members
    }
    return VerifiedReleaseSet(
        release_id=manifest.release_id,
        directory=directory,
        manifest_path=directory / RELEASE_MANIFEST_NAME,
        manifest_sha256=manifest_sha256,
        manifest=manifest,
        members=MappingProxyType(members),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
