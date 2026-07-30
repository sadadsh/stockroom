from pathlib import Path

from PIL import Image, ImageDraw

from stockroom.altium.project_visuals import (
    _configure_pcb_outjob,
    _configure_schematic_outjob,
    _crop_board_page,
    _render_script,
    render_altium_project,
)
from stockroom.model.project import ProjectRecord


class _InstalledDriver:
    installed = True
    x2 = Path("C:/Program Files/Altium/AD26/X2.EXE")


def test_native_board_raster_discards_pdf_paper_before_scene_overlay():
    page = Image.new("RGB", (120, 90), "white")
    ImageDraw.Draw(page).rectangle((10, 8, 109, 81), fill="#202020")

    cropped = _crop_board_page(page)

    assert cropped.size == (100, 74)
    assert cropped.mode == "RGBA"
    cropped.close()


def test_native_board_raster_keeps_edge_touching_artwork_and_clears_only_paper():
    page = Image.new("RGB", (160, 120), "white")
    draw = ImageDraw.Draw(page)
    draw.polygon(
        (
            (20, 10),
            (139, 10),
            (139, 109),
            (80, 109),
            (80, 70),
            (20, 70),
        ),
        fill="#202020",
    )
    draw.rectangle((100, 40, 106, 109), fill="white")
    draw.rectangle((110, 30, 116, 36), fill="#c83434")

    cropped = _crop_board_page(page)

    # The board's dark extent is the crop boundary. The large lower-left
    # exterior notch becomes transparent while a white copper feature that
    # reaches the lower board edge remains visible.
    assert cropped.size == (120, 100)
    assert cropped.getpixel((10, 90))[3] == 0
    assert cropped.getpixel((83, 90)) == (255, 255, 255, 255)
    assert cropped.getpixel((93, 23)) == (200, 52, 52, 255)
    cropped.close()


def test_visual_script_uses_the_supported_parameterized_process_api(tmp_path: Path):
    script = _render_script(
        descriptor=tmp_path / "Demo.PrjPcb",
        jobs=[
            (
                tmp_path / "Demo.OutJob",
                "PDF",
                "PCB",
                tmp_path / "Demo.PcbDoc",
                tmp_path / "Demo.pdf",
            )
        ],
        marker=tmp_path / "result.txt",
    )

    assert "RunCommand" not in script
    assert "AddStringParameter('Action', 'PublishToPDF');" in script
    assert "AddStringParameter('DisableDialog', 'True');" in script
    assert "RunProcess('WorkspaceManager:Print');" in script


def test_altium_visuals_can_fail_closed_when_native_publish_is_disabled(
    tmp_path: Path,
):
    project = ProjectRecord(
        id="demo",
        name="Demo",
        root=tmp_path.as_posix(),
        eda="altium",
        sheet_paths=["Demo.SchDoc"],
    )

    bundle = render_altium_project(
        project,
        _InstalledDriver(),
        allow_unqualified_pdf_publish=False,
    )

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
                "OutputBasePath2=old-output",
                "OutputFileName2=old.pdf",
                "OutputFileNameMulti2=",
                "UseOutputNameForMulti2=1",
                "PublishMethod2=0",
                "RelativeOutputPath2=old.pdf",
                "OpenOutput2=1",
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
    assert f"OutputBasePath2={pdf.parent}" in configured
    assert "OutputFileNameMulti2=review.pdf" in configured
    assert "UseOutputNameForMulti2=0" in configured
    assert "PublishMethod2=1" in configured
    assert "OpenOutput2=0" in configured
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
                "OutputBasePath2=old-output",
                "OutputFileName2=old.pdf",
                "OutputFileNameMulti2=",
                "UseOutputNameForMulti2=1",
                "PublishMethod2=0",
                "RelativeOutputPath2=old.pdf",
                "OpenOutput2=1",
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
