"""Enrichment DEPTH over a faithful FULL Mouser product page (Batch A / A2).

The synthetic `mouser_product.html` covers the spec table; this fixture carries the
REAL page structures the depth pass must lift (all sliced from the owner's actual
captured Mouser page for ERJ-P03F1101V):
  - the full `<table class="pricing-table">` 9-break ladder (qty 1 .. 25,000), the
    real price the BOM cost layer needs, NOT the single JSON-LD offer;
  - the `pdp-product-availability` card ("In Stock: 5,616", "Factory Lead-Time: 15
    Weeks") the Mouser web path never read;
  - a "Lifecycle Status: Active" spec row that must promote to `r.lifecycle`.

The real Mouser JSON-LD is an ImageObject (no offers/mpn/datasheet), so on a real
page EVERY price/stock/lead value comes from these DOM structures, not JSON-LD."""

from __future__ import annotations

from pathlib import Path

from stockroom.enrich.extract import extract_all
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.enrich.sites.mouser_web import MouserWebSite

_FIXTURE = Path(__file__).parent / "fixtures" / "mouser_full.html"
_URL = "https://www.mouser.com/ProductDetail/Panasonic/ERJ-P03F1101V"


def _html() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def _result():
    return extract_all(_html(), _URL, SITE_EXTRACTORS)


def test_full_price_ladder_from_the_pricing_table() -> None:
    r = _result()
    # The real page's pricing table lists 9 breaks across its packaging groups (Cut Tape 1..1000
    # then Full Reel 5000..25000); the extractor keeps EVERY break as one sorted ladder so the
    # owner sees the deep-volume tiers, not just the first group.
    assert len(r.price_breaks) == 9
    first, last = r.price_breaks[0], r.price_breaks[-1]
    assert (first.qty, first.price) == (1, 0.31)
    assert (last.qty, last.price) == (25000, 0.043)
    # A mid-ladder break with a thousands-separated quantity parses correctly.
    thousand = next(b for b in r.price_breaks if b.qty == 1000)
    assert thousand.price == 0.063
    # The ladder is always sorted ascending and deduped per quantity (monotonic for the BOM layer).
    qtys = [b.qty for b in r.price_breaks]
    assert qtys == sorted(qtys) and len(set(qtys)) == len(qtys)
    assert all(b.currency == "USD" for b in r.price_breaks)


def test_price_ladder_is_deterministic_across_packaging_group_order() -> None:
    # Regression for the retired qty-monotonicity heuristic: two packaging groups where the
    # SECOND group restarts at a LOWER quantity than the first group's max must NOT drop the
    # second group (the old code truncated it). The result is the deterministic sorted+deduped
    # union of every break, whatever order the groups appear in.
    from stockroom.enrich.sites.mouser_web import _extract_price_breaks

    html = (
        '<table class="pricing-table"><tbody>'
        '<tr data-testid="PricingTableHeaderSubHeadingRow"><th>Cut Tape</th></tr>'
        '<tr data-testid="PricingTablePriceBreakRow"><th>1</th><td>$0.50</td><td>$0.50</td></tr>'
        '<tr data-testid="PricingTablePriceBreakRow"><th>1,000</th><td>$0.20</td><td>$200.00</td></tr>'
        '<tr data-testid="PricingTableHeaderSubHeadingRow"><th>Full Reel</th></tr>'
        '<tr data-testid="PricingTablePriceBreakRow"><th>500</th><td>$0.25</td><td>$125.00</td></tr>'
        '<tr data-testid="PricingTablePriceBreakRow"><th>5,000</th><td>$0.12</td><td>$600.00</td></tr>'
        "</tbody></table>"
    )
    breaks = _extract_price_breaks(html)
    assert [(b.qty, b.price) for b in breaks] == [(1, 0.5), (500, 0.25), (1000, 0.2), (5000, 0.12)]


def test_stock_count_from_the_availability_card() -> None:
    r = _result()
    assert r.stock is not None
    assert r.stock.value == 5616
    assert r.stock.source == "mouser_web"


def test_factory_lead_time_from_the_availability_card() -> None:
    r = _result()
    assert r.lead_time is not None
    assert r.lead_time.value == "15 Weeks"
    assert r.lead_time.source == "mouser_web"


def test_lifecycle_status_promotes_from_the_spec_row() -> None:
    r = _result()
    assert r.lifecycle is not None
    assert r.lifecycle.value == "Active"
    # It also stays a spec row (nothing the page said is dropped).
    assert r.specs["Lifecycle Status"].value == "Active"


def test_category_is_derived_from_the_product_category_spec() -> None:
    # A4: a pasted non-passive link must land in a real category, not "Other". fill_category
    # reads the distributor "Product Category" ("Thick Film Resistors - SMD") -> Resistors.
    from stockroom.enrich.pipeline import fill_category

    r = _result()
    assert r.category in ("", "Other")  # extract_all alone does not classify
    fill_category(r)
    assert r.category == "Resistors"


def test_package_comes_from_the_case_code_not_the_mounting_style() -> None:
    # A4: the real page carries "Mounting Style: PCB Mount" (how it mounts) and the size only as
    # "Case Code - in: 0603". The package must be the case code, never "PCB Mount".
    r = _result()
    assert r.package is not None
    assert r.package.value == "0603"
    # Mounting Style is kept as a plain spec, not mistaken for the package.
    assert r.specs["Mounting Style"].value == "PCB Mount"
    assert r.package.value != "PCB Mount"


def test_mouser_part_number_lifts_from_the_datalayer() -> None:
    # A3: a Mouser link carries the Mouser order number (667-...) in its dataLayer as
    # event_mouserpn; it belongs in dist_pns["mouser"], normalized to upper case so it reads
    # the same as the manufacturer MPN, ready to become the order/purchase part number.
    r = _result()
    assert r.dist_pns.get("mouser") == "667-ERJ-P03F1101V"


def test_the_web_extractor_alone_yields_price_stock_and_lead() -> None:
    # A direct unit of the site extractor (no generic cascade): the three depth fields
    # come from the site parser itself, so the pipeline gets them even when JSON-LD is
    # an ImageObject (the real Mouser case).
    r = MouserWebSite().extract(_html(), _URL)
    assert len(r.price_breaks) == 9
    assert r.stock.value == 5616
    assert r.lead_time.value == "15 Weeks"


def test_a_richer_site_ladder_supersedes_a_single_jsonld_offer() -> None:
    # A page carrying BOTH a JSON-LD single offer AND a real pricing table must expose
    # the full ladder, not the lone offer (the generic merge would otherwise win).
    jsonld = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product","mpn":"ERJ-P03F1101V",'
        '"offers":{"@type":"Offer","price":"0.12","priceCurrency":"USD"}}</script>'
    )
    html = jsonld + _html()
    r = extract_all(html, _URL, SITE_EXTRACTORS)
    assert len(r.price_breaks) == 9  # the 9-break table, not the single 0.12 offer
    assert r.price_breaks[0].price == 0.31


def test_jsonld_inventory_level_becomes_a_stock_count() -> None:
    # schema.org inventoryLevel IS a numeric stock (unlike the availability boolean the
    # extractor rightly ignores); the synthetic fixture carries inventoryLevel: 12000.
    from stockroom.enrich.extract import extract_jsonld_product

    synthetic = (
        Path(__file__).parent / "fixtures" / "mouser_product.html"
    ).read_text(encoding="utf-8")
    r = extract_jsonld_product(synthetic)
    assert r.stock is not None
    assert r.stock.value == 12000
