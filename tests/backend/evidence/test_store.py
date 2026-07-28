from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockroom.evidence import (
    EvidenceArtifact,
    EvidenceCorruption,
    EvidenceError,
    EvidenceManifestMismatch,
    EvidenceStore,
)
from stockroom.planning import KICAD_CAD_OPERATION, METADATA_OPERATION, ExactPartIdentity

_IDENTITY = ExactPartIdentity("ON Semiconductor", "S1M")


def _record(store: EvidenceStore, payload: object) -> str:
    return store.record_provider_success(
        identity=_IDENTITY,
        operation=METADATA_OPERATION,
        provider_key="mouser",
        adapter_version="1.0.0",
        payload=payload,
        media_type="application/json",
    )


def test_provider_evidence_is_content_addressed_idempotent_and_verifiable(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    payload = {
        "SearchResults": {
            "Parts": [
                {
                    "Manufacturer": "ON Semiconductor",
                    "ManufacturerPartNumber": "S1M",
                }
            ]
        }
    }

    first = _record(store, payload)
    second = _record(store, payload)

    assert first == second
    manifest = store.verify_provider_success(
        first,
        identity=_IDENTITY,
        operation=METADATA_OPERATION,
        provider_key="mouser",
        adapter_version="1.0.0",
    )
    assert manifest["schema"] == "stockroom.provider-evidence/1"
    assert manifest["payload"]["media_type"] == "application/json"
    assert manifest["payload"]["bytes"] > 0
    assert store.object_bytes(first) == (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def test_provider_evidence_removes_secret_fields_and_secret_query_values(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")

    digest = _record(
        store,
        {
            "Authorization": "Bearer should-not-persist",
            "nested": {
                "apiKey": "should-not-persist",
                "url": "https://example.invalid/part?apiKey=secret&view=full",
                "safe": "kept",
            },
        },
    )

    manifest = store.verify_provider_success(
        digest,
        identity=_IDENTITY,
        operation=METADATA_OPERATION,
        provider_key="mouser",
        adapter_version="1.0.0",
    )
    payload = store.object_bytes(manifest["payload"]["digest"]).decode("utf-8")
    assert "should-not-persist" not in payload
    assert "secret" not in payload
    assert "apiKey" not in payload
    assert "view=full" in payload
    assert '"safe":"kept"' in payload


def test_manifest_is_bound_to_exact_provider_operation_identity_and_version(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    digest = _record(store, {"part": "S1M"})

    mismatches = (
        {"identity": ExactPartIdentity("ON Semiconductor", "S1M-13-F")},
        {"provider_key": "digikey"},
        {"adapter_version": "2.0.0"},
    )
    for replacement in mismatches:
        arguments = {
            "identity": _IDENTITY,
            "operation": METADATA_OPERATION,
            "provider_key": "mouser",
            "adapter_version": "1.0.0",
            **replacement,
        }
        with pytest.raises(EvidenceManifestMismatch):
            store.verify_provider_success(digest, **arguments)


def test_object_tampering_is_detected_before_a_manifest_can_be_accepted(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    digest = _record(store, {"part": "S1M"})
    path = store.object_path(digest)
    path.write_bytes(b"tampered")

    with pytest.raises(EvidenceCorruption):
        store.verify_provider_success(
            digest,
            identity=_IDENTITY,
            operation=METADATA_OPERATION,
            provider_key="mouser",
            adapter_version="1.0.0",
        )


def test_evidence_root_must_be_absolute_and_nonlinked(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        EvidenceStore(Path("relative"))

    target = tmp_path / "Target"
    target.mkdir()
    link = tmp_path / "Link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ValueError):
        EvidenceStore(link)


def _cad_artifacts() -> tuple[EvidenceArtifact, ...]:
    return (
        EvidenceArtifact(
            "symbol",
            b"(kicad_symbol_lib (version 20231120))",
            "application/vnd.kicad.symbol-library",
            "S1M.kicad_sym",
        ),
        EvidenceArtifact(
            "footprint",
            b'(footprint "D_SMA")',
            "application/vnd.kicad.footprint",
            "S1M.kicad_mod",
        ),
        EvidenceArtifact(
            "model",
            b"ISO-10303-21;\nEND-ISO-10303-21;\n",
            "model/step",
            "S1M.step",
        ),
        EvidenceArtifact(
            "validation_report",
            (
                b'{"identity":{"authoritative_manufacturer_key":"ON Semiconductor",'
                b'"mpn_canonical":"S1M"},"operation":"cad:kicad",'
                b'"provider":"snapmagic","schema":"stockroom.cad-validation/1","valid":true}'
            ),
            "application/json",
            "Validation Report.json",
        ),
    )


def test_cad_success_requires_and_verifies_actual_symbol_footprint_and_model(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")

    digest = store.record_provider_artifact_success(
        identity=_IDENTITY,
        operation=KICAD_CAD_OPERATION,
        provider_key="snapmagic",
        adapter_version="1.0.0",
        artifacts=_cad_artifacts(),
    )
    manifest = store.verify_provider_success(
        digest,
        identity=_IDENTITY,
        operation=KICAD_CAD_OPERATION,
        provider_key="snapmagic",
        adapter_version="1.0.0",
    )

    assert manifest["schema"] == "stockroom.provider-artifact-evidence/1"
    assert [item["role"] for item in manifest["objects"]] == [
        "footprint",
        "model",
        "symbol",
        "validation_report",
    ]
    assert {item["provider"] for item in manifest["objects"]} == {"snapmagic"}
    assert all(store.object_bytes(item["digest"]) for item in manifest["objects"])


def test_cad_download_cannot_claim_success_when_the_model_is_missing(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    incomplete = tuple(item for item in _cad_artifacts() if item.role != "model")

    with pytest.raises(EvidenceError, match="missing model"):
        store.record_provider_artifact_success(
            identity=_IDENTITY,
            operation=KICAD_CAD_OPERATION,
            provider_key="snapmagic",
            adapter_version="1.0.0",
            artifacts=incomplete,
        )


def test_tampered_cad_artifact_fails_verification(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    digest = store.record_provider_artifact_success(
        identity=_IDENTITY,
        operation=KICAD_CAD_OPERATION,
        provider_key="snapmagic",
        adapter_version="1.0.0",
        artifacts=_cad_artifacts(),
    )
    manifest = json.loads(store.object_bytes(digest))
    model = next(item for item in manifest["objects"] if item["role"] == "model")
    store.object_path(model["digest"]).write_bytes(b"tampered")

    with pytest.raises(EvidenceCorruption):
        store.verify_provider_success(
            digest,
            identity=_IDENTITY,
            operation=KICAD_CAD_OPERATION,
            provider_key="snapmagic",
            adapter_version="1.0.0",
        )
