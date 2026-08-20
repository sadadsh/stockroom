from __future__ import annotations


def test_candidate_dto_round_trips_purchase_and_always_includes_the_key():
    # candidate_to_dto must emit a `purchase` key (even empty) so the frontend
    # StagingCandidate shape is complete (a missing key crashes the review card),
    # and a candidate's purchase links must survive the inspect -> edit -> commit
    # round trip instead of being silently dropped.
    from stockroom.api.routers.ingest import candidate_to_dto, dto_to_candidate
    from stockroom.ingest.staging import StagingCandidate
    from stockroom.model.part import Purchase

    empty = StagingCandidate(vendor="lcsc", symbol_lib_path=None, symbol_name="X",
                             footprint_variants=[], mpn="LM358", display_name="LM358",
                             entry_name="LM358", category="ICs")
    dto = candidate_to_dto(empty)
    assert "purchase" in dto and dto["purchase"] == []

    withp = StagingCandidate(vendor="lcsc", symbol_lib_path=None, symbol_name="X",
                             footprint_variants=[], mpn="LM358", display_name="LM358",
                             entry_name="LM358", category="ICs",
                             purchase=[Purchase(vendor="Mouser", url="https://m/x",
                                                stock=5, currency="USD")])
    dto = candidate_to_dto(withp)
    assert dto["purchase"][0]["url"] == "https://m/x"
    assert dto_to_candidate(dto).purchase[0].url == "https://m/x"


def test_commit_rejects_local_cad_before_any_library_write(client, app_ctx):
    # Add A Part is metadata-only. Even a structurally valid KiCad symbol/footprint
    # pair cannot revive the retired local-ZIP lane.
    lib = app_ctx.profile.library
    sym_source = lib.symbol_lib_path("ICs")  # real SR-ICs.kicad_sym from the fixture
    fp_source = lib.footprint_lib_path("ICs") / "TPS62130.kicad_mod"  # real footprint file
    assert sym_source.exists() and fp_source.exists()

    before = client.get("/api/library/parts").json()["count"]
    r = client.post("/api/ingest/commit", json={
        "vendor": "snapeda",
        "symbol_lib_path": str(sym_source), "symbol_name": "TPS62130",
        "footprint_variants": [str(fp_source)], "chosen_footprint_index": 0,
        "category": "ICs", "mpn": "LM358", "display_name": "LM358", "entry_name": "LM358NEW",
        "manufacturer": "TI", "description": "op amp",
        # deliberately NO model_path / datasheet_path / purchase
    })
    assert r.status_code == 422
    body = r.json()
    assert "local files cannot be added through ingest" in body["detail"]
    assert "KiCad, Altium, and STEP" in body["detail"]
    assert client.get("/api/library/parts").json()["count"] == before


def test_archive_profile_does_not_reopen_public_local_cad_ingest(client, app_ctx):
    # Archive mode can grandfather historical records through the archive importer,
    # but it must not weaken the public network-only Add A Part boundary.
    assert client.post("/api/profiles",
                       json={"name": "Legacy", "archive": True}).status_code == 200
    assert client.post("/api/profiles/Legacy/activate").status_code == 200

    lib = app_ctx.profile.library  # now the Legacy archive profile
    lib.symbols_dir.mkdir(parents=True, exist_ok=True)
    # reuse the Main fixture's symbol/footprint sources as staging inputs
    main_lib = app_ctx.profile_store.get("Main").library
    sym_source = main_lib.symbol_lib_path("ICs")
    fp_source = main_lib.footprint_lib_path("ICs") / "TPS62130.kicad_mod"

    r = client.post("/api/ingest/commit", json={
        "vendor": "snapeda",
        "symbol_lib_path": str(sym_source), "symbol_name": "TPS62130",
        "footprint_variants": [str(fp_source)], "chosen_footprint_index": 0,
        "category": "ICs", "mpn": "LM358", "display_name": "LM358", "entry_name": "LM358ARCH",
        "manufacturer": "TI", "description": "op amp",
    })
    assert r.status_code == 422, r.text
    assert "local files cannot be added through ingest" in r.json()["detail"]
    assert client.get("/api/library/parts").json()["count"] == 0


def test_public_inspect_rejects_local_zip_without_starting_a_job(client):
    r = client.post("/api/ingest/inspect", json={"paths": ["/tmp/part.zip"]})
    assert r.status_code == 422
    assert "local ZIP" in r.json()["detail"]
    assert "job_id" not in r.json()


def test_inspect_rejects_lcsc_easyeda_cad_as_a_production_geometry_source(client):
    response = client.post(
        "/api/ingest/inspect",
        json={"paths": [], "lcsc_ids": ["C7666"]},
    )

    assert response.status_code == 422
    assert "LCSC/EasyEDA CAD ingest" in response.json()["detail"]


def test_commit_incomplete_candidate_is_422_with_missing(client, monkeypatch):
    # A bare candidate has no symbol/footprint/etc, so add_part rejects it.
    from stockroom.mutation.library_ops import IncompleteError

    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def commit(self, candidate):
            raise IncompleteError(["symbol", "footprint", "3D model", "datasheet"])

        def cleanup(self):
            pass

    monkeypatch.setattr("stockroom.api.routers.ingest._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/ingest/commit", json={
        "vendor": "bulk", "symbol_lib_path": None, "symbol_name": "",
        "footprint_variants": [], "category": "ICs", "mpn": "LM358",
        "display_name": "LM358", "entry_name": "LM358",
    })
    assert r.status_code == 422
    assert "symbol" in r.json()["missing"]


def test_events_for_an_unknown_job_id_is_an_honest_404_not_a_silent_200(client):
    # An unknown/expired job id must be a 404 (KeyError resolved on the request path),
    # never a silent 200 with an empty SSE stream that a client would read as success
    # (spec section 2.2: no swallowed errors).
    r = client.get("/api/jobs/does-not-exist/events")
    assert r.status_code == 404
    assert r.json()["error"] == "KeyError"


def test_public_inspect_never_invokes_the_internal_pipeline(client, monkeypatch):
    called = False

    def forbidden(_ctx):
        nonlocal called
        called = True
        raise AssertionError("public local inspect reached the internal capture pipeline")

    monkeypatch.setattr("stockroom.api.routers.ingest._make_pipeline", forbidden)
    response = client.post("/api/ingest/inspect", json={"paths": ["/tmp/x.zip"]})

    assert response.status_code == 422
    assert called is False


def test_candidate_dto_round_trips_provenance():
    # provenance carries the datasheet source_url that to_staged_part records on
    # the committed part; dropping it between inspect and commit loses the source
    from stockroom.api.routers.ingest import candidate_to_dto, dto_to_candidate
    from stockroom.ingest.staging import StagingCandidate
    from stockroom.model.part import Provenance

    c = StagingCandidate(
        vendor="snapeda", symbol_lib_path=None, symbol_name="X",
        footprint_variants=[], mpn="LM358", display_name="LM358",
        entry_name="LM358", category="ICs",
        provenance=Provenance(source="snapeda", source_url="https://x/ds.pdf",
                              original_zip_sha256="abc123"),
    )
    dto = candidate_to_dto(c)
    back = dto_to_candidate(dto)
    assert back.provenance is not None
    assert back.provenance.source == "snapeda"
    assert back.provenance.source_url == "https://x/ds.pdf"
    assert back.provenance.original_zip_sha256 == "abc123"
    # a candidate without provenance still round-trips as None
    bare = StagingCandidate(vendor="lcsc", symbol_lib_path=None, symbol_name="X",
                            footprint_variants=[], mpn="A", display_name="A",
                            entry_name="A", category="ICs")
    assert dto_to_candidate(candidate_to_dto(bare)).provenance is None


def test_vendor_from_url_names_the_known_distributors():
    from stockroom.api.routers.ingest import vendor_from_url

    assert vendor_from_url("https://www.lcsc.com/product-detail/x.html") == "LCSC"
    assert vendor_from_url("https://www.mouser.com/ProductDetail/x") == "Mouser"
    assert vendor_from_url("https://www.digikey.com/en/products/detail/x") == "DigiKey"
    assert vendor_from_url("https://shop.example.com/p/1") == "shop.example.com"
    assert vendor_from_url("not a url") == "manual"


def _drain_job(client, job_id):
    # SSE frames are `event: <kind>` + `data: <json>`; the terminal kinds are
    # "result" (payload under "result") and "error" (detail + error class).
    import json as _json

    kind = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                kind = line[len("event:"):].strip()
            elif line.startswith("data:") and kind in ("result", "error"):
                data = _json.loads(line[len("data:"):].strip())
                if kind == "result":
                    return {"status": "done", "result": data["result"]}
                return {"status": "error", "result": data}
    return None




def test_commit_lands_a_file_less_candidate_from_a_pulled_link(client):
    # The primary add flow (owner 2026-07-24): a part pulled from a purchase link commits
    # with NO asset files at all - identity + datasheet link + purchase suffice - and the
    # guided capture attaches both EDA formats afterwards. The detail carries null asset
    # refs, never a fabricated LibRef.
    r = client.post("/api/ingest/commit", json={
        "vendor": "Mouser",
        "symbol_lib_path": None, "symbol_name": "",
        "footprint_variants": [], "chosen_footprint_index": 0,
        "model_path": None, "datasheet_path": None,
        "category": "ICs", "mpn": "TPD6E05U06RVZR", "display_name": "TPD6E05U06",
        "entry_name": "", "manufacturer": "TI", "description": "6-ch ESD array",
        "purchase": [{"vendor": "Mouser", "url": "https://www.mouser.com/ProductDetail/x"}],
        "provenance": {"source": "mouser", "source_url": "https://ti.com/tpd6e05u06.pdf",
                       "original_zip_sha256": "", "ingested_at": ""},
        "gaps": [],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # A file-less add carries NO assets for any tool, and an empty bundle is omitted from
    # the wire format entirely rather than serialized as a wall of nulls.
    assert body["assets"] == {}
    assert body["mpn"] == "TPD6E05U06RVZR"
    detail = client.get(f"/api/library/parts/{body['id']}").json()
    assert detail["assets"] == {}


def test_commit_returns_typed_conflict_for_a_normalized_existing_mpn(client):
    def candidate(mpn: str) -> dict:
        return {
            "vendor": "Mouser",
            "symbol_lib_path": None,
            "symbol_name": "",
            "footprint_variants": [],
            "chosen_footprint_index": 0,
            "model_path": None,
            "datasheet_path": None,
            "category": "ICs",
            "mpn": mpn,
            "display_name": mpn,
            "entry_name": "",
            "manufacturer": "Acme",
            "description": "interface controller",
            "purchase": [{"vendor": "Mouser", "url": "https://www.mouser.com/x"}],
            "provenance": {
                "source": "mouser",
                "source_url": "https://example.com/acme.pdf",
                "original_zip_sha256": "",
                "ingested_at": "",
            },
            "gaps": [],
        }

    created = client.post("/api/ingest/commit", json=candidate("ABC-123"))
    assert created.status_code == 200, created.text

    conflict = client.post("/api/ingest/commit", json=candidate("ABC.123"))

    assert conflict.status_code == 409
    assert conflict.json() == {
        "error": "MpnConflictError",
        "detail": "MPN 'ABC.123' already exists as 'ABC-123'",
        "code": "mpn_conflict",
        "existing_part_id": created.json()["id"],
        "existing_mpn": "ABC-123",
    }


def test_the_add_lane_carries_vendor_disagreements_all_the_way_to_the_record():
    """A part ADDED must keep the competing vendor answers, exactly as a REFRESHED one does.

    Measured symptom: adding a part showed seven disagreeing fields in the review modal and then
    saved `alternates: None`, while Refresh on the same part produced 13 alternates and 9 UI
    disclosures. A part added and never refreshed silently lost every competing answer - the
    exact loss the conflict machinery exists to prevent.

    Cause: the inspect -> edit -> commit round trip goes through this DTO, and the DTO carried
    `specs` while dropping `alternates` (the disagreements) and `enrichment` (per-key
    provenance). The enrich layer computed both, `StagingCandidate` held both and
    `to_staged_part` forwarded both; they died crossing the wire.
    """
    from stockroom.api.routers.ingest import candidate_to_dto, dto_to_candidate
    from stockroom.ingest.staging import StagingCandidate

    c = StagingCandidate(
        vendor="", symbol_lib_path=None, symbol_name="", footprint_variants=[],
        display_name="TPS62130RGTR",
        category="ICs",
        mpn="TPS62130RGTR",
        specs={"Tolerance": "1%"},
        enrichment={"Tolerance": {"source": "mouser", "confidence": "high"}},
        alternates={
            "Tolerance": [
                {"value": "1%", "source": "mouser", "confidence": "high"},
                {"value": "2%", "source": "digikey", "confidence": "high"},
            ],
            "description": [
                {"value": "3A step-down converter", "source": "mouser", "confidence": "high"},
                {"value": "Buck Regulator 3A", "source": "digikey", "confidence": "high"},
            ],
        },
    )

    back = dto_to_candidate(candidate_to_dto(c))

    assert set(back.alternates) == {"Tolerance", "description"}, (
        "the vendor disagreements did not survive the commit round trip"
    )
    assert [a["value"] for a in back.alternates["Tolerance"]] == ["1%", "2%"]
    assert [a["source"] for a in back.alternates["description"]] == ["mouser", "digikey"]
    # Provenance rides along too: it is the same drop, and an empty `enrichment` map on every
    # real part is what that staging comment already recorded as a symptom.
    assert back.enrichment["Tolerance"]["source"] == "mouser"

    # And the projection onto the record keeps them, so this is end to end and not DTO-only.
    staged = back.to_staged_part()
    assert [a["value"] for a in staged.alternates["Tolerance"]] == ["1%", "2%"]


def test_a_candidate_with_no_disagreements_round_trips_to_empty_not_missing():
    """The empty case is the one that crashes a review card: the frontend reads these keys
    unconditionally, so they must always be PRESENT, like `purchase` already is."""
    from stockroom.api.routers.ingest import candidate_to_dto, dto_to_candidate
    from stockroom.ingest.staging import StagingCandidate

    dto = candidate_to_dto(StagingCandidate(
        vendor="", symbol_lib_path=None, symbol_name="", footprint_variants=[],
        display_name="R", category="Resistors"))
    assert dto["alternates"] == {}
    assert dto["enrichment"] == {}
    assert dto_to_candidate(dto).alternates == {}


def test_candidate_catalog_intelligence_survives_the_commit_dto():
    from stockroom.api.routers.ingest import candidate_to_dto, dto_to_candidate
    from stockroom.ingest.staging import StagingCandidate

    catalog = {
        "digikey": {
            "schema_version": 1,
            "product_number": "296-X-ND",
            "availability": {
                "cad_model": True,
                "three_d_model": False,
                "providers": ["Ultra Librarian"],
            },
            "media": [{"media_type": "EDA Models", "title": "CAD", "url": "https://u/x"}],
        }
    }
    candidate = StagingCandidate(
        vendor="digikey",
        symbol_lib_path=None,
        symbol_name="",
        footprint_variants=[],
        catalog=catalog,
    )
    dto = candidate_to_dto(candidate)
    assert dto["catalog"] == catalog
    assert dto_to_candidate(dto).catalog == catalog


def test_a_part_committed_through_the_api_has_the_disagreements_in_its_RECORD(client, app_ctx):
    """End to end, at the layer the sheet reads from.

    The DTO round-trip test above proves the wire carries `alternates`; this proves the value
    survives all the way into the persisted record, which is what the detail sheet's alternates
    disclosure actually reads. The two are different claims, and only this one is the feature.
    """
    import json

    r = client.post("/api/ingest/commit", json={
        "vendor": "Mouser",
        "symbol_lib_path": None, "symbol_name": "",
        "footprint_variants": [], "chosen_footprint_index": 0,
        "model_path": None, "datasheet_path": None,
        "category": "ICs", "mpn": "TPS62130RGTR", "display_name": "TPS62130RGTR",
        "entry_name": "", "manufacturer": "Texas Instruments",
        "description": "3A step-down converter",
        "provenance": {"source": "mouser", "source_url": "https://ti.com/lit/ds/tps62130.pdf",
                       "original_zip_sha256": "", "ingested_at": ""},
        "purchase": [{"vendor": "Mouser", "url": "https://www.mouser.com/x",
                      "part_number": "595-TPS62130RGTR", "price_breaks": [], "stock": 10,
                      "currency": "USD", "fetched_at": ""}],
        "specs": {"Tolerance": "1%"},
        "enrichment": {"Tolerance": {"source": "mouser", "confidence": "high"}},
        "alternates": {
            "Tolerance": [
                {"value": "1%", "source": "mouser", "confidence": "high"},
                {"value": "2%", "source": "digikey", "confidence": "high"},
            ],
        },
    })
    assert r.status_code == 200, r.text
    part_id = r.json()["id"]

    on_disk = json.loads(
        (app_ctx.profile.library.parts_dir / f"{part_id}.json").read_text(encoding="utf-8")
    )
    alts = on_disk.get("alternates") or {}
    assert [a["value"] for a in alts.get("Tolerance", [])] == ["1%", "2%"], (
        f"the committed record dropped the vendor disagreement: {on_disk.get('alternates')!r}"
    )
    assert [a["source"] for a in alts["Tolerance"]] == ["mouser", "digikey"]
    assert (on_disk.get("enrichment") or {}).get("Tolerance", {}).get("source") == "mouser"


def test_commit_api_rejects_part_a_payload_submitted_as_part_b(client):
    before = client.get("/api/library/parts").json()["count"]
    response = client.post("/api/ingest/commit", json={
        "vendor": "Mouser",
        "symbol_lib_path": None,
        "symbol_name": "",
        "footprint_variants": [],
        "chosen_footprint_index": 0,
        "model_path": None,
        "datasheet_path": None,
        "category": "ICs",
        "mpn": "PART-B",
        "display_name": "PART-B",
        "entry_name": "",
        "manufacturer": "Acme",
        "description": "Evidence mismatch test",
        "tags": [],
        "gaps": [],
        "purchase": [{
            "vendor": "Mouser",
            "url": "https://www.mouser.com/part-b",
            "part_number": "PART-B",
            "price_breaks": [],
            "stock": 1,
            "currency": "USD",
            "fetched_at": "",
        }],
        "provenance": {
            "source": "mouser",
            "source_url": "https://example.com/part-b.pdf",
            "original_zip_sha256": "",
            "ingested_at": "",
        },
        "specs": {},
        "enrichment": {},
        "alternates": {},
        "catalog": {},
        "official_payloads": {
            "mouser": {
                "SearchResults": {"Parts": [{"ManufacturerPartNumber": "PART-A"}]},
            },
        },
        "official_evidence": {
            "mouser": {
                "provider": "mouser",
                "queried_mpn": "PART-B",
                "canonical_mpn": "PART-B",
                "selected_values": {"mpn": "PART-B"},
            },
        },
    })

    assert response.status_code == 400
    assert "PART-A" in response.json()["detail"]
    assert "PART-B" in response.json()["detail"]
    assert client.get("/api/library/parts").json()["count"] == before
