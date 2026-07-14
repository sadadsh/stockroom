"""M7f-C project_ops stackup read / preview / apply: the atomic write orchestration (mirrors the
set_settings / conform_apply precedents). A stackup apply is ONE scoped commit on the project's own
git (preset apply = whole-block generate + board thickness; field edits = per-field in place), or
zero trace on failure, or an honest no-commit no-op when nothing changes."""

import shutil

import pytest

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


# A real KiCad-10 4-layer FR4 board: (layers) with 4 copper (listed in INDEX order, not physical),
# (general thickness), and a (setup (stackup ...)) with a pad_to_mask_clearance sibling.
_STACKUP = (
    "(stackup\n"
    '\t\t\t(layer "F.SilkS"\n\t\t\t\t(type "Top Silk Screen")\n\t\t\t)\n'
    '\t\t\t(layer "F.Paste"\n\t\t\t\t(type "Top Solder Paste")\n\t\t\t)\n'
    '\t\t\t(layer "F.Mask"\n\t\t\t\t(type "Top Solder Mask")\n\t\t\t\t(thickness 0.01)\n\t\t\t)\n'
    '\t\t\t(layer "F.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 1"\n\t\t\t\t(type "prepreg")\n\t\t\t\t(thickness 0.1)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "In1.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 2"\n\t\t\t\t(type "core")\n\t\t\t\t(thickness 1.24)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "In2.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 3"\n\t\t\t\t(type "prepreg")\n\t\t\t\t(thickness 0.1)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "B.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "B.Mask"\n\t\t\t\t(type "Bottom Solder Mask")\n\t\t\t\t(thickness 0.01)\n\t\t\t)\n'
    '\t\t\t(layer "B.Paste"\n\t\t\t\t(type "Bottom Solder Paste")\n\t\t\t)\n'
    '\t\t\t(layer "B.SilkS"\n\t\t\t\t(type "Bottom Silk Screen")\n\t\t\t)\n'
    '\t\t\t(copper_finish "None")\n'
    "\t\t\t(dielectric_constraints no)\n"
    "\t\t)"
)
_PCB = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    '\t(generator "pcbnew")\n'
    '\t(generator_version "10.0")\n'
    "\t(general\n\t\t(thickness 1.51)\n\t)\n"
    "\t(layers\n"
    '\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n'
    '\t\t(1 "F.Mask" user)\n\t\t(3 "B.Mask" user)\n'
    "\t)\n"
    "\t(setup\n\t\t" + _STACKUP + "\n\t\t(pad_to_mask_clearance 0.05)\n\t)\n"
    ")\n"
)

# A 2-layer board (only F.Cu/B.Cu), used to prove the layer-count guard.
_PCB_2 = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    "\t(general\n\t\t(thickness 1.6)\n\t)\n"
    "\t(layers\n"
    '\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n'
    "\t)\n"
    "\t(setup\n"
    "\t\t(stackup\n"
    '\t\t\t(layer "F.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 1"\n\t\t\t\t(type "core")\n\t\t\t\t(thickness 1.51)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "B.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(copper_finish "None")\n\t\t\t(dielectric_constraints no)\n'
    "\t\t)\n"
    "\t)\n"
    ")\n"
)


def _git_project(dir_path, pcb_text=_PCB):
    dir_path.mkdir(parents=True, exist_ok=True)
    prepo = GitRepo(dir_path)
    prepo.init()
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_pcb").write_text(pcb_text, encoding="utf-8")
    prepo.commit("init", [dir_path / "board.kicad_pro", dir_path / "board.kicad_pcb"])
    return dir_path, prepo


def _no_git_project(dir_path, pcb_text=_PCB):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_pcb").write_text(pcb_text, encoding="utf-8")
    return dir_path


# --- stackup_read -------------------------------------------------------------

def test_stackup_read_reports_current_stack_and_catalog(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    r = ops.stackup_read(rec.id)
    assert r["under_git"] is True and r["has_board"] is True
    assert r["copper_layers"] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert r["thickness"] == 1.51
    assert r["stackup"]["copper_finish"] == "None"
    assert {p["key"] for p in r["presets"]} == {"oshpark_2", "oshpark_4"}


def test_stackup_read_is_honest_without_a_board(tmp_path):
    ops = _ops(tmp_path)
    dir_path = tmp_path / "ext" / "board"
    dir_path.mkdir(parents=True)
    prepo = GitRepo(dir_path)
    prepo.init()
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    prepo.commit("init", [dir_path / "board.kicad_pro"])
    rec = ops.register(dir_path)
    r = ops.stackup_read(rec.id)
    assert r["has_board"] is False
    assert r["stackup"] is None
    assert r["copper_layers"] == []


def test_stackup_read_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.stackup_read("nope")


# --- stackup_preview ----------------------------------------------------------

def test_stackup_preview_preset_shows_target_without_writing(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    before = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    head_before = prepo.head()

    prev = ops.stackup_preview(rec.id, preset_key="oshpark_4")
    assert prev["changed"] is True
    # the board thickness becomes the generated stack's own sum (KiCad's invariant), not the
    # preset's nominal 1.6 mm label: 4x0.035 copper is replaced by the preset's copper/dielectric.
    assert prev["thickness"] == 1.5318
    assert prev["stackup"]["copper_finish"] == "ENIG"
    assert prev["verify_note"]  # the honesty caveat is surfaced
    # a preview writes nothing and commits nothing
    assert (proj / "board.kicad_pcb").read_text(encoding="utf-8") == before
    assert prepo.head() == head_before


def test_stackup_preview_field_edit_shows_edited_stack(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    prev = ops.stackup_preview(rec.id, copper_finish="ENIG")
    assert prev["changed"] is True
    assert prev["stackup"]["copper_finish"] == "ENIG"


def test_stackup_preview_preset_layer_mismatch_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board", pcb_text=_PCB_2)  # a 2-layer board
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.stackup_preview(rec.id, preset_key="oshpark_4")  # 4-layer preset onto a 2-layer board


def test_stackup_preview_rejects_both_modes_or_neither(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.stackup_preview(rec.id, preset_key="oshpark_4", copper_finish="ENIG")
    with pytest.raises(ValueError):
        ops.stackup_preview(rec.id)


# --- stackup_apply ------------------------------------------------------------

def test_stackup_apply_refuses_a_dirty_board(tmp_path):
    # roadmap #7: a dirty board's uncommitted edits must not be swept into the stackup commit
    # (a Restore would then destroy them). Guard before any read; nothing is committed.
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    (proj / "board.kicad_pcb").write_text(_PCB + "\n(comment)\n", encoding="utf-8")  # uncommitted
    head_before = prepo.head()
    with pytest.raises(ValueError, match="uncommitted"):
        ops.stackup_apply(rec.id, preset_key="oshpark_4")
    assert prepo.head() == head_before  # nothing committed


def test_stackup_apply_preset_writes_minimal_diff_and_commits_once(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    pcb = proj / "board.kicad_pcb"

    result = ops.stackup_apply(rec.id, preset_key="oshpark_4")

    after = pcb.read_text(encoding="utf-8")
    assert '(copper_finish "ENIG")' in after
    assert '(color "Purple")' in after  # the coloured OSH Park mask
    # board thickness set to the generated stack's own sum (KiCad's invariant), not the nominal 1.6
    assert "(thickness 1.5318)" in after
    assert "(pad_to_mask_clearance 0.05)" in after  # the setup sibling survives untouched
    assert result["committed"] == prepo.head()
    assert prepo.head() != head_before
    assert prepo.is_clean()
    # exactly one commit added
    assert prepo._run("rev-list", "--count", f"{head_before}..HEAD").stdout.strip() == "1"


def test_stackup_apply_field_edit_commits(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    result = ops.stackup_apply(rec.id, copper_finish="ENIG", dielectric_constraints=True)
    after = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    assert '(copper_finish "ENIG")' in after
    assert "(dielectric_constraints yes)" in after
    assert result["committed"] == prepo.head()


def test_stackup_apply_per_dielectric_field_edit(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    ops.stackup_apply(rec.id, layer_edits={"dielectric 2": {"thickness": 1.2, "material": "Rogers"}})
    after = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    d2 = after.index('(layer "dielectric 2"')
    assert "(thickness 1.2)" in after[d2:d2 + 200]
    assert '(material "Rogers")' in after[d2:d2 + 200]


def test_stackup_apply_noop_is_no_commit(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    # set copper_finish to the value already on disk -> no byte change -> no commit
    result = ops.stackup_apply(rec.id, copper_finish="None")
    assert result["committed"] is None
    assert result["changed"] is False
    assert prepo.head() == head_before


def test_stackup_apply_refuses_a_project_not_under_git(tmp_path):
    ops = _ops(tmp_path)
    proj = _no_git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.stackup_apply(rec.id, preset_key="oshpark_4")


def test_stackup_apply_preset_mismatch_rejected_before_git(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board", pcb_text=_PCB_2)
    rec = ops.register(proj)
    head_before = prepo.head()
    with pytest.raises(ValueError):
        ops.stackup_apply(rec.id, preset_key="oshpark_4")
    assert prepo.head() == head_before  # nothing committed


def test_stackup_apply_field_edit_without_a_stackup_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    # a board with a setup but no stackup block
    no_stack = (
        "(kicad_pcb\n\t(layers\n\t\t(0 \"F.Cu\" signal)\n\t\t(2 \"B.Cu\" signal)\n\t)\n"
        "\t(setup\n\t\t(pad_to_mask_clearance 0.05)\n\t)\n)\n"
    )
    proj, _ = _git_project(tmp_path / "ext" / "board", pcb_text=no_stack)
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.stackup_apply(rec.id, copper_finish="ENIG")


def test_stackup_apply_preset_no_setup_block_is_clean_valueerror(tmp_path):
    # a board with copper layers but no (setup ...) block: a preset apply is an honest 400 (a clean
    # ValueError), never a raw KiCadFileError that would 500, and never a commit.
    ops = _ops(tmp_path)
    no_setup = (
        '(kicad_pcb\n\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)\n)\n'
    )
    proj, prepo = _git_project(tmp_path / "ext" / "board", pcb_text=no_setup)
    rec = ops.register(proj)
    head_before = prepo.head()
    with pytest.raises(ValueError):
        ops.stackup_apply(rec.id, preset_key="oshpark_2")
    with pytest.raises(ValueError):
        ops.stackup_preview(rec.id, preset_key="oshpark_2")
    assert prepo.head() == head_before


def test_stackup_apply_unknown_layer_edit_is_rejected(tmp_path):
    # a field edit naming a layer that does not exist is a clean 400 (never a silent no-op commit)
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    with pytest.raises(ValueError):
        ops.stackup_apply(rec.id, layer_edits={"NoSuchLayer": {"thickness": 0.5}})
    assert prepo.head() == head_before


def test_stackup_apply_field_absent_on_layer_is_rejected(tmp_path):
    # epsilon_r targets a copper layer (which carries no dielectric constant): update-if-present
    # would silently skip it, so it is refused as a clean 400 instead of a misleading no-op.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.stackup_apply(rec.id, layer_edits={"F.Cu": {"epsilon_r": 4.2}})


def test_stackup_apply_raising_write_leaves_zero_trace(tmp_path, monkeypatch):
    from stockroom.sexp.document import SexpDocument

    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    pcb = proj / "board.kicad_pcb"
    before = pcb.read_text(encoding="utf-8")
    head_before = prepo.head()

    def _boom(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(SexpDocument, "save", _boom)
    with pytest.raises(Exception):
        ops.stackup_apply(rec.id, preset_key="oshpark_4")

    assert pcb.read_text(encoding="utf-8") == before  # restored byte-for-byte
    assert prepo.head() == head_before and prepo.is_clean()
