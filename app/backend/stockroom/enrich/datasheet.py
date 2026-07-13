"""The datasheet: enrichment's ban-proof PRIMARY source (spec section 6.1 item 3).

A datasheet PDF never rate-limits, never bans, never redesigns. Follow the link
with a real browser User-Agent (the HttpFetcher impersonates Chrome) plus a
Referer, retry once on a transport blip, and accept ONLY a real PDF, validated by
a PDF Content-Type OR the %PDF- magic number, so a silent HTML "unavailable" page
is never stored as a .pdf (research: reject the HTML wrapper). Spec extraction
from the stored PDF is extract_datasheet_specs (Task 9)."""

from __future__ import annotations

from pathlib import Path

from stockroom.enrich.errors import EnrichError

_PDF_CONTENT_TYPES = ("application/pdf", "application/x-pdf", "application/octet-stream")


def looks_like_pdf(content: bytes) -> bool:
    return content[:5] == b"%PDF-"


def _is_pdf(content_type: str, content: bytes) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    return looks_like_pdf(content) or ct in _PDF_CONTENT_TYPES


def fetch_datasheet(url, dst: Path, fetcher=None, referer: str = "") -> Path:
    from stockroom.enrich.fetch import HttpFetcher

    fetcher = fetcher or HttpFetcher()
    dst = Path(dst)
    last_exc: Exception | None = None
    result = None
    for _ in range(2):  # one retry over the same HTTP/1.1 path on a transport blip
        try:
            result = fetcher.get(url, referer=referer)
            break
        except EnrichError as exc:
            last_exc = exc
            result = None
    if result is None:
        raise EnrichError(f"datasheet fetch failed for {url}: {last_exc}")
    if not (200 <= result.status < 300):
        raise EnrichError(f"datasheet fetch got status {result.status} for {url}")
    if not _is_pdf(result.content_type, result.content):
        raise EnrichError(
            f"datasheet at {url} is not a PDF (content-type {result.content_type!r}); "
            "refusing to store an HTML wrapper as a .pdf"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(result.content)
    return dst
