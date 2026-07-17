"""renormalize_descriptions(): rebuild machine names + placeholder descriptions from a
record's specs, in one atomic commit, leaving custom data untouched."""

import json
import shutil

import pytest

from stockroom.model.part import PartRecord
from stockroom.mutation.library_ops import LibraryOps

from .test_library_ops import _setup

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _seed_part(profile, repo, overrides: dict) -> str:
    """Write one committed part record (bad name/desc + real specs) and return its id."""
    parts_dir = profile.library.parts_dir
    parts_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "id": "part1",
        "display_name": "1.10k 1% 0603 Panasonic ERJ-P03F1101V",
        "category": "Resistors",
        "description": "Resistor, small symbol",
        "mpn": "ERJ-P03F1101V",
        "manufacturer": "Panasonic",
        "tags": [],
        "passive": True,
        "symbol": None,
        "footprint": {"lib": "Resistor_SMD", "name": "R_0603_1608Metric", "tool": "kicad"},
        "model": None,
        "datasheet": None,
        "purchase": [],
        "provenance": None,
        "hashes": None,
        "enrichment": {},
        "specs": {
            "Resistance": "1.1 kOhms",
            "Package": "0603",
            "Power Rating": "200 mW (1/5 W)",
            "Product": "Thick Film Chip Resistors",
        },
    }
    base.update(overrides)
    record = PartRecord.from_dict(base)
    path = parts_dir / f"{record.id}.json"
    path.write_text(record.dumps(), encoding="utf-8")
    repo.commit("seed part", [path])
    return record.id


def test_rebuilds_name_and_placeholder_description_in_one_commit(tmp_path, fixtures_dir):
    repo, profile, _staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _seed_part(profile, repo, {})
    assert repo.is_clean()

    report = ops.renormalize_descriptions()

    assert len(report) == 1
    fixed = ops.load_record(pid)
    assert fixed.display_name == "1.1 kΩ Resistor"
    assert fixed.description == "Thick Film Chip Resistor, 1.1 kΩ, 200 mW, 0603"
    assert repo.is_clean()  # committed as one scoped commit, zero uncommitted trace


def test_dry_run_reports_without_writing(tmp_path, fixtures_dir):
    repo, profile, _staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _seed_part(profile, repo, {})

    report = ops.renormalize_descriptions(dry_run=True)

    assert len(report) == 1 and report[0]["id"] == pid
    # nothing written: the bad name still stands
    assert ops.load_record(pid).display_name.startswith("1.10k")


def test_leaves_a_custom_name_and_real_description_untouched(tmp_path, fixtures_dir):
    repo, profile, _staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    # a part whose category has no clean-name rule and whose description is real
    _seed_part(
        profile,
        repo,
        {
            "id": "custom1",
            "display_name": "My Favourite Resistor",
            "category": "Resistors",
            "description": "Hand-written, keep me",
            "specs": {},  # no value spec -> no clean name possible
        },
    )

    report = ops.renormalize_descriptions()

    assert report == []  # nothing to change
    kept = ops.load_record("custom1")
    assert kept.display_name == "My Favourite Resistor"
    assert kept.description == "Hand-written, keep me"
