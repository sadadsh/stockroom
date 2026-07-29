"""Author one deployable, signed TUF feed for an immutable Stockroom release.

The Windows package embeds the pinned root and initial immutable release. This
tool authors the matching online roles and consistent-snapshot targets that the
managed host actually consumes. Production signing keys are explicit ephemeral
inputs; fixture mode uses the deterministic development-only root signer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner, Signer
from tuf.api.exceptions import DownloadHTTPError
from tuf.api.metadata import (
    Metadata,
    MetaFile,
    Root,
    Snapshot,
    TargetFile,
    Targets,
    Timestamp,
)
from tuf.ngclient.fetcher import FetcherInterface

from stockroom.update.manifest import RELEASE_MANIFEST_NAME
from stockroom.update.trusted_repository import (
    TrustedReleaseRepository,
    verify_local_release_set,
)

from .release_bundle import fixture_tuf_signer

_METADATA_URL = "https://metadata.stockroom-feed.invalid/"
_TARGET_URL = "https://targets.stockroom-feed.invalid/"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ReleaseFeedError(ValueError):
    """The release feed could not be authored or verified safely."""


class _RepositoryFetcher(FetcherInterface):
    """Expose a local repository through the updater's HTTPS-shaped boundary."""

    def __init__(self, repository: Path) -> None:
        self._repository = repository.resolve()

    def _fetch(self, url: str) -> Iterator[bytes]:
        parsed = urlsplit(url)
        if parsed.hostname == "metadata.stockroom-feed.invalid":
            base = self._repository / "metadata"
        elif parsed.hostname == "targets.stockroom-feed.invalid":
            base = self._repository / "targets"
        else:
            raise DownloadHTTPError("Unknown release-feed validation host.", 404)
        base = base.resolve()
        candidate = (base / unquote(parsed.path).lstrip("/")).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise DownloadHTTPError("Release-feed validation file not found.", 404)
        data = candidate.read_bytes()
        for offset in range(0, len(data), 128 * 1024):
            yield data[offset : offset + 128 * 1024]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validated_feed_base_uri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ReleaseFeedError(
            "feed base URI must be HTTPS without credentials, query, or fragment"
        )
    return value.rstrip("/")


def _canonical_bytes(document: object) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _load_root(path: Path) -> tuple[Metadata[Root], bytes]:
    try:
        data = Path(path).resolve(strict=True).read_bytes()
        metadata = Metadata.from_bytes(data)
        if not isinstance(metadata.signed, Root):
            raise ReleaseFeedError("pinned TUF metadata is not a root role")
        if not metadata.signed.consistent_snapshot:
            raise ReleaseFeedError(
                "pinned TUF root must enable consistent snapshots"
            )
        metadata.signed.verify_delegate(
            Root.type,
            metadata.signed_bytes,
            metadata.signatures,
        )
    except ReleaseFeedError:
        raise
    except Exception as exc:
        raise ReleaseFeedError("pinned TUF root is invalid") from exc
    return metadata, data


def _load_production_signer(path: Path) -> CryptoSigner:
    try:
        data = Path(path).resolve(strict=True).read_bytes()
        private_key = serialization.load_pem_private_key(data, password=None)
    except Exception as exc:
        raise ReleaseFeedError(
            "production TUF signing keys must be unencrypted PKCS#8 PEM files"
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ReleaseFeedError("production TUF signing keys must be Ed25519")
    return CryptoSigner(private_key)


def _role_signers(
    *,
    mode: str,
    root: Root,
    role: str,
    key_paths: Sequence[Path],
) -> tuple[Signer, ...]:
    if mode == "fixture":
        if key_paths:
            raise ReleaseFeedError("fixture mode refuses production TUF signing keys")
        signers: tuple[Signer, ...] = (fixture_tuf_signer(),)
    else:
        if not key_paths:
            raise ReleaseFeedError(
                f"production requires at least one {role} TUF signing key"
            )
        signers = tuple(_load_production_signer(path) for path in key_paths)

    try:
        delegated_role = root.roles[role]
    except KeyError as exc:
        raise ReleaseFeedError(f"pinned TUF root has no {role} role") from exc
    keyids = [signer.public_key.keyid for signer in signers]
    if len(set(keyids)) != len(keyids):
        raise ReleaseFeedError(f"{role} TUF signing keys must be distinct")
    unauthorized = set(keyids).difference(delegated_role.keyids)
    if unauthorized:
        raise ReleaseFeedError(
            f"{role} TUF signing key is not authorized by the pinned root"
        )
    if len(keyids) < delegated_role.threshold:
        raise ReleaseFeedError(
            f"{role} TUF signing keys do not satisfy the pinned root threshold"
        )
    return signers


def _sign(
    metadata: Metadata[Any],
    signers: Sequence[Signer],
    *,
    root: Root,
    role: str,
) -> bytes:
    for index, signer in enumerate(signers):
        metadata.sign(signer, append=index > 0)
    try:
        root.verify_delegate(role, metadata.signed_bytes, metadata.signatures)
    except Exception as exc:
        raise ReleaseFeedError(
            f"{role} metadata signatures do not satisfy the pinned root"
        ) from exc
    return metadata.to_bytes()


def _write_consistent_target(
    targets_directory: Path,
    target_info: TargetFile,
    data: bytes,
) -> tuple[str, ...]:
    paths = tuple(sorted(target_info.get_prefixed_paths()))
    if not paths:
        raise ReleaseFeedError("TUF did not produce a consistent target path")
    for relative_path in paths:
        destination = targets_directory.joinpath(*relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return paths


def _inventory(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path.read_bytes()),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _write_archive(repository: Path, archive: Path) -> tuple[int, str]:
    archive = archive.resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive.name}-",
        suffix=".tmp",
        dir=archive.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as bundle:
            for path in sorted(repository.rglob("*")):
                if not path.is_file():
                    continue
                relative_path = path.relative_to(repository).as_posix()
                info = zipfile.ZipInfo(relative_path, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                bundle.writestr(info, path.read_bytes(), compresslevel=9)
        os.replace(temporary, archive)
    finally:
        if temporary.exists():
            temporary.unlink()
    data = archive.read_bytes()
    return len(data), _sha256(data)


def _validate_round_trip(
    *,
    repository: Path,
    root_bytes: bytes,
    release_id: str,
    manifest_sha256: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="Stockroom Feed Validation ") as temp:
        validation_root = Path(temp)
        verified = TrustedReleaseRepository(
            bootstrap_root=root_bytes,
            metadata_base_url=_METADATA_URL,
            target_base_url=_TARGET_URL,
            state_directory=validation_root / "State",
            staging_directory=validation_root / "Staging",
            fetcher=_RepositoryFetcher(repository),
        ).stage_release()
        if (
            verified.release_id != release_id
            or verified.manifest_sha256 != manifest_sha256
        ):
            raise ReleaseFeedError(
                "trusted updater round trip selected the wrong release"
            )


def build_release_feed(
    *,
    mode: str,
    feed_base_uri: str,
    root_path: Path,
    release_directory: Path,
    release_id: str,
    expected_manifest_sha256: str,
    metadata_version: int,
    repository_root: Path,
    archive_path: Path,
    evidence_path: Path,
    targets_key_paths: Sequence[Path] = (),
    snapshot_key_paths: Sequence[Path] = (),
    timestamp_key_paths: Sequence[Path] = (),
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """Build, verify, archive, and describe one complete online TUF feed."""

    normalized_mode = mode.casefold()
    if normalized_mode not in {"fixture", "production"}:
        raise ReleaseFeedError("mode must be Fixture or Production")
    if type(metadata_version) is not int or metadata_version <= 0:
        raise ReleaseFeedError("metadata version must be a positive integer")
    feed_base_uri = _validated_feed_base_uri(feed_base_uri)
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    elif reference_time.tzinfo is None:
        raise ReleaseFeedError("reference time must include a timezone")
    reference_time = reference_time.astimezone(timezone.utc)

    verified = verify_local_release_set(
        Path(release_directory).resolve(strict=True),
        expected_release_id=release_id,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    root_metadata, root_bytes = _load_root(root_path)
    root = root_metadata.signed
    role_signers = {
        "targets": _role_signers(
            mode=normalized_mode,
            root=root,
            role="targets",
            key_paths=targets_key_paths,
        ),
        "snapshot": _role_signers(
            mode=normalized_mode,
            root=root,
            role="snapshot",
            key_paths=snapshot_key_paths,
        ),
        "timestamp": _role_signers(
            mode=normalized_mode,
            root=root,
            role="timestamp",
            key_paths=timestamp_key_paths,
        ),
    }

    repository_root = Path(repository_root).resolve()
    archive_path = Path(archive_path).resolve()
    evidence_path = Path(evidence_path).resolve()
    if archive_path == evidence_path:
        raise ReleaseFeedError("archive and evidence paths must be different")
    if (
        archive_path.is_relative_to(repository_root)
        or evidence_path.is_relative_to(repository_root)
    ):
        raise ReleaseFeedError(
            "archive and evidence must be outside the repository root"
        )
    if archive_path.exists() or evidence_path.exists():
        raise ReleaseFeedError("archive and evidence outputs must not already exist")
    if repository_root.exists():
        if not repository_root.is_dir() or any(repository_root.iterdir()):
            raise ReleaseFeedError("repository root must be an empty directory")
    repository_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=f".{repository_root.name}-",
            dir=repository_root.parent,
        )
    )
    try:
        metadata_directory = temporary_root / "metadata"
        targets_directory = temporary_root / "targets"
        metadata_directory.mkdir()
        targets_directory.mkdir()
        (metadata_directory / f"{root.version}.root.json").write_bytes(root_bytes)

        manifest_bytes = verified.manifest_path.read_bytes()
        target_files: dict[str, TargetFile] = {}
        target_records: list[dict[str, object]] = []
        manifest_info = TargetFile.from_data(RELEASE_MANIFEST_NAME, manifest_bytes)
        manifest_info.unrecognized_fields["custom"] = {
            "stockroom": {
                "kind": "release-manifest",
                "manifest_version": verified.manifest.manifest_version,
                "release_id": release_id,
            }
        }
        target_files[RELEASE_MANIFEST_NAME] = manifest_info
        manifest_paths = _write_consistent_target(
            targets_directory,
            manifest_info,
            manifest_bytes,
        )
        target_records.append(
            {
                "consistent_paths": list(manifest_paths),
                "kind": "release-manifest",
                "path": RELEASE_MANIFEST_NAME,
                "sha256": expected_manifest_sha256,
                "size": len(manifest_bytes),
            }
        )

        for member in verified.manifest.members:
            data = verified.members[member.path].read_bytes()
            target_path = f"Releases/{release_id}/{member.path}"
            target_info = TargetFile.from_data(target_path, data)
            target_info.unrecognized_fields["custom"] = {
                "stockroom": {
                    "kind": member.kind,
                    "manifest_sha256": expected_manifest_sha256,
                    "member_path": member.path,
                    "release_id": release_id,
                }
            }
            target_files[target_path] = target_info
            consistent_paths = _write_consistent_target(
                targets_directory,
                target_info,
                data,
            )
            target_records.append(
                {
                    "consistent_paths": list(consistent_paths),
                    "kind": member.kind,
                    "path": target_path,
                    "sha256": member.sha256,
                    "size": member.size,
                }
            )

        targets_metadata = Metadata(
            Targets(
                version=metadata_version,
                expires=reference_time + timedelta(days=90),
                targets=target_files,
            )
        )
        targets_bytes = _sign(
            targets_metadata,
            role_signers["targets"],
            root=root,
            role="targets",
        )
        snapshot_metadata = Metadata(
            Snapshot(
                version=metadata_version,
                expires=reference_time + timedelta(days=14),
                meta={
                    "targets.json": MetaFile.from_data(
                        metadata_version,
                        targets_bytes,
                        ["sha256"],
                    )
                },
            )
        )
        snapshot_bytes = _sign(
            snapshot_metadata,
            role_signers["snapshot"],
            root=root,
            role="snapshot",
        )
        timestamp_metadata = Metadata(
            Timestamp(
                version=metadata_version,
                expires=reference_time + timedelta(days=7),
                snapshot_meta=MetaFile.from_data(
                    metadata_version,
                    snapshot_bytes,
                    ["sha256"],
                ),
            )
        )
        timestamp_bytes = _sign(
            timestamp_metadata,
            role_signers["timestamp"],
            root=root,
            role="timestamp",
        )

        metadata_files = {
            f"{metadata_version}.targets.json": targets_bytes,
            f"{metadata_version}.snapshot.json": snapshot_bytes,
            "timestamp.json": timestamp_bytes,
        }
        for name, data in metadata_files.items():
            (metadata_directory / name).write_bytes(data)

        _validate_round_trip(
            repository=temporary_root,
            root_bytes=root_bytes,
            release_id=release_id,
            manifest_sha256=expected_manifest_sha256,
        )
        inventory = _inventory(temporary_root)
        if repository_root.exists():
            repository_root.rmdir()
        temporary_root.rename(repository_root)
    except Exception:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise

    archive_size, archive_sha256 = _write_archive(
        repository_root,
        archive_path,
    )
    evidence: dict[str, object] = {
        "schema": "stockroom-release-feed/1",
        "mode": normalized_mode,
        "release_id": release_id,
        "manifest_sha256": expected_manifest_sha256,
        "metadata_version": metadata_version,
        "generated_at": reference_time.isoformat().replace("+00:00", "Z"),
        "root": {
            "version": root.version,
            "sha256": _sha256(root_bytes),
            "consistent_snapshot": root.consistent_snapshot,
        },
        "roles": {
            role: {
                "authorized_keyids": sorted(root.roles[role].keyids),
                "signing_keyids": sorted(
                    signer.public_key.keyid for signer in signers
                ),
                "threshold": root.roles[role].threshold,
            }
            for role, signers in role_signers.items()
        },
        "metadata": {
            "targets": {
                "expires": targets_metadata.signed.expires.isoformat(),
                "path": f"metadata/{metadata_version}.targets.json",
                "sha256": _sha256(targets_bytes),
                "version": metadata_version,
            },
            "snapshot": {
                "expires": snapshot_metadata.signed.expires.isoformat(),
                "path": f"metadata/{metadata_version}.snapshot.json",
                "sha256": _sha256(snapshot_bytes),
                "version": metadata_version,
            },
            "timestamp": {
                "expires": timestamp_metadata.signed.expires.isoformat(),
                "path": "metadata/timestamp.json",
                "sha256": _sha256(timestamp_bytes),
                "version": metadata_version,
            },
        },
        "targets": sorted(target_records, key=lambda item: str(item["path"])),
        "repository_inventory": inventory,
        "archive": {
            "path": archive_path.name,
            "sha256": archive_sha256,
            "size": archive_size,
        },
        "validation": {
            "consistent_snapshot_layout": True,
            "online_role_thresholds": True,
            "trusted_updater_round_trip": True,
        },
        "deployment": {
            "external_action_required": normalized_mode == "production",
            "feed_base_uri": feed_base_uri,
            "metadata_base_url": f"{feed_base_uri}/metadata/",
            "metadata_subdirectory": "metadata/",
            "state": (
                "staged-not-deployed"
                if normalized_mode == "production"
                else "fixture-only"
            ),
            "target_base_url": f"{feed_base_uri}/targets/",
            "targets_subdirectory": "targets/",
        },
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_bytes(_canonical_bytes(evidence))
    return evidence


def _parse_reference_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "reference time must be ISO 8601"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("reference time must include a timezone")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("Fixture", "Production"))
    parser.add_argument("--feed-base-uri", required=True)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--release-directory", required=True, type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--metadata-version", required=True, type=int)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--targets-key", action="append", type=Path, default=[])
    parser.add_argument("--snapshot-key", action="append", type=Path, default=[])
    parser.add_argument("--timestamp-key", action="append", type=Path, default=[])
    parser.add_argument("--reference-time", type=_parse_reference_time)
    args = parser.parse_args()
    build_release_feed(
        mode=args.mode,
        feed_base_uri=args.feed_base_uri,
        root_path=args.root,
        release_directory=args.release_directory,
        release_id=args.release_id,
        expected_manifest_sha256=args.manifest_sha256,
        metadata_version=args.metadata_version,
        repository_root=args.repository_root,
        archive_path=args.archive,
        evidence_path=args.evidence,
        targets_key_paths=args.targets_key,
        snapshot_key_paths=args.snapshot_key,
        timestamp_key_paths=args.timestamp_key,
        reference_time=args.reference_time,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
