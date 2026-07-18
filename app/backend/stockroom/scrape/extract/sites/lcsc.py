"""LCSC product-page extractor (scrape layer; copied from enrich/sites, retired there
in S5). The generic cascade (JSON-LD/OG) carries MPN,
manufacturer, description, and price; this module adds only the LCSC-specific
extras the generic layers miss: the package and the parameter spec-table rows
(spec section 6.1, per-site extractor modules tier). Deliberately narrow."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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


# LCSC product pages are a Next.js app: the fully-hydrated product record ships
# inline in a <script id="__NEXT_DATA__"> JSON blob (props.pageProps.webData),
# which carries the canonical MPN/manufacturer/package/datasheet/spec-table with
# none of the HTML-scrape ambiguity of the _ROW path above.
_NEXTDATA = re.compile(
    r'<script[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class LcscProduct:
    lcsc: str
    mpn: str
    manufacturer: str
    package: str
    description: str
    datasheet_url: str
    # specs carries EVERY webData field (scalars + flattened nested + any leftover
    # list/dict as JSON), so nothing is lost when this persists to a record.
    specs: dict[str, str] = field(default_factory=dict)
    # The complete, unflattened webData object too, for a caller that wants the typed
    # structure rather than the flattened spec strings.
    raw: dict = field(default_factory=dict)


# Clean labels for the high-value webData scalars (everything else is captured too,
# under a humanized fall-back label, so no field is ever dropped).
_WEBDATA_LABELS: dict[str, str] = {
    "eccn": "ECCN",
    "productCycle": "Lifecycle",
    "isEnvironment": "RoHS",
    "isHasBattery": "Contains Battery",
    "isReel": "Available On Reel",
    "isHot": "Popular Part",
    "isPreSale": "Pre-Sale",
    "minBuyNumber": "Minimum Order Quantity",
    "maxBuyNumber": "Maximum Order Quantity",
    "minPacketNumber": "Package Quantity",
    "minPacketUnit": "Package Quantity Unit",
    "productArrange": "Packaging",
    "productUnit": "Unit",
    "productWeight": "Weight (kg)",
    "foreignWeight": "Weight Foreign (kg)",
    "catalogName": "LCSC Category",
    "parentCatalogName": "LCSC Parent Category",
    "wmCatalogNameEn": "LCSC Warehouse Category",
    "stockNumber": "Stock",
    "stockSz": "Stock (Shenzhen)",
    "productKeyAttributes": "Key Attributes",
    "productNameEn": "LCSC Product Name",
    "title": "LCSC Title",
    "split": "Order Multiple",
    "reelPrice": "Reel Setup Fee",
    "productId": "LCSC Product ID",
    "productArrange": "Packaging",
}

# webData keys already surfaced as first-class LcscProduct fields (do not re-capture
# them as a generic spec row).
_WEBDATA_FIRST_CLASS = frozenset({
    "productCode", "productModel", "brandNameEn", "encapStandard",
    "productIntroEn", "productDescEn", "pdfUrl", "pdfLinkUrl", "paramVOList",
})
# Nested webData objects flattened explicitly below (skip the raw scalar loop).
_WEBDATA_NESTED = frozenset({
    "htsMap", "edaSvgInfo", "productImages", "domesticStockVO",
    "overseasStockVO", "productPriceList", "parentCatalogList",
})

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _s(value: object) -> str:
    """Coerce a possibly-missing JSON value to a stripped string (never crash)."""
    if value is None:
        return ""
    return str(value).strip()


def _humanize(key: str) -> str:
    """A camelCase webData key -> a Title Case label (fallback for uncurated keys)."""
    return _CAMEL.sub(" ", key).replace("_", " ").title()


def _https(url: str) -> str:
    """LCSC/EasyEDA asset URLs often come protocol-relative (//host/...)."""
    url = _s(url)
    return "https:" + url if url.startswith("//") else url


def _capture_all_webdata(web_data: dict, specs: dict[str, str]) -> None:
    """Flatten EVERY useful webData field into specs (owner: more is better, capture
    all possible fields). Nested objects that carry value (per-country HTS tariff
    codes, EDA symbol/footprint SVGs, product images, warehouse stock, category path)
    are flattened by hand; every remaining scalar is captured under a curated or
    humanized label. setdefault throughout so a paramVOList row always wins its key."""
    hts = web_data.get("htsMap")
    if isinstance(hts, dict):
        for country, code in hts.items():
            if _s(code):
                specs.setdefault(f"HTS Code ({country})", _s(code))
    eda = web_data.get("edaSvgInfo")
    if isinstance(eda, dict):
        if _s(eda.get("schSvg")):
            specs.setdefault("EDA Symbol SVG", _https(eda.get("schSvg")))
        if _s(eda.get("pcbSvg")):
            specs.setdefault("EDA Footprint SVG", _https(eda.get("pcbSvg")))
    images = web_data.get("productImages")
    if isinstance(images, list):
        urls = [_https(u) for u in images if _s(u)]
        for i, u in enumerate(urls):
            specs.setdefault("Product Image" if i == 0 else f"Product Image {i + 1}", u)
    for key, label in (("domesticStockVO", "Stock (Domestic)"),
                       ("overseasStockVO", "Stock (Overseas)")):
        vo = web_data.get(key)
        if isinstance(vo, dict) and vo.get("total") is not None:
            specs.setdefault(label, _s(vo.get("total")))
    parents = web_data.get("parentCatalogList")
    if isinstance(parents, list):
        names = [_s(c.get("catalogNameEn")) for c in parents if isinstance(c, dict)]
        names = [n for n in names if n]
        if names:
            specs.setdefault("LCSC Category Path", " > ".join(names))

    for key, val in web_data.items():
        if key in _WEBDATA_FIRST_CLASS or key in _WEBDATA_NESTED or val is None:
            continue
        if isinstance(val, bool):
            text = "Yes" if val else "No"
        elif isinstance(val, (int, float)):
            if key in ("minBuyNumber", "maxBuyNumber") and val == -1:
                continue  # -1 is LCSC's "no limit" sentinel, not a real quantity
            text = _s(val)
        elif isinstance(val, str):
            text = val.strip()
            if not text:
                continue
        else:
            # A list/dict not in the explicit flatten set (e.g. faqs): keep it as JSON
            # rather than drop it, so NOTHING the source exposes is lost (owner: capture
            # every field). The UI decides what to surface.
            text = json.dumps(val, ensure_ascii=False)
            if not val:
                continue
        specs.setdefault(_WEBDATA_LABELS.get(key) or _humanize(key), text)


def parse_lcsc_product(html: str) -> LcscProduct | None:
    """Extract the LCSC product record from a page's __NEXT_DATA__ JSON blob.

    Returns None when the __NEXT_DATA__ script or its props.pageProps.webData
    node is absent (or the JSON does not decode).
    """
    match = _NEXTDATA.search(html)
    if match is None:
        return None
    try:
        root = json.loads(match.group(1))
    except (ValueError, TypeError):
        return None
    if not isinstance(root, dict):
        return None

    props = root.get("props")
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    web_data = (
        page_props.get("webData") if isinstance(page_props, dict) else None
    )
    if not isinstance(web_data, dict):
        return None

    specs: dict[str, str] = {}
    # The decoded parameter table first, so a real spec always owns its label.
    params = web_data.get("paramVOList")
    if isinstance(params, list):
        for entry in params:
            if not isinstance(entry, dict):
                continue
            name = _s(entry.get("paramNameEn"))
            value = _s(entry.get("paramValueEn"))
            if not name or not value:
                continue
            specs.setdefault(name, value)
    # Then every other field the page exposes (owner: capture everything).
    _capture_all_webdata(web_data, specs)

    description = _s(
        web_data.get("productIntroEn") or web_data.get("productDescEn") or ""
    )

    return LcscProduct(
        lcsc=_s(web_data.get("productCode")),
        mpn=_s(web_data.get("productModel")),
        manufacturer=_s(web_data.get("brandNameEn")),
        package=_s(web_data.get("encapStandard")),
        description=description,
        datasheet_url=_s(web_data.get("pdfUrl") or ""),
        specs=specs,
        raw=dict(web_data),
    )
