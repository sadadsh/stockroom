"""The closed vocabularies the component dossier speaks in.

Every one of these is a set of NAMED SITUATIONS rather than a scale. "We have no value for a
field this category requires" and "no source mentioned it" are different sentences with
different fixes, and collapsing them into one "incomplete" number is what forced the frontend
to guess which of the two it was looking at.
"""

from __future__ import annotations

# Bump when the dossier shape changes in a way a reader must notice. The frontend mirrors this
# number so a stale client can degrade honestly instead of misreading a new shape.
DOSSIER_SCHEMA_VERSION = 2

# The group every dossier has, in display order, whatever the component is. A category schema
# inserts its own groups after these (see `dossier.categories`); it never reorders them, so a
# person moving between two parts finds the same headings in the same places.
UNIVERSAL_GROUPS: tuple[tuple[str, str], ...] = (
    ("key_specifications", "Main Specifications"),
    ("functional", "Functional"),
    ("electrical", "Electrical"),
    ("timing_performance", "Timing and Performance"),
    ("input_characteristics", "Input Characteristics"),
    ("output_characteristics", "Output Characteristics"),
    ("power", "Power"),
    ("interface_pinout", "Interface and Pinout"),
    ("package_mechanical", "Package and Mechanical"),
    ("environmental_reliability", "Environmental and Reliability"),
    ("compliance_lifecycle", "Compliance and Lifecycle"),
    ("manufacturer_information", "Manufacturer Information"),
)

# Groups a category schema may add. Declared centrally so two schemas cannot spell the same
# heading two ways, and so a group id can never render without a label.
CATEGORY_GROUPS: tuple[tuple[str, str], ...] = (
    # Microcontrollers and processors.
    ("processor_architecture", "Processor Architecture"),
    ("memory", "Memory"),
    ("clocks", "Clocks"),
    ("analog_digital_peripherals", "Analog and Digital Peripherals"),
    ("communication_interfaces", "Communication Interfaces"),
    ("security_debug", "Security and Debug"),
    ("power_modes", "Power Modes"),
    # Resistors.
    ("resistance", "Resistance"),
    ("tolerance_stability", "Tolerance and Stability"),
    ("power_derating", "Power and Derating"),
    ("temperature_characteristics", "Temperature Characteristics"),
    ("pulse_overload", "Pulse and Overload"),
    ("construction_termination", "Construction and Termination"),
    # Connectors.
    ("contact_configuration", "Contact Configuration"),
    ("pitch_spacing", "Pitch and Spacing"),
    ("mounting", "Mounting"),
    ("mating_retention", "Mating and Retention"),
    ("electrical_ratings", "Electrical Ratings"),
    ("mechanical_durability", "Mechanical Durability"),
    ("materials_plating", "Materials and Plating"),
    # Capacitors, inductors, diodes, transistors, crystals.
    ("capacitance", "Capacitance"),
    ("inductance", "Inductance"),
    ("junction_characteristics", "Junction Characteristics"),
    ("switching_characteristics", "Switching Characteristics"),
    ("frequency_stability", "Frequency and Stability"),
)

# The last resort, and deliberately last in every ordering. A key that keeps landing here wants
# a field definition, not a bigger bucket.
OTHER_GROUP: tuple[str, str] = ("other", "Other")

# THE MORE GENERAL HEADING EACH CATEGORY GROUP BELONGS UNDER.
#
# A category group is a REFINEMENT of a universal one: `Capacitance` refines `Electrical`,
# `Construction and Termination` refines `Package and Mechanical`, `Clocks` refines
# `Timing and Performance`. The refinement earns its own heading when there is enough under it to be
# worth separating, and MEASURED on a 100 nF 0402 capacitor there was not: seven headings held
# exactly one row each - `Package and Mechanical`, `Environmental and Reliability`, `Capacitance`,
# `Tolerance and Stability`, `Temperature Characteristics`, `Construction and Termination`,
# `Mounting` - so the sheet spent one header line per line of data and the column's anchor strip
# offered seven destinations that were each a single row.
#
# So a refinement holding ONE row folds into the heading above it (see
# `specifications.build_specifications`). The row is not moved somewhere arbitrary and it is not
# hidden: a case code IS a package-and-mechanical fact, and reading it under that heading is more
# useful than reading it under a heading invented for it alone.
#
# EVERY category group has an entry, and every value is a UNIVERSAL group - never
# `key_specifications` (that names the headline region, not a group) and never `other` (which is the
# bucket for keys nobody has defined, so folding INTO it would hide a row rather than home it).
# `tests/backend/dossier/test_specifications.py` asserts both halves, so a new category group cannot
# ship without declaring where it belongs. Universal groups have no entry: they ARE the parents, and
# one row under `Environmental and Reliability` is a heading a reader can still navigate by.
GROUP_PARENT: dict[str, str] = {
    # Microcontrollers and processors.
    "processor_architecture": "functional",
    "memory": "functional",
    "clocks": "timing_performance",
    "analog_digital_peripherals": "functional",
    "communication_interfaces": "interface_pinout",
    "security_debug": "functional",
    "power_modes": "power",
    # Resistors.
    "resistance": "electrical",
    "tolerance_stability": "electrical",
    "power_derating": "power",
    "temperature_characteristics": "environmental_reliability",
    "pulse_overload": "electrical",
    "construction_termination": "package_mechanical",
    # Connectors.
    "contact_configuration": "interface_pinout",
    "pitch_spacing": "package_mechanical",
    "mounting": "package_mechanical",
    "mating_retention": "package_mechanical",
    "electrical_ratings": "electrical",
    "mechanical_durability": "package_mechanical",
    "materials_plating": "package_mechanical",
    # Capacitors, inductors, diodes, transistors, crystals.
    "capacitance": "electrical",
    "inductance": "electrical",
    "junction_characteristics": "electrical",
    "switching_characteristics": "timing_performance",
    "frequency_stability": "timing_performance",
}

GROUP_LABELS: dict[str, str] = (
    dict(UNIVERSAL_GROUPS) | dict(CATEGORY_GROUPS) | {OTHER_GROUP[0]: OTHER_GROUP[1]}
)

# What we know about ONE specification, and the exact difference between the six situations the
# old projection collapsed into "unknown":
#
#   missing         the category EXPECTS this field and nothing supplied it. A real gap.
#   not_reported    no source offered it, and the category does not require it. Not a gap.
#   not_applicable  the field does not apply to this category or this part at all.
#   unverified      a value exists, from a source that is not the manufacturer's own word.
#   conflicting     two or more sources gave materially different answers; all are kept.
#   verified        the value came from a reviewed override or the manufacturer's own document.
VERIFICATION_STATES: tuple[str, ...] = (
    "missing",
    "not_reported",
    "not_applicable",
    "unverified",
    "conflicting",
    "verified",
)

# Whether the category wants this field at all. Completeness counts `expected` and
# `recommended`; it never counts `applicable` and never counts `not_applicable`, which is what
# stops a resistor being marked incomplete for having no clock source.
APPLICABILITY_STATES: tuple[str, ...] = (
    "expected",
    "recommended",
    "applicable",
    "not_applicable",
)

# How much a field matters when the category is read at a glance.
IMPORTANCE_LEVELS: tuple[str, ...] = ("key", "primary", "secondary")

# Whether the sources agreed. `resolved` means they disagreed and a reviewed override settled
# it - the losing answers are still carried, because a settled disagreement is still evidence.
CONFLICT_STATES: tuple[str, ...] = ("none", "conflicting", "resolved")

# What kind of thing the value IS, which decides whether it can be compared, ranged or filtered.
VALUE_TYPES: tuple[str, ...] = (
    "quantity",
    "range",
    "integer",
    "boolean",
    "enum",
    "text",
    "list",
)

__all__ = [
    "APPLICABILITY_STATES",
    "CATEGORY_GROUPS",
    "CONFLICT_STATES",
    "DOSSIER_SCHEMA_VERSION",
    "GROUP_LABELS",
    "GROUP_PARENT",
    "IMPORTANCE_LEVELS",
    "OTHER_GROUP",
    "UNIVERSAL_GROUPS",
    "VALUE_TYPES",
    "VERIFICATION_STATES",
]
