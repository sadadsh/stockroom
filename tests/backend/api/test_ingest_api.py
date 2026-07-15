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


def test_commit_fires_the_REAL_gate_end_to_end_with_missing_list(client, app_ctx):
    # No fake: drive the REAL IngestPipeline.commit -> LibraryOps.add_part gate through
    # the API. The candidate carries real symbol + footprint SOURCES (so to_staged_part
    # succeeds) but is missing the datasheet/3D model/purchase passport fields, so the
    # complete-to-add gate must reject it with an honest 422 + per-field missing list,
    # and NOTHING may be written to the primary Main profile (spec section 6). This is
    # the proof that an incomplete part cannot be snuck into a primary profile.
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
    assert body["error"] == "IncompleteError"
    assert set(body["missing"]) >= {"3D model", "datasheet", "purchase link"}
    # the primary profile is untouched: the rejected add left zero trace
    assert client.get("/api/library/parts").json()["count"] == before


def test_archive_profile_bypasses_the_gate_through_the_api(client, app_ctx):
    # The one honest bypass (spec section 7): an archive profile grandfathers a legacy
    # import, so the SAME incomplete candidate that is rejected on Main is accepted on
    # an archive profile. Proven end-to-end so the bypass is real and scoped.
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
    # archive grandfathers it: the incomplete part lands (200), not a 422
    assert r.status_code == 200, r.text
    assert client.get("/api/library/parts").json()["count"] == 1


def test_inspect_starts_a_job_and_streams_a_result(client, monkeypatch):
    # Stub the IngestPipeline factory so no real vendor zip or kicad-cli is needed.
    from stockroom.ingest.staging import StagingCandidate

    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def inspect(self, inputs=(), lcsc_ids=(), workdir=None):
            return [StagingCandidate(
                vendor="snapeda", symbol_lib_path=None, symbol_name="X",
                footprint_variants=[], category="ICs", mpn="LM358",
                display_name="LM358", entry_name="LM358",
                gaps=["no symbol in this package"],
            )]

        def cleanup(self):
            pass

    monkeypatch.setattr("stockroom.api.routers.ingest._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/ingest/inspect", json={"paths": ["/tmp/part.zip"], "lcsc_ids": []})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # drain the SSE stream; the terminal result carries the candidate list
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "LM358" in body
    assert "result" in body
    assert "done" in body


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


def test_a_failing_job_surfaces_its_error_over_sse_then_terminates(client, monkeypatch):
    # A job that raises must stream a labeled 'error' event carrying the message and
    # STILL end with 'done', so the SSE consumer both sees the failure and terminates
    # cleanly (honest degradation, never a dropped or hanging stream).
    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def inspect(self, inputs=(), lcsc_ids=(), workdir=None):
            raise RuntimeError("staging blew up")

        def cleanup(self):
            pass

    monkeypatch.setattr("stockroom.api.routers.ingest._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/ingest/inspect", json={"paths": ["/tmp/x.zip"], "lcsc_ids": []})
    job_id = r.json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "error" in body
    assert "staging blew up" in body
    assert "done" in body


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


def test_enrich_candidate_applies_explicit_links_and_autofills(client, app_ctx, tmp_path, monkeypatch):
    # the owner's add flow: paste a datasheet link + a purchase link on the staged
    # part and the rest fills itself; the endpoint applies the explicit links, then
    # runs the enrichment pipeline over the candidate
    class _FakePipeline:
        def fetch_and_store_datasheet(self, candidate, url):
            stored = tmp_path / "stored.pdf"
            stored.write_bytes(b"%PDF-1.4\n%%EOF\n")
            candidate.datasheet_path = stored
            return stored

        def enrich_candidate(self, candidate, overwrite=None):
            candidate.manufacturer = candidate.manufacturer or "Texas Instruments"
            candidate.description = candidate.description or "Buck converter"
            return candidate

        def datasheet_fill(self, candidate):
            candidate.mpn = candidate.mpn or "TPS62130RGTR"
            return candidate

    monkeypatch.setattr(
        "stockroom.api.routers.ingest._make_enrich_pipeline", lambda ctx: _FakePipeline()
    )
    body = {
        "candidate": {"vendor": "snapeda", "symbol_name": "X", "display_name": "TPS62130",
                      "entry_name": "TPS62130", "category": "ICs"},
        "datasheet_url": "https://ti.com/ds.pdf",
        "purchase_url": "https://www.lcsc.com/product-detail/p.html",
    }
    r = client.post("/api/ingest/enrich", json=body)
    assert r.status_code == 200
    event = _drain_job(client, r.json()["job_id"])
    assert event["status"] == "done"
    out = event["result"]
    cand = out["candidate"]
    assert cand["datasheet_path"]  # the pasted link was fetched and stored
    assert cand["purchase"][0]["url"] == "https://www.lcsc.com/product-detail/p.html"
    assert cand["purchase"][0]["vendor"] == "LCSC"
    assert cand["mpn"] == "TPS62130RGTR"  # identity extracted from the datasheet
    assert cand["manufacturer"] == "Texas Instruments"  # then enrichment filled on
    # the pasted datasheet source is recorded for the committed record
    assert cand["provenance"]["source_url"] == "https://ti.com/ds.pdf"
    assert "manufacturer" in out["filled"] and "mpn" in out["filled"]


def test_enrich_candidate_attaches_a_local_datasheet_file(client, app_ctx, tmp_path, monkeypatch):
    class _FakePipeline:
        def enrich_candidate(self, candidate, overwrite=None):
            return candidate

        def datasheet_fill(self, candidate):
            return candidate

    monkeypatch.setattr(
        "stockroom.api.routers.ingest._make_enrich_pipeline", lambda ctx: _FakePipeline()
    )
    pdf = tmp_path / "TPS62130.pdf"
    pdf.write_bytes(b"%PDF-1.4\nreal enough\n%%EOF\n")
    body = {
        "candidate": {"vendor": "snapeda", "symbol_name": "X", "display_name": "TPS62130",
                      "entry_name": "TPS62130", "category": "ICs", "mpn": "TPS62130RGTR"},
        "datasheet_file": str(pdf),
    }
    r = client.post("/api/ingest/enrich", json=body)
    event = _drain_job(client, r.json()["job_id"])
    assert event["status"] == "done"
    stored = event["result"]["candidate"]["datasheet_path"]
    assert stored and stored != str(pdf)  # copied under the app's datasheet store
    from pathlib import Path as _P

    assert _P(stored).read_bytes().startswith(b"%PDF")


def test_enrich_candidate_rejects_a_non_pdf_file_honestly(client, app_ctx, tmp_path, monkeypatch):
    class _FakePipeline:
        def enrich_candidate(self, candidate, overwrite=None):
            return candidate

        def datasheet_fill(self, candidate):
            return candidate

    monkeypatch.setattr(
        "stockroom.api.routers.ingest._make_enrich_pipeline", lambda ctx: _FakePipeline()
    )
    junk = tmp_path / "page.html"
    junk.write_text("<html>not a datasheet</html>", encoding="utf-8")
    body = {
        "candidate": {"vendor": "snapeda", "symbol_name": "X", "display_name": "P",
                      "entry_name": "P", "category": "ICs"},
        "datasheet_file": str(junk),
    }
    r = client.post("/api/ingest/enrich", json=body)
    event = _drain_job(client, r.json()["job_id"])
    assert event["status"] == "done"
    out = event["result"]
    assert out["candidate"]["datasheet_path"] is None  # never silently attached
    assert any("PDF" in n for n in out["notes"])  # and the refusal is stated
