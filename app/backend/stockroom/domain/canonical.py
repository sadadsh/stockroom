"""Minimal canonical vNext domain for a verified two-pin passive.

The models contain durable facts only. Runtime readiness, workflow state, and
publication state belong to the workflow ledger rather than canonical library
content.
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

from stockroom.templates import (
    PassiveTemplateTerminal,
    PassiveToolTemplateBinding,
    passive_template_definition,
)
from stockroom.workflow.identifiers import (
    authoritative_text,
    derive_component_identity,
    digest_text,
    parse_sha256,
)
from stockroom.workflow.model import canonical_json

SchemaVersion = Literal[1]
NonBlankText = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False)]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ToolKey = Literal["kicad", "altium"]
TerminalNumber = Literal["1", "2"]
TwoPinKind = Literal["resistor", "diode"]


class CanonicalModel(BaseModel):
    """Strict immutable base for canonical records."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def canonical_json_bytes(model: CanonicalModel) -> bytes:
    """Serialize one canonical model as stable UTF-8 JSON plus one final LF."""

    document = model.model_dump(mode="json")
    return canonical_json(document).encode("utf-8") + b"\n"


def canonical_model_digest(model: CanonicalModel) -> str:
    """Return the SHA-256 digest of the exact canonical bytes."""

    return digest_text(hashlib.sha256(canonical_json_bytes(model)).digest())


def _validate_digest(value: str) -> str:
    parse_sha256(value, "digest")
    return value


def _validate_authoritative(value: str, field_name: str) -> str:
    return authoritative_text(value, field_name)


class Manufacturer(CanonicalModel):
    schema_version: SchemaVersion = 1
    manufacturer_id: NonBlankText
    manufacturer_digest: Sha256Digest
    authoritative_key: NonBlankText

    @field_validator("authoritative_key")
    @classmethod
    def validate_authoritative_key(cls, value: str) -> str:
        return _validate_authoritative(value, "authoritative_key")

    @field_validator("manufacturer_digest")
    @classmethod
    def validate_manufacturer_digest(cls, value: str) -> str:
        return _validate_digest(value)

    @model_validator(mode="after")
    def validate_derived_identity(self) -> Self:
        derived = derive_component_identity(self.authoritative_key, "_identity_probe_")
        if self.manufacturer_id != derived.manufacturer_id:
            raise ValueError("manufacturer_id does not match authoritative_key")
        if self.manufacturer_digest != digest_text(derived.manufacturer_digest):
            raise ValueError("manufacturer_digest does not match authoritative_key")
        return self

    @classmethod
    def from_exact_key(cls, authoritative_key: str) -> Self:
        exact_key = _validate_authoritative(authoritative_key, "authoritative_key")
        derived = derive_component_identity(exact_key, "_identity_probe_")
        return cls(
            manufacturer_id=derived.manufacturer_id,
            manufacturer_digest=digest_text(derived.manufacturer_digest),
            authoritative_key=exact_key,
        )


class ComponentIdentity(CanonicalModel):
    schema_version: SchemaVersion = 1
    component_id: NonBlankText
    identity_digest: Sha256Digest
    manufacturer_id: NonBlankText
    mpn_canonical: NonBlankText

    @field_validator("mpn_canonical")
    @classmethod
    def validate_mpn(cls, value: str) -> str:
        return _validate_authoritative(value, "mpn_canonical")

    @field_validator("identity_digest")
    @classmethod
    def validate_identity_digest(cls, value: str) -> str:
        return _validate_digest(value)

    @classmethod
    def from_exact_identity(
        cls,
        authoritative_manufacturer_key: str,
        mpn_canonical: str,
    ) -> Self:
        manufacturer_key = _validate_authoritative(
            authoritative_manufacturer_key,
            "authoritative_manufacturer_key",
        )
        exact_mpn = _validate_authoritative(mpn_canonical, "mpn_canonical")
        derived = derive_component_identity(manufacturer_key, exact_mpn)
        return cls(
            component_id=derived.component_id,
            identity_digest=digest_text(derived.component_digest),
            manufacturer_id=derived.manufacturer_id,
            mpn_canonical=exact_mpn,
        )

    def validate_against(self, manufacturer: Manufacturer) -> None:
        derived = derive_component_identity(
            manufacturer.authoritative_key,
            self.mpn_canonical,
        )
        if (
            self.manufacturer_id != manufacturer.manufacturer_id
            or self.component_id != derived.component_id
            or self.identity_digest != digest_text(derived.component_digest)
        ):
            raise ValueError("component identity does not match manufacturer and MPN")


class AuthoritativeEvidence(CanonicalModel):
    schema_version: SchemaVersion = 1
    source_kind: Literal[
        "manufacturer_datasheet",
        "manufacturer_catalog",
        "qualified_fixture",
    ]
    source_locator: NonBlankText
    content_digest: Sha256Digest

    @field_validator("source_locator")
    @classmethod
    def validate_locator(cls, value: str) -> str:
        return _validate_authoritative(value, "source_locator")

    @field_validator("content_digest")
    @classmethod
    def validate_content_digest(cls, value: str) -> str:
        return _validate_digest(value)


class SelectedClaim(CanonicalModel):
    schema_version: SchemaVersion = 1
    key: Literal["value", "package"]
    value: NonBlankText
    evidence: AuthoritativeEvidence
    selection_rule_revision: Literal["authoritative-exact-v1"] = "authoritative-exact-v1"

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        return _validate_authoritative(value, "claim value")


class PointNm(CanonicalModel):
    schema_version: SchemaVersion = 1
    x_nm: int
    y_nm: int


class BodyRectangleNm(CanonicalModel):
    schema_version: SchemaVersion = 1
    min_x_nm: int
    min_y_nm: int
    max_x_nm: int
    max_y_nm: int

    @model_validator(mode="after")
    def validate_extent(self) -> Self:
        if self.min_x_nm >= self.max_x_nm or self.min_y_nm >= self.max_y_nm:
            raise ValueError("body rectangle must have positive integer-nm area")
        return self


class PassiveTerminal(CanonicalModel):
    schema_version: SchemaVersion = 1
    number: TerminalNumber
    role: Literal["terminal", "cathode", "anode"]
    position: PointNm
    rotation_udeg: int = Field(ge=0, lt=360_000_000)
    electrical_type: Literal["passive"] = "passive"


class ToolNeutralDefinition(CanonicalModel):
    schema_version: SchemaVersion = 1
    component_id: NonBlankText
    definition_kind: Literal["two_pin_passive"] = "two_pin_passive"
    functional_kind: TwoPinKind
    geometry_unit: Literal["nm"] = "nm"
    angle_unit: Literal["udeg"] = "udeg"
    body: BodyRectangleNm
    terminals: tuple[PassiveTerminal, PassiveTerminal]

    @model_validator(mode="after")
    def validate_two_terminal_geometry(self) -> Self:
        if tuple(terminal.number for terminal in self.terminals) != ("1", "2"):
            raise ValueError("two-pin passive terminals must be exactly ('1', '2')")
        if self.terminals[0].position == self.terminals[1].position:
            raise ValueError("two-pin passive terminals must occupy distinct points")
        roles = tuple(terminal.role for terminal in self.terminals)
        expected_roles = (
            ("cathode", "anode") if self.functional_kind == "diode" else ("terminal", "terminal")
        )
        if roles != expected_roles:
            raise ValueError(f"{self.functional_kind} terminal roles must be {expected_roles!r}")
        return self


class SharedTemplate(CanonicalModel):
    schema_version: SchemaVersion = 1
    template_id: NonBlankText
    kind: Literal["symbol", "footprint"]
    contract_digest: Sha256Digest

    @field_validator("contract_digest")
    @classmethod
    def validate_contract_digest(cls, value: str) -> str:
        return _validate_digest(value)


class TerminalBinding(CanonicalModel):
    schema_version: SchemaVersion = 1
    canonical_terminal: TerminalNumber
    tool_terminal: NonBlankText

    @field_validator("tool_terminal")
    @classmethod
    def validate_tool_terminal(cls, value: str) -> str:
        return _validate_authoritative(value, "tool_terminal")


class ToolTemplateBinding(CanonicalModel):
    schema_version: SchemaVersion = 1
    tool: ToolKey
    symbol_template_id: NonBlankText
    footprint_template_id: NonBlankText
    terminal_bindings: tuple[TerminalBinding, TerminalBinding]

    @model_validator(mode="after")
    def validate_terminal_bindings(self) -> Self:
        canonical_terminals = tuple(
            binding.canonical_terminal for binding in self.terminal_bindings
        )
        if canonical_terminals != ("1", "2"):
            raise ValueError("tool binding must map canonical terminals 1 and 2 in order")
        tool_terminals = tuple(binding.tool_terminal for binding in self.terminal_bindings)
        if len(set(tool_terminals)) != 2:
            raise ValueError("tool terminal identifiers must be unique")
        return self


class ArtifactSet(CanonicalModel):
    schema_version: SchemaVersion = 1
    component_id: NonBlankText
    definition_digest: Sha256Digest
    shared_templates: tuple[SharedTemplate, SharedTemplate]
    tool_bindings: tuple[ToolTemplateBinding, ToolTemplateBinding]

    @field_validator("definition_digest")
    @classmethod
    def validate_definition_digest(cls, value: str) -> str:
        return _validate_digest(value)

    @model_validator(mode="after")
    def validate_shared_dual_eda_bindings(self) -> Self:
        if tuple(template.kind for template in self.shared_templates) != (
            "symbol",
            "footprint",
        ):
            raise ValueError("artifact set requires one symbol and one footprint template")
        if tuple(binding.tool for binding in self.tool_bindings) != (
            "kicad",
            "altium",
        ):
            raise ValueError("artifact set requires exactly KiCad and Altium bindings")
        symbol_id, footprint_id = (template.template_id for template in self.shared_templates)
        if any(
            binding.symbol_template_id != symbol_id or binding.footprint_template_id != footprint_id
            for binding in self.tool_bindings
        ):
            raise ValueError("both EDA tools must bind the same shared templates")
        return self


class Verification(CanonicalModel):
    schema_version: SchemaVersion = 1
    component_id: NonBlankText
    definition_digest: Sha256Digest
    artifact_set_digest: Sha256Digest
    claim_evidence_digests: tuple[Sha256Digest, Sha256Digest]
    observed_terminal_numbers: tuple[TerminalNumber, TerminalNumber]
    observed_tool_bindings: tuple[ToolKey, ToolKey]
    method_revision: Literal["two-pin-passive-static-v1"] = "two-pin-passive-static-v1"

    @field_validator(
        "definition_digest",
        "artifact_set_digest",
    )
    @classmethod
    def validate_link_digest(cls, value: str) -> str:
        return _validate_digest(value)

    @field_validator("claim_evidence_digests")
    @classmethod
    def validate_evidence_digests(
        cls,
        value: tuple[str, str],
    ) -> tuple[str, str]:
        for digest in value:
            _validate_digest(digest)
        return value

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        if self.observed_terminal_numbers != ("1", "2"):
            raise ValueError("verification must observe exactly terminals 1 and 2")
        if self.observed_tool_bindings != ("kicad", "altium"):
            raise ValueError("verification must observe KiCad and Altium bindings")
        return self


class CanonicalPassiveBundle(CanonicalModel):
    schema_version: SchemaVersion = 1
    manufacturer: Manufacturer
    identity: ComponentIdentity
    claims: tuple[SelectedClaim, SelectedClaim]
    definition: ToolNeutralDefinition
    artifacts: ArtifactSet
    verification: Verification

    @model_validator(mode="after")
    def validate_bundle_links(self) -> Self:
        self.identity.validate_against(self.manufacturer)
        if tuple(claim.key for claim in self.claims) != ("value", "package"):
            raise ValueError("passive bundle requires selected value and package claims")
        component_ids = {
            self.identity.component_id,
            self.definition.component_id,
            self.artifacts.component_id,
            self.verification.component_id,
        }
        if len(component_ids) != 1:
            raise ValueError("bundle records refer to different components")
        definition_digest = canonical_model_digest(self.definition)
        if (
            self.artifacts.definition_digest != definition_digest
            or self.verification.definition_digest != definition_digest
        ):
            raise ValueError("bundle definition digest link is invalid")
        if self.verification.artifact_set_digest != canonical_model_digest(self.artifacts):
            raise ValueError("bundle artifact-set digest link is invalid")
        evidence_digests = tuple(claim.evidence.content_digest for claim in self.claims)
        if self.verification.claim_evidence_digests != evidence_digests:
            raise ValueError("bundle claim evidence links are invalid")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self)

    def canonical_digest(self) -> str:
        return canonical_model_digest(self)


def _passive_terminal(
    terminal: PassiveTemplateTerminal,
) -> PassiveTerminal:
    return PassiveTerminal(
        number=terminal.number,
        role=terminal.role,
        position=PointNm(x_nm=terminal.x_nm, y_nm=terminal.y_nm),
        rotation_udeg=terminal.rotation_udeg,
        electrical_type=terminal.electrical_type,
    )


def _tool_template_binding(
    binding: PassiveToolTemplateBinding,
) -> ToolTemplateBinding:
    first, second = binding.terminal_bindings
    return ToolTemplateBinding(
        tool=binding.tool,
        symbol_template_id=binding.symbol_template_id,
        footprint_template_id=binding.footprint_template_id,
        terminal_bindings=(
            TerminalBinding(
                canonical_terminal=first.canonical_terminal,
                tool_terminal=first.tool_terminal,
            ),
            TerminalBinding(
                canonical_terminal=second.canonical_terminal,
                tool_terminal=second.tool_terminal,
            ),
        ),
    )


def build_two_pin_passive_bundle(
    *,
    authoritative_manufacturer_key: str,
    mpn_canonical: str,
    functional_kind: TwoPinKind,
    value: str,
    package: str,
    value_evidence: AuthoritativeEvidence,
    package_evidence: AuthoritativeEvidence,
) -> CanonicalPassiveBundle:
    """Build canonical facts for one supported shared-template two-pin profile."""

    exact_value = _validate_authoritative(value, "value")
    exact_package = _validate_authoritative(package, "package")
    profile = passive_template_definition(functional_kind, exact_package)
    symbol_template, footprint_template = profile.artifacts
    symbol_template_id = symbol_template.template_id
    footprint_template_id = footprint_template.template_id

    manufacturer = Manufacturer.from_exact_key(authoritative_manufacturer_key)
    identity = ComponentIdentity.from_exact_identity(
        manufacturer.authoritative_key,
        mpn_canonical,
    )
    claims = (
        SelectedClaim(key="value", value=exact_value, evidence=value_evidence),
        SelectedClaim(
            key="package",
            value=exact_package,
            evidence=package_evidence,
        ),
    )
    definition = ToolNeutralDefinition(
        component_id=identity.component_id,
        functional_kind=functional_kind,
        body=BodyRectangleNm(
            min_x_nm=profile.body_min_x_nm,
            min_y_nm=profile.body_min_y_nm,
            max_x_nm=profile.body_max_x_nm,
            max_y_nm=profile.body_max_y_nm,
        ),
        terminals=(
            _passive_terminal(profile.terminals[0]),
            _passive_terminal(profile.terminals[1]),
        ),
    )
    shared_templates = (
        SharedTemplate(
            template_id=symbol_template_id,
            kind="symbol",
            contract_digest=symbol_template.contract_digest,
        ),
        SharedTemplate(
            template_id=footprint_template_id,
            kind="footprint",
            contract_digest=footprint_template.contract_digest,
        ),
    )
    tool_bindings = (
        _tool_template_binding(profile.tool_bindings[0]),
        _tool_template_binding(profile.tool_bindings[1]),
    )
    artifacts = ArtifactSet(
        component_id=identity.component_id,
        definition_digest=canonical_model_digest(definition),
        shared_templates=shared_templates,
        tool_bindings=tool_bindings,
    )
    verification = Verification(
        component_id=identity.component_id,
        definition_digest=canonical_model_digest(definition),
        artifact_set_digest=canonical_model_digest(artifacts),
        claim_evidence_digests=(
            value_evidence.content_digest,
            package_evidence.content_digest,
        ),
        observed_terminal_numbers=("1", "2"),
        observed_tool_bindings=("kicad", "altium"),
    )
    return CanonicalPassiveBundle(
        manufacturer=manufacturer,
        identity=identity,
        claims=claims,
        definition=definition,
        artifacts=artifacts,
        verification=verification,
    )
