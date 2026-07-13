"""The datasheet: enrichment's ban-proof PRIMARY source (spec section 6.1 item 3).

A datasheet PDF never rate-limits, never bans, never redesigns. Follow the link
with a real browser User-Agent (the HttpFetcher impersonates Chrome) plus a
Referer, retry once on a transport blip, and accept ONLY a real PDF, validated by
a PDF Content-Type OR the %PDF- magic number, so a silent HTML "unavailable" page
is never stored as a .pdf (research: reject the HTML wrapper). Spec extraction
from the stored PDF is extract_datasheet_specs (Task 9)."""

from __future__ import annotations

import re
from pathlib import Path

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.schema import EnrichmentResult, Sourced

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


# Known package families, scanned for in the datasheet text (extend as needed).
_PACKAGE_RE = re.compile(
    r"\b(?:VQFN|QFN|LQFP|TQFP|TSSOP|SSOP|SOIC|SOT-?23|SOT-?223|DFN|BGA|WLCSP|MSOP|DIP)"
    r"(?:-?\d+)?\b",
    re.IGNORECASE,
)
# A small known-manufacturer set; a hit in the text confirms the manufacturer.
_MANUFACTURERS = (
    "Texas Instruments", "STMicroelectronics", "Analog Devices", "Microchip",
    "NXP", "Infineon", "onsemi", "ON Semiconductor", "Nexperia", "Vishay",
    "Murata", "TDK", "Diodes Incorporated", "Renesas", "Maxim Integrated",
)
_PIN_RE = re.compile(r"\bPIN\s+(\d+)\s+([A-Z][A-Z0-9_/+-]{0,15})", re.IGNORECASE)


def _pdf_text(pdf_path) -> tuple[str, dict]:
    """First-few-pages text plus the document-info metadata, or ("", {}) on any
    failure (a malformed datasheet yields an honest partial result, never an
    exception)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # dependency not installed yet
        raise EnrichError("pypdf is required for datasheet extraction") from exc
    try:
        reader = PdfReader(str(pdf_path))
        text_parts = []
        for page in reader.pages[:4]:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page must not sink the rest
                continue
        info = {}
        try:
            meta = reader.metadata or {}
            info = {str(k): str(v) for k, v in meta.items()}
        except Exception:  # noqa: BLE001
            info = {}
        return "\n".join(text_parts), info
    except Exception:  # noqa: BLE001 - a corrupt PDF is a partial result, not a crash
        return "", {}


def extract_datasheet_specs(pdf_path, known_mpn: str = "") -> EnrichmentResult:
    r = EnrichmentResult()
    text, info = _pdf_text(pdf_path)
    haystack = f"{text}\n{' '.join(info.values())}"
    if not haystack.strip():
        return r
    upper = haystack.upper()

    if known_mpn and known_mpn.upper() in upper:
        r.mpn = Sourced(known_mpn, "datasheet", "high")

    for man in _MANUFACTURERS:
        if man.upper() in upper:
            r.manufacturer = Sourced(man, "datasheet", "high")
            break

    pkg = _PACKAGE_RE.search(haystack)
    if pkg:
        r.package = Sourced(pkg.group(0).upper(), "datasheet", "high")

    pins = []
    for num, name in _PIN_RE.findall(text):
        pins.append({"pin": num, "name": name})
    if pins:
        r.specs["pinout"] = Sourced(pins, "datasheet", "high")
    return r
