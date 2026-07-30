"""Deterministic source-contract proof for the representative passive profile.

The proof renders both adapter inputs without starting either EDA.  It is useful
for schema and source drift checks, but its explicit boundary prevents it from
being promoted to native readback or publication readiness evidence.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from stockroom.altium.native_authoring import render_native_authoring_script
from stockroom.domain import CanonicalPassiveBundle
from stockroom.eda.passive_projection import render_kicad_template_source_plan
from stockroom.templates import representative_passive_template
from stockroom.workflow.identifiers import digest_text, parse_sha256
from stockroom.workflow.model import canonical_json

SchemaVersion = Literal[1]
NonBlankText = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False)]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ToolKey = Literal["kicad", "altium"]
SourceKind = Literal["kicad_projection_plan", "altium_delphiscript"]

_LIMITATIONS = (
    "KiCad source was rendered but KiCad native execution and readback were not run.",
    "Altium source was rendered but Altium native execution and readback were not run.",
    "Source-contract proof is not component publication readiness evidence.",
)


class _ProofModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AdapterSourceEvidence(_ProofModel):
    schema_version: SchemaVersion = 1
    tool: ToolKey
    adapter_revision: NonBlankText
    source_kind: SourceKind
    binding_digest: Sha256Digest
    source_digest: Sha256Digest
    source_size_bytes: int = Field(gt=0)

    @field_validator("adapter_revision")
    @classmethod
    def validate_adapter_revision(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("adapter_revision must have no surrounding whitespace")
        return value

    @field_validator("binding_digest", "source_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        parse_sha256(value, "source proof digest")
        return value


class PassiveTemplateSourceProof(_ProofModel):
    """A stable, explicitly non-native proof of both adapter source seams."""

    schema_version: SchemaVersion = 1
    proof_scope: Literal["adapter_source_contract"] = "adapter_source_contract"
    component_id: NonBlankText
    canonical_bundle_digest: Sha256Digest
    template_profile_id: NonBlankText
    template_profile_digest: Sha256Digest
    adapters: tuple[AdapterSourceEvidence, AdapterSourceEvidence]
    native_execution: Literal["not_run"] = "not_run"
    limitations: tuple[str, str, str] = _LIMITATIONS

    @field_validator("canonical_bundle_digest", "template_profile_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        parse_sha256(value, "source proof digest")
        return value

    @model_validator(mode="after")
    def validate_dual_eda_boundary(self) -> Self:
        if tuple(adapter.tool for adapter in self.adapters) != ("kicad", "altium"):
            raise ValueError("source proof requires KiCad then Altium adapter evidence")
        if tuple(adapter.source_kind for adapter in self.adapters) != (
            "kicad_projection_plan",
            "altium_delphiscript",
        ):
            raise ValueError("source proof adapter evidence has the wrong source kind")
        if self.limitations != _LIMITATIONS:
            raise ValueError("source proof limitations cannot be weakened")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.model_dump(mode="json")).encode("utf-8") + b"\n"

    def canonical_digest(self) -> str:
        return digest_text(hashlib.sha256(self.canonical_bytes()).digest())


def _digest(data: bytes) -> str:
    return digest_text(hashlib.sha256(data).digest())


def _binding_digest(tool: ToolKey) -> str:
    profile = representative_passive_template()
    binding = profile.binding_for(tool)
    payload = canonical_json(binding.model_dump(mode="json")).encode("utf-8") + b"\n"
    return _digest(payload)


def build_passive_template_source_proof(
    bundle: CanonicalPassiveBundle,
) -> PassiveTemplateSourceProof:
    """Render and bind both source adapters without claiming native success."""

    if not isinstance(bundle, CanonicalPassiveBundle):
        raise TypeError("bundle must be a CanonicalPassiveBundle")
    checked = CanonicalPassiveBundle.model_validate(bundle.model_dump(mode="python"))
    profile = representative_passive_template()
    kicad_source = render_kicad_template_source_plan(checked)
    altium_source = render_native_authoring_script(
        checked,
        schlib_win=r"C:\Stockroom Source Proof\Component.SchLib",
        pcblib_win=r"C:\Stockroom Source Proof\Component.PcbLib",
        step_win=r"C:\Stockroom Source Proof\Component.step",
        marker_win=r"C:\Stockroom Source Proof\Semantic Readback.json",
        procedure="SRPassiveTemplateSourceProof",
    ).encode("utf-8")
    return PassiveTemplateSourceProof(
        component_id=checked.identity.component_id,
        canonical_bundle_digest=checked.canonical_digest(),
        template_profile_id=profile.profile_id,
        template_profile_digest=profile.canonical_digest(),
        adapters=(
            AdapterSourceEvidence(
                tool="kicad",
                adapter_revision=profile.binding_for("kicad").adapter_revision,
                source_kind="kicad_projection_plan",
                binding_digest=_binding_digest("kicad"),
                source_digest=_digest(kicad_source),
                source_size_bytes=len(kicad_source),
            ),
            AdapterSourceEvidence(
                tool="altium",
                adapter_revision=profile.binding_for("altium").adapter_revision,
                source_kind="altium_delphiscript",
                binding_digest=_binding_digest("altium"),
                source_digest=_digest(altium_source),
                source_size_bytes=len(altium_source),
            ),
        ),
    )
