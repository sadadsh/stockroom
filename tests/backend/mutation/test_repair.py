"""M6f doctor repair: scan_repairs() reports every self-healable defect and every
manual-only finding, and apply_repairs() heals drift + rewrites non-portable 3D-model
links + commits stray files in one git-backed transaction, leaving the manual findings
honestly untouched. Built on the same add_part path the rest of the suite exercises."""

import shutil

import pytest

from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.part import PartRecord
from stockroom.mutation.library_ops import LibraryOps

from .test_library_ops import _setup

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _healthy(tmp_path, fixtures_dir):
    """A committed, drift-free single-part library and its ops handle."""
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    record = ops.add_part(staged)
    assert repo.is_clean()  # the fixture must start clean or the tests below are meaningless
    return repo, profile, ops, record


def _fp_path(profile, record):
    return profile.library.footprint_lib_path(record.category) / f"{record.footprint.name}.kicad_mod"


# ---------------------------------------------------------------- scan


def test_scan_clean_library_is_healthy(tmp_path, fixtures_dir):
    _, _, ops, _ = _healthy(tmp_path, fixtures_dir)
    plan = ops.scan_repairs()
    assert plan.is_healthy
    assert plan.fixable == []
    assert plan.manual == []
    assert plan.uncommitted == []


def test_scan_finds_drift_as_fixable(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    sp = profile.library.symbol_lib_path("ICs")
    lib = SymbolLib.load(sp)
    lib.get_symbol(record.symbol.name).set_property("Manufacturer", "WRONG")
    lib.save(sp)

    plan = ops.scan_repairs()
    drift = [a for a in plan.fixable if a.kind == "drift"]
    assert len(drift) == 1
    assert drift[0].part_id == record.id
    assert drift[0].before == "WRONG"
    assert drift[0].after == "TI"


def test_scan_finds_non_portable_model_path_as_fixable(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    fp_path = _fp_path(profile, record)
    fp = Footprint.load(fp_path)
    basename = record.model.file.split("/")[-1]
    fp.set_model_path(f"C:\\Users\\someone\\models\\{basename}")  # absolute, non-portable
    fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")

    plan = ops.scan_repairs()
    paths = [a for a in plan.fixable if a.kind == "model_path"]
    assert len(paths) == 1
    assert paths[0].part_id == record.id
    assert paths[0].after == f"${{SR_LIB}}/models/{basename}"


def test_scan_finds_dangling_model_and_datasheet_as_manual(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    (profile.library.root / record.model.file).unlink()
    (profile.library.datasheets_dir / record.datasheet.file).unlink()

    plan = ops.scan_repairs()
    kinds = {f.kind for f in plan.manual}
    assert "dangling_model" in kinds
    assert "dangling_datasheet" in kinds
    # a missing FILE is never auto-fixed (we cannot fabricate it)
    assert all(f.how_to_fix for f in plan.manual)
    assert not any(a.kind in ("dangling_model", "dangling_datasheet") for a in plan.fixable)


def test_scan_finds_missing_symbol_as_manual(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    sp = profile.library.symbol_lib_path("ICs")
    # blank the category symbol lib so the part's symbol vanishes
    sp.write_text(
        '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "x")\n)\n',
        encoding="utf-8", newline="",
    )
    plan = ops.scan_repairs()
    assert any(f.kind == "missing_symbol" and f.part_id == record.id for f in plan.manual)


def test_scan_reports_uncommitted_files(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    (profile.library.datasheets_dir / "stray.pdf").write_bytes(b"%PDF-1.4\n")
    plan = ops.scan_repairs()
    assert any("stray.pdf" in line for line in plan.uncommitted)


# ---------------------------------------------------------------- apply


def test_apply_heals_drift_to_the_json_source_of_truth(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    sp = profile.library.symbol_lib_path("ICs")
    lib = SymbolLib.load(sp)
    lib.get_symbol(record.symbol.name).set_property("Manufacturer", "WRONG")
    lib.save(sp)

    result = ops.apply_repairs()
    assert result.healed_drift == 1
    # the symbol now matches the record (JSON is the source of truth)
    healed = SymbolLib.load(sp).get_symbol(record.symbol.name).get_property("Manufacturer")
    assert healed == "TI"
    # and a fresh scan is drift-free
    assert not [a for a in ops.scan_repairs().fixable if a.kind == "drift"]


def test_apply_rewrites_non_portable_model_path(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    fp_path = _fp_path(profile, record)
    fp = Footprint.load(fp_path)
    basename = record.model.file.split("/")[-1]
    fp.set_model_path(f"/home/someone/models/{basename}")
    fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")

    result = ops.apply_repairs()
    assert result.fixed_paths == 1
    assert Footprint.load(fp_path).model_path == f"${{SR_LIB}}/models/{basename}"


def test_apply_commits_the_repair_and_stray_assets(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    before = repo.head()
    # a stray committed-worthy asset + a real drift
    (profile.library.datasheets_dir / "stray.pdf").write_bytes(b"%PDF-1.4\n")
    sp = profile.library.symbol_lib_path("ICs")
    lib = SymbolLib.load(sp)
    lib.get_symbol(record.symbol.name).set_property("Description", "SCRIBBLE")
    lib.save(sp)

    result = ops.apply_repairs()
    assert result.commit and result.commit != before
    assert repo.is_clean()  # working tree fully swept after the repair


def test_apply_leaves_manual_findings_untouched(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    (profile.library.root / record.model.file).unlink()

    result = ops.apply_repairs()
    assert any(f.kind == "dangling_model" for f in result.manual)
    # a dangling file is never silently "fixed" by deleting the reference
    assert PartRecord.loads(
        (profile.library.parts_dir / f"{record.id}.json").read_text(encoding="utf-8")
    ).model is not None


def test_apply_on_healthy_library_is_a_no_op(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    before = repo.head()
    result = ops.apply_repairs()
    assert result.healed_drift == 0
    assert result.fixed_paths == 0
    assert result.commit in ("", before)  # no new commit created
    assert repo.head() == before


def test_apply_model_path_repair_is_idempotent(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    fp_path = _fp_path(profile, record)
    fp = Footprint.load(fp_path)
    basename = record.model.file.split("/")[-1]
    fp.set_model_path(f"/abs/{basename}")
    fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")

    assert ops.apply_repairs().fixed_paths == 1
    # a second pass finds the link already canonical -> nothing to rewrite
    assert ops.apply_repairs().fixed_paths == 0


def test_scan_reports_a_missing_model_once_not_twice(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    (profile.library.root / record.model.file).unlink()  # the footprint link now dangles too
    plan = ops.scan_repairs()
    model_findings = [f for f in plan.manual if f.part_id == record.id and "model" in f.kind]
    assert len(model_findings) == 1  # the record-level dangling_model owns it, not double-reported
    assert model_findings[0].kind == "dangling_model"


def _other_profile(profile, repo):
    from stockroom.store.profile import ProfileStore

    return ProfileStore(profile.library.root.parent, repo).create("Other")


def test_apply_does_not_commit_another_profiles_uncommitted_files(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    other = _other_profile(profile, repo)
    (other.library.parts_dir / "wip.json").write_text('{"in": "progress"}', encoding="utf-8")
    # a real defect to repair in the ACTIVE profile
    sp = profile.library.symbol_lib_path("ICs")
    sl = SymbolLib.load(sp)
    sl.get_symbol(record.symbol.name).set_property("Description", "SCRIBBLE")
    sl.save(sp)

    ops.apply_repairs()
    # the OTHER profile's in-progress edit is never swept into the active repair
    dirty = [line.replace("\\", "/") for line in repo.status_porcelain()]
    assert any("Other/parts/wip.json" in line for line in dirty)


def test_apply_commits_both_sides_of_a_staged_rename(tmp_path, fixtures_dir):
    import subprocess

    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    old = profile.library.datasheets_dir / record.datasheet.file
    new = profile.library.datasheets_dir / "renamed.pdf"
    subprocess.run(["git", "-C", str(repo.root), "mv", str(old), str(new)], check=True)

    ops.apply_repairs()
    assert repo.is_clean()  # both the deletion of old and the add of new are committed


def test_apply_commits_a_non_ascii_stray_file(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    (profile.library.datasheets_dir / "café.pdf").write_bytes(b"%PDF-1.4\n")
    ops.apply_repairs()  # must not raise on git's octal-quoted porcelain path
    assert repo.is_clean()


def test_apply_skips_and_reports_an_unparseable_stray_file(tmp_path, fixtures_dir):
    repo, profile, ops, record = _healthy(tmp_path, fixtures_dir)
    # a real drift to heal (committed value, so healing produces a real change)
    sp = profile.library.symbol_lib_path("ICs")
    sl = SymbolLib.load(sp)
    sl.get_symbol(record.symbol.name).set_property("Manufacturer", "WRONG")
    sl.save(sp)
    repo.commit("commit the drifted symbol", [sp])
    # a malformed KiCad file dropped into the library
    bad = profile.library.footprint_lib_path("ICs") / "broken.kicad_mod"
    bad.write_text("(footprint", encoding="utf-8", newline="")

    result = ops.apply_repairs()
    # the legitimate heal is NOT rolled back by the bad stray file
    assert result.healed_drift == 1
    assert SymbolLib.load(sp).get_symbol(record.symbol.name).get_property("Manufacturer") == "TI"
    # the malformed file is surfaced honestly and never committed
    assert any(f.kind == "unparseable_file" for f in ops.scan_repairs().manual)
    assert any("broken.kicad_mod" in line for line in repo.status_porcelain())
