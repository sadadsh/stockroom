"""Immutable CAD bundles can be selected without losing or incoherently mixing alternatives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from stockroom.cad_materialization import materialize_pair
from stockroom.cad_variants import (
    CadVariantResolutionError,
    list_cad_variants,
    resolve_cad_variant,
    same_cad_evidence_set,
    selection_matches,
)
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.evidence.store import VerifiedRoleArtifact
from stockroom.model.part import PartRecord


@dataclass(frozen=True)
class _Identity:
    authoritative_manufacturer_key: str = "ON Semiconductor"
    mpn_canonical: str = "S1M"


@dataclass(frozen=True)
class _Operation:
    label: str


_IDENTITY = _Identity()
_KICAD = _Operation("cad:kicad")
_ALTIUM = _Operation("cad:altium")


def _role_report(
    *,
    provider: str,
    roles: tuple[str, ...],
    operation: str,
    source_manifests: tuple[str, ...] = (),
) -> bytes:
    return json.dumps(
        {
            "identity": {
                "authoritative_manufacturer_key": _IDENTITY.authoritative_manufacturer_key,
                "mpn_canonical": _IDENTITY.mpn_canonical,
            },
            "operation": operation,
            "provider": provider,
            "roles": sorted(roles),
            "schema": "stockroom.cad-role-validation/1",
            "source_manifests": sorted(source_manifests),
            "valid": True,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _record_bundle(
    store: EvidenceStore,
    *,
    provider: str,
    artifacts: dict[str, bytes],
    operation: _Operation,
    source_manifests: tuple[str, ...] = (),
) -> str:
    roles = tuple(artifacts)
    return store.record_role_artifact_success(
        identity=_IDENTITY,
        operation=operation,
        provider_key=provider,
        adapter_version="browser-v1",
        artifacts=tuple(
            EvidenceArtifact(
                role,
                data,
                "application/octet-stream",
                f"S1M-{provider}-{role}.bin",
            )
            for role, data in artifacts.items()
        ),
        validation_report=_role_report(
            provider=provider,
            roles=roles,
            operation=operation.label,
            source_manifests=source_manifests,
        ),
        source_manifests=source_manifests,
    )


def _kicad_bytes() -> dict[str, bytes]:
    return {
        "symbol": b'(kicad_symbol_lib (version 20231120) (generator "Stockroom"))',
        "footprint": b'(footprint "S1M" (version 20240108) (generator "Stockroom"))',
        "model": b"ISO-10303-21;\nEND-ISO-10303-21;\n",
    }


def test_every_exact_bundle_survives_switching_and_ultra_librarian_is_recommended(
    tmp_path: Path,
) -> None:
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    # Same bytes from two providers remain two bundle variants because provenance differs, while
    # the object store deduplicates the repeated content.
    snap_manifest = _record_bundle(
        store,
        provider="snapmagic",
        artifacts=_kicad_bytes(),
        operation=_KICAD,
    )
    ultra_manifest = _record_bundle(
        store,
        provider="ultralibrarian",
        artifacts=_kicad_bytes(),
        operation=_KICAD,
    )

    listed = list_cad_variants(store, identity=_IDENTITY, tool="kicad")

    assert [variant.provider for variant in listed] == ["ultralibrarian", "snapmagic"]
    assert {variant.manifest_digest for variant in listed} == {
        ultra_manifest,
        snap_manifest,
    }
    assert all(
        {artifact.asset_kind for artifact in variant.artifacts} == {"symbol", "footprint", "model"}
        for variant in listed
    )

    record = PartRecord(id="s1m-0000", mpn="S1M", manufacturer="ON Semiconductor")
    snap = resolve_cad_variant(
        store,
        identity=_IDENTITY,
        tool="kicad",
        manifest_digest=snap_manifest,
    )
    record.cad_variants.select("kicad", snap.pointer)
    assert selection_matches(record.cad_variants, snap.descriptor)

    ultra = resolve_cad_variant(
        store,
        identity=_IDENTITY,
        tool="kicad",
        manifest_digest=ultra_manifest,
    )
    record.cad_variants.select("kicad", ultra.pointer)

    assert selection_matches(record.cad_variants, ultra.descriptor)
    assert not selection_matches(record.cad_variants, snap.descriptor)
    assert set(ultra.data) == {"symbol", "footprint", "model"}
    assert store.object_bytes(snap_manifest)
    assert store.object_bytes(ultra_manifest)
    assert len(list_cad_variants(store, identity=_IDENTITY, tool="kicad")) == 2


def test_partial_role_evidence_is_preserved_but_not_selectable_as_a_bundle(
    tmp_path: Path,
) -> None:
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    partial = _record_bundle(
        store,
        provider="ultralibrarian",
        artifacts={"symbol": _kicad_bytes()["symbol"]},
        operation=_KICAD,
    )

    assert store.object_bytes(partial)
    assert len(store.list_role_variants(identity=_IDENTITY, role="symbol")) == 1
    assert list_cad_variants(store, identity=_IDENTITY, tool="kicad") == ()


def test_altium_bundle_has_native_roles_and_a_verified_kicad_source_closure(
    tmp_path: Path,
) -> None:
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    kicad_manifest = _record_bundle(
        store,
        provider="ultralibrarian",
        artifacts=_kicad_bytes(),
        operation=_KICAD,
    )
    altium_manifest = _record_bundle(
        store,
        provider="ultralibrarian",
        artifacts={
            "altium_symbol": b"native SchLib bytes",
            "altium_footprint": b"native PcbLib with embedded 3D bytes",
        },
        operation=_ALTIUM,
        source_manifests=(kicad_manifest,),
    )

    resolved = resolve_cad_variant(
        store,
        identity=_IDENTITY,
        tool="altium",
        manifest_digest=altium_manifest,
    )

    assert {artifact.asset_kind for artifact in resolved.descriptor.artifacts} == {
        "symbol",
        "footprint",
    }
    assert {artifact.evidence_role for artifact in resolved.descriptor.artifacts} == {
        "altium_symbol",
        "altium_footprint",
    }
    assert "model" not in resolved.data
    assert resolved.descriptor.source_manifests == (kicad_manifest,)


def test_one_manifest_projects_the_same_author_set_to_both_eda_tools(
    tmp_path: Path,
) -> None:
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    shared_manifest = _record_bundle(
        store,
        provider="digikey-ultralibrarian",
        artifacts={
            **_kicad_bytes(),
            "altium_symbol": b"native SchLib bytes",
            "altium_footprint": b"native PcbLib with embedded 3D bytes",
        },
        operation=_KICAD,
    )

    kicad = resolve_cad_variant(
        store,
        identity=_IDENTITY,
        tool="kicad",
        manifest_digest=shared_manifest,
    )
    altium = resolve_cad_variant(
        store,
        identity=_IDENTITY,
        tool="altium",
        manifest_digest=shared_manifest,
    )

    assert same_cad_evidence_set(kicad.descriptor, altium.descriptor)
    assert kicad.descriptor.provider == altium.descriptor.provider
    assert kicad.descriptor.manifest_digest == altium.descriptor.manifest_digest


def test_same_provider_but_split_manifests_cannot_be_materialized_as_one_pair(
    tmp_path: Path,
) -> None:
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    kicad_manifest = _record_bundle(
        store,
        provider="digikey-ultralibrarian",
        artifacts=_kicad_bytes(),
        operation=_KICAD,
    )
    altium_manifest = _record_bundle(
        store,
        provider="digikey-ultralibrarian",
        artifacts={
            "altium_symbol": b"native SchLib bytes",
            "altium_footprint": b"native PcbLib with embedded 3D bytes",
        },
        operation=_ALTIUM,
        source_manifests=(kicad_manifest,),
    )
    kicad = resolve_cad_variant(
        store,
        identity=_IDENTITY,
        tool="kicad",
        manifest_digest=kicad_manifest,
    )
    altium = resolve_cad_variant(
        store,
        identity=_IDENTITY,
        tool="altium",
        manifest_digest=altium_manifest,
    )

    assert not same_cad_evidence_set(kicad.descriptor, altium.descriptor)
    record = PartRecord(id="s1m-0000", mpn="S1M", manufacturer="ON Semiconductor")
    with pytest.raises(ValueError, match="one provider evidence set"):
        materialize_pair(object(), record, kicad, altium)


def test_a_broken_store_cannot_mix_roles_from_different_manifests() -> None:
    def _artifact(role: str, marker: str, manifest: str) -> VerifiedRoleArtifact:
        data = marker.encode()
        import hashlib

        return VerifiedRoleArtifact(
            manifest_digest=f"sha256:{manifest * 64}",
            artifact_digest=f"sha256:{hashlib.sha256(data).hexdigest()}",
            role=role,
            data=data,
            media_type="application/octet-stream",
            suggested_name=f"S1M.{role}",
            provider_key="ultralibrarian",
            adapter_version="broken-v1",
            operation="cad:kicad",
        )

    symbol = _artifact("symbol", "symbol", "a")
    mixed = {
        "symbol": symbol,
        "footprint": _artifact("footprint", "footprint", "b"),
        "model": _artifact("model", "model", "a"),
    }

    class _BrokenStore:
        def list_role_variants(self, **_kwargs):
            return (symbol,)

        def verified_role_artifacts(self, _digest, **_kwargs):
            return mixed

    with pytest.raises(CadVariantResolutionError, match="one evidence manifest"):
        list_cad_variants(_BrokenStore(), identity=_IDENTITY, tool="kicad")
    with pytest.raises(CadVariantResolutionError, match="one evidence manifest"):
        resolve_cad_variant(
            _BrokenStore(),
            identity=_IDENTITY,
            tool="kicad",
            manifest_digest=symbol.manifest_digest,
        )


def test_an_unregistered_tool_is_loud_before_evidence_access() -> None:
    class _NeverCalled:
        def list_role_variants(self, **_kwargs):
            raise AssertionError("evidence store was called")

        def verified_role_artifacts(self, _digest, **_kwargs):
            raise AssertionError("evidence store was called")

    with pytest.raises(KeyError, match="no coherent CAD variant bundle"):
        list_cad_variants(_NeverCalled(), identity=_IDENTITY, tool="eagle")
