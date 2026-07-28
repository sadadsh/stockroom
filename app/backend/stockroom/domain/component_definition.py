"""Tool-neutral, fixed-point component definitions.

Geometry is stored only as integer nanometres.  Provenance is attached to the
claims that selected each value, while unresolved engineering choices remain
explicit production blockers rather than being promoted to facts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

NM_PER_MM = 1_000_000

ClaimBasis = Literal["documented", "derived", "policy"]
TerminalSide = Literal["left", "bottom", "right", "top"]
ElectricalType = Literal["passive"]


def _require_non_blank(value: str, field_name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and have no surrounding whitespace")


def _require_positive_nm(value: int, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer number of nanometres")


@dataclass(frozen=True, slots=True)
class PointNm:
    x_nm: int
    y_nm: int

    def __post_init__(self) -> None:
        if type(self.x_nm) is not int or type(self.y_nm) is not int:
            raise ValueError("point coordinates must be integer nanometres")


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    manufacturer: str
    mpn: str
    symbol_name: str
    footprint_name: str
    reference_prefix: str

    def __post_init__(self) -> None:
        for field_name in (
            "manufacturer",
            "mpn",
            "symbol_name",
            "footprint_name",
            "reference_prefix",
        ):
            _require_non_blank(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class BodyEnvelopeNm:
    width_nm: int
    depth_nm: int
    height_nm: int | None

    def __post_init__(self) -> None:
        _require_positive_nm(self.width_nm, "body width")
        _require_positive_nm(self.depth_nm, "body depth")
        if self.height_nm is not None:
            _require_positive_nm(self.height_nm, "body height")


@dataclass(frozen=True, slots=True)
class TerminalDefinition:
    number: str
    side: TerminalSide
    side_index: int
    center: PointNm
    drill_diameter_nm: int
    land_diameter_nm: int
    electrical_type: ElectricalType = "passive"

    def __post_init__(self) -> None:
        _require_non_blank(self.number, "terminal number")
        if type(self.side_index) is not int or not 0 <= self.side_index < 12:
            raise ValueError("terminal side_index must be an integer from 0 through 11")
        _require_positive_nm(self.drill_diameter_nm, "terminal drill diameter")
        _require_positive_nm(self.land_diameter_nm, "terminal land diameter")
        if self.land_diameter_nm <= self.drill_diameter_nm:
            raise ValueError("terminal land diameter must be larger than its drill")


@dataclass(frozen=True, slots=True)
class MountingHoleDefinition:
    center: PointNm
    drill_diameter_nm: int

    def __post_init__(self) -> None:
        _require_positive_nm(self.drill_diameter_nm, "mounting-hole drill diameter")


@dataclass(frozen=True, slots=True)
class ComponentModel:
    """A selected exact-part 3D model.

    IC51 deliberately has no instance of this record yet.  A model URI and its
    documented height must arrive together before projection can use either.
    """

    uri: str
    body_height_nm: int

    def __post_init__(self) -> None:
        _require_non_blank(self.uri, "model URI")
        _require_positive_nm(self.body_height_nm, "model body height")


@dataclass(frozen=True, slots=True)
class ProvenanceClaim:
    key: str
    basis: ClaimBasis
    value: str
    source_locator: str
    note: str

    def __post_init__(self) -> None:
        for field_name in ("key", "value", "source_locator", "note"):
            _require_non_blank(getattr(self, field_name), f"claim {field_name}")


@dataclass(frozen=True, slots=True)
class ProductionBlocker:
    code: str
    claim_key: str
    detail: str

    def __post_init__(self) -> None:
        for field_name in ("code", "claim_key", "detail"):
            _require_non_blank(getattr(self, field_name), f"blocker {field_name}")


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    """Shared EDA-neutral component IR with deterministic fixed-point geometry."""

    identity: ComponentIdentity
    body: BodyEnvelopeNm
    terminals: tuple[TerminalDefinition, ...]
    mounting_holes: tuple[MountingHoleDefinition, ...]
    model: ComponentModel | None
    provenance: tuple[ProvenanceClaim, ...]
    blockers: tuple[ProductionBlocker, ...]
    schema_version: int = 1
    geometry_unit: Literal["nm"] = "nm"

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported component-definition schema version")
        if not self.terminals:
            raise ValueError("component definition requires terminals")
        terminal_numbers = tuple(terminal.number for terminal in self.terminals)
        if len(set(terminal_numbers)) != len(terminal_numbers):
            raise ValueError("terminal numbers must be unique")
        terminal_centers = tuple(terminal.center for terminal in self.terminals)
        if len(set(terminal_centers)) != len(terminal_centers):
            raise ValueError("terminal centers must be unique")
        hole_centers = tuple(hole.center for hole in self.mounting_holes)
        if len(set(hole_centers)) != len(hole_centers):
            raise ValueError("mounting-hole centers must be unique")
        if set(terminal_centers) & set(hole_centers):
            raise ValueError("terminal and mounting-hole centers must not overlap")
        claim_keys = tuple(claim.key for claim in self.provenance)
        if len(set(claim_keys)) != len(claim_keys):
            raise ValueError("provenance claim keys must be unique")
        missing_claims = {
            blocker.claim_key for blocker in self.blockers if blocker.claim_key not in claim_keys
        }
        if missing_claims:
            raise ValueError(
                f"production blockers reference missing claims: {sorted(missing_claims)}"
            )
        if self.model is None and self.body.height_nm is not None:
            raise ValueError("body height cannot be selected without an exact-part model record")
        if self.model is not None and self.body.height_nm != self.model.body_height_nm:
            raise ValueError("body envelope and model heights must agree")
        if not self.blockers and (self.model is None or self.body.height_nm is None):
            raise ValueError(
                "a production-ready definition requires an exact model and body height"
            )

    @property
    def production_ready(self) -> bool:
        """True only when no unresolved engineering claim remains."""

        return not self.blockers

    def canonical_bytes(self) -> bytes:
        """Return stable UTF-8 JSON bytes for content addressing."""

        document = {
            **asdict(self),
            "production_ready": self.production_ready,
        }
        return (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

    def canonical_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


_DOCUMENTED_SOURCE = "provided-exact-part-facts:IC51-0484-806"
_FAMILY_DIAGRAM_SOURCE = "family-diagram-derived:IC51-0484-806-terminal-map"
_LAND_POLICY_SOURCE = "stockroom-policy:pth-contact-land-od-1.20mm-v1"


def _ic51_terminals() -> tuple[TerminalDefinition, ...]:
    radii_nm = (5_000_000, 6_270_000, 7_540_000)
    tangent_nm = tuple(-2_750_000 + index * 500_000 for index in range(12))
    terminals: list[TerminalDefinition] = []

    for side, first_number in (
        ("left", 1),
        ("bottom", 13),
        ("right", 25),
        ("top", 37),
    ):
        for side_index in range(12):
            radius_nm = radii_nm[side_index % len(radii_nm)]
            tangent = tangent_nm[side_index]
            if side == "left":
                center = PointNm(-radius_nm, tangent)
            elif side == "bottom":
                center = PointNm(tangent, radius_nm)
            elif side == "right":
                center = PointNm(radius_nm, -tangent)
            else:
                center = PointNm(-tangent, -radius_nm)
            terminals.append(
                TerminalDefinition(
                    number=str(first_number + side_index),
                    side=side,
                    side_index=side_index,
                    center=center,
                    drill_diameter_nm=800_000,
                    land_diameter_nm=1_200_000,
                )
            )
    return tuple(terminals)


def build_ic51_0484_806_definition() -> ComponentDefinition:
    """Build the blocked, exact-identity definition for Yamaichi IC51-0484-806."""

    return ComponentDefinition(
        identity=ComponentIdentity(
            manufacturer="Yamaichi Electronics",
            mpn="IC51-0484-806",
            symbol_name="IC51-0484-806",
            footprint_name="IC51-0484-806",
            reference_prefix="J",
        ),
        body=BodyEnvelopeNm(
            width_nm=29_000_000,
            depth_nm=32_000_000,
            height_nm=None,
        ),
        terminals=_ic51_terminals(),
        mounting_holes=tuple(
            MountingHoleDefinition(
                center=PointNm(x_nm, y_nm),
                drill_diameter_nm=3_200_000,
            )
            for x_nm, y_nm in (
                (-10_080_000, -9_500_000),
                (10_080_000, -9_500_000),
                (10_080_000, 9_500_000),
                (-10_080_000, 9_500_000),
            )
        ),
        model=None,
        provenance=(
            ProvenanceClaim(
                key="exact_identity",
                basis="documented",
                value="Yamaichi Electronics / IC51-0484-806",
                source_locator=_DOCUMENTED_SOURCE,
                note="Exact manufacturer part number selected without substitution.",
            ),
            ProvenanceClaim(
                key="contact_geometry",
                basis="documented",
                value="48 passive contacts; 0.50 mm pitch; 0.80 mm drill",
                source_locator=_DOCUMENTED_SOURCE,
                note="Exact-part contact count, tangent pitch, and contact drill.",
            ),
            ProvenanceClaim(
                key="mounting_geometry",
                basis="documented",
                value="4 x 3.20 mm NPTH at (+/-10.08 mm, +/-9.50 mm)",
                source_locator=_DOCUMENTED_SOURCE,
                note="Exact-part non-plated mounting-hole pattern.",
            ),
            ProvenanceClaim(
                key="body_envelope",
                basis="documented",
                value="29.00 mm x 32.00 mm; height unavailable",
                source_locator=_DOCUMENTED_SOURCE,
                note="Reference body envelope only; no exact-part height is available.",
            ),
            ProvenanceClaim(
                key="radial_rows",
                basis="derived",
                value="5.00 mm / 6.27 mm / 7.54 mm",
                source_locator=_DOCUMENTED_SOURCE,
                note=(
                    "Centerline radii derived from 10.00 mm and 15.08 mm squares "
                    "with 1.27 mm row spacing."
                ),
            ),
            ProvenanceClaim(
                key="terminal_mapping",
                basis="derived",
                value=(
                    "top view counterclockwise: 1-12 left top-to-bottom; "
                    "13-24 bottom left-to-right; 25-36 right bottom-to-top; "
                    "37-48 top right-to-left"
                ),
                source_locator=_FAMILY_DIAGRAM_SOURCE,
                note=(
                    "Family/diagram-derived mapping; not directly confirmed against an "
                    "exact-part IC51-0484-806 terminal-number drawing."
                ),
            ),
            ProvenanceClaim(
                key="copper_land_od",
                basis="policy",
                value="1.20 mm circular copper land outside diameter",
                source_locator=_LAND_POLICY_SOURCE,
                note="Provisional Stockroom rule, not a documented exact-part land recommendation.",
            ),
            ProvenanceClaim(
                key="exact_part_3d",
                basis="documented",
                value="model=None; body height=None",
                source_locator=_DOCUMENTED_SOURCE,
                note="No exact-part STEP model or documented body height is available.",
            ),
        ),
        blockers=(
            ProductionBlocker(
                code="terminal-map-not-exact-part-confirmed",
                claim_key="terminal_mapping",
                detail=(
                    "Confirm the family/diagram-derived pin-number mapping against an "
                    "exact-part IC51-0484-806 drawing."
                ),
            ),
            ProductionBlocker(
                code="policy-derived-copper-land",
                claim_key="copper_land_od",
                detail=(
                    "Approve the provisional 1.20 mm copper land outside diameter for "
                    "fabrication and socket reliability."
                ),
            ),
            ProductionBlocker(
                code="missing-exact-part-3d-and-height",
                claim_key="exact_part_3d",
                detail="Acquire an exact-part STEP model and documented body height.",
            ),
        ),
    )
