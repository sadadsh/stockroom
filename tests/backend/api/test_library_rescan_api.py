import json


def _drain_job(client, job_id):
    kind = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip() or "{}")
                if kind == "result":
                    return data["result"]
                if kind == "error":
                    raise AssertionError(data)
    raise AssertionError("no terminal event")


def test_rescan_endpoint_refreshes_the_library_via_the_adapters(client, app_ctx, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced
    import stockroom.api.routers.library as lib_router

    class FakeAdapter:
        enabled = True
        vendor = "Mouser"

        def lookup(self, mpn):
            r = EnrichmentResult()
            r.mpn = Sourced(mpn, "mouser", "high")
            r.stock = Sourced(4321, "mouser", "high")
            r.price_breaks = [PriceBreak(1, 1.23)]
            return r

    monkeypatch.setattr(lib_router, "build_refresh_adapters", lambda ctx: [FakeAdapter()])

    r = client.post("/api/library/rescan?force=true")
    assert r.status_code == 200
    summary = _drain_job(client, r.json()["job_id"])
    assert summary["total"] >= 1 and summary["updated"] >= 1
    # the state surface reflects the run
    st = client.get("/api/library/rescan/state")
    assert st.status_code == 200
    body = st.json()
    assert body["counts"].get("updated", 0) >= 1
    assert all(set(v) == {"checked_at", "outcome"} for v in body["parts"].values())


def test_rescan_state_is_empty_before_any_run(client):
    body = client.get("/api/library/rescan/state").json()
    assert body["parts"] == {} and body["counts"] == {}
