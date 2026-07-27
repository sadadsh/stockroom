"""Where a part's CAD files can be fetched, per vendor.

Owner, 2026-07-27: *"yes rebuild guided capture, digikey UL snapmagic and samacsys"*. That
instruction is what remained after every AUTOMATED route was measured and closed:

* **Nexar / Octopart** — a sanctioned, CAD-aware API that aggregates UL and SnapMagic, at
  **$1,000/month**. Priced out.
* **Ultra Librarian** — its terms state verbatim: *"You may not use any robot or other automated
  means to access or gather content from the Website."* Automation is forbidden, not merely hard.
* **SnapMagic** — an API exists, but its catalogue blends community-built and automatically generated models,
  which fails the owner's actual bar ("not trusted where we've gotten them").
* **Mouser** — the Search API carries no CAD fields at all (verified by dumping every key it
  returns). Its "Download Design Files" button is SamacSys, a separate service.
* **LCSC / EasyEDA** — ruled out by the owner, and KiCad-only regardless.

So the human clicks Download, in their own browser session, and the app does everything either
side of that click: pick the part, open exactly the right page, catch the file, classify it,
attach it, move to the next part.

**This module resolves URLs and nothing else.** It downloads no file and automates no vendor site.
That is precisely what keeps the guided flow inside every one of those vendors' terms, and it is
why the acquisition path is a link rather than a fetcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, quote_plus


@dataclass(frozen=True)
class CadSource:
    """One vendor's page for one part, and what the person has to do when they get there."""

    key: str
    label: str
    url: str
    # Which EDA tools this vendor can actually export for. The owner needs BOTH, and a vendor that
    # cannot emit Altium must say so rather than send someone to a page that can never satisfy the
    # requirement they are working on.
    tools: tuple[str, ...]
    # True when the vendor merely HOSTS models other libraries built (DigiKey shows SnapEDA / Ultra
    # Librarian / SamacSys downloads on its product pages) rather than authoring them. Carried as
    # data so a surface can order and label it honestly instead of implying a fourth library.
    aggregator: bool
    # Shown in the guided window. Per-vendor, because "click Download" is not the same journey on
    # a distributor product page as on a model library's part page.
    instruction: str


# Ordered by the owner's trust ranking, stated 2026-07-27: Ultra Librarian is manufacturer-verified
# and built from source with the semiconductor makers; SamacSys is independently verified and is
# what Mouser serves; SnapMagic is last of the authors because it blends community and automatically generated
# content. DigiKey sits first only because it is the one page that gathers all three in one place,
# which is fewer clicks when the part is stocked there.
_SOURCES: tuple[tuple[str, str, tuple[str, ...], bool, str], ...] = (
    (
        "digikey",
        "DigiKey",
        ("kicad", "altium"),
        True,
        "Open the CAD Models section, then download for KiCad and for Altium.",
    ),
    (
        "ultralibrarian",
        "Ultra Librarian",
        ("kicad", "altium"),
        False,
        "Pick the part, choose KiCad and Altium as the export formats, then Download.",
    ),
    (
        "samacsys",
        "SamacSys",
        ("kicad", "altium"),
        False,
        "Open the part, then download the KiCad and Altium models.",
    ),
    (
        "snapmagic",
        "SnapMagic",
        ("kicad", "altium"),
        False,
        "Check the model is manufacturer-verified, then download for KiCad and Altium.",
    ),
)


def all_cad_sources() -> tuple[CadSource, ...]:
    """Every vendor, in trust order, with empty URLs. The catalogue, independent of any part."""
    return tuple(
        CadSource(key=k, label=lbl, url="", tools=tools, aggregator=agg, instruction=instr)
        for k, lbl, tools, agg, instr in _SOURCES
    )


def _url_for(key: str, mpn: str, digikey_product_url: str) -> str:
    """The search or product URL for one vendor.

    Every MPN is percent-encoded. Real part numbers carry `+`, `/`, `#` and spaces
    (`MAX6817EUT+T` and `MCP4728-E/UN` are both in the owner's library), and an unencoded `+`
    silently becomes a space on the vendor's side — landing the user on a search for the wrong
    part, which is worse than landing them nowhere.
    """
    if key == "digikey":
        return digikey_product_url or (
            f"https://www.digikey.com/en/products/result?keywords={quote_plus(mpn)}"
        )
    if key == "ultralibrarian":
        # `app.`, NOT `www.` - MEASURED 2026-07-27 on the owner's machine (scripts/vendorprobe.py):
        # www.ultralibrarian.com/search?queryText=... returns a 404 "PAGE NOT FOUND" page since the
        # site became part of Cadence. The query PARAMETER was right; only the host was wrong, and
        # it was read off Ultra Librarian's own search form (action="https://app.ultralibrarian.com
        # /search", name="queryText"), which is the authoritative source for it.
        return f"https://app.ultralibrarian.com/search?queryText={quote_plus(mpn)}"
    if key == "samacsys":
        # A QUERY, not a path segment - MEASURED the same session. `/search/<MPN>` is parsed by
        # Component Search Engine as a part page for a part named "search", redirects to
        # /model-request/search/<MPN>, and claims "ECAD model is currently unavailable for this
        # part" even when SamacSys HAS the part. Their own form: action="/search" method="get"
        # name="term".
        return f"https://componentsearchengine.com/search?term={quote_plus(mpn)}"
    if key == "snapmagic":
        return f"https://www.snapeda.com/search/?q={quote_plus(mpn)}"
    raise ValueError(f"unknown cad source: {key!r}")


def _digikey_product_url(mpn: str, adapter) -> str:
    """The exact DigiKey product page when the API resolves one, else "".

    An exact product page is worth a network call because it lands ON the CAD section instead of a
    result list. A failure here is never fatal: the caller falls back to a keyword search, and the
    other three vendors are unaffected — one vendor's outage must not cost the user the other three.
    """
    if adapter is None or not getattr(adapter, "enabled", False):
        return ""
    try:
        result = adapter.lookup(mpn)
    except Exception:  # noqa: BLE001 - a vendor outage degrades this link, never the whole set
        return ""
    product = getattr(result, "product_url", None)
    return getattr(product, "value", "") or ""


def resolve_cad_sources(mpn: str, digikey=None) -> list[CadSource]:
    """Every vendor page this part can be fetched from, in trust order.

    A blank MPN resolves to NOTHING rather than to a set of vendor home pages: sending someone to
    a search for "" is worse than telling them there is nowhere to go.
    """
    mpn = (mpn or "").strip()
    if not mpn:
        return []
    product_url = _digikey_product_url(mpn, digikey)
    return [
        CadSource(
            key=source.key,
            label=source.label,
            url=_url_for(source.key, mpn, product_url),
            tools=source.tools,
            aggregator=source.aggregator,
            instruction=source.instruction,
        )
        for source in all_cad_sources()
    ]
