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
            r.manufacturer = Sourced("Texas Instruments", "mouser", "high")
            r.description = Sourced("buck converter", "mouser", "high")
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/enrich/part", json={"mpn": "TPS62130RGTR", "category": "ICs"})
    assert r.status_code == 200
    out = _drain_job(client, r.json()["job_id"])
    assert out["status"] == "done"
    body = out["result"]
    assert body["manufacturer"]["value"] == "Texas Instruments"
    assert body["manufacturer"]["source"] == "mouser"
    assert body["manufacturer"]["confidence"] == "high"


def test_enrich_result_carries_complete_official_payloads_to_initial_add(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    mouser = {"SearchResults": {"Parts": [{"ManufacturerPartNumber": "TPS62130RGTR"}]}}
    digikey = {"Product": {"ManufacturerProductNumber": "TPS62130RGTR"}}

    class _FakePipeline:
        def enrich(self, mpn, category, want=None, progress=None):
            result = EnrichmentResult(category="ICs", mpn=Sourced(mpn, "mouser", "high"))
            result.official_payloads = {"mouser": mouser, "digikey": digikey}
            result.official_evidence = {
                provider: {
                    "provider": provider,
                    "queried_mpn": mpn,
                    "canonical_mpn": mpn,
                    "selected_values": {"mpn": mpn},
                }
                for provider in ("mouser", "digikey")
            }
            result.source_states = {"mouser": "success", "digikey": "success"}
            return result

    monkeypatch.setattr(
        "stockroom.api.routers.enrich._make_pipeline", lambda _ctx: _FakePipeline()
    )

    job_id = client.post(
        "/api/enrich/part", json={"mpn": "TPS62130RGTR", "category": "ICs"}
    ).json()["job_id"]
    body = _drain_job(client, job_id)["result"]

    assert body["official_payloads"] == {"mouser": mouser, "digikey": digikey}
    assert body["official_evidence"] == {
        "mouser": {
            "provider": "mouser",
            "queried_mpn": "TPS62130RGTR",
            "canonical_mpn": "TPS62130RGTR",
            "selected_values": {"mpn": "TPS62130RGTR"},
        },
        "digikey": {
            "provider": "digikey",
            "queried_mpn": "TPS62130RGTR",
            "canonical_mpn": "TPS62130RGTR",
            "selected_values": {},
        },
    }


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


def test_product_image_proxy_serves_a_cached_vendor_image(client, monkeypatch):
    # The SPA's <img> fallback: GET /api/enrich/image?url=... proxies the vendor CDN photo
    # through the backend (browser-refused hotlinks still render) and serves real image bytes
    # with the sniffed content type.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    monkeypatch.setattr("stockroom.enrich.image_proxy._http_fetch", lambda url: png)
    r = client.get("/api/enrich/image", params={"url": "https://mm.digikey.com/Images/x.png"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == png


def test_product_image_proxy_rejects_a_disallowed_url(client):
    # hostile input: the URL originates from remote page content - loopback/private/plain-http
    # targets are refused up front (400), never fetched
    r = client.get("/api/enrich/image", params={"url": "https://127.0.0.1/x.png"})
    assert r.status_code == 400


def test_product_image_proxy_404s_when_the_fetch_yields_no_image(client, monkeypatch):
    monkeypatch.setattr("stockroom.enrich.image_proxy._http_fetch",
                        lambda url: b"<html>blocked</html>")
    r = client.get("/api/enrich/image", params={"url": "https://www.mouser.com/images/x.jpg"})
    assert r.status_code == 404


def test_enrich_dto_carries_the_kept_spec_conflicts(client, monkeypatch):
    # A disagreement between sources reaches the UI with every value + its origin, so the
    # Add flow can show all of it (merge-only-identical, owner 2026-07-24).
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def extract_from_url(self, url, progress=None):
            r = EnrichmentResult(category="Resistors")
            r.specs = {"Resistance": Sourced("100 mOhm", "mouser", "high")}
            r.spec_conflicts = {
                "Resistance": [
                    Sourced("100 mOhm", "mouser", "high"),
                    Sourced("105 mOhm", "digikey", "high"),
                ]
            }
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())
    r = client.post("/api/enrich/from-url", json={"url": "https://www.mouser.com/x"})
    body = _drain_job(client, r.json()["job_id"])["result"]
    assert body["spec_conflicts"] == {
        "Resistance": [
            {"value": "100 mOhm", "source": "mouser", "confidence": "high"},
            {"value": "105 mOhm", "source": "digikey", "confidence": "high"},
        ]
    }


def test_enrich_dto_carries_every_canonical_field_and_the_field_conflicts(client, monkeypatch):
    """The DTO was hand-listing fields too, so country_of_origin and tariff_rate were pulled by
    the Mouser path and then never reached the UI at all - a part's origin and its real US
    import tariff existed in the backend and were invisible in the app. Enumerated from the
    schema now, and asserted for the WHOLE set so the next added field cannot be forgotten."""
    from stockroom.enrich.schema import SOURCED_FIELDS, EnrichmentResult, Sourced

    class _FakePipeline:
        def extract_from_url(self, url, progress=None):
            r = EnrichmentResult(category="ICs")
            for i, name in enumerate(SOURCED_FIELDS):
                setattr(r, name, Sourced(f"v{i}", "mouser", "high"))
            r.field_conflicts = {
                "description": [
                    Sourced("A", "mouser", "high"), Sourced("B", "digikey", "high"),
                ]
            }
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())
    r = client.post("/api/enrich/from-url", json={"url": "https://www.mouser.com/x"})
    body = _drain_job(client, r.json()["job_id"])["result"]
    missing = [name for name in SOURCED_FIELDS if body.get(name) is None]
    assert missing == [], f"the DTO dropped {missing}"
    assert body["field_conflicts"]["description"] == [
        {"value": "A", "source": "mouser", "confidence": "high"},
        {"value": "B", "source": "digikey", "confidence": "high"},
    ]


def _fake_bulk_pipeline(datasheet):
    """A pipeline that resolves one stock number and fills a candidate to completeness."""
    from stockroom.enrich.pipeline import ResolvedQuery
    from stockroom.model.part import Purchase

    class _P:
        def resolve_to_mpn(self, query):
            if query == "595-TPS62130RGTR":
                return ResolvedQuery(mpn="TPS62130RGTR", query=query,
                                     vendor="mouser", resolved=True)
            return ResolvedQuery(mpn=query, query=query)

        def enrich_candidate(self, candidate, overwrite=None):
            if candidate.mpn == "NOTHING":
                return candidate  # stays incomplete
            candidate.manufacturer = "Texas Instruments"
            candidate.description = "3A step-down converter"
            candidate.category = "ICs"
            candidate.datasheet_path = datasheet
            candidate.purchase = [Purchase(vendor="mouser", url="https://mouser/x")]
            return candidate

    return _P()


def test_bulk_import_adds_the_complete_parts_and_reports_the_rest(client, monkeypatch, tmp_path):
    """End to end through the real route, the real bulk_import and the real add_part gate:
    a stock number resolves, lands as a part, and an unresolvable one is REPORTED, not forced."""
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _fake_bulk_pipeline(ds))

    r = client.post("/api/enrich/bulk-import",
                    json={"part_numbers": ["595-TPS62130RGTR", "NOTHING"]})
    assert r.status_code == 200
    out = _drain_job(client, r.json()["job_id"])
    assert out["status"] == "done", out
    result = out["result"]
    assert result["counts"] == {"added": 1, "incomplete": 1}
    added = [i for i in result["items"] if i["status"] == "added"][0]
    assert added["query"] == "595-TPS62130RGTR"
    assert added["mpn"] == "TPS62130RGTR"
    assert added["resolved_by"] == "mouser"
    assert added["part_id"]
    incomplete = [i for i in result["items"] if i["status"] == "incomplete"][0]
    assert incomplete["missing"], "an incomplete part must say which fields it lacks"
    # the part is really in the library, not just claimed in a report
    assert client.get(f"/api/library/parts/{added['part_id']}").status_code == 200
    assert "importing" in out["stages"]


def test_bulk_import_dry_run_writes_nothing(client, monkeypatch, tmp_path):
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _fake_bulk_pipeline(ds))
    before = client.get("/api/library/parts").json()

    r = client.post("/api/enrich/bulk-import",
                    json={"part_numbers": ["595-TPS62130RGTR"], "dry_run": True})
    out = _drain_job(client, r.json()["job_id"])
    assert out["result"]["counts"] == {"would-add": 1}
    assert client.get("/api/library/parts").json() == before


def test_bulk_import_reads_a_pasted_bom_csv(client, monkeypatch, tmp_path):
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _fake_bulk_pipeline(ds))
    csv = "Ref,MPN,Qty\nU1,595-TPS62130RGTR,3\n"
    r = client.post("/api/enrich/bulk-import", json={"text": csv, "format": "csv"})
    out = _drain_job(client, r.json()["job_id"])
    assert out["result"]["counts"] == {"added": 1}


def test_bulk_import_refuses_an_empty_list(client):
    r = client.post("/api/enrich/bulk-import", json={"part_numbers": []})
    assert r.status_code == 422


def test_quantity_pricing_uses_exact_quantity_and_skips_digireel_until_order(
    client, app_ctx, monkeypatch
):
    calls: list[tuple] = []
    app_ctx.config.digikey_client_id = "client"
    app_ctx.config.digikey_client_secret = "secret"
    monkeypatch.setattr(
        "stockroom.enrich.digikey_api.DigiKeyClient.pricing_options_by_quantity",
        lambda _self, product, quantity: calls.append(("pricing", product, quantity))
        or {
            "DigiKeyProductNumber": "CUT-ND",
            "Packaging": "Cut Tape",
            "RequestedQuantity": quantity,
            "UnitPrice": 0.12,
            "Currency": "USD",
        },
    )
    monkeypatch.setattr(
        "stockroom.enrich.digikey_api.DigiKeyClient.digireel_pricing",
        lambda _self, product, quantity: calls.append(("digireel", product, quantity)) or {},
    )

    response = client.post(
        "/api/enrich/digikey/quantity-pricing",
        json={"product_number": "PART-ND", "quantity": 250, "prepare_order": False},
    )
    result = _drain_job(client, response.json()["job_id"])["result"]

    assert calls == [("pricing", "PART-ND", 250)]
    assert result["options"][0]["unit_price"] == 0.12
    assert result["digireel"] is None


def test_quantity_pricing_requests_digireel_only_for_explicit_order_preparation(
    client, app_ctx, monkeypatch
):
    calls: list[str] = []
    app_ctx.config.digikey_client_id = "client"
    app_ctx.config.digikey_client_secret = "secret"
    monkeypatch.setattr(
        "stockroom.enrich.digikey_api.DigiKeyClient.pricing_options_by_quantity",
        lambda *_args: {},
    )
    monkeypatch.setattr(
        "stockroom.enrich.digikey_api.DigiKeyClient.digireel_pricing",
        lambda *_args: calls.append("digireel") or {"UnitPrice": 0.08},
    )

    response = client.post(
        "/api/enrich/digikey/quantity-pricing",
        json={"product_number": "PART-ND", "quantity": 250, "prepare_order": True},
    )
    result = _drain_job(client, response.json()["job_id"])["result"]

    assert calls == ["digireel"]
    assert result["digireel"] == {"UnitPrice": 0.08}
