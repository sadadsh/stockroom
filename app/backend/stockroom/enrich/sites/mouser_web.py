"""Mouser product-WEB-page extractor (distinct from the optional Mouser API in
mouser.py). Adds package/spec extras the generic cascade misses. Narrow."""

from __future__ import annotations

import re
from html import unescape

from stockroom.enrich.schema import EnrichmentResult, Sourced

_ROW = re.compile(
    r"<t[dh][^>]*>\s*([^<]{1,60}?)\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<]{1,120}?)\s*</t[dh]>",
    re.IGNORECASE | re.DOTALL,
)
_PACKAGE_LABELS = {"package / case", "package", "case/package", "mounting style"}


class MouserWebSite:
    def matches(self, url: str) -> bool:
        return "mouser.com" in url.lower()

    def extract(self, html: str, url: str) -> EnrichmentResult:
        r = EnrichmentResult()
        for label, value in _ROW.findall(html):
            label = unescape(label).strip()
            value = unescape(value).strip()
            if not value:
                continue
            if label.lower() in _PACKAGE_LABELS and r.package is None:
                r.package = Sourced(value, "mouser_web", "medium")
            else:
                r.specs.setdefault(label, Sourced(value, "mouser_web", "medium"))
        return r
