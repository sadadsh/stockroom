from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.model.project import ProjectRecord
from stockroom.projects.collaboration import ReviewCandidate, ReviewManager
from stockroom.projects.review_evidence import (
    attach_native_validation,
    build_review_evidence,
    run_review_native_validation,
)
from stockroom.vcs.repo import GitRepo
from tests.backend.projects.test_bom import _write_schdoc


def _project_files(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_file())


def _kicad_project(root: Path) -> ProjectRecord:
    (root / "Amp.kicad_pro").write_text("{}", encoding="utf-8")
    (root / "Amp.kicad_sch").write_text(
        '(kicad_sch (symbol (lib_id "Amplifier_Operational:LM358")'
        ' (uuid "11111111-1111-1111-1111-111111111111")'
        ' (property "Reference" "U1")'
        ' (property "Value" "LM358DR")'
        ' (property "MPN" "LM358DR")'
        ' (property "Manufacturer" "Texas Instruments")'
        ' (property "Footprint" "Package_SO:SOIC-8")))\n',
        encoding="utf-8",
    )
    return ProjectRecord(
        id="amp",
        name="Amp",
        root=root.as_posix(),
        pro_path="Amp.kicad_pro",
        sheet_paths=["Amp.kicad_sch"],
        eda="kicad",
        git_root=root.as_posix(),
    )


def _altium_project(root: Path) -> ProjectRecord:
    (root / "Amp.PrjPcb").write_text(
        "[Design]\n[Document1]\nDocumentPath=Amp.SchDoc\n",
        encoding="utf-8",
    )
    _write_schdoc(
        root / "Amp.SchDoc",
        {
            "designator": "U1",
            "lib_ref": "LM358",
            "params": {
                "Value": "LM358DR",
                "MPN": "LM358DR",
                "Manufacturer": "Texas Instruments",
            },
            "footprint": "SOIC-8",
        },
    )
    return ProjectRecord(
        id="amp",
        name="Amp",
        root=root.as_posix(),
        pro_path="Amp.PrjPcb",
        sheet_paths=["Amp.SchDoc"],
        eda="altium",
        git_root=root.as_posix(),
    )


@pytest.mark.parametrize("factory", [_kicad_project, _altium_project])
def test_exact_review_evidence_is_shared_and_does_not_touch_the_checkout(
    tmp_path,
    factory,
):
    root = tmp_path / factory.__name__
    root.mkdir()
    project = factory(root)
    repo = GitRepo(root)
    repo.init()
    base = repo.commit("base", _project_files(root))
    repo._run("switch", "-c", "work/mina/amp")
    marker = root / ("Amp.kicad_sch" if project.eda == "kicad" else "Amp.PrjPcb")
    marker.write_bytes(marker.read_bytes() + b"\n")
    review = repo.commit("review", [marker])
    candidate = ReviewCandidate(
        branch="work/mina/amp",
        commit=review,
        base_branch="main",
        base_commit=base,
        changed_paths=(marker.name,),
    )
    before = (repo.current_branch(), repo.head(), repo.is_clean())

    evidence = build_review_evidence(ReviewManager(repo), project, candidate)
    repeated = build_review_evidence(ReviewManager(repo), project, candidate)

    assert evidence["eda"] == project.eda
    assert evidence["commit"] == review
    assert evidence["reviewable"] is True
    assert evidence["bom"]["line_count"] == 1
    assert evidence["bom"]["lines"][0]["mpn"] == "LM358DR"
    assert evidence["semantic_audit"]["counts"]["by_severity"]["error"] == 0
    assert evidence["native_validation"]["status"] == "pending"
    assert evidence["visual_diff"]["status"] == "pending"
    assert evidence["digest"] == repeated["digest"]
    assert len(evidence["digest"]) == 64
    assert (repo.current_branch(), repo.head(), repo.is_clean()) == before


def test_missing_bom_identity_blocks_the_review_snapshot(tmp_path):
    root = tmp_path / "blocked"
    root.mkdir()
    project = _kicad_project(root)
    sheet = root / "Amp.kicad_sch"
    sheet.write_text(
        '(kicad_sch (symbol (lib_id "Connector_Generic:Conn_01x02")'
        ' (property "Reference" "J1")'
        ' (property "Value" "")'
        ' (property "Footprint" "Connector_Molex:MicroFit_2x01")))\n',
        encoding="utf-8",
    )
    repo = GitRepo(root)
    repo.init()
    base = repo.commit("base", _project_files(root))
    repo._run("switch", "-c", "work/mina/amp")
    sheet.write_bytes(sheet.read_bytes() + b"\n")
    review = repo.commit("review", [sheet])
    candidate = ReviewCandidate(
        branch="work/mina/amp",
        commit=review,
        base_branch="main",
        base_commit=base,
        changed_paths=("Amp.kicad_sch",),
    )

    evidence = build_review_evidence(ReviewManager(repo), project, candidate)

    assert evidence["reviewable"] is False
    assert {finding["kind"] for finding in evidence["blockers"]} == {
        "missing_identity",
    }


def test_native_validation_is_bound_to_the_exact_detached_source(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "native"
    root.mkdir()
    project = _kicad_project(root)
    repo = GitRepo(root)
    repo.init()
    base = repo.commit("base", _project_files(root))
    repo._run("switch", "-c", "work/mina/amp")
    sheet = root / "Amp.kicad_sch"
    sheet.write_bytes(sheet.read_bytes() + b"\n")
    review = repo.commit("review", [sheet])
    candidate = ReviewCandidate(
        branch="work/mina/amp",
        commit=review,
        base_branch="main",
        base_commit=base,
        changed_paths=("Amp.kicad_sch",),
    )
    before = (repo.current_branch(), repo.head(), repo.is_clean(), sheet.read_bytes())
    validated_roots: list[Path] = []

    class Adapter:
        def validate(self, snapshot):
            validated_roots.append(Path(snapshot.root))
            return {
                "schema_version": 1,
                "adapter": "kicad",
                "status": "passed",
                "runtime": {"name": "KiCad CLI", "version": "9.0.4"},
                "checks": [
                    {
                        "kind": "schematic",
                        "path": "Amp.kicad_sch",
                        "status": "passed",
                        "errors": 0,
                        "warnings": 0,
                        "detail": "ERC passed.",
                    }
                ],
                "summary": {"checked": 1, "errors": 0, "warnings": 0},
                "detail": "Native checks passed.",
                "digest": "adapter-owned",
            }

    monkeypatch.setattr(
        "stockroom.projects.review_evidence.get_adapter",
        lambda eda: Adapter(),
    )

    manager = ReviewManager(repo)
    source = build_review_evidence(manager, project, candidate)
    validation = run_review_native_validation(manager, project, candidate)
    attached = attach_native_validation(source, validation)

    assert validation["status"] == "passed"
    assert validation["commit"] == review
    assert validation["source_digest"] == source["source_digest"]
    assert validated_roots and validated_roots[0] != root
    assert attached["reviewable"] is True
    assert attached["native_validation"]["checks"][0]["status"] == "passed"
    assert len(attached["digest"]) == 64
    assert (repo.current_branch(), repo.head(), repo.is_clean(), sheet.read_bytes()) == before


def test_native_validation_from_different_source_cannot_unlock_approval(tmp_path):
    root = tmp_path / "mismatch"
    root.mkdir()
    project = _kicad_project(root)
    repo = GitRepo(root)
    repo.init()
    base = repo.commit("base", _project_files(root))
    repo._run("switch", "-c", "work/mina/amp")
    sheet = root / "Amp.kicad_sch"
    sheet.write_bytes(sheet.read_bytes() + b"\n")
    review = repo.commit("review", [sheet])
    candidate = ReviewCandidate(
        branch="work/mina/amp",
        commit=review,
        base_branch="main",
        base_commit=base,
        changed_paths=("Amp.kicad_sch",),
    )
    evidence = build_review_evidence(ReviewManager(repo), project, candidate)
    validation = {
        "project_id": project.id,
        "branch": candidate.branch,
        "commit": candidate.commit,
        "base_branch": candidate.base_branch,
        "base_commit": candidate.base_commit,
        "source_digest": "0" * 64,
        "status": "passed",
        "detail": "Checks passed against some other source.",
    }

    attached = attach_native_validation(evidence, validation)

    assert attached["reviewable"] is False
    assert attached["native_validation"]["status"] == "pending"
    assert {item["kind"] for item in attached["blockers"]} == {
        "native_validation_pending"
    }
