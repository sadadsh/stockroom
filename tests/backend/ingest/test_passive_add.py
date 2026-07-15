"""The file-less passive add path: build a passive PartRecord from an MPN or a
Mouser URL, and commit it with no dropped asset files."""

from __future__ import annotations

import shutil

import pytest

from stockroom.ingest.passive_add import (
    PassiveAddError,
    PassiveNeedsInputError,
    build_passive_record,
    mouser_search_url,
    parse_mouser_product_url,
)
from stockroom.enrich.passive import passive_package_options
from stockroom.mutation.library_ops import LibraryOps
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

_OWNER_URL = (
    "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V"
    "?qs=sGAEpiMZZMtG0KNrPCHnjYpPrk%252BOMd4bdFNd%2Ftqgjvc%3D"
)


def test_parse_mouser_product_url_reads_manufacturer_and_mpn():
    assert parse_mouser_product_url(_OWNER_URL) == ("Panasonic", "ERJ-P03F1101V")
    assert parse_mouser_product_url("https://example.com/foo") is None


def test_build_from_the_owners_mouser_url_references_stock_assets():
    build = build_passive_record(_OWNER_URL)
    rec = build.record
    assert rec.passive is True
    assert rec.mpn == "ERJ-P03F1101V"
    assert rec.manufacturer == "Panasonic"
    assert rec.category == "Resistors"
    assert rec.description == "Resistor, 1.1 kOhm, 1%, 0603"
    # symbol/footprint reference KiCad stock, no owned model
    assert (rec.symbol.lib, rec.symbol.name) == ("Device", "R")
    assert (rec.footprint.lib, rec.footprint.name) == ("Resistor_SMD", "R_0603_1608Metric")
    assert rec.model is None
    # the pasted Mouser link is the buy-link verbatim
    assert rec.purchase[0].vendor == "Mouser"
    assert rec.purchase[0].url == _OWNER_URL
    assert rec.specs["Resistance"] == "1.1 kOhm"
    assert rec.specs["Footprint"] == "Resistor_SMD:R_0603_1608Metric"
    # no datasheet supplied -> the single remaining gap
    assert build.gaps == ["datasheet"]


def test_build_from_bare_mpn_constructs_a_mouser_link_and_completes_with_a_datasheet_url():
    build = build_passive_record("RC0603FR-0710KL", datasheet_url="https://example.com/ds.pdf")
    rec = build.record
    assert rec.mpn == "RC0603FR-0710KL"
    assert rec.manufacturer == "Yageo"
    assert rec.purchase[0].vendor == "Mouser"
    assert rec.purchase[0].url == mouser_search_url("RC0603FR-0710KL")
    assert rec.datasheet is not None and rec.datasheet.source_url == "https://example.com/ds.pdf"
    assert build.gaps == []  # datasheet URL provided -> passport complete


def test_category_override_is_honored():
    build = build_passive_record("RC0603FR-0710KL", category="Precision Resistors")
    assert build.record.category == "Precision Resistors"


def test_display_name_describes_the_passive_not_just_the_mpn():
    build = build_passive_record(_OWNER_URL)
    # the list should read "1.1 kOhm 1% 0603 Resistor", not the bare MPN
    assert build.record.display_name == "1.1 kOhm 1% 0603 Resistor"
    assert build.record.mpn == "ERJ-P03F1101V"  # MPN stays for search + id


def test_distributor_part_number_is_carried_on_the_purchase():
    build = build_passive_record(_OWNER_URL, purchase_part_number="667-ERJ-P03F1101V")
    assert build.record.purchase[0].part_number == "667-ERJ-P03F1101V"


def test_non_mouser_product_url_is_rejected_by_host_check():
    with pytest.raises(PassiveAddError):
        build_passive_record(
            "https://evil.example/ProductDetail/Yageo/RC0603FR-0710KL"
        )


def test_non_mouser_url_is_rejected():
    with pytest.raises(PassiveAddError):
        build_passive_record("https://www.digikey.com/en/products/detail/x/y/123")


# --------------------------------------------------------------------------- #
# The "cannot decode" fallback: an undecodable MPN is not an error. The user
# supplies kind + package (+ optional value/tolerance) and the passive is built
# from the KiCad stock footprint for the picked package. This is the real unblock
# for the owner's Mouser-sourced parts (Wurth etc.) that no decoder knows.
# --------------------------------------------------------------------------- #
_WURTH_URL = (
    "https://www.mouser.com/ProductDetail/Wurth-Elektronik/560112116151"
)


def test_undecodable_bare_mpn_asks_for_manual_input():
    # It must NOT raise a plain PassiveAddError: it raises the needs-input signal
    # carrying the cleaned MPN and the package options so the UI can offer pickers.
    with pytest.raises(PassiveNeedsInputError) as ei:
        build_passive_record("560112116151")
    err = ei.value
    assert err.mpn == "560112116151"
    assert "0603" in err.packages and "0402" in err.packages


def test_undecodable_mouser_url_carries_manufacturer_for_the_pickers():
    with pytest.raises(PassiveNeedsInputError) as ei:
        build_passive_record(_WURTH_URL)
    err = ei.value
    assert err.mpn == "560112116151"
    assert err.manufacturer == "Wurth-Elektronik"


def test_manual_kind_and_package_build_a_passive_from_the_stock_footprint():
    build = build_passive_record(
        "560112116151",
        kind="inductor",
        package="1210",
        value="4.7 µH",
        tolerance="20%",
        manufacturer="Wurth Elektronik",
        datasheet_url="https://www.we-online.com/x.pdf",
    )
    rec = build.record
    assert rec.passive is True
    assert rec.mpn == "560112116151"
    assert rec.manufacturer == "Wurth Elektronik"
    assert rec.category == "Inductors"
    assert (rec.symbol.lib, rec.symbol.name) == ("Device", "L")
    assert (rec.footprint.lib, rec.footprint.name) == ("Inductor_SMD", "L_1210_3225Metric")
    assert rec.model is None
    # the user-supplied value/tolerance are carried on the record
    assert rec.specs["Inductance"] == "4.7 µH"
    assert rec.specs["Tolerance"] == "20%"
    assert rec.specs["Footprint"] == "Inductor_SMD:L_1210_3225Metric"
    # descriptive name from the manual facts, not the bare MPN
    assert rec.display_name == "4.7 µH 20% 1210 Inductor"
    assert build.gaps == []  # datasheet supplied -> passport complete


def test_manual_mouser_url_uses_the_url_as_the_buy_link():
    build = build_passive_record(
        _WURTH_URL, kind="inductor", package="1210",
        datasheet_url="https://www.we-online.com/x.pdf",
    )
    rec = build.record
    assert rec.manufacturer == "Wurth-Elektronik"
    assert rec.purchase[0].vendor == "Mouser"
    assert rec.purchase[0].url == _WURTH_URL


def test_manual_package_overrides_a_wrong_decode():
    # A decoded MPN whose package the user corrects: the override wins and the
    # footprint/specs follow the picked package, not the decoded one.
    build = build_passive_record("RC0603FR-0710KL", package="0805",
                                 datasheet_url="https://x/y.pdf")
    rec = build.record
    assert (rec.footprint.lib, rec.footprint.name) == ("Resistor_SMD", "R_0805_2012Metric")
    assert rec.specs["Package"] == "0805"


def test_manual_build_without_package_still_asks_for_input():
    # kind alone is not enough to resolve a footprint; the package is required.
    with pytest.raises(PassiveNeedsInputError):
        build_passive_record("560112116151", kind="inductor")


def test_kind_override_does_not_bleed_the_decoded_value():
    # Correcting a decoded resistor to a capacitor must NOT carry the resistance
    # value/tolerance/manufacturer over (they were resistor facts): confidently-wrong
    # data is worse than a blank the user fills.
    build = build_passive_record("RC0603FR-0710KL", kind="capacitor", package="0603",
                                 datasheet_url="https://x/y.pdf")
    rec = build.record
    assert rec.category == "Capacitors"
    assert (rec.symbol.lib, rec.symbol.name) == ("Device", "C")
    assert "Capacitance" not in rec.specs
    assert "Resistance" not in rec.specs
    assert "Tolerance" not in rec.specs
    assert rec.manufacturer == ""  # the resistor-family manufacturer is repudiated
    assert rec.specs["Package"] == "0603"


def test_value_only_override_keeps_the_decoded_power():
    # Refining just the display value on an otherwise-unchanged decode must keep the
    # per-package power rating (power depends on the package, not the value).
    plain = build_passive_record("RC0603FR-0710KL", datasheet_url="https://x/y.pdf")
    assert plain.record.specs.get("Power") == "0.1 W"
    refined = build_passive_record("RC0603FR-0710KL", value="10 kOhm",
                                   datasheet_url="https://x/y.pdf")
    assert refined.record.specs.get("Power") == "0.1 W"
    assert refined.record.specs["Resistance"] == "10 kOhm"


def test_decoded_kind_without_a_package_asks_only_for_the_package():
    # A Murata LQ inductor decodes its KIND but not its package; the needs-input
    # signal must carry the kind and not claim a total decode failure.
    with pytest.raises(PassiveNeedsInputError) as ei:
        build_passive_record("LQW18AN10NG00D")
    err = ei.value
    assert err.suggested_kind == "inductor"
    assert "could not decode" not in str(err).lower()
    assert "package" in str(err).lower()


def test_package_options_are_the_resolvable_eia_cases_in_order():
    opts = passive_package_options()
    assert opts == sorted(opts)
    for common in ("0402", "0603", "0805", "1206"):
        assert common in opts


def _ops(tmp_path):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x", encoding="utf-8")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    return repo, profile, LibraryOps(profile, repo)


def test_add_passive_part_commits_only_the_json_record(tmp_path):
    repo, profile, ops = _ops(tmp_path)
    build = build_passive_record(_OWNER_URL, datasheet_url="https://industrial.panasonic.com/x.pdf")
    before = repo.head()
    record = ops.add_passive_part(build.record)

    assert record.id == "erj_p03f1101v"
    assert record.passive is True
    # exactly one new file: the JSON record (no symbol/footprint/model copied)
    json_path = profile.library.parts_dir / "erj_p03f1101v.json"
    assert json_path.is_file()
    assert repo.head() != before  # a real scoped commit landed
    assert repo.is_clean()  # atomic: no stray untracked files


def test_add_then_delete_a_passive_leaves_no_trace(tmp_path):
    # A passive owns no symbol/footprint files, so delete must not try to remove a
    # non-existent stock symbol from the category lib (it used to 404/500).
    repo, profile, ops = _ops(tmp_path)
    build = build_passive_record(_OWNER_URL, datasheet_url="https://x/y.pdf")
    rec = ops.add_passive_part(build.record)
    ops.delete_part(rec.id)  # must not raise
    assert not (profile.library.parts_dir / f"{rec.id}.json").exists()
    assert repo.is_clean()


def test_move_a_passive_changes_only_its_category(tmp_path):
    repo, profile, ops = _ops(tmp_path)
    build = build_passive_record(_OWNER_URL, datasheet_url="https://x/y.pdf")
    rec = ops.add_passive_part(build.record)
    moved = ops.move_category(rec.id, "Precision Resistors")
    assert moved.category == "Precision Resistors"
    assert moved.symbol.name == "R"  # stock lib_id is unchanged by the move
    assert moved.footprint.name == "R_0603_1608Metric"
    assert repo.is_clean()


def test_a_passive_never_reports_symbol_drift(tmp_path):
    repo, profile, ops = _ops(tmp_path)
    build = build_passive_record(_OWNER_URL, datasheet_url="https://x/y.pdf")
    rec = ops.add_passive_part(build.record)
    report = ops.detect_drift()
    assert rec.id not in report.missing_symbol


def test_incomplete_passive_is_rejected_with_zero_trace(tmp_path):
    from stockroom.mutation.library_ops import IncompleteError

    repo, profile, ops = _ops(tmp_path)
    build = build_passive_record(_OWNER_URL)  # no datasheet -> incomplete
    before = repo.head()
    with pytest.raises(IncompleteError):
        ops.add_passive_part(build.record)
    assert repo.head() == before
    assert repo.is_clean()  # rejected before any write -> zero trace
