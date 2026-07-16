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
_PACKAGE_FALLBACK_LABELS = ("case code - in", "case code", "case code (in)", "size / dimension")

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
        return r
