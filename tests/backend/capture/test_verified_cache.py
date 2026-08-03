"""The completion ladder reuses immutable exact CAD evidence before touching a network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockroom.cad_variants import resolve_cad_variant
from stockroom.capture.evidence import exact_identity
from stockroom.capture.requirements import Requirement
from stockroom.capture.verified_cache import (
    VerifiedEvidenceSource,
    active_pair_is_verified,
    record_completion_evidence,
)
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.model.cad_variant import CadVariantSelections
from stockroom.model.part import AssetRef, PartRecord, RequirementOverride
from stockroom.model.part_class import PartClass
from stockroom.planning import ALTIUM_CAD_OPERATION, KICAD_CAD_OPERATION


def _record() -> PartRecord:
    return PartRecord(
        id="tps62130",
        display_name="TPS62130",
        category="ICs",
        manufacturer="Texas Instruments",
        mpn="TPS62130RGTR",
    )


def _report(
    identity,
    *,
    operation: str,
    provider: str,
    roles: tuple[str, ...],
    source_manifests: tuple[str, ...] = (),
    native_entries: bool = True,
) -> bytes:
    cross_report = {
        "valid": True,
        "terminal_equivalence": True,
        "pad_equivalence": True,
        "package_equivalence": True,
    }
    if native_entries:
        cross_report["altium"] = {
            "symbol_entry": "TPS62130RGTR",
            "footprint_entry": "TPS62130RGTR",
        }
    return json.dumps(
        {
            "identity": {
                "authoritative_manufacturer_key": (identity.authoritative_manufacturer_key),
                "mpn_canonical": identity.mpn_canonical,
            },
            "operation": operation,
            "provider": provider,
            "cross_eda": {
                "status": "verified",
                "report": cross_report,
            },
            "roles": sorted(roles),
            "schema": "stockroom.cad-role-validation/1",
            "source_manifests": sorted(source_manifests),
            "valid": True,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _bundle(
    store: EvidenceStore,
    identity,
    *,
    provider: str,
    artifacts: dict[str, bytes],
    altium_source: str = "",
    native_entries: bool = True,
) -> str:
    source_manifests = (altium_source,) if altium_source else ()
    operation = ALTIUM_CAD_OPERATION if "altium_symbol" in artifacts else KICAD_CAD_OPERATION
    roles = tuple(artifacts)
    return store.record_role_artifact_success(
        identity=identity,
        operation=operation,
        provider_key=provider,
        adapter_version="verified-cache-test-v1",
        artifacts=tuple(
            EvidenceArtifact(
                role,
                data,
                "application/octet-stream",
                f"TPS62130-{role}.bin",
            )
            for role, data in artifacts.items()
        ),
        validation_report=_report(
            identity,
            operation=operation.label,
            provider=provider,
            roles=roles,
            source_manifests=source_manifests,
            native_entries=native_entries,
        ),
        source_manifests=source_manifests,
    )


def _kicad_bytes(marker: bytes = b"ul") -> dict[str, bytes]:
    return {
        "symbol": b"(kicad_symbol_lib " + marker + b")",
        "footprint": b"(footprint TPS62130 " + marker + b")",
        "model": b"ISO-10303-21;\n" + marker + b"\nEND-ISO-10303-21;\n",
    }


def _source(store: EvidenceStore, calls: list[tuple]) -> VerifiedEvidenceSource:
    return VerifiedEvidenceSource(
        store,
        materialize_kicad=lambda record, kicad: calls.append(
            ("kicad", record.id, kicad.descriptor.manifest_digest)
        ),
        materialize_pair=lambda record, kicad, altium: calls.append(
            (
                "pair",
                record.id,
                kicad.descriptor.manifest_digest,
                altium.descriptor.manifest_digest,
            )
        ),
        projection_verifier=lambda _record, _resolved: None,
    )


def _completion_evidence(store: EvidenceStore, record: PartRecord):
    return record_completion_evidence(
        store,
        record,
        projection_verifier=lambda _record, _resolved: None,
    )


def _active_pair_verified(store: EvidenceStore, record: PartRecord) -> bool:
    return active_pair_is_verified(
        store,
        record,
        projection_verifier=lambda _record, _resolved: None,
    )


def _complete_record(record: PartRecord) -> None:
    for tool, kinds in {
        "kicad": ("symbol", "footprint", "model"),
        "altium": ("symbol", "footprint"),
    }.items():
        for kind in kinds:
            reference = (
                AssetRef(file=f"{record.id}.step")
                if kind == "model"
                else AssetRef(lib="Stockroom", name=record.mpn)
            )
            record.assets_for(tool).set(kind, reference)


def _select_pair(
    store: EvidenceStore,
    record: PartRecord,
    *,
    digest: str,
) -> None:
    identity = exact_identity(record)
    record.cad_variants = CadVariantSelections(
        active={
            "kicad": resolve_cad_variant(
                store,
                identity=identity,
                tool="kicad",
                manifest_digest=digest,
            ).pointer,
            "altium": resolve_cad_variant(
                store,
                identity=identity,
                tool="altium",
                manifest_digest=digest,
            ).pointer,
        }
    )


def _complete_pair(
    store: EvidenceStore,
    record: PartRecord,
    *,
    provider: str = "ultralibrarian",
    marker: bytes = b"ul",
    native_entries: bool = True,
) -> str:
    identity = exact_identity(record)
    return _bundle(
        store,
        identity,
        provider=provider,
        artifacts={
            **_kicad_bytes(marker),
            "altium_symbol": b"native SchLib " + marker,
            "altium_footprint": b"native PcbLib " + marker,
        },
        native_entries=native_entries,
    )


def test_source_reverifies_and_materializes_a_complete_cross_eda_pair_first(
    tmp_path: Path,
) -> None:
    record = _record()
    identity = exact_identity(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    evidence_set = _bundle(
        store,
        identity,
        provider="ultralibrarian",
        artifacts={
            **_kicad_bytes(),
            "altium_symbol": b"native SchLib",
            "altium_footprint": b"native PcbLib with embedded model",
        },
    )
    calls: list[tuple] = []

    outcome = _source(store, calls).supply(record)

    assert calls == [("pair", record.id, evidence_set, evidence_set)]
    assert set(outcome.satisfied) == set(Requirement)
    assert outcome.error == ""
    assert outcome.skipped == ""


def test_source_refuses_a_proved_pair_without_native_entry_bindings(tmp_path: Path) -> None:
    record = _record()
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _bundle(
        store,
        exact_identity(record),
        provider="ultralibrarian",
        artifacts={
            **_kicad_bytes(),
            "altium_symbol": b"native SchLib",
            "altium_footprint": b"native PcbLib",
        },
        native_entries=False,
    )
    calls: list[tuple] = []

    outcome = _source(store, calls).supply(record)

    assert calls == []
    assert "native Altium symbol entry" in outcome.error


def test_source_never_projects_kicad_without_same_download_altium(
    tmp_path: Path,
) -> None:
    record = _record()
    identity = exact_identity(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _bundle(
        store,
        identity,
        provider="snapmagic",
        artifacts=_kicad_bytes(b"snap"),
    )
    _bundle(
        store,
        identity,
        provider="snapmagic",
        artifacts={
            "altium_symbol": b"unbound SchLib",
            "altium_footprint": b"unbound PcbLib",
        },
    )
    calls: list[tuple] = []

    outcome = _source(store, calls).supply(record)

    assert calls == []
    assert outcome.satisfied == ()
    assert "same-provider, same-download" in outcome.skipped


def test_corrupt_retained_bytes_fail_closed_without_materialization(
    tmp_path: Path,
) -> None:
    record = _record()
    identity = exact_identity(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _bundle(
        store,
        identity,
        provider="ultralibrarian",
        artifacts=_kicad_bytes(),
    )
    symbol = store.list_role_variants(identity=identity, role="symbol")[0]
    store.object_path(symbol.artifact_digest).write_bytes(b"tampered")
    calls: list[tuple] = []

    outcome = _source(store, calls).supply(record)

    assert calls == []
    assert "failed revalidation" in outcome.error
    assert outcome.satisfied == ()


def test_empty_exact_cache_declines_without_error_or_side_effect(
    tmp_path: Path,
) -> None:
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    calls: list[tuple] = []

    outcome = _source(store, calls).supply(_record())

    assert calls == []
    assert outcome.error == ""
    assert outcome.skipped == "no complete exact CAD evidence is retained"


def test_active_pair_requires_resolvable_same_evidence_pointers(tmp_path: Path) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record)
    _select_pair(store, record, digest=digest)

    evidence = _completion_evidence(store, record)

    assert evidence.state == "verified"
    assert evidence.manifest_digest == digest
    assert "reverified" in evidence.reason
    assert _active_pair_verified(store, record) is True


def test_active_pair_requires_installed_projection_readback(tmp_path: Path) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record)
    _select_pair(store, record, digest=digest)

    def reject_projection(_record, _resolved) -> None:
        raise ValueError("installed footprint is missing")

    evidence = record_completion_evidence(
        store,
        record,
        projection_verifier=reject_projection,
    )

    assert evidence.state == "unverified"
    assert evidence.manifest_digest is None
    assert "installed CAD projection" in evidence.reason
    assert "ValueError" in evidence.reason


def test_completion_forwards_the_reverified_immutable_validation_report(
    tmp_path: Path,
) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record)
    _select_pair(store, record, digest=digest)
    observed: dict[str, dict[str, object]] = {}

    def verify(_record, _resolved, *, validation_reports=None) -> None:
        assert validation_reports is not None
        observed.update(validation_reports)

    evidence = record_completion_evidence(
        store,
        record,
        projection_verifier=verify,
    )

    assert evidence.state == "verified"
    assert observed["kicad"] == observed["altium"]
    cross = observed["kicad"]["cross_eda"]
    assert isinstance(cross, dict)
    report = cross["report"]
    assert isinstance(report, dict)
    assert report["altium"]["footprint_entry"] == "TPS62130RGTR"


def test_complete_looking_assets_without_active_pointers_are_not_preserved(
    tmp_path: Path,
) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _complete_pair(store, record)

    evidence = _completion_evidence(store, record)

    assert evidence.state == "unverified"
    assert evidence.manifest_digest is None
    assert "pointer is absent" in evidence.reason
    assert _active_pair_verified(store, record) is False


def test_active_pair_without_native_entry_bindings_is_not_verified(tmp_path: Path) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record, native_entries=False)
    _select_pair(store, record, digest=digest)

    evidence = _completion_evidence(store, record)

    assert evidence.state == "unverified"
    assert "cross-EDA pair could not be reverified" in evidence.reason


def test_split_active_pointers_from_different_manifests_are_not_one_pair(
    tmp_path: Path,
) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    first = _complete_pair(store, record, provider="ultralibrarian", marker=b"first")
    second = _complete_pair(store, record, provider="snapmagic", marker=b"second")
    identity = exact_identity(record)
    record.cad_variants = CadVariantSelections(
        active={
            "kicad": resolve_cad_variant(
                store,
                identity=identity,
                tool="kicad",
                manifest_digest=first,
            ).pointer,
            "altium": resolve_cad_variant(
                store,
                identity=identity,
                tool="altium",
                manifest_digest=second,
            ).pointer,
        }
    )

    evidence = _completion_evidence(store, record)

    assert evidence.state == "unverified"
    assert "do not share one evidence set" in evidence.reason
    assert _active_pair_verified(store, record) is False


def test_tampered_active_evidence_is_not_preserved(tmp_path: Path) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record)
    _select_pair(store, record, digest=digest)
    identity = exact_identity(record)
    symbol = store.list_role_variants(identity=identity, role="symbol")[0]
    store.object_path(symbol.artifact_digest).write_bytes(b"tampered")

    evidence = _completion_evidence(store, record)

    assert evidence.state == "unverified"
    assert "could not be reverified" in evidence.reason
    assert _active_pair_verified(store, record) is False


def test_active_pointers_cannot_verify_absent_projected_references(tmp_path: Path) -> None:
    record = _record()
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record)
    _select_pair(store, record, digest=digest)

    evidence = _completion_evidence(store, record)

    assert evidence.state == "unverified"
    assert "projected references are absent" in evidence.reason


def test_pointer_for_another_exact_identity_cannot_verify_this_record(
    tmp_path: Path,
) -> None:
    first = _record()
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, first)
    _select_pair(store, first, digest=digest)
    other = _record()
    other.mpn = "TPS62131RGTR"
    _complete_record(other)
    other.cad_variants = first.cad_variants

    evidence = _completion_evidence(store, other)

    assert evidence.state == "unverified"
    assert "could not be reverified" in evidence.reason


def test_one_owned_tool_can_be_verified_without_fabricating_a_pair(tmp_path: Path) -> None:
    record = _record()
    record.requires_override = RequirementOverride(
        needs=(),
        tools=("altium",),
        reason="this exact part is intentionally KiCad-only",
    )
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record)
    identity = exact_identity(record)
    record.cad_variants = CadVariantSelections(
        active={
            "kicad": resolve_cad_variant(
                store,
                identity=identity,
                tool="kicad",
                manifest_digest=digest,
            ).pointer,
        }
    )

    evidence = _completion_evidence(store, record)

    assert evidence.state == "verified"
    assert evidence.manifest_digest == digest
    assert _active_pair_verified(store, record) is False


@pytest.mark.parametrize("part_class", [PartClass.PASSIVE, PartClass.VIRTUAL])
def test_classes_without_owned_cad_are_explicitly_not_required(
    tmp_path: Path,
    part_class: PartClass,
) -> None:
    record = _record()
    record.part_class = part_class
    store = EvidenceStore((tmp_path / "Evidence").resolve())

    evidence = _completion_evidence(store, record)

    assert evidence.state == "not-required"
    assert evidence.manifest_digest is None
    assert evidence.reason == "this part class has no owned CAD requirements"
