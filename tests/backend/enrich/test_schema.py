from stockroom.enrich.schema import (
    SCHEMA_VERSION,
    CanonicalSpecs,
    EnrichmentResult,
    PriceBreak,
    Sourced,
    normalize_mpn,
)


def test_normalize_mpn_is_filesystem_safe():
    assert normalize_mpn("TPS62130RGTR") == "TPS62130RGTR"
    assert normalize_mpn("tps62130rgtr") == "TPS62130RGTR"
    assert normalize_mpn("ABC/123") == "ABC-123"
    assert normalize_mpn("ABC\\123") == "ABC-123"
    assert normalize_mpn("ABC 123") == "ABC-123"
    # no path-separator or wildcard survives
    for ch in "/\\:*?\"<>|":
        assert ch not in normalize_mpn(f"A{ch}B")


def test_sourced_carries_source_and_confidence():
    s = Sourced(value="Texas Instruments", source="jsonld", confidence="high")
    assert s.value == "Texas Instruments"
    assert s.source == "jsonld"
    assert s.confidence == "high"


def test_result_stamps_schema_version():
    r = EnrichmentResult(category="ICs")
    assert r.schema_version == SCHEMA_VERSION


def test_filled_fields_reports_only_set_fields():
    r = EnrichmentResult(category="ICs")
    assert r.filled_fields() == set()
    r.mpn = Sourced("TPS62130RGTR", "jsonld", "high")
    r.datasheet_url = Sourced("http://x/d.pdf", "jsonld", "high")
    assert r.filled_fields() == {"mpn", "datasheet_url"}


def test_merge_missing_never_overwrites_a_filled_field():
    a = EnrichmentResult(category="ICs")
    a.mpn = Sourced("TPS62130RGTR", "datasheet", "high")
    b = EnrichmentResult(category="ICs")
    b.mpn = Sourced("WRONG", "scrape", "low")
    b.manufacturer = Sourced("TI", "scrape", "medium")
    a.merge_missing(b)
    # mpn already filled from the higher-trust source: keep it
    assert a.mpn.value == "TPS62130RGTR"
    assert a.mpn.source == "datasheet"
    # manufacturer was empty: take it from b
    assert a.manufacturer.value == "TI"


def test_merge_missing_fills_price_breaks_only_when_empty():
    a = EnrichmentResult(category="ICs")
    b = EnrichmentResult(category="ICs")
    b.price_breaks = [PriceBreak(qty=1, price=1.23)]
    a.merge_missing(b)
    assert a.price_breaks == [PriceBreak(qty=1, price=1.23)]
    c = EnrichmentResult(category="ICs")
    c.price_breaks = [PriceBreak(qty=10, price=0.99)]
    a.merge_missing(c)  # a already has breaks: unchanged
    assert a.price_breaks == [PriceBreak(qty=1, price=1.23)]


def test_canonical_specs_defaults():
    cs = CanonicalSpecs()
    assert cs.package == ""
    assert cs.specs == {}
    assert cs.pinout == []


# -- M7d: the procurement fields (lifecycle / lead time / product page / distributor P/Ns)


def test_procurement_fields_default_empty():
    r = EnrichmentResult(category="ICs")
    assert r.lifecycle is None
    assert r.lead_time is None
    assert r.product_url is None
    assert r.dist_pns == {}
    assert r.filled_fields() == set()


def test_filled_fields_reports_the_procurement_fields():
    r = EnrichmentResult(category="ICs")
    r.lifecycle = Sourced("Active", "mouser", "high")
    r.lead_time = Sourced("16 Weeks", "mouser", "high")
    r.product_url = Sourced("http://x/p", "mouser", "high")
    r.dist_pns = {"mouser": "595-TPS62130RGTR"}
    assert r.filled_fields() == {"lifecycle", "lead_time", "product_url", "dist_pns"}


def test_merge_missing_fills_procurement_fields_only_when_empty():
    a = EnrichmentResult(category="ICs")
    a.lifecycle = Sourced("Active", "datasheet", "high")
    a.dist_pns = {"mouser": "595-KEEP"}
    b = EnrichmentResult(category="ICs")
    b.lifecycle = Sourced("NRND", "scrape", "low")  # a already filled: must not overwrite
    b.lead_time = Sourced("12 Weeks", "scrape", "medium")  # a empty: take it
    b.dist_pns = {"mouser": "595-DROP", "lcsc": "C123"}  # per-key: keep mouser, add lcsc
    a.merge_missing(b)
    assert a.lifecycle.value == "Active"
    assert a.lifecycle.source == "datasheet"
    assert a.lead_time.value == "12 Weeks"
    assert a.dist_pns == {"mouser": "595-KEEP", "lcsc": "C123"}
