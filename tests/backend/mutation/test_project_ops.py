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


def _make_project(dir_path, sheet_body):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch\n" + sheet_body + ")\n", encoding="utf-8")
    return dir_path


_UNANNOTATED = (
    '  (symbol\n'
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R?" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "" (at 0 0 0))\n'
    '  )\n'
)


def test_register_list_get_delete_delegate_to_the_store(tmp_path):
    ops = _ops(tmp_path)
    proj = _make_project(tmp_path / "ext" / "board", _UNANNOTATED)
    rec = ops.register(proj)
    assert rec.name == "board"
    assert [r.id for r in ops.list()] == [rec.id]
    assert ops.get(rec.id) == rec
    ops.delete(rec.id)
    assert ops.get(rec.id) is None


def test_audit_reads_the_registered_sheets(tmp_path):
    ops = _ops(tmp_path)
    rec = ops.register(_make_project(tmp_path / "ext" / "board", _UNANNOTATED))
    au = ops.audit(rec.id)
    assert au["project"] == "board"  # named for the record, not the sheet stem
    assert au["components"] == 1
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R?", "unannotated") in kinds
    assert ("R?", "no_footprint") in kinds


def test_audit_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.audit("nope")


# --- M7e Editor writes (design rules + net classes) --------------------------

# A canonical KiCad-10 .kicad_pro (2-space indent, sorted keys, trailing newline)
# so a minimal-diff edit is verifiable.
_PRO = (
    "{\n"
    '  "board": {\n'
    '    "design_settings": {\n'
    '      "defaults": {\n'
    '        "copper_line_width": 0.2\n'
    "      },\n"
    '      "diff_pair_dimensions": [],\n'
    '      "rules": {\n'
    '        "min_clearance": 0.2,\n'
    '        "min_track_width": 0.2,\n'
    '        "use_height_for_length_calcs": true\n'
    "      },\n"
    '      "track_widths": [],\n'
    '      "via_dimensions": []\n'
    "    }\n"
    "  },\n"
    '  "meta": {\n'
    '    "filename": "board.kicad_pro",\n'
    '    "version": 3\n'
    "  },\n"
    '  "net_settings": {\n'
    '    "classes": [\n'
    "      {\n"
    '        "clearance": 0.2,\n'
    '        "name": "Default",\n'
    '        "track_width": 0.2,\n'
    '        "tuning_profile": "",\n'
    '        "via_diameter": 0.6,\n'
    '        "via_drill": 0.3,\n'
    '        "wire_width": 6\n'
    "      }\n"
    "    ],\n"
    '    "meta": {\n'
    '      "version": 5\n'
    "    },\n"
    '    "netclass_patterns": []\n'
    "  }\n"
    "}\n"
)


def _git_project(dir_path, pro_text=_PRO):
    """A project dir that is its OWN git repo with a committed .kicad_pro, so a
    project write commits into the project's own history (M7e Decision 1)."""
    dir_path.mkdir(parents=True, exist_ok=True)
    prepo = GitRepo(dir_path)
    prepo.init()
    (dir_path / "board.kicad_pro").write_text(pro_text, encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    prepo.commit("init project", [dir_path / "board.kicad_pro", dir_path / "board.kicad_sch"])
    return dir_path, prepo


def test_design_settings_reads_current_classes_and_rules(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    ds = ops.design_settings(rec.id)
    assert ds["under_git"] is True
    assert [c["name"] for c in ds["net_classes"]] == ["Default"]
    assert ds["design_rules"]["min_track_width"] == 0.2
    assert ds["track_widths"] == []


def test_set_net_classes_writes_minimal_diff_and_commits(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    pro = proj / "board.kicad_pro"
    before = pro.read_text(encoding="utf-8")
    design_before = before[before.index('"board"'):before.index('"meta"')]

    result = ops.set_net_classes(rec.id, [{"name": "Default", "track_width": 0.15}])

    after = pro.read_text(encoding="utf-8")
    # the edit landed
    assert '"track_width": 0.15' in after
    # the design-settings block is byte-identical (the net-class edit did not touch it)
    assert after[after.index('"board"'):after.index('"meta"')] == design_before
    # a KiCad-internal field the UI never sent survived (safe-merge)
    assert '"tuning_profile": ""' in after
    # exactly one new commit on the project's OWN repo, scoped to the .kicad_pro
    assert prepo.head() != head_before
    assert result["committed"] == prepo.head()
    assert prepo.is_clean()


def test_set_net_classes_returns_fab_validation(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    result = ops.set_net_classes(
        rec.id, [{"name": "Default", "track_width": 0.05}], floor="oshpark_2"
    )
    assert any("track" in f["issue"] for f in result["validation"])


def test_set_design_rules_writes_rules_leaving_net_settings_identical(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    pro = proj / "board.kicad_pro"
    before = pro.read_text(encoding="utf-8")
    net_before = before[before.index('"net_settings"'):]

    ops.set_design_rules(rec.id, {"min_track_width": 0.13})

    after = pro.read_text(encoding="utf-8")
    assert '"min_track_width": 0.13' in after
    assert '"min_clearance": 0.2' in after  # sibling rule preserved
    assert after[after.index('"net_settings"'):] == net_before  # net_settings untouched
    assert prepo.is_clean()


def test_set_design_rules_replaces_the_size_lists(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    ops.set_design_rules(rec.id, {"min_track_width": 0.2},
                         track_widths=[0.2, 0.4], via_dimensions=[{"diameter": 0.6, "drill": 0.3}])
    ds = ops.design_settings(rec.id)
    assert ds["track_widths"] == [0.2, 0.4]
    assert ds["via_dimensions"] == [{"diameter": 0.6, "drill": 0.3}]


def test_write_refuses_a_project_not_under_git(tmp_path):
    # a project with no .git ancestor cannot be written (Decision 1: writes need the
    # project's own git for the atomic commit + the asset gate to be meaningful).
    ops = _ops(tmp_path)
    proj = _make_project(tmp_path / "nogit" / "board", _UNANNOTATED)
    rec = ops.register(proj)
    assert rec.git_root is None
    with pytest.raises(ValueError):
        ops.set_net_classes(rec.id, [{"name": "Default", "track_width": 0.15}])


def test_write_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.set_net_classes("nope", [{"name": "Default"}])


def test_write_refuses_when_the_kicad_pro_is_gone_from_disk(tmp_path):
    # pro_path is set but the file was moved/deleted after registration: the write must be
    # an honest ValueError (-> 400 "re-register"), never a raw FileNotFoundError that 404s
    # and leaks the absolute path (GET /design already tolerates a missing .kicad_pro).
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    (proj / "board.kicad_pro").unlink()
    with pytest.raises(ValueError):
        ops.set_net_classes(rec.id, [{"name": "Default", "track_width": 0.15}])


def test_failed_write_leaves_zero_trace(tmp_path, monkeypatch):
    # if the write produces an invalid .kicad_pro, the Transaction validate aborts and
    # rolls the file back to its committed bytes with the project's git left clean.
    from stockroom.kicad import project_settings

    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    pro = proj / "board.kicad_pro"
    original = pro.read_text(encoding="utf-8")
    head_before = prepo.head()

    def _corrupt(path, patch):
        from pathlib import Path as _P
        _P(path).write_text("{ this is not valid json", encoding="utf-8")

    monkeypatch.setattr(project_settings, "apply_patch", _corrupt)
    with pytest.raises(Exception):
        ops.set_net_classes(rec.id, [{"name": "Default", "track_width": 0.15}])

    assert pro.read_text(encoding="utf-8") == original  # restored byte-for-byte
    assert prepo.head() == head_before  # no commit landed


# --- roadmap #4 Editor: netclass patterns ------------------------------------


def test_set_netclass_patterns_writes_and_commits(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()

    result = ops.set_netclass_patterns(rec.id, [{"pattern": "*GND", "netclass": "Default"}])

    pro = proj / "board.kicad_pro"
    after = pro.read_text(encoding="utf-8")
    assert '"pattern": "*GND"' in after
    assert '"netclass": "Default"' in after
    # exactly one new commit on the project's OWN repo, tree clean
    assert prepo.head() != head_before
    assert result["committed"] == prepo.head()
    assert prepo.is_clean()
    # the design read now surfaces the written row
    ds = ops.design_settings(rec.id)
    assert ds["netclass_patterns"] == [{"netclass": "Default", "pattern": "*GND"}]


def test_set_netclass_patterns_empty_list_clears_all(tmp_path):
    # the editor sends the FULL list, so an empty list must clear every pattern (a plain
    # merge replaces a list value wholesale, so no replace_keys is needed here).
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    ops.set_netclass_patterns(rec.id, [{"pattern": "*3V3", "netclass": "Default"}])
    assert ops.design_settings(rec.id)["netclass_patterns"] != []

    ops.set_netclass_patterns(rec.id, [])
    assert ops.design_settings(rec.id)["netclass_patterns"] == []


def test_set_netclass_patterns_rejects_an_unknown_netclass(tmp_path):
    # a row referencing a net class the project does not define is a ValueError (-> 400),
    # validated BEFORE any git touch so no commit lands.
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    with pytest.raises(ValueError):
        ops.set_netclass_patterns(rec.id, [{"pattern": "*X", "netclass": "Nonexistent"}])
    assert prepo.head() == head_before  # validate-before-git: nothing committed


def test_set_netclass_patterns_rejects_a_blank_pattern(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_netclass_patterns(rec.id, [{"pattern": "   ", "netclass": "Default"}])


def test_set_netclass_patterns_leaves_classes_and_board_byte_identical(tmp_path):
    # a patterns-only edit must not touch the design-settings block, the net classes, or the
    # net_settings.meta: everything BEFORE netclass_patterns is byte-identical (minimal diff).
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    pro = proj / "board.kicad_pro"
    before = pro.read_text(encoding="utf-8")

    ops.set_netclass_patterns(rec.id, [{"pattern": "*GND", "netclass": "Default"}])

    after = pro.read_text(encoding="utf-8")
    key = '"netclass_patterns"'
    assert after[: after.index(key)] == before[: before.index(key)]
    assert prepo.is_clean()


def test_set_netclass_patterns_preserves_net_settings_siblings(tmp_path):
    # A real KiCad-10 net_settings also carries net_colors + netclass_assignments beside
    # classes/meta/netclass_patterns (verified against the NETDECK Master.kicad_pro). A
    # patterns-only edit must leave every sibling intact (the partial-merge deep-copies
    # untouched keys), never drop one. Also exercises a non-Default netclass reference.
    import json

    pro_dict = {
        "board": {"design_settings": {"rules": {"min_clearance": 0.2}}},
        "meta": {"filename": "board.kicad_pro", "version": 3},
        "net_settings": {
            "classes": [
                {"clearance": 0.2, "name": "Default", "track_width": 0.2},
                {"clearance": 0.15, "name": "GND", "track_width": 0.25},
            ],
            "meta": {"version": 5},
            "net_colors": {"GND": "rgb(0, 0, 0)"},
            "netclass_assignments": {"/CHASSIS": "GND"},
            "netclass_patterns": [],
        },
    }
    pro_text = json.dumps(pro_dict, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ops = _ops(tmp_path)
    proj, prepo = _git_project(tmp_path / "ext" / "board", pro_text=pro_text)
    rec = ops.register(proj)

    ops.set_netclass_patterns(rec.id, [{"pattern": "*GND", "netclass": "GND"}])

    ns = json.loads((proj / "board.kicad_pro").read_text(encoding="utf-8"))["net_settings"]
    assert ns["netclass_patterns"] == [{"netclass": "GND", "pattern": "*GND"}]  # edited
    assert ns["net_colors"] == {"GND": "rgb(0, 0, 0)"}  # sibling preserved
    assert ns["netclass_assignments"] == {"/CHASSIS": "GND"}  # sibling preserved
    assert [c["name"] for c in ns["classes"]] == ["Default", "GND"]  # classes preserved
    assert prepo.is_clean()


def test_set_netclass_patterns_refuses_a_project_not_under_git(tmp_path):
    ops = _ops(tmp_path)
    proj = _make_project(tmp_path / "nogit" / "board", _UNANNOTATED)
    rec = ops.register(proj)
    assert rec.git_root is None
    with pytest.raises(ValueError):
        ops.set_netclass_patterns(rec.id, [{"pattern": "*GND", "netclass": "Default"}])


def test_set_netclass_patterns_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.set_netclass_patterns("nope", [{"pattern": "*GND", "netclass": "Default"}])


# --- M7f-A Editor: board setup + thickness -----------------------------------

# A canonical KiCad-10 .kicad_pcb with a (general (thickness)) and a (setup ...) so a
# board-setup / thickness edit is provably minimal and byte-preserving.
_PCB = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    '\t(generator "pcbnew")\n'
    '\t(generator_version "10.0")\n'
    "\t(general\n\t\t(thickness 1.6)\n\t)\n"
    '\t(paper "A4")\n'
    "\t(setup\n"
    "\t\t(pad_to_mask_clearance 0.0508)\n"
    "\t\t(allow_soldermask_bridges_in_footprints no)\n"
    "\t)\n"
    '\t(net 0 "")\n'
    ")\n"
)


def _git_project_with_board(dir_path, pro_text=_PRO, pcb_text=_PCB):
    """A project dir that is its own git repo with a committed .kicad_pro AND a
    .kicad_pcb, so a board-setup / thickness write commits into the project's own
    history (M7f-A). board_paths[0] is the primary board the settings edit targets."""
    dir_path.mkdir(parents=True, exist_ok=True)
    prepo = GitRepo(dir_path)
    prepo.init()
    (dir_path / "board.kicad_pro").write_text(pro_text, encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    (dir_path / "board.kicad_pcb").write_text(pcb_text, encoding="utf-8")
    prepo.commit("init project", [
        dir_path / "board.kicad_pro",
        dir_path / "board.kicad_sch",
        dir_path / "board.kicad_pcb",
    ])
    return dir_path, prepo


def test_board_settings_reads_setup_and_thickness(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    bs = ops.board_settings(rec.id)
    assert bs["under_git"] is True
    assert bs["has_board"] is True
    assert bs["board_setup"]["pad_to_mask_clearance"] == 0.0508
    assert bs["thickness"] == 1.6
    # the editor schema travels with the read so the frontend can render every field
    assert any(f["key"] == "pad_to_mask_clearance" for f in bs["fields"])
    # an absent via-protection block reads as its KiCad effective default (tenting ON), so
    # the form shows the true state and a save never silently flips it (_PCB has no tenting)
    assert bs["board_setup"]["tenting_front"] is True
    assert bs["board_setup"]["capping"] is False


def test_board_settings_is_honest_when_the_project_has_no_board(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")  # no .kicad_pcb
    rec = ops.register(proj)
    bs = ops.board_settings(rec.id)
    assert bs["has_board"] is False
    assert bs["board_setup"] == {}
    assert bs["thickness"] is None


def test_board_settings_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.board_settings("nope")


def test_set_settings_writes_board_setup_minimal_diff_and_commits(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    pcb = proj / "board.kicad_pcb"

    result = ops.set_settings(rec.id, board_setup={"pad_to_mask_clearance": 0.1})

    after = pcb.read_text(encoding="utf-8")
    assert "(pad_to_mask_clearance 0.1)" in after
    # a sibling setup key the edit did not name survived untouched
    assert "(allow_soldermask_bridges_in_footprints no)" in after
    # exactly one new commit on the project's OWN repo, and it is clean
    assert prepo.head() != head_before
    assert result["committed"] == prepo.head()
    assert prepo.is_clean()
    assert result["board_setup"]["pad_to_mask_clearance"] == 0.1


def test_set_settings_writes_thickness(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    ops.set_settings(rec.id, thickness=0.8)
    assert ops.board_settings(rec.id)["thickness"] == 0.8


def test_set_settings_board_setup_and_thickness_are_one_atomic_commit(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    ops.set_settings(rec.id, board_setup={"tenting_front": False}, thickness=1.2)
    # both edits landed in ONE commit (not two)
    assert len(prepo.log_paths([proj / "board.kicad_pcb"])) >= 1
    assert prepo.head() != head_before
    bs = ops.board_settings(rec.id)
    assert bs["board_setup"]["tenting_front"] is False
    assert bs["thickness"] == 1.2
    # only one commit was added
    log = prepo._run("rev-list", "--count", f"{head_before}..HEAD").stdout.strip()
    assert log == "1"


def test_set_settings_refuses_a_project_not_under_git(tmp_path):
    ops = _ops(tmp_path)
    proj = _make_project(tmp_path / "nogit" / "board", _UNANNOTATED)
    (proj / "board.kicad_pcb").write_text(_PCB, encoding="utf-8")
    rec = ops.register(proj)
    assert rec.git_root is None
    with pytest.raises(ValueError):
        ops.set_settings(rec.id, thickness=0.8)


def test_set_settings_refuses_when_there_is_no_board(tmp_path):
    # a board-setup / thickness edit needs a .kicad_pcb; a schematic-only project is an
    # honest ValueError, never a silent no-op that fabricates success.
    ops = _ops(tmp_path)
    proj, _ = _git_project(tmp_path / "ext" / "board")  # no .kicad_pcb
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_settings(rec.id, board_setup={"pad_to_mask_clearance": 0.1})


def test_set_settings_rejects_an_unsupported_key(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_settings(rec.id, board_setup={"not_a_real_key": 1})


def test_set_settings_rejects_a_bad_thickness(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_settings(rec.id, thickness=0)


def test_set_settings_with_nothing_to_write_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_settings(rec.id)


def test_set_settings_failed_write_leaves_zero_trace(tmp_path, monkeypatch):
    # a corrupt .kicad_pcb write must abort the Transaction and roll the board back to its
    # committed bytes, project git left clean (the atomic write contract).
    from stockroom.kicad import board as board_mod

    ops = _ops(tmp_path)
    proj, prepo = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    pcb = proj / "board.kicad_pcb"
    original = pcb.read_text(encoding="utf-8")
    head_before = prepo.head()

    def _corrupt(self, path):
        from pathlib import Path as _P
        _P(path).write_text("(this is not a valid kicad_pcb", encoding="utf-8")

    monkeypatch.setattr(board_mod.Board, "save", _corrupt)
    with pytest.raises(Exception):
        ops.set_settings(rec.id, thickness=0.8)

    assert pcb.read_text(encoding="utf-8") == original  # restored byte-for-byte
    assert prepo.head() == head_before  # no commit landed
    assert prepo.is_clean()


def test_set_settings_raising_write_leaves_zero_trace(tmp_path, monkeypatch):
    # a save that RAISES mid-write (disk full, lock, permission revoked) must still roll the
    # board back: the path is tracked BEFORE the write, so the Transaction restores it even
    # though the write threw. (The corrupt-and-return case above exercises the validate path;
    # this exercises the raising path, which a track-after-write ordering would leave dirty.)
    from stockroom.kicad import board as board_mod

    ops = _ops(tmp_path)
    proj, prepo = _git_project_with_board(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    pcb = proj / "board.kicad_pcb"
    original = pcb.read_text(encoding="utf-8")
    head_before = prepo.head()

    def _partial_then_raise(self, path):
        from pathlib import Path as _P
        _P(path).write_text("(kicad_pcb\n\t(version 2026", encoding="utf-8")  # truncated
        raise OSError("disk full mid-write")

    monkeypatch.setattr(board_mod.Board, "save", _partial_then_raise)
    with pytest.raises(OSError):
        ops.set_settings(rec.id, thickness=0.8)

    assert pcb.read_text(encoding="utf-8") == original  # restored despite the raising write
    assert prepo.head() == head_before
    assert prepo.is_clean()
    assert prepo.is_clean()


# --- M7f-A2 Editor: .kicad_pro severities + ERC pin-map + text-variables ------

# A canonical KiCad-10 .kicad_pro carrying the A2 surfaces (ERC + DRC rule severities, the
# 12x12 ERC pin-conflict matrix, top-level text variables). Built through the serializer so it
# is byte-canonical (2-space, sorted keys, trailing newline) and a minimal-diff edit is provable.
def _pro_a2_text():
    from stockroom.kicad import project_settings as _ps

    pin_map = [[0] * 12 for _ in range(12)]
    pin_map[1][1] = 2  # output vs output = error, a real KiCad default
    pin_map[6][0] = pin_map[0][6] = 1  # unspecified vs input = warning (symmetric)
    data = {
        "board": {
            "design_settings": {
                "defaults": {"copper_line_width": 0.2},
                "rule_severities": {"clearance": "error", "silk_overlap": "warning"},
                "rules": {"min_clearance": 0.2, "min_track_width": 0.2},
            }
        },
        "erc": {
            "pin_map": pin_map,
            "rule_severities": {"pin_not_connected": "error", "wire_dangling": "warning"},
        },
        "meta": {"filename": "board.kicad_pro", "version": 3},
        "net_settings": {"classes": [{"name": "Default"}], "meta": {"version": 5}},
        "text_variables": {"REV": "A", "OLD": "drop"},
    }
    return _ps.serialize(data)


def test_board_settings_reads_pro_severities_pin_map_and_text_vars(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    bs = ops.board_settings(rec.id)
    assert bs["has_pro"] is True
    assert bs["erc_severities"] == {"pin_not_connected": "error", "wire_dangling": "warning"}
    assert bs["drc_severities"] == {"clearance": "error", "silk_overlap": "warning"}
    assert bs["erc_pin_map"][1][1] == 2 and bs["erc_pin_map"][6][0] == 1
    assert bs["text_variables"] == {"REV": "A", "OLD": "drop"}
    # the editor catalogs travel with the read so the frontend renders without a hardcoded list
    assert bs["severity_levels"] == ["error", "warning", "ignore"]
    assert len(bs["erc_pin_types"]) == 12 and bs["erc_pin_types"][0] == "input"


def test_board_settings_pin_map_absent_is_none_never_fabricated(tmp_path):
    # a project whose .kicad_pro has no erc.pin_map reads as None, NOT a fabricated all-OK
    # matrix (which would silently disable every pin-conflict check the real default enforces).
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board")  # plain _PRO, no erc block
    rec = ops.register(proj)
    bs = ops.board_settings(rec.id)
    assert bs["erc_pin_map"] is None
    assert bs["erc_severities"] == {} and bs["drc_severities"] == {}
    assert bs["text_variables"] == {}


def test_set_settings_writes_erc_and_drc_severities_minimal_diff(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    head_before = prepo.head()
    pro = proj / "board.kicad_pro"

    ops.set_settings(
        rec.id,
        erc_severities={"pin_not_connected": "warning"},
        drc_severities={"clearance": "ignore"},
    )

    after = pro.read_text(encoding="utf-8")
    assert '"pin_not_connected": "warning"' in after
    assert '"clearance": "ignore"' in after
    # sibling severities the edit did not name survived untouched (per-rule merge, not wholesale)
    assert '"wire_dangling": "warning"' in after
    assert '"silk_overlap": "warning"' in after
    assert prepo.head() != head_before and prepo.is_clean()


def test_set_settings_writes_pin_map_wholesale(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    new_map = [[0] * 12 for _ in range(12)]
    new_map[2][2] = 2
    ops.set_settings(rec.id, erc_pin_map=new_map)
    assert ops.board_settings(rec.id)["erc_pin_map"] == new_map


def test_set_settings_writes_and_deletes_text_variables(tmp_path):
    # the desired map is authoritative: REV is updated, NEW is added, OLD (absent from it) is
    # deleted via the wholesale-replace path (a plain merge could never drop OLD).
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    ops.set_settings(rec.id, text_variables={"REV": "B", "NEW": "x"})
    tv = ops.board_settings(rec.id)["text_variables"]
    assert tv == {"REV": "B", "NEW": "x"}
    assert "OLD" not in tv


def test_set_settings_rejects_an_unknown_severity_rule(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_settings(rec.id, erc_severities={"not_a_rule_xyz": "error"})


def test_set_settings_rejects_a_bad_pin_map(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_settings(rec.id, erc_pin_map=[[0] * 12 for _ in range(11)])  # 11 rows


def test_set_settings_rejects_a_blank_text_var_name(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.set_settings(rec.id, text_variables={"  ": "x"})


def test_set_settings_board_and_pro_edits_are_one_atomic_commit(tmp_path):
    # a board-setup (.kicad_pcb) edit AND a pro-severity (.kicad_pro) edit submitted together
    # land in ONE commit that touches BOTH files (the atomic-across-files contract).
    ops = _ops(tmp_path)
    proj, prepo = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    head_before = prepo.head()

    ops.set_settings(
        rec.id,
        board_setup={"pad_to_mask_clearance": 0.1},
        erc_severities={"pin_not_connected": "warning"},
    )

    added = prepo._run("rev-list", "--count", f"{head_before}..HEAD").stdout.strip()
    assert added == "1"  # exactly one commit, not two
    names = prepo._run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "board.kicad_pcb" in names and "board.kicad_pro" in names  # both files in it
    bs = ops.board_settings(rec.id)
    assert bs["board_setup"]["pad_to_mask_clearance"] == 0.1
    assert bs["erc_severities"]["pin_not_connected"] == "warning"


def test_set_settings_failed_pro_write_leaves_zero_trace(tmp_path, monkeypatch):
    from stockroom.kicad import project_settings

    ops = _ops(tmp_path)
    proj, prepo = _git_project_with_board(tmp_path / "ext" / "board", pro_text=_pro_a2_text())
    rec = ops.register(proj)
    pro = proj / "board.kicad_pro"
    original = pro.read_text(encoding="utf-8")
    head_before = prepo.head()

    def _corrupt(path, patch, replace_keys=()):
        from pathlib import Path as _P
        _P(path).write_text("{ this is not valid json", encoding="utf-8")

    monkeypatch.setattr(project_settings, "apply_patch", _corrupt)
    with pytest.raises(Exception):
        ops.set_settings(rec.id, erc_severities={"pin_not_connected": "warning"})

    assert pro.read_text(encoding="utf-8") == original  # restored byte-for-byte
    assert prepo.head() == head_before and prepo.is_clean()


# --- M7f-B Editor: object conform (font/thickness normalize) ------------------

# A board with a silk gr_text + a footprint fp_text and a fab fp_text (so a conform is provably
# multi-object + layer-scoped) and a physical (general (thickness)) that a font conform never touches.
_PCB_TEXT = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    "\t(general\n\t\t(thickness 1.6)\n\t)\n"
    '\t(gr_text "BRD"\n\t\t(at 5 5 0)\n\t\t(layer "F.SilkS")\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.5 1.5)\n\t\t\t\t(thickness 0.3)\n\t\t\t)\n\t\t)\n\t)\n"
    '\t(footprint "R"\n'
    '\t\t(property "Reference" "R1"\n\t\t\t(at 0 0 0)\n\t\t\t(layer "F.SilkS")\n'
    "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n"
    '\t\t(fp_text user "FAB"\n\t\t\t(at 0 1 0)\n\t\t\t(layer "F.Fab")\n'
    "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 0.8 0.8)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n"
    "\t)\n)\n"
)
# A sheet with a top-level graphic text + a label (both conformable) and a lib_symbols cache text
# that must never be touched.
_SCH_TEXT = (
    "(kicad_sch\n"
    "\t(version 20260306)\n"
    '\t(lib_symbols\n\t\t(symbol "Device:R"\n\t\t\t(text "CACHE"\n\t\t\t\t(at 0 0 0)\n'
    "\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n"
    '\t(text "NOTE"\n\t\t(at 10 10 0)\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2.54 2.54)\n\t\t\t)\n\t\t)\n\t)\n"
    '\t(label "NET1"\n\t\t(at 20 20 0)\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n\t)\n)\n"
)


def _git_project_conformable(dir_path):
    """A git-backed project whose board AND sheet both carry conformable text objects."""
    dir_path.mkdir(parents=True, exist_ok=True)
    prepo = GitRepo(dir_path)
    prepo.init()
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text(_SCH_TEXT, encoding="utf-8")
    (dir_path / "board.kicad_pcb").write_text(_PCB_TEXT, encoding="utf-8")
    prepo.commit("init project", [
        dir_path / "board.kicad_pro", dir_path / "board.kicad_sch", dir_path / "board.kicad_pcb",
    ])
    return dir_path, prepo


def test_conform_catalog_reports_honest_state_and_catalogs(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    cat = ops.conform_catalog(rec.id)
    assert cat["under_git"] is True
    assert cat["has_pcb"] is True and cat["has_sch"] is True
    assert {c["key"] for c in cat["pcb_categories"]} == {"silk", "fab", "copper"}
    assert {c["key"] for c in cat["sch_categories"]} == {"text", "labels"}
    assert cat["suggested"]["silk"]["size"] > 0


def test_conform_catalog_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.conform_catalog("nope")


def test_conform_preview_counts_without_writing_or_committing(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    pcb_before = (proj / "board.kicad_pcb").read_text(encoding="utf-8")

    prev = ops.conform_preview(
        rec.id, {"silk": {"size": 2.0, "thickness": None}}, {"labels": {"size": 2.0, "thickness": None}}
    )
    by_path = {f["path"]: f for f in prev["files"]}
    assert by_path["board.kicad_pcb"]["counts"]["silk"] == 2  # gr_text + fp_text on silk
    assert by_path["board.kicad_sch"]["counts"]["labels"] == 1
    assert prev["total"] == 3
    # a preview writes nothing and commits nothing
    assert (proj / "board.kicad_pcb").read_text(encoding="utf-8") == pcb_before
    assert prepo.head() == head_before


def test_conform_apply_writes_minimal_diff_and_commits_once(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()

    result = ops.conform_apply(
        rec.id, {"silk": {"size": 2.0, "thickness": None}}, {"labels": {"size": 2.0, "thickness": None}}
    )
    pcb = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    sch = (proj / "board.kicad_sch").read_text(encoding="utf-8")
    assert pcb.count("(size 2 2)") == 2  # both silk objects
    assert "(size 0.8 0.8)" in pcb  # the fab text untouched (not selected)
    assert "(size 2 2)" in sch  # the label
    assert "CACHE" in sch and sch.count("(size 1.27 1.27)") == 1  # lib_symbols cache untouched
    assert result["committed"] == prepo.head()
    assert result["total"] == 3
    assert prepo.is_clean()
    added = prepo._run("rev-list", "--count", f"{head_before}..HEAD").stdout.strip()
    assert added == "1"  # ONE commit for both files


def test_conform_apply_is_one_atomic_commit_over_board_and_sheet(tmp_path):
    ops = _ops(tmp_path)
    proj, prepo = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    ops.conform_apply(rec.id, {"silk": {"size": 2.0}}, {"labels": {"size": 2.0}})
    names = prepo._run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "board.kicad_pcb" in names and "board.kicad_sch" in names


def test_conform_apply_nothing_to_change_is_a_no_commit_noop(tmp_path):
    # a copper conform on a board with no copper text (and no other selection) changes nothing:
    # an honest no-commit no-op, never a fabricated empty commit.
    ops = _ops(tmp_path)
    proj, prepo = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    head_before = prepo.head()
    result = ops.conform_apply(rec.id, {"copper": {"size": 1.0}}, {})
    assert result["committed"] is None
    assert result["total"] == 0
    assert prepo.head() == head_before  # no commit landed


def test_conform_apply_refuses_a_project_not_under_git(tmp_path):
    ops = _ops(tmp_path)
    proj = _make_project(tmp_path / "nogit" / "board", _UNANNOTATED)
    (proj / "board.kicad_pcb").write_text(_PCB_TEXT, encoding="utf-8")
    rec = ops.register(proj)
    assert rec.git_root is None
    with pytest.raises(ValueError):
        ops.conform_apply(rec.id, {"silk": {"size": 2.0}}, {})


def test_conform_apply_empty_selection_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.conform_apply(rec.id, {}, {})


def test_conform_apply_rejects_an_unknown_category(tmp_path):
    ops = _ops(tmp_path)
    proj, _ = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    with pytest.raises(ValueError):
        ops.conform_apply(rec.id, {"bogus": {"size": 2.0}}, {})


def test_conform_apply_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.conform_apply("nope", {"silk": {"size": 2.0}}, {})


def test_conform_apply_raising_write_leaves_zero_trace(tmp_path, monkeypatch):
    # a save that raises mid-write (after some files are already written) must roll EVERY tracked
    # file back to its committed bytes and land no commit (the atomicity contract).
    from stockroom.sexp.document import SexpDocument

    ops = _ops(tmp_path)
    proj, prepo = _git_project_conformable(tmp_path / "ext" / "board")
    rec = ops.register(proj)
    pcb = proj / "board.kicad_pcb"
    sch = proj / "board.kicad_sch"
    pcb_before, sch_before = pcb.read_text(encoding="utf-8"), sch.read_text(encoding="utf-8")
    head_before = prepo.head()

    real_save = SexpDocument.save
    calls = {"n": 0}

    def _flaky_save(self, path):
        calls["n"] += 1
        if calls["n"] == 1:
            real_save(self, path)  # first file lands on disk
            raise OSError("disk full")  # second write never happens; rollback must undo the first
        real_save(self, path)

    monkeypatch.setattr(SexpDocument, "save", _flaky_save)
    with pytest.raises(Exception):
        ops.conform_apply(rec.id, {"silk": {"size": 2.0}}, {"labels": {"size": 2.0}})

    assert pcb.read_text(encoding="utf-8") == pcb_before  # restored byte-for-byte
    assert sch.read_text(encoding="utf-8") == sch_before
    assert prepo.head() == head_before and prepo.is_clean()
