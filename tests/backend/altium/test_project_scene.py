from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from stockroom.altium.project_scene import export_altium_board_scenes
from stockroom.model.project import ProjectRecord

IPC2581 = """\
<IPC-2581 xmlns="http://webstds.ipc.org/2581">
  <Profile><Polygon>
    <PolyBegin x="100" y="100"/>
    <PolyStepSegment x="130" y="100"/>
    <PolyStepSegment x="130" y="126"/>
    <PolyStepSegment x="100" y="126"/>
  </Polygon></Profile>
  <Package name="R"><Outline><Polygon>
    <PolyBegin x="-0.5" y="-0.25"/>
    <PolyStepSegment x="0.5" y="0.25"/>
  </Polygon></Outline></Package>
  <Component refDes="R1" packageRef="R" layerRef="TopLayer">
    <Location x="120" y="110"/>
  </Component>
</IPC-2581>
"""


class _Driver:
    installed = True
    x2 = Path("C:/Program Files/Altium/AD26/X2.EXE")

    def run_script(self, *, project, proc, marker, timeout):
        assert project.suffix == ".PrjScr"
        assert proc.endswith(">ExportStockroomBoardScenes")
        assert timeout == 42
        source = project.with_name("StockroomBoardScenes.pas").read_text(encoding="utf-8")
        marker.write_text(
            "BOARD|Control.PcbDoc|completed|native IPC-2581 generation returned\n"
            "STATUS|completed|native board scenes returned\n",
            encoding="utf-8",
        )
        output_match = next(
            line for line in source.splitlines() if line.strip().startswith("{OUTPUT|")
        )
        output = Path(output_match.strip()[8:-1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "Control.cvg").write_text(IPC2581, encoding="utf-8")
        return SimpleNamespace(ok=True, detail="marker written", marker_text=marker.read_text())


def test_altium_scene_export_uses_native_outjob_and_shared_ipc_contract(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "Control.PcbDoc").write_bytes(b"native-board")
    (root / "Control.PrjPcb").write_text(
        "[Design]\n[Document1]\nDocumentPath=Control.PcbDoc\n",
        encoding="utf-8",
    )
    template = tmp_path / "Fabrication.OutJob"
    template.write_text(
        """\
[OutputGroup1]
TargetOutputMedium=Fabrication
OutputMedium3=Fabrication
OutputType3=IPC2581
OutputDocumentPath3=
OutputEnabled3=1
OutputEnabled3_OutputMedium3=4
Configuration3_Item1=Record=IPC2581View|IPC2581Version=B|MeasurementSystem=Metric
[PublishSettings]
OutputFilePath3=old
ReleaseManaged3=1
OutputBasePath3=old
[GeneratedFilesSettings]
RelativeOutputPath3=old
OpenOutputs3=1
AddToProject3=1
TimestampFolder3=1
UseOutputName3=1
OpenIPCOutput3=1
""",
        encoding="latin-1",
    )
    project = ProjectRecord(
        id="control",
        name="Control",
        root=root.as_posix(),
        pro_path="Control.PrjPcb",
        board_paths=["Control.PcbDoc"],
        sheet_paths=[],
    )
    before = (root / "Control.PcbDoc").read_bytes()

    result = export_altium_board_scenes(
        project,
        _Driver(),
        template=template,
        timeout=42,
    )

    assert result["status"] == "ready"
    assert result["source"]["preserved"] is True
    assert (root / "Control.PcbDoc").read_bytes() == before
    scene = result["scenes"]["Control.PcbDoc"]
    assert scene["bounds"]["width"] == 30.0
    assert scene["components"][0]["reference"] == "R1"
    assert result["runtime"] == {"name": "Altium Designer", "version": "AD26"}
