"""DigiKey product-WEB-page extractor (scrape layer).

DigiKey is a Next.js app that embeds the FULL product record as JSON in
``<script id="__NEXT_DATA__">`` at ``props.pageProps.envelope.data``. Parsing that structured
envelope reaches Mouser-parity depth - identity, the full parametric spec table, the price-break
ladder, live stock, the datasheet, factory lead time, the DigiKey order P/N, part status
(lifecycle) and the RoHS/compliance block - far more robustly than scraping the rendered DOM. A
bare-cell ``<td>label</td><td>value</td>`` regex is kept as a fallback for a page that lacks the
JSON (an older layout, or a partial/blocked render).

Never raises: the JSON is untrusted distributor data of arbitrary shape, so every nested access
is type-guarded AND the whole envelope parse is wrapped so any malformed shape degrades to the
bare-cell fallback (or an empty result) - enrichment continues (source-agnostic completeness)."""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, urlparse

from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced
from stockroom.scrape.extract.sites._hostmatch import is_brand_host

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)
# Bare-cell fallback for a page with no __NEXT_DATA__: <td>label</td><td>value</td>.
_ROW = re.compile(
    r"<t[dh][^>]*>\s*([^<]{1,60}?)\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<]{1,120}?)\s*</t[dh]>",
    re.IGNORECASE | re.DOTALL,
)
_SLASH_WS = re.compile(r"\s*/\s*")
# Package-label attributes in PREFERENCE order: "Supplier Device Package" carries the clean device
# token (SOT-23-5) while "Package / Case" is the verbose case ("SC-74A, SOT-753"), so the clean
# one wins when both are present, regardless of the order DigiKey lists them.
_PACKAGE_PRIORITY = ("supplier device package", "package/case", "package")
# DigiKey renders an absent attribute as a bare dash; never emit it as a spec value.
_EMPTY = {"", "-", "–", "—", "n/a"}
# Price strings carry the storefront currency as a leading symbol ("$0.12000", "€0.10"); read it
# so a regional storefront's ladder is not mislabeled USD (the BOM cost layer sums by number).
_CURRENCY_SYMBOLS = (("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY"))


def _canon_pkg(label: str) -> str:
    return _SLASH_WS.sub("/", label.lower().strip())


def _clean(v) -> str:
    return unescape(str(v)).strip() if isinstance(v, (str, int, float)) else ""


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _dget(obj, key) -> dict:
    """obj[key] as a dict, or {} when obj (or the value) is not a dict - defends every nested
    access against a truthy wrong type in untrusted distributor JSON."""
    return _as_dict(_as_dict(obj).get(key))


def _resolve_datasheet(url: str) -> str:
    """DigiKey wraps some manufacturer datasheets in a click-through redirect
    (``.../suppproductinfo.tsp?...&gotoUrl=<real>``); unwrap the ``gotoUrl`` so the stored link is
    the real datasheet. datasheetUrl is DigiKey's EXPLICIT datasheet field, so it is trusted (the
    actual PDF is validated - Content-Type + %PDF magic - when the datasheet source downloads it,
    so a redirect / non-.pdf link is not pre-rejected). A protocol-relative ``//host/x.pdf`` is
    promoted to https so a real datasheet is not dropped."""
    if not url:
        return ""
    try:
        goto = parse_qs(urlparse(url).query).get("gotoUrl") or parse_qs(urlparse(url).query).get("goto")
    except ValueError:
        goto = None
    resolved = goto[0] if goto else url
    if resolved.startswith("//"):
        resolved = "https:" + resolved
    return resolved if resolved.lower().startswith("http") else ""


def _to_int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _digikey_pn(overview: dict) -> str:
    """The DigiKey order number (e.g. 311-10.0KHRTR-ND) an order export needs, distinct from the
    manufacturer MPN. Prefer the digikeyProductNumbers list, fall back to the rolled-up number."""
    for entry in _as_list(_dget(overview, "digikeyProductNumbers").get("value")):
        val = _clean(entry.get("value")) if isinstance(entry, dict) else ""
        if val:
            return val
    return _clean(overview.get("rolledUpProductNumber"))


def _currency(data: dict) -> str:
    """The storefront currency, read from the symbol a price tier carries; defaults to USD when no
    priced tier is present. ($ is treated as USD; the regional CAD/AUD $ sub-case is not
    disambiguated, but the EUR/GBP/JPY mislabeling the BOM layer actually cares about is fixed.)"""
    for group in _as_list(_dget(data, "priceQuantity").get("pricing")):
        for tier in _as_list(_as_dict(group).get("mergedPricingTiers")):
            price = str(_as_dict(tier).get("unitPrice") or "")
            for symbol, code in _CURRENCY_SYMBOLS:
                if symbol in price:
                    return code
    return "USD"


def _price_breaks(quantity_table, currency: str) -> list:
    """Every price break DigiKey lists, as one quantity-sorted, per-quantity-deduped (lowest unit
    price wins) ladder, so the ladder is always monotonic for the BOM cost layer."""
    by_qty: dict[int, PriceBreak] = {}
    for row in _as_list(quantity_table):
        if not isinstance(row, dict):
            continue
        qty = _to_int(row.get("breakQty"))
        try:
            price = float(row.get("unitPrice"))
        except (ValueError, TypeError):
            price = None
        if qty is None or price is None:
            continue
        existing = by_qty.get(qty)
        if existing is None or price < existing.price:
            by_qty[qty] = PriceBreak(qty=qty, price=price, currency=currency)
    return [by_qty[q] for q in sorted(by_qty)]


def _env_rows(environmental) -> dict[str, str]:
    """The Environmental & Export Classifications block as {attribute: value}. Each dataRow is a
    two-cell [attribute, value] pair, each cell's text at data.value.value."""
    out: dict[str, str] = {}
    for row in _as_list(_as_dict(environmental).get("dataRows")):
        cells = _as_list(_as_dict(row).get("dataCells"))
        if len(cells) < 2:
            continue
        key = _cell_text(cells[0])
        val = _cell_text(cells[1])
        if key and val and val.lower() not in _EMPTY:
            out.setdefault(key, val)
    return out


def _cell_text(cell) -> str:
    value = _dget(_as_dict(cell).get("data"), "value").get("value")
    if value is None:
        value = _as_dict(_as_dict(cell).get("data")).get("value")
    return _clean(value)


class DigiKeyWebSite:
    def matches(self, url: str) -> bool:
        # Claim only the registrable digikey domain (digikey.com, digikey.de, digikey.co.uk, ...),
        # never a "digikey" subdomain of a foreign host or a query string that contains it.
        return is_brand_host(url, "digikey")

    def extract(self, html: str, url: str) -> EnrichmentResult:
        m = _NEXT_DATA.search(html or "")
        if m:
            try:
                data = json.loads(m.group(1))["props"]["pageProps"]["envelope"]["data"]
                if isinstance(data, dict):
                    return self._from_envelope(data)
            except (ValueError, KeyError, TypeError, AttributeError):
                pass  # malformed / unexpected shape -> fall back rather than raise
        return self._fallback(html)

    def _from_envelope(self, data: dict) -> EnrichmentResult:
        r = EnrichmentResult()
        overview = _dget(data, "productOverview")

        mpn = _clean(overview.get("manufacturerProductNumber"))
        if mpn:
            r.mpn = Sourced(mpn, "digikey_web", "medium")
        manufacturer = _clean(overview.get("manufacturer"))
        if manufacturer:
            r.manufacturer = Sourced(manufacturer, "digikey_web", "medium")
        desc = _clean(overview.get("detailedDescription")) or _clean(overview.get("description"))
        if desc:
            r.description = Sourced(desc, "digikey_web", "medium")
        ds = _resolve_datasheet(_clean(overview.get("datasheetUrl")))
        if ds:
            r.datasheet_url = Sourced(ds, "digikey_web", "medium")
        lead = _clean(overview.get("standardLeadTime"))
        if lead:
            r.lead_time = Sourced(lead, "digikey_web", "medium")
        dk_pn = _digikey_pn(overview)
        if dk_pn:
            r.dist_pns["digikey"] = dk_pn

        stock = _to_int(_dget(data, "priceQuantity").get("qtyAvailable"))
        if stock is not None:
            r.stock = Sourced(stock, "digikey_web", "medium")

        breaks = _price_breaks(data.get("quantityTable"), _currency(data))
        if breaks:
            r.price_breaks = breaks

        # The parametric attribute table. Each attribute may carry several values (a resistor's
        # Packaging = Tape & Reel / Cut Tape / Digi-Reel); join them. A "-" value is dropped. The
        # package attributes are collected and resolved AFTER the loop so the clean device token
        # wins over the verbose case regardless of order.
        pkg_candidates: dict[str, tuple[str, str]] = {}  # canon -> (original label, value)
        for attr in _as_list(_dget(data, "productAttributes").get("attributes")):
            if not isinstance(attr, dict):
                continue
            label = _clean(attr.get("label"))
            values = [
                _clean(v.get("value")) for v in _as_list(attr.get("values"))
                if isinstance(v, dict) and _clean(v.get("value")).lower() not in _EMPTY
            ]
            value = "; ".join(v for v in values if v)
            if not label or not value:
                continue
            lower = label.lower()
            if lower == "part status":
                # DigiKey's lifecycle -> the canonical field + the "Lifecycle" spec (the corpus
                # key the BOM procurement roll-up reads), never a separate "Part Status" twin.
                r.lifecycle = Sourced(value, "digikey_web", "medium")
                r.specs.setdefault("Lifecycle", Sourced(value, "digikey_web", "medium"))
                continue
            canon = _canon_pkg(label)
            if canon in _PACKAGE_PRIORITY:
                pkg_candidates.setdefault(canon, (label, value))
                continue
            if lower == "mfr":
                # fold DigiKey's short "Mfr" onto the canonical "Manufacturer" spec key
                r.specs.setdefault("Manufacturer", Sourced(value, "digikey_web", "medium"))
                continue
            r.specs.setdefault(label, Sourced(value, "digikey_web", "medium"))

        # The clean device token wins the package field; any OTHER package label (the verbose
        # "Package / Case" case detail) is kept as a spec, so no depth is lost (parity with the
        # Mouser path, which retains its case-code specs alongside the resolved package).
        selected = next((c for c in _PACKAGE_PRIORITY if c in pkg_candidates), None)
        if selected is not None:
            r.package = Sourced(pkg_candidates[selected][1], "digikey_web", "medium")
        for canon, (label, value) in pkg_candidates.items():
            if canon != selected:
                r.specs.setdefault(label, Sourced(value, "digikey_web", "medium"))

        # The RoHS/compliance block: the real RoHS status lands under the canonical "RoHS" key
        # (matching the Mouser path + corpus), the rest (ECCN, HTSUS, MSL, REACH) as specs.
        for key, value in _env_rows(data.get("environmental")).items():
            if key.lower() == "rohs status":
                r.specs["RoHS"] = Sourced(value, "digikey_web", "high")
            else:
                r.specs.setdefault(key, Sourced(value, "digikey_web", "medium"))
        return r

    def _fallback(self, html: str) -> EnrichmentResult:
        """A page with no __NEXT_DATA__: the old bare-cell <td>label</td><td>value</td> scan, so
        an older/partial DigiKey layout still yields whatever flat rows it exposes."""
        r = EnrichmentResult()
        for label, value in _ROW.findall(html or ""):
            label = unescape(label).strip()
            value = unescape(value).strip()
            if not value or value.lower() in _EMPTY:
                continue
            if _canon_pkg(label) in _PACKAGE_PRIORITY and r.package is None:
                r.package = Sourced(value, "digikey_web", "medium")
            else:
                r.specs.setdefault(label, Sourced(value, "digikey_web", "medium"))
        return r
