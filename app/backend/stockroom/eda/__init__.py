"""Tool-agnostic EDA registry and isolated native projection APIs."""

from .kicad_links import (
    KiCadLinkConflict,
    KiCadLinkProjectionError,
    PortableKiCadLinkProjection,
    PortableLibraryRow,
    PortableTableArtifact,
    project_portable_kicad_links,
)
from .passive_projection import (
    ArtifactDigest,
    DualEdaProjectionResult,
    EvidenceDigest,
    ObservedPad,
    ObservedPin,
    ProjectionError,
    ProjectionMismatch,
    ToolBinding,
    ToolProjection,
    UnsupportedProjection,
    project_passive_bundle,
)

__all__ = [
    "ArtifactDigest",
    "DualEdaProjectionResult",
    "EvidenceDigest",
    "KiCadLinkConflict",
    "KiCadLinkProjectionError",
    "ObservedPad",
    "ObservedPin",
    "PortableKiCadLinkProjection",
    "PortableLibraryRow",
    "PortableTableArtifact",
    "ProjectionError",
    "ProjectionMismatch",
    "ToolBinding",
    "ToolProjection",
    "UnsupportedProjection",
    "project_passive_bundle",
    "project_portable_kicad_links",
]
