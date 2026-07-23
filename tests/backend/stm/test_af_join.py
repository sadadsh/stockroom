"""Phase 2: the AF0-15 alternate-function mux join (DATA-04).

Joins each device's declared GPIO IP version (`mcu_peripheral` row WHERE
peripheral_name = 'GPIO', matched EXACTLY - never a substring test) to its
`GPIO-<version>_Modes.xml`, and lands `pin_alternate_function` rows keyed by
`raw_pin_name` (never `canonical_pin_name` - PINREMAP/`_C`-suffix duplicate
balls collide under the regex-collapsed canonical name). A device whose
declared version has no matching Modes file on disk fails the build loudly
(the literal 100%-join-resolution gate); F1's classic AFIO-remap tokens
(`__HAL_AFIO_REMAP_*`) are architecturally zero-AF-row and must NOT trip that
gate, while any genuinely unrecognized value shape must.

Fixtures (tests/backend/fixtures/stm/af_join/<case>/, synthetic, 2-3 pins each):
  happy/       - clean AF0-15 join, an LPBAMLPGPIO substring-trap peripheral,
                 and a Modes-file superset entry (PA9) absent from the device.
  f1_legacy/   - every GPIO_AF value is a __HAL_AFIO_REMAP_* token, nested one
                 level deeper under a RemapBlock (the real F1 XML shape).
  gate_missing/- a declared GPIO version with no matching Modes.xml at all.
  anomaly/     - a GPIO_AF value matching neither shape (genuine parse defect).
  pinremap/    - two same-position Pin identities (Variant="PINREMAP").
  c_suffix/    - a plain PC2 ball and a separate PC2_C ball on one MCU.

tests/backend/fixtures/stm/IP/ also carries the REAL GPIO Modes files backing
Phase 1's four committed device-XML fixtures (STM32F030RCTx -> F091,
STM32F048C6Ux -> F042, STM32F072RBIx -> F052, STM32F407V(E-G)Tx -> F417) so
every existing `StmIndex.build(FIXTURES)` call in the Phase 1 test suite keeps
resolving its AF join cleanly, with zero orphans, rather than breaking once
this module wires AF ingest into the shared build loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.stm import db as db_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"
AF_FIXTURES = FIXTURES / "af_join"


def _mcu_id(conn, ref_name: str) -> int:
    row = conn.execute("SELECT id FROM mcu WHERE ref_name = ?", (ref_name,)).fetchone()
    assert row is not None, f"no mcu row for {ref_name}"
    return row["id"]


def _af_rows(conn, mcu_id: int, raw_pin_name: str) -> list[tuple[int, str, str]]:
    return conn.execute(
        "SELECT af.af_index, af.signal, af.peripheral FROM pin_alternate_function af "
        "JOIN mcu_package_pin p ON p.id = af.mcu_package_pin_id "
        "WHERE p.mcu_id = ? AND p.raw_pin_name = ? ORDER BY af.af_index",
        (mcu_id, raw_pin_name),
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: end-to-end happy-path join
# ─────────────────────────────────────────────────────────────────────────────
def test_happy_path_af_join_lands_correct_rows_at_right_pin():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    conn = idx._conn
    mcu_id = _mcu_id(conn, "SYNTH_AF_HAPPY_Tx")

    pa0_rows = _af_rows(conn, mcu_id, "PA0")
    assert [(r["af_index"], r["signal"], r["peripheral"]) for r in pa0_rows] == [
        (1, "USART1_TX", "USART1"),
        (2, "TIM2_CH1", "TIM2"),
    ]

    pa1_rows = _af_rows(conn, mcu_id, "PA1")
    assert [(r["af_index"], r["signal"], r["peripheral"]) for r in pa1_rows] == [
        (2, "TIM2_CH2", "TIM2"),
    ]


def test_af_index_and_peripheral_parsed_from_possible_value_never_a_bare_index():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    conn = idx._conn
    mcu_id = _mcu_id(conn, "SYNTH_AF_HAPPY_Tx")
    row = conn.execute(
        "SELECT af.af_index, af.signal, af.peripheral FROM pin_alternate_function af "
        "JOIN mcu_package_pin p ON p.id = af.mcu_package_pin_id "
        "WHERE p.mcu_id = ? AND p.raw_pin_name = 'PA0' AND af.af_index = 1",
        (mcu_id,),
    ).fetchone()
    assert row is not None
    assert row["signal"] == "USART1_TX"
    assert row["peripheral"] == "USART1"
    assert row["signal"] is not None and row["peripheral"] is not None


def test_modes_file_superset_entry_with_no_matching_device_pin_is_skipped_not_errored():
    # PA9 exists in the Modes file's GPIO_Pin universe but not among this
    # device's own declared pins (PA0/PA1/PA2) - shared-Modes-file superset
    # case; must be silently skipped, never gate-counted or raised.
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    conn = idx._conn
    n = conn.execute(
        "SELECT COUNT(*) FROM pin_alternate_function af "
        "JOIN mcu_package_pin p ON p.id = af.mcu_package_pin_id "
        "WHERE p.raw_pin_name = 'PA9'"
    ).fetchone()[0]
    assert n == 0


def test_gpio_version_resolved_by_exact_name_never_a_substring_match():
    # The fixture also declares an <IP Name="LPBAMLPGPIO" Version=
    # "BOGUS_NONEXISTENT_v1_0"/> - a version with NO matching Modes file. A
    # substring/LIKE '%GPIO%' bug would try to resolve THIS version (since
    # "LPBAMLPGPIO" contains "GPIO") and raise on it; the exact-Name join
    # must ignore it entirely and build cleanly.
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    conn = idx._conn
    mcu_id = _mcu_id(conn, "SYNTH_AF_HAPPY_Tx")
    total = conn.execute(
        "SELECT COUNT(*) FROM pin_alternate_function af "
        "JOIN mcu_package_pin p ON p.id = af.mcu_package_pin_id WHERE p.mcu_id = ?",
        (mcu_id,),
    ).fetchone()[0]
    assert total == 3  # PA0 x2 + PA1 x1, none from the bogus LPBAMLPGPIO version


def test_pin_alternate_function_table_and_indices_exist_in_schema():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    conn = idx._conn
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "pin_alternate_function" in tables
    indices = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "ix_af_pin" in indices
    assert "ix_af_signal" in indices


def test_existing_phase1_fixtures_still_resolve_their_af_join_cleanly():
    # The four real Phase 1 device-XML fixtures each declare a real GPIO IP
    # version; tests/backend/fixtures/stm/IP/ carries the matching real
    # GPIO-<version>_Modes.xml for each, so the shared FIXTURES build (used
    # throughout the rest of the Phase 1 suite) must keep resolving cleanly
    # rather than raising once AF ingest is wired into the build loop.
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn
    assert idx.mcu_count() == 4
    total = conn.execute("SELECT COUNT(*) FROM pin_alternate_function").fetchone()[0]
    assert total > 0


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: the 100%-join-resolution gate + the F1 legacy-AFIO exception
# ─────────────────────────────────────────────────────────────────────────────
def test_unresolvable_gpio_version_makes_build_raise_naming_version_and_device():
    with pytest.raises(db_mod.StmGpioModesNotFoundError) as exc_info:
        db_mod.StmIndex.build(AF_FIXTURES / "gate_missing")
    msg = str(exc_info.value)
    assert "NO_SUCH_VERSION_v9_9" in msg


def test_f1_legacy_afio_remap_yields_zero_rows_and_does_not_raise():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "f1_legacy")
    conn = idx._conn
    mcu_id = _mcu_id(conn, "SYNTH_F1_LEGACY_Tx")
    n = conn.execute(
        "SELECT COUNT(*) FROM pin_alternate_function af "
        "JOIN mcu_package_pin p ON p.id = af.mcu_package_pin_id WHERE p.mcu_id = ?",
        (mcu_id,),
    ).fetchone()[0]
    assert n == 0


def test_is_legacy_afio_remap_recognizes_the_prefix():
    assert db_mod._is_legacy_afio_remap("__HAL_AFIO_REMAP_TIM2_PARTIAL_2") is True
    assert db_mod._is_legacy_afio_remap("GPIO_AF2_TIM2") is False
    assert db_mod._is_legacy_afio_remap("NOT_A_RECOGNIZED_SHAPE_AT_ALL") is False


def test_genuinely_unrecognized_af_value_shape_raises_loudly():
    with pytest.raises(db_mod.StmAfParseError) as exc_info:
        db_mod.StmIndex.build(AF_FIXTURES / "anomaly")
    msg = str(exc_info.value)
    assert "NOT_A_RECOGNIZED_SHAPE_AT_ALL" in msg
