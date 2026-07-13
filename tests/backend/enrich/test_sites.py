from stockroom.enrich.extract import SiteExtractor
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.enrich.sites.lcsc import LcscSite


def test_registered_extractors_all_satisfy_the_protocol():
    assert SITE_EXTRACTORS  # non-empty
    for ext in SITE_EXTRACTORS:
        assert isinstance(ext, SiteExtractor)


def test_lcsc_matches_only_lcsc_urls():
    s = LcscSite()
    assert s.matches("https://www.lcsc.com/product-detail/C123456.html")
    assert not s.matches("https://www.mouser.com/x")


def test_lcsc_extracts_package_from_a_spec_row():
    s = LcscSite()
    html = (
        '<table><tr><td>Package</td><td>VQFN-16</td></tr>'
        '<tr><td>Operating Temperature</td><td>-40C to 125C</td></tr></table>'
    )
    r = s.extract(html, "https://www.lcsc.com/product-detail/C1.html")
    assert r.package.value == "VQFN-16"
    assert r.package.confidence == "medium"
    assert r.specs.get("Operating Temperature").value == "-40C to 125C"
