from pathlib import Path

from stockroom.altium.project_visuals import (
    _configure_pcb_outjob,
    _configure_schematic_outjob,
    render_altium_project,
)
from stockroom.model.project import ProjectRecord


class _InstalledDriver:
    installed = True
    x2 = Path("C:/Program Files/Altium/AD26/X2.EXE")


def test_altium_visuals_remain_honestly_blocked_until_native_publish_is_qualified(
    tmp_path: Path,
):
    project = ProjectRecord(
        id="demo",
        name="Demo",
        root=tmp_path.as_posix(),
        eda="altium",
        sheet_paths=["Demo.SchDoc"],
    )

    bundle = render_altium_project(project, _InstalledDriver())

    assert bundle.evidence["status"] == "blocked"
    assert bundle.evidence["adapter"] == "altium"
    assert bundle.evidence["runtime"]["version"] == "AD26"
    assert "not qualified" in bundle.evidence["detail"]
    assert bundle.artifacts == {}


def test_schematic_outjob_enables_only_the_native_print_container(tmp_path: Path):
    source = tmp_path / "Assembly.OutJob"
    target = tmp_path / "Review.OutJob"
    pdf = tmp_path / "review.pdf"
    source.write_text(
        "\n".join(
            (
                "TargetOutputMedium=Other",
                "OutputMedium2=Documentation",
                "OutputMedium2_Type=Publish",
                "OutputType4=Schematic Print",
                "OutputEnabled4=0",
                "OutputEnabled4_OutputMedium2=0",
                "OutputDocumentPath4=",
                "OutputFilePath2=old.pdf",
                "OutputFileName2=old.pdf",
                "RelativeOutputPath2=old.pdf",
                "OpenOutputs2=1",
            )
        ),
        encoding="latin-1",
    )

    template_hash = _configure_schematic_outjob(source, target, pdf)
    configured = target.read_text(encoding="latin-1")

    assert len(template_hash) == 64
    assert "TargetOutputMedium=Documentation" in configured
    assert "OutputEnabled4=1" in configured
    assert "OutputEnabled4_OutputMedium2=1" in configured
    assert "OutputDocumentPath4=[Project Physical Documents]" in configured
    assert f"OutputFilePath2={pdf}" in configured
    assert "OpenOutputs2=0" in configured


def test_pcb_outjob_builds_intentional_top_and_bottom_views(tmp_path: Path):
    source = tmp_path / "Fabrication.OutJob"
    source.write_text(
        "\n".join(
            (
                "TargetOutputMedium=Other",
                "OutputMedium2=PDF",
                "OutputMedium2_Type=Publish",
                "OutputType7=PCB Print",
                "OutputEnabled7=0",
                "OutputEnabled7_OutputMedium2=0",
                "OutputDocumentPath7=",
                "PageOptions7=Record=PageOptions",
                "Configuration7_Item1=Record=PcbPrintView|PrintArea=DesignExtent",
                "Configuration7_Item2=Record=PcbPrintOut|Index=0|Mirror=False|Name=Composite",
                "Configuration7_Item3=Record=PcbPrintLayer|Layer=TopLayer|PrintOutIndex=0",
                "Configuration7_Item4=Record=PcbPrintLayer|Layer=TopOverlay|PrintOutIndex=0",
                "Configuration7_Item5=Record=PcbPrintLayer|Layer=BottomLayer|PrintOutIndex=0",
                "Configuration7_Item6=Record=PcbPrintLayer|Layer=BottomOverlay|PrintOutIndex=0",
                "Configuration7_Item7=Record=PcbPrintLayer|Layer=MultiLayer|PrintOutIndex=0",
                "OutputFilePath2=old.pdf",
                "OutputFileName2=old.pdf",
                "RelativeOutputPath2=old.pdf",
                "OpenOutputs2=1",
            )
        ),
        encoding="latin-1",
    )

    top = tmp_path / "Top.OutJob"
    bottom = tmp_path / "Bottom.OutJob"
    _configure_pcb_outjob(
        source,
        top,
        board_name="Demo.PcbDoc",
        side="top",
        target_pdf=tmp_path / "top.pdf",
    )
    _configure_pcb_outjob(
        source,
        bottom,
        board_name="Demo.PcbDoc",
        side="bottom",
        target_pdf=tmp_path / "bottom.pdf",
    )

    top_text = top.read_text(encoding="latin-1")
    bottom_text = bottom.read_text(encoding="latin-1")
    assert "Layer=TopLayer" in top_text
    assert "Layer=TopOverlay" in top_text
    assert "Layer=BottomLayer" not in top_text
    assert "Mirror=False" in top_text
    assert "Layer=BottomLayer" in bottom_text
    assert "Layer=BottomOverlay" in bottom_text
    assert "Layer=TopLayer" not in bottom_text
    assert "Mirror=True" in bottom_text
