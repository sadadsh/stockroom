"""M7f-D project_ops Prepare / Complete-All / manual fill / Restore: the atomic write orchestration
(mirrors the conform_apply / stackup_apply precedents). Prepare annotates references and auto-fills
blank identity fields from the shared library as ONE scoped commit on the project's own git; a manual
fill links one component to a chosen library part; Restore git-reverts the last Prepare/Fill. Every
write is one atomic commit or zero trace, with an honest no-commit no-op when nothing changes."""

from __future__ import annotations

import shutil

import pytest

from stockroom.model.part import Datasheet, LibRef, PartRecord
from stockroom.mutation.project_ops import ProjectOps
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _ops(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repo = GitRepo(repo_root)
    repo.init()
    (repo_root / "seed.txt").write_text("seed", encoding="utf-8")
    repo.commit("seed", [repo_root / "seed.txt"])
    store = ProjectStore(repo_root / ".projects", repo)
    return ProjectOps(store)


def _symbol(*, lib_id, ref, value="10k", footprint="Resistor_SMD:R_0402",
            datasheet="~", uuid="u-0000"):
    return "".join([
        "\t(symbol\n",
        f'\t\t(lib_id "{lib_id}")\n',
        "\t\t(at 10 10 0)\n\t\t(unit 1)\n\t\t(in_bom yes)\n\t\t(dnp no)\n",
        f'\t\t(uuid "{uuid}")\n',
        f'\t\t(property "Reference" "{ref}"\n\t\t\t(at 10 8 0)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        f'\t\t(property "Value" "{value}"\n\t\t\t(at 12 10 0)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        f'\t\t(property "Footprint" "{footprint}"\n\t\t\t(at 10 10 0)\n\t\t\t(hide yes)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        f'\t\t(property "Datasheet" "{datasheet}"\n\t\t\t(at 10 10 0)\n\t\t\t(hide yes)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        '\t\t(instances\n\t\t\t(project "proj"\n',
        f'\t\t\t\t(path "/root-uuid"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n',
        "\t)\n",
    ])


def _sheet(symbols):
    return "(kicad_sch\n\t(version 20260306)\n" + "".join(symbols) + ")\n"


# A sheet with an unannotated resistor R? (generic), an unannotated capacitor C?, and a U? that
# matches the library op-amp by symbol name (so Prepare annotates 3 and fills U's blank identity).
_SHEET_A = _sheet([
    _symbol(lib_id="Device:R", ref="R?", value="10k", uuid="a-r"),
    _symbol(lib_id="Device:C", ref="C?", value="100nF", footprint="Capacitor_SMD:C_0402", uuid="a-c"),
    _symbol(lib_id="SR-ICs:LM358", ref="U?", value="LM358", footprint="Package_SO:SOIC-8", uuid="a-u"),
])


def _parts():
    return [
        PartRecord(
            id="lm358", display_name="LM358 Op-Amp", category="ICs",
            description="Dual op-amp", mpn="LM358DR", manufacturer="TI",
            symbol=LibRef(lib="SR-ICs", name="LM358"),
            footprint=LibRef(lib="SR-ICs", name="SOIC-8"),
            datasheet=Datasheet(file="lm358.pdf", source_url="https://ti.com/lm358.pdf"),
        ),
        PartRecord(
            id="r10k", display_name="10k 0402", category="Resistors",
            description="10k 1% 0402", mpn="RC0402FR-0710KL", manufacturer="Yageo",
            symbol=LibRef(lib="SR-Resistors", name="R_10k"),
            footprint=LibRef(lib="SR-Resistors", name="R_0402"),
            datasheet=Datasheet(file="r.pdf", source_url="https://yageo.com/r.pdf"),
        ),
    ]


def _git_project(dir_path, sheets=None):
    dir_path.mkdir(parents=True, exist_ok=True)
    prepo = GitRepo(dir_path)
    prepo.init()
    tracked = [dir_path / "proj.kicad_pro"]
    (dir_path / "proj.kicad_pro").write_text("{}", encoding="utf-8")
    for name, text in (sheets or {"proj.kicad_sch": _SHEET_A}).items():
        (dir_path / name).write_text(text, encoding="utf-8")
        tracked.append(dir_path / name)
    prepo.commit("init", tracked)
    return dir_path, prepo


def _no_git_project(dir_path):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "proj.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "proj.kicad_sch").write_text(_SHEET_A, encoding="utf-8")
    return dir_path


# --- prepare_read (preview) ---------------------------------------------------


def test_prepare_read_reports_annotate_fill_and_residual(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    before = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    head = prepo.head()

    r = ops.prepare_read(rec.id, library_parts=_parts())
    assert r["under_git"] is True and r["has_sch"] is True
    assert r["annotate"] == 3  # R?, C?, U?
    assert r["fill_fields"] >= 3  # U gets MPN + Manufacturer + Description (+ Datasheet)
    # the plan lists the matched op-amp (by symbol); the residual after auto-fill still lists R/C
    matched = {i["part_id"] for i in r["plan"]["items"]}
    assert "lm358" in matched
    assert r["completion_after"]["complete"] <= r["completion_after"]["total"]
    # a preview writes nothing and commits nothing
    assert (proj / "proj.kicad_sch").read_text(encoding="utf-8") == before
    assert prepo.head() == head


def test_prepare_read_completion_uses_disk_refs_not_projected_ones(tmp_path):
    # The preview's `completion.incomplete_refs` must be the CURRENT on-disk designators, so the
    # manual-fill picker only ever names a ref that exists on disk. A fresh project's R? / C? are still
    # unannotated on disk; the projection (completion_after) uses the annotated R1 / C1 they WILL be.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    r = ops.prepare_read(rec.id, library_parts=_parts())
    current = set(r["completion"]["incomplete_refs"])
    assert "R?" in current and "C?" in current  # disk designators, not R1/C1
    assert "R1" not in current
    # and a manual fill on a picker-offered ref actually finds the component (no phantom-ref 400)
    ops.manual_fill(rec.id, "R?", "r10k", library_parts=_parts())
    after = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    assert '(property "MPN" "RC0402FR-0710KL"' in after
    # the projection names the annotated designators Prepare would assign
    proj_after = set(r["completion_after"]["incomplete_refs"])
    assert "R1" in proj_after or "C1" in proj_after


def test_prepare_read_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.prepare_read("nope")


# --- prepare_apply ------------------------------------------------------------


def test_prepare_apply_annotates_and_fills_one_commit(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    head_before = prepo.head()

    result = ops.prepare_apply(rec.id, library_parts=_parts())

    after = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    assert result["annotated"] == 3
    assert '(property "Reference" "R1"' in after
    assert '(reference "R1")' in after  # both forms annotated
    assert '(property "Reference" "U1"' in after
    # U1's blank identity filled from the library
    assert '(property "MPN" "LM358DR"' in after
    assert '(property "Manufacturer" "TI"' in after
    assert result["committed"] == prepo.head() and prepo.head() != head_before
    assert prepo.is_clean()
    # exactly one commit added
    assert prepo._run("rev-list", "--count", f"{head_before}..HEAD").stdout.strip() == "1"
    assert result["committed"].startswith(tuple("0123456789abcdef"))


def test_prepare_apply_noop_when_nothing_to_do(tmp_path):
    ops = _ops(tmp_path)
    # a fully annotated, fully filled sheet with no library match -> nothing to prepare
    done = _sheet([_symbol(lib_id="Device:R", ref="R1", value="47k", uuid="d")])
    proj, prepo = _git_project(tmp_path / "ext" / "p", sheets={"proj.kicad_sch": done})
    rec = ops.register(proj)
    head = prepo.head()
    result = ops.prepare_apply(rec.id, library_parts=_parts())
    assert result["committed"] is None
    assert result["annotated"] == 0 and result["fill_fields"] == 0
    assert prepo.head() == head


def test_prepare_apply_refuses_non_git(tmp_path):
    ops = _ops(tmp_path)
    proj = _no_git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.prepare_apply(rec.id, library_parts=_parts())


def test_prepare_apply_project_wide_unique_across_sheets(tmp_path):
    ops = _ops(tmp_path)
    a = _sheet([_symbol(lib_id="Device:R", ref="R?", uuid="s1")])
    b = _sheet([_symbol(lib_id="Device:R", ref="R?", uuid="s2")])
    proj, _ = _git_project(tmp_path / "ext" / "p",
                           sheets={"a.kicad_sch": a, "b.kicad_sch": b})
    rec = ops.register(proj)
    ops.prepare_apply(rec.id, library_parts=_parts())
    ta = (proj / "a.kicad_sch").read_text(encoding="utf-8")
    tb = (proj / "b.kicad_sch").read_text(encoding="utf-8")
    refs = {ta.count('"R1"'), tb.count('"R2"')}
    assert '(property "Reference" "R1"' in ta
    assert '(property "Reference" "R2"' in tb  # no collision across sheets


def test_prepare_apply_progress_is_reported(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    seen = []
    ops.prepare_apply(rec.id, library_parts=_parts(), progress=lambda d: seen.append(d))
    assert seen and seen[-1]["pct"] == 100
    assert all("message" in d for d in seen)


def test_prepare_apply_raising_write_leaves_zero_trace(tmp_path, monkeypatch):
    from stockroom.sexp.document import SexpDocument

    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    sch = proj / "proj.kicad_sch"
    before = sch.read_text(encoding="utf-8")
    head = prepo.head()

    def _boom(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(SexpDocument, "save", _boom)
    with pytest.raises(Exception):
        ops.prepare_apply(rec.id, library_parts=_parts())
    assert sch.read_text(encoding="utf-8") == before
    assert prepo.head() == head and prepo.is_clean()


# --- manual_fill --------------------------------------------------------------


def test_manual_fill_links_ref_to_library_part(tmp_path):
    ops = _ops(tmp_path)
    # R1 (generic Device:R) manually linked to the library resistor
    sheet = _sheet([_symbol(lib_id="Device:R", ref="R1", value="10k", uuid="m")])
    proj, prepo = _git_project(tmp_path / "ext" / "p", sheets={"proj.kicad_sch": sheet})
    rec = ops.register(proj)
    result = ops.manual_fill(rec.id, "R1", "r10k", library_parts=_parts())
    after = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    assert '(lib_id "SR-Resistors:R_10k")' in after  # repointed
    assert '(property "MPN" "RC0402FR-0710KL"' in after
    assert '(property "Footprint" "SR-Resistors:R_0402"' in after  # overwrite allowed
    assert result["committed"] == prepo.head()


def test_manual_fill_unknown_part_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.manual_fill(rec.id, "R?", "nope", library_parts=_parts())


def test_manual_fill_unknown_ref_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    head = prepo.head()
    with pytest.raises(ValueError):
        ops.manual_fill(rec.id, "Z99", "r10k", library_parts=_parts())
    assert prepo.head() == head  # nothing committed


def test_manual_fill_noop_when_already_linked(tmp_path):
    ops = _ops(tmp_path)
    # a component already carrying the library part's exact identity -> no byte change -> no commit
    ops.manual_fill  # noqa: B018
    sheet = _sheet([_symbol(lib_id="SR-Resistors:R_10k", ref="R1", value="10k",
                            footprint="SR-Resistors:R_0402",
                            datasheet="https://yageo.com/r.pdf", uuid="al")])
    proj, prepo = _git_project(tmp_path / "ext" / "p", sheets={"proj.kicad_sch": sheet})
    rec = ops.register(proj)
    # first fill lands MPN/Manufacturer/Description (absent); a second fill is a no-op
    ops.manual_fill(rec.id, "R1", "r10k", library_parts=_parts())
    head = prepo.head()
    result = ops.manual_fill(rec.id, "R1", "r10k", library_parts=_parts())
    assert result["committed"] is None
    assert prepo.head() == head


def test_manual_fill_refuses_non_git(tmp_path):
    ops = _ops(tmp_path)
    proj = _no_git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.manual_fill(rec.id, "R?", "r10k", library_parts=_parts())


# --- restore ------------------------------------------------------------------


def test_restore_reverts_last_prepare(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    before = (proj / "proj.kicad_sch").read_text(encoding="utf-8")

    applied = ops.prepare_apply(rec.id, library_parts=_parts())
    assert applied["committed"]
    assert (proj / "proj.kicad_sch").read_text(encoding="utf-8") != before

    result = ops.restore(rec.id)
    assert result["restored"] == applied["committed"]
    # the revert restores the pre-Prepare bytes exactly
    assert (proj / "proj.kicad_sch").read_text(encoding="utf-8") == before
    assert result["committed"] == prepo.head() and prepo.is_clean()


def test_restore_reverts_last_manual_fill(tmp_path):
    ops = _ops(tmp_path)
    sheet = _sheet([_symbol(lib_id="Device:R", ref="R1", value="10k", uuid="m")])
    proj, _ = _git_project(tmp_path / "ext" / "p", sheets={"proj.kicad_sch": sheet})
    rec = ops.register(proj)
    before = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    ops.manual_fill(rec.id, "R1", "r10k", library_parts=_parts())
    result = ops.restore(rec.id)
    assert result["subject"].startswith("Fill ")
    assert (proj / "proj.kicad_sch").read_text(encoding="utf-8") == before


def test_restore_nothing_to_restore_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.restore(rec.id)  # no Prepare/Fill commit yet


def test_restore_refuses_dirty_tree(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    ops.prepare_apply(rec.id, library_parts=_parts())
    # dirty the sheet after Prepare
    sch = proj / "proj.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8") + "\n; dirty\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ops.restore(rec.id)


def test_restore_refuses_non_git(tmp_path):
    ops = _ops(tmp_path)
    proj = _no_git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.restore(rec.id)


def test_second_restore_skips_the_already_reverted_commit(tmp_path):
    # A repeated Restore must NOT re-target the commit it already reverted (git would refuse the empty
    # revert with a conflict/503); with only one Prepare, the second Restore is an honest "nothing to
    # restore" (400), never a 503.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    ops.prepare_apply(rec.id, library_parts=_parts())
    ops.restore(rec.id)  # reverts the Prepare
    with pytest.raises(ValueError):
        ops.restore(rec.id)  # the Prepare is already reverted -> nothing left to restore


def test_prepare_apply_refuses_a_dirty_sheet(tmp_path):
    # A sheet with uncommitted user edits must not be swept into the Prepare commit (a later Restore
    # would destroy that work); Prepare refuses until the tree is committed-clean.
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    sch = proj / "proj.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8") + "\n; user edit\n", encoding="utf-8")
    head = prepo.head()
    with pytest.raises(ValueError):
        ops.prepare_apply(rec.id, library_parts=_parts())
    assert prepo.head() == head  # nothing committed


def test_manual_fill_refuses_a_dirty_sheet(tmp_path):
    ops = _ops(tmp_path)
    sheet = _sheet([_symbol(lib_id="Device:R", ref="R1", value="10k", uuid="m")])
    proj, prepo = _git_project(tmp_path / "ext" / "p", sheets={"proj.kicad_sch": sheet})
    rec = ops.register(proj)
    sch = proj / "proj.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8") + "\n; user edit\n", encoding="utf-8")
    head = prepo.head()
    with pytest.raises(ValueError):
        ops.manual_fill(rec.id, "R1", "r10k", library_parts=_parts())
    assert prepo.head() == head


def test_prepare_read_accepts_a_lazy_parts_thunk(tmp_path):
    # The router passes the library as a thunk so it is not loaded until after validation; a thunk
    # must resolve exactly like a list.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    calls = {"n": 0}

    def load():
        calls["n"] += 1
        return _parts()

    r = ops.prepare_read(rec.id, library_parts=load)
    assert calls["n"] == 1 and r["annotate"] == 3
    # an unknown id resolves 404 BEFORE the thunk is ever called
    calls["n"] = 0
    with pytest.raises(FileNotFoundError):
        ops.prepare_read("nope", library_parts=load)
    assert calls["n"] == 0


def test_restore_ignores_a_user_commit_that_merely_starts_with_prepare(tmp_path):
    # A user's own commit "Prepare the board for fab" must NOT be mistaken for a Stockroom
    # Prepare/Fill commit; restore only reverts "Prepare <name>:" / "Fill <name>:".
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    # a user commit touching the sheet whose subject starts with "Prepare " but is not Stockroom's
    sch = proj / "proj.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    prepo.commit("Prepare the board for fab", [sch])
    with pytest.raises(ValueError):
        ops.restore(rec.id)  # no Stockroom Prepare/Fill commit exists yet
