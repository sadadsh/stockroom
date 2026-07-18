"""API surface for the file-less passive add: preview + add from an MPN or Mouser URL."""

from __future__ import annotations

_OWNER_URL = (
    "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V"
    "?qs=sGAEpiMZZMtG0KNrPCHnjYpPrk%252BOMd4bdFNd%2Ftqgjvc%3D"
)


def test_passive_preview_decodes_without_committing(client):
    resp = client.post("/api/library/passive/preview", json={"input": _OWNER_URL})
    assert resp.status_code == 200
    body = resp.json()
    rec = body["record"]
    assert rec["passive"] is True
    assert rec["mpn"] == "ERJ-P03F1101V"
    assert rec["manufacturer"] == "Panasonic"
    assert rec["symbol"] == {"lib": "Device", "name": "R", "tool": "kicad"}
    assert rec["footprint"] == {"lib": "Resistor_SMD", "name": "R_0603_1608Metric", "tool": "kicad"}
    assert rec["purchase"][0]["url"] == _OWNER_URL
    assert body["gaps"] == ["datasheet"]
    # preview must not have added anything
    assert client.get("/api/library/parts").json()["count"] == 2


def test_passive_add_commits_and_indexes(client):
    resp = client.post("/api/library/passive", json={
        "input": _OWNER_URL,
        "datasheet_url": "https://industrial.panasonic.com/x.pdf",
    })
    assert resp.status_code == 200, resp.text
    rec = resp.json()
    assert rec["id"] == "erj_p03f1101v" and rec["passive"] is True
    # the derived index picked it up (2 seeded + 1 added)
    parts = client.get("/api/library/parts").json()
    assert parts["count"] == 3
    assert client.get("/api/library/parts/erj_p03f1101v").json()["mpn"] == "ERJ-P03F1101V"


def test_passive_add_without_datasheet_is_422_incomplete(client):
    resp = client.post("/api/library/passive", json={"input": _OWNER_URL})
    assert resp.status_code == 422
    assert "datasheet" in resp.json().get("missing", [])
    assert client.get("/api/library/parts").json()["count"] == 2  # zero trace


def test_undecodable_input_asks_for_manual_input(client):
    # An MPN no decoder knows is NOT an error: the preview returns 200 with a
    # needs_input status and the package options so the UI reveals manual pickers.
    resp = client.post("/api/library/passive/preview", json={"input": "560112116151"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_input"
    assert body["mpn"] == "560112116151"
    assert "0603" in body["packages"]
    # nothing was committed
    assert client.get("/api/library/parts").json()["count"] == 2


def test_manual_kind_and_package_preview_then_add(client):
    # After the pickers are filled the preview builds a real record, and the add
    # commits it with the stock footprint resolved from the picked package.
    preview = client.post("/api/library/passive/preview", json={
        "input": "560112116151", "kind": "inductor", "package": "1210",
        "value": "4.7 uH", "manufacturer": "Wurth Elektronik",
    })
    assert preview.status_code == 200, preview.text
    pbody = preview.json()
    assert pbody["status"] == "ok"
    assert pbody["record"]["footprint"] == {"lib": "Inductor_SMD", "name": "L_1210_3225Metric", "tool": "kicad"}

    resp = client.post("/api/library/passive", json={
        "input": "560112116151", "kind": "inductor", "package": "1210",
        "value": "4.7 uH", "manufacturer": "Wurth Elektronik",
        "datasheet_url": "https://www.we-online.com/x.pdf",
    })
    assert resp.status_code == 200, resp.text
    assert client.get("/api/library/parts").json()["count"] == 3


def test_add_undecodable_without_a_manual_pick_is_422(client):
    resp = client.post("/api/library/passive", json={"input": "560112116151"})
    assert resp.status_code == 422
    assert client.get("/api/library/parts").json()["count"] == 2  # zero trace
