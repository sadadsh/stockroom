from pathlib import Path

from stockroom.enrich.extract import (
    extract_all,
    extract_jsonld_product,
    extract_next_data,
    extract_opengraph,
)

FIX = Path(__file__).parent / "fixtures"


def _html(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_jsonld_product_extracts_the_high_value_fields():
    r = extract_jsonld_product(_html("lcsc_product.html"))
    assert r.mpn.value == "TPS62130RGTR"
    assert r.mpn.source == "jsonld"
    assert r.mpn.confidence == "high"
    assert r.manufacturer.value == "Texas Instruments"
    assert "step-down" in r.description.value
    assert r.price_breaks and r.price_breaks[0].price == 1.23
    # A boolean schema.org InStock flag is NOT a numeric stock count: it must NOT be
    # fabricated into stock=1 (roadmap #12), which would drive false shortage warnings and
    # pre-empt the real distributor stock. Unknown stock stays None (an honest non-risk).
    assert r.stock is None


def test_opengraph_extracts_title_and_description_at_medium_confidence():
    r = extract_opengraph(_html("og_only.html"))
    # og:description wins over og:title, so the extracted value is the fixture's
    # og:description string ("Low-power dual operational amplifier, SOIC-8").
    assert "operational amplifier" in r.description.value.lower()
    assert r.description.source == "opengraph"
    assert r.description.confidence == "medium"


def test_next_data_extracts_from_embedded_json_state():
    r = extract_next_data(_html("next_data.html"))
    assert r.mpn.value == "STM32F103C8T6"
    assert r.manufacturer.value == "STMicroelectronics"
    assert r.package.value == "LQFP-48"


def test_cascade_prefers_the_higher_confidence_source():
    # JSON-LD (high) and OG (medium) both present in lcsc_product plus an og tag
    html = _html("lcsc_product.html").replace(
        "</head>",
        '<meta property="og:description" content="WRONG low-trust desc"></head>',
    )
    r = extract_all(html, "https://lcsc.com/p")
    # description already set high by JSON-LD; OG must not overwrite it
    assert "step-down" in r.description.value
    assert r.description.source == "jsonld"


def test_cascade_falls_back_to_heuristics_when_no_structured_data():
    r = extract_all(_html("no_structured.html"), "https://x/p")
    assert "MAX232" in (r.description.value or "")
    assert r.description.confidence == "low"  # heuristic is lowest trust


def test_jsonld_captures_an_explicit_datasheet_url():
    html = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product","mpn":"X",'
        '"datasheet":"https://ti.com/lit/ds/x.pdf"}</script>'
    )
    r = extract_jsonld_product(html)
    assert r.datasheet_url.value == "https://ti.com/lit/ds/x.pdf"
    assert r.datasheet_url.source == "jsonld"


def test_jsonld_datasheet_from_additional_property():
    html = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product","mpn":"X",'
        '"additionalProperty":[{"@type":"PropertyValue","name":"Datasheet",'
        '"value":"https://example.com/parts/x-datasheet.pdf"}]}</script>'
    )
    r = extract_jsonld_product(html)
    assert r.datasheet_url.value == "https://example.com/parts/x-datasheet.pdf"


def test_jsonld_ignores_a_non_datasheet_url_in_the_datasheet_field():
    # a product-page URL sneaking into the field must NOT be stored as a datasheet
    html = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Product","mpn":"X",'
        '"datasheet":"https://lcsc.com/product-detail/C1.html"}</script>'
    )
    r = extract_jsonld_product(html)
    assert r.datasheet_url is None
