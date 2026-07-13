from __future__ import annotations


def test_list_all_parts(client):
    r = client.get("/api/library/parts")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    names = {p["display_name"] for p in body["parts"]}
    assert names == {"TPS62130", "MYSTERY"}


def test_search_filters_by_query(client):
    r = client.get("/api/library/parts", params={"q": "tps"})
    assert r.status_code == 200
    parts = r.json()["parts"]
    assert len(parts) == 1
    assert parts[0]["mpn"] == "TPS62130"


def test_filter_complete_only(client):
    r = client.get("/api/library/parts", params={"complete_only": True})
    assert {p["display_name"] for p in r.json()["parts"]} == {"TPS62130"}


def test_facets_roll_up_categories_and_completeness(client):
    r = client.get("/api/library/facets")
    assert r.status_code == 200
    body = r.json()
    assert body["by_category"]["ICs"] == 2
    assert body["complete"] == 1
    assert body["incomplete"] == 1


def test_part_detail_returns_full_record(client):
    r = client.get("/api/library/parts/tps62130")
    assert r.status_code == 200
    body = r.json()
    assert body["mpn"] == "TPS62130"
    assert body["symbol"]["name"] == "TPS62130"


def test_missing_part_detail_is_404(client):
    r = client.get("/api/library/parts/nope")
    assert r.status_code == 404


def test_library_list_requires_a_token(anon_client):
    assert anon_client.get("/api/library/parts").status_code == 401


def test_edit_field_updates_the_record_and_index(client):
    r = client.patch("/api/library/parts/mystery",
                     json={"field": "manufacturer", "value": "STMicro"})
    assert r.status_code == 200
    assert r.json()["manufacturer"] == "STMicro"
    # the read surface reflects it immediately (index rebuilt)
    detail = client.get("/api/library/parts/mystery").json()
    assert detail["manufacturer"] == "STMicro"


def test_move_category_changes_the_category(client):
    r = client.post("/api/library/parts/tps62130/move", json={"category": "Modules"})
    assert r.status_code == 200
    assert r.json()["category"] == "Modules"


def test_delete_part_removes_it(client):
    assert client.delete("/api/library/parts/mystery").status_code == 204
    assert client.get("/api/library/parts/mystery").status_code == 404
    assert client.get("/api/library/parts").json()["count"] == 1


def test_edit_unknown_part_is_404(client):
    r = client.patch("/api/library/parts/nope", json={"field": "mpn", "value": "X"})
    assert r.status_code == 404
