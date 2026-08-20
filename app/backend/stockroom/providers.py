"""The one authoritative catalogue of CAD/part providers Stockroom knows.

Every place that needs a provider's identity - the enrich CAD-source resolver, the capture
surface labels, DigiKey media recognition, the API's provider rows, and the frontend's
labels - reads this registry. It is deliberately data plus URL resolution only: no driving,
no sign-in, no selectors, no browser policy. The person operates provider pages; Stockroom
only needs to know where a page is, what it is called, and what it can be expected to offer.

A provider with no search URL is honest data, not a gap: for LCSC, TraceParts, CADENAS, and
manufacturer sites Stockroom only ever holds an exact page when distributor catalogue
evidence names one, and inventing a search URL would send someone to a page that proves
nothing. Expectations (`symbols`/`footprints`/`models`, `kicad`/`altium`) describe what the
provider is built to offer, never whether a specific part is available there.

A registered provider is not necessarily a CAD surface. A distributor can earn a row here for
its catalogue alone - LCSC does - in which case every artifact expectation is False and the
coverage table says so rather than opening a column nothing may ever fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """One provider surface, described completely by data."""

    key: str
    label: str
    # Registrable domains this provider serves pages from. Matched against a URL's host by
    # suffix (``app.ultralibrarian.com`` matches ``ultralibrarian.com``). Empty means the
    # provider has no fixed home (a manufacturer site can live anywhere).
    domains: tuple[str, ...]
    # MPN search URL with ``{mpn}`` already percent-encoded by ``search_url``. Empty when no
    # measured search surface exists; an exact evidence URL is then the only way in.
    search_template: str
    # Lower-cased substrings that identify this provider inside distributor catalogue media
    # entries (title + url). Empty for providers never named by catalogue evidence.
    media_tokens: tuple[str, ...]
    # What the provider is built to offer. Expectations, never per-part availability.
    symbols: bool
    footprints: bool
    models: bool
    kicad: bool
    altium: bool
    # True when downloading normally requires an account sign-in performed by the person.
    needs_login: bool
    # True when the surface HOSTS models other libraries authored (DigiKey and Mouser show
    # Ultra Librarian / SamacSys / SnapMagic downloads) rather than authoring them.
    aggregator: bool
    # Distributors carry official part APIs and buy links; model libraries do not.
    distributor: bool
    # Shown beside the provider page. Per-provider because the journey differs per site.
    instruction: str
    enabled: bool = True

    @property
    def order(self) -> int:
        """Stable preferred order: position in the registry tuple."""
        return _ORDER[self.key]


# This tuple's order IS the preferred order, and `dossier/precedence.py` settles a tie inside
# one tier by it, so the distributors lead it in the owner's own trust order, stated 2026-08-05:
# Mouser first, DigiKey second, LCSC third. It replaced digikey-then-mouser, which was never a
# trust ranking - it only reflected DigiKey's one page gathering all three CAD authors, which is
# a fact about CAD and not about whose catalogue answer to believe. LCSC is ranked last of the
# three by POSITION rather than by a weaker tier, because its catalogue record is the same CLASS
# of evidence as the other two - a distributor's own product data - and one tier keeps all three
# equally, honestly, below the manufacturer's own word.
#
# Trust order for the model authors is a separate owner decision, stated 2026-07-27: Ultra
# Librarian is manufacturer-verified, SamacSys is independently verified (and what Mouser
# serves), SnapMagic blends community and unverified generated content. The evidence-only providers
# close the list.
PROVIDERS: tuple[ProviderRecord, ...] = (
    ProviderRecord(
        key="mouser",
        label="Mouser",
        domains=("mouser.com",),
        search_template="https://www.mouser.com/c/?q={mpn}",
        media_tokens=(),
        symbols=True,
        footprints=True,
        models=True,
        kicad=True,
        altium=True,
        needs_login=False,
        aggregator=True,
        distributor=True,
        instruction="Open the part page, then use the ECAD Model links to download.",
    ),
    ProviderRecord(
        key="digikey",
        label="DigiKey",
        domains=("digikey.com",),
        search_template="https://www.digikey.com/en/products/result?keywords={mpn}",
        media_tokens=(),
        symbols=True,
        footprints=True,
        models=True,
        kicad=True,
        altium=True,
        needs_login=False,
        aggregator=True,
        distributor=True,
        instruction="Open the CAD Models section, then download for KiCad and for Altium.",
    ),
    ProviderRecord(
        key="lcsc",
        label="LCSC",
        # `scrape/extract/sites/lcsc.py` claims a page by `"lcsc.com" in url`, and
        # `enrich/distributor_url.py` by `"lcsc." in host`; the suffix match here covers both
        # (`www.lcsc.com` and any subdomain). EasyEDA is deliberately NOT listed: it is a
        # different surface whose geometry this product refuses, and claiming its domain would
        # make an EasyEDA URL read as LCSC distributor evidence.
        domains=("lcsc.com",),
        # Blank on purpose, measured 2026-08-05: https://www.lcsc.com/search?<param>=S1M returns
        # the same 89,805-byte JavaScript shell titled `Search by ""` for every candidate
        # parameter name, so no parameter can be SHOWN to drive the search and the MPN never
        # appears in the response. `enrich/pipeline.py` calls the same URL "the dead search-URL
        # scrape" for exactly this reason. An LCSC page is reached by the exact product-detail
        # URL the catalogue resolves (jlcsearch -> /product-detail/<C-number>.html), which is
        # already how `LcscSource` gets there.
        search_template="",
        # Never named as an author inside another distributor's catalogue media, the same as the
        # other two distributors.
        media_tokens=(),
        # LCSC is registered for its CATALOGUE, not for CAD. Its EasyEDA-derived symbol,
        # footprint and 3D geometry is explicitly refused as a source in two places
        # (`api/routers/ingest.py` rejects LCSC/EasyEDA CAD ingest; `capture/runner.py` refuses
        # a converted LCSC/EasyEDA trio as an active completion source), so claiming an artifact
        # here would open a coverage column no honest capture could ever fill and would send a
        # person to a surface this product does not accept geometry from.
        symbols=False,
        footprints=False,
        models=False,
        kicad=False,
        altium=False,
        # The product page and the jlcsearch catalogue leg both read without an account.
        needs_login=False,
        # DigiKey and Mouser host the three registered CAD authors' downloads; LCSC hosts
        # EasyEDA's, which this registry does not know and this product does not accept.
        aggregator=False,
        distributor=True,
        instruction=(
            "Open the LCSC product page for this exact part, then read its specifications, "
            "stock and datasheet. Do not take CAD from here."
        ),
    ),
    ProviderRecord(
        key="ultralibrarian",
        label="Ultra Librarian",
        domains=("ultralibrarian.com",),
        # `app.`, NOT `www.` - measured 2026-07-27 (scripts/webread.py --controls):
        # www.ultralibrarian.com/search returns a 404 since the site became part of Cadence.
        search_template="https://app.ultralibrarian.com/search?queryText={mpn}",
        media_tokens=("ultralibrarian", "ultra librarian"),
        symbols=True,
        footprints=True,
        models=True,
        kicad=True,
        altium=True,
        needs_login=True,
        aggregator=False,
        distributor=False,
        instruction="Pick the part, choose KiCad and Altium as the export formats, then Download.",
    ),
    ProviderRecord(
        key="samacsys",
        label="SamacSys",
        domains=("componentsearchengine.com", "samacsys.com"),
        # A QUERY, not a path segment - measured the same session: /search/<MPN> is parsed
        # as a part page for a part named "search" and claims the model is unavailable.
        search_template="https://componentsearchengine.com/search?term={mpn}",
        media_tokens=("samacsys", "componentsearchengine"),
        symbols=True,
        footprints=True,
        models=True,
        kicad=True,
        altium=True,
        needs_login=True,
        aggregator=False,
        distributor=False,
        instruction="Open the part, then download the KiCad and Altium models.",
    ),
    ProviderRecord(
        key="snapmagic",
        label="SnapMagic",
        domains=("snapeda.com", "snapmagic.com"),
        search_template="https://www.snapeda.com/search/?q={mpn}",
        media_tokens=("snapeda", "snapmagic"),
        symbols=True,
        footprints=True,
        models=True,
        kicad=True,
        altium=True,
        needs_login=True,
        aggregator=False,
        distributor=False,
        instruction="Check the model is manufacturer-verified, then download for KiCad and Altium.",
    ),
    ProviderRecord(
        key="manufacturer",
        label="Manufacturer",
        domains=(),
        search_template="",
        media_tokens=("manufacturer provided",),
        symbols=False,
        footprints=False,
        models=True,
        kicad=False,
        altium=False,
        needs_login=False,
        aggregator=False,
        distributor=False,
        instruction="Find the part's product page, then download the CAD files it offers.",
    ),
    ProviderRecord(
        key="traceparts",
        label="TraceParts",
        domains=("traceparts.com",),
        search_template="",
        media_tokens=("traceparts",),
        symbols=False,
        footprints=False,
        models=True,
        kicad=False,
        altium=False,
        needs_login=True,
        aggregator=False,
        distributor=False,
        instruction="Open the model page, then download the 3D model.",
    ),
    ProviderRecord(
        key="cadenas",
        label="CADENAS",
        domains=("cadenas.de", "partcommunity.com"),
        search_template="",
        media_tokens=("cadenas",),
        symbols=False,
        footprints=False,
        models=True,
        kicad=False,
        altium=False,
        needs_login=True,
        aggregator=False,
        distributor=False,
        instruction="Open the model page, then download the 3D model.",
    ),
)

_BY_KEY: dict[str, ProviderRecord] = {record.key: record for record in PROVIDERS}
_ORDER: dict[str, int] = {record.key: index for index, record in enumerate(PROVIDERS)}


def provider(key: str) -> ProviderRecord:
    """The record for ``key``. Loud on an unknown key so a typo cannot become a silent row."""
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown provider: {key!r}") from None


def all_providers(*, enabled_only: bool = False) -> tuple[ProviderRecord, ...]:
    if enabled_only:
        return tuple(record for record in PROVIDERS if record.enabled)
    return PROVIDERS


def provider_label(key: str) -> str:
    """Display label for ``key``, or the key itself for a surface the registry does not
    know (an unknown provider stays visible under its raw key, never invisible)."""
    record = _BY_KEY.get(key)
    return record.label if record is not None else key


def search_url(key: str, mpn: str) -> str:
    """The provider's MPN search URL, or "" when no measured search surface exists.

    Every MPN is percent-encoded: real part numbers carry ``+``, ``/``, ``#`` and spaces
    (``MAX6817EUT+T`` and ``MCP4728-E/UN`` are both in the owner's library), and an
    unencoded ``+`` silently becomes a space on the vendor's side.
    """
    record = provider(key)
    if not record.search_template:
        return ""
    return record.search_template.format(mpn=quote_plus(mpn))


def provider_for_host(host: str) -> ProviderRecord | None:
    """The provider whose registered domain matches ``host`` by suffix, else None."""
    candidate = (host or "").strip().casefold().rstrip(".")
    if not candidate:
        return None
    for record in PROVIDERS:
        for domain in record.domains:
            if candidate == domain or candidate.endswith("." + domain):
                return record
    return None


def provider_for_media(title: str, url: str) -> ProviderRecord | None:
    """The provider a distributor catalogue media entry names, else None.

    Matches the entry's title and URL against each provider's media tokens, longest token
    first so "ultra librarian" can never be shadowed by a shorter overlapping token.
    """
    haystack = f"{(title or '').casefold()} {(url or '').casefold()}"
    best: tuple[int, ProviderRecord] | None = None
    for record in PROVIDERS:
        for token in record.media_tokens:
            if token in haystack and (best is None or len(token) > best[0]):
                best = (len(token), record)
    return best[1] if best is not None else None


__all__ = [
    "PROVIDERS",
    "ProviderRecord",
    "all_providers",
    "provider",
    "provider_for_host",
    "provider_for_media",
    "provider_label",
    "search_url",
]
