"""Shared records for the dossier tests.

Four real components, deliberately from four different families, because the whole point of the
category schema registry is that these four are not described by the same set of parameters.
"""

from __future__ import annotations

from stockroom.model.part import PartRecord


def logic_gate(**overrides) -> PartRecord:
    base = {
        "id": "sn74lvc1g08dbvr-0001",
        "mpn": "SN74LVC1G08DBVR",
        "manufacturer": "Texas Instruments",
        "display_name": "SN74LVC1G08DBVR",
        "category": "ICs",
        "description": "Single 2-Input AND Gate",
        "specs": {
            "Package / Case": "SOT-23-5",
            "Number of Pins": "5",
            "Voltage - Supply": "1.65V ~ 5.5V",
            "Operating Temperature": "-40C to 125C",
            "Logic Type": "AND Gate",
        },
    }
    base.update(overrides)
    return PartRecord(**base)


def microcontroller(**overrides) -> PartRecord:
    base = {
        "id": "stm32h743vit6-0001",
        "mpn": "STM32H743VIT6",
        "manufacturer": "STMicroelectronics",
        "display_name": "STM32H743VIT6",
        "category": "ICs",
        "description": "Arm Cortex-M7 microcontroller",
        "specs": {
            "Package / Case": "LQFP100",
            "Number of Pins": "100",
            "Core Processor": "ARM Cortex-M7",
            "Program Memory Size": "2 MB",
            "RAM Size": "1 MB",
            "Voltage - Supply": "1.62V ~ 3.6V",
            "Operating Temperature": "-40C to 85C",
        },
    }
    base.update(overrides)
    return PartRecord(**base)


def resistor(**overrides) -> PartRecord:
    base = {
        "id": "erj-p03f1101v-0001",
        "mpn": "ERJ-P03F1101V",
        "manufacturer": "Panasonic",
        "display_name": "ERJ-P03F1101V",
        "category": "Resistors",
        "description": "RES 1.1K OHM 1% 1/5W 0603 thick film",
        "specs": {
            "Resistance": "1.1 kOhms",
            "Tolerance": "1%",
            "Power": "200 mW",
            "Package / Case": "0603",
            "Composition": "Thick Film",
            "Operating Temperature": "-55C to 155C",
        },
    }
    base.update(overrides)
    return PartRecord(**base)


def connector(**overrides) -> PartRecord:
    base = {
        "id": "61300411121-0001",
        "mpn": "61300411121",
        "manufacturer": "Wurth Elektronik",
        "display_name": "61300411121",
        "category": "Connectors",
        "description": "Header connector, 4 position, 2.54mm pitch",
        "specs": {
            "Number of Positions": "4",
            "Pitch": "2.54mm",
            "Gender": "Header",
            "Mounting Type": "Through Hole",
            "Current Rating": "3 A",
            "Operating Temperature": "-25C to 125C",
        },
    }
    base.update(overrides)
    return PartRecord(**base)


def capacitor(**overrides) -> PartRecord:
    """A 100 nF 0402 MLCC, described the way a distributor describes one.

    The description repeats the value and the package, which is ordinary for a distributor and is
    why the identity header has to read line 2 before it decides what lines 3 and 4 say. This is
    also the part that grew a `Memory` and a `Communication Interfaces` heading, because the
    capacitor schema rules `program_memory_size` and `interface` inapplicable and both of those
    keys belong to microcontroller groups.
    """
    base = {
        "id": "cl05b104ko5nnnc-0001",
        "mpn": "CL05B104KO5NNNC",
        "manufacturer": "Samsung",
        "display_name": "100nF 0402",
        "category": "Capacitors",
        "description": "100 nF 16V X7R 0402",
        "specs": {
            "Capacitance": "100 nF",
            "Package": "0402",
        },
    }
    base.update(overrides)
    return PartRecord(**base)


def by_key(specifications) -> dict:
    """Every emitted specification, keyed by its canonical field key."""
    return {item["key"]: item for item in specifications}
