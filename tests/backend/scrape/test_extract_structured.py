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


def test_microdata_ignores_nested_itemscope_props():
    # finding [2]: an Offer's sku/price nested inside the Product scope must NOT be read
    # as the product's MPN/price (schema.org ownership = nearest itemscope ancestor).
    html = ('<div itemscope itemtype="https://schema.org/Product">'
            '<span itemprop="name">Arduino Uno</span>'
            '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
            '<span itemprop="sku">OFFER-SKU-999</span>'
            '<span itemprop="price">25.00</span>'
            '<span itemprop="priceCurrency">EUR</span></div></div>')
    r = extract_microdata(html)
    assert r.mpn is None                       # the Offer SKU did NOT leak in as the MPN
    assert not r.price_breaks                   # the Offer price did NOT leak in
    assert r.description.value == "Arduino Uno"  # the product's own prop still read


def test_nuxt_parses_trailing_statement_form():
    # finding [5]: window.__NUXT__={...}; followed by more JS must still decode.
    html = ('<script>window.__NUXT__={"data":[{"mpn":"NX9","manufacturer":"Nuxt Corp"}]};'
            'window.__NUXT__.config={};</script>')
    r = extract_nuxt(html)
    assert r.mpn.value == "NX9" and r.manufacturer.value == "Nuxt Corp"


def test_structured_blobs_never_raises_on_deeply_nested_json():
    # finding [6]: json.loads raises RecursionError (not JSONDecodeError) on a pathological
    # blob; the never-raises contract must still hold.
    deep = '<script id="__NEXT_DATA__">' + "[" * 5000 + "]" * 5000 + "</script>"
    blobs = structured_blobs(deep)  # must not raise
    assert isinstance(blobs, dict) and "next_data" in blobs


def test_site_pricing_table_supersedes_a_lone_microdata_price():
    # finding [7]: microdata inserted before the site adapters let a microdata single price
    # block a single-break site pricing table from superseding it.
    from stockroom.scrape.extract import extract_product
    html = ('<div itemscope itemtype="https://schema.org/Product">'
            '<span itemprop="price">9.99</span></div>'
            '<table class="pricing-table">'
            '<tr data-testid="PricingTablePriceBreakRow"><td>500</td><td>$0.20</td></tr>'
            '</table>')
    r = extract_product(html, "https://www.mouser.com/p")
    assert any(b.qty == 500 and b.price == 0.20 for b in r.price_breaks)
    assert not any(b.price == 9.99 for b in r.price_breaks)


def test_build_scrape_result_never_raises_even_if_extraction_throws(monkeypatch):
    # finding [8]: the "Never raises" contract must hold inside build_scrape_result itself,
    # not only via engine.scrape's outer guard.
    import stockroom.scrape.extract as ex
    from stockroom.scrape.model import Page, ScrapeResult

    def _boom(*a, **k):
        raise RuntimeError("extractor blew up")

    monkeypatch.setattr(ex, "extract_product", _boom)
    page = Page(url="https://x/p", final_url="https://x/p", status=200,
                content=b"<html></html>", text="<html></html>",
                content_type="text/html", render_tier="browser")
    sr = ex.build_scrape_result(page)
    assert isinstance(sr, ScrapeResult) and sr.page is page


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
