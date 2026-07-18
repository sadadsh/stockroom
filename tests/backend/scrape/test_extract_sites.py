from stockroom.scrape.extract.sites import SITE_ADAPTERS
from stockroom.scrape.extract.sites.lcsc import LcscSite, parse_lcsc_product
from stockroom.scrape.extract.sites.mouser_web import MouserWebSite, _extract_price_breaks


def test_site_adapters_registered():
    assert len(SITE_ADAPTERS) == 3
    assert any(isinstance(a, MouserWebSite) for a in SITE_ADAPTERS)
    assert LcscSite().matches("https://www.lcsc.com/product-detail/C1.html")


def test_mouser_matches_regional_tld_domains():
    # A regional Mouser storefront (mouser.co.il, mouser.de, ...) renders the SAME product page
    # as mouser.com, so the extractor must claim it - otherwise a co.il URL falls to the generic
    # cascade and loses the whole parametric/compliance depth (corpus part tps259470lrpwr).
    m = MouserWebSite()
    assert m.matches("https://www.mouser.co.il/en/ProductDetail/TI/TPS259470LRPWR")
    assert m.matches("https://www.mouser.de/ProductDetail/x")
    assert m.matches("https://www.mouser.com/en/ProductDetail/x")
    # never a false claim on an unrelated host that merely contains the string "mouser"
    assert not m.matches("https://www.notmouser.com/x")
    assert not m.matches("https://www.digikey.com/x")


def test_mouser_price_ladder_monotonic():
    html = (
        '<table class="pricing-table">'
        '<tr data-testid="PricingTablePriceBreakRow"><td>1</td><td>$0.50</td></tr>'
        '<tr data-testid="PricingTablePriceBreakRow"><td>100</td><td>$0.30</td></tr>'
        '<tr data-testid="PricingTablePriceBreakRow"><td>1,000</td><td>$0.10</td></tr>'
        '</table>'
    )
    breaks = _extract_price_breaks(html)
    assert [b.qty for b in breaks] == [1, 100, 1000]
    assert [b.price for b in breaks] == [0.5, 0.3, 0.1]


def test_lcsc_nextdata_missing_returns_none():
    assert parse_lcsc_product("<html>no next</html>") is None
