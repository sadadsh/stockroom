"""WHERE an asset came from, recorded on the asset.

Owner's complaint, verbatim, and the reason the whole trust workstream exists:
*"a lot of our symbols, footprints, and 3d models are broken so its not trusted where we've gotten
them"*. `model/asset.py::AssetOrigin` was built for exactly that question -- which vendor, from
what URL, when -- and NOTHING ever populated it, so every attach produced `origin: None` and the
library still could not answer it.

`captured_at` is stamped by the SERVER, never accepted from the caller: a provenance timestamp a
client can set is not evidence.
"""

import shutil

import pytest

from stockroom.model.asset import AssetOrigin
from stockroom.mutation.library_ops import LibraryOps

from .test_library_ops import _setup
from .test_rederive_library import _load, _seed

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _part(profile, repo, part_id="aaa-1111"):
    rec = _seed(profile, repo, part_id, payload=None, derived_by="rules@2")
    path = profile.library.parts_dir / f"{part_id}.json"
    path.write_text(rec.dumps(), encoding="utf-8")
    repo.commit(f"seed {part_id}", [path])
    return part_id


def test_attaching_a_symbol_records_which_vendor_it_came_from(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _part(profile, repo)

    ops.attach_symbol(
        pid, "SR-ICs", "AAA",
        origin=AssetOrigin(vendor="ultralibrarian", url="https://ultralibrarian.com/x"),
        now_iso="2026-07-27T12:00:00Z",
    )

    origin = _load(profile, pid).assets_for("kicad").symbol.origin
    assert origin is not None
    assert (origin.vendor, origin.url) == ("ultralibrarian", "https://ultralibrarian.com/x")
    assert origin.captured_at == "2026-07-27T12:00:00Z"


def test_attaching_a_footprint_records_it_too(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _part(profile, repo)

    ops.attach_footprint(
        pid, "SR-ICs", "AAA",
        origin=AssetOrigin(vendor="samacsys", url="https://componentsearchengine.com/x"),
        now_iso="2026-07-27T12:00:00Z",
    )

    assert _load(profile, pid).assets_for("kicad").footprint.origin.vendor == "samacsys"


def test_an_attach_with_NO_origin_stays_honestly_unattributed(tmp_path, fixtures_dir):
    """`None` is not the same as an empty origin. An asset nobody recorded a source for must read
    as UNATTRIBUTED, never as one whose vendor happens to be the empty string -- that distinction
    is the whole reason `Asset.origin` is optional."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _part(profile, repo)

    ops.attach_symbol(pid, "SR-ICs", "AAA")

    assert _load(profile, pid).assets_for("kicad").symbol.origin is None


def test_repointing_an_asset_replaces_its_origin_rather_than_keeping_the_old_one(
    tmp_path, fixtures_dir
):
    """Provenance describes a FILE. Repoint the reference and the old provenance describes nothing
    -- keeping it would attach one vendor's name to another vendor's file, which is worse than no
    provenance at all."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _part(profile, repo)
    ops.attach_symbol(
        pid, "SR-ICs", "AAA",
        origin=AssetOrigin(vendor="snapmagic", url="https://snapeda.com/x"),
        now_iso="2026-07-27T12:00:00Z",
    )

    ops.attach_symbol(
        pid, "SR-ICs", "BBB",
        origin=AssetOrigin(vendor="ultralibrarian", url="https://ultralibrarian.com/y"),
        now_iso="2026-07-27T13:00:00Z",
    )

    origin = _load(profile, pid).assets_for("kicad").symbol.origin
    assert origin.vendor == "ultralibrarian"
    assert origin.captured_at == "2026-07-27T13:00:00Z"


def test_repointing_WITHOUT_an_origin_clears_the_stale_one(tmp_path, fixtures_dir):
    """The same rule in the other direction, and the one a naive implementation gets wrong: an
    attach that names no vendor must leave the asset UNATTRIBUTED rather than inheriting the
    previous file's provenance."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _part(profile, repo)
    ops.attach_symbol(
        pid, "SR-ICs", "AAA",
        origin=AssetOrigin(vendor="snapmagic", url="https://snapeda.com/x"),
        now_iso="2026-07-27T12:00:00Z",
    )

    ops.attach_symbol(pid, "SR-ICs", "BBB")

    assert _load(profile, pid).assets_for("kicad").symbol.origin is None


def test_the_library_can_be_asked_where_its_assets_came_from(tmp_path, fixtures_dir):
    """The owner's question, answerable at last. Their words: "its not trusted where we've gotten
    them" -- so the library has to be able to say where."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    pid = _part(profile, repo)
    ops.attach_symbol(
        pid, "SR-ICs", "AAA",
        origin=AssetOrigin(vendor="ultralibrarian", url="https://u/x"),
        now_iso="2026-07-27T12:00:00Z",
    )
    ops.attach_footprint(pid, "SR-ICs", "AAA")

    from stockroom.store.index import LibraryIndex

    index = LibraryIndex.build(profile.library.parts_dir)
    assert index.assets_by_vendor() == {"ultralibrarian": 1, "": 1}
