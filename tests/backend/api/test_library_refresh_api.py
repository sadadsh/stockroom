import json


def _drain_job(client, job_id):
    """Consume a job's SSE stream and return the terminal payload (event: <kind> + data: <json>)."""
    kind = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip() or "{}")
                if kind == "result":
                    return {"status": "done", "result": data["result"]}
                if kind == "error":
                    return {"status": "error", "result": data}
    return {"status": "none", "result": None}


def test_refresh_endpoint_updates_a_part_via_the_api_adapters(client, app_ctx, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced
    import stockroom.api.routers.library as lib_router

    class FakeAdapter:
        enabled = True
        vendor = "Mouser"

        def lookup(self, mpn):
            r = EnrichmentResult()
            r.stock = Sourced(4321, "mouser", "high")
            r.price_breaks = [PriceBreak(1, 1.23)]
            return r

    # force the endpoint to use our fake adapter regardless of configured creds (no network)
    monkeypatch.setattr(lib_router, "build_refresh_adapters", lambda ctx: [FakeAdapter()])

    r = client.post("/api/library/parts/tps62130/refresh")
    assert r.status_code == 200
    out = _drain_job(client, r.json()["job_id"])
    assert out["status"] == "done", out
    body = out["result"]
    assert any(p["vendor"] == "Mouser" and p["stock"] == 4321 for p in body["purchase"])
    # and it persisted through the git Transaction
    updated = app_ctx.ops.load_record("tps62130")
    assert any(p.vendor == "Mouser" and p.stock == 4321 for p in updated.purchase)


def test_refresh_unknown_part_is_a_404(client):
    r = client.post("/api/library/parts/nope/refresh")
    assert r.status_code == 404
