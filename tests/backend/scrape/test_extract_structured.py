from stockroom.scrape.extract.structured import (
    extract_jsonld_product, extract_microdata, extract_next_data, extract_nuxt,
    extract_opengraph, structured_blobs,
)

_JSONLD = (
    '<script type="application/ld+json">'
    '{"@type":"Product","mpn":"LM317T","brand":{"name":"TI"},'
    '"description":"Adjustable regulator",'
    '"offers":{"price":"0.50","priceCurrency":"USD","availability":"InStock",'
    '"inventoryLevel":1200}}</script>'
)


def test_jsonld_product_copied_behaviour():
    r = extract_jsonld_product(_JSONLD)
    assert r.mpn.value == "LM317T" and r.manufacturer.value == "TI"
    assert r.stock.value == 1200 and r.price_breaks[0].price == 0.5


def test_opengraph_and_next_data_still_work():
    og = extract_opengraph('<meta property="og:description" content="A part">')
    assert og.description.value == "A part"
    nd = extract_next_data('<script id="__NEXT_DATA__">{"a":{"mpn":"X1","manufacturer":"Acme"}}</script>')
    assert nd.mpn.value == "X1" and nd.manufacturer.value == "Acme"


def test_microdata_product():
    html = ('<div itemscope itemtype="https://schema.org/Product">'
            '<span itemprop="mpn">ABC123</span>'
            '<span itemprop="brand">BrandCo</span>'
            '<meta itemprop="description" content="A described part"></div>')
    r = extract_microdata(html)
    assert r.mpn.value == "ABC123"
    assert r.manufacturer.value == "BrandCo"
    assert r.description.value == "A described part"


def test_nuxt_state_walk():
    html = '<script>window.__NUXT__={"data":[{"mpn":"NX9","manufacturer":"Nuxt Corp"}]}</script>'
    r = extract_nuxt(html)
    assert r.mpn.value == "NX9" and r.manufacturer.value == "Nuxt Corp"


def test_structured_blobs_collects_every_source():
    blobs = structured_blobs(_JSONLD + '<meta property="og:title" content="T">')
    assert isinstance(blobs["jsonld"], list) and blobs["jsonld"]
    assert blobs["opengraph"].get("og:title") == "T"
    assert "microdata" in blobs and "next_data" in blobs and "nuxt" in blobs


def test_extract_product_cascade_merges_sources_and_prefers_high_conf():
    from stockroom.scrape.extract import extract_product
    html = (
        '<script type="application/ld+json">{"@type":"Product","mpn":"LM317T",'
        '"brand":{"name":"TI"}}</script>'
        '<meta property="og:description" content="Adjustable regulator">'
    )
    r = extract_product(html, "https://x/p")
    assert r.mpn.value == "LM317T"                        # JSON-LD high wins
    assert r.description.value == "Adjustable regulator"  # OG fills the gap


def test_build_scrape_result_populates_all_facets():
    from stockroom.scrape.extract import build_scrape_result
    from stockroom.scrape.model import Page
    html = ('<html><body><article><h1>LM317T</h1><p>' + ('word ' * 60) + '</p>'
            '<a href="/d">d</a></article>'
            '<script type="application/ld+json">{"@type":"Product","mpn":"LM317T"}</script>'
            '</body></html>')
    page = Page(url="https://x/p", final_url="https://x/p", status=200,
                content=html.encode(), text=html, content_type="text/html",
                render_tier="browser")
    sr = build_scrape_result(page)
    assert sr.product is not None and sr.product.mpn.value == "LM317T"
    assert "# LM317T" in sr.markdown
    assert "https://x/d" in sr.links
    assert sr.structured["jsonld"]
