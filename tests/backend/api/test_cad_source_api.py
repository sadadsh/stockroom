def test_cad_source_primary_is_ultralibrarian(client, app_ctx):
    r = client.get("/api/library/parts/tps62130/cad-source")
    assert r.status_code == 200
    body = r.json()
    assert body["vendor"] == "UltraLibrarian"
    assert "ultralibrarian.com" in body["url"]
    assert "needs" in body


def test_cad_source_falls_back_to_digikey_when_primary_unresolvable(client, app_ctx, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced
    import stockroom.api.routers.library as lib_router

    class FakeDK:
        enabled = True
        vendor = "DigiKey"

        def lookup(self, mpn):
            r = EnrichmentResult()
            r.product_url = Sourced(f"https://www.digikey.com/detail/{mpn}", "digikey", "high")
            return r

    # Force the UL/SnapEDA primary to yield nothing so the DigiKey fallback runs.
    monkeypatch.setattr(lib_router, "build_refresh_adapters", lambda ctx: [FakeDK()])
    import stockroom.enrich.asset_source as asset_source
    monkeypatch.setattr(asset_source, "resolve_asset_page", lambda *a, **k: None)

    r = client.get("/api/library/parts/tps62130/cad-source")
    assert r.status_code == 200
    body = r.json()
    assert body["vendor"] == "DigiKey"
    assert body["url"].startswith("https://www.digikey.com/detail/")


def test_cad_source_unknown_part_404(client):
    assert client.get("/api/library/parts/nope/cad-source").status_code == 404
