"""M7g Buildability: fuse completeness (live) + ERC/DRC (cached) + BOM (cached) + git into
ONE ready-to-build verdict. READ-only. A cold checks/BOM cache is an HONEST 'not run yet'
hard blocker, never a fabricated pass (a false READY is worse than a false NOT-READY)."""

from __future__ import annotations

import shutil

import pytest

from stockroom.mutation.project_ops import ProjectOps
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

_COMPLETE = {"MPN": "LM358DR", "Manufacturer": "TI", "Datasheet": "http://x", "Description": "opamp"}
_CHECKS_OK = {"ran_at": "2026-07-14T00:00:00Z",
              "summary": {"ok": True, "errors": 0, "warnings": 0, "checked": 2}}
_CHECKS_WARN = {"ran_at": "2026-07-14T00:00:00Z",
                "summary": {"ok": True, "errors": 0, "warnings": 3, "checked": 2}}
_CHECKS_ERR = {"ran_at": "2026-07-14T00:00:00Z",
               "summary": {"ok": True, "errors": 2, "warnings": 0, "checked": 2}}
_BOM_OK = {"ran_at": "2026-07-14T00:00:00Z", "boards": 1, "priced": True,
           "lines": [{"mpn": "X", "qty": 1, "stock": 100, "unit_price": 0.1,
                      "extended": 0.1, "lifecycle": "Active"}],
           "summary": {"unpriced_lines": 0}}
_BOM_STOCK = {"ran_at": "2026-07-14T00:00:00Z", "boards": 1, "priced": True,
              "lines": [{"mpn": "X", "qty": 5, "stock": 0, "unit_price": 0.1,
                         "extended": 0.5, "lifecycle": "Active"}],
              "summary": {"unpriced_lines": 0}}


def _ops(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repo = GitRepo(repo_root)
    repo.init()
    (repo_root / "seed.txt").write_text("seed", encoding="utf-8")
    repo.commit("seed", [repo_root / "seed.txt"])
    return ProjectOps(ProjectStore(repo_root / ".projects", repo))


def _sym(ref, *, footprint="Resistor_SMD:R_0402", props=None, lib_id="Device:R", uuid="u"):
    fields = {"Reference": ref, "Value": "x", "Footprint": footprint, **(props or {})}
    nodes = "".join(f'\t\t(property "{k}" "{v}"\n\t\t\t(at 0 0 0)\n\t\t)\n' for k, v in fields.items())
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "{lib_id}")\n\t\t(at 0 0 0)\n\t\t(unit 1)\n\t\t(uuid "{uuid}")\n'
        + nodes
        + f'\t\t(instances\n\t\t\t(project "p"\n\t\t\t\t(path "/r"\n\t\t\t\t\t(reference "{ref}")'
        + "\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n"
    )


def _sheet(symbols):
    return "(kicad_sch\n\t(version 20260306)\n" + "".join(symbols) + ")\n"


_FRESH = _sheet([_sym("R?", uuid="r"), _sym("U?", footprint="Package_SO:SOIC-8", lib_id="SR:LM358", uuid="u")])
_DONE = _sheet([_sym("U1", footprint="Package_SO:SOIC-8", props=_COMPLETE, lib_id="SR:LM358", uuid="u1")])
_NOFP = _sheet([_sym("R1", footprint="", props=_COMPLETE, uuid="r1")])
# annotated + footprinted, but missing MPN/Manufacturer/Datasheet/Description: an identity
# warning with NO hard blocker (so the completeness signal should read "warn", not "pass").
_ANNOT_NO_MPN = _sheet([_sym("R1", footprint="Resistor_SMD:R_0402", uuid="r1")])


def _git_project(dir_path, sheet=_FRESH):
    dir_path.mkdir(parents=True, exist_ok=True)
    prepo = GitRepo(dir_path)
    prepo.init()
    (dir_path / "proj.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "proj.kicad_sch").write_text(sheet, encoding="utf-8")
    prepo.commit("init", [dir_path / "proj.kicad_pro", dir_path / "proj.kicad_sch"])
    return dir_path, prepo


def test_unknown_id_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        _ops(tmp_path).buildability("nope")


def test_fresh_project_cold_caches_not_ready(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    v = ops.buildability(rec.id)  # no checks, no bom cache
    assert v["ready"] is False
    kinds = {b["kind"] for b in v["blockers"]}
    assert "unannotated" in kinds  # R?, U?
    assert "checks_not_run" in kinds  # cold cache -> honest blocker, never a pass
    assert "bom_not_built" in kinds
    assert "missing_footprint" not in kinds  # both have footprints
    # cold caches are surfaced as their honest states, not fabricated passes
    assert v["signals"]["checks"]["state"] == "not_run"
    assert v["signals"]["bom"]["state"] == "not_built"
    # incomplete identity is a warning, not a blocker
    assert any(w["kind"] == "identity_incomplete" for w in v["warnings"])


def test_ready_when_every_signal_passes(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p", sheet=_DONE)
    rec = ops.register(proj)
    v = ops.buildability(rec.id, checks=_CHECKS_OK, bom=_BOM_OK)
    assert v["ready"] is True
    assert v["blockers"] == []
    assert v["signals"]["completeness"]["state"] == "pass"
    assert v["signals"]["checks"]["state"] == "pass"
    assert v["signals"]["bom"]["state"] == "pass"
    assert v["signals"]["git"]["state"] == "clean"


def test_checks_errors_block(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p", sheet=_DONE)
    rec = ops.register(proj)
    v = ops.buildability(rec.id, checks=_CHECKS_ERR, bom=_BOM_OK)
    assert v["ready"] is False
    assert any(b["kind"] == "checks_failed" for b in v["blockers"])
    assert v["signals"]["checks"]["state"] == "fail"


def test_checks_warnings_do_not_block(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p", sheet=_DONE)
    rec = ops.register(proj)
    v = ops.buildability(rec.id, checks=_CHECKS_WARN, bom=_BOM_OK)
    assert v["ready"] is True
    assert any(w["kind"] == "checks_warnings" for w in v["warnings"])
    # review fix: the chip must read "warn" (amber), agreeing with the Checks section below,
    # not "pass" (green).
    assert v["signals"]["checks"]["state"] == "warn"


def test_identity_incomplete_downgrades_completeness_to_warn(tmp_path):
    # A fully annotated + footprinted board that still lacks MPN/datasheet is a warning, not a
    # hard blocker; its completeness chip must read "warn", not "pass".
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p", sheet=_ANNOT_NO_MPN)
    rec = ops.register(proj)
    v = ops.buildability(rec.id, checks=_CHECKS_OK, bom=_BOM_OK)
    assert v["signals"]["completeness"]["state"] == "warn"
    assert any(w["kind"] == "identity_incomplete" for w in v["warnings"])
    assert v["ready"] is True


def test_unannotated_blocker_remedy_names_kicad(tmp_path):
    # Multi-unit / repeated-hierarchy refs are DEFERRED to KiCad by Prepare, so the remedy must
    # not be a Prepare-only dead-end that provably cannot clear the blocker.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")  # _FRESH has unannotated R?/U?
    rec = ops.register(proj)
    v = ops.buildability(rec.id)
    b = next(b for b in v["blockers"] if b["kind"] == "unannotated")
    assert "KiCad" in b["next_step"]


def test_bom_stock_risk_is_warning_not_blocker(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p", sheet=_DONE)
    rec = ops.register(proj)
    v = ops.buildability(rec.id, checks=_CHECKS_OK, bom=_BOM_STOCK)
    assert v["ready"] is True  # a stock-out is a warning, not a design-level NOT READY
    assert any(w["kind"] == "bom_stock" for w in v["warnings"])
    assert v["signals"]["bom"]["state"] == "warn"


def test_missing_footprint_blocks(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p", sheet=_NOFP)
    rec = ops.register(proj)
    v = ops.buildability(rec.id, checks=_CHECKS_OK, bom=_BOM_OK)
    assert v["ready"] is False
    assert any(b["kind"] == "missing_footprint" for b in v["blockers"])


def test_dirty_tree_is_a_warning(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p", sheet=_DONE)
    rec = ops.register(proj)
    (proj / "proj.kicad_sch").write_text(_DONE.replace("opamp", "opamp v2"), encoding="utf-8")  # valid uncommitted edit
    v = ops.buildability(rec.id, checks=_CHECKS_OK, bom=_BOM_OK)
    assert v["signals"]["git"]["state"] == "dirty"
    assert any(w["kind"] == "dirty_tree" for w in v["warnings"])
    assert v["ready"] is True  # dirty tree is a reproducibility warning, not a hard blocker


def test_not_git_project_is_a_warning(tmp_path):
    ops = _ops(tmp_path)
    proj = tmp_path / "ext" / "p"
    proj.mkdir(parents=True)
    (proj / "proj.kicad_pro").write_text("{}", encoding="utf-8")
    (proj / "proj.kicad_sch").write_text(_DONE, encoding="utf-8")
    rec = ops.register(proj)
    v = ops.buildability(rec.id, checks=_CHECKS_OK, bom=_BOM_OK)
    assert v["signals"]["git"]["state"] == "not_git"
    assert any(w["kind"] == "not_git" for w in v["warnings"])
