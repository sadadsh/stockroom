from stockroom.enrich.schema import (
    SCHEMA_VERSION,
    CanonicalSpecs,
    EnrichmentResult,
    PriceBreak,
    Sourced,
    mpn_identity_key,
    normalize_lifecycle,
    normalize_mpn,
)


def test_normalize_lifecycle_canonicalizes_distributor_tokens():
    # LCSC's "normal" and Mouser's "none" both mean a part in normal production = Active.
    assert normalize_lifecycle("normal") == "Active"
    assert normalize_lifecycle("none") == "Active"
    assert normalize_lifecycle("NRND") == "Not Recommended for New Designs"
    assert normalize_lifecycle("eol") == "End of Life"
    assert normalize_lifecycle("Active") == "Active"  # already canonical, unchanged
    # an unknown lower-case token is Title-cased (never shown verbatim), a cased one is kept
    assert normalize_lifecycle("preproduction") == "Preproduction"
    assert normalize_lifecycle("Some Vendor Status") == "Some Vendor Status"
    assert normalize_lifecycle("") == "" and normalize_lifecycle(None) is None


def test_normalize_mpn_is_filesystem_safe():
    assert normalize_mpn("TPS62130RGTR") == "TPS62130RGTR"
    assert normalize_mpn("tps62130rgtr") == "TPS62130RGTR"
    assert normalize_mpn("ABC/123") == "ABC-123"
    assert normalize_mpn("ABC\\123") == "ABC-123"
    assert normalize_mpn("ABC 123") == "ABC-123"
    # no path-separator or wildcard survives
    for ch in "/\\:*?\"<>|":
        assert ch not in normalize_mpn(f"A{ch}B")


def test_mpn_identity_key_is_case_tolerant_but_preserves_punctuation():
    assert mpn_identity_key(" abc/123+X ") == mpn_identity_key("ABC/123+x")
    assert mpn_identity_key("ABC/123+X") != mpn_identity_key("ABC-123+X")


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


# -- Spec conflicts (owner 2026-07-24: "display all of it and only merge stuff thats
# identical"): when two sources DISAGREE on a spec, BOTH values are kept and surfaced;
# identical values (normalized) merge silently as before.


def test_merge_missing_records_a_spec_conflict_when_values_differ():
    a = EnrichmentResult(category="ICs")
    a.specs["Resistance"] = Sourced("100 mOhm", "mouser", "high")
    b = EnrichmentResult(category="ICs")
    b.specs["Resistance"] = Sourced("105 mOhm", "digikey", "high")
    a.merge_missing(b)
    # the first source still wins the single-value slot (nothing overwritten)...
    assert a.specs["Resistance"].value == "100 mOhm"
    # ...but the disagreement is KEPT, both values with their sources
    conflict = a.spec_conflicts["Resistance"]
    assert [(s.value, s.source) for s in conflict] == [
        ("100 mOhm", "mouser"),
        ("105 mOhm", "digikey"),
    ]


def test_merge_missing_identical_values_merge_without_a_conflict():
    a = EnrichmentResult(category="ICs")
    a.specs["Tolerance"] = Sourced("1%", "mouser", "high")
    b = EnrichmentResult(category="ICs")
    # identical after normalization (case + surrounding space): NOT a conflict
    b.specs["Tolerance"] = Sourced(" 1% ", "digikey", "high")
    a.merge_missing(b)
    assert a.spec_conflicts == {}


def test_merge_missing_a_third_differing_value_joins_the_conflict_once():
    a = EnrichmentResult(category="ICs")
    a.specs["Vf"] = Sourced("0.7 V", "mouser", "high")
    b = EnrichmentResult(category="ICs")
    b.specs["Vf"] = Sourced("0.65 V", "digikey", "high")
    a.merge_missing(b)
    c = EnrichmentResult(category="ICs")
    c.specs["Vf"] = Sourced("0.65 V", "lcsc", "medium")  # same value again: no duplicate
    a.merge_missing(c)
    assert [s.value for s in a.spec_conflicts["Vf"]] == ["0.7 V", "0.65 V"]


def test_merge_missing_a_key_only_one_side_has_never_conflicts():
    a = EnrichmentResult(category="ICs")
    b = EnrichmentResult(category="ICs")
    b.specs["New Key"] = Sourced("x", "digikey", "high")
    a.merge_missing(b)
    assert a.specs["New Key"].value == "x"
    assert a.spec_conflicts == {}


# -- Field conflicts (Batch 3, punch 2/9). The single-slot canonical fields lost every
# losing value with no record at all: two distributors' descriptions, datasheet links,
# packages and lifecycles all resolved to whichever source ran first and the other was
# DROPPED. A disagreement on a shared fact is data (owner: "see ALL DigiKey + Mouser
# data"), so it is kept with its source exactly the way a spec disagreement is.


def test_merge_missing_keeps_both_descriptions_with_their_sources():
    a = EnrichmentResult(category="ICs")
    a.description = Sourced("3A Buck Converter", "mouser", "high")
    b = EnrichmentResult(category="ICs")
    b.description = Sourced("Step-Down Regulator, 3 A, WSON-8", "digikey", "high")
    a.merge_missing(b)
    # the first source still wins the single-value slot
    assert a.description.value == "3A Buck Converter"
    # ...and the loser is no longer discarded
    assert [(s.value, s.source) for s in a.field_conflicts["description"]] == [
        ("3A Buck Converter", "mouser"),
        ("Step-Down Regulator, 3 A, WSON-8", "digikey"),
    ]


def test_merge_missing_identical_field_values_merge_without_a_conflict():
    a = EnrichmentResult(category="ICs")
    a.manufacturer = Sourced("Texas Instruments", "mouser", "high")
    b = EnrichmentResult(category="ICs")
    b.manufacturer = Sourced(" texas instruments ", "digikey", "high")
    a.merge_missing(b)
    assert a.field_conflicts == {}


def test_merge_missing_never_conflicts_a_per_vendor_field():
    """stock and product_url are per-vendor BY NATURE: each distributor legitimately has
    its own, and they live in dist_stock / dist_urls. Recording them as disagreements
    would bury the real ones in noise."""
    a = EnrichmentResult(category="ICs")
    a.stock = Sourced(1200, "mouser", "high")
    a.product_url = Sourced("https://mouser.com/x", "mouser", "high")
    b = EnrichmentResult(category="ICs")
    b.stock = Sourced(48, "digikey", "high")
    b.product_url = Sourced("https://digikey.com/y", "digikey", "high")
    a.merge_missing(b)
    assert a.field_conflicts == {}


def test_merge_missing_a_third_differing_field_value_joins_the_conflict_once():
    a = EnrichmentResult(category="ICs")
    a.package = Sourced("WSON-8", "mouser", "high")
    for source in ("digikey", "lcsc"):
        other = EnrichmentResult(category="ICs")
        other.package = Sourced("VSON-8", source, "high")
        a.merge_missing(other)
    assert [s.value for s in a.field_conflicts["package"]] == ["WSON-8", "VSON-8"]


def test_merge_missing_carries_the_other_sides_conflicts():
    """A partial can arrive ALREADY carrying disagreements (an adapter that merged two of
    its own answers, or a nested walk). merge_missing dropped both conflict maps
    entirely, so every disagreement found below the top level was silently lost."""
    a = EnrichmentResult(category="ICs")
    b = EnrichmentResult(category="ICs")
    b.specs["Vf"] = Sourced("0.7 V", "mouser", "high")
    b.spec_conflicts["Vf"] = [
        Sourced("0.7 V", "mouser", "high"), Sourced("0.65 V", "digikey", "high")
    ]
    b.description = Sourced("A", "mouser", "high")
    b.field_conflicts["description"] = [
        Sourced("A", "mouser", "high"), Sourced("B", "digikey", "high")
    ]
    a.merge_missing(b)
    assert [s.value for s in a.spec_conflicts["Vf"]] == ["0.7 V", "0.65 V"]
    assert [s.value for s in a.field_conflicts["description"]] == ["A", "B"]


def test_merge_missing_keeps_every_vendors_own_ladder_and_stock():
    """punch 4: the DigiKey sourcing row rendered with no price and no stock. merge_missing
    kept only the FIRST vendor's ladder and never merged the per-vendor maps at all, so a
    second distributor's prices existed on its partial and then vanished."""
    a = EnrichmentResult(category="ICs")
    a.dist_price_breaks["mouser"] = [PriceBreak(qty=1, price=1.5)]
    a.dist_stock["mouser"] = 1200
    b = EnrichmentResult(category="ICs")
    b.dist_price_breaks["digikey"] = [PriceBreak(qty=1, price=1.42)]
    b.dist_stock["digikey"] = 48
    a.merge_missing(b)
    assert sorted(a.dist_price_breaks) == ["digikey", "mouser"]
    assert a.dist_price_breaks["digikey"][0].price == 1.42
    assert a.dist_stock == {"mouser": 1200, "digikey": 48}


def test_merge_missing_can_merge_without_recording_a_conflict():
    """The six extraction techniques run over ONE document are the same authority read six
    ways; their disagreements are our parsing, not two vendors' answers. `extract_product`
    merges with record_conflicts=False so an og:title never becomes an "alternative
    description" competing with a real distributor's."""
    a = EnrichmentResult(category="ICs")
    a.description = Sourced("3A Buck Converter", "jsonld", "high")
    a.specs["Package"] = Sourced("WSON-8", "jsonld", "high")
    b = EnrichmentResult(category="ICs")
    b.description = Sourced("TPS62130 - Texas Instruments | Mouser", "opengraph", "medium")
    b.specs["Package"] = Sourced("VSON", "opengraph", "medium")
    a.merge_missing(b, record_conflicts=False)
    assert a.description.value == "3A Buck Converter"  # first still wins the slot
    assert a.field_conflicts == {} and a.spec_conflicts == {}
