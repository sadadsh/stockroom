"""Four part classes, and requirements as `f(part_class, tool)`.

DECIDED in `docs/specs/2026-07-27-owner-spec-complete-trusted-library.md` section 6 (D3):

    passive     nothing                          both EDAs ship them; app UI + BOM only
    component   symbol + footprint + 3D, per EDA the acquisition case
    mechanical  footprint only, no symbol        an M3 screw; may or may not be orderable
    virtual     nothing, and no BOM line         a test point, a fiducial, a logo

It replaces `passive: bool`, which was a two-valued part class. The cost of that was measured,
not theorised: the owner's register already holds M3 mounting holes and a ring LED integral to
its button, and BOTH were excluded from the library BY HAND because they fit neither value.

PRIOR ART (checked before writing, 2026-07-27): KiCad expresses the same distinctions as
per-symbol flags (`exclude_from_bom`, `exclude_from_board`, `dnp`) rather than as a taxonomy,
and Altium uses a per-component "Component Type" enumeration (Standard, Mechanical, Graphical,
Net Tie, Standard (No BOM)). Altium's shape is the closer analogue and was the model for this
being an ENUM ON THE PART rather than a set of independent booleans - a taxonomy answers "what
files does this need" once, where N booleans re-derive it at every call site and drift. Neither
tool's enumeration is adopted verbatim, because both describe what the TOOL does with a placed
component, while this answers what STOCKROOM must acquire for a library part; the owner chose
these four names and their needs directly.

The point of the table below is that a requirement is DATA. There is no `if tool == "altium"`
and no `if record.passive` here or in anything that calls it: the class says which KINDS it
needs, the EDA registry says which kinds a tool can hold, and the answer is the intersection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from stockroom.eda.registry import get_tool


class PartClass(str, Enum):
    """What a part IS, which decides what files it needs. Serialized as its value."""

    PASSIVE = "passive"
    COMPONENT = "component"
    MECHANICAL = "mechanical"
    VIRTUAL = "virtual"


# A record with no class stated is a component: the acquisition case, so an unclassified part
# shows up as needing work rather than silently excusing itself.
DEFAULT_PART_CLASS = PartClass.COMPONENT


@dataclass(frozen=True)
class ClassNeeds:
    """What one class needs, as data.

    `assets` names asset KINDS, never tools. Which of those a given tool can actually end up
    holding is the registry's answer, not this table's, so adding a third EDA tool changes
    nothing here.
    """

    # Asset kinds a part of this class needs, in the order a person would acquire them.
    assets: tuple[str, ...] = ()
    # Whether a part of this class appears on a bill of materials. A fiducial does not.
    bom_line: bool = True
    label: str = ""
    description: str = ""


CLASS_NEEDS: dict[PartClass, ClassNeeds] = {
    PartClass.PASSIVE: ClassNeeds(
        assets=(),
        bom_line=True,
        label="Passive",
        description=(
            "A resistor, capacitor or inductor. Both KiCad and Altium ship generic passives, "
            "so there is nothing to acquire. Its SR-* symbol is a BOM-property vehicle "
            "produced by rebuild_part, never a captured asset."
        ),
    ),
    PartClass.COMPONENT: ClassNeeds(
        assets=("symbol", "footprint", "model"),
        bom_line=True,
        label="Component",
        description="An active or otherwise non-generic part. The acquisition case.",
    ),
    PartClass.MECHANICAL: ClassNeeds(
        assets=("footprint",),
        bom_line=True,
        label="Mechanical",
        description=(
            "A screw, standoff or mounting hole. It occupies board area and may be ordered, "
            "but it has no schematic symbol."
        ),
    ),
    PartClass.VIRTUAL: ClassNeeds(
        assets=(),
        bom_line=False,
        label="Virtual",
        description="A test point, fiducial or logo. Nothing to acquire and nothing to buy.",
    ),
}


@dataclass
class RequirementOverride:
    """The per-part escape hatch, so one odd part never forces a new class.

    `needs` REPLACES the class default. An override with an EMPTY `needs` is meaningful and is
    not the same as no override at all: `requires_override: null` means "use the class
    default", while `RequirementOverride(needs=())` is somebody stating that this one part
    needs nothing. Collapsing the two is how an escape hatch silently stops working.
    """

    # Asset kinds this part needs, replacing its class's list.
    needs: tuple[str, ...] = ()
    # EDA tool keys the override applies to. Empty means every tool.
    tools: tuple[str, ...] = ()
    # Why. An anonymous exception is one nobody can ever review or retire.
    reason: str = ""
    # Keys a newer build wrote here, kept verbatim and re-emitted (the same guarantee
    # PartRecord.extra gives the record as a whole, one level down).
    extra: dict = field(default_factory=dict)

    def applies_to(self, tool_key: str) -> bool:
        return not self.tools or tool_key in self.tools

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "needs": list(self.needs),
            "tools": list(self.tools),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RequirementOverride":
        known = {"needs", "tools", "reason"}
        return cls(
            needs=tuple(d.get("needs") or ()),
            tools=tuple(d.get("tools") or ()),
            reason=d.get("reason", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


def parse_part_class(value) -> PartClass:
    """The PartClass for a stored value. Raises ValueError for anything else.

    LOUD on purpose. part_class decides which files a part needs, so guessing would either
    demand files a part cannot have or excuse a part that needs them - and both failures are
    invisible, which is exactly the class of defect this schema exists to end. A record from a
    build that added a fifth class also carries a higher `schema_version`, so
    `PartRecord.is_future_schema` is what explains the refusal.
    """
    if isinstance(value, PartClass):
        return value
    try:
        return PartClass(value)
    except ValueError:
        known = ", ".join(c.value for c in PartClass)
        raise ValueError(f"unknown part_class {value!r}: known classes are {known}") from None


def _wanted(part_class: PartClass, tool_key: str, override: RequirementOverride | None) -> tuple:
    if override is not None and override.applies_to(tool_key):
        return tuple(override.needs)
    return CLASS_NEEDS[parse_part_class(part_class)].assets


def needed_kinds(
    part_class: PartClass, tool_key: str, override: RequirementOverride | None = None
) -> tuple[str, ...]:
    """Asset kinds `tool_key` should END UP holding for a part of this class.

    Intersected with the tool's `closable_assets()`, which is deliberately wider than what a
    capture session can fetch: an Altium 3D body cannot be referenced but CAN be embedded, so
    it is a real gap with a real action behind it and hiding it would be dishonest.

    Raises for an unregistered tool (via the registry) rather than falling back to KiCad -
    that silent fallback is what let an Altium attach overwrite a KiCad reference.
    """
    wanted = _wanted(part_class, tool_key, override)
    return tuple(k for k in get_tool(tool_key).closable_assets() if k in wanted)


def capturable_kinds(
    part_class: PartClass, tool_key: str, override: RequirementOverride | None = None
) -> tuple[str, ...]:
    """Asset kinds a CAPTURE session can actually be asked to fetch for this part.

    Narrower than `needed_kinds`: asking a vendor for an asset the tool can only receive by
    embedding names a gap the session can never close.
    """
    wanted = _wanted(part_class, tool_key, override)
    return tuple(k for k in get_tool(tool_key).capturable_assets() if k in wanted)


def has_bom_line(part_class: PartClass, override: RequirementOverride | None = None) -> bool:
    """Whether a part of this class appears on a bill of materials.

    The override deliberately does NOT reach this: it adjusts what FILES a part needs, and
    whether something is bought is a different question with a different answer. A part that
    should not be bought is a `virtual` part.
    """
    return CLASS_NEEDS[parse_part_class(part_class)].bom_line
