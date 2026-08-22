import re
from pathlib import Path

import pytest
from test_normalize import SYNTHETIC

from stockroom.pcad import normalize, parse_text
from stockroom.pcad.altium_request import build_altium_writer_request


def test_request_preserves_identity_variants_pins_and_semantic_layers(tmp_path: Path):
    library = normalize(parse_text(SYNTHETIC))

    request = build_altium_writer_request(library, output_directory=tmp_path / "output")

    assert request["mpn"] == "EXACT-LONG-MPN"
    assert request["outputStem"] == "exact-long-mpn-5c56"
    assert request["symbol"]["name"] == "EXACT-LONG-MPN"
    assert request["symbol"]["partCount"] == 1
    assert all(pin["ownerPartId"] == 1 for pin in request["symbol"]["pins"])
    for primitive_kind in ("lines", "rectangles", "polylines", "arcs", "ellipses", "labels"):
        assert all(
            primitive["ownerPartId"] == 1
            for primitive in request["symbol"][primitive_kind]
        )
    assert request["defaultFootprint"] == "DEFAULT"
    assert request["padPinMap"] == [{"pad": "1", "pin": "1"}]
    assert request["symbol"]["pins"][0]["orientation"] == "left"
    assert request["symbol"]["parameters"][-1] == {
        "name": "Footprint",
        "value": "DEFAULT",
        "visible": False,
    }
    assert [item["name"] for item in request["footprints"]] == [
        "DEFAULT",
        "MEDIUM",
        "LARGE",
    ]
    default = request["footprints"][0]
    assert default["pads"][0]["sizeXmm"] == 0.381
    assert {item["layer"] for item in default["lines"]} == {71}
    assert default["arcs"] == []
    assert default["texts"] == []  # layer 98 is the provider worksheet, not part geometry


def test_request_keeps_exact_punctuated_mpn_out_of_the_output_filename(tmp_path: Path):
    source = SYNTHETIC.replace("EXACT-LONG-MPN", "MAX17608ATC+")
    library = normalize(parse_text(source))

    request = build_altium_writer_request(library, output_directory=tmp_path / "output")

    assert request["mpn"] == "MAX17608ATC+"
    assert request["symbol"]["name"] == "MAX17608ATC+"
    assert request["outputStem"] == "max17608atc-373c"
    assert len(request["outputStem"]) <= 100
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", request["outputStem"])


def test_request_links_same_step_to_every_variant_with_one_stable_model_id(tmp_path: Path):
    step = tmp_path / "Part.step"
    step.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    library = normalize(parse_text(SYNTHETIC))

    request = build_altium_writer_request(
        library,
        output_directory=tmp_path / "output",
        step_model=step,
    )

    models = [item["model"] for item in request["footprints"]]
    assert len({item["id"] for item in models}) == 1
    assert re.fullmatch(
        r"\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}",
        models[0]["id"],
    )
    assert all(item["path"] == str(step.resolve()) for item in models)
    assert all(len(item["bodyOutline"]) >= 3 for item in models)
    assert all(item["rotationX"] == 90 for item in models)


def test_ul_top_mask_and_paste_rectangles_become_native_fills(tmp_path: Path):
    source = SYNTHETIC.replace(
        "    (layerContents (layerNumRef 92)",
        "    (layerContents (layerNumRef 4)\n"
        "      (poly (pt -2 -1) (pt -2 1) (pt 2 1) (pt 2 -1)))\n"
        "    (layerContents (layerNumRef 8)\n"
        "      (poly (pt -1 -0.5) (pt -1 0.5) (pt 1 0.5) (pt 1 -0.5)))\n"
        "    (layerContents (layerNumRef 92)",
    )
    library = normalize(parse_text(source))

    request = build_altium_writer_request(library, output_directory=tmp_path / "output")

    fills = request["footprints"][0]["fills"]
    assert {item["layer"] for item in fills} == {35, 37}
    assert all(item["rotation"] == 0 for item in fills)


def test_real_request_has_four_pads_and_embedded_model_for_all_variants(tmp_path: Path):
    root = Path(__file__).parents[3] / "work" / "Real ABM13W P-CAD Qualification"
    lia = root / "AltiumV15" / "2026-07-27_20-09-29.lia"
    step = root / "Unified Source" / "ABM13W_ABR.step"
    if not lia.exists() or not step.exists():
        return

    from stockroom.pcad import parse_file

    request = build_altium_writer_request(
        normalize(parse_file(lia)),
        output_directory=tmp_path / "output",
        step_model=step,
    )

    assert len(request["footprints"]) == 3
    assert all(len(item["pads"]) == 4 for item in request["footprints"])
    assert all(item["model"]["name"] == "ABM13W_ABR.step" for item in request["footprints"])
    assert request["symbol"]["name"] == "ABM13W-32.0000MHZ-5-DH7G-T5"
    # P-CAD stores each pin at the symbol-body end. Altium's orientation points
    # from there to the electrical tip, so the 300 mil pins land at the exact
    # same 0/1600 mil electrical endpoints as the provider's KiCad symbol.
    by_designator = {
        item["designator"]: item for item in request["symbol"]["pins"]
    }
    assert by_designator["1"]["orientation"] == "left"
    assert by_designator["1"]["xmm"] - by_designator["1"]["lengthMm"] == pytest.approx(0.0)
    assert by_designator["4"]["orientation"] == "right"
    assert by_designator["4"]["xmm"] + by_designator["4"]["lengthMm"] == pytest.approx(40.64)
