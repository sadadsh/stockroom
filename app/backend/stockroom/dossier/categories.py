"""Category schemas: what a component of THIS kind is described by.

A logic gate is not a microcontroller is not a resistor is not a connector. They do not share a
set of important parameters, they do not share a set of headings, and they certainly do not
share a definition of "complete" - counting a resistor's missing clock source against it is not
a measurement, it is noise. One universal field list produced exactly that, which is why there
is a registry here instead.

The registry is DATA. Supporting a new kind of component is a `CategorySchema` row: its key
specifications, its group order, what it is expected to carry, what would be good to have, what
does not apply to it at all, its canonical units, its validation constraints, its search facets,
its comparison fields, and which of its specifications a CAD artifact can be checked against.
Nothing below branches on a category name, and nothing anywhere else may either.

Resolution runs from the specific to the general: an explicit signal in the part's own data
picks a schema inside its filed category, the filed category's own default answers when no
signal fires, and the base schema answers when a part is not filed at all. A part is never
described by a schema for a different category.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from stockroom.dossier.fields import normalize_key
from stockroom.dossier.vocabulary import UNIVERSAL_GROUPS


@dataclass(frozen=True, slots=True)
class Constraint:
    """One validation rule for a field's normalized magnitude or its allowed values.

    A value outside the rule is REPORTED, never rewritten or dropped: the source said it, and a
    projection that silently corrected a distributor would hide the thing worth looking at.
    """

    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    allowed: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""


@dataclass(frozen=True, slots=True)
class CadRelationship:
    """A specification a CAD artifact can be validated against.

    This names the relationship only. The actual checks live with the artifacts
    (`model.trust.AssetCheck`), and no cross-provider rule is touched by anything here.
    """

    field_key: str
    artifact: str
    check: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class CategorySchema:
    """Everything the product knows about how to describe one kind of component."""

    key: str
    label: str
    # The filed category (`model.category.CATEGORIES`) this schema refines, or "" for the base
    # schema that answers for an unfiled part.
    parent: str = ""
    # Tokens that identify this kind inside a part's own words. Matched against the
    # description, the display name, the MPN, the tags and the values of the identifying spec
    # keys - never against a spec key's NAME, which every category shares.
    signals: tuple[str, ...] = field(default_factory=tuple)
    # This schema's own groups, inserted after the universal ones. Main Specifications always
    # leads and `other` always trails, so a schema never declares either.
    groups: tuple[str, ...] = field(default_factory=tuple)
    # Where this category puts a field that has a different universal home. A resistor's
    # resistance is its headline, not one more electrical parameter.
    group_overrides: Mapping[str, str] = field(default_factory=dict)
    key_specs: tuple[str, ...] = field(default_factory=tuple)
    expected: tuple[str, ...] = field(default_factory=tuple)
    recommended: tuple[str, ...] = field(default_factory=tuple)
    applicable: tuple[str, ...] = field(default_factory=tuple)
    # Fields that DO NOT apply here. Emitted as `not_applicable` rather than silently omitted,
    # so a reader looking for one learns it does not exist for this part instead of wondering.
    not_applicable: tuple[str, ...] = field(default_factory=tuple)
    units: Mapping[str, str] = field(default_factory=dict)
    constraints: Mapping[str, Constraint] = field(default_factory=dict)
    facets: tuple[str, ...] = field(default_factory=tuple)
    comparison: tuple[str, ...] = field(default_factory=tuple)
    cad_relationships: tuple[CadRelationship, ...] = field(default_factory=tuple)
    # An expected field is worth twice a recommended one. Stated as data so a category whose
    # recommendations matter more can say so without a second completeness function.
    expected_weight: float = 2.0
    recommended_weight: float = 1.0

    def group_order(self) -> tuple[str, ...]:
        """Every group this schema renders, in order: universal first, then its own."""
        universal = tuple(key for key, _ in UNIVERSAL_GROUPS)
        extra = tuple(key for key in self.groups if key not in universal)
        return universal + extra

    def field_order(self) -> tuple[str, ...]:
        """The schema's own ordering of its fields, key specifications first."""
        seen: list[str] = []
        for group in (self.key_specs, self.expected, self.recommended, self.applicable):
            for key in group:
                if key not in seen:
                    seen.append(key)
        return tuple(seen)

    def applicability(self, field_key: str) -> str:
        if field_key in self.not_applicable:
            return "not_applicable"
        if field_key in self.expected:
            return "expected"
        if field_key in self.recommended:
            return "recommended"
        return "applicable"

    def group_for(self, field_key: str, default: str) -> str:
        return self.group_overrides.get(field_key, default)


_COMMON_COMPLIANCE: tuple[str, ...] = ("rohs", "reach", "lifecycle", "operating_temperature")
_COMMON_APPLICABLE: tuple[str, ...] = (
    "qualification",
    "moisture_sensitivity_level",
    "eccn",
    "country_of_origin",
    "lead_time",
    "packaging",
    "series",
    "htsus",
    "part_status",
    "weight",
)

_PACKAGE_CAD: tuple[CadRelationship, ...] = (
    CadRelationship("package", "footprint", "package_vs_footprint",
                    "The footprint must be the package the specification names."),
    CadRelationship("package", "model", "package_vs_model",
                    "The 3D body must be the package the specification names."),
)
_PIN_CAD: tuple[CadRelationship, ...] = (
    CadRelationship("pin_count", "symbol", "pins_vs_datasheet",
                    "The symbol must carry one pin per specified pin."),
    CadRelationship("pin_count", "footprint", "pads_vs_pins",
                    "The footprint must carry one pad per specified pin."),
)


BASE_SCHEMA = CategorySchema(
    key="component",
    label="Component",
    parent="",
    groups=(),
    key_specs=("component_type", "package", "operating_temperature", "lifecycle"),
    expected=("package", "operating_temperature"),
    recommended=("component_type", "lifecycle", "rohs", "mounting_type"),
    applicable=_COMMON_APPLICABLE + ("reach", "pin_count", "supply_voltage"),
    facets=("package", "mounting_type", "operating_temperature", "lifecycle"),
    comparison=("package", "operating_temperature", "lifecycle"),
    cad_relationships=_PACKAGE_CAD,
)


CATEGORY_SCHEMAS: tuple[CategorySchema, ...] = (
    # ------------------------------------------------------------------ resistors
    CategorySchema(
        key="resistor",
        label="Resistor",
        parent="Resistors",
        signals=("resistor", "chip resistor", "thick film", "thin film", "current sense"),
        groups=(
            "resistance",
            "tolerance_stability",
            "power_derating",
            "temperature_characteristics",
            "pulse_overload",
            "construction_termination",
        ),
        group_overrides={
            "resistance": "resistance",
            "tolerance": "tolerance_stability",
            "stability": "tolerance_stability",
            "noise_level": "tolerance_stability",
            "power_rating": "power_derating",
            "derating_curve": "power_derating",
            "voltage_rating": "power_derating",
            "temperature_coefficient": "temperature_characteristics",
            "pulse_withstand": "pulse_overload",
            "composition": "construction_termination",
            "termination_style": "construction_termination",
            "case_code": "construction_termination",
        },
        key_specs=(
            "resistance",
            "tolerance",
            "power_rating",
            "voltage_rating",
            "temperature_coefficient",
            "composition",
            "package",
            "mounting_type",
        ),
        expected=("resistance", "tolerance", "power_rating", "package", "operating_temperature"),
        recommended=(
            "voltage_rating",
            "temperature_coefficient",
            "composition",
            "mounting_type",
            "case_code",
            "lifecycle",
            "rohs",
        ),
        applicable=_COMMON_APPLICABLE
        + ("termination_style", "pulse_withstand", "stability", "noise_level", "size_dimension",
           "height", "reach", "flammability_rating", "derating_curve"),
        not_applicable=("pin_count", "supply_voltage", "interface", "program_memory_size"),
        units={"resistance": "Ω", "power_rating": "W", "tolerance": "%",
               "temperature_coefficient": "ppm", "voltage_rating": "V"},
        constraints={
            "resistance": Constraint(minimum=0.0, unit="Ω", note="Resistance cannot be negative."),
            "power_rating": Constraint(minimum=0.0, unit="W"),
            "tolerance": Constraint(minimum=0.0, maximum=100.0, unit="%"),
        },
        facets=("resistance", "tolerance", "power_rating", "package", "mounting_type",
                "composition", "temperature_coefficient"),
        comparison=("resistance", "tolerance", "power_rating", "voltage_rating",
                    "temperature_coefficient", "package"),
        cad_relationships=_PACKAGE_CAD,
    ),
    # ------------------------------------------------------------------ capacitors
    CategorySchema(
        key="capacitor",
        label="Capacitor",
        parent="Capacitors",
        signals=("capacitor", "mlcc", "ceramic capacitor", "electrolytic", "tantalum"),
        groups=("capacitance", "tolerance_stability", "temperature_characteristics",
                "construction_termination"),
        group_overrides={
            "capacitance": "capacitance",
            "tolerance": "tolerance_stability",
            "dielectric": "temperature_characteristics",
            "temperature_coefficient": "temperature_characteristics",
            "case_code": "construction_termination",
            "termination_style": "construction_termination",
        },
        key_specs=("capacitance", "tolerance", "voltage_rating", "dielectric", "esr",
                   "package", "mounting_type"),
        expected=("capacitance", "tolerance", "voltage_rating", "package",
                  "operating_temperature"),
        recommended=("dielectric", "mounting_type", "case_code", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("esr", "termination_style", "height", "size_dimension",
                                         "reach", "temperature_coefficient"),
        not_applicable=("pin_count", "interface", "program_memory_size"),
        units={"capacitance": "F", "voltage_rating": "V", "tolerance": "%", "esr": "Ω"},
        constraints={
            "capacitance": Constraint(minimum=0.0, unit="F"),
            "voltage_rating": Constraint(minimum=0.0, unit="V"),
        },
        facets=("capacitance", "voltage_rating", "dielectric", "tolerance", "package"),
        comparison=("capacitance", "tolerance", "voltage_rating", "dielectric", "package"),
        cad_relationships=_PACKAGE_CAD,
    ),
    # ------------------------------------------------------------------ inductors
    CategorySchema(
        key="inductor",
        label="Inductor",
        parent="Inductors",
        signals=("inductor", "ferrite bead", "common mode choke", "power inductor"),
        groups=("inductance", "tolerance_stability", "construction_termination"),
        group_overrides={"inductance": "inductance", "tolerance": "tolerance_stability",
                         "case_code": "construction_termination"},
        key_specs=("inductance", "tolerance", "current_rating", "dc_resistance",
                   "max_frequency", "package"),
        expected=("inductance", "current_rating", "package", "operating_temperature"),
        recommended=("tolerance", "dc_resistance", "mounting_type", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("max_frequency", "height", "size_dimension", "reach"),
        not_applicable=("pin_count", "interface", "program_memory_size"),
        units={"inductance": "H", "current_rating": "A", "dc_resistance": "Ω"},
        constraints={"inductance": Constraint(minimum=0.0, unit="H")},
        facets=("inductance", "current_rating", "dc_resistance", "package"),
        comparison=("inductance", "tolerance", "current_rating", "dc_resistance", "package"),
        cad_relationships=_PACKAGE_CAD,
    ),
    # ------------------------------------------------------------------ diodes
    CategorySchema(
        key="diode",
        label="Diode",
        parent="Diodes",
        signals=("diode", "tvs", "schottky", "zener", "rectifier", "esd protection"),
        groups=("junction_characteristics", "switching_characteristics"),
        group_overrides={"leakage_current": "junction_characteristics"},
        key_specs=("component_type", "voltage_rating", "current_rating", "capacitance",
                   "channels", "package"),
        expected=("component_type", "voltage_rating", "package", "operating_temperature"),
        recommended=("current_rating", "channels", "capacitance", "mounting_type", "lifecycle",
                     "rohs"),
        applicable=_COMMON_APPLICABLE + ("leakage_current", "power_rating", "polarity",
                                         "pin_count", "reach"),
        not_applicable=("program_memory_size", "interface"),
        units={"voltage_rating": "V", "current_rating": "A", "capacitance": "F"},
        facets=("component_type", "voltage_rating", "current_rating", "channels", "package"),
        comparison=("voltage_rating", "current_rating", "capacitance", "package"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ transistors
    CategorySchema(
        key="transistor",
        label="Transistor",
        parent="Transistors",
        signals=("mosfet", "transistor", "bjt", "igbt", "jfet"),
        groups=("junction_characteristics", "switching_characteristics"),
        key_specs=("component_type", "polarity", "voltage_rating", "current_rating",
                   "dc_resistance", "power_rating", "package"),
        expected=("component_type", "voltage_rating", "current_rating", "package",
                  "operating_temperature"),
        recommended=("polarity", "power_rating", "dc_resistance", "mounting_type", "lifecycle",
                     "rohs"),
        applicable=_COMMON_APPLICABLE + ("pin_count", "leakage_current", "rise_fall_time",
                                         "reach"),
        not_applicable=("program_memory_size", "interface"),
        units={"voltage_rating": "V", "current_rating": "A", "power_rating": "W"},
        facets=("component_type", "polarity", "voltage_rating", "current_rating", "package"),
        comparison=("voltage_rating", "current_rating", "dc_resistance", "power_rating",
                    "package"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ microcontrollers
    CategorySchema(
        key="microcontroller",
        label="Microcontroller",
        parent="ICs",
        signals=("microcontroller", "mcu", "cortex-m", "cortex m", "arm cortex", "risc-v mcu",
                 "8-bit microcontroller", "32-bit microcontroller", "soc", "application processor"),
        groups=(
            "processor_architecture",
            "memory",
            "clocks",
            "analog_digital_peripherals",
            "communication_interfaces",
            "security_debug",
            "power_modes",
        ),
        group_overrides={
            "supply_voltage": "power",
            "quiescent_current": "power",
            "max_frequency": "clocks",
        },
        key_specs=(
            "core_processor",
            "cpu_speed",
            "program_memory_size",
            "ram_size",
            "supply_voltage",
            "io_count",
            "connectivity",
            "package",
        ),
        expected=(
            "core_processor",
            "program_memory_size",
            "ram_size",
            "supply_voltage",
            "package",
            "pin_count",
            "operating_temperature",
        ),
        recommended=(
            "cpu_speed",
            "core_size",
            "io_count",
            "connectivity",
            "peripherals",
            "adc_channels",
            "adc_resolution",
            "oscillator_type",
            "debug_interface",
            "mounting_type",
            "lifecycle",
            "rohs",
        ),
        applicable=_COMMON_APPLICABLE
        + ("eeprom_size", "dac_channels", "timers", "usb_support", "ethernet_support",
           "can_support", "security_features", "standby_current", "power_modes",
           "quiescent_current", "instruction_set", "core_count", "fpu", "clock_sources",
           "external_memory_interface", "program_memory_type", "interface", "reach",
           "max_frequency"),
        not_applicable=("resistance", "capacitance", "inductance", "positions", "pitch",
                        "mating_cycles"),
        units={"program_memory_size": "B", "ram_size": "B", "eeprom_size": "B",
               "cpu_speed": "Hz", "supply_voltage": "V", "adc_resolution": "bit"},
        constraints={
            "program_memory_size": Constraint(minimum=0.0, unit="B"),
            "ram_size": Constraint(minimum=0.0, unit="B"),
            "pin_count": Constraint(minimum=1.0),
        },
        facets=("core_processor", "program_memory_size", "ram_size", "cpu_speed",
                "supply_voltage", "package", "pin_count", "connectivity"),
        comparison=("core_processor", "cpu_speed", "program_memory_size", "ram_size",
                    "io_count", "supply_voltage", "package", "pin_count"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ logic gates
    CategorySchema(
        key="logic_gate",
        label="Logic Gate",
        parent="ICs",
        signals=("logic gate", "nand gate", "nor gate", "and gate", "or gate", "xor gate",
                 "inverter", "buffer gate", "single gate", "logic inverter", "gates and inverters",
                 "schmitt trigger inverter"),
        groups=(),
        group_overrides={"supply_voltage": "power", "max_frequency": "timing_performance"},
        key_specs=(
            "gate_function",
            "logic_family",
            "channels",
            "inputs_per_gate",
            "supply_voltage",
            "propagation_delay",
            "output_drive_current",
            "package",
        ),
        expected=(
            "gate_function",
            "logic_family",
            "channels",
            "supply_voltage",
            "package",
            "pin_count",
            "operating_temperature",
        ),
        recommended=(
            "inputs_per_gate",
            "propagation_delay",
            "output_drive_current",
            "output_type",
            "input_voltage_high",
            "input_voltage_low",
            "schmitt_trigger",
            "mounting_type",
            "lifecycle",
            "rohs",
        ),
        applicable=_COMMON_APPLICABLE
        + ("output_voltage_high", "output_voltage_low", "quiescent_current", "rise_fall_time",
           "max_frequency", "reach", "esd_rating"),
        not_applicable=("program_memory_size", "ram_size", "cpu_speed", "core_processor",
                        "resistance", "capacitance", "positions", "pitch", "mating_cycles"),
        units={"supply_voltage": "V", "propagation_delay": "s", "output_drive_current": "A"},
        constraints={
            "channels": Constraint(minimum=1.0),
            "inputs_per_gate": Constraint(minimum=1.0),
            "pin_count": Constraint(minimum=2.0),
        },
        facets=("gate_function", "logic_family", "channels", "supply_voltage", "package",
                "output_type"),
        comparison=("gate_function", "logic_family", "channels", "supply_voltage",
                    "propagation_delay", "output_drive_current", "package"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ regulators
    CategorySchema(
        key="voltage_regulator",
        label="Voltage Regulator",
        parent="ICs",
        signals=("voltage regulator", "ldo", "buck converter", "boost converter",
                 "dc dc converter", "switching regulator", "step-down", "step down regulator"),
        groups=("power_modes",),
        group_overrides={"supply_voltage": "input_characteristics"},
        key_specs=("component_type", "supply_voltage", "output_voltage", "output_current",
                   "max_frequency", "quiescent_current", "efficiency", "package"),
        expected=("supply_voltage", "output_voltage", "output_current", "package",
                  "operating_temperature"),
        recommended=("component_type", "max_frequency", "quiescent_current", "topology",
                     "pin_count", "mounting_type", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("efficiency", "standby_current", "features", "reach"),
        not_applicable=("program_memory_size", "positions", "pitch", "mating_cycles"),
        units={"supply_voltage": "V", "output_voltage": "V", "output_current": "A",
               "max_frequency": "Hz"},
        facets=("output_voltage", "output_current", "supply_voltage", "topology", "package"),
        comparison=("supply_voltage", "output_voltage", "output_current", "quiescent_current",
                    "package"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ amplifiers
    CategorySchema(
        key="amplifier",
        label="Amplifier",
        parent="ICs",
        signals=("operational amplifier", "op amp", "opamp", "instrumentation amplifier",
                 "comparator", "audio amplifier"),
        groups=(),
        key_specs=("component_type", "channels", "supply_voltage", "bandwidth", "slew_rate",
                   "output_current", "package"),
        expected=("channels", "supply_voltage", "package", "operating_temperature"),
        recommended=("bandwidth", "slew_rate", "output_current", "pin_count", "mounting_type",
                     "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("noise_level", "quiescent_current", "reach"),
        not_applicable=("program_memory_size", "positions", "pitch", "mating_cycles"),
        units={"supply_voltage": "V", "bandwidth": "Hz"},
        facets=("channels", "supply_voltage", "bandwidth", "package"),
        comparison=("channels", "supply_voltage", "bandwidth", "slew_rate", "package"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ generic IC
    CategorySchema(
        key="integrated_circuit",
        label="Integrated Circuit",
        parent="ICs",
        signals=(),
        groups=("communication_interfaces",),
        key_specs=("component_type", "function", "supply_voltage", "interface", "channels",
                   "max_frequency", "package", "pin_count"),
        expected=("supply_voltage", "package", "pin_count", "operating_temperature"),
        recommended=("component_type", "function", "interface", "channels", "mounting_type",
                     "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("max_frequency", "output_type", "features",
                                         "quiescent_current", "reach"),
        not_applicable=("positions", "pitch", "mating_cycles", "resistance"),
        units={"supply_voltage": "V", "max_frequency": "Hz"},
        facets=("component_type", "supply_voltage", "interface", "package", "pin_count"),
        comparison=("supply_voltage", "interface", "channels", "package", "pin_count"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ connectors
    CategorySchema(
        key="connector",
        label="Connector",
        parent="Connectors",
        signals=("connector", "header", "receptacle", "terminal block", "socket", "usb connector",
                 "card edge"),
        groups=(
            "contact_configuration",
            "pitch_spacing",
            "mounting",
            "mating_retention",
            "electrical_ratings",
            "mechanical_durability",
            "materials_plating",
        ),
        group_overrides={
            "current_rating": "electrical_ratings",
            "voltage_rating": "electrical_ratings",
            "contact_resistance": "electrical_ratings",
            "insulation_resistance": "electrical_ratings",
            "dielectric_withstanding_voltage": "electrical_ratings",
            "pin_count": "contact_configuration",
        },
        key_specs=(
            "positions",
            "rows",
            "pitch",
            "gender",
            "mounting_type",
            "current_rating",
            "contact_plating",
            "mating_cycles",
        ),
        expected=("positions", "pitch", "gender", "mounting_type", "current_rating",
                  "operating_temperature"),
        recommended=("rows", "voltage_rating", "contact_plating", "mating_cycles",
                     "mounting_angle", "retention_type", "housing_material", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE
        + ("contact_material", "contact_type", "contact_resistance", "insulation_resistance",
           "dielectric_withstanding_voltage", "insertion_force", "withdrawal_force", "mates_with",
           "row_spacing", "ports", "color", "height", "size_dimension", "package",
           "flammability_rating", "ingress_protection", "reach", "termination_style"),
        not_applicable=("program_memory_size", "ram_size", "cpu_speed", "core_processor",
                        "supply_voltage", "resistance", "capacitance", "propagation_delay",
                        "gate_function", "logic_family"),
        units={"pitch": "mm", "current_rating": "A", "voltage_rating": "V",
               "contact_resistance": "Ω", "insulation_resistance": "Ω"},
        constraints={
            "positions": Constraint(minimum=1.0),
            "pitch": Constraint(minimum=0.0, unit="mm"),
            "mating_cycles": Constraint(minimum=0.0),
        },
        facets=("positions", "pitch", "rows", "gender", "mounting_type", "current_rating",
                "contact_plating"),
        comparison=("positions", "rows", "pitch", "gender", "current_rating", "voltage_rating",
                    "mating_cycles", "contact_plating"),
        cad_relationships=(
            CadRelationship("positions", "symbol", "pins_vs_positions",
                            "The symbol must carry one pin per specified position."),
            CadRelationship("positions", "footprint", "pads_vs_positions",
                            "The footprint must carry one pad per specified position."),
            CadRelationship("pitch", "footprint", "pitch_vs_footprint",
                            "The footprint pad spacing must be the specified pitch."),
            CadRelationship("mounting_type", "footprint", "mounting_vs_footprint",
                            "A through-hole part cannot carry a surface-mount footprint."),
        ),
    ),
    # ------------------------------------------------------------------ switches
    CategorySchema(
        key="switch",
        label="Switch",
        parent="Switches",
        signals=("switch", "tactile", "pushbutton", "dip switch", "rotary switch", "slide switch"),
        groups=("contact_configuration", "mounting", "mechanical_durability"),
        group_overrides={"current_rating": "electrical_ratings",
                         "voltage_rating": "electrical_ratings"},
        key_specs=("component_type", "configuration", "current_rating", "voltage_rating",
                   "mounting_type", "mating_cycles", "package"),
        expected=("component_type", "current_rating", "voltage_rating", "mounting_type",
                  "operating_temperature"),
        recommended=("configuration", "mating_cycles", "contact_resistance", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("actuator_type", "height", "size_dimension", "color",
                                         "package", "reach", "insertion_force"),
        not_applicable=("program_memory_size", "supply_voltage", "propagation_delay"),
        units={"current_rating": "A", "voltage_rating": "V"},
        facets=("component_type", "configuration", "current_rating", "mounting_type"),
        comparison=("configuration", "current_rating", "voltage_rating", "mating_cycles"),
        cad_relationships=_PACKAGE_CAD,
    ),
    # ------------------------------------------------------------------ fuses
    CategorySchema(
        key="fuse",
        label="Fuse",
        parent="Fuses",
        signals=("fuse", "ptc", "resettable fuse", "circuit protection"),
        groups=("pulse_overload",),
        key_specs=("current_rating", "voltage_rating", "component_type", "dc_resistance",
                   "package", "mounting_type"),
        expected=("current_rating", "voltage_rating", "package", "operating_temperature"),
        recommended=("component_type", "dc_resistance", "mounting_type", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("pulse_withstand", "size_dimension", "reach"),
        not_applicable=("program_memory_size", "supply_voltage", "interface"),
        units={"current_rating": "A", "voltage_rating": "V", "dc_resistance": "Ω"},
        facets=("current_rating", "voltage_rating", "component_type", "package"),
        comparison=("current_rating", "voltage_rating", "dc_resistance", "package"),
        cad_relationships=_PACKAGE_CAD,
    ),
    # ------------------------------------------------------------------ crystals
    CategorySchema(
        key="crystal_oscillator",
        label="Crystal Or Oscillator",
        parent="Crystals & Oscillators",
        signals=("crystal", "oscillator", "resonator", "tcxo", "vcxo"),
        groups=("frequency_stability",),
        group_overrides={"max_frequency": "frequency_stability"},
        key_specs=("max_frequency", "frequency_tolerance", "frequency_stability", "capacitance",
                   "esr", "package"),
        expected=("max_frequency", "frequency_tolerance", "package", "operating_temperature"),
        recommended=("frequency_stability", "capacitance", "esr", "supply_voltage",
                     "mounting_type", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("size_dimension", "height", "output_type", "reach"),
        not_applicable=("program_memory_size", "positions", "pitch"),
        units={"max_frequency": "Hz", "frequency_tolerance": "ppm", "capacitance": "F",
               "esr": "Ω"},
        facets=("max_frequency", "frequency_tolerance", "package", "mounting_type"),
        comparison=("max_frequency", "frequency_tolerance", "frequency_stability", "capacitance",
                    "package"),
        cad_relationships=_PACKAGE_CAD,
    ),
    # ------------------------------------------------------------------ sensors
    CategorySchema(
        key="sensor",
        label="Sensor",
        parent="Sensors",
        signals=("sensor", "accelerometer", "temperature sensor", "imu", "hall effect"),
        groups=("communication_interfaces", "analog_digital_peripherals"),
        key_specs=("component_type", "supply_voltage", "interface", "adc_resolution",
                   "output_type", "operating_temperature", "package"),
        expected=("component_type", "supply_voltage", "interface", "package",
                  "operating_temperature"),
        recommended=("output_type", "adc_resolution", "quiescent_current", "pin_count",
                     "mounting_type", "lifecycle", "rohs"),
        applicable=_COMMON_APPLICABLE + ("features", "standby_current", "reach",
                                         "ingress_protection"),
        not_applicable=("positions", "pitch", "mating_cycles"),
        units={"supply_voltage": "V", "adc_resolution": "bit"},
        facets=("component_type", "interface", "supply_voltage", "package"),
        comparison=("component_type", "supply_voltage", "interface", "adc_resolution",
                    "package"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ modules
    CategorySchema(
        key="module",
        label="Module",
        parent="Modules",
        signals=("module", "wireless module", "rf module", "development board"),
        groups=("communication_interfaces", "power_modes"),
        key_specs=("component_type", "supply_voltage", "interface", "max_frequency",
                   "connectivity", "mounting_type", "size_dimension"),
        expected=("supply_voltage", "interface", "operating_temperature", "size_dimension"),
        recommended=("component_type", "max_frequency", "connectivity", "mounting_type",
                     "lifecycle", "rohs", "package"),
        applicable=_COMMON_APPLICABLE + ("features", "quiescent_current", "standby_current",
                                         "pin_count", "reach", "height"),
        not_applicable=("positions", "pitch", "resistance", "capacitance"),
        units={"supply_voltage": "V", "max_frequency": "Hz"},
        facets=("component_type", "interface", "supply_voltage", "connectivity"),
        comparison=("supply_voltage", "interface", "max_frequency", "size_dimension"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
    # ------------------------------------------------------------------ electromechanical
    CategorySchema(
        key="electromechanical",
        label="Electromechanical",
        parent="Electromechanical",
        signals=("relay", "buzzer", "speaker", "motor", "fan", "solenoid"),
        groups=("contact_configuration", "mounting", "mechanical_durability"),
        group_overrides={"current_rating": "electrical_ratings",
                         "voltage_rating": "electrical_ratings"},
        key_specs=("component_type", "configuration", "supply_voltage", "current_rating",
                   "voltage_rating", "mounting_type", "package"),
        expected=("component_type", "supply_voltage", "current_rating", "operating_temperature"),
        recommended=("configuration", "voltage_rating", "mounting_type", "mating_cycles",
                     "lifecycle", "rohs", "package"),
        applicable=_COMMON_APPLICABLE + ("max_frequency", "size_dimension", "height", "reach",
                                         "ingress_protection"),
        not_applicable=("program_memory_size", "propagation_delay", "pitch"),
        units={"supply_voltage": "V", "current_rating": "A", "voltage_rating": "V"},
        facets=("component_type", "supply_voltage", "current_rating", "mounting_type"),
        comparison=("component_type", "supply_voltage", "current_rating", "voltage_rating"),
        cad_relationships=_PACKAGE_CAD + _PIN_CAD,
    ),
)


SCHEMAS_BY_KEY: dict[str, CategorySchema] = {item.key: item for item in CATEGORY_SCHEMAS}
SCHEMAS_BY_KEY[BASE_SCHEMA.key] = BASE_SCHEMA

# Filed category -> the schema that answers when no signal fires. The FIRST schema registered
# for a category is its default, which is why the generic entry is registered last within each
# family and the specific ones lead.
_CATEGORY_DEFAULTS: dict[str, CategorySchema] = {}
for _schema in CATEGORY_SCHEMAS:
    if _schema.parent and _schema.parent not in _CATEGORY_DEFAULTS:
        _CATEGORY_DEFAULTS[_schema.parent] = _schema
# ICs default to the generic integrated circuit, never to the first specific refinement: a part
# filed under ICs with nothing identifying it is an IC, not a microcontroller.
_CATEGORY_DEFAULTS["ICs"] = SCHEMAS_BY_KEY["integrated_circuit"]

# Spec keys whose VALUE names what the part is. Their values are searched for signals; the key
# names themselves never are, because every category carries a "Type".
_IDENTIFYING_SPEC_KEYS: frozenset[str] = frozenset(
    {
        "type",
        "component type",
        "product type",
        "device type",
        "part type",
        "function",
        "device function",
        "family",
        "series",
        "logic type",
        "product category",
        "category",
        "subcategory",
        "technology",
        "topology",
    }
)


def _signal_text(record) -> str:
    """The part's own words, folded into one searchable string.

    Deliberately not every spec value: a signal search across a whole spec bag matches the word
    "buffer" inside an unrelated parameter and refiles the part on a coincidence.
    """
    parts: list[str] = [
        str(getattr(record, "description", "") or ""),
        str(getattr(record, "display_name", "") or ""),
        str(getattr(record, "mpn", "") or ""),
        " ".join(str(tag) for tag in (getattr(record, "tags", None) or [])),
    ]
    specs = getattr(record, "specs", None) or {}
    for key, value in specs.items():
        if normalize_key(key) in _IDENTIFYING_SPEC_KEYS and isinstance(value, (str, int, float)):
            parts.append(str(value))
    return " ".join(parts).casefold()


def resolve_schema(record) -> CategorySchema:
    """The schema that describes this component.

    Scoped to the filed category first, so a signal word appearing in a resistor's description
    can never describe it with a microcontroller's schema. Within the category the schema with
    the most matching signals wins, and the registry's own order settles a tie - so the answer
    is stable rather than dependent on how the description happens to be worded.
    """
    category = str(getattr(record, "category", "") or "").strip()
    candidates = [item for item in CATEGORY_SCHEMAS if item.parent == category]
    if not candidates:
        return _CATEGORY_DEFAULTS.get(category, BASE_SCHEMA)
    text = _signal_text(record)
    best: CategorySchema | None = None
    best_score = 0
    for schema in candidates:
        score = sum(1 for signal in schema.signals if signal in text)
        if score > best_score:
            best, best_score = schema, score
    if best is not None:
        return best
    return _CATEGORY_DEFAULTS.get(category, BASE_SCHEMA)


__all__ = [
    "BASE_SCHEMA",
    "CATEGORY_SCHEMAS",
    "SCHEMAS_BY_KEY",
    "CadRelationship",
    "CategorySchema",
    "Constraint",
    "resolve_schema",
]
