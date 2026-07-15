"""TDD for the LCSC __NEXT_DATA__ product extractor (parse_lcsc_product).

Drives the extractor against the real parsed __NEXT_DATA__ root object captured
from an LCSC product page (C60490, YAGEO RC0402FR-0710KL), wrapped back into the
synthetic <script id="__NEXT_DATA__"> shell the extractor must find and decode.
"""

from __future__ import annotations

import json
from pathlib import Path

from stockroom.enrich.sites.lcsc import LcscProduct, parse_lcsc_product

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "lcsc_nextdata_C60490.json"
)


def _html_with_nextdata() -> str:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(fixture)
        + "</script></html>"
    )


def test_parse_lcsc_product_from_nextdata() -> None:
    product = parse_lcsc_product(_html_with_nextdata())

    assert isinstance(product, LcscProduct)
    assert product.lcsc == "C60490"
    assert product.mpn == "RC0402FR-0710KL"
    assert product.manufacturer == "YAGEO"
    assert product.package == "0402"
    assert product.description  # non-empty productIntroEn

    assert product.datasheet_url.startswith("https")
    assert ".pdf" in product.datasheet_url

    # Ordered spec map built from paramVOList (paramNameEn -> paramValueEn),
    # values taken verbatim from the real fixture.
    assert product.specs["Resistance"] == "10kΩ"
    assert product.specs["Power(Watts)"] == "62.5mW"
    assert product.specs["Tolerance"] == "±1%"
    assert product.specs["Voltage Rating"] == "50V"


def test_parse_lcsc_product_captures_every_valuable_webdata_field() -> None:
    # The owner wants EVERYTHING the source exposes stored, not just the params:
    # compliance, lifecycle, ordering, physical, tariff, media.
    s = parse_lcsc_product(_html_with_nextdata()).specs
    assert s["ECCN"] == "EAR99"
    assert s["Lifecycle"] == "normal"
    assert s["RoHS"] == "Yes"
    assert s["Minimum Order Quantity"] == "100"
    assert s["Package Quantity"] == "10000"
    assert s["Packaging"] == "Tape & Reel (TR)"
    assert s["LCSC Category"] == "Chip Resistor - Surface Mount"
    assert s["Key Attributes"] == "RES 10kΩ ±1% 62.5mW 0402"
    assert s["Stock"] == "857900"
    assert "Weight (kg)" in s
    # per-country HTS tariff codes -> feed Build & Cost tariffs
    assert s["HTS Code (US)"] == "8533210020"
    assert s["HTS Code (CN)"] == "8533211000"
    # EDA symbol/footprint SVG + product image (previews later)
    assert s["EDA Symbol SVG"].startswith("https://image.easyeda.com")
    assert s["EDA Footprint SVG"].startswith("https://")
    assert s["Product Image"].startswith("https://assets.lcsc.com")


def test_parse_lcsc_product_loses_no_list_or_dict_field() -> None:
    # Regression lock (review finding): list/dict webData fields were silently dropped.
    # Every image is captured, and a leftover list (faqs) is kept as JSON, not lost.
    s = parse_lcsc_product(_html_with_nextdata()).specs
    assert s["Product Image"].startswith("https://assets.lcsc.com")
    assert s["Product Image 2"].startswith("https://assets.lcsc.com")  # not just the first
    assert "Faqs" in s and "question" in s["Faqs"]  # the Q/A list is preserved as JSON


def test_parse_lcsc_product_keeps_the_full_raw_webdata() -> None:
    # Nothing is lost: the complete source record is retained for the database.
    product = parse_lcsc_product(_html_with_nextdata())
    assert isinstance(product.raw, dict)
    assert product.raw["productCode"] == "C60490"
    assert len(product.raw) >= 60


def test_parse_lcsc_product_no_nextdata_returns_none() -> None:
    assert parse_lcsc_product("<html>no next data</html>") is None


def test_parse_lcsc_product_missing_webdata_returns_none() -> None:
    html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {}}})
        + "</script></html>"
    )
    assert parse_lcsc_product(html) is None
