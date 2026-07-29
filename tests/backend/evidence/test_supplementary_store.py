from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from stockroom.cad_variants import list_cad_variants
from stockroom.capture.download_broker import DownloadReceipt
from stockroom.evidence import (
    EvidenceCorruption,
    EvidenceManifestMismatch,
    EvidenceStore,
)
from stockroom.planning import ExactPartIdentity

_IDENTITY = ExactPartIdentity("Texas Instruments", "TPD6E05U06RVZR")
_SURFACE = "digikey"
_PROVIDER = "digikey-traceparts"


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _receipt(
    directory: Path,
    *,
    name: str,
    data: bytes,
    task_id: str,
    identity: ExactPartIdentity = _IDENTITY,
    digest: str | None = None,
) -> DownloadReceipt:
    path = directory / name
    path.write_bytes(data)
    return DownloadReceipt(
        task_id=task_id,
        manufacturer_key=identity.authoritative_manufacturer_key,
        mpn_canonical=identity.mpn_canonical,
        path=path,
        suggested_name=name,
        source_url="https://www.digikey.com/models/file.step?token=secret&view=full#private",
        final_url="https://cdn.example.invalid/file.step?access_token=secret",
        sha256=digest or _digest(data),
        size_bytes=len(data),
        transport="playwright",
        attempt=1,
        surface_key=_SURFACE,
        evidence_provider_key=_PROVIDER,
    )


def _record(
    store: EvidenceStore,
    receipts: tuple[DownloadReceipt, ...],
    *,
    identity: ExactPartIdentity = _IDENTITY,
) -> str:
    return store.record_supplementary_artifacts(
        identity=identity,
        surface_key=_SURFACE,
        provider_key=_PROVIDER,
        adapter_version="digikey-models/1",
        receipts=receipts,
    )


def test_supplementary_originals_are_deduplicated_sanitized_and_not_projectable(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "Staging"
    staging.mkdir()
    receipts = (
        _receipt(
            staging,
            name="supplier-certified.step",
            data=b"STEP ORIGINAL",
            task_id="capture-1",
        ),
        _receipt(
            staging,
            name="drawing.dxf",
            data=b"DXF ORIGINAL",
            task_id="capture-2",
        ),
    )
    store = EvidenceStore(tmp_path / "Evidence")

    first = _record(store, receipts)
    second = _record(store, receipts)

    assert first == second
    manifest = json.loads(store.object_bytes(first))
    assert manifest["schema"] == "stockroom.supplementary-artifact-evidence/1"
    assert manifest["projectable"] is False
    assert manifest["surface"] == _SURFACE
    assert manifest["provider"] == _PROVIDER
    assert len(manifest["objects"]) == 2
    for reference in manifest["objects"]:
        assert "role" not in reference
        assert "?" not in reference["receipt"]["source_url"]
        assert "#" not in reference["receipt"]["source_url"]
        assert "?" not in reference["receipt"]["final_url"]

    listed = store.list_supplementary_artifacts(identity=_IDENTITY)
    assert len(listed) == 1
    assert listed[0].manifest_digest == first
    assert {artifact.suggested_name for artifact in listed[0].artifacts} == {
        "drawing.dxf",
        "supplier-certified.step",
    }
    assert list_cad_variants(store, identity=_IDENTITY, tool="kicad") == ()
    assert list_cad_variants(store, identity=_IDENTITY, tool="altium") == ()


def test_supplementary_evidence_survives_staging_deletion_and_detects_cas_tamper(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "Staging"
    staging.mkdir()
    receipt = _receipt(
        staging,
        name="manufacturer-model.step",
        data=b"ORIGINAL MODEL",
        task_id="capture-3",
    )
    store = EvidenceStore(tmp_path / "Evidence")
    digest = _record(store, (receipt,))

    receipt.path.unlink()
    verified = store.verify_supplementary_artifacts(
        digest,
        identity=_IDENTITY,
        surface_key=_SURFACE,
        provider_key=_PROVIDER,
        adapter_version="digikey-models/1",
    )
    artifact = verified.artifacts[0]
    assert artifact.path.read_bytes() == b"ORIGINAL MODEL"

    artifact.path.write_bytes(b"TAMPERED")
    with pytest.raises(EvidenceCorruption):
        store.verify_supplementary_artifacts(
            digest,
            identity=_IDENTITY,
            surface_key=_SURFACE,
            provider_key=_PROVIDER,
            adapter_version="digikey-models/1",
        )


def test_supplementary_receipt_hash_must_match_staged_bytes(tmp_path: Path) -> None:
    staging = tmp_path / "Staging"
    staging.mkdir()
    receipt = _receipt(
        staging,
        name="mismatch.step",
        data=b"ACTUAL",
        task_id="capture-4",
        digest=_digest(b"CLAIMED"),
    )
    store = EvidenceStore(tmp_path / "Evidence")

    with pytest.raises(
        EvidenceManifestMismatch,
        match="do not match the receipt digest",
    ):
        _record(store, (receipt,))

    assert store.list_supplementary_artifacts(identity=_IDENTITY) == ()


def test_supplementary_index_is_scoped_to_exact_identity(tmp_path: Path) -> None:
    staging = tmp_path / "Staging"
    staging.mkdir()
    other = ExactPartIdentity("Texas Instruments", "TPS7A4701RGWR")
    first = _receipt(
        staging,
        name="first.step",
        data=b"FIRST",
        task_id="capture-5",
    )
    second = _receipt(
        staging,
        name="second.step",
        data=b"SECOND",
        task_id="capture-6",
        identity=other,
    )
    store = EvidenceStore(
        tmp_path / "Evidence",
        max_object_bytes=512 * 1024 * 1024,
    )

    first_digest = _record(store, (first,))
    second_digest = _record(store, (second,), identity=other)

    assert [item.manifest_digest for item in store.list_supplementary_artifacts(
        identity=_IDENTITY
    )] == [first_digest]
    assert [item.manifest_digest for item in store.list_supplementary_artifacts(
        identity=other
    )] == [second_digest]
