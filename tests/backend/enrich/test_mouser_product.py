"""End-to-end extraction over a faithful Mouser product page (Panasonic
ERJ-P03F1101V).

Locks two things the owner cares about together: (1) the generic JSON-LD cascade
still lifts the part identity/price/datasheet, and (2) the Mouser web extractor now
parses the REAL parametric spec table, whose rows are attr-col / attr-value-col
cell pairs with the label wrapped in a nested <label> tag (the shape the old
[^<] _ROW regex silently missed)."""

from __future__ import annotations

from pathlib import Path

from stockroom.enrich.extract import extract_all
from stockroom.enrich.sites import SITE_EXTRACTORS

_FIXTURE = Path(__file__).parent / "fixtures" / "mouser_product.html"
_URL = "https://www.mouser.com/ProductDetail/Panasonic/ERJ-P03F1101V"


def _result():
    html = _FIXTURE.read_text(encoding="utf-8")
    return extract_all(html, _URL, SITE_EXTRACTORS)


def test_jsonld_identity_price_and_datasheet_come_through() -> None:
    r = _result()
    assert r.mpn.value == "ERJ-P03F1101V"
    assert r.manufacturer.value == "Panasonic"
    assert r.price_breaks  # at least one price break from the JSON-LD offer
    assert r.price_breaks[0].price == 0.12
    assert r.datasheet_url.value.endswith(".pdf")


def test_real_parametric_specs_now_parse() -> None:
    r = _result()
    assert r.specs["Resistance"].value == "1.1 kOhms"
    assert r.specs["Tolerance"].value == "±1%"  # &plusmn; unescaped
    assert r.specs["Power Rating"].value == "0.2 W"
    assert r.specs["Product Category"].value == "Chip Resistor"
    assert r.specs["Operating Temperature"].value == "-55 C to +155 C"
    # Every parametric spec is sourced/confidence-stamped from the web extractor.
    assert r.specs["Resistance"].source == "mouser_web"
    assert r.specs["Resistance"].confidence == "medium"


def test_package_resolves_from_the_package_case_row() -> None:
    # This extractor maps a "Package / Case" label into the canonical package field
    # (via _PACKAGE_LABELS), so the value lands in r.package, NOT r.specs.
    r = _result()
    assert r.package.value == "0603 (1608 Metric)"
    assert "Package / Case" not in r.specs


def test_datasheet_from_the_datalayer_raw() -> None:
    # Mouser's real page carries the datasheet ONLY in its analytics dataLayer
    # (event_datasheet_url), not JSON-LD; the extractor must lift it.
    from stockroom.enrich.sites.mouser_web import MouserWebSite

    html = (
        '<a href="https://www.mouser.com/catalog/additional/Foo_Catalog.pdf">Catalog</a>'
        '<script>var d={"event_manufacturerpn":"erj-p03f1101v",'
        '"event_datasheet_url":"https://industrial.panasonic.com/cdbs/x/AOA0000C331.pdf"};</script>'
    )
    r = MouserWebSite().extract(html, "https://www.mouser.com/ProductDetail/x")
    assert r.datasheet_url is not None
    assert r.datasheet_url.value == "https://industrial.panasonic.com/cdbs/x/AOA0000C331.pdf"


def test_datasheet_from_the_datalayer_html_escaped() -> None:
    from stockroom.enrich.sites.mouser_web import MouserWebSite

    html = "&quot;event_datasheet_url&quot;:&quot;https://example.com/ds/abc.pdf&quot;"
    r = MouserWebSite().extract(html, "https://www.mouser.com/x")
    assert r.datasheet_url is not None
    assert r.datasheet_url.value == "https://example.com/ds/abc.pdf"


def test_pcn_or_catalog_pdf_is_not_taken_as_the_datasheet() -> None:
    # No event_datasheet_url present: a PCN/catalog PDF anchor must NOT be chosen.
    from stockroom.enrich.sites.mouser_web import MouserWebSite

    html = '<a href="https://www.mouser.com/PCN/Panasonic_Change.pdf">PCN</a>'
    r = MouserWebSite().extract(html, "https://www.mouser.com/x")
    assert r.datasheet_url is None
