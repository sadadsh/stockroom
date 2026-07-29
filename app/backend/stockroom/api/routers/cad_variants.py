"""Authenticated inventory and atomic pair activation for retained CAD bundles.

Evidence is immutable and machine-local. Every retained provider variant remains inspectable, but
only one exact same-provider, same-download KiCad and Altium pair can be activated. Pair activation
reverifies both projections, installs every required role, and persists both pointers in one Git
Transaction. The legacy single-tool route remains only to fail closed for older clients.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from stockroom.api.errors import ApiError
from stockroom.cad_materialization import materialize_pair
from stockroom.cad_variants import (
    CadVariantDescriptor,
    list_cad_variants,
    resolve_cad_variant,
    same_cad_evidence_set,
)
from stockroom.capture.evidence import exact_identity
from stockroom.capture.runner import capture_state_root
from stockroom.evidence import EvidenceStore
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


class ActivateCadPairBody(BaseModel):
    """A stale-safe request to switch one cross-EDA-proved pair atomically."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kicad_variant_id: str = Field(
        alias="kicadVariantId",
        pattern=r"sha256:[0-9a-f]{64}",
    )
    altium_variant_id: str = Field(
        alias="altiumVariantId",
        pattern=r"sha256:[0-9a-f]{64}",
    )
    expected_active_kicad_variant_id: str | None = Field(
        alias="expectedActiveKicadVariantId",
        pattern=r"sha256:[0-9a-f]{64}",
    )
    expected_active_altium_variant_id: str | None = Field(
        alias="expectedActiveAltiumVariantId",
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
    provider, trust_rank, trust_label, trust_reason = _provider_presentation(descriptor.provider)
    return {
        "id": descriptor.variant_key,
        "provider": provider,
        "format": ("KiCad Native" if descriptor.tool == "kicad" else "Altium Designer (Native)"),
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


def _pair_document(
    kicad: CadVariantDescriptor,
    altium: CadVariantDescriptor,
) -> dict:
    kicad_provider, kicad_rank, _, _ = _provider_presentation(kicad.provider)
    altium_provider, altium_rank, _, _ = _provider_presentation(altium.provider)
    if kicad_provider != altium_provider:
        raise ValueError("one CAD evidence set cannot have two provider identities")
    return {
        "kicadVariantId": kicad.variant_key,
        "altiumVariantId": altium.variant_key,
        "provider": kicad_provider,
        "trustRank": max(kicad_rank, altium_rank),
        "trustLabel": "Same-Download Validated Pair",
        "trustReason": (
            "KiCad and Altium were projected from the exact same immutable provider "
            "manifest, adapter, operation, and source closure."
        ),
    }


def _inventory_document(ctx, part_id: str, store: EvidenceStore | None = None) -> dict:
    record = ctx.ops.load_record(part_id)
    # Identity-less reference parts cannot have exact retained evidence yet.  An empty inventory
    # is useful UI state; activation remains impossible until identity is authoritative.
    identity = None
    if record.manufacturer and record.mpn:
        identity = exact_identity(record)
    evidence = store or _store()
    inventories = []
    descriptors_by_tool: dict[str, tuple[CadVariantDescriptor, ...]] = {}
    for tool in _TOOLS:
        descriptors = (
            list_cad_variants(evidence, identity=identity, tool=tool)
            if identity is not None
            else ()
        )
        descriptors_by_tool[tool] = tuple(descriptors)
        inventories.append(
            {
                "tool": tool,
                "activeVariantId": _active_variant_id(record, tool),
                "variants": [_descriptor_document(item) for item in descriptors],
            }
        )
    supplementary = (
        evidence.list_supplementary_artifacts(identity=identity) if identity is not None else ()
    )
    return {
        "partId": part_id,
        "inventories": inventories,
        "pairs": [
            _pair_document(kicad, altium)
            for kicad in descriptors_by_tool["kicad"]
            for altium in descriptors_by_tool["altium"]
            if same_cad_evidence_set(kicad, altium)
        ],
        "supplementary": [_supplementary_document(part_id, item) for item in supplementary],
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
                if item.artifact_digest == artifact_digest and item.suggested_name == file_name
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


def _activate_pair(
    ctx,
    part_id: str,
    body: ActivateCadPairBody,
    store: EvidenceStore,
) -> None:
    """Compare both pointers and install one compatible pair without an invalid midpoint."""

    with ctx.repo._write_lock():
        record = ctx.ops.load_record(part_id)
        current_kicad = _active_variant_id(record, "kicad")
        current_altium = _active_variant_id(record, "altium")
        if (
            current_kicad != body.expected_active_kicad_variant_id
            or current_altium != body.expected_active_altium_variant_id
        ):
            raise ApiError(
                409,
                "the active CAD pair changed; refresh the inventory before switching",
            )

        identity = exact_identity(record)
        kicad_descriptors = list_cad_variants(
            store,
            identity=identity,
            tool="kicad",
        )
        altium_descriptors = list_cad_variants(
            store,
            identity=identity,
            tool="altium",
        )
        selected_kicad = next(
            (item for item in kicad_descriptors if item.variant_key == body.kicad_variant_id),
            None,
        )
        selected_altium = next(
            (item for item in altium_descriptors if item.variant_key == body.altium_variant_id),
            None,
        )
        if selected_kicad is None or selected_altium is None:
            raise ApiError(404, "the requested validated CAD pair is not retained")
        if not same_cad_evidence_set(selected_kicad, selected_altium):
            raise ApiError(
                409,
                "the requested KiCad and Altium variants do not share one exact "
                "provider download evidence set",
            )

        resolved_kicad = resolve_cad_variant(
            store,
            identity=identity,
            tool="kicad",
            manifest_digest=selected_kicad.manifest_digest,
        )
        resolved_altium = resolve_cad_variant(
            store,
            identity=identity,
            tool="altium",
            manifest_digest=selected_altium.manifest_digest,
        )
        materialize_pair(ctx, record, resolved_kicad, resolved_altium)


def cad_variants_router(require_token) -> APIRouter:
    router = APIRouter(
        prefix="/api/library/parts",
        dependencies=[Depends(require_token)],
    )

    @router.get("/{part_id}/cad-variants")
    def inventory(request: Request, part_id: str) -> dict:
        return _inventory_document(request.app.state.ctx, part_id)

    @router.get(
        "/{part_id}/cad-variants/supplementary/{manifest_digest}/{artifact_digest}/{file_name}"
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
        del request, part_id, body
        raise ApiError(
            409,
            "single-tool CAD activation is disabled; choose one retained same-source "
            "KiCad and Altium pair",
        )

    @router.post("/{part_id}/cad-variants/activate-pair")
    def activate_pair(
        request: Request,
        part_id: str,
        body: ActivateCadPairBody,
    ) -> dict:
        ctx = request.app.state.ctx
        store = _store()
        _activate_pair(ctx, part_id, body, store)
        ctx.rebuild_index()
        ctx.auto_push()
        return _inventory_document(ctx, part_id, store)

    return router


__all__ = [
    "ActivateCadPairBody",
    "ActivateCadVariantBody",
    "cad_variants_router",
]
