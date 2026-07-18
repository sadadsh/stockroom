"""Mouser product-WEB-page extractor (scrape layer; copied from enrich/sites, retired
there in S5). Distinct from the optional Mouser API in mouser.py. Adds package/spec
extras the generic cascade misses. Narrow.

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

# Mouser's own order number (e.g. "667-ERJ-P03F1101V"), carried in the same analytics
# dataLayer as event_mouserpn (raw and HTML-escaped). It is the distributor part number an
# order export needs ("order from Mouser by this P/N"), distinct from the manufacturer MPN.
_MOUSER_PN = re.compile(
    r"event_mouserpn(?:&quot;|[\"'])?\s*:\s*(?:&quot;|[\"'])([0-9]+-[A-Za-z0-9./_-]+)",
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

# Labels whose value IS the component package/case. "Mounting Style" is deliberately NOT here:
# on a real Mouser page it reads "PCB Mount" / "SMD/SMT" (how it mounts, not its size), and letting
# it win hid the true package (the real ERJ page carries the size only in "Case Code - in": 0603).
_PACKAGE_LABELS = {"package / case", "package", "case/package"}
# Fallback package sources, in preference order, used only when no _PACKAGE_LABELS row was found:
# the imperial case code ("Case Code - in": 0603) is the EIA size the app names packages by.
# Only EIA case-code labels: they carry a clean package token (0603). "Size / Dimension" is
# deliberately excluded - it is a verbose physical measurement ("1.6mm x 0.8mm"), not a package.
_PACKAGE_FALLBACK_LABELS = ("case code - in", "case code", "case code (in)")

# The FULL price ladder Mouser renders as <table class="pricing-table"> whose rows are
# data-testid="PricingTablePriceBreakRow" (a "Cut Tape" sub-heading row sits between the
# header and the breaks and is NOT a price-break row, so it never cross-matches). Each
# break row, tags stripped, reads "<qty> <unit-price> <ext-price>" e.g. "1,000 $0.063
# $63.00". This is the real per-unit cost the BOM layer needs; the generic JSON-LD offer
# gives only the single qty=1 price (and the real Mouser JSON-LD is an ImageObject with no
# offer at all), so without this table a Mouser passive priced nothing.
_PRICING_TABLE = re.compile(r"<table[^>]*\bpricing-table\b.*?</table>", re.IGNORECASE | re.DOTALL)
_PRICE_ROW = re.compile(r"<tr[^>]*PricingTablePriceBreakRow[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_QTY = re.compile(r"([\d,]+)")
_MONEY = re.compile(r"([$€£])\s*([\d,]+(?:\.\d+)?)")
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}

# The availability card ("In Stock: 5,616", "Factory Lead-Time: 15 Weeks"). The stock count
# is the header the page renders under data-testid="PricingAvailabilityHeader"; the lead time
# is a plain "Factory Lead-Time: N Weeks" line. Both are the honest procurement inputs the
# Mouser web path never read (Mouser scrapes 403 a plain client, so this only runs on the real
# rendered page through the WebView2 seam). Absent -> the field stays None (never fabricated).
_AVAIL_HEADER = re.compile(
    r"PricingAvailabilityHeader\"[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL
)
_IN_STOCK = re.compile(r"In Stock:\s*([\d,]+)", re.IGNORECASE)
_CAN_SHIP = re.compile(r"([\d,]+)\s*Can Ship", re.IGNORECASE)
_LEAD_TIME = re.compile(r"Factory Lead-?Time:\s*(\d[\d,]*\s*(?:Weeks?|Wks?|Days?))", re.IGNORECASE)

# Spec labels whose value IS the part's manufacturing lifecycle: promote it to the canonical
# lifecycle field (the BOM procurement risk roll-up reads it), while leaving it a spec row too.
_LIFECYCLE_LABELS = ("lifecycle status", "lifecycle", "part status", "product lifecycle")

# The compliance / "Origin Classifications" block Mouser renders as a <dt>label:</dt><dd>value</dd>
# definition list (Country of Origin, Assembly Country of Origin, ECCN, HTS, RoHS Status, ...).
# The <dt> label often nests a tooltip <button> whose sr-only sentence must NOT be read as the
# label, so the label is taken as the text BEFORE the first colon. The value is the first <dd>
# immediately following the labelled <dt>.
_DT_DD = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.IGNORECASE | re.DOTALL)

# The price ladder Mouser embeds as JSON: each break carries DecUnitPrice and, when the part is
# tariffed for US import, a non-null DecTariffUnitPrice (the per-unit tariff amount). The ratio
# is the effective US-import-tariff percentage the page itself shows in its price - never a
# researched or estimated rate.
_PB_TARIFF = re.compile(
    r'"DecUnitPrice"\s*:\s*([0-9.]+)\s*,\s*"DecTariffUnitPrice"\s*:\s*(null|[0-9.]+)',
    re.IGNORECASE,
)

# Mouser's analytics dataLayer lifecycle token; "none" = the part carries no special status =
# normal/active production. The real key is a SUFFIX (event_product_lifecycle / item_lifecycle)
# and the block appears both raw ("...lifecycle":"none") and HTML-escaped (&quot;). Read only when
# the spec table did not already carry a lifecycle.
_DL_LIFECYCLE = re.compile(
    r'lifecycle(?:&quot;|["\'])\s*:\s*(?:&quot;|["\'])([^"&\']*)', re.IGNORECASE
)
_LIFECYCLE_MAP = {
    "none": "Active", "active": "Active", "new": "New Product", "new product": "New Product",
    "eol": "End of Life", "obsolete": "Obsolete",
    "nrnd": "Not Recommended for New Designs",
}
# Compliance labels lifted onto specs (Country of Origin is ALSO promoted to a first-class field).
_COMPLIANCE_KEYS = {
    "assembly country of origin": "Assembly Country of Origin",
    "country of diffusion": "Country of Diffusion",
    "eccn": "ECCN",
    "hts": "HTS Code",
    "rohs status": "RoHS Status",
}


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _extract_compliance(html: str) -> dict[str, str]:
    """The origin/compliance dt/dd pairs as {label: value}. Label is the text before the first
    colon (so a nested tooltip sentence never leaks in); value is the cleaned <dd>. HTML comments
    are stripped first so a stray `<dt>`/`<dd>` inside a comment cannot poison a pairing."""
    html = _HTML_COMMENT.sub("", html)
    out: dict[str, str] = {}
    for raw_label, raw_value in _DT_DD.findall(html):
        label = _clean(raw_label).split(":", 1)[0].strip()
        value = _clean(raw_value)
        if label and value:
            out.setdefault(label, value)
    return out


def _extract_tariff_rate(html: str) -> float | None:
    """Effective US-import-tariff % from the embedded price ladder: DecTariffUnitPrice /
    DecUnitPrice * 100 at the first break that carries a tariff. A tariffed part returns its
    rate; a ladder whose every break shows a null tariff returns 0.0 (a CONFIRMED no-tariff,
    e.g. a non-China origin); a page with no ladder JSON returns None (unknown, never a
    fabricated 0)."""
    seen = False
    for unit, tar in _PB_TARIFF.findall(html):
        seen = True
        if tar.lower() == "null":
            continue
        try:
            u, t = float(unit), float(tar)
        except ValueError:
            continue
        if u > 0:
            return round(t / u * 100, 2)
    return 0.0 if seen else None


def _clean(cell: str) -> str:
    """Strip all nested tags, unescape entities, and trim a captured table cell."""
    return unescape(_TAGS.sub("", cell)).strip()


def _clean_block(block: str) -> str:
    """Strip tags, unescape, and collapse whitespace over a whole markup block, so a value
    split across nested tags (the availability card, a price-break row) reads as flat text."""
    return re.sub(r"\s+", " ", unescape(_TAGS.sub(" ", block))).strip()


def _extract_price_breaks(html: str):
    """Parse EVERY price break the pricing table lists, across all packaging groups (Cut Tape /
    MouseReel then Full Reel), returned as one quantity-sorted ladder. A Mouser part often has a
    deep-volume Full Reel tier the owner explicitly wants to see (ordering many, not just the
    unit price), so we keep them all rather than truncating to the first group. The result is
    deterministic (never dependent on an accidental quantity relationship between groups): breaks
    are sorted ascending by quantity and deduped per quantity keeping the lowest unit price, so
    the ladder is always monotonic for the BOM cost layer that reads it."""
    from stockroom.enrich.schema import PriceBreak

    tbl = _PRICING_TABLE.search(html)
    if not tbl:
        return []
    by_qty: dict[int, PriceBreak] = {}
    for raw in _PRICE_ROW.findall(tbl.group(0)):
        text = _clean_block(raw)
        qm = _QTY.search(text)
        pm = _MONEY.search(text)
        if not qm or not pm:
            continue
        try:
            qty = int(qm.group(1).replace(",", ""))
            price = float(pm.group(2).replace(",", ""))
        except ValueError:
            continue
        cur = _CURRENCY.get(pm.group(1), "USD")
        existing = by_qty.get(qty)
        if existing is None or price < existing.price:
            by_qty[qty] = PriceBreak(qty=qty, price=price, currency=cur)
    return [by_qty[q] for q in sorted(by_qty)]


def _extract_stock(html: str) -> int | None:
    """The live stock count from the availability header ("In Stock: 5,616"), falling back
    to the "N Can Ship Immediately" line. Returns None when neither is present (an honest
    unknown, never a fabricated 0 or 1)."""
    header = _AVAIL_HEADER.search(html)
    scope = _clean_block(header.group(1)) if header else ""
    m = _IN_STOCK.search(scope) or _CAN_SHIP.search(_clean_block(html))
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_lead_time(html: str) -> str | None:
    """The manufacturer factory lead time ("15 Weeks"), or None when the page carries none."""
    m = _LEAD_TIME.search(_clean_block(html))
    return m.group(1).strip() if m else None


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
        # The Mouser order number -> dist_pns["mouser"], upper-cased so it reads like the MPN.
        pn = _MOUSER_PN.search(html)
        if pn:
            r.dist_pns["mouser"] = unescape(pn.group(1)).upper()
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

        # A4: when no explicit package row existed, fall back to the case-code spec ("Case Code
        # - in": 0603 on a real resistor page) rather than leaving the package blank / wrong.
        if r.package is None:
            lowered = {k.lower(): v for k, v in r.specs.items()}
            for label in _PACKAGE_FALLBACK_LABELS:
                s = lowered.get(label)
                if s is not None and str(s.value).strip():
                    r.package = Sourced(str(s.value), "mouser_web", "medium")
                    break

        # A2 depth: the full price ladder, the live stock count, and the factory lead time
        # the generic cascade never reads off a Mouser page.
        breaks = _extract_price_breaks(html)
        if breaks:
            r.price_breaks = breaks
        stock = _extract_stock(html)
        if stock is not None:
            r.stock = Sourced(stock, "mouser_web", "medium")
        lead = _extract_lead_time(html)
        if lead:
            r.lead_time = Sourced(lead, "mouser_web", "medium")

        # Promote a lifecycle/part-status spec into the canonical lifecycle field (kept as a
        # spec row too), so the BOM procurement risk roll-up sees a part's manufacturing status.
        if r.lifecycle is None:
            for label, sourced in r.specs.items():
                if label.lower() in _LIFECYCLE_LABELS:
                    r.lifecycle = Sourced(sourced.value, "mouser_web", "medium")
                    break

        # The Origin Classifications compliance block: country of origin (first-class field the
        # tariff/import view reads, plus a spec), assembly country / ECCN / HTS as specs, and the
        # real RoHS status that supersedes the useless "RoHS: Details" the attr table captured.
        comp = _extract_compliance(html)
        comp_lc = {k.lower(): v for k, v in comp.items()}  # page labels are Title/UPPER-cased
        coo = comp_lc.get("country of origin")
        if coo and coo.lower() not in ("not available", "none", ""):
            r.country_of_origin = Sourced(coo, "mouser_web", "medium")
            r.specs.setdefault("Country of Origin", Sourced(coo, "mouser_web", "medium"))
        for raw_key, spec_key in _COMPLIANCE_KEYS.items():
            v = comp_lc.get(raw_key)
            if v and v.lower() not in ("details", ""):
                r.specs.setdefault(spec_key, Sourced(v, "mouser_web", "medium"))
        rohs = comp_lc.get("rohs status")
        if rohs and rohs.lower() not in ("details", ""):
            # the real status wins over a prior "RoHS: Details" popup-link value
            r.specs["RoHS"] = Sourced(rohs, "mouser_web", "high")

        # The effective US import tariff Mouser bakes into its price ladder (never a researched
        # rate). 0.0 is a confirmed no-tariff; None (no ladder) stays honestly empty.
        rate = _extract_tariff_rate(html)
        if rate is not None:
            r.tariff_rate = Sourced(rate, "mouser_web", "medium")

        # Lifecycle from the analytics dataLayer when the spec table carried none ("none" =
        # no special status = Active production), so the field fills honestly instead of blank.
        if r.lifecycle is None:
            m = _DL_LIFECYCLE.search(html)
            if m:
                raw = m.group(1).strip()
                norm = _LIFECYCLE_MAP.get(raw.lower(), raw.title() if raw else "")
                if norm:
                    r.lifecycle = Sourced(norm, "mouser_web", "medium")
        return r
