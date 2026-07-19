"""Parametric facets: the modular Mouser-style search needs the filter dimensions
GENERATED from the parts' free-form spec bags, not hardcoded per category. These tests
build a tiny library (two resistors + one capacitor, each with a real spec bag) and
assert GET /api/library/facets/parametric aggregates each spec key into an options or a
range facet, that ?category scopes the aggregation, and that a brand-new spec key yields
a facet with zero code change (the whole point)."""

from __future__ import annotations

import pytest


def _write_spec_part(parts_dir, part_id, category, specs):
    from stockroom.model.part import PartRecord

    rec = PartRecord(
        id=part_id,
        display_name=part_id.upper(),
        category=category,
        specs=dict(specs),
    )
    (parts_dir / f"{part_id}.json").write_text(rec.dumps(), encoding="utf-8")


@pytest.fixture
def spec_client(tmp_path):
    """A library with parametric spec bags across two categories, served through the
    real API app so the endpoint is exercised end to end (index scoping + record load)."""
    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app
    from stockroom.api.context import build_context
    from stockroom.store.machine_config import MachineConfig
    from stockroom.store.profile import ProfileStore
    from stockroom.vcs.repo import GitRepo

    root = tmp_path / "libraries"
    root.mkdir()
    repo = GitRepo(root)
    repo.init()
    profile = ProfileStore(root, repo).create("Main")
    parts = profile.library.parts_dir
    parts.mkdir(parents=True, exist_ok=True)

    _write_spec_part(parts, "r1", "Resistors",
                     {"Resistance": "10 kΩ", "Tolerance": "1%", "Power": "0.25 W"})
    _write_spec_part(parts, "r2", "Resistors",
                     {"Resistance": "1 kΩ", "Tolerance": "5%", "Power": "0.25 W"})
    _write_spec_part(parts, "c1", "Capacitors",
                     {"Capacitance": "100 nF", "Voltage": "50 V", "Dielectric": "X7R"})
    repo.commit("seed parametric fixture parts", [root])

    kicad_dir = tmp_path / "kicad"
    kicad_dir.mkdir()
    config = MachineConfig(active_profile="Main")
    ctx = build_context(root, kicad_dir=kicad_dir, config=config, token="testtoken")
    app = create_app(ctx)
    with TestClient(app, base_url="http://test", raise_server_exceptions=False,
                    headers={"X-Stockroom-Token": "testtoken"}) as c:
        yield c


def _facets_by_key(body):
    return {f["key"]: f for f in body["facets"]}


def test_parametric_facets_cover_every_spec_key(spec_client):
    r = spec_client.get("/api/library/facets/parametric")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["category"] is None
    facets = _facets_by_key(body)
    # every spec key present across the library becomes a facet, no key list hardcoded
    assert set(facets) == {"Resistance", "Tolerance", "Power",
                           "Capacitance", "Voltage", "Dielectric"}


def test_numeric_spec_becomes_a_range_with_unit(spec_client):
    facets = _facets_by_key(spec_client.get("/api/library/facets/parametric").json())
    res = facets["Resistance"]
    assert res["kind"] == "range"
    assert res["label"] == "Resistance"
    assert res["count"] == 2
    # SI prefixes are normalized so 1 kΩ < 10 kΩ orders correctly
    assert res["min"] == 1000.0
    assert res["max"] == 10000.0
    assert res["unit"] == "Ω"
    # a percent unit and a sub-unit prefix parse just as cleanly
    assert facets["Tolerance"]["kind"] == "range"
    assert facets["Tolerance"]["min"] == 1.0
    assert facets["Tolerance"]["max"] == 5.0
    assert facets["Tolerance"]["unit"] == "%"
    cap = facets["Capacitance"]
    assert cap["kind"] == "range"
    assert cap["min"] == pytest.approx(100e-9)
    assert cap["unit"] == "F"


def test_discrete_spec_becomes_options_with_counts(spec_client):
    facets = _facets_by_key(spec_client.get("/api/library/facets/parametric").json())
    diel = facets["Dielectric"]
    assert diel["kind"] == "options"
    assert diel["count"] == 1
    assert diel["options"] == [{"value": "X7R", "count": 1}]
    # a value shared by both resistors reports a count of 2, most-common first
    power = facets["Power"]
    if power["kind"] == "options":
        assert power["options"][0] == {"value": "0.25 W", "count": 2}


def test_package_codes_are_options_not_a_numeric_range(spec_client, tmp_path):
    # "0402"/"0603" parse as 402/603 but are CODES, not magnitudes (leading zero) - so a Package
    # spec must aggregate as discrete options, never a nonsensical 402..603 range slider.
    import json

    parts = tmp_path / "libraries" / "Main" / "parts"
    for pid, case in (("r1", "0603"), ("r2", "0402")):
        rec = json.loads((parts / f"{pid}.json").read_text(encoding="utf-8"))
        rec["specs"]["Package"] = case
        (parts / f"{pid}.json").write_text(json.dumps(rec), encoding="utf-8")

    facets = _facets_by_key(spec_client.get("/api/library/facets/parametric").json())
    pkg = facets["Package"]
    assert pkg["kind"] == "options"
    assert {o["value"] for o in pkg["options"]} == {"0603", "0402"}


def test_category_filter_scopes_the_aggregation(spec_client):
    r = spec_client.get("/api/library/facets/parametric", params={"category": "Resistors"})
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "Resistors"
    assert body["total"] == 2
    facets = _facets_by_key(body)
    # only resistor spec keys, none of the capacitor's
    assert "Resistance" in facets
    assert "Capacitance" not in facets
    assert "Voltage" not in facets


def test_a_brand_new_spec_key_yields_a_facet_with_no_code_change(spec_client, tmp_path):
    # the whole point: a category can grow a never-seen spec key and it must surface as
    # a facet purely from the data. Add one to r1's record, rebuild the index, re-query.
    import json

    part = tmp_path / "libraries" / "Main" / "parts" / "r1.json"
    rec = json.loads(part.read_text(encoding="utf-8"))
    rec["specs"]["Whimsy Factor"] = "Sparkly"
    part.write_text(json.dumps(rec), encoding="utf-8")

    facets = _facets_by_key(spec_client.get("/api/library/facets/parametric").json())
    assert "Whimsy Factor" in facets
    assert facets["Whimsy Factor"]["kind"] == "options"
    assert facets["Whimsy Factor"]["options"] == [{"value": "Sparkly", "count": 1}]


def _part_ids(body):
    return {p["id"] for p in body["parts"]}


def test_spec_filter_options_narrows_the_parts_list(spec_client):
    # Dielectric:X7R is carried only by the capacitor
    r = spec_client.get("/api/library/parts", params={"spec": "Dielectric:X7R"})
    assert r.status_code == 200
    body = r.json()
    assert _part_ids(body) == {"c1"}
    assert body["count"] == 1


def test_spec_filter_range_narrows_by_normalized_magnitude(spec_client):
    # 5k..20k keeps r1 (10 kΩ), drops r2 (1 kΩ); SI prefixes normalized like the facet
    r = spec_client.get(
        "/api/library/parts",
        params={"category": "Resistors", "spec": "Resistance:5000~20000"},
    )
    assert _part_ids(r.json()) == {"r1"}


def test_spec_filter_ands_multiple_keys(spec_client):
    # a resistance band AND a tolerance band: only r1 (10 kΩ, 1%) satisfies both
    r = spec_client.get(
        "/api/library/parts",
        params={"category": "Resistors", "spec": ["Resistance:5000~20000", "Tolerance:0~2"]},
    )
    assert _part_ids(r.json()) == {"r1"}


def test_no_spec_filter_returns_every_part(spec_client):
    r = spec_client.get("/api/library/parts")
    assert r.json()["count"] == 3


def test_a_malformed_spec_token_is_ignored_not_500(spec_client):
    r = spec_client.get("/api/library/parts", params={"spec": "garbage-no-colon"})
    assert r.status_code == 200
    assert r.json()["count"] == 3


def test_parametric_facets_require_a_token(tmp_path):
    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app
    from stockroom.api.context import build_context
    from stockroom.store.machine_config import MachineConfig
    from stockroom.store.profile import ProfileStore
    from stockroom.vcs.repo import GitRepo

    root = tmp_path / "libraries"
    root.mkdir()
    repo = GitRepo(root)
    repo.init()
    ProfileStore(root, repo).create("Main")
    repo.commit("seed", [root])
    kicad_dir = tmp_path / "kicad"
    kicad_dir.mkdir()
    ctx = build_context(root, kicad_dir=kicad_dir,
                        config=MachineConfig(active_profile="Main"), token="testtoken")
    app = create_app(ctx)
    with TestClient(app, base_url="http://test", raise_server_exceptions=False) as c:
        assert c.get("/api/library/facets/parametric").status_code == 401
