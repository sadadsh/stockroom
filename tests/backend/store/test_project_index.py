from stockroom.model.project import ProjectRecord
from stockroom.store.project_index import ProjectIndex


def _write(projects_dir, rec):
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / f"{rec.id}.json").write_text(rec.dumps(), encoding="utf-8")


def _seed(tmp_path):
    pdir = tmp_path / "projects"
    _write(
        pdir,
        ProjectRecord(
            id="alpha",
            name="Alpha Board",
            root="/home/x/alpha",
            pro_path="alpha.kicad_pro",
            board_paths=["alpha.kicad_pcb"],
            sheet_paths=["alpha.kicad_sch", "power.kicad_sch"],
            git_root="/home/x",
            registered_at="2026-07-13T10:00:00Z",
        ),
    )
    _write(
        pdir,
        ProjectRecord(id="beta", name="Beta", root="/home/y/beta", registered_at="2026-07-13T11:00:00Z"),
    )
    return pdir


def test_build_derives_a_row_per_record(tmp_path):
    idx = ProjectIndex.build(_seed(tmp_path))
    assert idx.count() == 2
    row = idx.get("alpha")
    assert row.name == "Alpha Board"
    assert row.root == "/home/x/alpha"
    assert row.board_count == 1
    assert row.sheet_count == 2
    assert row.has_git is True
    assert idx.get("beta").has_git is False
    assert idx.get("beta").board_count == 0


def test_build_tolerates_a_missing_projects_dir(tmp_path):
    idx = ProjectIndex.build(tmp_path / "not_there")
    assert idx.count() == 0
    assert idx.all() == []


def test_search_matches_name_and_root_substrings(tmp_path):
    idx = ProjectIndex.build(_seed(tmp_path))
    assert [r.id for r in idx.search("alpha")] == ["alpha"]
    assert [r.id for r in idx.search("/home/y")] == ["beta"]
    # empty query returns everything, sorted by name (case-insensitive)
    assert [r.id for r in idx.search("")] == ["alpha", "beta"]


def test_search_is_case_insensitive(tmp_path):
    idx = ProjectIndex.build(_seed(tmp_path))
    assert [r.id for r in idx.search("BOARD")] == ["alpha"]


def test_get_missing_returns_none(tmp_path):
    idx = ProjectIndex.build(_seed(tmp_path))
    assert idx.get("nope") is None


def test_all_returns_every_row_sorted(tmp_path):
    idx = ProjectIndex.build(_seed(tmp_path))
    assert [r.id for r in idx.all()] == ["alpha", "beta"]


def test_facets_count_total_and_git_backed(tmp_path):
    idx = ProjectIndex.build(_seed(tmp_path))
    f = idx.facets()
    assert f.total == 2
    assert f.with_git == 1
