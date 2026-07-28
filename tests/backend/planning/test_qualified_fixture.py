from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from stockroom.eda import UnsupportedProjection
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.stock import find_kicad_share_dir
from stockroom.planning import OnePartFixtureRunner
from stockroom.vcs import GitRepo
from stockroom.workflow import BatchStatus, StageName, StageStatus, WorkflowStore

FIXTURE = Path(__file__).parents[1] / "altium" / "fixtures" / "sample.IntLib"


def _requires_kicad_10() -> None:
    cli = KiCadCli()
    if not cli.available or find_kicad_share_dir() is None:
        pytest.skip("installed KiCad 10 CLI and stock libraries are required")
    if not cli.version().startswith("10."):
        pytest.skip("this projection is qualified only against KiCad 10")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def _repository(root: Path) -> GitRepo:
    repository = GitRepo(root)
    repository.init()
    (root / "Dirty.txt").write_text("base dirty\n", encoding="utf-8")
    (root / "Staged.txt").write_text("base staged\n", encoding="utf-8")
    repository.commit(
        "Initialize empty component library",
        [root / "Dirty.txt", root / "Staged.txt"],
    )
    return repository


def _runner(
    store: WorkflowStore,
    staging: Path,
    repository: GitRepo,
    active: Path,
) -> OnePartFixtureRunner:
    return OnePartFixtureRunner(
        store,
        staging,
        repository,
        FIXTURE,
        fixture_mode=True,
        live_catalog_path=active / "Catalog.sqlite",
        machine_local_root=active,
    )


def _assert_plain_json(value: object) -> None:
    if value is None or type(value) in {bool, int, float, str}:
        return
    if type(value) is list:
        for item in value:
            _assert_plain_json(item)
        return
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for item in value.values():
            _assert_plain_json(item)
        return
    raise AssertionError(f"non-JSON workflow result: {type(value).__name__}")


def test_rejects_non_fixture_mode_before_native_altium_exists(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "Workflow.sqlite")
    repository = GitRepo(tmp_path / "Library")

    with pytest.raises(
        UnsupportedProjection,
        match="real native Altium adapter",
    ):
        OnePartFixtureRunner(
            store,
            tmp_path / "Staging",
            repository,
            FIXTURE,
            fixture_mode=False,
        )


@pytest.mark.requires_kicad_cli
def test_resumes_after_store_reopen_and_publishes_one_scoped_commit(
    tmp_path: Path,
) -> None:
    _requires_kicad_10()
    repository = _repository(tmp_path / "Library")
    base_commit = repository.head()
    staging = tmp_path / "Staging"
    active = tmp_path / "Active"
    database = tmp_path / "Workflow.sqlite"

    dirty_path = repository.root / "Dirty.txt"
    staged_path = repository.root / "Staged.txt"
    dirty_path.write_text("owner dirty work\n", encoding="utf-8")
    staged_path.write_text("owner staged work\n", encoding="utf-8")
    _git(repository.root, "add", "--", "Staged.txt")
    dirty_before = _git(repository.root, "diff", "--binary", "--", "Dirty.txt")
    staged_before = _git(
        repository.root,
        "diff",
        "--cached",
        "--binary",
        "--",
        "Staged.txt",
    )

    first_store = WorkflowStore(database)
    first_runner = _runner(first_store, staging, repository, active)
    batch = first_runner.submit_fixture(idempotency_key="qualified-s1m-e2e")

    for _ in range(7):
        dispatch = first_runner.poll_stage("fixture_stage_worker")
        assert dispatch is not None
    item_id = first_store.list_items(batch.id)[0].id
    stages_before_reopen = {stage.name: stage for stage in first_store.list_stages(item_id)}
    assert stages_before_reopen[StageName.CANONICAL_DEFINITION].status is StageStatus.COMPLETED
    assert stages_before_reopen[StageName.NATIVE_CONVERSION_ACQUISITION].status is StageStatus.READY

    reopened_store = WorkflowStore(database)
    resumed_runner = _runner(reopened_store, staging, repository, active)
    result = resumed_runner.run_to_completion(
        batch.id,
        worker_id="fixture_stage_worker",
    )

    assert result.batch.status is BatchStatus.COMPLETED
    assert result.item_id == item_id
    assert result.receipt.publication_id == result.publication_id
    with sqlite3.connect(database) as connection:
        global_receipt_count = connection.execute(
            "SELECT COUNT(*) FROM component_publication_receipts"
        ).fetchone()[0]
        publication_operation_count = connection.execute(
            "SELECT COUNT(*) FROM publication_operations"
        ).fetchone()[0]
    assert global_receipt_count == 1
    assert publication_operation_count == 1
    completed_stages = reopened_store.list_stages(item_id)
    assert len(completed_stages) == 14
    assert tuple(stage.name for stage in completed_stages) == tuple(StageName)
    assert all(stage.status is StageStatus.COMPLETED for stage in completed_stages)
    for stage in completed_stages:
        _assert_plain_json(stage.result)
        json.dumps(stage.result, allow_nan=False)

    assert _git(repository.root, "rev-list", "--count", f"{base_commit}..HEAD").strip() == "1"
    changed = {
        path
        for path in _git(
            repository.root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "HEAD",
        ).splitlines()
        if path
    }
    assert len(changed) == 9
    assert any(path.endswith("Canonical Component.json") for path in changed)
    assert {
        "Catalog/Catalog Digest.json",
        "Catalog/Stockroom.kicad_dbl",
        "Stockroom-Portable-KiCad-Tables/Stockroom-Portable-Symbol-Libraries.kicad-table",
        "Stockroom-Portable-KiCad-Tables/Stockroom-Portable-Footprint-Libraries.kicad-table",
    } <= changed
    assert "Catalog/Catalog.sqlite" not in changed
    assert "Catalog/Stockroom.DbLib" not in changed
    receipt_payload = result.receipt.payload
    assert type(receipt_payload) is dict
    tracked_from_receipt = {target["path"] for target in receipt_payload["tracked_files"]}
    machine_local_from_receipt = {
        target["path"] for target in receipt_payload["machine_local_files"]
    }
    assert tracked_from_receipt == changed
    assert machine_local_from_receipt == {"Catalog/Stockroom.DbLib"}

    assert _git(repository.root, "diff", "--binary", "--", "Dirty.txt") == dirty_before
    assert (
        _git(
            repository.root,
            "diff",
            "--cached",
            "--binary",
            "--",
            "Staged.txt",
        )
        == staged_before
    )
    assert _git(repository.root, "diff", "--name-only").splitlines() == ["Dirty.txt"]
    assert _git(
        repository.root,
        "diff",
        "--cached",
        "--name-only",
    ).splitlines() == ["Staged.txt"]

    assert (active / "Catalog.sqlite").is_file()
    assert (active / "Catalog" / "Stockroom.DbLib").is_file()
    assert not (active / "sym-lib-table").exists()
    assert not (active / "fp-lib-table").exists()

    second = resumed_runner.run_to_completion(batch.id)
    assert second.publication_id == result.publication_id
    assert repository.head() == result.receipt.git_commit_oid
    assert _git(repository.root, "rev-list", "--count", f"{base_commit}..HEAD").strip() == "1"
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM component_publication_receipts").fetchone()[0]
            == 1
        )
