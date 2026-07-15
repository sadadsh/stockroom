"""Mouser product-WEB-page extractor (distinct from the optional Mouser API in
mouser.py). Adds package/spec extras the generic cascade misses. Narrow.

Mouser renders its parametric spec table as attr-col / attr-value-col cell pairs
whose label sits inside a nested <label> tag, e.g.

    <tr id="...pdp_specs_SpecList..."><td class="attr-col"><label>Resistance:</label>
    </td><td class="attr-value-col">1.1 kOhms</td></tr>

The nested tag means the old plain-text _ROW regex (which uses [^<]) captures
nothing, so the real spec table is parsed here from the attr-col structure, with
_ROW kept as a fallback for older/simpler pages that still emit bare cells."""

from __future__ import annotations

import re
from html import unescape

from stockroom.enrich.schema import EnrichmentResult, Sourced

# Mouser embeds the real datasheet URL in its analytics dataLayer as
# `event_datasheet_url`, both raw ("event_datasheet_url":"https://...pdf") and
# HTML-escaped (&quot;event_datasheet_url&quot;:&quot;https://...pdf&quot;). This is the
# reliable one: the page also carries PCN / catalog PDFs as plain anchors, which are NOT
# the part datasheet, so a blind "first .pdf link" would grab the wrong file.
_MOUSER_DATASHEET = re.compile(
    r"event_datasheet_url(?:&quot;|[\"'])?\s*:\s*(?:&quot;|[\"'])(https?://[^\"'&\s\\]+)",
    re.IGNORECASE,
)

# Bare-cell fallback for older/simpler pages: <td>label</td><td>value</td> with no
# nested markup. Kept as a fallback, applied only when the attr-col pass finds nothing.
_ROW = re.compile(
    r"<t[dh][^>]*>\s*([^<]{1,60}?)\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<]{1,120}?)\s*</t[dh]>",
    re.IGNORECASE | re.DOTALL,
)

# Real Mouser parametric table: an attr-col cell (the label, usually inside a nested
# <label>) immediately followed by an attr-value-col cell (the value). Other classes
# and attributes on either <td> are allowed; nested tags inside each cell are stripped
# after capture. "attr-col" is not a substring of "attr-value-col", so the two never
# cross-match.
_ATTR_PAIR = re.compile(
    r"<td[^>]*\battr-col\b[^>]*>(.*?)</td>\s*"
    r"<td[^>]*\battr-value-col\b[^>]*>(.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)

# Strips every nested tag from a captured cell so <label>Resistance:</label> -> text.
_TAGS = re.compile(r"<[^>]+>")

_PACKAGE_LABELS = {"package / case", "package", "case/package", "mounting style"}


def _clean(cell: str) -> str:
    """Strip all nested tags, unescape entities, and trim a captured table cell."""
    return unescape(_TAGS.sub("", cell)).strip()


class MouserWebSite:
    def matches(self, url: str) -> bool:
        return "mouser.com" in url.lower()

    def extract(self, html: str, url: str) -> EnrichmentResult:
        r = EnrichmentResult()
        # The datasheet Mouser marks in its dataLayer (the manufacturer PDF), not a PCN
        # or catalog PDF. Only accept a value that looks like a real datasheet.
        m = _MOUSER_DATASHEET.search(html)
        if m:
            ds = unescape(m.group(1))
            v = ds.lower()
            if v.startswith("http") and (v.endswith(".pdf") or "datasheet" in v or ".pdf?" in v):
                r.datasheet_url = Sourced(ds, "mouser_web", "medium")
        found = False
        for raw_label, raw_value in _ATTR_PAIR.findall(html):
            label = _clean(raw_label).rstrip(":").strip()
            value = _clean(raw_value)
            if not label or not value:
                continue
            found = True
            if label.lower() in _PACKAGE_LABELS and r.package is None:
                r.package = Sourced(value, "mouser_web", "medium")
            else:
                r.specs.setdefault(label, Sourced(value, "mouser_web", "medium"))
        # Fallback ONLY when the real attr-col table was absent, so simple/older pages
        # with bare <td>label</td><td>value</td> cells still enrich.
        if not found:
            for label, value in _ROW.findall(html):
                label = unescape(label).strip().rstrip(":").strip()
                value = unescape(value).strip()
                if not label or not value:
                    continue
                if label.lower() in _PACKAGE_LABELS and r.package is None:
                    r.package = Sourced(value, "mouser_web", "medium")
                else:
                    r.specs.setdefault(label, Sourced(value, "mouser_web", "medium"))
        return r
