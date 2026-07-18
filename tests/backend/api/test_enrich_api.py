from __future__ import annotations

import json as _json

from stockroom.api.context import build_context
from stockroom.api.routers.enrich import _make_pipeline
from stockroom.store.machine_config import MachineConfig


def _drain_job(client, job_id):
    """Consume a job's SSE stream and return every progress stage plus the terminal payload.
    SSE frames are `event: <kind>` + `data: <json>`; the terminal kinds are result / error."""
    stages: list[str] = []
    kind = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                kind = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = _json.loads(line[len("data:"):].strip())
                if kind == "progress" and "stage" in data:
                    stages.append(data["stage"])
                elif kind == "result":
                    return {"status": "done", "result": data["result"], "stages": stages}
                elif kind == "error":
                    return {"status": "error", "result": data, "stages": stages}
    return {"status": "none", "result": None, "stages": stages}


def test_enrich_part_streams_sourced_fields(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def enrich(self, mpn, category, want=None, progress=None):
            r = EnrichmentResult(category=category)
            r.manufacturer = Sourced("Texas Instruments", "jsonld", "high")
            r.description = Sourced("buck converter", "jsonld", "high")
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/enrich/part", json={"mpn": "TPS62130RGTR", "category": "ICs"})
    assert r.status_code == 200
    out = _drain_job(client, r.json()["job_id"])
    assert out["status"] == "done"
    body = out["result"]
    assert body["manufacturer"]["value"] == "Texas Instruments"
    assert body["manufacturer"]["source"] == "jsonld"
    assert body["manufacturer"]["confidence"] == "high"


def test_enrich_part_streams_the_real_stage_sequence(client, monkeypatch):
    # S6: the background job emits the honest per-stage progress the pipeline produces, so the UI
    # can show live loading. The fake drives the sink exactly as the real pipeline would.
    from stockroom.enrich.progress import Stage, emit
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def enrich(self, mpn, category, want=None, progress=None):
            for st in (Stage.FETCHING, Stage.RENDERING, Stage.EXTRACTING, Stage.VALIDATING):
                emit(progress, st)
            r = EnrichmentResult(category=category)
            r.mpn = Sourced(mpn, "scrape", "medium")
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())
    out = _drain_job(client, client.post(
        "/api/enrich/part", json={"mpn": "LM317"}).json()["job_id"])
    assert out["status"] == "done"
    assert out["stages"] == ["fetching", "rendering", "extracting", "validating"]


def test_from_url_streams_a_passive_add_plan(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def extract_from_url(self, url, progress=None):
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
    plan = _drain_job(client, r.json()["job_id"])["result"]["add_plan"]
    assert plan == {"kind": "resistor", "package": "0603", "value": "118 Ohms", "tolerance": "1%"}


def test_from_url_streams_procurement_fields(client, monkeypatch):
    # A2: the DTO must carry the FULL pulled depth, not just identity + specs. lifecycle /
    # lead_time / product_url / dist_pns / stock live on the schema but were dropped by the
    # DTO, so the owner's UI could never show them even when a Mouser page yielded them.
    from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

    class _FakePipeline:
        def extract_from_url(self, url, progress=None):
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
    body = _drain_job(client, client.post(
        "/api/enrich/from-url", json={"url": "https://www.mouser.com/x"}).json()["job_id"])["result"]
    assert body["stock"]["value"] == 5616
    assert body["lifecycle"]["value"] == "Active"
    assert body["lead_time"]["value"] == "15 Weeks"
    assert body["product_url"]["value"] == "https://www.mouser.com/ProductDetail/x"
    assert body["dist_pns"] == {"mouser": "667-ERJ-P03F1101V"}
    assert len(body["price_breaks"]) == 2


def test_from_url_add_plan_null_for_non_passive(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def extract_from_url(self, url, progress=None):
            r = EnrichmentResult(category="Transistors")
            r.mpn = Sourced("IRLML6344TRPBF", "mouser", "high")
            r.description = Sourced("MOSFET N-Ch 30V 5A SOT-23", "mouser", "high")
            r.specs = {"On-Resistance (RDS(on))": Sourced("29 mOhms", "mouser", "high")}
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())
    r = client.post("/api/enrich/from-url", json={"url": "https://www.mouser.com/x"})
    assert r.status_code == 200
    assert _drain_job(client, r.json()["job_id"])["result"]["add_plan"] is None


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


def test_make_pipeline_wires_digikey_only_when_both_creds_are_set(library_root, tmp_path):
    # _make_pipeline builds a live DigiKeyAdapter and registers it as a "digikey" source only
    # when BOTH digikey_client_id and digikey_client_secret are set on the machine config;
    # this seam had no test coverage (plan Task 4 called for one and it was never added).
    with_creds = MachineConfig(active_profile="Main", digikey_client_id="id",
                               digikey_client_secret="secret")
    ctx = build_context(library_root, kicad_dir=tmp_path / "kicad-with", config=with_creds,
                        token="testtoken")
    names = {s.name for s in _make_pipeline(ctx).registry.sources}
    assert "digikey" in names

    without_creds = MachineConfig(active_profile="Main")
    ctx2 = build_context(library_root, kicad_dir=tmp_path / "kicad-without", config=without_creds,
                         token="testtoken")
    names2 = {s.name for s in _make_pipeline(ctx2).registry.sources}
    assert "digikey" not in names2
