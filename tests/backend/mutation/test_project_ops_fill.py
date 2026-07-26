"""M7f-D project_ops Prepare / Complete-All / manual fill / Restore: the atomic write orchestration
(mirrors the conform_apply / stackup_apply precedents). Prepare annotates references and auto-fills
blank identity fields from the shared library as ONE scoped commit on the project's own git; a manual
fill links one component to a chosen library part; Restore git-reverts the last Prepare/Fill. Every
write is one atomic commit or zero trace, with an honest no-commit no-op when nothing changes."""

from __future__ import annotations

import shutil

import pytest

from stockroom.model.part import AssetRef, Datasheet, EdaAssets, PartRecord
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
            eda={"kicad": EdaAssets(
                symbol=AssetRef(lib="SR-ICs", name="LM358"),
                footprint=AssetRef(lib="SR-ICs", name="SOIC-8"),
            )},
            datasheet=Datasheet(file="lm358.pdf", source_url="https://ti.com/lm358.pdf"),
        ),
        PartRecord(
            id="r10k", display_name="10k 0402", category="Resistors",
            description="10k 1% 0402", mpn="RC0402FR-0710KL", manufacturer="Yageo",
            eda={"kicad": EdaAssets(
                symbol=AssetRef(lib="SR-Resistors", name="R_10k"),
                footprint=AssetRef(lib="SR-Resistors", name="R_0402"),
            )},
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
    assert '(property "Reference" "R1"' in ta
    assert '(property "Reference" "R2"' in tb
    # The claim in this test's NAME, which nothing checked: the designators are unique ACROSS
    # sheets, so neither sheet may carry the other's reference. A dead `refs = {...}` sat here
    # instead, computing the evidence and dropping it.
    assert '"R2"' not in ta
    assert '"R1"' not in tb


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


# --- bulk assign (assign_read / assign_refs) ----------------------------------
#
# The owner's scenario end to end: a project holding a pile of default-library passives. Every one
# carries a generic stock symbol, so none of them can be IDENTIFIED, and the safe path is to group the
# identical ones and assign each group in one decision and one commit.


def _stock_passives():
    """A library of passives as `add_passive_part` really files them: the symbol and footprint are
    KiCad STOCK references, so none of these parts can be reached by the symbol identity tier."""
    def res(pid, mpn, value, package, metric):
        return PartRecord(
            id=pid, display_name=f"{value} {package}", category="Resistors",
            description=f"{value} 1% {package}", mpn=mpn, manufacturer="Yageo", passive=True,
            eda={"kicad": EdaAssets(
                symbol=AssetRef(lib="Device", name="R"),
                footprint=AssetRef(lib="Resistor_SMD", name=f"R_{package}_{metric}"),
            )},
            datasheet=Datasheet(source_url=f"https://yageo.com/{mpn}.pdf"),
            specs={"Resistance": value, "Package": package},
        )
    return [res("r10k", "RC0402FR-0710KL", "10 kOhm", "0402", "1005Metric"),
            res("r47k", "RC0402FR-0747KL", "47 kOhm", "0402", "1005Metric")]


_FP_0402 = "Resistor_SMD:R_0402_1005Metric"


def _passive_sheet():
    # Four placed resistors: three identical 10k and one 47k, all on the generic Device:R symbol.
    return _sheet([
        _symbol(lib_id="Device:R", ref="R1", value="10k", footprint=_FP_0402, uuid="p-1"),
        _symbol(lib_id="Device:R", ref="R2", value="10k", footprint=_FP_0402, uuid="p-2"),
        _symbol(lib_id="Device:R", ref="R10", value="10k", footprint=_FP_0402, uuid="p-10"),
        _symbol(lib_id="Device:R", ref="R3", value="47k", footprint=_FP_0402, uuid="p-3"),
    ])


def test_assign_read_groups_identical_passives_with_candidates(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    head = prepo.head()

    r = ops.assign_read(rec.id, library_parts=_stock_passives())
    assert r["components"] == 4 and r["unassigned"] == 4
    assert [g["refs"] for g in r["groups"]] == [["R1", "R2", "R10"], ["R3"]]
    tenk = r["groups"][0]
    assert tenk["count"] == 3 and tenk["value"] == "10k" and tenk["footprint"] == _FP_0402
    assert tenk["sheets"] == ["proj.kicad_sch"]
    # Each group offers the value-matched part, and ONLY that one, at the exact-footprint tier.
    assert [c["part_id"] for c in tenk["candidates"]] == ["r10k"]
    assert tenk["candidates"][0]["confidence"] == "value+footprint"
    assert [c["part_id"] for c in r["groups"][1]["candidates"]] == ["r47k"]
    # A read writes nothing and commits nothing.
    assert prepo.head() == head


def test_assign_refs_fills_a_whole_group_in_one_commit(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    before = prepo.head()

    result = ops.assign_refs(rec.id, ["R1", "R2", "R10"], "r10k",
                             library_parts=_stock_passives())
    after = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    assert result["committed"] == prepo.head()
    assert result["committed"] != before
    # ONE commit for the whole group, not one per component, and its subject says so.
    log = prepo.log_paths([proj / "proj.kicad_sch"], max_count=2)
    assert log[0].subject == f"Fill {rec.name}: 3 components from library"
    assert log[0].sha == result["committed"] and log[1].sha == before
    assert after.count('(property "MPN" "RC0402FR-0710KL"') == 3
    # ...and the untouched 47k component keeps no MPN at all.
    assert '"RC0402FR-0747KL"' not in after


def test_assign_refs_writes_the_stock_reference_kicad_can_resolve(tmp_path):
    # The regression that made this whole slice necessary: the fill used to requalify a passive's
    # stock reference to the Stockroom category library, which holds no such symbol or footprint, so
    # KiCad could resolve neither afterwards.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p",
                           sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R1"], "r10k", library_parts=_stock_passives())
    after = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    assert '(lib_id "Device:R")' in after
    assert f'(property "Footprint" "{_FP_0402}"' in after
    assert "SR-Resistors" not in after


def test_assign_refs_rejects_a_stale_selection_without_writing_anything(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    head = prepo.head()
    before = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    with pytest.raises(ValueError) as err:
        ops.assign_refs(rec.id, ["R1", "Z98", "Z99"], "r10k", library_parts=_stock_passives())
    # Every missing ref is named at once, so a stale UI selection is fixed in one round trip.
    assert "Z98" in str(err.value) and "Z99" in str(err.value)
    # Nothing written, nothing committed: the group is all or nothing.
    assert prepo.head() == head
    assert (proj / "proj.kicad_sch").read_text(encoding="utf-8") == before


def test_assign_refs_rejects_an_empty_selection(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.assign_refs(rec.id, [], "r10k", library_parts=_stock_passives())


def test_assign_refs_is_idempotent(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R1", "R2", "R10"], "r10k", library_parts=_stock_passives())
    head = prepo.head()
    again = ops.assign_refs(rec.id, ["R1", "R2", "R10"], "r10k", library_parts=_stock_passives())
    assert again["committed"] is None and prepo.head() == head


def test_assign_read_drops_a_group_once_it_is_assigned(tmp_path):
    # After assigning, those components carry a real MPN, so the strict-MPN identity tier matches them
    # and they leave the unassigned surface. That is what makes the surface a shrinking work list.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p",
                           sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R1", "R2", "R10"], "r10k", library_parts=_stock_passives())
    r = ops.assign_read(rec.id, library_parts=_stock_passives())
    assert r["unassigned"] == 1
    assert [g["refs"] for g in r["groups"]] == [["R3"]]


def test_assign_refs_refuses_a_dirty_sheet(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p",
                           sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    sch = proj / "proj.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted"):
        ops.assign_refs(rec.id, ["R1"], "r10k", library_parts=_stock_passives())


# --- durable bindings: an assignment that survives a re-annotate ---------------
#
# Punch 17's last gap. Before this, an assignment only wrote identity FIELDS, so the link between a
# placement and its library part existed nowhere: renumbering the reference or editing the Value
# left nothing to re-verify. The binding is that link, and where it is STORED is registry data.


def _binding_field(tool="kicad"):
    from stockroom.projects import binding

    return binding.field_for(tool)


def test_assign_refs_stamps_a_durable_binding_into_the_kicad_schematic(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    result = ops.assign_refs(rec.id, ["R1", "R2", "R10"], "r10k", library_parts=_stock_passives())
    after = (proj / "proj.kicad_sch").read_text(encoding="utf-8")
    # One binding per assigned placement, written in the SAME commit as the identity fields.
    assert after.count(f'(property "{_binding_field()}" "r10k"') == 3
    assert result["bound"] == 3
    assert prepo.is_clean([proj / "proj.kicad_sch"])
    # Hidden: a Stockroom bookkeeping field must not print on the user's schematic sheet.
    field_at = after.index(f'(property "{_binding_field()}" "r10k"')
    assert "(hide yes)" in after[field_at:field_at + 200]


def test_a_binding_survives_a_reannotate_where_every_other_tier_fails(tmp_path):
    """The property this whole slice exists for. KiCad renumbers R1 to R77; nothing about the
    placement's symbol, value or designator can identify the part afterwards, and the binding
    still does."""
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R1"], "r10k", library_parts=_stock_passives())

    sch = proj / "proj.kicad_sch"
    renumbered = sch.read_text(encoding="utf-8").replace('"R1"', '"R77"')
    sch.write_text(renumbered, encoding="utf-8")
    prepo.commit("Renumber in KiCad", [sch])

    r = ops.assign_read(rec.id, library_parts=_stock_passives())
    bound = {b["ref"]: b for b in r["bound"]}
    assert bound["R77"]["part_id"] == "r10k"
    assert bound["R77"]["display_name"] == "10 kOhm 0402"
    assert "R77" not in {ref for g in r["groups"] for ref in g["refs"]}
    # ...and the fill plan agrees, at the binding tier rather than a guess.
    plan = ops.prepare_read(rec.id, library_parts=_stock_passives())["plan"]
    assert {i["ref"]: i["confidence"] for i in plan["items"]}.get("R77") in (None, "binding")


def test_a_binding_survives_a_value_edit(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R3"], "r47k", library_parts=_stock_passives())
    sch = proj / "proj.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8").replace('"47k"', '"470k"'), encoding="utf-8")
    prepo.commit("Retune", [sch])
    r = ops.assign_read(rec.id, library_parts=_stock_passives())
    assert [b["part_id"] for b in r["bound"] if b["ref"] == "R3"] == ["r47k"]


def test_assign_read_reports_drift_between_a_bound_part_and_the_placement(tmp_path):
    """"Re-verified later" made real: a bound placement whose schematic fields no longer agree with
    its library part is reported as drift rather than quietly ignored."""
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                               sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R1"], "r10k", library_parts=_stock_passives())
    assert [b["drift"] for b in ops.assign_read(rec.id, library_parts=_stock_passives())["bound"]
            if b["ref"] == "R1"] == [[]]
    sch = proj / "proj.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8").replace('"RC0402FR-0710KL"', '"WRONG-MPN"'),
                   encoding="utf-8")
    prepo.commit("Hand edit", [sch])
    drift = [b["drift"] for b in ops.assign_read(rec.id, library_parts=_stock_passives())["bound"]
             if b["ref"] == "R1"][0]
    assert [(d["prop"], d["new"]) for d in drift] == [("MPN", "RC0402FR-0710KL")]


def test_a_binding_to_a_part_that_left_the_library_is_reported_not_silently_reguessed(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p",
                           sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R1"], "r10k", library_parts=_stock_passives())
    shrunk = [p for p in _stock_passives() if p.id != "r10k"]
    r = ops.assign_read(rec.id, library_parts=shrunk)
    broken = [b for b in r["bound"] if b["ref"] == "R1"]
    assert len(broken) == 1 and broken[0]["missing"] is True
    assert broken[0]["part_id"] == "r10k" and broken[0]["display_name"] == ""


# --- the same surface for a tool whose design Stockroom cannot write ----------


def _altium_schdoc(path, *component_blocks):
    """A synthetic .SchDoc, the same shape tests/backend/projects/test_bom.py builds, plus the
    per-component UNIQUEID that an Altium binding is keyed by."""
    import struct

    from tests.backend.altium.cfb_writer import write_cfb

    def rec(*pairs):
        payload = ("|" + "|".join(pairs)).encode("latin-1") + b"\x00"
        return struct.pack("<I", len(payload)) + payload

    stream = rec("HEADER=Protel for Windows - Schematic Capture Binary File Version 5.0")
    idx = 0
    for block in component_blocks:
        comp_idx = idx
        stream += rec("RECORD=1", f"LIBREFERENCE={block['lib_ref']}",
                      f"DESIGNITEMID={block.get('design_item_id', '')}",
                      f"UNIQUEID={block.get('unique_id', '')}", "OWNERPARTID=-1")
        idx += 1
        stream += rec("RECORD=34", f"OWNERINDEX={comp_idx}", "NAME=Designator",
                      f"TEXT={block['designator']}")
        idx += 1
        for name, text in block.get("params", {}).items():
            stream += rec("RECORD=41", f"OWNERINDEX={comp_idx}", f"NAME={name}", f"TEXT={text}")
            idx += 1
        if block.get("footprint"):
            stream += rec("RECORD=44", f"OWNERINDEX={comp_idx}")
            stream += rec("RECORD=45", f"OWNERINDEX={idx}", f"MODELNAME={block['footprint']}",
                          "MODELTYPE=PCBLIB", "ISCURRENT=T")
            idx += 2
    write_cfb(path, "FileHeader", stream)
    return path


def _altium_project(dir_path):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "proj.PrjPcb").write_text(
        "[Design]\nVersion=1.0\n[Document1]\nDocumentPath=Amp.SchDoc\n", encoding="utf-8")
    _altium_schdoc(
        dir_path / "Amp.SchDoc",
        {"designator": "R1", "lib_ref": "RES", "unique_id": "AAAAAAAA",
         "params": {"Value": "10k"}, "footprint": "RESC1005X40"},
        {"designator": "R2", "lib_ref": "RES", "unique_id": "BBBBBBBB",
         "params": {"Value": "10k"}, "footprint": "RESC1005X40"},
    )
    return dir_path


def _altium_passives():
    return [PartRecord(
        id="r10k", display_name="10 kOhm 0402", category="Resistors",
        description="10k 1% 0402", mpn="RC0402FR-0710KL", manufacturer="Yageo", passive=True,
        eda={"altium": EdaAssets(symbol=AssetRef(lib="SR.SchLib", name="RES"),
                                 footprint=AssetRef(lib="SR.PcbLib", name="RESC1005X40"))},
        specs={"Resistance": "10 kOhm", "Package": "0402"},
    )]


def test_assign_read_serves_an_altium_project_instead_of_refusing_it(tmp_path):
    """Registry-generic: the bulk-assign surface reads placements through whichever reader the
    project's tool declares, so an Altium registration is a first-class citizen here."""
    ops = _ops(tmp_path)
    rec = ops.register(_altium_project(tmp_path / "ext" / "a"))
    assert rec.eda == "altium"
    r = ops.assign_read(rec.id, library_parts=_altium_passives())
    assert r["components"] == 2
    assert [g["refs"] for g in r["groups"]] == [["R1", "R2"]]
    assert r["binding"]["writable"] is False and r["binding"]["reason"]


def test_an_altium_assignment_is_recorded_because_the_design_cannot_be_written(tmp_path):
    """Stockroom never writes Altium binary, so the binding lives on the project record. The
    .SchDoc must come out byte-identical: a write there would be the bug, not the feature."""
    ops = _ops(tmp_path)
    proj = _altium_project(tmp_path / "ext" / "a")
    rec = ops.register(proj)
    before = (proj / "Amp.SchDoc").read_bytes()

    result = ops.assign_refs(rec.id, ["R1", "R2"], "r10k", library_parts=_altium_passives())
    assert result["bound"] == 2
    assert (proj / "Amp.SchDoc").read_bytes() == before

    stored = ops.store.get(rec.id).bindings["altium"]
    assert stored == {"AAAAAAAA": "r10k", "BBBBBBBB": "r10k"}
    # ...and reading back resolves it, so the group leaves the unassigned work list.
    r = ops.assign_read(rec.id, library_parts=_altium_passives())
    assert r["groups"] == [] and r["unassigned"] == 0
    assert sorted(b["ref"] for b in r["bound"]) == ["R1", "R2"]


def test_an_altium_binding_is_keyed_by_the_components_unique_id_not_its_designator(tmp_path):
    ops = _ops(tmp_path)
    rec = ops.register(_altium_project(tmp_path / "ext" / "a"))
    ops.assign_refs(rec.id, ["R1"], "r10k", library_parts=_altium_passives())
    assert list(ops.store.get(rec.id).bindings["altium"]) == ["AAAAAAAA"]


def test_a_natively_dblib_placed_altium_component_is_already_bound(tmp_path):
    """Altium copies a DbLib column onto the placement, so a component placed from Stockroom's own
    library arrives carrying its binding with nothing recorded anywhere."""
    from stockroom.projects import binding

    ops = _ops(tmp_path)
    proj = (tmp_path / "ext" / "a")
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "proj.PrjPcb").write_text("[Design]\n[Document1]\nDocumentPath=Amp.SchDoc\n",
                                      encoding="utf-8")
    _altium_schdoc(proj / "Amp.SchDoc",
                   {"designator": "R1", "lib_ref": "RES", "unique_id": "AAAAAAAA",
                    "params": {"Value": "10k", binding.field_for("altium"): "r10k"},
                    "footprint": "RESC1005X40"})
    rec = ops.register(proj)
    r = ops.assign_read(rec.id, library_parts=_altium_passives())
    assert r["groups"] == []
    assert [b["part_id"] for b in r["bound"]] == ["r10k"]


def test_drift_is_a_DISAGREEMENT_not_a_blank_field(tmp_path):
    """The distinction that decides whether the record is usable at all. A placement that simply has
    not been filled in yet is Prepare's job and is not a problem with the binding; only a field whose
    schematic value CONTRADICTS the library part needs a human. Counting blanks as drift flagged
    every healthy assignment, which is the same as flagging none."""
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "p",
                              sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    sch = proj / "proj.kicad_sch"
    # R1 is bound and left with NO Manufacturer/Description at all; R2 is bound and contradicts the
    # library on MPN. Only R2 is drift.
    field = _binding_field()
    text = sch.read_text(encoding="utf-8")
    text = text.replace(
        '(property "Reference" "R1"',
        f'(property "{field}" "r10k" (at 0 0 0) (hide yes))\n\t\t(property "Reference" "R1"', 1)
    text = text.replace(
        '(property "Reference" "R2"',
        f'(property "{field}" "r10k" (at 0 0 0) (hide yes))\n'
        '\t\t(property "MPN" "SOMETHING-ELSE" (at 0 0 0))\n\t\t(property "Reference" "R2"', 1)
    sch.write_text(text, encoding="utf-8")
    prepo.commit("hand edits", [sch])

    bound = {b["ref"]: b for b in ops.assign_read(rec.id, library_parts=_stock_passives())["bound"]}
    assert bound["R1"]["drift"] == []
    assert [(d["prop"], d["old"], d["new"]) for d in bound["R2"]["drift"]] == [
        ("MPN", "SOMETHING-ELSE", "RC0402FR-0710KL")]


def test_a_dangling_binding_is_offered_for_reassignment_not_only_reported(tmp_path):
    """A diagnosis with no repair is a dead end. The placement genuinely carries no library part, so
    it belongs in the assignable work list as well as in the broken-links report."""
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "p",
                           sheets={"proj.kicad_sch": _passive_sheet()})
    rec = ops.register(proj)
    ops.assign_refs(rec.id, ["R1"], "r10k", library_parts=_stock_passives())
    shrunk = [p for p in _stock_passives() if p.id != "r10k"]
    r = ops.assign_read(rec.id, library_parts=shrunk)
    assert [b["ref"] for b in r["bound"] if b["missing"]] == ["R1"]
    assert "R1" in {ref for g in r["groups"] for ref in g["refs"]}
