from pathlib import Path

import pytest

from stockroom.enrich.datasheet import (
    extract_datasheet_specs,
    fetch_datasheet,
    looks_like_pdf,
)
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


def test_fetch_datasheet_rejects_html_served_as_octet_stream(tmp_path):
    # a generic application/octet-stream Content-Type must NOT alone qualify: the
    # body is HTML, so without %PDF- magic it is refused (never store a wrapper).
    body = b"<!doctype html><html><body>unavailable</body></html>"
    res = FetchResult("u", 200, body.decode(), body, "application/octet-stream", "u")
    with pytest.raises(EnrichError):
        fetch_datasheet("https://x/d.pdf", tmp_path / "d.pdf", fetcher=_StubFetcher(res))
    assert not (tmp_path / "d.pdf").exists()


def test_fetch_datasheet_accepts_pdf_bytes_served_as_octet_stream(tmp_path):
    # octet-stream IS fine when the magic bytes confirm a real PDF (common for CDNs)
    data = (FIX / "sample_datasheet.pdf").read_bytes()
    res = FetchResult("u", 200, data.decode("latin-1"), data, "application/octet-stream", "u")
    out = fetch_datasheet("https://x/d.pdf", tmp_path / "d.pdf", fetcher=_StubFetcher(res))
    assert out.read_bytes().startswith(b"%PDF-")


def test_extract_datasheet_specs_reads_mpn_manufacturer_package():
    r = extract_datasheet_specs(FIX / "sample_datasheet.pdf", known_mpn="TPS62130RGTR")
    assert r.mpn.value == "TPS62130RGTR"
    assert r.mpn.source == "datasheet"
    assert r.mpn.confidence == "high"
    assert "Texas Instruments" in (r.manufacturer.value or "")
    assert r.package.value == "VQFN-16"


def test_extract_datasheet_specs_is_lenient_on_a_bad_pdf(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\nnot really a pdf\n%%EOF\n")
    r = extract_datasheet_specs(bad)  # must not raise
    assert r.filled_fields() == set() or r.mpn is None


def test_datasheet_fill_reads_identity_from_the_stored_pdf(tmp_path, monkeypatch):
    # the user handed us the datasheet (URL or file); its extraction is the
    # primary identity source and fills only what is still blank
    from stockroom.enrich.pipeline import EnrichmentPipeline
    from stockroom.enrich.schema import EnrichmentResult, Sourced
    from stockroom.ingest.staging import StagingCandidate

    def fake_extract(pdf_path, known_mpn=""):
        return EnrichmentResult(
            category="ICs",
            mpn=Sourced(value="TPS62130RGTR", source="datasheet", confidence=0.9),
            manufacturer=Sourced(value="Texas Instruments", source="datasheet", confidence=0.9),
        )

    monkeypatch.setattr("stockroom.enrich.datasheet.extract_datasheet_specs", fake_extract)
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    pipeline = EnrichmentPipeline(tmp_path / "cache")
    c = StagingCandidate(
        vendor="snapeda", symbol_lib_path=None, symbol_name="X",
        footprint_variants=[], datasheet_path=pdf,
        manufacturer="Already Set", category="ICs",
    )
    pipeline.datasheet_fill(c)
    assert c.mpn == "TPS62130RGTR"  # blank -> filled from the datasheet
    assert c.manufacturer == "Already Set"  # never overwrites a value


def test_datasheet_fill_without_a_datasheet_is_a_no_op(tmp_path):
    from stockroom.enrich.pipeline import EnrichmentPipeline
    from stockroom.ingest.staging import StagingCandidate

    c = StagingCandidate(vendor="snapeda", symbol_lib_path=None, symbol_name="X",
                         footprint_variants=[])
    out = EnrichmentPipeline(tmp_path / "cache").datasheet_fill(c)
    assert out.mpn == ""
