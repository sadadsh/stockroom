"""The priority-registry with a remaining-set fall-through (spec section 6.1).

Sources are tried in priority order (LCSC/easyeda -> scrape -> optional Mouser);
each fills only what is still missing, then the next handles only the leftovers;
the walk stops once nothing remains (KiCost distributor.py pattern, verified in
the research). A source that fails is skipped and the walk continues, so a dead
source can never wall a part off from reaching complete (source-agnostic
completeness, the load-bearing rule)."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.schema import SOURCE_STATES, EnrichmentResult, mpn_identity_key

# adapter.last_status vocabulary -> the closed source_states vocabulary. Anything the map
# does not name collapses to "failed": an unknown status is still an attempted source that
# produced no usable answer, and the state vocabulary never grows by accident.
_LAST_STATUS_STATES: dict[str, str] = {
    "ok": "success",
    "not_found": "unavailable",
    "rate_limited": "failed",
    "auth_error": "failed",
    "error": "failed",
}


def source_state(source, partial: EnrichmentResult) -> str:
    """The honest verdict for one consulted distributor source.

    The adapter's own ``last_status`` is the primary signal (the official adapters swallow
    their transport errors and record the classification there). A source without one is
    judged by what it returned: data means success, an empty answer means the part is not
    carried there.
    """
    last_status = str(getattr(source, "last_status", "") or "")
    state = _LAST_STATUS_STATES.get(last_status, "")
    if not state:
        state = "success" if partial.filled_fields() else "unavailable"
    assert state in SOURCE_STATES
    return state

# The want token that means "ask EVERY distributor, not just enough of them". It is not a
# field: it is satisfied only once every source declaring a `vendor` has been consulted, which
# is what keeps the walk from ending the moment the canonical fields happen to be full.
#
# Why it has to exist: the fall-through below is a cost optimisation, and for the identity
# fields it is the right one. But a distributor's PRICE LADDER and LIVE STOCK are not
# substitutable - Mouser's ladder is not an answer for DigiKey's - so "somebody already told us
# a price" must not stand in for "we asked DigiKey". Before this token, an LCSC hit filled every
# wanted field and the Mouser/DigiKey legs were never called at all, which is precisely why one
# distributor's Sourcing row rendered with no price and no stock.
#
# The cost is honest and bounded: one extra API round trip per UNCACHED part per enabled
# distributor, paced by the shared limiter. A caller that does not need it (a bulk pass that
# only wants identity) omits the token and keeps the cheap early stop.
DIST_SOURCING: str = "dist_sourcing"

# The full set of canonical fields a registry walk tries to fill by default.
DEFAULT_WANT: frozenset[str] = frozenset(
    {"mpn", "manufacturer", "description", "datasheet_url", "stock", "package",
     "price_breaks", "specs", DIST_SOURCING}
)


def record_vendor_offer(result: EnrichmentResult, vendor: str,
                         partial: EnrichmentResult) -> None:
    """Keep THIS distributor's own price ladder, live stock and product page under its vendor
    key, before the per-field merge collapses them into one primary answer.

    Keyed off the source's declared `vendor`, never its `name`: `scrape` and `datasheet` also
    carry a URL and sometimes a price, but they are not places to buy from, and keying on the
    name would have put a "Scrape" row in the Sourcing list. Which sources are distributors is
    data on the source, so a third one needs no change here.

    The key is lower-cased because every OTHER writer and reader of these maps uses the
    lowercase form ("mouser"/"digikey") - the paste path, the DTO, and the frontend's
    `dist_price_breaks[key]` lookup. A display-cased "Mouser" would land beside the lowercase
    entry instead of in it, and the UI would silently find no prices: the exact symptom this
    whole change exists to remove.
    """
    vendor = vendor.strip().lower()
    if not vendor:
        return
    if partial.price_breaks:
        result.dist_price_breaks.setdefault(vendor, list(partial.price_breaks))
    if partial.stock is not None:
        try:
            result.dist_stock.setdefault(vendor, int(float(str(partial.stock.value))))
        except (TypeError, ValueError):
            pass  # an unparseable stock is simply not recorded (never a fabricated 0)
    if partial.product_url is not None:
        url = str(partial.product_url.value).strip()
        if url:
            result.dist_urls.setdefault(vendor, url)


@runtime_checkable
class Source(Protocol):
    name: str

    def enrich(self, mpn: str, category: str, remaining: set[str]) -> EnrichmentResult: ...


def _accepts_kw(fn, name: str) -> bool:
    """True if fn declares keyword `name` (or **kwargs). Lets a source opt in to the
    accumulated result (e.g. DatasheetSource needs the datasheet_url a prior source
    found) without forcing every Source to grow the parameter."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    params = sig.parameters
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


class SourceRegistry:
    def __init__(self, sources: Iterable[Source]):
        self.sources = list(sources)

    def enrich(self, mpn: str, category: str, want: set[str] | None = None,
               progress=None, *, initial: EnrichmentResult | None = None,
               exhaustive: bool = False,
               skip_vendor_keys: set[str] | None = None,
               skip_source_names: set[str] | None = None) -> EnrichmentResult:
        remaining = set(want) if want is not None else set(DEFAULT_WANT)
        result = initial if initial is not None else EnrichmentResult(category=category)
        skipped = {key.strip().lower() for key in (skip_vendor_keys or set())}
        skipped_names = {name.strip().lower() for name in (skip_source_names or set())}
        # Every distributor source we have not consulted YET. A source counts as consulted the
        # moment it has been asked - including when it fails - so a dead API can never hold the
        # walk open waiting for an answer that is not coming.
        unconsulted = {
            id(s)
            for s in self.sources
            if getattr(s, "vendor_key", "").strip().lower() not in skipped
            and getattr(s, "vendor_key", "")
        }
        for source in self.sources:
            vendor = getattr(source, "vendor_key", "").strip().lower()
            source_name = getattr(source, "name", "").strip().lower()
            if vendor in skipped or source_name in skipped_names:
                continue
            if not remaining and not exhaustive:
                break
            # A source opts into optional kwargs by declaring them (or **kwargs), so the
            # walk stays backward compatible: a source that declares neither keeps its
            # original three-arg signature. `resolved` hands it the result so far (the
            # datasheet source needs the URL the scrape surfaced); `progress` hands it the
            # job's stage sink so a networked source can stream its real fetch/render phases.
            kwargs: dict = {}
            if _accepts_kw(source.enrich, "resolved"):
                kwargs["resolved"] = result
            if progress is not None and _accepts_kw(source.enrich, "progress"):
                kwargs["progress"] = progress
            try:
                partial = source.enrich(mpn, category, set(remaining), **kwargs)
            except EnrichError:
                unconsulted.discard(id(source))  # asked, and it failed: that still counts
                if vendor:
                    result.source_states[vendor] = "failed"
                continue  # a dead source never blocks
            unconsulted.discard(id(source))
            if (
                partial.mpn is not None
                and mpn_identity_key(partial.mpn.value) != mpn_identity_key(mpn)
            ):
                # Search APIs are allowed to return fuzzy candidates, but an MPN lookup is not.
                # Reject the whole foreign row before its manufacturer, specs, prices, or URL
                # can contaminate the requested part, then continue to the next source.
                if vendor:
                    # The source answered, but not with THIS part: for the requested MPN it
                    # is honestly unavailable there, never a silent nothing.
                    result.source_states[vendor] = "unavailable"
                continue
            if vendor:
                result.source_states[vendor] = source_state(source, partial)
            if vendor:
                record_vendor_offer(result, vendor, partial)
            result.merge_missing(partial)
            if not exhaustive:
                remaining -= result.filled_fields()
            if not unconsulted:
                remaining.discard(DIST_SOURCING)
        return result
