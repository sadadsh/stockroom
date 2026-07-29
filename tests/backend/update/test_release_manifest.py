from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from stockroom.update.manifest import ReleaseManifest, ReleaseManifestError


def _document() -> dict[str, Any]:
    backend = b"backend"
    sbom = b'{"spdxVersion":"SPDX-2.3"}'
    return {
        "api_compatibility": {"maximum": 4, "minimum": 3},
        "manifest_version": 1,
        "members": [
            {
                "kind": "backend",
                "path": "Backend/Stockroom.pyz",
                "sha256": hashlib.sha256(backend).hexdigest(),
                "size": len(backend),
            },
            {
                "kind": "sbom",
                "path": "Support/SBOM.spdx.json",
                "sha256": hashlib.sha256(sbom).hexdigest(),
                "size": len(sbom),
            },
        ],
        "migration": {
            "catalog": {"from": 5, "to": 6},
            "control": {"from": 2, "to": 3},
        },
        "minimum_host_version": "2.0.0",
        "package_version": "4.0.0",
        "protocol_version": 3,
        "release_id": "2026.07.29.1",
        "required_eda_bridge_version": "3.1.0",
        "required_odbc_driver_version": "18.5.1.1",
        "rollback_release_id": "2026.07.28.2",
        "sbom_sha256": hashlib.sha256(sbom).hexdigest(),
        "schema_compatibility": {
            "catalog": {"maximum": 7, "minimum": 6},
            "control": {"maximum": 4, "minimum": 3},
        },
        "workflow_code_versions": {"library-publication": 8},
    }


def _bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def test_manifest_is_strictly_parsed_and_deeply_immutable() -> None:
    manifest = ReleaseManifest.from_bytes(_bytes(_document()))

    assert manifest.manifest_version == 1
    assert manifest.schema_compatibility.catalog.minimum == 6
    assert manifest.migration.control.target == 3
    assert (
        manifest.target_path_for(manifest.members[0])
        == "Releases/2026.07.29.1/Backend/Stockroom.pyz"
    )
    with pytest.raises(TypeError):
        manifest.workflow_code_versions["injected"] = 99  # ty: ignore[invalid-assignment]


def test_v2_manifest_explicitly_allows_a_verified_skipped_predecessor() -> None:
    document = _document()
    document["manifest_version"] = 2
    document["compatible_from_release_ids"] = [
        document["rollback_release_id"],
        "2026.07.20.4",
    ]

    manifest = ReleaseManifest.from_bytes(_bytes(document))

    assert manifest.manifest_version == 2
    assert manifest.compatible_from_release_ids == (
        "2026.07.28.2",
        "2026.07.20.4",
    )
    assert manifest.supports_direct_activation_from("2026.07.20.4")
    assert not manifest.supports_direct_activation_from("2026.07.19.9")


def test_v1_manifest_remains_exact_predecessor_only() -> None:
    manifest = ReleaseManifest.from_bytes(_bytes(_document()))

    assert manifest.compatible_from_release_ids == ("2026.07.28.2",)
    assert manifest.supports_direct_activation_from("2026.07.28.2")
    assert not manifest.supports_direct_activation_from("2026.07.20.4")


@pytest.mark.parametrize(
    "compatible",
    [
        [],
        ["2026.07.20.4"],
        ["2026.07.28.2", "2026.07.28.2"],
        ["2026.07.28.2", "2026.07.29.1"],
    ],
)
def test_v2_manifest_rejects_ambiguous_compatibility_relations(
    compatible: list[str],
) -> None:
    document = _document()
    document["manifest_version"] = 2
    document["compatible_from_release_ids"] = compatible

    with pytest.raises(ReleaseManifestError, match="compatible_from_release_ids"):
        ReleaseManifest.from_bytes(_bytes(document))


def test_manifest_rejects_duplicate_and_unknown_json_fields() -> None:
    valid = _bytes(_document()).decode()
    duplicate = valid.replace('"manifest_version":1', '"manifest_version":1,"manifest_version":1')

    with pytest.raises(ReleaseManifestError, match="Duplicate JSON key"):
        ReleaseManifest.from_bytes(duplicate.encode())

    document = _document()
    document["signing_key"] = "must-not-be-accepted"
    with pytest.raises(ReleaseManifestError, match="unknown"):
        ReleaseManifest.from_bytes(_bytes(document))


@pytest.mark.parametrize(
    "path",
    [
        "../outside.exe",
        "Backend\\Stockroom.pyz",
        "C:/Windows/System32/payload.dll",
        "Support/NUL.txt",
        "Support/trailing.",
    ],
)
def test_manifest_rejects_unsafe_windows_member_paths(path: str) -> None:
    document = _document()
    document["members"][0]["path"] = path

    with pytest.raises(ReleaseManifestError, match="path"):
        ReleaseManifest.from_bytes(_bytes(document))


def test_manifest_rejects_case_colliding_member_paths() -> None:
    document = _document()
    duplicate = deepcopy(document["members"][0])
    duplicate["path"] = "backend/stockroom.pyz"
    document["members"].append(duplicate)

    with pytest.raises(ReleaseManifestError, match="case-insensitive duplicate"):
        ReleaseManifest.from_bytes(_bytes(document))


@pytest.mark.parametrize("inconsistency", ["migration", "rollback", "sbom"])
def test_manifest_rejects_incoherent_release_metadata(inconsistency: str) -> None:
    document = _document()
    if inconsistency == "migration":
        document["migration"]["catalog"]["to"] = 99
    elif inconsistency == "rollback":
        document["rollback_release_id"] = document["release_id"]
    else:
        document["sbom_sha256"] = "0" * 64

    with pytest.raises(ReleaseManifestError):
        ReleaseManifest.from_bytes(_bytes(document))
