"""List and resolve coherent immutable CAD bundles without materializing one.

This is the seam between the evidence CAS and a future transactional EDA materializer.  Listing
returns every complete validated bundle in evidence-store trust order.  Resolving a requested
manifest reverifies its exact identity, every required role, source-manifest closure, and bytes.
No function here downloads, writes a library file, changes a part record, or deletes evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from stockroom.evidence.store import (
    DEFAULT_CAD_PROVIDER_PREFERENCE,
    EvidenceManifestMismatch,
    ExactIdentity,
    VerifiedRoleArtifact,
)
from stockroom.model.cad_variant import (
    CAD_VARIANT_ROLE_MAP,
    CadVariantArtifactPointer,
    CadVariantPointer,
    CadVariantSelections,
)


class CadVariantEvidence(Protocol):
    def list_role_variants(
        self,
        *,
        identity: ExactIdentity,
        role: str,
        provider_preference: tuple[str, ...] = DEFAULT_CAD_PROVIDER_PREFERENCE,
    ) -> tuple[VerifiedRoleArtifact, ...]: ...

    def verified_role_artifacts(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
        roles: tuple[str, ...],
    ) -> dict[str, VerifiedRoleArtifact]: ...


class CadVariantResolutionError(ValueError):
    """Verified evidence did not satisfy one coherent EDA bundle."""


@dataclass(frozen=True, slots=True)
class CadVariantArtifactDescriptor:
    asset_kind: str
    evidence_role: str
    artifact_digest: str
    media_type: str
    suggested_name: str


@dataclass(frozen=True, slots=True)
class CadVariantDescriptor:
    """Metadata for one selectable whole-tool bundle, without copying its bytes."""

    tool: str
    manifest_digest: str
    provider: str
    adapter_version: str
    operation: str
    artifacts: tuple[CadVariantArtifactDescriptor, ...]
    source_manifests: tuple[str, ...] = ()

    def pointer(self) -> CadVariantPointer:
        return CadVariantPointer(
            manifest_digest=self.manifest_digest,
            provider=self.provider,
            artifacts={
                artifact.asset_kind: CadVariantArtifactPointer(
                    artifact_digest=artifact.artifact_digest,
                    evidence_role=artifact.evidence_role,
                )
                for artifact in self.artifacts
            },
            source_manifests=self.source_manifests,
        )

    @property
    def variant_key(self) -> str:
        return self.manifest_digest


@dataclass(frozen=True, slots=True)
class ResolvedCadVariant:
    """One reverified coherent bundle and its exact immutable bytes by logical role."""

    descriptor: CadVariantDescriptor
    data: dict[str, bytes]

    def __post_init__(self) -> None:
        expected = {artifact.asset_kind: artifact for artifact in self.descriptor.artifacts}
        if set(self.data) != set(expected):
            raise CadVariantResolutionError("resolved CAD bundle does not contain every role")
        for asset_kind, content in self.data.items():
            observed = f"sha256:{hashlib.sha256(content).hexdigest()}"
            if observed != expected[asset_kind].artifact_digest:
                raise CadVariantResolutionError(
                    f"CAD variant {asset_kind} bytes do not match the artifact digest"
                )
        object.__setattr__(self, "data", dict(self.data))

    @property
    def pointer(self) -> CadVariantPointer:
        return self.descriptor.pointer()


def cad_variant_roles(tool: str) -> dict[str, str]:
    try:
        return dict(CAD_VARIANT_ROLE_MAP[tool])
    except KeyError:
        raise KeyError(f"no coherent CAD variant bundle is registered for {tool!r}") from None


def _bundle_descriptor(
    artifacts: dict[str, VerifiedRoleArtifact],
    *,
    tool: str,
) -> CadVariantDescriptor:
    required = cad_variant_roles(tool)
    if set(artifacts) != set(required.values()):
        raise CadVariantResolutionError("evidence resolver did not return every bundle role")

    ordered: list[tuple[str, VerifiedRoleArtifact]] = []
    for asset_kind, evidence_role in required.items():
        try:
            artifact = artifacts[evidence_role]
        except KeyError:
            raise CadVariantResolutionError(
                f"evidence bundle is missing role {evidence_role!r}"
            ) from None
        if artifact.role != evidence_role:
            raise CadVariantResolutionError(
                f"evidence role {artifact.role!r} cannot satisfy "
                f"{tool}/{asset_kind}; expected {evidence_role!r}"
            )
        observed = f"sha256:{hashlib.sha256(artifact.data).hexdigest()}"
        if observed != artifact.artifact_digest:
            raise CadVariantResolutionError(
                f"CAD variant {asset_kind} bytes do not match the artifact digest"
            )
        ordered.append((asset_kind, artifact))

    first = ordered[0][1]
    if any(
        artifact.manifest_digest != first.manifest_digest
        or artifact.provider_key != first.provider_key
        or artifact.adapter_version != first.adapter_version
        or artifact.operation != first.operation
        or artifact.source_manifests != first.source_manifests
        for _, artifact in ordered[1:]
    ):
        raise CadVariantResolutionError("CAD bundle roles do not share one evidence manifest")

    return CadVariantDescriptor(
        tool=tool,
        manifest_digest=first.manifest_digest,
        provider=first.provider_key,
        adapter_version=first.adapter_version,
        operation=first.operation,
        artifacts=tuple(
            CadVariantArtifactDescriptor(
                asset_kind=asset_kind,
                evidence_role=artifact.role,
                artifact_digest=artifact.artifact_digest,
                media_type=artifact.media_type,
                suggested_name=artifact.suggested_name,
            )
            for asset_kind, artifact in ordered
        ),
        source_manifests=first.source_manifests,
    )


def list_cad_variants(
    store: CadVariantEvidence,
    *,
    identity: ExactIdentity,
    tool: str,
    provider_preference: tuple[str, ...] = DEFAULT_CAD_PROVIDER_PREFERENCE,
) -> tuple[CadVariantDescriptor, ...]:
    """Return all complete exact bundles in deterministic trust order.

    Partial role manifests remain preserved in evidence but are not selectable as a bundle.
    """
    required = cad_variant_roles(tool)
    evidence_roles = tuple(required.values())
    seed_role = evidence_roles[0]
    seeds = store.list_role_variants(
        identity=identity,
        role=seed_role,
        provider_preference=provider_preference,
    )
    bundles: list[CadVariantDescriptor] = []
    seen: set[str] = set()
    for seed in seeds:
        if seed.manifest_digest in seen:
            continue
        seen.add(seed.manifest_digest)
        try:
            artifacts = store.verified_role_artifacts(
                seed.manifest_digest,
                identity=identity,
                roles=evidence_roles,
            )
        except EvidenceManifestMismatch:
            continue
        bundles.append(_bundle_descriptor(artifacts, tool=tool))
    return tuple(bundles)


def resolve_cad_variant(
    store: CadVariantEvidence,
    *,
    identity: ExactIdentity,
    tool: str,
    manifest_digest: str,
) -> ResolvedCadVariant:
    """Reverify one chosen whole-tool manifest and return all bytes for materialization."""
    required = cad_variant_roles(tool)
    artifacts = store.verified_role_artifacts(
        manifest_digest,
        identity=identity,
        roles=tuple(required.values()),
    )
    descriptor = _bundle_descriptor(artifacts, tool=tool)
    if descriptor.manifest_digest != manifest_digest:
        raise CadVariantResolutionError("evidence resolver returned a different manifest")
    data = {
        artifact.asset_kind: artifacts[artifact.evidence_role].data
        for artifact in descriptor.artifacts
    }
    return ResolvedCadVariant(descriptor=descriptor, data=data)


def selection_matches(
    selections: CadVariantSelections,
    descriptor: CadVariantDescriptor,
) -> bool:
    """Whether a bundle descriptor is active for its EDA tool."""
    return selections.selection_for(descriptor.tool) == descriptor.pointer()


__all__ = [
    "CadVariantArtifactDescriptor",
    "CadVariantDescriptor",
    "CadVariantResolutionError",
    "ResolvedCadVariant",
    "cad_variant_roles",
    "list_cad_variants",
    "resolve_cad_variant",
    "selection_matches",
]
