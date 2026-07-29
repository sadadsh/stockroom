"""Durable pointers from materialized CAD bundles to immutable evidence variants.

The bytes live in :class:`stockroom.evidence.EvidenceStore`.  A part record stores one active
bundle pointer per EDA tool.  Keeping that pointer separate from ``PartRecord.assets`` is
deliberate:

* the evidence CAS and its role index preserve every validated provider bundle;
* this model records which coherent bundle the owner selected;
* ``assets`` remains the materialized projection that KiCad or Altium opens.

Selection is bundle-shaped, never independent per role.  Allowing a UL symbol to be combined
with a SnapMagic footprint or model would discard the cross-role validation that made either
download trustworthy.  A materializer must reverify the entire pointer, write every projection,
and persist the pointer in one transaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from stockroom.eda.registry import get_tool

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROVIDER_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_TECHNICAL_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")

# Logical EDA asset kind -> immutable evidence role.  This is the selection-coherence registry:
# every role in one row must come from one manifest.  Altium has no independently selectable
# model role; its 3D body is embedded and verified with the native PcbLib, not a second STEP
# pointer that could diverge from the footprint.
CAD_VARIANT_ROLE_MAP: dict[str, dict[str, str]] = {
    "kicad": {
        "symbol": "symbol",
        "footprint": "footprint",
        "model": "model",
    },
    "altium": {
        "symbol": "altium_symbol",
        "footprint": "altium_footprint",
    },
}


def _canonical_text(value: object, *, name: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"{name} is not canonical")
    return value


@dataclass(frozen=True, slots=True)
class CadVariantArtifactPointer:
    """One logical asset role and its exact immutable bytes inside a bundle manifest."""

    artifact_digest: str
    evidence_role: str
    extra: dict = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        _canonical_text(self.artifact_digest, name="artifact digest", pattern=_DIGEST)
        _canonical_text(self.evidence_role, name="evidence role", pattern=_TECHNICAL_KEY)
        if type(self.extra) is not dict:
            raise ValueError("CAD variant artifact pointer extra fields must be an object")
        object.__setattr__(self, "extra", dict(self.extra))

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "artifact_digest": self.artifact_digest,
            "evidence_role": self.evidence_role,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "CadVariantArtifactPointer":
        if type(value) is not dict:
            raise ValueError("CAD variant artifact pointer must be an object")
        known = {"artifact_digest", "evidence_role"}
        return cls(
            artifact_digest=value.get("artifact_digest", ""),
            evidence_role=value.get("evidence_role", ""),
            extra={key: item for key, item in value.items() if key not in known},
        )


@dataclass(frozen=True, slots=True)
class CadVariantPointer:
    """One coherent, digest-bound active bundle for an EDA tool."""

    manifest_digest: str
    provider: str
    artifacts: dict[str, CadVariantArtifactPointer]
    source_manifests: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        _canonical_text(self.manifest_digest, name="manifest digest", pattern=_DIGEST)
        _canonical_text(self.provider, name="provider key", pattern=_PROVIDER_KEY)
        if type(self.artifacts) is not dict or not self.artifacts:
            raise ValueError("CAD variant bundle artifacts must be a non-empty object")
        normalized: dict[str, CadVariantArtifactPointer] = {}
        evidence_roles: set[str] = set()
        for asset_kind, pointer in self.artifacts.items():
            _canonical_text(asset_kind, name="CAD variant asset kind", pattern=_TECHNICAL_KEY)
            if not isinstance(pointer, CadVariantArtifactPointer):
                raise ValueError("CAD variant bundle artifact must be a CadVariantArtifactPointer")
            if pointer.evidence_role in evidence_roles:
                raise ValueError("CAD variant bundle evidence roles must be unique")
            evidence_roles.add(pointer.evidence_role)
            normalized[asset_kind] = pointer
        if (
            type(self.source_manifests) is not tuple
            or tuple(sorted(set(self.source_manifests))) != self.source_manifests
            or any(
                type(digest) is not str or _DIGEST.fullmatch(digest) is None
                for digest in self.source_manifests
            )
        ):
            raise ValueError("CAD variant source manifests must be unique canonical digests")
        if self.manifest_digest in self.source_manifests:
            raise ValueError("CAD variant bundle cannot name itself as a source manifest")
        if type(self.extra) is not dict:
            raise ValueError("CAD variant pointer extra fields must be an object")
        object.__setattr__(self, "artifacts", normalized)
        object.__setattr__(self, "extra", dict(self.extra))

    @property
    def variant_key(self) -> str:
        """Stable UI/API identity for this exact validated bundle."""
        return self.manifest_digest

    def artifact_for(self, asset_kind: str) -> CadVariantArtifactPointer | None:
        return self.artifacts.get(asset_kind)

    def validate_for_tool(self, tool: str) -> None:
        try:
            expected = CAD_VARIANT_ROLE_MAP[tool]
        except KeyError:
            raise KeyError(f"no coherent CAD variant bundle is registered for {tool!r}") from None
        observed = {
            asset_kind: pointer.evidence_role for asset_kind, pointer in self.artifacts.items()
        }
        if observed != expected:
            raise ValueError(
                f"{tool} CAD variant bundle roles must be {expected!r}, got {observed!r}"
            )

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "manifest_digest": self.manifest_digest,
            "provider": self.provider,
            "artifacts": {
                asset_kind: pointer.to_dict() for asset_kind, pointer in self.artifacts.items()
            },
            "source_manifests": list(self.source_manifests),
        }

    @classmethod
    def from_dict(cls, value: dict) -> "CadVariantPointer":
        if type(value) is not dict:
            raise ValueError("CAD variant pointer must be an object")
        raw_artifacts = value.get("artifacts") or {}
        if type(raw_artifacts) is not dict:
            raise ValueError("CAD variant bundle artifacts must be an object")
        raw_sources = value.get("source_manifests") or []
        if type(raw_sources) is not list:
            raise ValueError("CAD variant source manifests must be a list")
        known = {"manifest_digest", "provider", "artifacts", "source_manifests"}
        return cls(
            manifest_digest=value.get("manifest_digest", ""),
            provider=value.get("provider", ""),
            artifacts={
                asset_kind: CadVariantArtifactPointer.from_dict(pointer)
                for asset_kind, pointer in raw_artifacts.items()
            },
            source_manifests=tuple(raw_sources),
            extra={key: item for key, item in value.items() if key not in known},
        )


@dataclass
class CadVariantSelections:
    """One active coherent bundle pointer per EDA tool.

    Unknown future tools and pointer fields are preserved on read so an older peer cannot erase
    them while editing unrelated metadata.  This build can only make a new selection for a tool
    registered in ``CAD_VARIANT_ROLE_MAP``.
    """

    active: dict[str, CadVariantPointer] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.active) is not dict or type(self.extra) is not dict:
            raise ValueError("CAD variant selections must be objects")
        normalized: dict[str, CadVariantPointer] = {}
        for tool, pointer in self.active.items():
            _canonical_text(tool, name="CAD variant tool", pattern=_TECHNICAL_KEY)
            if not isinstance(pointer, CadVariantPointer):
                raise ValueError("CAD variant selection must be a CadVariantPointer")
            # Known tools are strict.  Unknown future tools are preserved but cannot be newly
            # selected through `select`, because this build does not understand their bundle.
            if tool in CAD_VARIANT_ROLE_MAP:
                pointer.validate_for_tool(tool)
            normalized[tool] = pointer
        self.active = normalized
        self.extra = dict(self.extra)

    def selection_for(self, tool: str) -> CadVariantPointer | None:
        return self.active.get(tool)

    def select(self, tool: str, pointer: CadVariantPointer) -> None:
        """Set one verified whole-tool bundle without touching evidence or projections."""
        get_tool(tool)
        if not isinstance(pointer, CadVariantPointer):
            raise TypeError("CAD variant selection must be a CadVariantPointer")
        pointer.validate_for_tool(tool)
        self.active[tool] = pointer

    def clear(self, tool: str) -> CadVariantPointer:
        """Clear only the active pointer; immutable bundles remain in evidence storage."""
        spec = get_tool(tool)
        try:
            return self.active.pop(tool)
        except KeyError:
            raise KeyError(f"{spec.label} has no active CAD variant") from None

    def is_empty(self) -> bool:
        return not self.active and not self.extra

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "active": {tool: pointer.to_dict() for tool, pointer in self.active.items()},
        }

    @classmethod
    def from_dict(cls, value: dict) -> "CadVariantSelections":
        if type(value) is not dict:
            raise ValueError("CAD variant selections must be an object")
        raw_active = value.get("active") or {}
        if type(raw_active) is not dict:
            raise ValueError("CAD variant active selections must be an object")
        return cls(
            active={
                tool: CadVariantPointer.from_dict(pointer) for tool, pointer in raw_active.items()
            },
            extra={key: item for key, item in value.items() if key != "active"},
        )


__all__ = [
    "CAD_VARIANT_ROLE_MAP",
    "CadVariantArtifactPointer",
    "CadVariantPointer",
    "CadVariantSelections",
]
