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


def test_from_url_includes_a_passive_add_plan(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def extract_from_url(self, url):
            r = EnrichmentResult(category="")
            r.mpn = Sourced("560112116151", "mouser", "high")
            r.package = Sourced("0603 (1608 Metric)", "mouser", "high")
            r.description = Sourced("Thick Film Resistors - SMD 118 Ohms 1%", "mouser", "high")
            r.specs = {
                "Resistance": Sourced("118 Ohms", "mouser", "high"),
                "Tolerance": Sourced("1%", "mouser", "high"),
            }
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())
    r = client.post("/api/enrich/from-url", json={"url": "https://www.mouser.com/x"})
    assert r.status_code == 200
    plan = r.json()["add_plan"]
    assert plan == {"kind": "resistor", "package": "0603", "value": "118 Ohms", "tolerance": "1%"}


def test_from_url_serializes_procurement_fields(client, monkeypatch):
    # A2: the DTO must carry the FULL pulled depth, not just identity + specs. lifecycle /
    # lead_time / product_url / dist_pns / stock live on the schema but were dropped by the
    # DTO, so the owner's UI could never show them even when a Mouser page yielded them.
    from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

    class _FakePipeline:
        def extract_from_url(self, url):
            r = EnrichmentResult(category="Resistors")
            r.mpn = Sourced("ERJ-P03F1101V", "mouser_web", "medium")
            r.stock = Sourced(5616, "mouser_web", "medium")
            r.lifecycle = Sourced("Active", "mouser_web", "medium")
            r.lead_time = Sourced("15 Weeks", "mouser_web", "medium")
            r.product_url = Sourced("https://www.mouser.com/ProductDetail/x", "mouser_web", "medium")
            r.dist_pns = {"mouser": "667-ERJ-P03F1101V"}
            r.price_breaks = [PriceBreak(1, 0.31, "USD"), PriceBreak(10, 0.163, "USD")]
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())
    body = client.post("/api/enrich/from-url", json={"url": "https://www.mouser.com/x"}).json()
    assert body["stock"]["value"] == 5616
    assert body["lifecycle"]["value"] == "Active"
    assert body["lead_time"]["value"] == "15 Weeks"
    assert body["product_url"]["value"] == "https://www.mouser.com/ProductDetail/x"
    assert body["dist_pns"] == {"mouser": "667-ERJ-P03F1101V"}
    assert len(body["price_breaks"]) == 2


def test_from_url_add_plan_null_for_non_passive(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def extract_from_url(self, url):
            r = EnrichmentResult(category="Transistors")
            r.mpn = Sourced("IRLML6344TRPBF", "mouser", "high")
            r.description = Sourced("MOSFET N-Ch 30V 5A SOT-23", "mouser", "high")
            r.specs = {"On-Resistance (RDS(on))": Sourced("29 mOhms", "mouser", "high")}
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())
    r = client.post("/api/enrich/from-url", json={"url": "https://www.mouser.com/x"})
    assert r.status_code == 200
    assert r.json()["add_plan"] is None


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
