from __future__ import annotations


def test_enrich_part_returns_sourced_fields(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def enrich(self, mpn, category, want=None):
            r = EnrichmentResult(category=category)
            r.manufacturer = Sourced("Texas Instruments", "jsonld", "high")
            r.description = Sourced("buck converter", "jsonld", "high")
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/enrich/part", json={"mpn": "TPS62130RGTR", "category": "ICs"})
    assert r.status_code == 200
    body = r.json()
    assert body["manufacturer"]["value"] == "Texas Instruments"
    assert body["manufacturer"]["source"] == "jsonld"
    assert body["manufacturer"]["confidence"] == "high"


def test_bulk_enrich_streams_a_report(client, monkeypatch):
    from stockroom.enrich.bulk import BulkItem, BulkReport

    def _fake_bulk(mpns, pipeline, category="Other", candidate_factory=None):
        return BulkReport(items=[
            BulkItem(mpn="A", candidate=None, complete=True, missing=[]),
            BulkItem(mpn="B", candidate=None, complete=False, missing=["symbol"]),
        ])

    monkeypatch.setattr("stockroom.api.routers.enrich.bulk_enrich", _fake_bulk)
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline", lambda ctx: object())

    r = client.post("/api/enrich/bulk", json={"text": "A\nB"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "symbol" in body  # the incomplete item's missing field surfaced
    assert "done" in body
