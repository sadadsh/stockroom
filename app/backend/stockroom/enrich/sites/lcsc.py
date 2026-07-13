"""LCSC product-page extractor. The generic cascade (JSON-LD/OG) carries MPN,
manufacturer, description, and price; this module adds only the LCSC-specific
extras the generic layers miss: the package and the parameter spec-table rows
(spec section 6.1, per-site extractor modules tier). Deliberately narrow."""

from __future__ import annotations

import re
from html import unescape

from stockroom.enrich.schema import EnrichmentResult, Sourced

# Match <td>Label</td><td>Value</td> spec-table rows without a DOM library. Two
# stdlib-regex captures over a known table shape is enough; we are NOT doing
# open-ended CSS scraping (spec section 6.1: structured data first).
_ROW = re.compile(
    r"<t[dh][^>]*>\s*([^<]{1,60}?)\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<]{1,120}?)\s*</t[dh]>",
    re.IGNORECASE | re.DOTALL,
)
_PACKAGE_LABELS = {"package", "package/case", "package / case", "footprint"}


class LcscSite:
    def matches(self, url: str) -> bool:
        return "lcsc.com" in url.lower()

    def extract(self, html: str, url: str) -> EnrichmentResult:
        r = EnrichmentResult()
        for label, value in _ROW.findall(html):
            label = unescape(label).strip()
            value = unescape(value).strip()
            if not value:
                continue
            if label.lower() in _PACKAGE_LABELS and r.package is None:
                r.package = Sourced(value, "lcsc", "medium")
            else:
                r.specs.setdefault(label, Sourced(value, "lcsc", "medium"))
        return r
