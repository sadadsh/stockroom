from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockroom.model.project import ProjectRecord
from stockroom.projects.assembly import AssemblyRunStore


class _Adapter:
    def placements(self, project):
        del project
        return [
            {
                "ref": "R1",
                "uuid": "native-r1",
                "value": "10k",
                "footprint": "R_0603",
                "props": {"MPN": "RC0603FR-0710KL", "Manufacturer": "Yageo"},
                "_sheet": "Main.SchDoc",
            },
            {
                "ref": "C1",
                "uuid": "native-c1",
                "value": "100n",
                "footprint": "C_0603",
                "props": {"MPN": "CL10B104KB8NNNC"},
                "_sheet": "Main.SchDoc",
            },
        ]


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> ProjectRecord:
    root = tmp_path / "project"
    root.mkdir()
    (root / "Main.SchDoc").write_text("fixture", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Assembler")
    _git(root, "config", "user.email", "assembler@example.test")
    _git(root, "add", "Main.SchDoc")
    _git(root, "commit", "-m", "fixture")
    return ProjectRecord(
        id="amp",
        name="Amp",
        root=root.as_posix(),
        pro_path="Amp.PrjPcb",
        board_paths=["Amp.PcbDoc"],
        sheet_paths=["Main.SchDoc"],
        eda="altium",
        git_root=root.as_posix(),
        registered_at="2026-07-28T00:00:00Z",
    )


def test_run_survives_reopen_and_reconstructs_latest_state(
    tmp_path: Path, project: ProjectRecord, monkeypatch
) -> None:
    monkeypatch.setattr(
        "stockroom.projects.placements.get_adapter",
        lambda eda: _Adapter(),
    )
    store = AssemblyRunStore(
        tmp_path / "state",
        now=lambda: "2026-07-28T12:00:00Z",
        new_id=iter(("run-a", "event-a", "event-b")).__next__,
    )
    run = store.start(project, operator="Sadad", boards=2)
    assert run["source_commit"] == _git(Path(project.root), "rev-parse", "HEAD")
    assert run["progress"]["total"] == 4

    target = run["placements"][0]
    updated = store.record_event(
        "amp",
        "run-a",
        placement_id=target["placement_id"],
        state="done",
        scanned_mpn="RC0603FR-0710KL",
    )
    assert updated["progress"]["counts"]["done"] == 1

    reopened = AssemblyRunStore(tmp_path / "state").active("amp")
    assert reopened is not None
    assert reopened["id"] == "run-a"
    assert reopened["placements"][0]["state"] == "done"
    assert reopened["events"][0]["id"] == "event-a"


def test_mismatched_scan_cannot_complete_placement(
    tmp_path: Path, project: ProjectRecord, monkeypatch
) -> None:
    monkeypatch.setattr(
        "stockroom.projects.placements.get_adapter",
        lambda eda: _Adapter(),
    )
    store = AssemblyRunStore(tmp_path / "state", new_id=lambda: "run-b")
    run = store.start(project, operator="Alex")
    with pytest.raises(ValueError, match="does not match expected"):
        store.record_event(
            "amp",
            "run-b",
            placement_id=run["placements"][0]["placement_id"],
            state="done",
            scanned_mpn="WRONG-PART",
        )


def test_dirty_source_is_refused_before_snapshot(
    tmp_path: Path, project: ProjectRecord, monkeypatch
) -> None:
    monkeypatch.setattr(
        "stockroom.projects.placements.get_adapter",
        lambda eda: _Adapter(),
    )
    (Path(project.root) / "Main.SchDoc").write_text("changed", encoding="utf-8")
    store = AssemblyRunStore(tmp_path / "state")
    with pytest.raises(ValueError, match="before pinning"):
        store.start(project, operator="Sadad")


def test_completed_run_has_verifiable_receipt_and_clears_active(
    tmp_path: Path, project: ProjectRecord, monkeypatch
) -> None:
    monkeypatch.setattr(
        "stockroom.projects.placements.get_adapter",
        lambda eda: _Adapter(),
    )
    ids = iter(("run-c", "event-c1", "event-c2"))
    store = AssemblyRunStore(
        tmp_path / "state",
        now=iter(
            (
                "2026-07-28T12:00:00Z",
                "2026-07-28T12:01:00Z",
                "2026-07-28T12:02:00Z",
                "2026-07-28T12:03:00Z",
            )
        ).__next__,
        new_id=ids.__next__,
    )
    run = store.start(project, operator="Sadad")
    with pytest.raises(ValueError, match="pending placement"):
        store.complete("amp", "run-c")
    for placement in run["placements"]:
        store.record_event(
            "amp",
            "run-c",
            placement_id=placement["placement_id"],
            state="done",
        )
    completed = store.complete("amp", "run-c")
    assert completed["status"] == "completed"
    assert completed["receipt"]["source_commit"] == completed["source_commit"]
    assert len(completed["receipt"]["digest"]) == 64
    assert store.active("amp") is None
    with pytest.raises(ValueError, match="cannot accept new events"):
        store.record_event(
            "amp",
            "run-c",
            placement_id=run["placements"][0]["placement_id"],
            state="reworked",
        )


def test_resolved_progress_and_altium_bindings_feed_the_bench(
    tmp_path: Path, project: ProjectRecord, monkeypatch
) -> None:
    monkeypatch.setattr(
        "stockroom.projects.placements.get_adapter",
        lambda eda: _Adapter(),
    )
    project.bindings = {"altium": {"native-r1": "r10k"}}
    part = SimpleNamespace(
        id="r10k",
        mpn="RC0402FR-0710KL",
        manufacturer="Yageo",
    )
    store = AssemblyRunStore(
        tmp_path / "state",
        new_id=iter(("run-d", "event-d1", "event-d2")).__next__,
    )
    run = store.start(project, operator="Sadad", library_parts=[part])
    resistor = run["placements"][0]
    assert resistor["part_id"] == "r10k"
    assert resistor["mpn"] == "RC0402FR-0710KL"
    assert resistor["manufacturer"] == "Yageo"

    run = store.record_event(
        "amp",
        "run-d",
        placement_id=resistor["placement_id"],
        state="reworked",
    )
    assert run["progress"]["complete"] == 0
    assert run["progress"]["resolved"] == 1
    assert run["progress"]["percent"] == 50.0

    run = store.record_event(
        "amp",
        "run-d",
        placement_id=run["placements"][1]["placement_id"],
        state="skipped",
    )
    assert run["progress"]["resolved"] == 2
    assert run["progress"]["percent"] == 100.0
