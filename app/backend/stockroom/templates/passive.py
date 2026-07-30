"""Versioned tool-neutral contracts for shared two-pin passive templates.

This registry describes template authority only.  It does not claim that an
adapter ran, a native file opened, or a component is ready to publish.  Native
readback evidence remains a separate workflow outcome.
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

from stockroom.workflow.identifiers import digest_text, parse_sha256
from stockroom.workflow.model import canonical_json

SchemaVersion = Literal[1]
NonBlankText = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False)]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ToolKey = Literal["kicad", "altium"]
TerminalNumber = Literal["1", "2"]
TwoPinKind = Literal["resistor", "diode"]


class _TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _authoritative_text(value: str, field_name: str) -> str:
    if value != value.strip():
        raise ValueError(f"{field_name} must have no surrounding whitespace")
    return value


def template_contract_digest(template_id: str, kind: str) -> str:
    """Digest the stable identity contract for one shared template artifact."""

    payload = canonical_json(
        {
            "kind": kind,
            "schema_version": 1,
            "template_id": template_id,
        }
    ).encode("utf-8")
    return digest_text(hashlib.sha256(payload).digest())


class PassiveTemplateArtifact(_TemplateModel):
    schema_version: SchemaVersion = 1
    kind: Literal["symbol", "footprint"]
    template_id: NonBlankText
    contract_digest: Sha256Digest

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, value: str) -> str:
        return _authoritative_text(value, "template_id")

    @field_validator("contract_digest")
    @classmethod
    def validate_contract_digest(cls, value: str) -> str:
        parse_sha256(value, "contract_digest")
        return value

    @model_validator(mode="after")
    def validate_derived_digest(self) -> Self:
        if self.contract_digest != template_contract_digest(self.template_id, self.kind):
            raise ValueError("template contract digest does not match its identity")
        return self


class PassiveTemplateTerminal(_TemplateModel):
    schema_version: SchemaVersion = 1
    number: TerminalNumber
    role: Literal["terminal", "cathode", "anode"]
    x_nm: int
    y_nm: int
    rotation_udeg: int = Field(ge=0, lt=360_000_000)
    electrical_type: Literal["passive"] = "passive"


class TemplateTerminalBinding(_TemplateModel):
    schema_version: SchemaVersion = 1
    canonical_terminal: TerminalNumber
    tool_terminal: NonBlankText

    @field_validator("tool_terminal")
    @classmethod
    def validate_tool_terminal(cls, value: str) -> str:
        return _authoritative_text(value, "tool_terminal")


class PassiveToolTemplateBinding(_TemplateModel):
    """One EDA adapter's explicit projection contract for a shared profile."""

    schema_version: SchemaVersion = 1
    tool: ToolKey
    adapter_revision: NonBlankText
    symbol_template_id: NonBlankText
    footprint_template_id: NonBlankText
    adapter_symbol_reference: NonBlankText
    adapter_footprint_reference: NonBlankText
    terminal_bindings: tuple[TemplateTerminalBinding, TemplateTerminalBinding]

    @field_validator(
        "adapter_revision",
        "symbol_template_id",
        "footprint_template_id",
        "adapter_symbol_reference",
        "adapter_footprint_reference",
    )
    @classmethod
    def validate_authoritative_text(cls, value: str) -> str:
        return _authoritative_text(value, "tool template binding text")

    @model_validator(mode="after")
    def validate_terminal_bindings(self) -> Self:
        canonical = tuple(binding.canonical_terminal for binding in self.terminal_bindings)
        if canonical != ("1", "2"):
            raise ValueError("tool template binding must map canonical terminals 1 and 2")
        native = tuple(binding.tool_terminal for binding in self.terminal_bindings)
        if len(set(native)) != 2:
            raise ValueError("tool template terminal identifiers must be unique")
        return self


class PassiveTemplateDefinition(_TemplateModel):
    """One immutable, tool-neutral passive template profile."""

    schema_version: SchemaVersion = 1
    profile_id: NonBlankText
    functional_kind: TwoPinKind
    package: NonBlankText
    body_min_x_nm: int
    body_min_y_nm: int
    body_max_x_nm: int
    body_max_y_nm: int
    terminals: tuple[PassiveTemplateTerminal, PassiveTemplateTerminal]
    artifacts: tuple[PassiveTemplateArtifact, PassiveTemplateArtifact]
    tool_bindings: tuple[PassiveToolTemplateBinding, PassiveToolTemplateBinding]

    @field_validator("profile_id", "package")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        return _authoritative_text(value, "passive template identity")

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.body_min_x_nm >= self.body_max_x_nm or self.body_min_y_nm >= self.body_max_y_nm:
            raise ValueError("passive template body must have positive integer-nm area")
        if tuple(terminal.number for terminal in self.terminals) != ("1", "2"):
            raise ValueError("passive template terminals must be exactly 1 and 2")
        expected_roles = (
            ("cathode", "anode") if self.functional_kind == "diode" else ("terminal", "terminal")
        )
        if tuple(terminal.role for terminal in self.terminals) != expected_roles:
            raise ValueError(
                f"{self.functional_kind} passive template roles must be {expected_roles!r}"
            )
        if tuple(artifact.kind for artifact in self.artifacts) != ("symbol", "footprint"):
            raise ValueError("passive template requires symbol then footprint artifacts")
        if tuple(binding.tool for binding in self.tool_bindings) != ("kicad", "altium"):
            raise ValueError("passive template requires explicit KiCad and Altium bindings")
        symbol_id, footprint_id = (artifact.template_id for artifact in self.artifacts)
        if any(
            binding.symbol_template_id != symbol_id or binding.footprint_template_id != footprint_id
            for binding in self.tool_bindings
        ):
            raise ValueError("both EDA bindings must resolve the same shared templates")
        return self

    def binding_for(self, tool: ToolKey) -> PassiveToolTemplateBinding:
        return next(binding for binding in self.tool_bindings if binding.tool == tool)

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.model_dump(mode="json")).encode("utf-8") + b"\n"

    def canonical_digest(self) -> str:
        return digest_text(hashlib.sha256(self.canonical_bytes()).digest())


def _artifact(
    kind: Literal["symbol", "footprint"],
    template_id: str,
) -> PassiveTemplateArtifact:
    return PassiveTemplateArtifact(
        kind=kind,
        template_id=template_id,
        contract_digest=template_contract_digest(template_id, kind),
    )


def _terminal_bindings(
    first: str,
    second: str,
) -> tuple[TemplateTerminalBinding, TemplateTerminalBinding]:
    return (
        TemplateTerminalBinding(canonical_terminal="1", tool_terminal=first),
        TemplateTerminalBinding(canonical_terminal="2", tool_terminal=second),
    )


_DIODE_SMA = PassiveTemplateDefinition(
    profile_id="shared.passive.diode.sma_do_214ac.profile.v1",
    functional_kind="diode",
    package="SMA (DO-214AC)",
    body_min_x_nm=-1_000_000,
    body_min_y_nm=-500_000,
    body_max_x_nm=1_000_000,
    body_max_y_nm=500_000,
    terminals=(
        PassiveTemplateTerminal(
            number="1",
            role="cathode",
            x_nm=-2_540_000,
            y_nm=0,
            rotation_udeg=0,
        ),
        PassiveTemplateTerminal(
            number="2",
            role="anode",
            x_nm=2_540_000,
            y_nm=0,
            rotation_udeg=180_000_000,
        ),
    ),
    artifacts=(
        _artifact("symbol", "shared.passive.diode.two_pin.v1"),
        _artifact("footprint", "shared.passive.diode.sma_do_214ac.v1"),
    ),
    tool_bindings=(
        PassiveToolTemplateBinding(
            tool="kicad",
            adapter_revision="stockroom.kicad.stock-template/1",
            symbol_template_id="shared.passive.diode.two_pin.v1",
            footprint_template_id="shared.passive.diode.sma_do_214ac.v1",
            adapter_symbol_reference="Device:D",
            adapter_footprint_reference="Diode_SMD:D_SMA",
            terminal_bindings=_terminal_bindings("1", "2"),
        ),
        PassiveToolTemplateBinding(
            tool="altium",
            adapter_revision="stockroom.altium.native-authoring/1",
            symbol_template_id="shared.passive.diode.two_pin.v1",
            footprint_template_id="shared.passive.diode.sma_do_214ac.v1",
            adapter_symbol_reference="stockroom-template:diode-two-pin-v1",
            adapter_footprint_reference="stockroom-template:sma-do-214ac-v1",
            terminal_bindings=_terminal_bindings("C", "A"),
        ),
    ),
)

_RESISTOR_0603 = PassiveTemplateDefinition(
    profile_id="shared.passive.resistor.0603_1608_metric.profile.v1",
    functional_kind="resistor",
    package="0603 (1608 Metric)",
    body_min_x_nm=-1_000_000,
    body_min_y_nm=-500_000,
    body_max_x_nm=1_000_000,
    body_max_y_nm=500_000,
    terminals=(
        PassiveTemplateTerminal(
            number="1",
            role="terminal",
            x_nm=-2_540_000,
            y_nm=0,
            rotation_udeg=0,
        ),
        PassiveTemplateTerminal(
            number="2",
            role="terminal",
            x_nm=2_540_000,
            y_nm=0,
            rotation_udeg=180_000_000,
        ),
    ),
    artifacts=(
        _artifact("symbol", "shared.passive.resistor.two_pin.v1"),
        _artifact("footprint", "shared.passive.resistor.0603_1608_metric.v1"),
    ),
    tool_bindings=(
        PassiveToolTemplateBinding(
            tool="kicad",
            adapter_revision="stockroom.kicad.stock-template/1",
            symbol_template_id="shared.passive.resistor.two_pin.v1",
            footprint_template_id="shared.passive.resistor.0603_1608_metric.v1",
            adapter_symbol_reference="Device:R",
            adapter_footprint_reference="Resistor_SMD:R_0603_1608Metric",
            terminal_bindings=_terminal_bindings("1", "2"),
        ),
        PassiveToolTemplateBinding(
            tool="altium",
            adapter_revision="stockroom.altium.native-authoring/1",
            symbol_template_id="shared.passive.resistor.two_pin.v1",
            footprint_template_id="shared.passive.resistor.0603_1608_metric.v1",
            adapter_symbol_reference="stockroom-template:resistor-two-pin-v1",
            adapter_footprint_reference="stockroom-template:r-0603-1608-metric-v1",
            terminal_bindings=_terminal_bindings("1", "2"),
        ),
    ),
)

_PROFILES = {
    (profile.functional_kind, profile.package): profile for profile in (_DIODE_SMA, _RESISTOR_0603)
}


def passive_template_definition(
    functional_kind: TwoPinKind,
    package: str,
) -> PassiveTemplateDefinition:
    """Resolve one exact supported profile without fuzzy package matching."""

    exact_package = _authoritative_text(package, "package")
    try:
        return _PROFILES[(functional_kind, exact_package)]
    except KeyError:
        raise ValueError(
            f"unsupported two-pin passive template profile {functional_kind!r}/{exact_package!r}"
        ) from None


def representative_passive_template() -> PassiveTemplateDefinition:
    """Return the one profile qualified by the current dual-EDA adapter slice."""

    return _DIODE_SMA
