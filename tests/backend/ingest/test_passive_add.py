"""The file-less passive add path: build a passive PartRecord from an MPN or a
Mouser URL, and commit it with no dropped asset files."""

from __future__ import annotations

import shutil

import pytest

from stockroom.ingest.passive_add import (
    PassiveAddError,
    build_passive_record,
    mouser_search_url,
    parse_mouser_product_url,
)
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


def test_non_passive_mpn_is_rejected():
    with pytest.raises(PassiveAddError):
        build_passive_record("STM32F103C8T6")


def test_non_mouser_url_is_rejected():
    with pytest.raises(PassiveAddError):
        build_passive_record("https://www.digikey.com/en/products/detail/x/y/123")


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
