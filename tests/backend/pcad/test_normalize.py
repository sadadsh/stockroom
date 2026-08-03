from pathlib import Path

import pytest

from stockroom.pcad import PcadNormalizeError, normalize, parse_file, parse_text

SYNTHETIC = """ACCEL_ASCII "fixture.lia"
(asciiHeader (asciiVersion 3 0) (fileUnits Mil))
(library "Fixture"
  (padStyleDef "P1"
    (holeDiam 0)
    (padShape (layerNumRef 1) (padShapeType Rect) (shapeWidth 15) (shapeHeight 19))
    (padShape (layerType Plane) (padShapeType Thrm4_45)
      (outsideDiam 25) (insideDiam 20) (spokeWidth 5))
    (padShape (layerNumRef 2) (padShapeType Ellipse) (shapeWidth 0) (shapeHeight 0)))
  (padStyleDef "P2"
    (holeDiam 0)
    (padShape (layerNumRef 1) (padShapeType Rect) (shapeWidth 17) (shapeHeight 23)))
  (padStyleDef "P3"
    (holeDiam 0)
    (padShape (layerNumRef 1) (padShapeType Rect) (shapeWidth 13) (shapeHeight 15)))
  (textStyleDef "T"
    (font (fontType Stroke) (fontFamily SanSerif) (fontFace "QUALITY")
      (fontHeight 50) (strokeWidth 3)))
  (patternDef "DEFAULT"
    (originalName "DEFAULT")
    (multiLayer (pad (padNum 1) (padStyleRef "P1") (pt -11.6142 15.5) (rotation 180))
      (pickpoint (pt 0 0)))
    (layerContents (layerNumRef 92)
      (line (pt -1 -1) (pt 1 1) (width 1)))
    (layerContents (layerNumRef 94)
      (poly (pt 0 0) (pt 1 0) (pt 0 1) (width 1)))
    (layerContents (layerNumRef 96)
      (arc (pt 0 0) (radius 1) (startAngle 0) (sweepAngle 360) (width 1)))
    (layerContents (layerNumRef 98)
      (text (pt 0 0) "label" (textStyleRef "T") (justify CENTER)))
    (layerContents (layerNumRef 6)
      (attr "Height" "13" (pt 0 0) (textStyleRef "T"))))
  (patternDef "MEDIUM"
    (multiLayer (pad (padNum 1) (padStyleRef "P2") (pt 0 0))))
  (patternDef "LARGE"
    (multiLayer (pad (padNum 1) (padStyleRef "P3") (pt 0 0))))
  (symbolDef "SYM"
    (originalName "SYM")
    (pin (pinNum 1) (pt 300 -99.9999999999998) (rotation 180) (pinLength 300)
      (pinDisplay (dispPinDes True) (dispPinName False))
      (pinDes (text (pt 100 0) "1" (textStyleRef "T")))
      (pinName (text (pt 310 0) "P" (textStyleRef "T")))
      (defaultPinDes "1"))
    (line (pt 300 0) (pt 600 0))
    (attr "RefDes" "RefDes" (pt 0 0) (textStyleRef "T")))
  (compDef "SHORT"
    (compHeader (SourceLibrary "") (numPins 1) (numParts 1) (refDesPrefix "U"))
    (compPin "1" (pinName "P") (partNum 1) (symPinNum 1) (pinType Passive))
    (attachedSymbol (partNum 1) (altType Normal) (symbolName "SYM"))
    (attachedPattern (patternNum 1) (patternName "DEFAULT") (numPads 1)
      (padPinMap (PadNum 1) (CompPinRef "1")))
    (attr "Manufacturer_Name" "Maker" (pt 0 0) (textStyleRef "T"))
    (attr "Manufacturer_Part_Number" "EXACT-LONG-MPN" (pt 0 0) (textStyleRef "T"))))
"""


def test_normalizer_extracts_exact_identity_variants_and_integer_geometry():
    library = normalize(parse_text(SYNTHETIC))
    assert library.manufacturer == "Maker"
    assert library.mpn == "EXACT-LONG-MPN"
    assert library.default_footprint == "DEFAULT"
    assert [footprint.name for footprint in library.footprints] == [
        "DEFAULT",
        "MEDIUM",
        "LARGE",
    ]
    default_pad = library.footprints[0].pads[0]
    assert default_pad.position.x_nm == -295_001
    assert default_pad.position.y_nm == 393_700
    assert (default_pad.width_nm, default_pad.height_nm) == (381_000, 482_600)
    assert default_pad.rotation_udeg == 180_000_000
    pin = library.symbol.pins[0]
    assert pin.position.y_nm == -2_540_000
    assert pin.length_nm == 7_620_000
    assert pin.show_name is False
    assert pin.show_number is True
    assert library.pad_pin_map == (("1", "1"),)
    assert {graphic.kind for graphic in library.footprints[0].graphics} == {
        "line",
        "polygon",
        "arc",
        "text",
    }


def test_unresolved_electrical_style_fails_instead_of_dropping_pad():
    source = SYNTHETIC.replace('(padStyleRef "P1")', '(padStyleRef "MISSING")', 1)
    with pytest.raises(PcadNormalizeError, match="unresolved pad style"):
        normalize(parse_text(source))


def test_unsupported_symbol_geometry_fails_instead_of_being_ignored():
    source = SYNTHETIC.replace(
        "    (line (pt 300 0) (pt 600 0))",
        "    (bezier (pt 300 0) (pt 600 0))",
    )
    with pytest.raises(PcadNormalizeError, match="unsupported symbol geometry"):
        normalize(parse_text(source))


def test_incomplete_pad_pin_map_fails_closed():
    source = SYNTHETIC.replace("(numPads 1)", "(numPads 2)", 1)
    with pytest.raises(PcadNormalizeError, match="padPinMap does not match"):
        normalize(parse_text(source))


def test_unmapped_physical_thermal_via_pad_is_preserved():
    source = SYNTHETIC.replace(
        "      (pickpoint (pt 0 0)))",
        '      (pad (padNum 18) (padStyleRef "P1") (pt 0 0))\n'
        "      (pickpoint (pt 0 0)))",
    ).replace(
        '(multiLayer (pad (padNum 1) (padStyleRef "P2") (pt 0 0))))',
        '(multiLayer (pad (padNum 1) (padStyleRef "P2") (pt 0 0))\n'
        '      (pad (padNum 18) (padStyleRef "P2") (pt 0 0))))',
    ).replace(
        '(multiLayer (pad (padNum 1) (padStyleRef "P3") (pt 0 0))))',
        '(multiLayer (pad (padNum 1) (padStyleRef "P3") (pt 0 0))\n'
        '      (pad (padNum 18) (padStyleRef "P3") (pt 0 0))))',
    )

    library = normalize(parse_text(source))

    assert [pad.number for pad in library.footprints[0].pads] == ["1", "18"]
    assert library.pad_pin_map == (("1", "1"),)


def test_real_abm13w_library_extracts_all_native_inputs_when_fixture_is_present():
    path = (
        Path(__file__).parents[3]
        / "work"
        / "Real ABM13W P-CAD Qualification"
        / "AltiumV15"
        / "2026-07-27_20-09-29.lia"
    )
    if not path.exists():
        pytest.skip("local qualification capture is not present")

    library = normalize(parse_file(path))
    assert library.manufacturer == "Abracon"
    assert library.mpn == "ABM13W-32.0000MHZ-5-DH7G-T5"
    assert library.reference_prefix == "XTAL"
    assert library.default_footprint == "ABM13W_ABR"
    assert [footprint.name for footprint in library.footprints] == [
        "ABM13W_ABR",
        "ABM13W_ABR-M",
        "ABM13W_ABR-L",
    ]
    assert len(library.symbol.pins) == 4
    assert library.pad_pin_map == (("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"))
    assert all(len(footprint.pads) == 4 for footprint in library.footprints)
    assert [
        (footprint.pads[0].width_nm, footprint.pads[0].height_nm)
        for footprint in library.footprints
    ] == [(381_000, 482_600), (431_800, 584_200), (330_200, 381_000)]
    first = library.footprints[0].pads[0]
    assert (first.position.x_nm, first.position.y_nm) == (-295_001, 393_700)
