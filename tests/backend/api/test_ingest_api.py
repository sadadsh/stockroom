from __future__ import annotations


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
