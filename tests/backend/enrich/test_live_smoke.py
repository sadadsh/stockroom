"""Opt-in live smoke suite. Deselected by default (addopts: -m 'not live_enrich').
Run explicitly with: uv run pytest -m live_enrich. These hit the real network and
are NOT part of the CI default run; they exist to catch scraper rot against real
sites, which the ecosystem research warns is inevitable."""

import pytest

pytestmark = pytest.mark.live_enrich


def test_live_lcsc_product_page_yields_an_mpn():
    from stockroom.enrich.fetch import HttpRenderedDomFetcher
    from stockroom.enrich.pipeline import ScrapeSource, _default_url_for

    fetcher = HttpRenderedDomFetcher()

    class _Limiter:
        def acquire(self):
            pass

    src = ScrapeSource(fetcher=fetcher, limiter=_Limiter(),
                       url_for=lambda mpn, cat: "https://www.lcsc.com/product-detail/C7442.html")
    r = src.enrich("LM358", "ICs", remaining={"mpn", "manufacturer"})
    # a structured-data field should come back; if not, the scraper has rotted
    assert r.mpn is not None or r.manufacturer is not None


def test_live_datasheet_fetch_stores_a_pdf(tmp_path):
    from stockroom.enrich.datasheet import fetch_datasheet

    dst = fetch_datasheet(
        "https://www.ti.com/lit/ds/symlink/lm358.pdf", tmp_path / "lm358.pdf"
    )
    assert dst.read_bytes().startswith(b"%PDF-")
