"""Authenticated inventory and compare-and-switch activation for retained CAD bundles.

Evidence is immutable and machine-local; a part record stores only the one whole-bundle pointer
currently materialized for each EDA tool.  This surface never selects roles independently.  An
activation reverifies the requested manifest, installs every required role through the existing
tool materializer, and persists the pointer in that materializer's single Git Transaction.
"""

from __future__ import annotations

import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from stockroom.api.errors import ApiError
from stockroom.cad_variants import (
    CadVariantDescriptor,
    list_cad_variants,
    resolve_cad_variant,
)
from stockroom.capture.evidence import exact_identity
from stockroom.capture.runner import capture_state_root
from stockroom.evidence import EvidenceStore
from stockroom.ingest.naming import propose_entry_name
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.staging import StagingCandidate
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.asset import AssetOrigin
from stockroom.model.part import PartRecord

_TOOLS = ("kicad", "altium")
_PROVIDER_PRESENTATION = {
    "ultralibrarian": (
        "Ultra Librarian",
        0,
        "Preferred Source",
        "Preferred retained provider; exact identity and bundle validation passed.",
    ),
    "snapmagic": (
        "SnapMagic",
        1,
        "Validated Fallback",
        "Retained fallback; exact identity and bundle validation passed.",
    ),
}
_SUPPLEMENTARY_PROVIDER_LABELS = {
    "traceparts": "TraceParts",
    "cadenas": "CADENAS",
    "manufacturer": "Manufacturer",
    "snapmagic": "SnapMagic",
    "ultralibrarian": "Ultra Librarian",
}
_SUPPLEMENTARY_SURFACE_LABELS = {
    "digikey": "DigiKey",
}


class ActivateCadVariantBody(BaseModel):
    """A stale-safe whole-bundle selection request."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tool: Literal["kicad", "altium"]
    variant_id: str = Field(alias="variantId", pattern=r"sha256:[0-9a-f]{64}")
    expected_active_variant_id: str | None = Field(
        alias="expectedActiveVariantId",
        pattern=r"sha256:[0-9a-f]{64}",
    )


def _store() -> EvidenceStore:
    return EvidenceStore((capture_state_root() / "Evidence").resolve())


def _provider_presentation(provider: str) -> tuple[str, int, str, str]:
    known = _PROVIDER_PRESENTATION.get(provider)
    if known is not None:
        return known
    for family, presentation in _PROVIDER_PRESENTATION.items():
        suffix = f"-{family}"
        if provider.endswith(suffix):
            surface = re.sub(r"[._-]+", " ", provider[: -len(suffix)]).title()
            label, rank, trust_label, _reason = presentation
            return (
                f"{surface} · {label}",
                rank,
                trust_label,
                f"{label}-authored retained variant acquired through {surface}; "
                "exact identity and bundle validation passed.",
            )
    display = re.sub(r"[._-]+", " ", provider).title()
    return (
        display,
        100,
        "Validated Retained Source",
        "Retained provider; exact identity and bundle validation passed.",
    )


def _descriptor_document(descriptor: CadVariantDescriptor) -> dict:
    provider, trust_rank, trust_label, trust_reason = _provider_presentation(
        descriptor.provider
    )
    return {
        "id": descriptor.variant_key,
        "provider": provider,
        "format": (
            "KiCad Native"
            if descriptor.tool == "kicad"
            else "Altium Designer (Native)"
        ),
        "artifacts": [
            {
                "kind": artifact.asset_kind,
                "fileName": artifact.suggested_name
                or {
                    "symbol": "Symbol",
                    "footprint": "Footprint",
                    "model": "3D Model",
                }[artifact.asset_kind],
            }
            for artifact in descriptor.artifacts
        ],
        "evidenceDigest": descriptor.manifest_digest,
        # One digest/readback check per projected role, the bundle validation report itself,
        # and one recursively reverified dependency closure per source manifest.
        "validationChecks": len(descriptor.artifacts) + 1 + len(descriptor.source_manifests),
        "trustRank": trust_rank,
        "trustLabel": trust_label,
        "trustReason": trust_reason,
    }


def _supplementary_provider_label(surface: str, provider: str) -> str:
    author = provider.removeprefix(f"{surface}-")
    author_label = _SUPPLEMENTARY_PROVIDER_LABELS.get(
        author,
        re.sub(r"[._-]+", " ", author).title(),
    )
    surface_label = _SUPPLEMENTARY_SURFACE_LABELS.get(
        surface,
        re.sub(r"[._-]+", " ", surface).title(),
    )
    return f"{surface_label} · {author_label}"


def _supplementary_document(part_id: str, evidence) -> dict:
    encoded_part = quote(part_id, safe="")
    encoded_manifest = quote(evidence.manifest_digest, safe="")
    artifacts = [
        {
            "id": artifact.artifact_digest,
            "fileName": artifact.suggested_name,
            "sizeBytes": artifact.size_bytes,
            "mediaType": "application/octet-stream",
            "evidenceDigest": artifact.artifact_digest,
            "canActivate": False,
            "downloadUrl": (
                f"/api/library/parts/{encoded_part}/cad-variants/supplementary/"
                f"{encoded_manifest}/{quote(artifact.artifact_digest, safe='')}/"
                f"{quote(artifact.suggested_name, safe='')}"
            ),
        }
        for artifact in evidence.artifacts
    ]
    return {
        "id": evidence.manifest_digest,
        "provider": _supplementary_provider_label(
            evidence.surface_key,
            evidence.provider_key,
        ),
        "surface": _SUPPLEMENTARY_SURFACE_LABELS.get(
            evidence.surface_key,
            re.sub(r"[._-]+", " ", evidence.surface_key).title(),
        ),
        "adapterVersion": evidence.adapter_version,
        "evidenceDigest": evidence.manifest_digest,
        "canActivate": False,
        "artifacts": artifacts,
    }


def _active_variant_id(record: PartRecord, tool: str) -> str | None:
    pointer = record.cad_variants.selection_for(tool)
    return pointer.variant_key if pointer is not None else None


def _altium_accepts_kicad(altium_pointer, kicad_manifest: str) -> bool:
    """Whether native Altium was validated against this exact KiCad bundle.

    A same-manifest bundle can carry both formats directly. A composed Altium manifest instead
    names the exact KiCad evidence it was cross-EDA checked against in ``source_manifests``.
    """
    return (
        altium_pointer.manifest_digest == kicad_manifest
        or kicad_manifest in altium_pointer.source_manifests
    )


def _inventory_document(ctx, part_id: str, store: EvidenceStore | None = None) -> dict:
    record = ctx.ops.load_record(part_id)
    # Identity-less reference parts cannot have exact retained evidence yet.  An empty inventory
    # is useful UI state; activation remains impossible until identity is authoritative.
    identity = None
    if record.manufacturer and record.mpn:
        identity = exact_identity(record)
    evidence = store or _store()
    inventories = []
    for tool in _TOOLS:
        descriptors = (
            list_cad_variants(evidence, identity=identity, tool=tool)
            if identity is not None
            else ()
        )
        inventories.append(
            {
                "tool": tool,
                "activeVariantId": _active_variant_id(record, tool),
                "variants": [_descriptor_document(item) for item in descriptors],
            }
        )
    supplementary = (
        evidence.list_supplementary_artifacts(identity=identity)
        if identity is not None
        else ()
    )
    return {
        "partId": part_id,
        "inventories": inventories,
        "supplementary": [
            _supplementary_document(part_id, item) for item in supplementary
        ],
    }


def _supplementary_download(
    ctx,
    part_id: str,
    manifest_digest: str,
    artifact_digest: str,
    file_name: str,
    store: EvidenceStore | None = None,
) -> FileResponse:
    record = ctx.ops.load_record(part_id)
    if not record.manufacturer or not record.mpn:
        raise ApiError(404, "the requested supplementary artifact is not retained")
    identity = exact_identity(record)
    evidence = store or _store()
    manifest = next(
        (
            item
            for item in evidence.list_supplementary_artifacts(identity=identity)
            if item.manifest_digest == manifest_digest
        ),
        None,
    )
    artifact = (
        next(
            (
                item
                for item in manifest.artifacts
                if item.artifact_digest == artifact_digest
                and item.suggested_name == file_name
            ),
            None,
        )
        if manifest is not None
        else None
    )
    if artifact is None:
        raise ApiError(404, "the requested supplementary artifact is not retained")
    return FileResponse(
        artifact.path,
        media_type="application/octet-stream",
        filename=artifact.suggested_name,
    )


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
    # Installed-readback evidence deliberately retains the whole category library.  Its stable
    # record binding is stronger than heuristics against the MPN and makes reactivation exact even
    # when the entry was human-named and the library contains hundreds of neighbours.
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


def _materialize_kicad(ctx, record: PartRecord, resolved) -> PartRecord:
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


def _materialize_altium(ctx, record: PartRecord, resolved) -> PartRecord:
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


def _activate(ctx, part_id: str, body: ActivateCadVariantBody, store: EvidenceStore) -> None:
    # Compare and the nested materializer Transaction share this repository-wide re-entrant lock.
    # No second activation can advance the record between the expected-value check and commit.
    with ctx.repo._write_lock():
        record = ctx.ops.load_record(part_id)
        current = _active_variant_id(record, body.tool)
        if current != body.expected_active_variant_id:
            raise ApiError(
                409,
                "the active CAD variant changed; refresh the inventory before switching",
            )
        identity = exact_identity(record)
        descriptors = list_cad_variants(store, identity=identity, tool=body.tool)
        selected = next(
            (item for item in descriptors if item.variant_key == body.variant_id),
            None,
        )
        if selected is None:
            raise ApiError(404, "the requested complete validated CAD variant is not retained")
        active_kicad = record.cad_variants.selection_for("kicad")
        active_altium = record.cad_variants.selection_for("altium")
        if body.tool == "altium":
            if active_kicad is None:
                raise ApiError(
                    409,
                    "select the compatible KiCad bundle before activating this Altium bundle",
                )
            if not _altium_accepts_kicad(
                selected.pointer(),
                active_kicad.manifest_digest,
            ):
                raise ApiError(
                    409,
                    "this Altium bundle was validated against a different active KiCad bundle",
                )
        if (
            body.tool == "kicad"
            and active_altium is not None
            and not _altium_accepts_kicad(active_altium, selected.manifest_digest)
        ):
            raise ApiError(
                409,
                "the active Altium bundle was validated against a different KiCad bundle",
            )
        resolved = resolve_cad_variant(
            store,
            identity=identity,
            tool=body.tool,
            manifest_digest=selected.manifest_digest,
        )
        if body.tool == "kicad":
            _materialize_kicad(ctx, record, resolved)
        else:
            _materialize_altium(ctx, record, resolved)


def cad_variants_router(require_token) -> APIRouter:
    router = APIRouter(
        prefix="/api/library/parts",
        dependencies=[Depends(require_token)],
    )

    @router.get("/{part_id}/cad-variants")
    def inventory(request: Request, part_id: str) -> dict:
        return _inventory_document(request.app.state.ctx, part_id)

    @router.get(
        "/{part_id}/cad-variants/supplementary/"
        "{manifest_digest}/{artifact_digest}/{file_name}"
    )
    def supplementary_download(
        request: Request,
        part_id: str,
        manifest_digest: str,
        artifact_digest: str,
        file_name: str,
    ) -> FileResponse:
        return _supplementary_download(
            request.app.state.ctx,
            part_id,
            manifest_digest,
            artifact_digest,
            file_name,
        )

    @router.post("/{part_id}/cad-variants/activate")
    def activate(request: Request, part_id: str, body: ActivateCadVariantBody) -> dict:
        ctx = request.app.state.ctx
        store = _store()
        _activate(ctx, part_id, body, store)
        ctx.rebuild_index()
        ctx.auto_push()
        return _inventory_document(ctx, part_id, store)

    return router


__all__ = ["ActivateCadVariantBody", "cad_variants_router"]
