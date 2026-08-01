from __future__ import annotations

from types import SimpleNamespace

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.model.project import ProjectRecord
from stockroom.projects.placement_geometry import (
    altium_board_geometry,
    kicad_board_geometry,
    parse_altium_position_csv,
    parse_kicad_position_csv,
)


def _project(root, *, eda: str, board: str) -> ProjectRecord:
    return ProjectRecord(
        id=f"{eda}-board",
        name="Board",
        root=str(root),
        pro_path="",
        board_paths=[board],
        sheet_paths=[],
        eda=eda,
    )


def test_kicad_and_altium_parsers_return_the_same_placement_shape():
    kicad = parse_kicad_position_csv(
        (
            '"Ref","Val","Package","PosX","PosY","Rot","Side"\n'
            '"R1","10k","R_0402","10.25","20.5","90","top"\n'
        ),
        "Board",
    )
    altium = parse_altium_position_csv(
        (
            '"Center-X","Center-Y","Designator","Footprint","Layer","Rotation"\n'
            '"10.25","20.5","R1","R_0402","TopLayer","90"\n'
        ),
        "Board",
    )

    assert kicad == altium == [
        {
            "reference": "R1",
            "board": "Board",
            "x_mm": 10.25,
            "y_mm": 20.5,
            "rotation_deg": 90.0,
            "side": "top",
            "footprint": "R_0402",
        }
    ]
    assert set(kicad[0]) == set(altium[0])


@pytest.mark.serial_only
def test_kicad_geometry_uses_native_metric_csv_and_preserves_the_board(tmp_path):
    board = tmp_path / "Board.kicad_pcb"
    board.write_text(
        """
(kicad_pcb
  (version 20240108)
  (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (footprint "Resistor_SMD:R_0402_1005Metric"
    (layer "F.Cu")
    (at 10.25 20.5 90)
    (property "Reference" "R1" (at 0 -1.17 90) (layer "F.SilkS"))
    (property "Value" "10k" (at 0 1.17 90) (layer "F.Fab"))
  )
)
""".strip(),
        encoding="utf-8",
    )
    before = board.read_bytes()

    result = kicad_board_geometry(
        _project(tmp_path, eda="kicad", board=board.name),
        KiCadCli(),
    )

    assert result["status"] == "ready"
    assert result["adapter"] == "kicad"
    assert result["placements"][0]["reference"] == "R1"
    assert result["placements"][0]["x_mm"] == 10.25
    assert result["placements"][0]["side"] == "top"
    assert board.read_bytes() == before


def test_altium_geometry_runs_against_a_copy_and_preserves_the_board(tmp_path):
    board = tmp_path / "Board.PcbDoc"
    board.write_bytes(b"native-altium-board")
    before = board.read_bytes()

    class Driver:
        installed = True
        x2 = tmp_path / "AD26" / "X2.EXE"

        def run_script(self, *, marker, **_kwargs):
            output = marker.parent / "project" / "Stockroom Placement Output" / "1"
            output.mkdir(parents=True, exist_ok=True)
            (output / "Pick Place for Board.csv").write_text(
                '"Center-X","Center-Y","Designator","Footprint","Layer","Rotation"\n'
                '"10.25","20.5","R1","R_0402","TopLayer","90"\n',
                encoding="utf-8",
            )
            marker.write_text(
                "\n".join(
                    [
                        "BOARD|Board.PcbDoc",
                        "STATUS|completed|native placement export returned",
                    ]
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(ok=True, detail="marker written")

    template = tmp_path / "Assembly.OutJob"
    template.write_text(
        """
[OutputJobFile]
[OutputGroup1]
TargetOutputMedium=AssemblyData
OutputMedium3=AssemblyData
OutputMedium3_Type=GeneratedFiles
OutputType2=Pick Place
OutputDocumentPath2=
OutputEnabled2=1
OutputEnabled2_OutputMedium3=1
Configuration2_Item1=Record=PickPlaceView|Units=Imperial|GenerateCSVFormat=False|GenerateTextFormat=True|ShowUnits=False
[GeneratedFilesSettings]
RelativeOutputPath3=
OpenOutputs3=0
AddToProject3=0
TimestampFolder3=0
UseOutputName3=0
""".strip(),
        encoding="latin-1",
    )
    result = altium_board_geometry(
        _project(tmp_path, eda="altium", board=board.name),
        Driver(),
        template=template,
    )

    assert result["status"] == "ready"
    assert result["adapter"] == "altium"
    assert result["placements"][0]["reference"] == "R1"
    assert result["placements"][0]["x_mm"] == 10.25
    assert result["placements"][0]["side"] == "top"
    assert result["source"]["preserved"] is True
    assert board.read_bytes() == before
