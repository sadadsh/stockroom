from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
from securesystemslib.signer import CryptoSigner
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
    PinnedRootError,
    ReleaseSetVerificationError,
    RepositoryRefreshError,
    TrustedReleaseRepository,
)

METADATA_URL = "https://metadata.stockroom.test/"
TARGET_URL = "https://targets.stockroom.test/"


class TemporaryRepositoryFetcher(FetcherInterface):
    """Serve one temporary on-disk repository through HTTPS-shaped URLs."""

    def __init__(self, repository: Path) -> None:
        self._repository = repository.resolve()
        self.requests: list[str] = []

    def _fetch(self, url: str) -> Iterator[bytes]:
        self.requests.append(url)
        parsed = urlsplit(url)
        if parsed.hostname == "metadata.stockroom.test":
            base = self._repository / "metadata"
        elif parsed.hostname == "targets.stockroom.test":
            base = self._repository / "targets"
        else:
            raise DownloadHTTPError("Unknown temporary repository host.", 404)

        candidate = (base / unquote(parsed.path).lstrip("/")).resolve()
        if not candidate.is_relative_to(base.resolve()) or not candidate.is_file():
            raise DownloadHTTPError("Temporary repository target not found.", 404)
        data = candidate.read_bytes()
        for offset in range(0, len(data), 97):
            yield data[offset : offset + 97]


class TemporarySignedRepository:
    """Test-only TUF repository authoring fixture."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.metadata_directory = root / "metadata"
        self.targets_directory = root / "targets"
        self.metadata_directory.mkdir(parents=True)
        self.targets_directory.mkdir(parents=True)
        self._signers = {
            role: CryptoSigner.generate_ed25519()
            for role in ("root", "snapshot", "targets", "timestamp")
        }
        root_role = Root(
            version=1,
            expires=datetime.now(timezone.utc) + timedelta(days=30),
            consistent_snapshot=True,
        )
        for role, signer in self._signers.items():
            root_role.add_key(signer.public_key, role)
        root_metadata = Metadata(root_role)
        root_metadata.sign(self._signers["root"])
        self.bootstrap_root = root_metadata.to_bytes()
        (self.metadata_directory / "1.root.json").write_bytes(self.bootstrap_root)

    def publish(
        self,
        manifest: dict[str, Any],
        payloads: dict[str, bytes],
        *,
        version: int = 1,
        timestamp_expires: datetime | None = None,
        snapshot_expires: datetime | None = None,
        targets_expires: datetime | None = None,
        member_release_override: str | None = None,
    ) -> bytes:
        manifest_bytes = _json_bytes(manifest)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        release_id = manifest["release_id"]

        target_files: dict[str, TargetFile] = {}
        manifest_info = TargetFile.from_data(RELEASE_MANIFEST_NAME, manifest_bytes)
        manifest_info.unrecognized_fields["custom"] = {
            "stockroom": {
                "kind": "release-manifest",
                "manifest_version": manifest["manifest_version"],
                "release_id": release_id,
            }
        }
        target_files[RELEASE_MANIFEST_NAME] = manifest_info
        self._write_consistent_target(manifest_info, manifest_bytes)

        members = {member["path"]: member for member in manifest["members"]}
        for member_path, payload in payloads.items():
            member = members[member_path]
            target_path = f"Releases/{release_id}/{member_path}"
            target_info = TargetFile.from_data(target_path, payload)
            target_info.unrecognized_fields["custom"] = {
                "stockroom": {
                    "kind": member["kind"],
                    "manifest_sha256": manifest_sha256,
                    "member_path": member_path,
                    "release_id": member_release_override or release_id,
                }
            }
            target_files[target_path] = target_info
            self._write_consistent_target(target_info, payload)

        targets_role = Targets(
            version=version,
            expires=targets_expires
            or datetime.now(timezone.utc) + timedelta(days=7),
            targets=target_files,
        )
        targets_metadata = Metadata(targets_role)
        targets_metadata.sign(self._signers["targets"])
        targets_bytes = targets_metadata.to_bytes()

        snapshot_role = Snapshot(
            version=version,
            expires=snapshot_expires
            or datetime.now(timezone.utc) + timedelta(days=2),
            meta={
                "targets.json": MetaFile.from_data(
                    version, targets_bytes, ["sha256"]
                )
            },
        )
        snapshot_metadata = Metadata(snapshot_role)
        snapshot_metadata.sign(self._signers["snapshot"])
        snapshot_bytes = snapshot_metadata.to_bytes()

        timestamp_role = Timestamp(
            version=version,
            expires=timestamp_expires
            or datetime.now(timezone.utc) + timedelta(hours=12),
            snapshot_meta=MetaFile.from_data(
                version, snapshot_bytes, ["sha256"]
            ),
        )
        timestamp_metadata = Metadata(timestamp_role)
        timestamp_metadata.sign(self._signers["timestamp"])
        timestamp_bytes = timestamp_metadata.to_bytes()

        (self.metadata_directory / f"{version}.targets.json").write_bytes(targets_bytes)
        (self.metadata_directory / f"{version}.snapshot.json").write_bytes(snapshot_bytes)
        (self.metadata_directory / "timestamp.json").write_bytes(timestamp_bytes)
        return manifest_bytes

    def _write_consistent_target(self, target_info: TargetFile, data: bytes) -> None:
        for relative_path in target_info.get_prefixed_paths():
            destination = self.targets_directory.joinpath(*relative_path.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)


def _payloads() -> dict[str, bytes]:
    return {
        "Backend/Stockroom.pyz": b"verified backend",
        "Frontend/Assets.zip": b"verified frontend",
        "Runtime/Python.zip": b"verified runtime",
        "Schemas/Catalog.sql": b"create table component(id text);",
        "Support/SBOM.spdx.json": b'{"spdxVersion":"SPDX-2.3"}',
    }


def _manifest(
    payloads: dict[str, bytes],
    *,
    release_id: str = "2026.07.29.1",
    rollback_release_id: str = "2026.07.28.4",
) -> dict[str, Any]:
    kinds = {
        "Backend/Stockroom.pyz": "backend",
        "Frontend/Assets.zip": "frontend",
        "Runtime/Python.zip": "runtime",
        "Schemas/Catalog.sql": "schema",
        "Support/SBOM.spdx.json": "sbom",
    }
    members = [
        {
            "kind": kinds[path],
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for path, data in payloads.items()
    ]
    sbom_digest = next(member["sha256"] for member in members if member["kind"] == "sbom")
    return {
        "api_compatibility": {"maximum": 5, "minimum": 3},
        "manifest_version": 1,
        "members": members,
        "migration": {
            "catalog": {"from": 6, "to": 7},
            "control": {"from": 3, "to": 4},
        },
        "minimum_host_version": "2.1.0",
        "package_version": "4.8.0",
        "protocol_version": 4,
        "release_id": release_id,
        "required_eda_bridge_version": "3.2.1",
        "required_odbc_driver_version": "18.5.1.1",
        "rollback_release_id": rollback_release_id,
        "sbom_sha256": sbom_digest,
        "schema_compatibility": {
            "catalog": {"maximum": 8, "minimum": 7},
            "control": {"maximum": 5, "minimum": 4},
        },
        "workflow_code_versions": {"cad-acquisition": 12, "library-publication": 8},
    }


def _client(
    repository: TemporarySignedRepository,
    tmp_path: Path,
    fetcher: TemporaryRepositoryFetcher,
) -> TrustedReleaseRepository:
    return TrustedReleaseRepository(
        bootstrap_root=repository.bootstrap_root,
        metadata_base_url=METADATA_URL,
        target_base_url=TARGET_URL,
        state_directory=tmp_path / "client-state",
        staging_directory=tmp_path / "staged-releases",
        fetcher=fetcher,
    )


def test_stages_every_signed_member_as_one_atomic_immutable_set(tmp_path: Path) -> None:
    payloads = _payloads()
    manifest = _manifest(payloads)
    repository = TemporarySignedRepository(tmp_path / "repository")
    repository.publish(manifest, payloads)
    fetcher = TemporaryRepositoryFetcher(repository.root)
    client = _client(repository, tmp_path, fetcher)

    release = client.stage_release()

    assert release.release_id == manifest["release_id"]
    assert release.directory == tmp_path / "staged-releases" / manifest["release_id"]
    assert release.manifest_path.read_bytes() == _json_bytes(manifest)
    assert set(release.members) == set(payloads)
    assert {path: release.members[path].read_bytes() for path in payloads} == payloads
    assert not list((tmp_path / "staged-releases").glob(".Incoming-*"))
    with pytest.raises(TypeError):
        release.members["Injected.exe"] = release.directory / "Injected.exe"  # ty: ignore[invalid-assignment]

    second = client.stage_release()

    assert second.directory == release.directory
    assert second.manifest_sha256 == release.manifest_sha256
    assert any(url.endswith("/timestamp.json") for url in fetcher.requests)
    assert any("Release Manifest.json" in url for url in fetcher.requests)


def test_tuf_binding_preserves_v2_skipped_release_compatibility(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    manifest = _manifest(
        payloads,
        release_id="2026.07.29.4",
        rollback_release_id="2026.07.29.3",
    )
    manifest["manifest_version"] = 2
    manifest["compatible_from_release_ids"] = [
        "2026.07.29.3",
        "2026.07.28.4",
    ]
    repository = TemporarySignedRepository(tmp_path / "repository")
    repository.publish(manifest, payloads)

    release = _client(
        repository,
        tmp_path,
        TemporaryRepositoryFetcher(repository.root),
    ).stage_release()

    assert release.manifest.manifest_version == 2
    assert release.manifest.supports_direct_activation_from("2026.07.28.4")


def test_pinned_bootstrap_root_is_mandatory(tmp_path: Path) -> None:
    with pytest.raises(PinnedRootError, match="mandatory"):
        TrustedReleaseRepository(
            bootstrap_root=b"",
            metadata_base_url=METADATA_URL,
            target_base_url=TARGET_URL,
            state_directory=tmp_path / "state",
            staging_directory=tmp_path / "staging",
        )


@pytest.mark.parametrize("expired_role", ["snapshot", "targets", "timestamp"])
def test_expired_tuf_metadata_blocks_acceptance_and_leaves_no_partial_release(
    tmp_path: Path,
    expired_role: str,
) -> None:
    payloads = _payloads()
    repository = TemporarySignedRepository(tmp_path / "repository")
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    repository.publish(
        _manifest(payloads),
        payloads,
        snapshot_expires=expired if expired_role == "snapshot" else None,
        targets_expires=expired if expired_role == "targets" else None,
        timestamp_expires=expired if expired_role == "timestamp" else None,
    )
    client = _client(
        repository, tmp_path, TemporaryRepositoryFetcher(repository.root)
    )

    with pytest.raises(RepositoryRefreshError):
        client.stage_release()

    assert not list((tmp_path / "staged-releases").iterdir())


def test_persisted_tuf_state_rejects_repository_rollback(tmp_path: Path) -> None:
    payloads = _payloads()
    manifest = _manifest(payloads)
    repository = TemporarySignedRepository(tmp_path / "repository")
    repository.publish(manifest, payloads, version=2)
    client = _client(
        repository, tmp_path, TemporaryRepositoryFetcher(repository.root)
    )
    accepted = client.stage_release()

    repository.publish(manifest, payloads, version=1)
    with pytest.raises(RepositoryRefreshError):
        client.stage_release()

    assert accepted.directory.is_dir()
    assert accepted.manifest_path.is_file()
    assert not list((tmp_path / "staged-releases").glob(".Incoming-*"))


def test_release_id_can_never_be_reused_for_different_signed_bytes(tmp_path: Path) -> None:
    payloads = _payloads()
    manifest = _manifest(payloads)
    repository = TemporarySignedRepository(tmp_path / "repository")
    repository.publish(manifest, payloads, version=1)
    client = _client(
        repository, tmp_path, TemporaryRepositoryFetcher(repository.root)
    )
    accepted = client.stage_release()
    accepted_backend = accepted.members["Backend/Stockroom.pyz"].read_bytes()

    changed_payloads = {**payloads, "Backend/Stockroom.pyz": b"different backend"}
    repository.publish(_manifest(changed_payloads), changed_payloads, version=2)
    with pytest.raises(ReleaseSetVerificationError):
        client.stage_release()

    assert accepted.members["Backend/Stockroom.pyz"].read_bytes() == accepted_backend
    assert not list((tmp_path / "staged-releases").glob(".Incoming-*"))


def test_tuf_rejects_snapshot_mix_and_match_before_target_download(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    repository = TemporarySignedRepository(tmp_path / "repository")
    repository.publish(_manifest(payloads), payloads)
    snapshot = repository.metadata_directory / "1.snapshot.json"
    snapshot.write_bytes(snapshot.read_bytes() + b" ")
    fetcher = TemporaryRepositoryFetcher(repository.root)
    client = _client(repository, tmp_path, fetcher)

    with pytest.raises(RepositoryRefreshError):
        client.stage_release()

    assert not any(url.startswith(TARGET_URL) for url in fetcher.requests)
    assert not list((tmp_path / "staged-releases").iterdir())


def test_signed_member_from_another_release_is_rejected(tmp_path: Path) -> None:
    payloads = _payloads()
    repository = TemporarySignedRepository(tmp_path / "repository")
    repository.publish(
        _manifest(payloads),
        payloads,
        member_release_override="2026.07.20.9",
    )
    client = _client(
        repository, tmp_path, TemporaryRepositoryFetcher(repository.root)
    )

    with pytest.raises(ReleaseSetVerificationError, match="signed manifest"):
        client.stage_release()

    assert not list((tmp_path / "staged-releases").iterdir())


def test_corrupt_payload_never_becomes_a_visible_release(tmp_path: Path) -> None:
    payloads = _payloads()
    manifest = _manifest(payloads)
    repository = TemporarySignedRepository(tmp_path / "repository")
    repository.publish(manifest, payloads)
    member = manifest["members"][-1]
    target_path = f"Releases/{manifest['release_id']}/{member['path']}"
    target_info = TargetFile.from_data(target_path, payloads[member["path"]])
    prefixed_path = target_info.get_prefixed_paths()[0]
    target_file = repository.targets_directory.joinpath(*prefixed_path.split("/"))
    target_file.write_bytes(b"corrupt")
    client = _client(
        repository, tmp_path, TemporaryRepositoryFetcher(repository.root)
    )

    with pytest.raises(ReleaseSetVerificationError):
        client.stage_release()

    assert not list((tmp_path / "staged-releases").iterdir())


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
