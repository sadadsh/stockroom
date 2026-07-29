"""Author and verify the immutable release bundle embedded in the Windows package.

Production receives its offline-authored TUF root as an explicit build input.
Fixture builds use one public, deterministic development-only root so the full
managed host can be exercised without inventing production trust.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root

from stockroom.update.manifest import ReleaseManifest
from stockroom.update.trusted_repository import verify_local_release_set

_FIXTURE_ROOT_SEED = hashlib.sha256(
    b"Stockroom deterministic fixture TUF root; never production"
).digest()


class ReleaseBundleError(ValueError):
    """The packaged release bundle could not be authored safely."""


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validated_base_uri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ReleaseBundleError(
            "feed base URI must be HTTPS without credentials, query, or fragment"
        )
    return value.rstrip("/")


def _validate_root(data: bytes) -> bytes:
    try:
        metadata = Metadata.from_bytes(data)
        if not isinstance(metadata.signed, Root):
            raise ReleaseBundleError("TUF bootstrap metadata is not a root role")
        metadata.signed.verify_delegate(
            Root.type,
            metadata.signed_bytes,
            metadata.signatures,
        )
    except ReleaseBundleError:
        raise
    except Exception as exc:
        raise ReleaseBundleError("TUF bootstrap root is invalid") from exc
    return data


def fixture_tuf_signer() -> CryptoSigner:
    """Return the deterministic fixture-only signer shared by release tooling."""

    private_key = Ed25519PrivateKey.from_private_bytes(_FIXTURE_ROOT_SEED)
    return CryptoSigner(private_key)


def _fixture_root() -> bytes:
    signer = fixture_tuf_signer()
    root = Root(
        version=1,
        expires=datetime(2038, 1, 1, tzinfo=timezone.utc),
        consistent_snapshot=True,
    )
    for role in ("root", "targets", "snapshot", "timestamp"):
        root.add_key(signer.public_key, role)
    metadata = Metadata(root)
    metadata.sign(signer)
    return _validate_root(metadata.to_bytes())


def _spdx_document(
    *,
    executable_name: str,
    executable_sha1: str,
    executable_sha256: str,
    release_id: str,
    source_revision: str,
    source_date_epoch: int,
) -> bytes:
    created = datetime.fromtimestamp(source_date_epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    namespace_digest = _sha256(
        f"{release_id}\0{source_revision}\0{executable_sha256}".encode("utf-8")
    )
    verification_code = hashlib.sha1(  # noqa: S324 - required by SPDX 2.3
        executable_sha1.encode("ascii"),
        usedforsecurity=False,
    ).hexdigest()
    return _canonical_bytes(
        {
            "SPDXID": "SPDXRef-DOCUMENT",
            "creationInfo": {
                "created": created,
                "creators": ["Tool: Stockroom Windows Packager"],
            },
            "dataLicense": "CC0-1.0",
            "documentNamespace": (
                "https://stockroom.local/spdx/" + namespace_digest
            ),
            "files": [
                {
                    "SPDXID": "SPDXRef-ManagedHost",
                    "checksums": [
                        {
                            "algorithm": "SHA1",
                            "checksumValue": executable_sha1,
                        },
                        {
                            "algorithm": "SHA256",
                            "checksumValue": executable_sha256,
                        }
                    ],
                    "copyrightText": "NOASSERTION",
                    "fileName": f"./Backend/{executable_name}",
                }
            ],
            "name": f"Stockroom {release_id}",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-Stockroom",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": True,
                    "name": "Stockroom",
                    "packageVerificationCode": {
                        "packageVerificationCodeValue": verification_code
                    },
                    "versionInfo": release_id.removeprefix("release-"),
                }
            ],
            "relationships": [
                {
                    "relatedSpdxElement": "SPDXRef-Package-Stockroom",
                    "relationshipType": "DESCRIBES",
                    "spdxElementId": "SPDXRef-DOCUMENT",
                },
                {
                    "relatedSpdxElement": "SPDXRef-ManagedHost",
                    "relationshipType": "CONTAINS",
                    "spdxElementId": "SPDXRef-Package-Stockroom",
                },
            ],
            "spdxVersion": "SPDX-2.3",
        }
    )


def build_release_bundle(
    *,
    mode: str,
    executable: Path,
    bundle_root: Path,
    version: str,
    feed_base_uri: str,
    source_revision: str,
    source_date_epoch: int,
    tuf_root_path: Path | None,
    rollback_release_id: str | None = None,
    compatible_from_release_ids: Sequence[str] | None = None,
    protocol_version: int = 1,
) -> dict[str, str]:
    normalized_mode = mode.casefold()
    if normalized_mode not in {"fixture", "production"}:
        raise ReleaseBundleError("mode must be Fixture or Production")
    executable = Path(executable).resolve(strict=True)
    if executable.suffix.casefold() != ".exe":
        raise ReleaseBundleError("managed host must be a Windows executable")
    if source_date_epoch < 315532800 or source_date_epoch > 2147483647:
        raise ReleaseBundleError("source date epoch is outside the reproducible range")
    if type(protocol_version) is not int or protocol_version <= 0:
        raise ReleaseBundleError("protocol version must be a positive integer")
    feed = _validated_base_uri(feed_base_uri)
    release_id = f"release-{version}"
    bundle_root = Path(bundle_root).resolve()
    bundle_root.mkdir(parents=True, exist_ok=True)
    if any(bundle_root.iterdir()):
        raise ReleaseBundleError("bundle root must be empty")

    if normalized_mode == "production":
        if tuf_root_path is None:
            raise ReleaseBundleError(
                "production requires an offline-authored pinned TUF root"
            )
        root_bytes = _validate_root(Path(tuf_root_path).resolve(strict=True).read_bytes())
    else:
        if tuf_root_path is not None:
            raise ReleaseBundleError("fixture mode refuses a production TUF root")
        root_bytes = _fixture_root()
    if rollback_release_id is None:
        if normalized_mode == "production":
            raise ReleaseBundleError(
                "production requires an explicit rollback release"
            )
        rollback_release_id = "release-bootstrap"
    compatible_predecessors = (
        tuple(compatible_from_release_ids)
        if compatible_from_release_ids is not None
        else (() if normalized_mode == "production" else ("release-bootstrap",))
    )
    if not compatible_predecessors:
        raise ReleaseBundleError(
            "production requires explicit compatible predecessors"
        )

    release_root = bundle_root / "Initial Release" / release_id
    backend_name = "Stockroom Worker.exe"
    backend_path = release_root / "Backend" / backend_name
    backend_path.parent.mkdir(parents=True)
    shutil.copyfile(executable, backend_path)
    backend_bytes = backend_path.read_bytes()
    backend_sha1 = hashlib.sha1(  # noqa: S324 - required by SPDX 2.3
        backend_bytes,
        usedforsecurity=False,
    ).hexdigest()
    backend_sha256 = _sha256(backend_bytes)

    sbom_bytes = _spdx_document(
        executable_name=backend_name,
        executable_sha1=backend_sha1,
        executable_sha256=backend_sha256,
        release_id=release_id,
        source_revision=source_revision,
        source_date_epoch=source_date_epoch,
    )
    sbom_path = release_root / "Support" / "SBOM.spdx.json"
    sbom_path.parent.mkdir(parents=True)
    sbom_path.write_bytes(sbom_bytes)
    members = [
        {
            "kind": "backend",
            "path": f"Backend/{backend_name}",
            "sha256": backend_sha256,
            "size": len(backend_bytes),
        },
        {
            "kind": "sbom",
            "path": "Support/SBOM.spdx.json",
            "sha256": _sha256(sbom_bytes),
            "size": len(sbom_bytes),
        },
    ]
    manifest_document = {
        "api_compatibility": {
            "maximum": protocol_version,
            "minimum": protocol_version,
        },
        "compatible_from_release_ids": list(compatible_predecessors),
        "manifest_version": 2,
        "members": members,
        "migration": {
            "catalog": {"from": 1, "to": 1},
            "control": {"from": 1, "to": 1},
        },
        "minimum_host_version": version,
        "package_version": version,
        "protocol_version": protocol_version,
        "release_id": release_id,
        "required_eda_bridge_version": "1",
        "required_odbc_driver_version": "1",
        "rollback_release_id": rollback_release_id,
        "sbom_sha256": _sha256(sbom_bytes),
        "schema_compatibility": {
            "catalog": {"maximum": 1, "minimum": 1},
            "control": {"maximum": 1, "minimum": 1},
        },
        "workflow_code_versions": {"component-completion": 1},
    }
    manifest_bytes = _canonical_bytes(manifest_document)
    ReleaseManifest.from_bytes(manifest_bytes)
    manifest_path = release_root / "Release Manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha256 = _sha256(manifest_bytes)

    (bundle_root / "Root.json").write_bytes(root_bytes)
    (bundle_root / "Update Feed.json").write_bytes(
        _canonical_bytes(
            {
                "current_manifest_sha256": manifest_sha256,
                "current_release_id": release_id,
                "metadata_base_url": f"{feed}/metadata/",
                "schema_version": 1,
                "target_base_url": f"{feed}/targets/",
            }
        )
    )
    verify_local_release_set(
        release_root,
        expected_release_id=release_id,
        expected_manifest_sha256=manifest_sha256,
    )
    return {
        "backend_sha256": backend_sha256,
        "compatible_from_release_ids": ",".join(compatible_predecessors),
        "manifest_sha256": manifest_sha256,
        "release_id": release_id,
        "rollback_release_id": rollback_release_id,
        "root_sha256": _sha256(root_bytes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("Fixture", "Production"))
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--feed-base-uri", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-date-epoch", required=True, type=int)
    parser.add_argument("--protocol-version", default=1, type=int)
    parser.add_argument("--tuf-root-path", type=Path)
    parser.add_argument(
        "--rollback-release-id",
    )
    parser.add_argument(
        "--compatible-from-release-id",
        action="append",
        dest="compatible_from_release_ids",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_release_bundle(
        mode=args.mode,
        executable=args.executable,
        bundle_root=args.bundle_root,
        version=args.version,
        feed_base_uri=args.feed_base_uri,
        source_revision=args.source_revision,
        source_date_epoch=args.source_date_epoch,
        tuf_root_path=args.tuf_root_path,
        rollback_release_id=args.rollback_release_id,
        compatible_from_release_ids=args.compatible_from_release_ids,
        protocol_version=args.protocol_version,
    )
    payload = _canonical_bytes(result)
    if args.output is not None:
        args.output.write_bytes(payload)
    else:
        print(payload.decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
