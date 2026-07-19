from tests.backend.api.conftest import _drain_job


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
    out = _drain_job(client, r.json()["job_id"])
    assert out["status"] == "done", out
    summary = out["result"]
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


def test_rescan_is_single_flight_while_one_is_running(client, app_ctx, monkeypatch):
    import threading

    import stockroom.api.routers.library as lib_router
    from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

    event = threading.Event()

    class BlockingAdapter:
        enabled = True
        vendor = "Mouser"

        def __init__(self, event):
            self._event = event

        def lookup(self, mpn):
            self._event.wait()  # blocks until the test releases it, keeping the job RUNNING
            r = EnrichmentResult()
            r.mpn = Sourced(mpn, "mouser", "high")
            r.price_breaks = [PriceBreak(1, 1.23)]
            return r

    monkeypatch.setattr(lib_router, "build_refresh_adapters", lambda ctx: [BlockingAdapter(event)])

    r1 = client.post("/api/library/rescan?force=true")
    assert r1.status_code == 200
    job_a = r1.json()["job_id"]

    # job A is now blocked mid-lookup on the read lane; a second POST must NOT submit a new job
    r2 = client.post("/api/library/rescan?force=true")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["job_id"] == job_a
    assert body2["already_running"] is True
    assert len(app_ctx.jobs._jobs) == 1  # only job A was ever created

    event.set()  # release the blocked lookup so job A can complete
    out = _drain_job(client, job_a)
    assert out["status"] == "done", out
    summary = out["result"]
    assert summary["total"] >= 1 and summary["updated"] >= 1
