from types import SimpleNamespace

from tests.backend.api.conftest import _drain_job


def test_build_refresh_adapters_enables_only_the_configured_vendors():
    import stockroom.api.routers.library as lib_router

    # Mouser key present, DigiKey creds absent -> exactly one enabled, vendor-tagged, adapter.
    ctx = SimpleNamespace(config=SimpleNamespace(
        mouser_api_key="mk", digikey_client_id="", digikey_client_secret=""))
    adapters = lib_router.build_refresh_adapters(ctx)
    assert [a.vendor for a in adapters] == ["Mouser"]
    assert adapters[0].enabled is True

    # both vendors configured -> both, in registry order.
    ctx = SimpleNamespace(config=SimpleNamespace(
        mouser_api_key="mk", digikey_client_id="ci", digikey_client_secret="cs"))
    assert [a.vendor for a in lib_router.build_refresh_adapters(ctx)] == ["Mouser", "DigiKey"]

    # no creds -> no adapters (a refresh silently finds nothing rather than erroring).
    ctx = SimpleNamespace(config=SimpleNamespace(
        mouser_api_key="", digikey_client_id="", digikey_client_secret=""))
    assert lib_router.build_refresh_adapters(ctx) == []


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
