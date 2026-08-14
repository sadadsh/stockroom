"""Author and verify the immutable release bundle embedded in the Windows package.

Production receives its offline-authored TUF root as an explicit build input.
Fixture builds use one public, deterministic development-only root so the full
managed host can be exercised without inventing production trust.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
_HOST_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CAD_THIRD_PARTY_NOTICE = Path(__file__).with_name("Third Party Notices.txt")
_ALTIUMSHARP_LICENSE = _REPOSITORY_ROOT / "vendor" / "AltiumSharp" / "LICENSE"


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


def _validated_host_version(value: str, *, package_version: str) -> str:
    if not isinstance(value, str) or _HOST_VERSION_PATTERN.fullmatch(value) is None:
        raise ReleaseBundleError(
            "minimum host version must be a canonical four-part numeric version"
        )
    if (
        not isinstance(package_version, str)
        or _HOST_VERSION_PATTERN.fullmatch(package_version) is None
    ):
        raise ReleaseBundleError("package version must be a canonical four-part numeric version")
    host_floor = tuple(int(part) for part in value.split("."))
    packaged_host = tuple(int(part) for part in package_version.split("."))
    if host_floor > packaged_host:
        raise ReleaseBundleError(
            "minimum host version cannot exceed the packaged host version"
        )
    return value


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
    cad_converter_files: Sequence[tuple[str, str, str]],
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
                },
                *[
                    {
                        "SPDXID": f"SPDXRef-CadConverter-{index}",
                        "checksums": [
                            {"algorithm": "SHA1", "checksumValue": sha1},
                            {"algorithm": "SHA256", "checksumValue": sha256},
                        ],
                        "copyrightText": "NOASSERTION",
                        "fileName": f"./Tools/CadConverter/{name}",
                    }
                    for index, (name, sha1, sha256) in enumerate(
                        cad_converter_files,
                        start=1,
                    )
                ],
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
                },
                {
                    "SPDXID": "SPDXRef-Package-AltiumSharp",
                    "downloadLocation": "https://github.com/issus/AltiumSharp",
                    "licenseConcluded": "Apache-2.0",
                    "licenseDeclared": "Apache-2.0",
                    "name": "AltiumSharp",
                    "versionInfo": "ce72437f30cd54f549601d4e0ca5846d21272150",
                },
                {
                    "SPDXID": "SPDXRef-Package-EdaAbstractions",
                    "downloadLocation": (
                        "https://github.com/issus/OriginalCircuit.Eda.Abstractions"
                    ),
                    "licenseConcluded": "MIT",
                    "licenseDeclared": "MIT",
                    "name": "OriginalCircuit.Eda.Abstractions",
                    "versionInfo": "114b40b94fcde0cd68a0c6a5db4d26b7aa3fb0f3",
                },
                {
                    "SPDXID": "SPDXRef-Package-OpenMcdf",
                    "downloadLocation": "https://github.com/openmcdf/openmcdf",
                    "licenseConcluded": "MPL-2.0",
                    "licenseDeclared": "MPL-2.0",
                    "name": "OpenMcdf",
                    "versionInfo": "3.1.4",
                },
                {
                    "SPDXID": "SPDXRef-Package-EncodingCodePages",
                    "downloadLocation": "https://github.com/dotnet/runtime",
                    "licenseConcluded": "MIT",
                    "licenseDeclared": "MIT",
                    "name": "System.Text.Encoding.CodePages",
                    "versionInfo": "9.0.0",
                },
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
                *[
                    {
                        "relatedSpdxElement": f"SPDXRef-CadConverter-{index}",
                        "relationshipType": "CONTAINS",
                        "spdxElementId": "SPDXRef-Package-Stockroom",
                    }
                    for index in range(1, len(cad_converter_files) + 1)
                ],
                *[
                    {
                        "relatedSpdxElement": dependency,
                        "relationshipType": "DEPENDS_ON",
                        "spdxElementId": "SPDXRef-Package-Stockroom",
                    }
                    for dependency in (
                        "SPDXRef-Package-AltiumSharp",
                        "SPDXRef-Package-EdaAbstractions",
                        "SPDXRef-Package-OpenMcdf",
                        "SPDXRef-Package-EncodingCodePages",
                    )
                ],
            ],
            "spdxVersion": "SPDX-2.3",
        }
    )


def build_release_bundle(
    *,
    mode: str,
    executable: Path,
    window_host_root: Path,
    cad_converter_root: Path,
    bundle_root: Path,
    version: str,
    minimum_host_version: str,
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
    if executable.is_dir():
        worker_root = executable
        worker_executable = worker_root / "Stockroom Worker.exe"
        if not worker_executable.is_file():
            raise ReleaseBundleError("packaged worker root is missing Stockroom Worker.exe")
        worker_files = tuple(
            sorted(
                (path for path in worker_root.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(worker_root).as_posix().casefold(),
            )
        )
    elif executable.suffix.casefold() == ".exe":
        worker_root = executable.parent
        worker_executable = executable
        worker_files = (executable,)
    else:
        raise ReleaseBundleError("packaged worker must be a Windows executable or runtime tree")
    if any(path.is_symlink() for path in worker_files):
        raise ReleaseBundleError("packaged worker runtime must not contain symlinks")
    window_host_root = Path(window_host_root).resolve(strict=True)
    if not window_host_root.is_dir():
        raise ReleaseBundleError("window host publish root must be a directory")
    window_host_executable = window_host_root / "Stockroom.WindowHost.exe"
    if not window_host_executable.is_file():
        raise ReleaseBundleError(
            "window host publish root is missing Stockroom.WindowHost.exe"
        )
    window_host_sha256 = _sha256(window_host_executable.read_bytes())
    cad_converter_root = Path(cad_converter_root).resolve(strict=True)
    if not cad_converter_root.is_dir():
        raise ReleaseBundleError("CAD converter publish root must be a directory")
    cad_converter_executable = cad_converter_root / "Stockroom.CadConverter.exe"
    if not cad_converter_executable.is_file():
        raise ReleaseBundleError(
            "CAD converter publish root is missing Stockroom.CadConverter.exe"
        )
    cad_converter_files = tuple(
        sorted(
            (path for path in cad_converter_root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(cad_converter_root).as_posix().casefold(),
        )
    )
    if any(path.is_symlink() for path in cad_converter_files):
        raise ReleaseBundleError("CAD converter publish root must not contain symlinks")
    if len(cad_converter_files) < 2:
        raise ReleaseBundleError(
            "CAD converter publish root is incomplete; self-contained runtime files are required"
        )
    if not _CAD_THIRD_PARTY_NOTICE.is_file() or not _ALTIUMSHARP_LICENSE.is_file():
        raise ReleaseBundleError("native CAD converter licensing inputs are unavailable")
    if source_date_epoch < 315532800 or source_date_epoch > 2147483647:
        raise ReleaseBundleError("source date epoch is outside the reproducible range")
    if type(protocol_version) is not int or protocol_version <= 0:
        raise ReleaseBundleError("protocol version must be a positive integer")
    host_version_floor = _validated_host_version(
        minimum_host_version,
        package_version=version,
    )
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
    backend_members: list[dict[str, object]] = []
    backend_path = release_root / "Backend" / backend_name
    for source in worker_files:
        relative = (
            Path(backend_name)
            if source == worker_executable
            else source.relative_to(worker_root)
        )
        destination = release_root / "Backend" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        data = destination.read_bytes()
        canonical_path = f"Backend/{relative.as_posix()}"
        backend_members.append(
            {
                "kind": "backend" if source == worker_executable else "backend-runtime",
                "path": canonical_path,
                "sha256": _sha256(data),
                "size": len(data),
            }
        )
    backend_bytes = backend_path.read_bytes()
    backend_sha1 = hashlib.sha1(  # noqa: S324 - required by SPDX 2.3
        backend_bytes,
        usedforsecurity=False,
    ).hexdigest()
    backend_sha256 = _sha256(backend_bytes)
    cad_converter_members: list[dict[str, object]] = []
    cad_converter_spdx: list[tuple[str, str, str]] = []
    for source in cad_converter_files:
        relative = source.relative_to(cad_converter_root)
        destination = release_root / "Tools" / "CadConverter" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        data = destination.read_bytes()
        sha1 = hashlib.sha1(data, usedforsecurity=False).hexdigest()  # noqa: S324
        sha256 = _sha256(data)
        canonical_path = f"Tools/CadConverter/{relative.as_posix()}"
        cad_converter_members.append(
            {
                "kind": (
                    "cad-converter"
                    if canonical_path == "Tools/CadConverter/Stockroom.CadConverter.exe"
                    else "cad-converter-runtime"
                ),
                "path": canonical_path,
                "sha256": sha256,
                "size": len(data),
            }
        )
        cad_converter_spdx.append((relative.as_posix(), sha1, sha256))

    sbom_bytes = _spdx_document(
        executable_name=backend_name,
        executable_sha1=backend_sha1,
        executable_sha256=backend_sha256,
        cad_converter_files=cad_converter_spdx,
        release_id=release_id,
        source_revision=source_revision,
        source_date_epoch=source_date_epoch,
    )
    sbom_path = release_root / "Support" / "SBOM.spdx.json"
    sbom_path.parent.mkdir(parents=True)
    sbom_path.write_bytes(sbom_bytes)
    notice_bytes = _CAD_THIRD_PARTY_NOTICE.read_bytes()
    notice_path = release_root / "Support" / "Third Party Notices.txt"
    notice_path.write_bytes(notice_bytes)
    license_bytes = _ALTIUMSHARP_LICENSE.read_bytes()
    license_path = release_root / "Support" / "Licenses" / "AltiumSharp Apache-2.0.txt"
    license_path.parent.mkdir(parents=True)
    license_path.write_bytes(license_bytes)
    # MSIX/App Installer own the native WPF host. TUF release sets own only
    # rolling worker payloads, tools, and support evidence; downloading another
    # self-contained WPF runtime could not update the already-running host.
    members = [
        *cad_converter_members,
        *backend_members,
        {
            "kind": "sbom",
            "path": "Support/SBOM.spdx.json",
            "sha256": _sha256(sbom_bytes),
            "size": len(sbom_bytes),
        },
        {
            "kind": "notice",
            "path": "Support/Third Party Notices.txt",
            "sha256": _sha256(notice_bytes),
            "size": len(notice_bytes),
        },
        {
            "kind": "license",
            "path": "Support/Licenses/AltiumSharp Apache-2.0.txt",
            "sha256": _sha256(license_bytes),
            "size": len(license_bytes),
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
        "minimum_host_version": host_version_floor,
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
        "cad_converter_sha256": next(
            str(member["sha256"])
            for member in cad_converter_members
            if member["kind"] == "cad-converter"
        ),
        "compatible_from_release_ids": ",".join(compatible_predecessors),
        "manifest_sha256": manifest_sha256,
        "minimum_host_version": host_version_floor,
        "release_id": release_id,
        "rollback_release_id": rollback_release_id,
        "root_sha256": _sha256(root_bytes),
        "window_host_sha256": window_host_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("Fixture", "Production"))
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--window-host-root", required=True, type=Path)
    parser.add_argument("--cad-converter-root", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--minimum-host-version", required=True)
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
        window_host_root=args.window_host_root,
        cad_converter_root=args.cad_converter_root,
        bundle_root=args.bundle_root,
        version=args.version,
        minimum_host_version=args.minimum_host_version,
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
