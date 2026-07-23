def test_cad_source_vendor_is_always_digikey_even_with_ul_login(client, app_ctx):
    # A saved Ultra Librarian login no longer selects a vendor: the source is always DigiKey.
    app_ctx.config.ul_username = "me@x.com"
    r = client.get("/api/library/parts/tps62130/cad-source")
    assert r.status_code == 200
    body = r.json()
    assert body["vendor"] == "DigiKey"
    assert "digikey.com" in body["url"]
    assert "needs" in body


def test_cad_source_exact_product_page_from_digikey_adapter(client, app_ctx, monkeypatch):
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
    assert body["vendor"] == "DigiKey"
    assert body["url"].startswith("https://www.digikey.com/detail/")


def test_cad_source_search_fallback_when_no_digikey_adapter(client, app_ctx, monkeypatch):
    import stockroom.api.routers.library as lib_router

    # No DigiKey adapter available (no creds): the part still opens a real DigiKey search page.
    monkeypatch.setattr(lib_router, "build_refresh_adapters", lambda ctx: [])
    r = client.get("/api/library/parts/tps62130/cad-source")
    assert r.status_code == 200
    body = r.json()
    assert body["vendor"] == "DigiKey"
    assert body["url"] == "https://www.digikey.com/en/products/result?keywords=TPS62130"


def test_cad_source_unknown_part_404(client):
    assert client.get("/api/library/parts/nope/cad-source").status_code == 404
