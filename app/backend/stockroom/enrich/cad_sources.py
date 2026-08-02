"""Resolve every known CAD route for one exact part.

DigiKey Product Information V4 Media is durable route evidence, not an Ultra Librarian preference.
Stockroom retains the complete Media payload, recognizes every known CAD author it names, and the
single Get Files workflow walks DigiKey's multi-author surface plus exact standalone pages. A partial
result from one author never ends collection: valid files are retained and later routes fill gaps
or become selectable alternatives.

This module only resolves exact or provider-search URLs. The capture layer owns the persistent
in-app provider WebView, ordinary interaction automation, task-bound downloads, validation, and
attachment; security challenges remain human-only.
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


def _url_for(key: str, mpn: str, digikey_product_url: str, digikey_models_id: str = "") -> str:
    """The search or product URL for one vendor.

    Every MPN is percent-encoded. Real part numbers carry `+`, `/`, `#` and spaces
    (`MAX6817EUT+T` and `MCP4728-E/UN` are both in the owner's library), and an unencoded `+`
    silently becomes a space on the vendor's side — landing the user on a search for the wrong
    part, which is worse than landing them nowhere.
    """
    if key == "digikey":
        # Best first: the models page IS the CAD surface, so it costs neither the search nor the
        # scroll to the CAD Models section. Its id is opaque and unlookupable, so it exists only
        # for a part the person has already opened once — see `capture/digikey_models.py`. Then
        # the exact product page, then the keyword search, exactly as before.
        if digikey_models_id:
            from stockroom.capture.digikey_models import digikey_models_url

            try:
                return digikey_models_url(digikey_models_id)
            except ValueError:
                pass  # not an id: fall through rather than interpolate it into a URL
        return digikey_product_url or (
            f"https://www.digikey.com/en/products/result?keywords={quote_plus(mpn)}"
        )
    if key == "ultralibrarian":
        # `app.`, NOT `www.` - MEASURED 2026-07-27 on the owner's machine (scripts/webread.py --controls):
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


def catalog_provider_urls(catalog: dict | None) -> dict[str, str]:
    """Exact provider detail links DigiKey's Media API returned for this product."""
    out: dict[str, str] = {}
    if not isinstance(catalog, dict):
        return out
    for item in catalog.get("media") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").casefold()
        haystack = f"{title} {url.casefold()}"
        key = ""
        if "ultralibrarian" in haystack or "ultra librarian" in haystack:
            key = "ultralibrarian"
        elif "snapeda" in haystack or "snapmagic" in haystack:
            key = "snapmagic"
        elif "samacsys" in haystack or "componentsearchengine" in haystack:
            key = "samacsys"
        elif "traceparts" in haystack:
            key = "traceparts"
        elif "cadenas" in haystack:
            key = "cadenas"
        elif "manufacturer provided" in haystack:
            key = "manufacturer"
        if key and url.startswith("https://"):
            out.setdefault(key, url)
    return out


def resolve_cad_sources(
    mpn: str,
    digikey=None,
    *,
    digikey_models_id: str = "",
    digikey_catalog: dict | None = None,
) -> list[CadSource]:
    """Every vendor page this part can be fetched from, in trust order.

    A blank MPN resolves to NOTHING rather than to a set of vendor home pages: sending someone to
    a search for "" is worse than telling them there is nowhere to go.

    `digikey_models_id` is optional and purely an optimisation: pass the id learned from a previous
    capture of THIS exact part and DigiKey's link becomes its models page. Omit it — or pass
    anything that is not an id — and every URL is exactly what it was before.
    """
    mpn = (mpn or "").strip()
    if not mpn:
        return []
    models_id = digikey_models_id if isinstance(digikey_models_id, str) else ""
    product_url = (
        str(digikey_catalog.get("product_url") or "").strip()
        if isinstance(digikey_catalog, dict)
        else ""
    ) or _digikey_product_url(mpn, digikey)
    exact_provider_urls = catalog_provider_urls(digikey_catalog)
    return [
        CadSource(
            key=source.key,
            label=source.label,
            url=exact_provider_urls.get(source.key)
            or _url_for(source.key, mpn, product_url, models_id),
            tools=source.tools,
            aggregator=source.aggregator,
            instruction=source.instruction,
        )
        for source in all_cad_sources()
    ]
