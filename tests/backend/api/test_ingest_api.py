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
