"""Structured-data-FIRST extraction over fetched HTML (scrape layer, spec section 3).

Priority is machine-readable and redesign-stable sources first: schema.org JSON-LD
Product (high), then OpenGraph/meta (medium), embedded JS state such as __NEXT_DATA__
and __NUXT__ (medium), and schema.org microdata (medium). Every field is normalized
into Stockroom's own canonical schema (enrich.schema, the shared component contract)
and stamped with its source and confidence, so a later higher-trust source (the
datasheet) can be preferred. The JSON-LD/OpenGraph/__NEXT_DATA__ extractors are ported
verbatim from the corpus-tuned enrich/extract.py; microdata, __NUXT__, and the raw
structured_blobs collector are new in S3. The cascade orchestrator (extract_product /
extract_all) and the SiteExtractor protocol live in extract/__init__.py."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

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


# JSON-LD keys a distributor Product commonly carries a datasheet link under. Kept
# narrow: only an explicit datasheet field, never a generic "url" (which is the
# product page, not the PDF), so we never mislabel a product URL as a datasheet.
_DATASHEET_KEYS = ("datasheet", "datasheetUrl", "datasheetURL", "datasheet_url")


def _looks_like_datasheet_url(val: str) -> bool:
    v = val.strip().lower()
    return v.startswith("http") and (v.endswith(".pdf") or "datasheet" in v or ".pdf?" in v)


def _datasheet_url(obj: dict) -> str:
    """Pull a datasheet URL from a JSON-LD Product: an explicit datasheet key, or a
    schema.org additionalProperty whose name mentions 'datasheet'. Only a URL that
    actually looks like a datasheet (PDF/datasheet path) is accepted, so a product
    page is never mislabelled as the datasheet."""
    for key in _DATASHEET_KEYS:
        cand = _first_str(obj.get(key))
        if cand and _looks_like_datasheet_url(cand):
            return cand
    props = obj.get("additionalProperty")
    for prop in props if isinstance(props, list) else []:
        if not isinstance(prop, dict):
            continue
        name = _first_str(prop.get("name")).lower()
        val = _first_str(prop.get("value"), prop.get("url"))
        if "datasheet" in name and val and _looks_like_datasheet_url(val):
            return val
    return ""


def _inventory_level(off: dict) -> int | None:
    """schema.org inventoryLevel is a genuine numeric stock count (a QuantitativeValue or a
    bare number), distinct from the availability flag (a boolean we never fabricate into a
    count). Returns the count when present and parseable, else None."""
    lvl = off.get("inventoryLevel")
    if isinstance(lvl, dict):
        lvl = lvl.get("value")
    if lvl is None or isinstance(lvl, bool):
        return None
    try:
        return int(float(lvl))
    except (TypeError, ValueError):
        return None


def _offers_to_breaks(offers) -> tuple[list[PriceBreak], bool, int | None]:
    breaks: list[PriceBreak] = []
    in_stock = False
    inventory: int | None = None
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
        if inventory is None:
            inventory = _inventory_level(off)
    return breaks, in_stock, inventory


def extract_jsonld_product(html: str) -> EnrichmentResult:
    r = EnrichmentResult()
    for raw in _SCRIPT_LD.findall(html):
        try:
            blob = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError, RecursionError):
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
            ds = _datasheet_url(obj)
            if ds:
                r.datasheet_url = Sourced(ds, "jsonld", "high")
            breaks, _in_stock, inventory = _offers_to_breaks(obj.get("offers"))
            if breaks:
                r.price_breaks = breaks
            # A schema.org availability flag is a BOOLEAN, not a stock count: never fabricate
            # it into stock=1 (roadmap #12). But inventoryLevel IS a real numeric stock, so
            # take it when the offer carries one; an offer with none leaves stock None (honest).
            if inventory is not None:
                r.stock = Sourced(inventory, "jsonld", "medium")
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
    except (json.JSONDecodeError, ValueError, RecursionError):
        return r
    for node in _walk_json(blob):
        mpn = _first_str(node.get("manufacturerPartNumber"), node.get("mpn"))
        man = _first_str(node.get("manufacturer"))
        pkg = _first_str(node.get("package"), node.get("packageType"))
        desc = _first_str(node.get("description"))
        ds = _first_str(node.get("datasheet"), node.get("datasheetUrl"),
                        node.get("datasheetURL"), node.get("datasheet_url"))
        if mpn and r.mpn is None:
            r.mpn = Sourced(mpn, "next_data", "medium")
        if man and r.manufacturer is None:
            r.manufacturer = Sourced(man, "next_data", "medium")
        if pkg and r.package is None:
            r.package = Sourced(pkg, "next_data", "medium")
        if desc and r.description is None:
            r.description = Sourced(desc, "next_data", "medium")
        if ds and r.datasheet_url is None and _looks_like_datasheet_url(ds):
            r.datasheet_url = Sourced(ds, "next_data", "medium")
    return r


def _heuristic(html: str) -> EnrichmentResult:
    r = EnrichmentResult()
    sweep = _MetaSweep()
    sweep.feed(html)
    if sweep.title:
        r.description = Sourced(sweep.title, "heuristic", "low")
    return r


# --- NEW structured sources (S3): microdata + __NUXT__, plus a raw-blob collector ---

_MICRODATA_MPN = ("mpn", "productid", "sku", "model")


def _itemprop_map(scope) -> dict[str, str]:
    """Collect itemprop -> value for ONE microdata scope (a selectolax node), obeying
    schema.org ownership: a property belongs to the nearest enclosing itemscope, so a
    nested item (an Offer/Brand) and everything under it is skipped, never flattened into
    the outer Product. A <meta> uses @content; else the node text. First value per prop
    wins. (selectolax `.css` can't express this and bare boolean attributes read as None
    via `.get`, so this is a manual descent using `"itemscope" in attributes`.)"""
    out: dict[str, str] = {}

    def _walk(node, depth: int) -> None:
        if depth > 60:
            return
        for child in node.iter(include_text=False):
            has_scope = "itemscope" in child.attributes
            prop = (child.attributes.get("itemprop") or "").strip().lower()
            if prop and not has_scope and prop not in out:
                val = (child.attributes.get("content") or child.text(deep=True) or "").strip()
                if val:
                    out[prop] = val
            if has_scope:
                continue  # a nested item: don't capture its value, don't descend into it
            _walk(child, depth + 1)

    _walk(scope, 0)
    return out


def extract_microdata(html: str) -> EnrichmentResult:
    """schema.org microdata Product (itemscope/itemprop). Medium confidence: it is
    author-declared structured data but weaker than a JSON-LD Product."""
    from stockroom.scrape.extract.html import parse

    r = EnrichmentResult()
    scope = None
    for node in parse(html).css("[itemscope][itemtype]"):
        if "product" in (node.attributes.get("itemtype") or "").lower():
            scope = node
            break
    if scope is None:
        return r
    props = _itemprop_map(scope)
    for key in _MICRODATA_MPN:
        if props.get(key):
            r.mpn = Sourced(props[key], "microdata", "medium")
            break
    brand = props.get("brand") or props.get("manufacturer")
    if brand:
        r.manufacturer = Sourced(brand, "microdata", "medium")
    desc = props.get("description") or props.get("name")
    if desc:
        r.description = Sourced(desc, "microdata", "medium")
    price = props.get("price")
    if price:
        try:
            r.price_breaks = [PriceBreak(qty=1, price=float(price),
                                         currency=props.get("pricecurrency") or "USD")]
        except (TypeError, ValueError):
            pass
    return r


def _decode_object_after(html: str, marker: str):
    """Find `marker` then JSON-decode the object literal that follows, using raw_decode so
    a trailing statement after the object (window.__NUXT__={...};window.foo=1) does not
    break it. Only a plain `= {...}` assignment is decoded; an IIFE/function form is
    skipped (returns None) rather than mis-parsed, so no bad data is invented. Never raises."""
    idx = html.find(marker)
    if idx < 0:
        return None
    rest = html[idx + len(marker):]
    brace = rest.find("{")
    if brace < 0:
        return None
    if rest[:brace].strip(" =\t\r\n") != "":
        return None  # not a plain-object assignment (e.g. an IIFE) -> skip, never guess
    try:
        obj, _end = json.JSONDecoder().raw_decode(rest[brace:])
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None
    return obj if isinstance(obj, (dict, list)) else None


def extract_nuxt(html: str) -> EnrichmentResult:
    """Nuxt.js SSR state (window.__NUXT__ = {...}): walk it like __NEXT_DATA__ for the
    same part fields. Medium confidence. A non-JSON, IIFE, or absent blob contributes
    nothing (never a wrong value)."""
    r = EnrichmentResult()
    blob = _decode_object_after(html, "window.__NUXT__")
    if blob is None:
        return r
    for node in _walk_json(blob):
        mpn = _first_str(node.get("manufacturerPartNumber"), node.get("mpn"))
        man = _first_str(node.get("manufacturer"), node.get("brand"))
        pkg = _first_str(node.get("package"), node.get("packageType"))
        desc = _first_str(node.get("description"))
        if mpn and r.mpn is None:
            r.mpn = Sourced(mpn, "nuxt", "medium")
        if man and r.manufacturer is None:
            r.manufacturer = Sourced(man, "nuxt", "medium")
        if pkg and r.package is None:
            r.package = Sourced(pkg, "nuxt", "medium")
        if desc and r.description is None:
            r.description = Sourced(desc, "nuxt", "medium")
    return r


def structured_blobs(html: str) -> dict:
    """Every generic web structured-data source found, raw, for a general consumer: all
    JSON-LD objects, the OpenGraph/meta dict, the __NEXT_DATA__ and __NUXT__ JSON, and
    microdata itemprop maps. Part-agnostic; never raises."""
    jsonld: list = []
    for raw in _SCRIPT_LD.findall(html):
        try:
            jsonld.append(json.loads(raw.strip()))
        except (json.JSONDecodeError, ValueError, RecursionError):
            continue
    sweep = _MetaSweep()
    try:
        sweep.feed(html)
    except Exception:  # noqa: BLE001 - a malformed page yields a partial blob, never a raise
        pass
    next_data = None
    m = _SCRIPT_NEXT.search(html)
    if m:
        try:
            next_data = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError, RecursionError):
            next_data = None
    nuxt = _decode_object_after(html, "window.__NUXT__")
    from stockroom.scrape.extract.html import parse

    micro: list = []
    for node in parse(html).css("[itemscope][itemtype]"):
        if "product" in (node.attributes.get("itemtype") or "").lower():
            micro.append(_itemprop_map(node))
    return {
        "jsonld": jsonld,
        "opengraph": dict(sweep.meta),
        "meta": dict(sweep.meta),
        "next_data": next_data,
        "nuxt": nuxt,
        "microdata": micro,
    }
