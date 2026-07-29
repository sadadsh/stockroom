"""The completion ladder reuses immutable exact CAD evidence before touching a network."""

from __future__ import annotations

import json
from pathlib import Path

from stockroom.cad_variants import resolve_cad_variant
from stockroom.capture.evidence import exact_identity
from stockroom.capture.requirements import Requirement
from stockroom.capture.verified_cache import (
    VerifiedEvidenceSource,
    active_pair_is_verified,
)
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.model.cad_variant import CadVariantSelections
from stockroom.model.part import AssetRef, PartRecord
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
) -> bytes:
    return json.dumps(
        {
            "identity": {
                "authoritative_manufacturer_key": (identity.authoritative_manufacturer_key),
                "mpn_canonical": identity.mpn_canonical,
            },
            "operation": operation,
            "provider": provider,
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

    assert active_pair_is_verified(store, record) is True


def test_complete_looking_assets_without_active_pointers_are_not_preserved(
    tmp_path: Path,
) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _complete_pair(store, record)

    assert active_pair_is_verified(store, record) is False


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

    assert active_pair_is_verified(store, record) is False


def test_tampered_active_evidence_is_not_preserved(tmp_path: Path) -> None:
    record = _record()
    _complete_record(record)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    digest = _complete_pair(store, record)
    _select_pair(store, record, digest=digest)
    identity = exact_identity(record)
    symbol = store.list_role_variants(identity=identity, role="symbol")[0]
    store.object_path(symbol.artifact_digest).write_bytes(b"tampered")

    assert active_pair_is_verified(store, record) is False
