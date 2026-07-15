"""The offline passive fast path (enrich/passive.py).

A passive's MPN alone is enough to recover its value, tolerance, package, and
power/voltage rating (a deterministic, no-network decode), and to resolve the
KiCad *stock* symbol/footprint/3D it should use. These tests are grounded in real
manufacturer part numbers, including the owner's own ERJ-P03F1101V (whose library
record proves ERJ-P03 == the 0603 case, 1.1 kOhm, 0.2 W, 1%).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.enrich.passive import (
    PassiveSpec,
    decode_resistance,
    detect_passive,
    parse_passive_mpn,
    resolve_passive_assets,
)


# --------------------------------------------------------------------------- #
# The value decoders in isolation (canonical EIA codes, no vendor guesswork).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "code,ohms",
    [
        # RKM / IEC 60062 letter-as-decimal-point notation.
        ("1R00", 1.0),
        ("4K70", 4700.0),
        ("1M00", 1_000_000.0),
        ("0R10", 0.1),
        ("100R", 100.0),
        ("10K", 10_000.0),
        ("1K1", 1100.0),
        # 4-digit (3 significant figures + decade multiplier).
        ("1101", 1100.0),
        ("1002", 10_000.0),
        ("4700", 470.0),
        # 3-digit (2 significant figures + decade multiplier).
        ("103", 10_000.0),
        ("100", 10.0),
        ("4R7", 4.7),
    ],
)
def test_decode_resistance_canonical_codes(code, ohms):
    assert decode_resistance(code) == pytest.approx(ohms)


# --------------------------------------------------------------------------- #
# Resistor value + tolerance decode (the universal, family-agnostic core).
# --------------------------------------------------------------------------- #
def test_owner_erj_p03f1101v_matches_its_library_record():
    # Ground truth from libraries/Main/parts/667_erj_p03f1101v.json:
    #   "Thick Film Resistors - SMD 0603 1.1Kohms 0.2W 1%"
    spec = parse_passive_mpn("ERJ-P03F1101V")
    assert spec is not None
    assert spec.kind == "resistor"
    assert spec.value_ohms == pytest.approx(1100.0)
    assert spec.value == "1.1 kOhm"
    assert spec.tolerance == "1%"
    assert spec.package == "0603"
    assert spec.power == "0.2 W"
    assert spec.manufacturer == "Panasonic"


def test_mouser_distributor_prefix_is_stripped_before_parsing():
    # The record stores the MPN as "667-ERJ-P03F1101V" (Mouser's 667- prefix).
    spec = parse_passive_mpn("667-ERJ-P03F1101V")
    assert spec is not None and spec.value_ohms == pytest.approx(1100.0)
    assert spec.package == "0603"


@pytest.mark.parametrize(
    "mpn,ohms,value_str,tol,pkg",
    [
        # Yageo RC: EIA size is literal in the MPN; value in RKM ("1K1" = 1.1k),
        # F = 1%, trailing L is the lead-free suffix (not part of the value).
        ("RC0603FR-071K1L", 1100.0, "1.1 kOhm", "1%", "0603"),
        # Stackpole RMCF: "1K10" = 1.10k, F = 1%, literal 0603.
        ("RMCF0603FT1K10", 1100.0, "1.1 kOhm", "1%", "0603"),
        # Vishay CRCW: literal 0402, "10K0" = 10.0k, F = 1%.
        ("CRCW040210K0FKED", 10000.0, "10 kOhm", "1%", "0402"),
        # Vishay CRCW 0805, "4K70" = 4.70k, F = 1%.
        ("CRCW08054K70FKEA", 4700.0, "4.7 kOhm", "1%", "0805"),
        # Yageo 1206, value "10K", trailing L suffix stripped.
        ("RC1206FR-0710KL", 10000.0, "10 kOhm", "1%", "1206"),
        # Stackpole 0805, J = 5%, "10K0" = 10.0k.
        ("RMCF0805JT10K0", 10000.0, "10 kOhm", "5%", "0805"),
        # Megohm "1M00" = 1.0 MOhm, 1%, 0603.
        ("RMCF0603FT1M00", 1_000_000.0, "1 MOhm", "1%", "0603"),
    ],
)
def test_resistor_families_decode_value_tolerance_package(mpn, ohms, value_str, tol, pkg):
    spec = parse_passive_mpn(mpn)
    assert spec is not None, f"{mpn} should parse as a passive"
    assert spec.kind == "resistor"
    assert spec.value_ohms == pytest.approx(ohms), f"{mpn} ohms"
    assert spec.value == value_str, f"{mpn} human value"
    assert spec.tolerance == tol, f"{mpn} tolerance"
    assert spec.package == pkg, f"{mpn} package"


def test_specs_dict_is_display_ready_and_carries_the_key_facts():
    spec = parse_passive_mpn("ERJ-P03F1101V")
    assert spec is not None
    d = spec.to_specs()
    # Title Case keys (design contract: interactive/label text is Title Case).
    assert d["Resistance"] == "1.1 kOhm"
    assert d["Tolerance"] == "1%"
    assert d["Package"] == "0603"
    assert d["Power"] == "0.2 W"


# --------------------------------------------------------------------------- #
# Capacitor / inductor value decode (kind + value + tolerance; package via a
# literal EIA token when the family embeds one).
# --------------------------------------------------------------------------- #
def test_capacitor_pico_farad_code_decodes():
    # "104" = 10 x 10^4 pF = 100 nF; K = 10%.
    spec = parse_passive_mpn("CL10B104KB8NNNC")  # Samsung CL10 == 0603
    assert spec is not None
    assert spec.kind == "capacitor"
    assert spec.value_farads == pytest.approx(100e-9)
    assert spec.value == "100 nF"
    assert spec.tolerance == "10%"


def test_inductor_is_detected():
    spec = parse_passive_mpn("LQW18AN10NJ00D")  # Murata inductor, 10 nH
    assert spec is not None
    assert spec.kind == "inductor"


def test_murata_power_inductor_does_not_emit_a_wrong_value():
    # LQH/LQM power inductors carry a type code (e.g. "CN") that the nH decoder used
    # to misread as a value ~10^5 off (LQH32CN100K23 is 10 uH, not 0.1 nH). Murata
    # case codes are also per-series and not a clean EIA case, so we now emit NEITHER
    # a value NOR a package offline (jlcsearch fills them); only the kind is asserted.
    spec = parse_passive_mpn("LQH32CN100K23")
    assert spec is not None and spec.kind == "inductor"
    assert spec.value == "" and spec.value_henries is None
    assert spec.package == ""


def test_erj_pa3_does_not_inherit_the_p03_power_rating():
    # ERJ-PA3 (0603 anti-surge) is rated 0.25 W, NOT the ERJ-P03's 0.20 W. Only the
    # grounded ERJ-P03 hardcodes a power; PA3 must not be mislabelled 0.2 W.
    spec = parse_passive_mpn("ERJ-PA3F1002V")
    assert spec is not None and spec.kind == "resistor"
    assert spec.value_ohms == pytest.approx(10000.0)
    assert spec.tolerance == "1%"
    assert spec.package == "0603"
    assert spec.power != "0.2 W"


def test_erj_p03_still_gets_its_grounded_power():
    assert parse_passive_mpn("ERJ-P03F1101V").power == "0.2 W"


def test_resolve_2220_and_1218_map_to_real_kicad_footprints():
    # Verified against the installed KiCad 10 libraries.
    c = resolve_passive_assets("capacitor", "2220", footprints_root=None)
    assert c is not None and c.footprint == "Capacitor_SMD:C_2220_5750Metric"
    r = resolve_passive_assets("resistor", "1218", footprints_root=None)
    assert r is not None and r.footprint == "Resistor_SMD:R_1218_3246Metric"


def test_non_passive_mpn_returns_none():
    assert parse_passive_mpn("STM32F103C8T6") is None
    assert parse_passive_mpn("LM317T") is None
    assert parse_passive_mpn("") is None
    assert parse_passive_mpn("   ") is None


# --------------------------------------------------------------------------- #
# Passive detection (auto-detect + override), independent of a full decode.
# --------------------------------------------------------------------------- #
def test_detect_passive_from_category():
    assert detect_passive(mpn="", category="Resistors", refdes="") == "resistor"
    assert detect_passive(mpn="", category="Capacitors", refdes="") == "capacitor"
    assert detect_passive(mpn="", category="Inductors", refdes="") == "inductor"


def test_detect_passive_from_refdes():
    assert detect_passive(mpn="", category="", refdes="R14") == "resistor"
    assert detect_passive(mpn="", category="", refdes="C7") == "capacitor"
    assert detect_passive(mpn="", category="", refdes="L2") == "inductor"


def test_detect_passive_from_mpn_family():
    assert detect_passive(mpn="ERJ-P03F1101V", category="", refdes="") == "resistor"


def test_detect_passive_returns_none_for_active_part():
    assert detect_passive(mpn="STM32F103C8T6", category="ICs", refdes="U3") is None


def test_override_forces_or_clears_passive():
    # Explicit override wins over auto-detection either way.
    assert detect_passive(mpn="STM32F103", category="ICs", refdes="U1",
                          override="resistor") == "resistor"
    assert detect_passive(mpn="ERJ-P03F1101V", category="Resistors", refdes="R1",
                          override="none") is None


# --------------------------------------------------------------------------- #
# KiCad stock-asset resolution (offline). lib_ids are always correct; the
# presence flag is advisory and degrades where KiCad libs are not installed.
# --------------------------------------------------------------------------- #
def test_resolve_maps_case_to_kicad_stock_lib_ids():
    a = resolve_passive_assets("resistor", "0603", footprints_root=None)
    assert a.symbol == "Device:R"
    assert a.footprint == "Resistor_SMD:R_0603_1608Metric"
    assert a.model_name == "R_0603_1608Metric"

    c = resolve_passive_assets("capacitor", "0402", footprints_root=None)
    assert c.symbol == "Device:C"
    assert c.footprint == "Capacitor_SMD:C_0402_1005Metric"

    ind = resolve_passive_assets("inductor", "0805", footprints_root=None)
    assert ind.symbol == "Device:L"
    assert ind.footprint == "Inductor_SMD:L_0805_2012Metric"


def test_resolve_presence_check_against_a_footprints_root(tmp_path):
    pretty = tmp_path / "Resistor_SMD.pretty"
    pretty.mkdir()
    (pretty / "R_0603_1608Metric.kicad_mod").write_text("(footprint)", encoding="utf-8")

    present = resolve_passive_assets("resistor", "0603", footprints_root=tmp_path)
    assert present.present is True

    # A case with no stock footprint file present is honestly flagged absent, but the
    # lib_id is still returned (never fabricated, never blank).
    absent = resolve_passive_assets("resistor", "2512", footprints_root=tmp_path)
    assert absent.present is False
    assert absent.footprint == "Resistor_SMD:R_2512_6332Metric"


def test_resolve_unknown_package_returns_none():
    assert resolve_passive_assets("resistor", "", footprints_root=None) is None
    assert resolve_passive_assets("resistor", "9999", footprints_root=None) is None
