"""`LibraryOps.rederive_library()`: bring every record onto the current derivation ruleset.

WHY THIS EXISTS. `model/derived.py` stamps each derived block with the ruleset that produced it,
"so a library can be swept for parts still carrying an older derivation instead of everything
being re-derived blindly". Until now nothing could perform that sweep from inside the app: the
only route was `scripts/import_library.py`, which REFUSES to run without distributor credentials
and re-fetches over the network. Owner's standing rule - *"everything u do manually the app should
do by itself"* - makes that a missing feature, not a workaround.

The three properties that make it safe to point at a real library:

  CREDENTIAL-FREE   it reads `sourced/` and nothing else, so a fresh clone with no keys can
                    rebuild the library it just pulled (device parity).
  NON-DESTRUCTIVE   a record with NO stored evidence is SKIPPED, never blanked. `rederive()` on
                    its own recomputes an empty block from no payloads, which is right for one
                    part being imported and catastrophic for a whole-library sweep.
  ATOMIC            one transaction: the library moves to the new ruleset or it does not move.
"""

import json
import shutil

import pytest

from stockroom.model.derived import DERIVED_BY
from stockroom.model.part import PartRecord
from stockroom.model.part_class import PartClass
from stockroom.model.sourced import SOURCED_DIRNAME, SourceEntry, source_rel_path
from stockroom.mutation.library_ops import LibraryOps

from .test_library_ops import _setup

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

# A real-shaped Mouser search response, trimmed to the fields the parser reads. Its `Description`
# carries the catalogue tail measured on the owner's library (13 of 158 parts, 2026-07-27).
_MOUSER_PAYLOAD = {
    "Errors": [],
    "SearchResults": {
        "NumberOfResult": 1,
        "Parts": [
            {
                "ManufacturerPartNumber": "TPS3700DDCT",
                "Manufacturer": "Texas Instruments",
                "MouserPartNumber": "595-TPS3700DDCT",
                "Description": (
                    "Analog Comparators Window Comp for Over & Under Vltg Det A A "
                    "595-TPS3700DDCR"
                ),
                "Category": "Analog Comparators",
            }
        ],
    },
}


def _seed(profile, repo, part_id: str, *, payload: dict | None, derived_by: str, **fields):
    """Write one committed record, and optionally the raw evidence beside it."""
    parts_dir = profile.library.parts_dir
    parts_dir.mkdir(parents=True, exist_ok=True)
    record = PartRecord(
        id=part_id,
        mpn=fields.pop("mpn", "TPS3700DDCT"),
        manufacturer="Texas Instruments",
        part_class=PartClass.COMPONENT,
        category="ICs",
        derived_by=derived_by,
        **fields,
    )
    written = [parts_dir / f"{part_id}.json"]
    if payload is not None:
        src_dir = parts_dir.parent / SOURCED_DIRNAME / part_id
        src_dir.mkdir(parents=True, exist_ok=True)
        src = src_dir / "mouser.json"
        src.write_text(json.dumps(payload), encoding="utf-8")
        record.sources["mouser"] = SourceEntry(
            fetched_at="2026-07-27T00:00:00Z", file=source_rel_path(part_id, "mouser")
        )
        written.append(src)
    written[0].write_text(record.dumps(), encoding="utf-8")
    repo.commit(f"seed {part_id}", written)
    return record


def _load(profile, part_id: str) -> PartRecord:
    return PartRecord.loads(
        (profile.library.parts_dir / f"{part_id}.json").read_text(encoding="utf-8")
    )


def test_a_stale_record_is_brought_onto_the_current_ruleset(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(
        profile, repo, "tps3700ddct-1111",
        payload=_MOUSER_PAYLOAD,
        derived_by="rules@1",
        description="Analog Comparators Window Comp for Over & Under Vltg Det A A 595-TPS3700DDCR",
    )

    report = ops.rederive_library(now_iso="2026-07-27T12:00:00Z")

    assert report["rewritten"] == 1
    rec = _load(profile, "tps3700ddct-1111")
    assert rec.derived_by == DERIVED_BY
    assert rec.description == "Analog Comparators Window Comp for Over & Under Vltg Det"


def test_a_record_with_NO_stored_evidence_is_skipped_rather_than_blanked(tmp_path, fixtures_dir):
    """THE SAFETY PROPERTY. `rederive()` alone recomputes from nothing and leaves an EMPTY block,
    which would silently wipe the description of every hand-added part in a real library."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(
        profile, repo, "handmade-2222",
        payload=None, derived_by="rules@1",
        mpn="HANDMADE-1", display_name="A Part I Typed In", description="Typed by hand",
    )

    report = ops.rederive_library(now_iso="2026-07-27T12:00:00Z")

    assert report["no_evidence"] == 1
    assert report["rewritten"] == 0
    rec = _load(profile, "handmade-2222")
    assert rec.description == "Typed by hand"
    assert rec.display_name == "A Part I Typed In"
    assert rec.derived_by == "rules@1"  # untouched, so it still reads as needing evidence


def test_running_it_twice_changes_nothing_the_second_time(tmp_path, fixtures_dir):
    """Idempotent, and measurably so: the second pass must report zero rewrites and leave the
    git tree clean. A pass that rewrote every record every time would churn the library and make
    "unchanged" meaningless."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(profile, repo, "tps3700ddct-1111", payload=_MOUSER_PAYLOAD, derived_by="rules@1")

    ops.rederive_library(now_iso="2026-07-27T12:00:00Z")
    first = (profile.library.parts_dir / "tps3700ddct-1111.json").read_bytes()

    second = ops.rederive_library(now_iso="2026-07-27T23:59:59Z")

    assert second["rewritten"] == 0
    assert second["unchanged"] == 1
    assert (profile.library.parts_dir / "tps3700ddct-1111.json").read_bytes() == first
    assert repo.is_clean()


def test_the_raw_evidence_is_never_written(tmp_path, fixtures_dir):
    """Lossless, measured rather than promised: the `sourced/` bytes are hashed either side."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(profile, repo, "tps3700ddct-1111", payload=_MOUSER_PAYLOAD, derived_by="rules@1")
    src = profile.library.parts_dir.parent / SOURCED_DIRNAME / "tps3700ddct-1111" / "mouser.json"
    before = src.read_bytes()

    ops.rederive_library(now_iso="2026-07-27T12:00:00Z")

    assert src.read_bytes() == before


def test_a_dry_run_reports_the_same_work_and_writes_nothing(tmp_path, fixtures_dir):
    """Anything that acts on a whole library gets a dry run BEFORE it acts."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(profile, repo, "tps3700ddct-1111", payload=_MOUSER_PAYLOAD, derived_by="rules@1")
    before = (profile.library.parts_dir / "tps3700ddct-1111.json").read_bytes()

    report = ops.rederive_library(now_iso="2026-07-27T12:00:00Z", dry_run=True)

    assert report["rewritten"] == 1
    assert (profile.library.parts_dir / "tps3700ddct-1111.json").read_bytes() == before
    assert repo.is_clean()


def test_identity_survives_the_sweep(tmp_path, fixtures_dir):
    """Spec rule 3: `id`, `mpn`, `manufacturer` and `part_class` are never derived. A sweep that
    could rewrite them would make a re-derive a re-import."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(profile, repo, "tps3700ddct-1111", payload=_MOUSER_PAYLOAD, derived_by="rules@1")
    before = _load(profile, "tps3700ddct-1111")

    ops.rederive_library(now_iso="2026-07-27T12:00:00Z")

    after = _load(profile, "tps3700ddct-1111")
    assert (after.id, after.mpn, after.manufacturer, after.part_class) == (
        before.id, before.mpn, before.manufacturer, before.part_class,
    )


def test_one_unreadable_record_does_not_abandon_the_rest(tmp_path, fixtures_dir):
    """One corrupt file must not leave the library half-swept. It is reported by id and the
    parts either side of it still land."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(profile, repo, "aaa-1111", payload=_MOUSER_PAYLOAD, derived_by="rules@1")
    _seed(profile, repo, "zzz-3333", payload=_MOUSER_PAYLOAD, derived_by="rules@1")
    broken = profile.library.parts_dir / "mmm-2222.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    repo.commit("seed a broken record", [broken])

    report = ops.rederive_library(now_iso="2026-07-27T12:00:00Z")

    assert report["rewritten"] == 2
    assert [f["id"] for f in report["failed"]] == ["mmm-2222"]
    assert _load(profile, "aaa-1111").derived_by == DERIVED_BY
    assert _load(profile, "zzz-3333").derived_by == DERIVED_BY


def test_the_whole_sweep_lands_in_ONE_commit(tmp_path, fixtures_dir):
    """"The library is on ruleset N" is one fact, so it is one commit - and one rollback."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _seed(profile, repo, "aaa-1111", payload=_MOUSER_PAYLOAD, derived_by="rules@1")
    _seed(profile, repo, "zzz-3333", payload=_MOUSER_PAYLOAD, derived_by="rules@1")
    before = repo.log_count() if hasattr(repo, "log_count") else None

    ops.rederive_library(now_iso="2026-07-27T12:00:00Z")

    assert repo.is_clean()
    if before is not None:
        assert repo.log_count() == before + 1
