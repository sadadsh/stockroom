import sqlite3

from stockroom.model.part import AssetRef, EdaAssets, PartRecord


def _db_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in conn.execute('PRAGMA table_info("Parts")')]
        return [dict(zip(cols, row)) for row in conn.execute('SELECT * FROM "Parts"')]
    finally:
        conn.close()


def _place_ready(pid, mpn):
    return PartRecord(
        id=pid, display_name=pid, category="ICs", mpn=mpn, manufacturer="TI",
        description="d", value=mpn,
        eda={"altium": EdaAssets(
            symbol=AssetRef(lib=f"{pid}.SchLib", name=mpn),
            footprint=AssetRef(lib=f"{pid}.PcbLib", name="FP"),
        )},
    )


def test_regenerate_emits_only_place_ready(library_ops):
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    # not place-ready: no altium refs
    (ops.lib.parts_dir / "b.json").write_text(
        PartRecord(id="b", display_name="b", category="ICs", mpn="BBB").dumps(), encoding="utf-8")

    result = ops.regenerate_altium_dblib()

    assert result["emitted"] == 1
    assert "b" in result["skipped"]
    assert result["dblib"].exists()
    assert result["db"].exists()
    rows = _db_rows(result["db"])
    assert [r["MPN"] for r in rows] == ["AAA"]

    # Only the .DbLib is shared. The .db is derived from these very records, so committing it
    # (the 2026-07-23 decision, reversed 2026-07-25) made two peers adding different parts
    # conflict on an unmergeable binary carrying nothing the records did not already hold.
    ops = library_ops
    tracked = ops.repo._run("ls-files", "--", str(result["db"].parent)).stdout.splitlines()
    names = {p.rsplit("/", 1)[-1] for p in tracked}
    assert "stockroom-parts.db" not in names
    assert "Stockroom.DbLib" in names
    assert ".gitignore" not in names


def test_place_ready_does_not_require_a_persisted_value(library_ops):
    """The place-ready gate must NOT require record.value (nothing in the real pipeline sets it);
    the Value column is derived at emit time. A part with value="" but full identity + assets is
    emitted, with Value derived (an active's MPN)."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    rec = PartRecord(
        id="c", display_name="c", category="ICs", mpn="CCC", manufacturer="TI",
        description="a chip", value="",  # NOT populated by the real pipeline
        eda={"altium": EdaAssets(
            symbol=AssetRef(lib="c.SchLib", name="CCC"),
            footprint=AssetRef(lib="c.PcbLib", name="FP"),
        )},
    )
    (ops.lib.parts_dir / "c.json").write_text(rec.dumps(), encoding="utf-8")

    result = ops.regenerate_altium_dblib()

    assert result["emitted"] == 1  # emitted despite value==""
    row = _db_rows(result["db"])[0]
    assert row["Value"] == "CCC"  # derived (active -> MPN), not blank


def test_regenerate_is_idempotent(library_ops):
    """Regenerate runs on every data refresh; an unchanged .DbLib must not crash on an
    empty commit or spawn a noisy empty commit (GitRepo.commit no-ops on an empty diff)."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")

    ops.regenerate_altium_dblib()
    head_after_first = ops.repo.head()
    second = ops.regenerate_altium_dblib()  # identical content

    assert second["emitted"] == 1
    assert ops.repo.head() == head_after_first  # no new (empty) commit
    assert second["dblib"].exists()


def test_regenerate_survives_a_staged_never_committed_gitignore(library_ops):
    # The live winverify failure (2026-07-23): an interrupted pre-migration run left
    # altium/.gitignore STAGED but never committed. _is_tracked (an index read) calls it
    # tracked, so the retirement joins the commit pathspec; `add -A` erases the staged
    # entry and `commit --only` aborts on a path git no longer knows - 500ing every
    # regenerate on that library forever. It must succeed and retire the file.
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    altium_dir = ops.lib.parts_dir.parent / "altium"
    altium_dir.mkdir(parents=True, exist_ok=True)
    gi = altium_dir / ".gitignore"
    gi.write_text("stockroom-parts.xlsx\n", encoding="utf-8")
    ops.repo._run("add", "--", str(gi))  # staged, never committed (the interrupted-run state)

    result = ops.regenerate_altium_dblib()

    assert result["emitted"] == 1
    assert not gi.exists()  # retired from disk
    tracked = ops.repo._run("ls-files", "--", str(altium_dir)).stdout.splitlines()
    assert not any(p.endswith(".gitignore") for p in tracked)


def test_the_derived_data_source_is_no_longer_shared_through_git(library_ops):
    """Batch 2 item 3. The .db is emitted from the JSON records, so sharing it means two peers who
    each add a DIFFERENT part produce two unmergeable binaries carrying nothing the records do not
    already hold. It is now ignored and untracked; only the .DbLib stays shared."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")

    result = ops.regenerate_altium_dblib()

    assert result["db"].exists()  # still on disk, so Altium can read it
    tracked = ops.repo._run("ls-files", "--", str(result["db"].parent)).stdout.splitlines()
    names = {p.rsplit("/", 1)[-1] for p in tracked}
    assert "stockroom-parts.db" not in names
    assert "Stockroom.DbLib" in names


def test_a_library_that_already_committed_the_data_source_is_migrated_by_a_regenerate(library_ops):
    """The owner's library HAS the .db committed. An ignore rule does nothing to a tracked file, so
    without an explicit untrack every regenerate would leave their tree dirty forever."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    altium_dir = ops.lib.parts_dir.parent / "altium"
    altium_dir.mkdir(parents=True, exist_ok=True)
    legacy = altium_dir / "stockroom-parts.db"
    legacy.write_bytes(b"SQLite format 3\x00legacy")
    ops.repo.commit("legacy: commit the derived data source", [legacy], force=True)
    assert "stockroom-parts.db" in ops.repo._run("ls-files", "--", str(altium_dir)).stdout

    result = ops.regenerate_altium_dblib()

    assert result["migration_blocked"] == ""
    assert "stockroom-parts.db" not in ops.repo._run("ls-files", "--", str(altium_dir)).stdout
    assert legacy.exists()  # untracked, never deleted: Altium still needs to read it
    # The ignore rule is written too, or `git status` would show the file as untracked forever.
    # That is why the migration runs the library's own hygiene rather than a bare `git rm --cached`.
    assert "stockroom-parts.db" in (ops.repo.root / ".gitignore").read_text(encoding="utf-8")
    # and the tree is clean afterwards, which is the property the owner actually observes
    assert ops.repo.is_clean([altium_dir])


def test_the_automatic_ensure_never_dirties_a_tree_that_has_not_migrated_yet(library_ops):
    """Two peers on different SQLite builds hold byte-different but content-IDENTICAL files, so
    rewriting a still-tracked copy at boot would achieve nothing except making their tree dirty."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    altium_dir = ops.lib.parts_dir.parent / "altium"
    altium_dir.mkdir(parents=True, exist_ok=True)
    legacy = altium_dir / "stockroom-parts.db"
    legacy.write_bytes(b"SQLite format 3\x00a peer's bytes")
    ops.repo.commit("legacy: commit the derived data source", [legacy], force=True)

    result = ops.ensure_altium_datasource()

    assert result["written"] is False
    assert result["reason"] == "shared"
    assert legacy.read_bytes() == b"SQLite format 3\x00a peer's bytes"
    assert ops.repo.is_clean([altium_dir])


def test_ensure_builds_the_data_source_on_a_fresh_clone_without_committing(library_ops):
    """The property the old commit was bought for: a fresh clone must be placeable. It is now
    bought by rebuilding on demand instead of by sharing a derived binary."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    head_before = ops.repo.head()

    result = ops.ensure_altium_datasource()

    assert result["written"] is True
    assert result["reason"] == "missing"
    assert result["path"].exists()
    assert [r["MPN"] for r in _db_rows(result["path"])] == ["AAA"]
    assert ops.repo.head() == head_before  # nothing committed


def test_ensure_rewrites_nothing_when_the_data_source_already_matches(library_ops):
    """A rewrite on every boot would dirty the tree of anyone who has not migrated yet, and would
    churn the mtime for no reason. Same-machine byte determinism is what makes this checkable."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    ops.ensure_altium_datasource()
    before = (ops.lib.parts_dir.parent / "altium" / "stockroom-parts.db").read_bytes()

    result = ops.ensure_altium_datasource()

    assert result["written"] is False
    assert result["reason"] == "current"
    assert result["path"].read_bytes() == before


def test_ensure_rebuilds_after_the_library_changes(library_ops):
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    ops.ensure_altium_datasource()

    (ops.lib.parts_dir / "b.json").write_text(_place_ready("b", "BBB").dumps(), encoding="utf-8")
    result = ops.ensure_altium_datasource()

    assert result["written"] is True
    assert result["reason"] == "stale"
    assert [r["MPN"] for r in _db_rows(result["path"])] == ["AAA", "BBB"]
