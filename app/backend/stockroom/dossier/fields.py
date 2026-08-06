"""The canonical specification field registry.

A distributor's parameter name is EVIDENCE, not an identifier. `DCR`, `DC Resistance` and
`Resistance - DC` are one field spelled three ways, and a presentation that keyed on the
spelling showed the same fact three times with three different numbers and nothing saying which
was in force. Every raw key resolves through this registry to one canonical field, so a value
from Mouser and a value from LCSC land on the same row and disagree visibly.

A key this registry has never seen is NOT dropped and NOT guessed at: it keeps the source's own
wording, lands in `other`, and is reported as a source-specific field that does not yet map
canonically (`dossier.raw` level two). That is the honest state, and it is also the backlog -
the fix for a key that keeps appearing there is one row here, never a branch anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_key(text: object) -> str:
    """Fold casing and punctuation so `Voltage Rating`, `voltage_rating` and `Voltage - Rating`
    resolve to one registry entry."""
    return _NON_ALNUM.sub(" ", str(text or "").casefold()).strip()


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """One canonical field: what it is called, where it belongs, and how it behaves."""

    key: str
    label: str
    # The universal group this field falls in when a category schema says nothing else. A
    # schema may move it (a resistor's resistance belongs under Resistance, not Electrical),
    # which is a `group_overrides` row rather than a second definition of the same field.
    group: str
    value_type: str = "text"
    # The canonical unit, used only to fill a gap in a bare number. A value's own unit wins.
    unit: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    filterable: bool = True
    sortable: bool = False
    comparable: bool = True


def _f(
    key: str,
    label: str,
    group: str,
    value_type: str = "text",
    unit: str = "",
    aliases: tuple[str, ...] = (),
    *,
    filterable: bool = True,
    sortable: bool = False,
    comparable: bool = True,
) -> FieldDefinition:
    return FieldDefinition(
        key=key,
        label=label,
        group=group,
        value_type=value_type,
        unit=unit,
        aliases=aliases,
        filterable=filterable,
        # A field with a magnitude is sortable by construction; text is not, unless a caller
        # says so. Declared per row rather than inferred so an enum can opt in.
        sortable=sortable or value_type in {"quantity", "integer", "range"},
        comparable=comparable,
    )


FIELDS: tuple[FieldDefinition, ...] = (
    # ---------------------------------------------------------------- functional
    _f("component_type", "Component Type", "functional", "enum",
       aliases=("type", "product type", "device type", "part type")),
    _f("function", "Function", "functional", "enum", aliases=("device function", "circuit")),
    _f("technology", "Technology", "functional", "enum", aliases=("construction technology",)),
    _f("topology", "Topology", "functional", "enum"),
    _f("configuration", "Configuration", "functional", "enum"),
    _f("channels", "Channels", "functional", "integer",
       aliases=("number of channels", "channel count", "circuits", "number of circuits")),
    _f("elements", "Elements", "functional", "integer", aliases=("number of elements",)),
    _f("polarity", "Polarity", "functional", "enum"),
    _f("logic_family", "Logic Family", "functional", "enum",
       aliases=("family", "series family", "logic family")),
    # A distributor's "Logic Type" column names the FUNCTION (`AND Gate`), not the family
    # (`LVC`). Filing it under the family would have made every 74-series part look like it
    # belonged to a family called "AND Gate".
    _f("gate_function", "Gate Function", "functional", "enum",
       aliases=("logic function", "gate type", "boolean function", "logic type")),
    _f("inputs_per_gate", "Inputs Per Gate", "functional", "integer",
       aliases=("number of inputs per gate", "inputs per element")),
    _f("schmitt_trigger", "Schmitt Trigger Input", "functional", "boolean",
       aliases=("schmitt trigger",)),
    _f("output_type", "Output Type", "output_characteristics", "enum",
       aliases=("output configuration", "output stage")),
    _f("features", "Features", "functional", "text", filterable=False),
    _f("applications", "Applications", "functional", "text", filterable=False),
    _f("series", "Series", "manufacturer_information", "enum"),
    _f("part_status", "Part Status", "compliance_lifecycle", "enum"),

    # ---------------------------------------------------------------- electrical
    _f("resistance", "Resistance", "electrical", "quantity", "Ω",
       aliases=("resistance value", "ohms", "nominal resistance")),
    _f("dc_resistance", "DC Resistance", "electrical", "quantity", "Ω",
       aliases=("dcr", "dc resistance dcr", "series resistance")),
    _f("capacitance", "Capacitance", "electrical", "quantity", "F",
       aliases=("capacitance value", "nominal capacitance")),
    _f("inductance", "Inductance", "electrical", "quantity", "H",
       aliases=("inductance value", "nominal inductance")),
    _f("impedance", "Impedance", "electrical", "quantity", "Ω"),
    _f("esr", "ESR", "electrical", "quantity", "Ω",
       aliases=("equivalent series resistance", "esr equivalent series resistance")),
    _f("tolerance", "Tolerance", "electrical", "quantity", "%",
       aliases=("resistance tolerance", "capacitance tolerance", "value tolerance")),
    _f("voltage_rating", "Voltage Rating", "electrical", "quantity", "V",
       aliases=("voltage rated", "voltage rating dc", "rated voltage", "max voltage",
                "maximum voltage", "voltage rating ac", "withstanding voltage")),
    _f("current_rating", "Current Rating", "electrical", "quantity", "A",
       aliases=("rated current", "current rating per contact", "contact current rating")),
    _f("supply_voltage", "Supply Voltage", "power", "range", "V",
       aliases=("voltage supply", "operating voltage", "voltage supply dc",
                "supply voltage range", "input voltage")),
    _f("output_voltage", "Output Voltage", "output_characteristics", "quantity", "V"),
    _f("output_current", "Output Current", "output_characteristics", "quantity", "A",
       aliases=("current output", "output current per channel")),
    _f("input_current", "Input Current", "input_characteristics", "quantity", "A"),
    _f("input_voltage_high", "Input Voltage High", "input_characteristics", "quantity", "V",
       aliases=("vih", "input high voltage")),
    _f("input_voltage_low", "Input Voltage Low", "input_characteristics", "quantity", "V",
       aliases=("vil", "input low voltage")),
    _f("output_voltage_high", "Output Voltage High", "output_characteristics", "quantity", "V",
       aliases=("voh", "output high voltage")),
    _f("output_voltage_low", "Output Voltage Low", "output_characteristics", "quantity", "V",
       aliases=("vol", "output low voltage")),
    _f("output_drive_current", "Output Drive Current", "output_characteristics", "quantity", "A",
       aliases=("current output high low", "drive current", "output sink source current")),
    _f("leakage_current", "Leakage Current", "electrical", "quantity", "A"),
    _f("insulation_resistance", "Insulation Resistance", "electrical_ratings", "quantity", "Ω"),
    _f("contact_resistance", "Contact Resistance", "electrical_ratings", "quantity", "Ω"),
    _f("dielectric_withstanding_voltage", "Dielectric Withstanding Voltage",
       "electrical_ratings", "quantity", "V", aliases=("dielectric withstand voltage",)),
    _f("dielectric", "Dielectric", "electrical", "enum",
       aliases=("dielectric material", "temperature coefficient code")),

    # ---------------------------------------------------------------- power
    _f("power_rating", "Power Rating", "power", "quantity", "W",
       aliases=("power", "power watts", "rated power", "power dissipation")),
    _f("quiescent_current", "Quiescent Current", "power", "quantity", "A",
       aliases=("iq", "supply current", "current supply")),
    _f("standby_current", "Standby Current", "power_modes", "quantity", "A",
       aliases=("sleep current", "shutdown current")),
    _f("power_modes", "Power Modes", "power_modes", "text", filterable=False),
    _f("derating_curve", "Derating", "power_derating", "text", filterable=False,
       aliases=("power derating", "derating")),
    _f("efficiency", "Efficiency", "power", "quantity", "%"),

    # ---------------------------------------------------------------- timing
    _f("propagation_delay", "Propagation Delay", "timing_performance", "quantity", "s",
       aliases=("propagation delay tpd", "delay time", "tpd")),
    _f("rise_fall_time", "Rise / Fall Time", "timing_performance", "quantity", "s",
       aliases=("rise time", "fall time", "transition time")),
    _f("max_frequency", "Maximum Frequency", "timing_performance", "quantity", "Hz",
       aliases=("frequency", "operating frequency", "switching frequency", "clock frequency",
                "max clock frequency", "speed")),
    _f("bandwidth", "Bandwidth", "timing_performance", "quantity", "Hz"),
    _f("slew_rate", "Slew Rate", "timing_performance", "quantity"),
    _f("frequency_tolerance", "Frequency Tolerance", "frequency_stability", "quantity", "ppm"),
    _f("frequency_stability", "Frequency Stability", "frequency_stability", "quantity", "ppm"),

    # ---------------------------------------------------------------- processor
    _f("core_processor", "Core Processor", "processor_architecture", "enum",
       aliases=("core", "cpu core", "processor core", "core processor family")),
    _f("core_size", "Core Size", "processor_architecture", "enum",
       aliases=("data bus width", "bit size", "word size")),
    _f("core_count", "Core Count", "processor_architecture", "integer",
       aliases=("number of cores", "cores")),
    _f("instruction_set", "Instruction Set", "processor_architecture", "enum",
       aliases=("architecture", "isa")),
    _f("fpu", "Floating Point Unit", "processor_architecture", "boolean",
       aliases=("floating point unit",)),
    _f("cpu_speed", "CPU Speed", "clocks", "quantity", "Hz",
       aliases=("speed cpu", "core speed", "max cpu frequency", "clock rate")),
    _f("oscillator_type", "Oscillator Type", "clocks", "enum",
       aliases=("oscillator", "internal oscillator")),
    _f("clock_sources", "Clock Sources", "clocks", "text", filterable=False),

    # ---------------------------------------------------------------- memory
    _f("program_memory_size", "Program Memory Size", "memory", "quantity", "B",
       aliases=("program memory size flash", "flash size", "flash", "program memory")),
    _f("program_memory_type", "Program Memory Type", "memory", "enum"),
    _f("ram_size", "RAM Size", "memory", "quantity", "B",
       aliases=("ram size sram", "sram size", "ram", "data ram size")),
    _f("eeprom_size", "EEPROM Size", "memory", "quantity", "B", aliases=("eeprom",)),
    _f("external_memory_interface", "External Memory Interface", "memory", "enum",
       aliases=("memory interface",)),

    # ---------------------------------------------------------------- peripherals
    _f("peripherals", "Peripherals", "analog_digital_peripherals", "text", filterable=False),
    _f("adc_channels", "ADC Channels", "analog_digital_peripherals", "integer",
       aliases=("number of a d converters", "a d converters", "adc")),
    _f("adc_resolution", "ADC Resolution", "analog_digital_peripherals", "quantity", "bit",
       aliases=("resolution", "converter resolution")),
    _f("dac_channels", "DAC Channels", "analog_digital_peripherals", "integer",
       aliases=("number of d a converters", "d a converters", "dac")),
    _f("timers", "Timers", "analog_digital_peripherals", "text", filterable=False),
    _f("connectivity", "Connectivity", "communication_interfaces", "text", filterable=False),
    _f("interface", "Interface", "communication_interfaces", "enum",
       aliases=("interfaces", "communication interface", "protocol")),
    _f("usb_support", "USB", "communication_interfaces", "enum"),
    _f("ethernet_support", "Ethernet", "communication_interfaces", "enum"),
    _f("can_support", "CAN", "communication_interfaces", "enum"),
    _f("debug_interface", "Debug Interface", "security_debug", "enum",
       aliases=("programming interface", "debug port")),
    _f("security_features", "Security Features", "security_debug", "text", filterable=False,
       aliases=("security", "cryptography", "crypto engine")),

    # ---------------------------------------------------------------- pinout
    _f("pin_count", "Pin Count", "interface_pinout", "integer",
       aliases=("number of pins", "pins", "number of terminations", "pin count total")),
    _f("io_count", "I/O Count", "interface_pinout", "integer",
       aliases=("number of i o", "number of io", "i o count")),
    _f("positions", "Positions", "contact_configuration", "integer",
       aliases=("number of positions", "positions contacts", "number of contacts", "contacts")),
    _f("rows", "Rows", "contact_configuration", "integer", aliases=("number of rows",)),
    _f("ports", "Ports", "contact_configuration", "integer", aliases=("number of ports",)),
    _f("gender", "Gender", "contact_configuration", "enum",
       aliases=("connector gender", "connector type gender")),
    _f("contact_type", "Contact Type", "contact_configuration", "enum"),

    # ---------------------------------------------------------------- mechanical
    _f("package", "Package", "package_mechanical", "enum",
       aliases=("package case", "supplier device package", "case", "case package",
                "package type", "manufacturer package")),
    _f("case_code", "Case Code", "package_mechanical", "enum",
       aliases=("case code in", "case code mm", "size dimension code")),
    _f("mounting_type", "Mounting Type", "mounting", "enum",
       aliases=("mounting", "mounting style", "mount type")),
    _f("mounting_angle", "Mounting Angle", "mounting", "enum", aliases=("orientation",)),
    _f("pitch", "Pitch", "pitch_spacing", "quantity", "mm",
       aliases=("pitch mating", "contact pitch", "row pitch")),
    _f("row_spacing", "Row Spacing", "pitch_spacing", "quantity", "mm"),
    _f("size_dimension", "Size / Dimension", "package_mechanical", "text",
       aliases=("size", "dimensions", "body size")),
    _f("height", "Height", "package_mechanical", "quantity", "mm",
       aliases=("height seated max", "max height")),
    _f("length", "Length", "package_mechanical", "quantity", "mm"),
    _f("width", "Width", "package_mechanical", "quantity", "mm"),
    _f("thickness", "Thickness", "package_mechanical", "quantity", "mm"),
    _f("diameter", "Diameter", "package_mechanical", "quantity", "mm"),
    _f("weight", "Weight", "package_mechanical", "quantity", "g", aliases=("unit weight",)),
    _f("termination_style", "Termination", "construction_termination", "enum",
       aliases=("termination", "terminations", "termination type", "lead style")),
    _f("composition", "Composition", "construction_termination", "enum",
       aliases=("resistive element", "element material")),
    _f("housing_material", "Housing Material", "materials_plating", "enum",
       aliases=("body material", "insulator material")),
    _f("contact_material", "Contact Material", "materials_plating", "enum"),
    _f("contact_plating", "Contact Plating", "materials_plating", "enum",
       aliases=("plating", "contact finish")),
    _f("color", "Color", "package_mechanical", "enum", aliases=("colour",)),
    _f("mating_cycles", "Mating Cycles", "mechanical_durability", "integer",
       aliases=("durability", "insertion cycles", "mating cycles min")),
    _f("insertion_force", "Insertion Force", "mechanical_durability", "quantity"),
    _f("withdrawal_force", "Withdrawal Force", "mechanical_durability", "quantity"),
    _f("retention_type", "Retention", "mating_retention", "enum",
       aliases=("locking feature", "latch", "retention")),
    _f("mates_with", "Mates With", "mating_retention", "text", filterable=False),
    _f("actuator_type", "Actuator", "mechanical_durability", "enum", aliases=("actuator",)),

    # ---------------------------------------------------------------- environment
    _f("operating_temperature", "Operating Temperature", "environmental_reliability", "range",
       "°C", aliases=("operating temperature range", "temperature range",
                      "operating temp", "operating temperature junction")),
    _f("storage_temperature", "Storage Temperature", "environmental_reliability", "range", "°C"),
    _f("temperature_coefficient", "Temperature Coefficient", "temperature_characteristics",
       "quantity", "ppm", aliases=("tempco", "temperature coefficient ppm c")),
    _f("humidity_rating", "Humidity", "environmental_reliability", "text",
       aliases=("humidity", "relative humidity")),
    _f("moisture_sensitivity_level", "Moisture Sensitivity Level", "environmental_reliability",
       "enum", aliases=("msl", "moisture sensitivity level msl")),
    _f("esd_rating", "ESD Rating", "environmental_reliability", "text", aliases=("esd",)),
    _f("flammability_rating", "Flammability Rating", "environmental_reliability", "enum",
       aliases=("flammability",)),
    _f("ingress_protection", "Ingress Protection", "environmental_reliability", "enum",
       aliases=("ip rating", "ingress protection rating")),
    _f("pulse_withstand", "Pulse Withstand", "pulse_overload", "text", filterable=False,
       aliases=("overload", "short time overload", "pulse rating")),
    _f("stability", "Long Term Stability", "tolerance_stability", "text",
       aliases=("load life stability", "long term stability")),
    _f("noise_level", "Noise", "tolerance_stability", "text", aliases=("current noise", "noise")),

    # ---------------------------------------------------------------- compliance
    _f("rohs", "RoHS", "compliance_lifecycle", "enum",
       aliases=("rohs status", "rohs compliant")),
    _f("reach", "REACH", "compliance_lifecycle", "enum", aliases=("reach status",)),
    _f("lifecycle", "Lifecycle", "compliance_lifecycle", "enum",
       aliases=("lifecycle status", "product status", "manufacturing status")),
    _f("qualification", "Qualification", "compliance_lifecycle", "enum",
       aliases=("aec q200", "aec q100", "automotive qualification")),
    _f("ul_rating", "UL Rating", "compliance_lifecycle", "enum"),
    _f("eccn", "ECCN", "compliance_lifecycle", "enum"),
    _f("htsus", "HTS Code", "compliance_lifecycle", "text", filterable=False,
       aliases=("hts code", "htsus code")),
    _f("country_of_origin", "Country Of Origin", "compliance_lifecycle", "enum"),
    _f("lead_time", "Lead Time", "compliance_lifecycle", "text"),
    _f("factory_lead_time", "Factory Lead Time", "compliance_lifecycle", "text"),
    # The distributor page's OWN measured import rate, never a researched one. A confirmed 0%
    # is meaningful data, which is why the unit is carried: a bare `0` reads as an empty cell.
    _f("tariff_rate", "US Tariff", "compliance_lifecycle", "quantity", "%",
       aliases=("us tariff", "us tariff %", "tariff rate")),
    _f("packaging", "Packaging", "manufacturer_information", "enum"),
    _f("minimum_order_quantity", "Minimum Order Quantity", "manufacturer_information", "integer",
       aliases=("moq",)),
    _f("order_multiple", "Order Multiple", "manufacturer_information", "integer"),
    _f("standard_package", "Standard Package", "manufacturer_information", "integer",
       aliases=("standard pack quantity", "standard pack qty")),
    _f("factory_pack_quantity", "Factory Pack Quantity", "manufacturer_information", "integer",
       aliases=("factory pack qty",)),
    _f("manufacturer_part_status", "Manufacturer Part Status", "manufacturer_information",
       "enum"),
    _f("base_part_number", "Base Part Number", "manufacturer_information", "text",
       filterable=False),
)

_INDEX: dict[str, FieldDefinition] = {}
for _definition in FIELDS:
    for _spelling in (_definition.key, _definition.label, *_definition.aliases):
        _INDEX.setdefault(normalize_key(_spelling), _definition)

FIELDS_BY_KEY: dict[str, FieldDefinition] = {item.key: item for item in FIELDS}


def field_for(raw_key: object) -> FieldDefinition | None:
    """The canonical field a raw spec key names, or None when nothing here claims it.

    None is a real answer and is handled rather than papered over: the caller keeps the key
    exactly as the source wrote it and reports it as unmapped, which is both honest to the
    reader and the list of rows this registry still owes.
    """
    return _INDEX.get(normalize_key(raw_key))


def humanize(raw_key: object) -> str:
    """A readable label for a key with no definition, keeping the source's own wording."""
    text = str(raw_key or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else ""


__all__ = [
    "FIELDS",
    "FIELDS_BY_KEY",
    "FieldDefinition",
    "field_for",
    "humanize",
    "normalize_key",
]
