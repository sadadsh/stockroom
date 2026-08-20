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
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

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
_FONT_AWESOME_LICENSE = Path(__file__).with_name("Font Awesome Free License.txt")
_GEIST_MONO_LICENSE = Path(__file__).with_name("Geist Mono License.txt")
_ALTIUMSHARP_LICENSE = _REPOSITORY_ROOT / "vendor" / "AltiumSharp" / "LICENSE"
_STOCKROOM_LICENSE = _REPOSITORY_ROOT / "LICENSE"
_PYTHON_LOCK = _REPOSITORY_ROOT / "uv.lock"
_FRONTEND_LOCK = _REPOSITORY_ROOT / "app" / "frontend" / "package-lock.json"


class ReleaseBundleError(ValueError):
    """The packaged release bundle could not be authored safely."""


@dataclass(frozen=True)
class _SpdxFile:
    spdx_id: str
    file_name: str
    sha1: str
    sha256: str
    comment: str | None = None


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


def _spdx_package_id(ecosystem: str, name: str, version: str, identity: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-.") or "Dependency"
    digest = _sha256(f"{ecosystem}\0{identity}\0{version}".encode("utf-8"))[:12]
    return f"SPDXRef-Package-{ecosystem}-{readable}-{digest}"


def _windows_python312_marker_allows(marker: str | None) -> bool:
    if marker is None:
        return True
    supported = {
        "implementation_name != 'PyPy'": True,
        "platform_python_implementation != 'PyPy'": True,
        "python_full_version < '3.13'": True,
        "sys_platform == 'darwin'": False,
        "sys_platform == 'win32'": True,
    }
    try:
        return supported[marker]
    except KeyError as exc:
        raise ReleaseBundleError(
            f"uv.lock uses an unsupported Windows production marker: {marker}"
        ) from exc


def _python_dependency_evidence() -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    try:
        lock = tomllib.loads(_PYTHON_LOCK.read_text(encoding="utf-8"))
        packages = lock["package"]
        package_by_name = {package["name"]: package for package in packages}
        root = next(
            package
            for package in packages
            if package["name"] == "stockroom"
            and package.get("source") == {"editable": "."}
        )
    except (KeyError, OSError, StopIteration, tomllib.TOMLDecodeError) as exc:
        raise ReleaseBundleError("uv.lock is not a readable Stockroom production lock") from exc

    selected_extras: dict[str, set[str]] = {}
    processed_base: set[str] = set()
    pending: list[tuple[str, tuple[str, ...]]] = []
    edges: set[tuple[str, str]] = set()

    def enqueue(source: str, dependency: dict[str, object]) -> None:
        marker = dependency.get("marker")
        if marker is not None and not isinstance(marker, str):
            raise ReleaseBundleError("uv.lock dependency marker must be text")
        if not _windows_python312_marker_allows(marker):
            return
        name = dependency.get("name")
        if not isinstance(name, str) or name not in package_by_name:
            raise ReleaseBundleError("uv.lock production dependency is unresolved")
        raw_extras = dependency.get("extra", dependency.get("extras", ()))
        extras = tuple(sorted(str(extra) for extra in raw_extras))
        edges.add((source, name))
        pending.append((name, extras))

    for dependency in root.get("dependencies", []):
        enqueue("stockroom", dependency)

    while pending:
        name, extras = pending.pop(0)
        known_extras = selected_extras.setdefault(name, set())
        new_extras = set(extras) - known_extras
        package = package_by_name[name]
        if name not in processed_base:
            for dependency in package.get("dependencies", []):
                enqueue(name, dependency)
            processed_base.add(name)
        for extra in sorted(new_extras):
            optional = package.get("optional-dependencies", {}).get(extra)
            if optional is None:
                raise ReleaseBundleError(
                    f"uv.lock does not resolve requested extra {name}[{extra}]"
                )
            for dependency in optional:
                enqueue(name, dependency)
        known_extras.update(new_extras)

    selected_names = {target for _, target in edges}
    id_by_name = {
        name: _spdx_package_id(
            "Python",
            name,
            str(package_by_name[name]["version"]),
            name,
        )
        for name in sorted(selected_names)
    }
    result_packages: list[dict[str, object]] = []
    for name in sorted(selected_names):
        package = package_by_name[name]
        version = str(package["version"])
        sdist = package.get("sdist", {})
        download = sdist.get("url", "NOASSERTION")
        result_packages.append(
            {
                "SPDXID": id_by_name[name],
                "copyrightText": "NOASSERTION",
                "downloadLocation": download,
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceLocator": f"pkg:pypi/{quote(name, safe='')}@{version}",
                        "referenceType": "purl",
                    }
                ],
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "name": name,
                "primaryPackagePurpose": "LIBRARY",
                "comment": "Locked Windows Python 3.12 production dependency from uv.lock.",
                "versionInfo": version,
            }
        )
    relationships = [
        {
            "relatedSpdxElement": id_by_name[target],
            "relationshipType": "DEPENDS_ON",
            "spdxElementId": (
                "SPDXRef-Package-Stockroom" if source == "stockroom" else id_by_name[source]
            ),
        }
        for source, target in sorted(edges)
        if target in id_by_name and (source == "stockroom" or source in id_by_name)
    ]
    return result_packages, relationships


def _npm_name(package_path: str) -> str:
    return package_path.rsplit("node_modules/", maxsplit=1)[-1]


def _npm_purl_name(name: str) -> str:
    if name.startswith("@") and "/" in name:
        namespace, package_name = name.split("/", maxsplit=1)
        return f"{quote(namespace, safe='')}/{quote(package_name, safe='')}"
    return quote(name, safe="")


def _resolve_npm_dependency(
    source_path: str,
    name: str,
    selected_paths: set[str],
) -> str | None:
    prefixes = [source_path]
    while "/node_modules/" in prefixes[-1]:
        prefixes.append(prefixes[-1].rsplit("/node_modules/", maxsplit=1)[0])
    prefixes.append("")
    for prefix in prefixes:
        candidate = f"{prefix}/node_modules/{name}".lstrip("/")
        if candidate in selected_paths:
            return candidate
    return None


def _npm_constraint_allows(
    values: object,
    *,
    target: str,
    field: str,
) -> bool:
    if values is None:
        return True
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ReleaseBundleError(f"frontend lock {field} constraint must be a string list")
    positive: set[str] = set()
    negative: set[str] = set()
    for raw_value in values:
        value = raw_value.casefold()
        denied = value.startswith("!")
        name = value[1:] if denied else value
        if not name:
            raise ReleaseBundleError(f"frontend lock {field} constraint is empty")
        (negative if denied else positive).add(name)
    if target in negative or "any" in negative:
        return False
    return not positive or target in positive or "any" in positive


def _npm_targets_win32_x64(package: dict[str, object]) -> bool:
    return _npm_constraint_allows(
        package.get("os"),
        target="win32",
        field="os",
    ) and _npm_constraint_allows(
        package.get("cpu"),
        target="x64",
        field="cpu",
    )


def _npm_dependency_requirements(package: dict[str, object]) -> dict[str, bool]:
    requirements = {
        str(name): True for name in package.get("dependencies", {})
    }
    for name in package.get("optionalDependencies", {}):
        requirements[str(name)] = False
    peer_metadata = package.get("peerDependenciesMeta", {})
    if not isinstance(peer_metadata, dict):
        raise ReleaseBundleError("frontend lock peer dependency metadata must be an object")
    for name in package.get("peerDependencies", {}):
        metadata = peer_metadata.get(name, {})
        if not isinstance(metadata, dict):
            raise ReleaseBundleError("frontend lock peer dependency metadata must be an object")
        peer_required = metadata.get("optional") is not True
        requirements[str(name)] = requirements.get(str(name), False) or peer_required
    return requirements


def _frontend_dependency_evidence() -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    try:
        lock = json.loads(_FRONTEND_LOCK.read_text(encoding="utf-8"))
        root = lock["packages"][""]
        locked = lock["packages"]
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        raise ReleaseBundleError(
            "app/frontend/package-lock.json is not a readable production lock"
        ) from exc

    production = {
        path: package
        for path, package in locked.items()
        if path and package.get("dev") is not True
    }
    production_paths = set(production)
    compatible_paths = {
        path for path, package in production.items() if _npm_targets_win32_x64(package)
    }
    selected_paths: set[str] = set()
    resolved_edges: set[tuple[str, str]] = set()
    pending = [
        ("", name, required)
        for name, required in sorted(_npm_dependency_requirements(root).items())
    ]
    while pending:
        source_path, name, required = pending.pop(0)
        target = _resolve_npm_dependency(source_path, name, production_paths)
        if target is None or target not in compatible_paths:
            if required:
                source = source_path or "stockroom-frontend"
                raise ReleaseBundleError(
                    "required frontend production dependency is unavailable for "
                    f"win32/x64: {name} (from {source})"
                )
            continue
        resolved_edges.add((source_path, target))
        if target in selected_paths:
            continue
        selected_paths.add(target)
        pending.extend(
            (target, dependency_name, dependency_required)
            for dependency_name, dependency_required in sorted(
                _npm_dependency_requirements(production[target]).items()
            )
        )
    selected = {path: production[path] for path in sorted(selected_paths)}
    id_by_path = {
        path: _spdx_package_id(
            "Npm",
            _npm_name(path),
            str(package["version"]),
            path,
        )
        for path, package in sorted(selected.items())
    }
    result_packages: list[dict[str, object]] = []
    for path, package in sorted(selected.items()):
        name = _npm_name(path)
        version = str(package["version"])
        license_name = package.get("license", "NOASSERTION")
        if not isinstance(license_name, str) or license_name not in {
            "(CC-BY-4.0 AND MIT)",
            "0BSD",
            "Apache-2.0",
            "BSD-3-Clause",
            "CC0-1.0",
            "ISC",
            "MIT",
            "OFL-1.1",
        }:
            license_name = "NOASSERTION"
        result_packages.append(
            {
                "SPDXID": id_by_path[path],
                "copyrightText": "NOASSERTION",
                "downloadLocation": package.get("resolved", "NOASSERTION"),
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceLocator": f"pkg:npm/{_npm_purl_name(name)}@{version}",
                        "referenceType": "purl",
                    }
                ],
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": license_name,
                "name": name,
                "primaryPackagePurpose": "LIBRARY",
                "comment": (
                    "Locked win32/x64 production frontend dependency from "
                    "app/frontend/package-lock.json."
                ),
                "versionInfo": version,
            }
        )

    frontend_id = _spdx_package_id(
        "Npm",
        str(root["name"]),
        str(root["version"]),
        "",
    )
    frontend_package = {
        "SPDXID": frontend_id,
        "copyrightText": "NOASSERTION",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "LicenseRef-Stockroom-Proprietary",
        "licenseDeclared": "LicenseRef-Stockroom-Proprietary",
        "name": str(root["name"]),
        "primaryPackagePurpose": "APPLICATION",
        "comment": "Built frontend application described by app/frontend/package-lock.json.",
        "versionInfo": str(root["version"]),
    }
    relationships: list[dict[str, str]] = [
        {
            "relatedSpdxElement": frontend_id,
            "relationshipType": "DEPENDS_ON",
            "spdxElementId": "SPDXRef-Package-Stockroom",
        }
    ]
    relationships.extend(
        {
            "relatedSpdxElement": id_by_path[target],
            "relationshipType": "DEPENDS_ON",
            "spdxElementId": frontend_id if source == "" else id_by_path[source],
        }
        for source, target in sorted(resolved_edges)
    )
    return [frontend_package, *result_packages], relationships


def _spdx_verification_code(files: Sequence[_SpdxFile]) -> str:
    concatenated = "".join(sorted(file.sha1 for file in files)).encode("ascii")
    return hashlib.sha1(  # noqa: S324 - SPDX 2.3 package verification algorithm
        concatenated,
        usedforsecurity=False,
    ).hexdigest()


def _spdx_document(
    *,
    runtime_files: Sequence[_SpdxFile],
    release_id: str,
    source_revision: str,
    source_date_epoch: int,
    stockroom_license: str,
) -> bytes:
    created = datetime.fromtimestamp(source_date_epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    namespace_digest = _sha256(
        (
            f"{release_id}\0{source_revision}\0"
            + "".join(file.sha256 for file in runtime_files)
        ).encode("utf-8")
    )
    python_packages, python_relationships = _python_dependency_evidence()
    frontend_packages, frontend_relationships = _frontend_dependency_evidence()
    file_documents: list[dict[str, object]] = []
    for file in runtime_files:
        document: dict[str, object] = {
            "SPDXID": file.spdx_id,
            "checksums": [
                {"algorithm": "SHA1", "checksumValue": file.sha1},
                {"algorithm": "SHA256", "checksumValue": file.sha256},
            ],
            "copyrightText": "NOASSERTION",
            "fileName": file.file_name,
            "licenseConcluded": "NOASSERTION",
            "licenseInfoInFiles": ["NOASSERTION"],
        }
        if file.comment is not None:
            document["comment"] = file.comment
        file_documents.append(document)

    native_packages: list[dict[str, object]] = [
        {
            "SPDXID": "SPDXRef-Package-AltiumSharp",
            "copyrightText": "Copyright Original Circuit contributors",
            "downloadLocation": "https://github.com/issus/AltiumSharp",
            "filesAnalyzed": False,
            "licenseConcluded": "Apache-2.0",
            "licenseDeclared": "Apache-2.0",
            "name": "AltiumSharp",
            "versionInfo": "ce72437f30cd54f549601d4e0ca5846d21272150",
        },
        {
            "SPDXID": "SPDXRef-Package-EdaAbstractions",
            "copyrightText": "Copyright Original Circuit contributors",
            "downloadLocation": "https://github.com/issus/OriginalCircuit.Eda.Abstractions",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "name": "OriginalCircuit.Eda.Abstractions",
            "versionInfo": "114b40b94fcde0cd68a0c6a5db4d26b7aa3fb0f3",
        },
        {
            "SPDXID": "SPDXRef-Package-OpenMcdf",
            "copyrightText": "Copyright OpenMcdf contributors",
            "downloadLocation": "https://github.com/openmcdf/openmcdf",
            "filesAnalyzed": False,
            "licenseConcluded": "MPL-2.0",
            "licenseDeclared": "MPL-2.0",
            "name": "OpenMcdf",
            "versionInfo": "3.1.4",
        },
        {
            "SPDXID": "SPDXRef-Package-EncodingCodePages",
            "copyrightText": "Copyright .NET Foundation and contributors",
            "downloadLocation": "https://github.com/dotnet/runtime",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "name": "System.Text.Encoding.CodePages",
            "versionInfo": "9.0.0",
        },
        {
            "SPDXID": "SPDXRef-Package-GitHubCli",
            "copyrightText": "Copyright GitHub, Inc. and contributors",
            "downloadLocation": "https://github.com/cli/cli",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "name": "GitHub CLI",
            "versionInfo": "2.95.0",
        },
    ]
    stockroom_package = {
        "SPDXID": "SPDXRef-Package-Stockroom",
        "comment": (
            "The WindowHost file records describe the native WPF payload owned by MSIX/App "
            "Installer. WindowHost files are intentionally not TUF release-set members."
        ),
        "copyrightText": "Copyright Stockroom copyright holders",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": True,
        "hasFiles": [file.spdx_id for file in runtime_files],
        "licenseConcluded": "LicenseRef-Stockroom-Proprietary",
        "licenseDeclared": "LicenseRef-Stockroom-Proprietary",
        "name": "Stockroom",
        "packageVerificationCode": {
            "packageVerificationCodeValue": _spdx_verification_code(runtime_files),
            # The SPDX document is itself a release member. SPDX 2.3 explicitly permits that
            # circular document to be excluded; every other manifest member is analyzed below.
            "packageVerificationCodeExcludedFiles": ["./Support/SBOM.spdx.json"],
        },
        "primaryPackagePurpose": "APPLICATION",
        "versionInfo": release_id.removeprefix("release-"),
    }
    relationships: list[dict[str, str]] = [
        {
            "relatedSpdxElement": "SPDXRef-Package-Stockroom",
            "relationshipType": "DESCRIBES",
            "spdxElementId": "SPDXRef-DOCUMENT",
        },
        *[
            {
                "relatedSpdxElement": file.spdx_id,
                "relationshipType": "CONTAINS",
                "spdxElementId": "SPDXRef-Package-Stockroom",
            }
            for file in runtime_files
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
                "SPDXRef-Package-GitHubCli",
            )
        ],
        *python_relationships,
        *frontend_relationships,
    ]
    relationships = [
        dict(zip(("relatedSpdxElement", "relationshipType", "spdxElementId"), item))
        for item in sorted(
            {
                (
                    relationship["relatedSpdxElement"],
                    relationship["relationshipType"],
                    relationship["spdxElementId"],
                )
                for relationship in relationships
            }
        )
    ]
    return _canonical_bytes(
        {
            "SPDXID": "SPDXRef-DOCUMENT",
            "creationInfo": {
                "created": created,
                "creators": ["Tool: Stockroom Windows Packager"],
            },
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://stockroom.local/spdx/" + namespace_digest,
            "extractedLicensingInfo": [
                {
                    "extractedText": stockroom_license,
                    "licenseId": "LicenseRef-Stockroom-Proprietary",
                    "name": "Stockroom Proprietary License Notice",
                }
            ],
            "files": file_documents,
            "name": f"Stockroom {release_id}",
            "packages": [
                stockroom_package,
                *native_packages,
                *python_packages,
                *frontend_packages,
            ],
            "relationships": relationships,
            "spdxVersion": "SPDX-2.3",
        }
    )


def build_release_bundle(
    *,
    mode: str,
    executable: Path,
    window_host_root: Path,
    cad_converter_root: Path,
    github_cli_root: Path,
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
                key=lambda path: (
                    path.relative_to(worker_root).as_posix().casefold(),
                    path.relative_to(worker_root).as_posix(),
                ),
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
    window_host_files = tuple(
        sorted(
            (path for path in window_host_root.rglob("*") if path.is_file()),
            key=lambda path: (
                path.relative_to(window_host_root).as_posix().casefold(),
                path.relative_to(window_host_root).as_posix(),
            ),
        )
    )
    if any(path.is_symlink() for path in window_host_files):
        raise ReleaseBundleError("window host publish root must not contain symlinks")
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
            key=lambda path: (
                path.relative_to(cad_converter_root).as_posix().casefold(),
                path.relative_to(cad_converter_root).as_posix(),
            ),
        )
    )
    if any(path.is_symlink() for path in cad_converter_files):
        raise ReleaseBundleError("CAD converter publish root must not contain symlinks")
    if len(cad_converter_files) < 2:
        raise ReleaseBundleError(
            "CAD converter publish root is incomplete; self-contained runtime files are required"
        )
    if (
        not _CAD_THIRD_PARTY_NOTICE.is_file()
        or not _FONT_AWESOME_LICENSE.is_file()
        or not _GEIST_MONO_LICENSE.is_file()
        or not _ALTIUMSHARP_LICENSE.is_file()
        or not _STOCKROOM_LICENSE.is_file()
    ):
        raise ReleaseBundleError("release licensing inputs are unavailable")
    github_cli_root = Path(github_cli_root).resolve(strict=True)
    github_cli_executable = github_cli_root / "bin" / "gh.exe"
    github_cli_license = github_cli_root / "LICENSE"
    if not github_cli_executable.is_file() or not github_cli_license.is_file():
        raise ReleaseBundleError("pinned GitHub CLI payload is incomplete")
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
    worker_spdx: list[_SpdxFile] = []
    backend_path = release_root / "Backend" / backend_name
    for index, source in enumerate(worker_files, start=1):
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
        sha1 = hashlib.sha1(data, usedforsecurity=False).hexdigest()  # noqa: S324
        sha256 = _sha256(data)
        backend_members.append(
            {
                "kind": "backend" if source == worker_executable else "backend-runtime",
                "path": canonical_path,
                "sha256": sha256,
                "size": len(data),
            }
        )
        worker_spdx.append(
            _SpdxFile(
                spdx_id=f"SPDXRef-Worker-{index}",
                file_name=f"./{canonical_path}",
                sha1=sha1,
                sha256=sha256,
            )
        )
    backend_bytes = backend_path.read_bytes()
    backend_sha256 = _sha256(backend_bytes)
    window_host_spdx: list[_SpdxFile] = []
    for index, source in enumerate(window_host_files, start=1):
        relative = source.relative_to(window_host_root).as_posix()
        data = source.read_bytes()
        window_host_spdx.append(
            _SpdxFile(
                spdx_id=f"SPDXRef-WindowHost-{index}",
                file_name=f"./WindowHost/{relative}",
                sha1=hashlib.sha1(data, usedforsecurity=False).hexdigest(),  # noqa: S324
                sha256=_sha256(data),
                comment=(
                    "MSIX-owned WPF host file; described by this SPDX document but not a "
                    "TUF release-set member."
                ),
            )
        )
    cad_converter_members: list[dict[str, object]] = []
    cad_converter_spdx: list[_SpdxFile] = []
    for index, source in enumerate(cad_converter_files, start=1):
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
        cad_converter_spdx.append(
            _SpdxFile(
                spdx_id=f"SPDXRef-CadConverter-{index}",
                file_name=f"./Tools/CadConverter/{relative.as_posix()}",
                sha1=sha1,
                sha256=sha256,
            )
        )

    github_cli_bytes = github_cli_executable.read_bytes()
    github_cli_sha1 = hashlib.sha1(  # noqa: S324 - required by SPDX 2.3
        github_cli_bytes,
        usedforsecurity=False,
    ).hexdigest()
    github_cli_sha256 = _sha256(github_cli_bytes)
    github_cli_path = release_root / "Tools" / "gh.exe"
    github_cli_path.parent.mkdir(parents=True, exist_ok=True)
    github_cli_path.write_bytes(github_cli_bytes)
    github_cli_member = {
        "kind": "github-cli",
        "path": "Tools/gh.exe",
        "sha256": github_cli_sha256,
        "size": len(github_cli_bytes),
    }

    github_cli_spdx = _SpdxFile(
        spdx_id="SPDXRef-GitHubCli",
        file_name="./Tools/gh.exe",
        sha1=github_cli_sha1,
        sha256=github_cli_sha256,
    )
    stockroom_license_text = _STOCKROOM_LICENSE.read_text(encoding="utf-8")
    notice_bytes = _CAD_THIRD_PARTY_NOTICE.read_bytes()
    license_bytes = _ALTIUMSHARP_LICENSE.read_bytes()
    font_awesome_license_bytes = _FONT_AWESOME_LICENSE.read_bytes()
    geist_mono_license_bytes = _GEIST_MONO_LICENSE.read_bytes()
    github_cli_license_bytes = github_cli_license.read_bytes()
    stockroom_license_bytes = stockroom_license_text.encode("utf-8")

    support_sources = (
        ("Notice", "Support/Third Party Notices.txt", notice_bytes),
        (
            "AltiumSharp-License",
            "Support/Licenses/AltiumSharp Apache-2.0.txt",
            license_bytes,
        ),
        ("Apache-License", "Support/Licenses/Apache-2.0.txt", license_bytes),
        (
            "Font-Awesome-License",
            "Support/Licenses/Font Awesome Free License.txt",
            font_awesome_license_bytes,
        ),
        (
            "Geist-Mono-License",
            "Support/Licenses/Geist Mono OFL-1.1.txt",
            geist_mono_license_bytes,
        ),
        ("GitHub-Cli-License", "Support/Licenses/GitHub CLI MIT.txt", github_cli_license_bytes),
        (
            "Stockroom-License",
            "Support/Licenses/Stockroom Proprietary.txt",
            stockroom_license_bytes,
        ),
    )
    support_spdx = tuple(
        _SpdxFile(
            spdx_id=f"SPDXRef-Support-{identifier}",
            file_name=f"./{relative}",
            sha1=hashlib.sha1(data, usedforsecurity=False).hexdigest(),  # noqa: S324
            sha256=_sha256(data),
        )
        for identifier, relative, data in support_sources
    )
    sbom_bytes = _spdx_document(
        runtime_files=(
            *worker_spdx,
            *window_host_spdx,
            *cad_converter_spdx,
            github_cli_spdx,
            *support_spdx,
        ),
        release_id=release_id,
        source_revision=source_revision,
        source_date_epoch=source_date_epoch,
        stockroom_license=stockroom_license_text,
    )
    sbom_path = release_root / "Support" / "SBOM.spdx.json"
    sbom_path.parent.mkdir(parents=True)
    sbom_path.write_bytes(sbom_bytes)
    notice_path = release_root / "Support" / "Third Party Notices.txt"
    notice_path.write_bytes(notice_bytes)
    license_path = release_root / "Support" / "Licenses" / "AltiumSharp Apache-2.0.txt"
    license_path.parent.mkdir(parents=True)
    license_path.write_bytes(license_bytes)
    apache_license_path = release_root / "Support" / "Licenses" / "Apache-2.0.txt"
    apache_license_path.write_bytes(license_bytes)
    font_awesome_license_path = (
        release_root / "Support" / "Licenses" / "Font Awesome Free License.txt"
    )
    font_awesome_license_path.write_bytes(font_awesome_license_bytes)
    geist_mono_license_path = (
        release_root / "Support" / "Licenses" / "Geist Mono OFL-1.1.txt"
    )
    geist_mono_license_path.write_bytes(geist_mono_license_bytes)
    github_cli_license_path = release_root / "Support" / "Licenses" / "GitHub CLI MIT.txt"
    github_cli_license_path.write_bytes(github_cli_license_bytes)
    stockroom_license_path = (
        release_root / "Support" / "Licenses" / "Stockroom Proprietary.txt"
    )
    stockroom_license_path.write_bytes(stockroom_license_bytes)
    # MSIX/App Installer own the native WPF host. TUF release sets own only
    # rolling worker payloads, tools, and support evidence; downloading another
    # self-contained WPF runtime could not update the already-running host.
    members = [
        *cad_converter_members,
        github_cli_member,
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
        {
            "kind": "license",
            "path": "Support/Licenses/Apache-2.0.txt",
            "sha256": _sha256(license_bytes),
            "size": len(license_bytes),
        },
        {
            "kind": "license",
            "path": "Support/Licenses/Font Awesome Free License.txt",
            "sha256": _sha256(font_awesome_license_bytes),
            "size": len(font_awesome_license_bytes),
        },
        {
            "kind": "license",
            "path": "Support/Licenses/Geist Mono OFL-1.1.txt",
            "sha256": _sha256(geist_mono_license_bytes),
            "size": len(geist_mono_license_bytes),
        },
        {
            "kind": "license",
            "path": "Support/Licenses/GitHub CLI MIT.txt",
            "sha256": _sha256(github_cli_license_bytes),
            "size": len(github_cli_license_bytes),
        },
        {
            "kind": "license",
            "path": "Support/Licenses/Stockroom Proprietary.txt",
            "sha256": _sha256(stockroom_license_bytes),
            "size": len(stockroom_license_bytes),
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
        "github_cli_sha256": github_cli_sha256,
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
    parser.add_argument("--github-cli-root", required=True, type=Path)
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
        github_cli_root=args.github_cli_root,
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
