from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced
from stockroom.scrape.validate import (
    is_pdf_bytes, sane_price_breaks, valid_mpn, valid_url, validate_product,
)


def test_pdf_magic():
    assert is_pdf_bytes(b"%PDF-1.7 ...")
    assert not is_pdf_bytes(b"<html>nope")


def test_valid_mpn_charset():
    assert valid_mpn("LM317T") and valid_mpn("ERJ-P03F1101V")
    assert not valid_mpn("") and not valid_mpn("bad<>chars") and not valid_mpn("x" * 65)


def test_valid_url():
    assert valid_url("https://x/y") and not valid_url("javascript:void(0)")
    assert not valid_url("/relative") and not valid_url("")


def test_sane_price_breaks_drops_anomalies_and_sorts():
    breaks = [PriceBreak(1000, 0.10), PriceBreak(1, 0.50),
              PriceBreak(10, 0.60), PriceBreak(100, -1.0)]
    out = sane_price_breaks(breaks)
    assert [(b.qty, b.price) for b in out] == [(1, 0.5), (1000, 0.1)]
    # qty=10 dropped (0.60 > 0.50 at higher qty); qty=100 dropped (price <= 0)


def test_validate_product_drops_bad_fields_keeps_good():
    r = EnrichmentResult()
    r.mpn = Sourced("bad<mpn>", "jsonld", "high")
    r.stock = Sourced(-5, "scrape", "medium")
    r.datasheet_url = Sourced("not a url", "scrape", "low")
    r.package = Sourced("SOT-23", "scrape", "medium")
    r.price_breaks = [PriceBreak(1, 0.5), PriceBreak(100, 0.4)]
    out = validate_product(r)
    assert out.mpn is None and out.stock is None and out.datasheet_url is None
    assert out.package.value == "SOT-23"                 # plain text kept
    assert [b.qty for b in out.price_breaks] == [1, 100]  # good ladder kept


def test_validate_product_never_raises_on_weird_types():
    r = EnrichmentResult()
    r.stock = Sourced("not-an-int", "scrape", "low")
    assert validate_product(r).stock is None
