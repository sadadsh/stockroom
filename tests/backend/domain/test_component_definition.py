from dataclasses import asdict

from stockroom.domain.component_definition import (
    PointNm,
    build_ic51_0484_806_definition,
)


def test_ic51_definition_is_exact_fixed_point_and_blocked():
    definition = build_ic51_0484_806_definition()

    assert asdict(definition.identity) == {
        "manufacturer": "Yamaichi Electronics",
        "mpn": "IC51-0484-806",
        "symbol_name": "IC51-0484-806",
        "footprint_name": "IC51-0484-806",
        "reference_prefix": "J",
    }
    assert (definition.body.width_nm, definition.body.depth_nm) == (
        29_000_000,
        32_000_000,
    )
    assert definition.body.height_nm is None
    assert definition.model is None
    assert definition.geometry_unit == "nm"
    assert definition.production_ready is False

    assert tuple(terminal.number for terminal in definition.terminals) == tuple(
        str(number) for number in range(1, 49)
    )
    assert {terminal.electrical_type for terminal in definition.terminals} == {"passive"}
    assert {terminal.drill_diameter_nm for terminal in definition.terminals} == {800_000}
    assert {terminal.land_diameter_nm for terminal in definition.terminals} == {1_200_000}
    assert tuple(hole.center for hole in definition.mounting_holes) == (
        PointNm(-10_080_000, -9_500_000),
        PointNm(10_080_000, -9_500_000),
        PointNm(10_080_000, 9_500_000),
        PointNm(-10_080_000, 9_500_000),
    )
    assert {hole.drill_diameter_nm for hole in definition.mounting_holes} == {3_200_000}

    claims = {claim.key: claim for claim in definition.provenance}
    assert claims["contact_geometry"].basis == "documented"
    assert claims["radial_rows"].basis == "derived"
    assert claims["terminal_mapping"].basis == "derived"
    assert "not directly confirmed" in claims["terminal_mapping"].note
    assert claims["copper_land_od"].basis == "policy"
    assert claims["exact_part_3d"].value == "model=None; body height=None"
    assert {blocker.code for blocker in definition.blockers} == {
        "terminal-map-not-exact-part-confirmed",
        "policy-derived-copper-land",
        "missing-exact-part-3d-and-height",
    }


def test_ic51_top_view_counterclockwise_mapping_has_exact_centers():
    definition = build_ic51_0484_806_definition()

    expected_centers = (
        PointNm(-5_000_000, -2_750_000),
        PointNm(-6_270_000, -2_250_000),
        PointNm(-7_540_000, -1_750_000),
        PointNm(-5_000_000, -1_250_000),
        PointNm(-6_270_000, -750_000),
        PointNm(-7_540_000, -250_000),
        PointNm(-5_000_000, 250_000),
        PointNm(-6_270_000, 750_000),
        PointNm(-7_540_000, 1_250_000),
        PointNm(-5_000_000, 1_750_000),
        PointNm(-6_270_000, 2_250_000),
        PointNm(-7_540_000, 2_750_000),
        PointNm(-2_750_000, 5_000_000),
        PointNm(-2_250_000, 6_270_000),
        PointNm(-1_750_000, 7_540_000),
        PointNm(-1_250_000, 5_000_000),
        PointNm(-750_000, 6_270_000),
        PointNm(-250_000, 7_540_000),
        PointNm(250_000, 5_000_000),
        PointNm(750_000, 6_270_000),
        PointNm(1_250_000, 7_540_000),
        PointNm(1_750_000, 5_000_000),
        PointNm(2_250_000, 6_270_000),
        PointNm(2_750_000, 7_540_000),
        PointNm(5_000_000, 2_750_000),
        PointNm(6_270_000, 2_250_000),
        PointNm(7_540_000, 1_750_000),
        PointNm(5_000_000, 1_250_000),
        PointNm(6_270_000, 750_000),
        PointNm(7_540_000, 250_000),
        PointNm(5_000_000, -250_000),
        PointNm(6_270_000, -750_000),
        PointNm(7_540_000, -1_250_000),
        PointNm(5_000_000, -1_750_000),
        PointNm(6_270_000, -2_250_000),
        PointNm(7_540_000, -2_750_000),
        PointNm(2_750_000, -5_000_000),
        PointNm(2_250_000, -6_270_000),
        PointNm(1_750_000, -7_540_000),
        PointNm(1_250_000, -5_000_000),
        PointNm(750_000, -6_270_000),
        PointNm(250_000, -7_540_000),
        PointNm(-250_000, -5_000_000),
        PointNm(-750_000, -6_270_000),
        PointNm(-1_250_000, -7_540_000),
        PointNm(-1_750_000, -5_000_000),
        PointNm(-2_250_000, -6_270_000),
        PointNm(-2_750_000, -7_540_000),
    )
    assert tuple(terminal.center for terminal in definition.terminals) == expected_centers
    assert tuple(terminal.side for terminal in definition.terminals) == (
        ("left",) * 12 + ("bottom",) * 12 + ("right",) * 12 + ("top",) * 12
    )


def test_ic51_canonical_bytes_and_digest_are_stable():
    first = build_ic51_0484_806_definition()
    second = build_ic51_0484_806_definition()

    assert first.canonical_bytes() == second.canonical_bytes()
    assert (
        first.canonical_digest()
        == "sha256:e60d6974feae4b74288ff9280eb8bb61763750bab9992ea87a612adddd38b3c2"
    )
