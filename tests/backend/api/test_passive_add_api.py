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
    assert rec["symbol"] == {"lib": "Device", "name": "R"}
    assert rec["footprint"] == {"lib": "Resistor_SMD", "name": "R_0603_1608Metric"}
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


def test_non_passive_input_is_422(client):
    resp = client.post("/api/library/passive/preview", json={"input": "STM32F103C8T6"})
    assert resp.status_code == 422
