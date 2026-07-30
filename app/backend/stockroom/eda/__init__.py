"""Tool-agnostic EDA registry and isolated native projection APIs.

Projection modules are loaded lazily. Eagerly importing them here makes the
ordinary ``stockroom.eda.registry`` import recurse through mutation placement
and the partially initialized part model.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ArtifactDigest",
    "AdapterSourceEvidence",
    "DualEdaProjectionResult",
    "EvidenceDigest",
    "KiCadLinkConflict",
    "KiCadLinkProjectionError",
    "ObservedPad",
    "ObservedPin",
    "PortableKiCadLinkProjection",
    "PortableLibraryRow",
    "PortableTableArtifact",
    "PassiveTemplateSourceProof",
    "ProjectionError",
    "ProjectionMismatch",
    "ToolBinding",
    "ToolProjection",
    "UnsupportedProjection",
    "project_passive_bundle",
    "project_portable_kicad_links",
    "build_passive_template_source_proof",
    "render_kicad_template_source_plan",
]

_KICAD_LINK_EXPORTS = {
    "KiCadLinkConflict",
    "KiCadLinkProjectionError",
    "PortableKiCadLinkProjection",
    "PortableLibraryRow",
    "PortableTableArtifact",
    "project_portable_kicad_links",
}
_TEMPLATE_PROOF_EXPORTS = {
    "AdapterSourceEvidence",
    "PassiveTemplateSourceProof",
    "build_passive_template_source_proof",
}
_PASSIVE_EXPORTS = set(__all__) - _KICAD_LINK_EXPORTS - _TEMPLATE_PROOF_EXPORTS


def __getattr__(name: str):
    if name in _KICAD_LINK_EXPORTS:
        return getattr(import_module(".kicad_links", __name__), name)
    if name in _TEMPLATE_PROOF_EXPORTS:
        return getattr(import_module(".passive_template_proof", __name__), name)
    if name in _PASSIVE_EXPORTS:
        return getattr(import_module(".passive_projection", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
