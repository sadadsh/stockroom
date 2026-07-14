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
    assert prepo.is_clean()
