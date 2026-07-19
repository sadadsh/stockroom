def test_cad_source_returns_the_digikey_url(client, app_ctx, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced
    import stockroom.api.routers.library as lib_router

    class FakeDK:
        enabled = True
        vendor = "DigiKey"

        def lookup(self, mpn):
            r = EnrichmentResult()
            r.product_url = Sourced(f"https://www.digikey.com/detail/{mpn}", "digikey", "high")
            return r

    monkeypatch.setattr(lib_router, "build_refresh_adapters", lambda ctx: [FakeDK()])
    r = client.get("/api/library/parts/tps62130/cad-source")
    assert r.status_code == 200
    body = r.json()
    assert body["vendor"] == "DigiKey" and body["url"].startswith("https://www.digikey.com/detail/")


def test_cad_source_unknown_part_404(client):
    assert client.get("/api/library/parts/nope/cad-source").status_code == 404
