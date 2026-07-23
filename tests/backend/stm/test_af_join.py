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


# ─────────────────────────────────────────────────────────────────────────────
# Plan 02 Task 1: self-audit AF-range + orphan-join clauses (DATA-07, redundant
# with the schema CHECK / the build-time raise, asserted explicitly)
# ─────────────────────────────────────────────────────────────────────────────
def test_clean_af_build_passes_the_range_and_orphan_audit_clauses():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    db_mod.run_self_audit(idx._conn)  # must not raise


def test_injected_out_of_range_af_index_raises():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    conn = idx._conn
    # af_index carries CHECK(af_index BETWEEN 0 AND 15) - bypass it deliberately
    # so the audit's OWN explicit range check (not just the schema CHECK) is
    # what is actually exercised here.
    conn.execute("PRAGMA ignore_check_constraints = 1")
    conn.execute("UPDATE pin_alternate_function SET af_index = 99 WHERE id = "
                 "(SELECT id FROM pin_alternate_function LIMIT 1)")
    with pytest.raises(db_mod.StmAuditFailure) as exc_info:
        db_mod.run_self_audit(conn)
    assert "AF-range" in str(exc_info.value) or "af_index" in str(exc_info.value)


def test_orphan_join_count_is_zero_on_a_clean_build():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    assert idx.meta()["af_orphan_join_count"] == "0"


def test_injected_nonzero_orphan_join_count_raises():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy")
    conn = idx._conn
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'af_orphan_join_count'")
    with pytest.raises(db_mod.StmAuditFailure) as exc_info:
        db_mod.run_self_audit(conn)
    assert "orphan" in str(exc_info.value).lower()


def test_f1_legacy_family_is_logged_as_accounted_for_and_not_an_orphan(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="stockroom.stm.db"):
        idx = db_mod.StmIndex.build(AF_FIXTURES / "f1_legacy")
    assert idx.meta()["af_orphan_join_count"] == "0"
    assert idx.meta()["af_legacy_afio_device_count"] == "1"
    assert any(
        "legacy AFIO-remap family" in r.message and "1 devices" in r.message
        for r in caplog.records
    )
    db_mod.run_self_audit(idx._conn)  # must not raise - a legitimate zero


# ─────────────────────────────────────────────────────────────────────────────
# Plan 02 Task 2: grain integrity through the PINREMAP and _C-suffix collision
# shapes (GREEN regression locks - Phase 1 already preserves both
# same-position identities; a collapse here is a Phase 1 regression, never an
# accepted gap, and must never be papered over by joining onto whichever
# single row survives)
# ─────────────────────────────────────────────────────────────────────────────
def test_pinremap_same_position_identities_each_get_their_own_distinct_af_rows():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "pinremap")
    conn = idx._conn
    mcu_id = _mcu_id(conn, "SYNTH_PINREMAP_AF_Tx")

    rows = conn.execute(
        "SELECT physical_pin_number, raw_pin_name FROM mcu_package_pin "
        "WHERE mcu_id = ? AND physical_pin_number = '30'",
        (mcu_id,),
    ).fetchall()
    assert len(rows) == 2, "both same-position PINREMAP identities must survive as distinct rows"
    raw_names = {r["raw_pin_name"] for r in rows}
    assert raw_names == {"PA9", "PA9_Remap"}

    pa9_af = _af_rows(conn, mcu_id, "PA9")
    assert [(r["af_index"], r["signal"], r["peripheral"]) for r in pa9_af] == [
        (1, "USART1_TX", "USART1"),
    ]
    remap_af = _af_rows(conn, mcu_id, "PA9_Remap")
    assert [(r["af_index"], r["signal"], r["peripheral"]) for r in remap_af] == [
        (4, "USART2_TX", "USART2"),
    ]
    # Never a merged/shared set: PA9 must not see USART2_TX and vice versa.
    assert "USART2_TX" not in {r["signal"] for r in pa9_af}
    assert "USART1_TX" not in {r["signal"] for r in remap_af}


def test_c_suffix_ball_gets_its_own_af_rows_never_inheriting_the_digital_pins_mux():
    idx = db_mod.StmIndex.build(AF_FIXTURES / "c_suffix")
    conn = idx._conn
    mcu_id = _mcu_id(conn, "SYNTH_C_SUFFIX_Tx")

    # Both balls share a canonical_pin_name ("PC2") under the regex-collapsed
    # canonical() rule, but are DISTINCT mcu_package_pin rows (different
    # physical positions) with distinct raw_pin_name values.
    canon_rows = conn.execute(
        "SELECT raw_pin_name, canonical_pin_name FROM mcu_package_pin "
        "WHERE mcu_id = ? AND canonical_pin_name = 'PC2'",
        (mcu_id,),
    ).fetchall()
    assert {r["raw_pin_name"] for r in canon_rows} == {"PC2", "PC2_C"}

    pc2_af = _af_rows(conn, mcu_id, "PC2")
    assert [(r["af_index"], r["signal"], r["peripheral"]) for r in pc2_af] == [
        (5, "SPI2_MISO", "SPI2"),
    ]
    pc2_c_af = _af_rows(conn, mcu_id, "PC2_C")
    assert [(r["af_index"], r["signal"], r["peripheral"]) for r in pc2_c_af] == [
        (9, "COMP1_INM", "COMP1"),
    ]
    assert "COMP1_INM" not in {r["signal"] for r in pc2_af}
    assert "SPI2_MISO" not in {r["signal"] for r in pc2_c_af}


def test_af_join_code_never_falls_back_to_canonical_pin_name():
    import inspect

    src = inspect.getsource(db_mod.StmIndex.build)
    # The AF-ingest wiring must key strictly on raw_pin_name; canonical_pin_name
    # is never referenced in that specific section of the build loop (bounded
    # to the AF-ingest comment block through the F1-legacy summary log call
    # that immediately follows it, so this does not spill into the NEXT
    # device iteration's mcu_package_pin insert, which legitimately uses
    # canonical_pin_name for an unrelated column).
    af_ingest_start = src.index("gpio_peripheral = conn.execute(")
    af_ingest_end = src.index("AF join: legacy AFIO-remap family", af_ingest_start)
    af_ingest_section = src[af_ingest_start:af_ingest_end]
    assert "canonical_pin_name" not in af_ingest_section
    assert "pin_ids_by_raw_name" in af_ingest_section
