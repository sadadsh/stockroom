from __future__ import annotations

from pathlib import Path

from stockroom.vcs.checkouts import scan_stockroom_checkouts
from stockroom.vcs.repo import GitRepo


def _origin(tmp_path: Path) -> GitRepo:
    repo = GitRepo(tmp_path / "origin")
    repo.init()
    marker = repo.root / "pyproject.toml"
    marker.write_text('[project]\nname = "stockroom"\n', encoding="utf-8")
    repo.commit("initial", [marker])
    return repo


def test_bounded_inventory_classifies_canonical_active_rival_and_ignores_other_remote(
    tmp_path: Path,
) -> None:
    origin = _origin(tmp_path)
    canonical = GitRepo(tmp_path / "Workspace" / "Stockroom")
    canonical.clone_from(origin.root)
    rival = GitRepo(tmp_path / "Other" / "Stockroom Copy")
    rival.clone_from(origin.root)
    unrelated_origin = GitRepo(tmp_path / "unrelated-origin")
    unrelated_origin.init()
    other_file = unrelated_origin.root / "other.txt"
    other_file.write_text("other\n", encoding="utf-8")
    unrelated_origin.commit("other", [other_file])
    unrelated = GitRepo(tmp_path / "Other" / "Unrelated")
    unrelated.clone_from(unrelated_origin.root)

    inventory = scan_stockroom_checkouts(
        canonical,
        roots=(tmp_path,),
        active_library=rival.root,
        max_depth=5,
        max_directories=100,
    )
    by_class = {item["classification"]: item for item in inventory["checkouts"]}

    assert inventory["state"] == "complete"
    assert inventory["rival_count"] == 1
    assert Path(by_class["canonical"]["path"]) == canonical.root.resolve()
    assert Path(by_class["active_rival"]["path"]) == rival.root.resolve()
    assert str(unrelated.root.resolve()) not in {item["path"] for item in inventory["checkouts"]}


def test_inventory_has_a_hard_directory_budget(tmp_path: Path) -> None:
    origin = _origin(tmp_path)
    canonical = GitRepo(tmp_path / "canonical")
    canonical.clone_from(origin.root)
    for number in range(10):
        (tmp_path / f"folder-{number}" / "nested").mkdir(parents=True)

    inventory = scan_stockroom_checkouts(
        canonical,
        roots=(tmp_path,),
        max_depth=5,
        max_directories=2,
    )

    assert inventory["state"] == "truncated"
    assert inventory["scanned_directories"] == 2
    assert any(item["classification"] == "canonical" for item in inventory["checkouts"])


def test_depth_boundary_reports_incomplete_evidence_when_a_subtree_was_not_scanned(
    tmp_path: Path,
) -> None:
    origin = _origin(tmp_path)
    canonical = GitRepo(tmp_path / "canonical")
    canonical.clone_from(origin.root)
    (tmp_path / "level-one" / "level-two").mkdir(parents=True)

    inventory = scan_stockroom_checkouts(
        canonical,
        roots=(tmp_path / "level-one",),
        max_depth=0,
        max_directories=100,
    )

    assert inventory["state"] == "truncated"


def test_an_unmanaged_canonical_checkout_does_not_match_every_local_repository(
    tmp_path: Path,
) -> None:
    canonical = _origin(tmp_path / "canonical-parent")
    unrelated = _origin(tmp_path / "unrelated-parent")

    inventory = scan_stockroom_checkouts(
        canonical,
        roots=(tmp_path,),
        max_depth=4,
        max_directories=100,
    )

    paths = {item["path"] for item in inventory["checkouts"]}
    assert str(canonical.root.resolve()) in paths
    assert str(unrelated.root.resolve()) not in paths
    assert inventory["rival_count"] == 0
