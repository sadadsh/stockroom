from __future__ import annotations

from pathlib import Path

from stockroom.altium.driver import RunOutcome
from stockroom.altium.project_validation import (
    _configure_drc_outjob,
    parse_drc_report,
    validate_altium_project,
)
from stockroom.model.project import ProjectRecord


def _template(path: Path) -> Path:
    path.write_text(
        "[OutputJobFile]\nVersion=1.0\n"
        "[OutputGroup1]\nTargetOutputMedium=Fabrication\n"
        "OutputMedium1=Reports\nOutputMedium1_Type=GeneratedFiles\n"
        "OutputType1=Design Rules Check\n"
        "OutputName1=Design Rules Check\n"
        "OutputCategory1=Validation\n"
        "OutputDocumentPath1=\n"
        "OutputEnabled1=0\n"
        "OutputEnabled1_OutputMedium1=1\n"
        "[GeneratedFilesSettings]\n"
        "RelativeOutputPath1=old\nOpenOutputs1=1\nAddToProject1=1\n",
        encoding="latin-1",
    )
    return path


def _report(path: Path, *, warnings: int = 0, violations: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<html><body><h1>Design Rule Verification Report</h1>"
        f"<table><tr><td>Warnings:</td><td>{warnings}</td></tr>"
        f"<tr><td>Rule Violations:</td><td>{violations}</td></tr></table>"
        "</body></html>",
        encoding="utf-8",
    )


class _Driver:
    def __init__(
        self,
        x2: Path,
        *,
        violations: int = 0,
        marker_status: str = "completed",
        schematic_state: str = "completed",
        schematic_errors: str = "0",
    ) -> None:
        self.x2 = x2
        self.violations = violations
        self.marker_status = marker_status
        self.schematic_state = schematic_state
        self.schematic_errors = schematic_errors

    @property
    def installed(self) -> bool:
        return True

    def run_script(self, **kwargs) -> RunOutcome:
        marker = kwargs["marker"]
        run_root = kwargs["project"].parent / "project"
        _report(
            run_root / "Project Outputs for Amp" / "Reports" / "DRC" / "Amp.html",
            warnings=2,
            violations=self.violations,
        )
        marker_text = (
            f"SCHEMATIC|{self.schematic_state}|1|{self.schematic_errors}|1|1\n"
            "DOCUMENTS|3|1\n"
            "PCB|Amp.PcbDoc|completed|DRC process returned\n"
            f"STATUS|{self.marker_status}|native checks returned\n"
        )
        marker.write_text(marker_text, encoding="utf-8")
        return RunOutcome("ok", "marker written", marker_text=marker_text)


def _project(root: Path) -> ProjectRecord:
    (root / "Amp.PrjPcb").write_text(
        "[Design]\n[Document1]\nDocumentPath=Amp.SchDoc\n"
        "[Document2]\nDocumentPath=Amp.PcbDoc\n",
        encoding="utf-8",
    )
    (root / "Amp.SchDoc").write_bytes(b"schematic")
    (root / "Amp.PcbDoc").write_bytes(b"board")
    return ProjectRecord(
        id="amp",
        name="Amp",
        root=root.as_posix(),
        pro_path="Amp.PrjPcb",
        sheet_paths=["Amp.SchDoc"],
        board_paths=["Amp.PcbDoc"],
        eda="altium",
    )


def test_configure_outjob_keeps_only_the_drc_reports_mapping(tmp_path):
    source = _template(tmp_path / "source.OutJob")
    target = tmp_path / "target.OutJob"

    digest = _configure_drc_outjob(source, target, "Amp.PcbDoc")

    text = target.read_text(encoding="latin-1")
    assert "TargetOutputMedium=Reports" in text
    assert "OutputDocumentPath1=Amp.PcbDoc" in text
    assert "OutputEnabled1=1" in text
    assert "OutputEnabled1_OutputMedium1=1" in text
    assert "OpenOutputs1=0" in text
    assert "AddToProject1=0" in text
    assert len(digest) == 64


def test_parse_drc_report_requires_native_summary_counts(tmp_path):
    report = tmp_path / "Amp.html"
    _report(report, warnings=2, violations=3)

    parsed = parse_drc_report(report)

    assert parsed["ok"] is True
    assert parsed["warnings"] == 2
    assert parsed["errors"] == 3
    assert parsed["artifact"]["bytes"] > 0
    assert len(parsed["artifact"]["sha256"]) == 64


def test_parse_drc_report_rejects_a_known_bad_report_without_summary_counts(tmp_path):
    report = tmp_path / "Amp.html"
    report.write_text(
        "<html><body><h1>Design Rule Verification Report</h1>"
        "<p>Everything looks fine.</p></body></html>",
        encoding="utf-8",
    )

    parsed = parse_drc_report(report)

    assert parsed["ok"] is False
    assert parsed["errors"] == 0
    assert "did not expose summary counts" in parsed["detail"]


def test_native_validation_runs_in_a_copy_and_returns_one_shared_contract(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    project = _project(root)
    template = _template(tmp_path / "Fabrication.OutJob")
    x2 = tmp_path / "AD26" / "X2.EXE"
    x2.parent.mkdir()
    x2.write_bytes(b"x2")
    monkeypatch.setattr(
        "stockroom.altium.project_validation._template_for",
        lambda _driver: template,
    )
    before = {path.name: path.read_bytes() for path in root.iterdir()}

    result = validate_altium_project(project, _Driver(x2))

    assert result["adapter"] == "altium"
    assert result["status"] == "passed"
    assert result["summary"] == {"checked": 2, "errors": 0, "warnings": 3}
    assert [check["kind"] for check in result["checks"]] == ["schematic", "pcb"]
    assert result["checks"][1]["artifact"]["name"] == "Amp.html"
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    assert not list(root.glob("*.OutJob"))
    assert len(result["digest"]) == 64


def test_native_drc_violations_fail_the_shared_contract(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    project = _project(root)
    template = _template(tmp_path / "Fabrication.OutJob")
    x2 = tmp_path / "AD26" / "X2.EXE"
    x2.parent.mkdir()
    x2.write_bytes(b"x2")
    monkeypatch.setattr(
        "stockroom.altium.project_validation._template_for",
        lambda _driver: template,
    )

    result = validate_altium_project(project, _Driver(x2, violations=4))

    assert result["status"] == "failed"
    assert result["summary"]["errors"] == 4
    assert result["checks"][1]["status"] == "failed"


def test_native_validation_does_not_pass_before_the_terminal_marker_is_observed(
    tmp_path, monkeypatch
):
    root = tmp_path / "source"
    root.mkdir()
    project = _project(root)
    template = _template(tmp_path / "Fabrication.OutJob")
    x2 = tmp_path / "AD26" / "X2.EXE"
    x2.parent.mkdir()
    x2.write_bytes(b"x2")
    monkeypatch.setattr(
        "stockroom.altium.project_validation._template_for",
        lambda _driver: template,
    )

    result = validate_altium_project(
        project,
        _Driver(x2, marker_status="running"),
    )

    assert result["status"] == "blocked"
    assert result["summary"]["errors"] == 0
    assert all(check["status"] == "passed" for check in result["checks"])


def test_malformed_native_marker_fails_closed_instead_of_crashing_or_passing(
    tmp_path, monkeypatch
):
    root = tmp_path / "source"
    root.mkdir()
    project = _project(root)
    template = _template(tmp_path / "Fabrication.OutJob")
    x2 = tmp_path / "AD26" / "X2.EXE"
    x2.parent.mkdir()
    x2.write_bytes(b"x2")
    monkeypatch.setattr(
        "stockroom.altium.project_validation._template_for",
        lambda _driver: template,
    )

    result = validate_altium_project(
        project,
        _Driver(x2, schematic_errors="not-a-number"),
    )

    assert result["status"] == "blocked"
    assert result["checks"][0]["status"] == "blocked"
