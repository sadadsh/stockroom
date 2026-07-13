"""Structured-data-FIRST extraction cascade over fetched HTML.

Priority is machine-readable and redesign-stable sources first, CSS-style
heuristics last (spec section 6.1, item 2): schema.org JSON-LD Product (high
confidence), then OpenGraph/meta (medium), then embedded JS state such as
__NEXT_DATA__ (medium), then per-site extractor modules, then a title/h1
heuristic (low). Every field is normalized into Stockroom's own canonical schema
and stamped with its source and confidence, so a later higher-trust source (the
datasheet) can be preferred over a lower-trust one."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Protocol, runtime_checkable

from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced


@runtime_checkable
class SiteExtractor(Protocol):
    def matches(self, url: str) -> bool: ...
    def extract(self, html: str, url: str) -> EnrichmentResult: ...


_SCRIPT_LD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_NEXT = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _first_str(*vals) -> str:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _iter_ld_objects(blob):
    """Yield every dict in a JSON-LD payload, walking @graph and lists."""
    if isinstance(blob, list):
        for item in blob:
            yield from _iter_ld_objects(item)
    elif isinstance(blob, dict):
        yield blob
        if "@graph" in blob:
            yield from _iter_ld_objects(blob["@graph"])


def _brand_name(brand) -> str:
    if isinstance(brand, dict):
        return _first_str(brand.get("name"))
    return _first_str(brand)


def _offers_to_breaks(offers) -> tuple[list[PriceBreak], bool]:
    breaks: list[PriceBreak] = []
    in_stock = False
    seq = offers if isinstance(offers, list) else [offers]
    for off in seq:
        if not isinstance(off, dict):
            continue
        price = off.get("price")
        currency = _first_str(off.get("priceCurrency")) or "USD"
        if price is not None:
            try:
                breaks.append(PriceBreak(qty=1, price=float(price), currency=currency))
            except (TypeError, ValueError):
                pass
        avail = _first_str(off.get("availability")).lower()
        if "instock" in avail or "in_stock" in avail:
            in_stock = True
    return breaks, in_stock


def extract_jsonld_product(html: str) -> EnrichmentResult:
    r = EnrichmentResult()
    for raw in _SCRIPT_LD.findall(html):
        try:
            blob = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for obj in _iter_ld_objects(blob):
            types = obj.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" not in types:
                continue
            mpn = _first_str(obj.get("mpn"), obj.get("productID"))
            if mpn:
                r.mpn = Sourced(mpn, "jsonld", "high")
            man = _brand_name(obj.get("brand")) or _first_str(obj.get("manufacturer"))
            if man:
                r.manufacturer = Sourced(man, "jsonld", "high")
            desc = _first_str(obj.get("description"), obj.get("name"))
            if desc:
                r.description = Sourced(desc, "jsonld", "high")
            breaks, in_stock = _offers_to_breaks(obj.get("offers"))
            if breaks:
                r.price_breaks = breaks
            if in_stock:
                r.stock = Sourced(1, "jsonld", "medium")
            return r  # first Product wins
    return r


class _MetaSweep(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name")
            content = a.get("content")
            if key and content:
                self.meta[key.lower()] = content
        elif tag == "title":
            self._in_title = True
        elif tag == "h1" and not self.title:
            self._in_title = "h1"  # reuse to capture first h1 text too

    def handle_endtag(self, tag):
        if tag in ("title", "h1"):
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title and data.strip():
            self.title = data.strip()


def extract_opengraph(html: str) -> EnrichmentResult:
    r = EnrichmentResult()
    sweep = _MetaSweep()
    sweep.feed(html)
    m = sweep.meta
    desc = _first_str(m.get("og:description"), m.get("description"))
    title = _first_str(m.get("og:title"))
    if desc:
        r.description = Sourced(desc, "opengraph", "medium")
    elif title:
        r.description = Sourced(title, "opengraph", "medium")
    return r


def _walk_json(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_json(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_json(v)


def extract_next_data(html: str) -> EnrichmentResult:
    r = EnrichmentResult()
    m = _SCRIPT_NEXT.search(html)
    if not m:
        return r
    try:
        blob = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return r
    for node in _walk_json(blob):
        mpn = _first_str(node.get("manufacturerPartNumber"), node.get("mpn"))
        man = _first_str(node.get("manufacturer"))
        pkg = _first_str(node.get("package"), node.get("packageType"))
        desc = _first_str(node.get("description"))
        if mpn and r.mpn is None:
            r.mpn = Sourced(mpn, "next_data", "medium")
        if man and r.manufacturer is None:
            r.manufacturer = Sourced(man, "next_data", "medium")
        if pkg and r.package is None:
            r.package = Sourced(pkg, "next_data", "medium")
        if desc and r.description is None:
            r.description = Sourced(desc, "next_data", "medium")
    return r


def _heuristic(html: str) -> EnrichmentResult:
    r = EnrichmentResult()
    sweep = _MetaSweep()
    sweep.feed(html)
    if sweep.title:
        r.description = Sourced(sweep.title, "heuristic", "low")
    return r


def extract_all(html: str, url: str, site_extractors: tuple = ()) -> EnrichmentResult:
    result = extract_jsonld_product(html)
    result.merge_missing(extract_opengraph(html))
    result.merge_missing(extract_next_data(html))
    for ext in site_extractors:
        if ext.matches(url):
            result.merge_missing(ext.extract(html, url))
    result.merge_missing(_heuristic(html))
    return result
