from __future__ import annotations

from pathlib import Path

from stockroom.projects.board_scene import parse_ipc2581_board_scene

IPC2581 = """\
<?xml version="1.0" encoding="UTF-8"?>
<IPC-2581 xmlns="http://webstds.ipc.org/2581" revision="C">
  <Content>
    <DictionaryStandard units="MILLIMETER">
      <EntryStandard id="PAD_0402">
        <RectRound width="0.6" height="0.5" radius="0.1"/>
      </EntryStandard>
    </DictionaryStandard>
  </Content>
  <Ecad name="Design">
    <CadData>
      <Step name="control">
        <Profile>
          <Polygon>
            <PolyBegin x="10" y="-20"/>
            <PolyStepSegment x="50" y="-20"/>
            <PolyStepSegment x="50" y="-80"/>
            <PolyStepSegment x="10" y="-80"/>
            <PolyStepSegment x="10" y="-20"/>
          </Polygon>
        </Profile>
        <Package name="R_0402">
          <Outline>
            <Polygon>
              <PolyBegin x="-0.5" y="-0.25"/>
              <PolyStepSegment x="0.5" y="-0.25"/>
              <PolyStepSegment x="0.5" y="0.25"/>
              <PolyStepSegment x="-0.5" y="0.25"/>
            </Polygon>
          </Outline>
        </Package>
        <Component
          refDes="R1"
          packageRef="R_0402"
          part="10k"
          layerRef="F.Cu"
          mountType="SMT"
        >
          <Xform rotation="90"/>
          <Location x="20" y="-30"/>
        </Component>
        <Component
          refDes="R2"
          packageRef="R_0402"
          part="10k"
          layerRef="B.Cu"
          mountType="SMT"
        >
          <Xform rotation="180" mirror="true"/>
          <Location x="40" y="-70"/>
        </Component>
        <LayerFeature layerRef="F.Cu">
          <Set net="GND">
            <Pad>
              <Location x="20" y="-30.4"/>
              <StandardPrimitiveRef id="PAD_0402"/>
              <PinRef componentRef="R1" pin="1"/>
            </Pad>
            <Features>
              <UserSpecial>
                <Line startX="20" startY="-30.4" endX="25" endY="-35">
                  <LineDesc lineWidth="0.2" lineEnd="ROUND"/>
                </Line>
              </UserSpecial>
            </Features>
          </Set>
        </LayerFeature>
        <LayerFeature layerRef="B.Cu">
          <Set net="VCC">
            <Pad>
              <Xform rotation="180"/>
              <Location x="40" y="-70.4"/>
              <StandardPrimitiveRef id="PAD_0402"/>
              <PinRef componentRef="R2" pin="2"/>
            </Pad>
          </Set>
        </LayerFeature>
        <LayerFeature layerRef="F.Cu_B.Cu">
          <Set geometry="PADSTACK_1" net="GND">
            <Hole
              name="H1"
              diameter="0.3"
              platingStatus="VIA"
              x="25"
              y="-35"
            />
          </Set>
        </LayerFeature>
      </Step>
    </CadData>
  </Ecad>
</IPC-2581>
"""


def test_ipc2581_scene_keeps_native_board_and_component_coordinates(tmp_path: Path):
    source = tmp_path / "control.xml"
    source.write_text(IPC2581, encoding="utf-8")

    scene = parse_ipc2581_board_scene(source, board="control.kicad_pcb")

    assert scene["schema_version"] == 1
    assert scene["source"]["format"] == "ipc-2581"
    assert scene["board"] == "control.kicad_pcb"
    assert scene["bounds"] == {
        "min_x": 10.0,
        "min_y": -80.0,
        "max_x": 50.0,
        "max_y": -20.0,
        "width": 40.0,
        "height": 60.0,
    }
    assert scene["components"] == [
        {
            "reference": "R1",
            "x_mm": 20.0,
            "y_mm": -30.0,
            "rotation_deg": 90.0,
            "side": "top",
            "package": "R_0402",
            "part": "10k",
            "bounds": {
                "min_x": -0.5,
                "min_y": -0.25,
                "max_x": 0.5,
                "max_y": 0.25,
                "width": 1.0,
                "height": 0.5,
            },
            "pins": [
                {
                    "number": "1",
                    "net": "GND",
                    "x_mm": 20.0,
                    "y_mm": -30.4,
                    "rotation_deg": 0.0,
                    "side": "top",
                    "layer": "F.Cu",
                    "shape": {
                        "kind": "rounded-rect",
                        "width_mm": 0.6,
                        "height_mm": 0.5,
                    },
                }
            ],
        },
        {
            "reference": "R2",
            "x_mm": 40.0,
            "y_mm": -70.0,
            "rotation_deg": 180.0,
            "side": "bottom",
            "package": "R_0402",
            "part": "10k",
            "bounds": {
                "min_x": -0.5,
                "min_y": -0.25,
                "max_x": 0.5,
                "max_y": 0.25,
                "width": 1.0,
                "height": 0.5,
            },
            "pins": [
                {
                    "number": "2",
                    "net": "VCC",
                    "x_mm": 40.0,
                    "y_mm": -70.4,
                    "rotation_deg": 180.0,
                    "side": "bottom",
                    "layer": "B.Cu",
                    "shape": {
                        "kind": "rounded-rect",
                        "width_mm": 0.6,
                        "height_mm": 0.5,
                    },
                }
            ],
        },
    ]
    assert scene["vias"] == [
        {
            "name": "H1",
            "net": "GND",
            "x_mm": 25.0,
            "y_mm": -35.0,
            "diameter_mm": 0.3,
            "from_layer": "",
            "to_layer": "",
            "sides": ["top", "bottom"],
        }
    ]
    assert scene["tracks"] == [
        {
            "net": "GND",
            "layer": "F.Cu",
            "side": "top",
            "start_x_mm": 20.0,
            "start_y_mm": -30.4,
            "end_x_mm": 25.0,
            "end_y_mm": -35.0,
            "width_mm": 0.2,
        }
    ]
    assert scene["summary"] == {
        "components": 2,
        "pins": 2,
        "vias": 1,
        "tracks": 1,
        "top": 1,
        "bottom": 1,
    }
    assert len(scene["source"]["sha256"]) == 64


def test_ipc2581_scene_normalizes_altium_layer_pads_to_the_same_pin_shape(tmp_path: Path):
    source = tmp_path / "control.cvg"
    source.write_text(
        """\
<IPC-2581 xmlns="http://webstds.ipc.org/2581" revision="B">
  <Content>
    <DictionaryStandard units="MILLIMETER">
      <EntryStandard id="RECTANGLE_1">
        <RectCenter width="0.7" height="0.4"/>
      </EntryStandard>
    </DictionaryStandard>
  </Content>
  <Ecad>
    <CadData>
      <Layer name="TopLayer" layerFunction="SIGNAL" side="TOP"/>
      <Layer name="BottomLayer" layerFunction="SIGNAL" side="BOTTOM"/>
      <Step name="control">
        <Profile>
          <Polygon>
            <PolyBegin x="0" y="0"/>
            <PolyStepSegment x="10" y="0"/>
            <PolyStepSegment x="10" y="10"/>
            <PolyStepSegment x="0" y="10"/>
          </Polygon>
        </Profile>
        <PadStack net="SCL">
          <LayerPad layerRef="TopSolder">
            <Location x="4" y="5"/>
            <StandardPrimitiveRef id="RECTANGLE_1"/>
            <PinRef componentRef="U1" pin="7"/>
          </LayerPad>
          <LayerPad layerRef="TopLayer">
            <Xform rotation="90"/>
            <Location x="4" y="5"/>
            <StandardPrimitiveRef id="RECTANGLE_1"/>
            <PinRef componentRef="U1" pin="7"/>
          </LayerPad>
        </PadStack>
        <PadStack net="No Net">
          <LayerPad layerRef="TopLayer">
            <Location x="4.5" y="5"/>
            <StandardPrimitiveRef id="RECTANGLE_1"/>
            <PinRef componentRef="U1" pin="8"/>
          </LayerPad>
        </PadStack>
        <PadStack net="SCL">
          <LayerHole
            name="Via_1"
            diameter="0.299999"
            platingStatus="VIA"
            x="6"
            y="7"
          >
            <Span fromLayer="TopLayer" toLayer="BottomLayer"/>
          </LayerHole>
        </PadStack>
        <LayerFeature layerRef="Drill Guide (TopLayer - BottomLayer)">
          <Set>
            <Hole
              name="Via Hole Drill 0"
              diameter="0.299999"
              platingStatus="VIA"
              x="6"
              y="7"
            />
          </Set>
        </LayerFeature>
        <LayerFeature layerRef="TopLayer">
          <Set net="SCL">
            <Features>
              <UserSpecial>
                <Line startX="4" startY="5" endX="6" endY="7">
                  <LineDesc lineWidth="0.254" lineEnd="ROUND"/>
                </Line>
              </UserSpecial>
            </Features>
          </Set>
          <Set net="No Net">
            <Features>
              <UserSpecial>
                <Line startX="1" startY="1" endX="2" endY="2">
                  <LineDesc lineWidth="0.254" lineEnd="ROUND"/>
                </Line>
              </UserSpecial>
            </Features>
          </Set>
        </LayerFeature>
        <Package name="QFN">
          <Outline>
            <Polygon>
              <PolyBegin x="-1" y="-1"/>
              <PolyStepSegment x="1" y="-1"/>
              <PolyStepSegment x="1" y="1"/>
              <PolyStepSegment x="-1" y="1"/>
            </Polygon>
          </Outline>
        </Package>
        <Component refDes="U1" packageRef="QFN" part="MCU" layerRef="TopLayer">
          <Location x="5" y="5"/>
        </Component>
      </Step>
    </CadData>
  </Ecad>
</IPC-2581>
""",
        encoding="utf-8",
    )

    scene = parse_ipc2581_board_scene(source, board="control.PcbDoc")

    assert scene["components"][0]["pins"] == [
        {
            "number": "7",
            "net": "SCL",
            "x_mm": 4.0,
            "y_mm": 5.0,
            "rotation_deg": 90.0,
            "side": "top",
            "layer": "TopLayer",
            "shape": {
                "kind": "rect",
                "width_mm": 0.7,
                "height_mm": 0.4,
            },
        },
        {
            "number": "8",
            "net": "",
            "x_mm": 4.5,
            "y_mm": 5.0,
            "rotation_deg": 0.0,
            "side": "top",
            "layer": "TopLayer",
            "shape": {
                "kind": "rect",
                "width_mm": 0.7,
                "height_mm": 0.4,
            },
        },
    ]
    assert scene["summary"]["pins"] == 2
    assert scene["vias"] == [
        {
            "name": "Via_1",
            "net": "SCL",
            "x_mm": 6.0,
            "y_mm": 7.0,
            "diameter_mm": 0.299999,
            "from_layer": "TopLayer",
            "to_layer": "BottomLayer",
            "sides": ["top", "bottom"],
        }
    ]
    assert scene["summary"]["vias"] == 1
    assert scene["tracks"] == [
        {
            "net": "SCL",
            "layer": "TopLayer",
            "side": "top",
            "start_x_mm": 4.0,
            "start_y_mm": 5.0,
            "end_x_mm": 6.0,
            "end_y_mm": 7.0,
            "width_mm": 0.254,
        }
    ]
    assert scene["summary"]["tracks"] == 1


def test_ipc2581_scene_rejects_a_profile_without_area(tmp_path: Path):
    source = tmp_path / "empty.xml"
    source.write_text(
        """<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Profile/></IPC-2581>""",
        encoding="utf-8",
    )

    try:
        parse_ipc2581_board_scene(source, board="empty.PcbDoc")
    except ValueError as exc:
        assert str(exc) == "IPC-2581 board profile has no usable area"
    else:
        raise AssertionError("dimensionless board scene was accepted")
