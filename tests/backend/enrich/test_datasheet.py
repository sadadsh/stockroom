from pathlib import Path

import pytest

from stockroom.enrich.datasheet import fetch_datasheet, looks_like_pdf
from stockroom.enrich.errors import EnrichError
from stockroom.enrich.fetch import FetchResult

FIX = Path(__file__).parent / "fixtures"


class _StubFetcher:
    def __init__(self, result=None, raise_times=0):
        self._result = result
        self._raise_times = raise_times
        self.calls = 0

    def get(self, url, referer="", timeout=15.0):
        self.calls += 1
        if self.calls <= self._raise_times:
            raise EnrichError("transport blip")
        return self._result


def _pdf_result():
    data = (FIX / "sample_datasheet.pdf").read_bytes()
    return FetchResult("u", 200, data.decode("latin-1"), data, "application/pdf", "u")


def test_looks_like_pdf_checks_magic_bytes():
    assert looks_like_pdf(b"%PDF-1.7\n...")
    assert not looks_like_pdf(b"<!doctype html>")
    assert not looks_like_pdf(b"")


def test_fetch_datasheet_stores_a_valid_pdf(tmp_path):
    dst = tmp_path / "d.pdf"
    out = fetch_datasheet("https://x/d.pdf", dst, fetcher=_StubFetcher(_pdf_result()))
    assert out == dst
    assert out.read_bytes().startswith(b"%PDF-")


def test_fetch_datasheet_rejects_an_html_wrapper(tmp_path):
    data = (FIX / "not_a_pdf.html").read_bytes()
    html_result = FetchResult("u", 200, data.decode(), data, "text/html", "u")
    with pytest.raises(EnrichError):
        fetch_datasheet("https://x/d.pdf", tmp_path / "d.pdf", fetcher=_StubFetcher(html_result))
    assert not (tmp_path / "d.pdf").exists()  # nothing stored


def test_fetch_datasheet_retries_once_on_transport_error(tmp_path):
    f = _StubFetcher(_pdf_result(), raise_times=1)
    out = fetch_datasheet("https://x/d.pdf", tmp_path / "d.pdf", fetcher=f)
    assert out.exists()
    assert f.calls == 2  # failed once, retried, succeeded


def test_fetch_datasheet_rejects_a_non_2xx_status(tmp_path):
    bad = FetchResult("u", 404, "nope", b"nope", "text/html", "u")
    with pytest.raises(EnrichError):
        fetch_datasheet("https://x/d.pdf", tmp_path / "d.pdf", fetcher=_StubFetcher(bad))
