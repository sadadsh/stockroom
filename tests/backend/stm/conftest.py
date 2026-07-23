"""A small, explicit Layer A/B schema fixture for stm/authority.py's unit tests
(stm-viewer workstream, Phase 3, 03-02).

Four MCUs:

- REF_MCU1 / REF_MCU1B: STM32F4, LQFP64, with IDENTICAL per-position facts -
  the "baseline" configuration (compatibility_suggestions groups them together).
- REF_MCU2: STM32F4, LQFP64, diverging from the baseline at a few positions:
  one AF-swappable divergence (position "13"), one un-swappable divergence
  (position "45", no reconciling AF exists), and several positions it simply
  lacks entirely (partial coverage: "34", "29", "30").
- REF_MCU3: STM32F1, LQFP64 - the SAME package_name as the above three, but a
  DIFFERENT family, proving package_family_union/socket_union scope by
  (package, family) TOGETHER, never a bare package string.

Position "29"/"30" (only on MCU1/MCU1B) exercise af_conflicts: both can
alternatively carry the SAME signal (USART3_TX), the double-claim case.
"""

from __future__ import annotations

import sqlite3

import pytest

from stockroom.stm.db import _SCHEMA

REF_MCU1 = "STM32F401VBTx"
REF_MCU1B = "STM32F401RETx"
REF_MCU2 = "STM32F407V(E-G)Tx"
REF_MCU3 = "STM32F103C(8-B)Tx"


def _insert_mcu(conn, art_id, ref_name, family, line, package, pin_count) -> int:
    return conn.execute(
        "INSERT INTO mcu (source_artifact_id, ref_name, family, line, package_name, "
        "pin_count, vdd_min, vdd_max, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (art_id, ref_name, family, line, package, pin_count, "1.8", "3.6",
         "2026-07-23T00:00:00Z"),
    ).lastrowid


def _insert_pin(
    conn, mcu_id, package, position, canonical, raw, pin_type, electrical_class,
    roles=(), functions=(), afs=(), lqfp_side="left",
) -> int:
    """roles: [(role_name, role_class)]; functions: [(signal, io_modes)];
    afs: [(af_index, signal, peripheral)]."""
    pin_id = conn.execute(
        "INSERT INTO mcu_package_pin (mcu_id, package_name, physical_pin_number, "
        "position_kind, bga_row, bga_col, canonical_pin_name, raw_pin_name, pin_type, "
        "electrical_class, gpio_port, gpio_pin_index, lqfp_side) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mcu_id, package, position, "numeric", None, None, canonical, raw, pin_type,
         electrical_class, None, None, lqfp_side),
    ).lastrowid
    for role_name, role_class in roles:
        conn.execute(
            "INSERT INTO pin_role (mcu_package_pin_id, role_name, role_class) VALUES (?,?,?)",
            (pin_id, role_name, role_class),
        )
    for signal, io_modes in functions:
        conn.execute(
            "INSERT INTO pin_function (mcu_package_pin_id, function_name, signal, io_modes) "
            "VALUES (?,?,?,?)",
            (pin_id, signal, signal, io_modes),
        )
    for af_index, signal, peripheral in afs:
        conn.execute(
            "INSERT INTO pin_alternate_function (mcu_package_pin_id, af_index, signal, "
            "peripheral) VALUES (?,?,?,?)",
            (pin_id, af_index, signal, peripheral),
        )
    return pin_id


@pytest.fixture
def stm_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)

    art_id = conn.execute(
        "INSERT INTO source_artifact (path, imported_at) VALUES (?,?)",
        ("/fixture/cubemx", "2026-07-23T00:00:00Z"),
    ).lastrowid

    mcu1 = _insert_mcu(conn, art_id, REF_MCU1, "STM32F4", "STM32F401", "LQFP64", 64)
    mcu1b = _insert_mcu(conn, art_id, REF_MCU1B, "STM32F4", "STM32F401", "LQFP64", 64)
    mcu2 = _insert_mcu(conn, art_id, REF_MCU2, "STM32F4", "STM32F407", "LQFP64", 64)
    mcu3 = _insert_mcu(conn, art_id, REF_MCU3, "STM32F1", "STM32F103", "LQFP64", 64)

    # position "12" (PA9): identical on MCU1/MCU1B/MCU2 -> a SHARED union position.
    for mcu_id in (mcu1, mcu1b, mcu2):
        _insert_pin(
            conn, mcu_id, "LQFP64", "12", "PA9", "PA9", "I/O", "io",
            roles=[("gpio", "io")],
            functions=[("USART1_TX", "In/Out")],
            afs=[(7, "USART1_TX", "USART1")],
        )
    # out-of-family MCU3 ALSO occupies position "12" (same package_name) with a
    # totally different signature - proves the family scope, never a bare package.
    _insert_pin(
        conn, mcu3, "LQFP64", "12", "PA9", "PA9", "Reset", "reset",
        roles=[("reset_nrst", "service")],
    )

    # position "13" (PA10): MCU1/MCU1B declare USART1_RX; MCU2 declares USART2_RX
    # but ALSO offers USART1_RX via an alternate AF (af_index=8) - AF-swappable.
    for mcu_id in (mcu1, mcu1b):
        _insert_pin(
            conn, mcu_id, "LQFP64", "13", "PA10", "PA10", "I/O", "io",
            roles=[("gpio", "io")],
            functions=[("USART1_RX", "In/Out")],
            afs=[(7, "USART1_RX", "USART1")],
        )
    _insert_pin(
        conn, mcu2, "LQFP64", "13", "PA10", "PA10", "I/O", "io",
        roles=[("gpio", "io")],
        functions=[("USART2_RX", "In/Out")],
        afs=[(7, "USART2_RX", "USART2"), (8, "USART1_RX", "USART1")],
    )

    # position "34" (PB2): present on MCU1/MCU1B ONLY - a PARTIAL union position.
    for mcu_id in (mcu1, mcu1b):
        _insert_pin(
            conn, mcu_id, "LQFP64", "34", "PB2", "PB2", "I/O", "io",
            roles=[("gpio", "io")],
        )

    # position "45" (PC4, analog): MCU1/MCU1B declare ADC1_IN14 via AF3; MCU2
    # declares ADC1_IN15 with NO alternate-function row offering ADC1_IN14 -
    # an UN-swappable divergence.
    for mcu_id in (mcu1, mcu1b):
        _insert_pin(
            conn, mcu_id, "LQFP64", "45", "PC4", "PC4", "Analog", "io",
            roles=[("analog", "io")],
            functions=[("ADC1_IN14", "Analog")],
            afs=[(3, "ADC1_IN14", "ADC1")],
        )
    _insert_pin(
        conn, mcu2, "LQFP64", "45", "PC4", "PC4", "Analog", "io",
        roles=[("analog", "io")],
        functions=[("ADC1_IN15", "Analog")],
    )

    # positions "29"/"30" (PA0/PA1), MCU1 + MCU1B (mirrored for compatibility_
    # suggestions grouping): both can alternatively carry USART3_TX - the
    # af_conflicts double-claim fixture.
    for mcu_id in (mcu1, mcu1b):
        _insert_pin(
            conn, mcu_id, "LQFP64", "29", "PA0", "PA0", "I/O", "io",
            roles=[("gpio", "io")],
            functions=[("TIM2_CH1", "In/Out")],
            afs=[(1, "TIM2_CH1", "TIM2"), (7, "USART3_TX", "USART3")],
        )
        _insert_pin(
            conn, mcu_id, "LQFP64", "30", "PA1", "PA1", "I/O", "io",
            roles=[("gpio", "io")],
            functions=[("TIM2_CH2", "In/Out")],
            afs=[(1, "TIM2_CH2", "TIM2"), (7, "USART3_TX", "USART3")],
        )

    conn.commit()
    return conn


@pytest.fixture
def stm_refs():
    return {"mcu1": REF_MCU1, "mcu1b": REF_MCU1B, "mcu2": REF_MCU2, "mcu3": REF_MCU3}
