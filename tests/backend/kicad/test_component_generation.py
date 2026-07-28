import pytest

from stockroom.domain.component_definition import (
    PointNm,
    build_ic51_0484_806_definition,
)
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.component_generation import (
    KiCadGenerationError,
    generate_kicad_component,
    readback_kicad_component,
    verify_kicad_readback,
)


def test_ic51_generation_has_stable_bytes_digests_and_explicit_blockers():
    definition = build_ic51_0484_806_definition()
    first = generate_kicad_component(definition)
    second = generate_kicad_component(definition)

    assert first.symbol.file_name == "IC51-0484-806.kicad_sym"
    assert first.footprint.file_name == "IC51-0484-806.kicad_mod"
    assert first.symbol.content == second.symbol.content
    assert first.footprint.content == second.footprint.content
    assert (
        first.symbol.digest
        == "sha256:58d278a5a94193f52d44d6967311b925406f04bd3e20b7000809c369e6ce2630"
    )
    assert (
        first.footprint.digest
        == "sha256:c911530c748d0b106bab9e9119c730b63bf64fd1f690e551418f4f32bb928cc3"
    )
    assert first.definition_digest == definition.canonical_digest()
    assert first.production_ready is False
    assert first.blockers == definition.blockers
    assert b"(model " not in first.footprint.content


def test_repository_parser_readback_proves_identity_pins_pads_holes_and_no_model():
    definition = build_ic51_0484_806_definition()
    generated = generate_kicad_component(definition)
    observed = readback_kicad_component(
        generated.symbol.content,
        generated.footprint.content,
    )

    assert (
        observed.manufacturer,
        observed.mpn,
        observed.symbol_name,
        observed.symbol_value,
        observed.footprint_reference,
        observed.footprint_name,
    ) == (
        "Yamaichi Electronics",
        "IC51-0484-806",
        "IC51-0484-806",
        "IC51-0484-806",
        "Stockroom:IC51-0484-806",
        "IC51-0484-806",
    )
    assert observed.pin_numbers == tuple(str(number) for number in range(1, 49))
    assert observed.pad_numbers == tuple(str(number) for number in range(1, 49))
    assert {pin.electrical_type for pin in observed.pins} == {"passive"}
    assert tuple(pad.center for pad in observed.plated_pads) == tuple(
        terminal.center for terminal in definition.terminals
    )
    assert {pad.drill_diameter_nm for pad in observed.plated_pads} == {800_000}
    assert {(pad.size_x_nm, pad.size_y_nm) for pad in observed.plated_pads} == {
        (1_200_000, 1_200_000)
    }
    assert {pad.pad_type for pad in observed.plated_pads} == {"thru_hole"}
    assert tuple(hole.center for hole in observed.mounting_holes) == (
        PointNm(-10_080_000, -9_500_000),
        PointNm(10_080_000, -9_500_000),
        PointNm(10_080_000, 9_500_000),
        PointNm(-10_080_000, 9_500_000),
    )
    assert {hole.drill_diameter_nm for hole in observed.mounting_holes} == {3_200_000}
    assert {hole.pad_type for hole in observed.mounting_holes} == {"np_thru_hole"}
    assert observed.model_path is None
    verify_kicad_readback(definition, observed)


def test_semantic_readback_fails_closed_on_pad_center_tampering():
    definition = build_ic51_0484_806_definition()
    generated = generate_kicad_component(definition)
    tampered = generated.footprint.content.replace(
        b'(pad "1" thru_hole circle (at -5 -2.75)',
        b'(pad "1" thru_hole circle (at -5.01 -2.75)',
        1,
    )
    assert tampered != generated.footprint.content

    observed = readback_kicad_component(generated.symbol.content, tampered)
    with pytest.raises(KiCadGenerationError, match="PTH pad numbers, centers"):
        verify_kicad_readback(definition, observed)


def test_repository_parser_rejects_an_unqualified_model_link():
    definition = build_ic51_0484_806_definition()
    generated = generate_kicad_component(definition)
    tampered = generated.footprint.content.replace(
        b")\n",
        b'\t(model "unqualified.step")\n)\n',
        1,
    )

    with pytest.raises(KiCadGenerationError, match="unexpectedly contains a 3D model"):
        readback_kicad_component(generated.symbol.content, tampered)


@pytest.mark.skipif(
    not KiCadCli().available,
    reason="kicad-cli unavailable through Stockroom discovery",
)
def test_kicad_10_natively_parses_and_exports_generated_libraries(tmp_path):
    generated = generate_kicad_component(build_ic51_0484_806_definition())
    symbol_path = tmp_path / generated.symbol.file_name
    symbol_path.write_bytes(generated.symbol.content)
    pretty = tmp_path / "Stockroom.pretty"
    pretty.mkdir()
    footprint_path = pretty / generated.footprint.file_name
    footprint_path.write_bytes(generated.footprint.content)

    cli = KiCadCli()
    symbol_svgs = cli.sym_export_svg(
        symbol_path,
        "IC51-0484-806",
        tmp_path / "symbol-svg",
    )
    footprint_svg = cli.fp_export_svg(
        pretty,
        "IC51-0484-806",
        tmp_path / "footprint-svg",
    )

    assert symbol_svgs and all(path.stat().st_size > 0 for path in symbol_svgs)
    assert footprint_svg.stat().st_size > 0
