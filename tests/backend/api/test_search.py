"""The modular search results endpoint: GET /api/library/search returns RICH rows the
Mouser-style results table needs - the part identity plus its full spec bag and a sourcing
summary (stock, unit price) - scoped by the same q/category/complete_only/spec filters as the
lean /parts list. The lean list stays lean (the picker); the table reads the rich rows. The
columns the table shows are chosen on the frontend from the parts' own specs, so this endpoint
never hardcodes a per-category column set - it just hands over each row's specs verbatim."""

from __future__ import annotations

import pytest


def _write_part(parts_dir, part_id, category, specs, purchase=None):
    from stockroom.model.part import PartRecord, Purchase

    rec = PartRecord(
        id=part_id,
        display_name=part_id.upper(),
        category=category,
        mpn=part_id.upper(),
        manufacturer="Acme",
        specs=dict(specs),
        purchase=[Purchase(**p) for p in (purchase or [])],
    )
    (parts_dir / f"{part_id}.json").write_text(rec.dumps(), encoding="utf-8")


@pytest.fixture
def search_client(tmp_path):
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

    _write_part(
        parts, "r1", "Resistors",
        {"Resistance": "10 kΩ", "Tolerance": "1%", "Lifecycle": "Active"},
        purchase=[{
            "vendor": "mouser", "url": "https://mouser.com/r1", "currency": "USD",
            "stock": 5000,
            "price_breaks": [{"qty": 1, "price": 0.31}, {"qty": 100, "price": 0.10}],
        }],
    )
    _write_part(
        parts, "r2", "Resistors",
        {"Resistance": "1 kΩ", "Tolerance": "5%"},
        purchase=[{
            "vendor": "mouser", "url": "https://mouser.com/r2", "currency": "USD",
            "stock": 61540,
            "price_breaks": [{"qty": 1, "price": 0.02}],
        }],
    )
    # a part with NO purchase at all: its sourcing summary must be null, never a 500
    _write_part(parts, "c1", "Capacitors", {"Capacitance": "100 nF", "Dielectric": "X7R"})
    repo.commit("seed search fixture", [root])

    kicad_dir = tmp_path / "kicad"
    kicad_dir.mkdir()
    config = MachineConfig(active_profile="Main")
    ctx = build_context(root, kicad_dir=kicad_dir, config=config, token="testtoken")
    app = create_app(ctx)
    with TestClient(app, base_url="http://test", raise_server_exceptions=False,
                    headers={"X-Stockroom-Token": "testtoken"}) as c:
        yield c


def _rows_by_id(body):
    return {row["id"]: row for row in body["parts"]}


def test_search_returns_rich_rows_with_specs_and_sourcing(search_client):
    r = search_client.get("/api/library/search")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    rows = _rows_by_id(body)
    r1 = rows["r1"]
    # identity carried through like the lean summary
    assert r1["display_name"] == "R1"
    assert r1["mpn"] == "R1"
    assert r1["manufacturer"] == "Acme"
    assert r1["category"] == "Resistors"
    # the full spec bag rides along so the table can pick columns from the data itself
    assert r1["specs"]["Resistance"] == "10 kΩ"
    assert r1["specs"]["Tolerance"] == "1%"
    # a flattened sourcing summary for the Stock / Unit columns
    assert r1["stock"] == 5000
    assert r1["unit_price"] == pytest.approx(0.31)
    assert r1["currency"] == "USD"


def test_search_unit_price_is_the_lowest_quantity_tier(search_client):
    rows = _rows_by_id(search_client.get("/api/library/search").json())
    # unit price is the qty-1 break (0.31), not the cheapest bulk tier (0.10)
    assert rows["r1"]["unit_price"] == pytest.approx(0.31)
    assert rows["r2"]["unit_price"] == pytest.approx(0.02)


def test_search_part_without_purchase_has_null_sourcing(search_client):
    c1 = _rows_by_id(search_client.get("/api/library/search").json())["c1"]
    assert c1["stock"] is None
    assert c1["unit_price"] is None
    assert c1["specs"]["Dielectric"] == "X7R"


def test_search_scopes_by_category(search_client):
    body = search_client.get("/api/library/search", params={"category": "Resistors"}).json()
    assert set(_rows_by_id(body)) == {"r1", "r2"}


def test_search_applies_the_spec_filter(search_client):
    # the SAME spec-filter contract as /parts: a normalized-magnitude range on Resistance
    body = search_client.get(
        "/api/library/search",
        params={"category": "Resistors", "spec": "Resistance:5000~20000"},
    ).json()
    assert set(_rows_by_id(body)) == {"r1"}


def test_search_matches_the_lean_parts_count_unfiltered(search_client):
    lean = search_client.get("/api/library/parts").json()["count"]
    rich = search_client.get("/api/library/search").json()["count"]
    assert lean == rich == 3


def test_search_requires_a_token(tmp_path):
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
        assert c.get("/api/library/search").status_code == 401
