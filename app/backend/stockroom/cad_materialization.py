"""Atomic materialization of already verified coherent CAD evidence.

The evidence store is machine-local and immutable.  Both the authenticated variant selector and
the zero-interaction verified-cache source need the same operation: reverified bytes become one
KiCad bundle, one native Altium bundle, or one cross-EDA-proved pair without an invalid midpoint.
Keeping that operation here prevents the API router from becoming a second ingest engine.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from stockroom.cad_variants import (
    CadVariantDescriptor,
    ResolvedCadVariant,
    same_cad_evidence_set,
)
from stockroom.ingest.naming import propose_entry_name
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.staging import StagingCandidate
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.asset import AssetOrigin
from stockroom.model.part import PartRecord


def _origin(descriptor: CadVariantDescriptor) -> AssetOrigin:
    return AssetOrigin(
        vendor=descriptor.provider,
        extra={
            "evidence_manifest_digest": descriptor.manifest_digest,
            "evidence_adapter_version": descriptor.adapter_version,
            "evidence_operation": descriptor.operation,
        },
    )


def _pick_kicad_symbol(path: Path, mpn: str, current_name: str = "") -> str:
    names = SymbolLib.load(path).symbol_names
    if not names:
        raise ValueError("selected KiCad evidence contains no symbol entry")
    # Installed-readback evidence may retain a whole category library.  Its stable record binding
    # is stronger than a filename heuristic and makes reactivation exact for human-named entries.
    if current_name and current_name in names:
        return current_name
    exact = [name for name in names if name == mpn]
    if len(exact) == 1:
        return exact[0]
    folded = [name for name in names if name.casefold() == mpn.casefold()]
    if len(folded) == 1:
        return folded[0]
    if len(names) == 1:
        return names[0]
    raise ValueError(
        "selected KiCad evidence contains multiple symbols without one exact MPN match"
    )


def materialize_kicad(ctx, record: PartRecord, resolved: ResolvedCadVariant) -> PartRecord:
    """Install one reverified complete KiCad bundle and its immutable pointer."""

    with tempfile.TemporaryDirectory(prefix="Stockroom-CAD-Variant-") as temporary:
        root = Path(temporary)
        symbol_path = root / "Variant.kicad_sym"
        footprint_path = root / "Variant.kicad_mod"
        model_path = root / "Variant.step"
        symbol_path.write_bytes(resolved.data["symbol"])
        footprint_path.write_bytes(resolved.data["footprint"])
        model_path.write_bytes(resolved.data["model"])
        current_symbol = record.assets_for("kicad").symbol
        source_name = _pick_kicad_symbol(
            symbol_path,
            record.mpn,
            current_symbol.name if current_symbol is not None else "",
        )
        entry_name = (
            current_symbol.name
            if current_symbol is not None and current_symbol.name
            else propose_entry_name(source_name, record.mpn)
        )
        candidate = StagingCandidate(
            vendor=resolved.descriptor.provider,
            symbol_lib_path=symbol_path,
            symbol_name=source_name,
            footprint_variants=[footprint_path],
            model_path=model_path,
            entry_name=entry_name,
            category=record.category,
            mpn=record.mpn,
            manufacturer=record.manufacturer,
        )
        pipeline = IngestPipeline(ctx.profile, ctx.repo, ctx.cli)
        return pipeline.attach_assets(
            record.id,
            candidate,
            origin=_origin(resolved.descriptor),
            now_iso=datetime.now(UTC).isoformat(),
            active_variant=resolved.pointer,
            replace_existing=True,
        )


def materialize_altium(ctx, record: PartRecord, resolved: ResolvedCadVariant) -> PartRecord:
    """Install one reverified native Altium pair and its immutable pointer."""

    with tempfile.TemporaryDirectory(prefix="Stockroom-CAD-Variant-") as temporary:
        root = Path(temporary)
        symbol_path = root / "Variant.SchLib"
        footprint_path = root / "Variant.PcbLib"
        symbol_path.write_bytes(resolved.data["symbol"])
        footprint_path.write_bytes(resolved.data["footprint"])
        return ctx.ops.attach_altium_assets(
            record.id,
            symbol_path,
            footprint_path,
            origin=_origin(resolved.descriptor),
            now_iso=datetime.now(UTC).isoformat(),
            active_variant=resolved.pointer,
        )


def materialize_pair(
    ctx,
    record: PartRecord,
    kicad_resolved: ResolvedCadVariant,
    altium_resolved: ResolvedCadVariant,
) -> PartRecord:
    """Install one same-download dual-EDA set through one rollback-safe transaction."""

    if not same_cad_evidence_set(
        kicad_resolved.descriptor,
        altium_resolved.descriptor,
    ):
        raise ValueError(
            "the selected KiCad and Altium projections do not share one provider evidence set"
        )

    with tempfile.TemporaryDirectory(prefix="Stockroom-CAD-Pair-") as temporary:
        root = Path(temporary)
        kicad_symbol_path = root / "Variant.kicad_sym"
        kicad_footprint_path = root / "Variant.kicad_mod"
        kicad_model_path = root / "Variant.step"
        altium_symbol_path = root / "Variant.SchLib"
        altium_footprint_path = root / "Variant.PcbLib"
        kicad_symbol_path.write_bytes(kicad_resolved.data["symbol"])
        kicad_footprint_path.write_bytes(kicad_resolved.data["footprint"])
        kicad_model_path.write_bytes(kicad_resolved.data["model"])
        altium_symbol_path.write_bytes(altium_resolved.data["symbol"])
        altium_footprint_path.write_bytes(altium_resolved.data["footprint"])

        current_symbol = record.assets_for("kicad").symbol
        source_name = _pick_kicad_symbol(
            kicad_symbol_path,
            record.mpn,
            current_symbol.name if current_symbol is not None else "",
        )
        entry_name = (
            current_symbol.name
            if current_symbol is not None and current_symbol.name
            else propose_entry_name(source_name, record.mpn)
        )
        candidate = StagingCandidate(
            vendor=kicad_resolved.descriptor.provider,
            symbol_lib_path=kicad_symbol_path,
            symbol_name=source_name,
            footprint_variants=[kicad_footprint_path],
            model_path=kicad_model_path,
            entry_name=entry_name,
            category=record.category,
            mpn=record.mpn,
            manufacturer=record.manufacturer,
        )
        pipeline = IngestPipeline(ctx.profile, ctx.repo, ctx.cli)
        return pipeline.attach_coherent_cad_assets(
            record.id,
            candidate,
            altium_symbol_path,
            altium_footprint_path,
            kicad_origin=_origin(kicad_resolved.descriptor),
            altium_origin=_origin(altium_resolved.descriptor),
            now_iso=datetime.now(UTC).isoformat(),
            kicad_active_variant=kicad_resolved.pointer,
            altium_active_variant=altium_resolved.pointer,
        )


__all__ = ["materialize_altium", "materialize_kicad", "materialize_pair"]
