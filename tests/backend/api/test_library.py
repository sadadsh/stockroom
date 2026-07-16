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


def test_set_specs_persists_pinout(client):
    pins = [{"pin": "1", "name": "VIN"}, {"pin": "2", "name": "GND"}]
    r = client.post(
        "/api/library/parts/tps62130/specs",
        json={"specs": {"pinout": {"value": pins, "source": "datasheet", "confidence": "high"}}},
    )
    assert r.status_code == 200
    assert r.json()["specs"]["pinout"] == pins
    # the read surface reflects it
    detail = client.get("/api/library/parts/tps62130").json()
    assert detail["specs"]["pinout"] == pins
    assert detail["enrichment"]["pinout"]["source"] == "datasheet"


def test_set_specs_does_not_change_completeness(client):
    # setting a pinout on the incomplete part leaves its missing list untouched
    # (missing/is_complete live on the list summary, not the detail record)
    def _mystery():
        parts = client.get("/api/library/parts").json()["parts"]
        return next(p for p in parts if p["id"] == "mystery")

    before = _mystery()
    pins = [{"pin": "1", "name": "A"}]
    r = client.post(
        "/api/library/parts/mystery/specs",
        json={"specs": {"pinout": {"value": pins, "source": "datasheet"}}},
    )
    assert r.status_code == 200
    after = _mystery()
    assert after["missing"] == before["missing"]
    assert after["is_complete"] is False


def test_set_specs_unknown_part_is_404(client):
    r = client.post(
        "/api/library/parts/nope/specs",
        json={"specs": {"pinout": {"value": [], "source": "x"}}},
    )
    assert r.status_code == 404


def test_set_specs_rejects_a_malformed_specs_body(client):
    # specs must be an object; a list (or scalar) is a client error, surfaced as a
    # 422 by the typed body, never an opaque 500 from specs.items() blowing up.
    r = client.post("/api/library/parts/tps62130/specs", json={"specs": ["pinout"]})
    assert r.status_code == 422


# -- BOM match: paste a BOM, see what the library already has --------------------


def test_bom_match_reports_in_library_and_missing(client):
    # the fixture library has TPS62130 (complete) and MYSTERY (incomplete, no MPN)
    r = client.post("/api/library/bom-match", json={"text": "tps-62130\nWIDGET99"})
    assert r.status_code == 200
    body = r.json()
    items = {i["mpn"]: i for i in body["items"]}
    hit = items["tps-62130"]
    assert hit["part_id"] == "tps62130"
    assert hit["display_name"] == "TPS62130"
    assert hit["is_complete"] is True
    miss = items["WIDGET99"]
    assert miss["part_id"] is None
    assert body["in_library"] == 1
    assert body["total"] == 2


def test_bom_match_accepts_a_bom_csv(client):
    csv = "Reference,MPN,Qty\nU1,TPS62130,1\nR1,WIDGET99,10\n"
    r = client.post("/api/library/bom-match", json={"csv": csv})
    assert r.status_code == 200
    mpns = [i["mpn"] for i in r.json()["items"]]
    assert "TPS62130" in mpns and "WIDGET99" in mpns


def test_bom_match_empty_input_is_an_empty_report(client):
    r = client.post("/api/library/bom-match", json={"text": "   "})
    assert r.status_code == 200
    assert r.json()["items"] == [] and r.json()["total"] == 0


def test_attach_footprint_endpoint_tags_kicad_tool(client):
    r = client.post("/api/library/parts/mystery/footprint",
                    json={"lib": "Package_SO", "name": "SOIC-8"})
    assert r.status_code == 200
    fp = r.json()["footprint"]
    assert fp["name"] == "SOIC-8" and fp["lib"] == "Package_SO"
    assert fp["tool"] == "kicad"  # default EDA tag, altium-ready
    # persisted through the index rebuild
    assert client.get("/api/library/parts/mystery").json()["footprint"]["name"] == "SOIC-8"


def test_attach_symbol_endpoint_requires_a_name(client):
    r = client.post("/api/library/parts/mystery/symbol", json={"lib": "Device"})
    assert r.status_code == 422
