"""The priority-registry with a remaining-set fall-through (spec section 6.1).

Sources are tried in priority order (LCSC/easyeda -> scrape -> optional Mouser);
each fills only what is still missing, then the next handles only the leftovers;
the walk stops once nothing remains (KiCost distributor.py pattern, verified in
the research). A source that fails is skipped and the walk continues, so a dead
source can never wall a part off from reaching complete (source-agnostic
completeness, the load-bearing rule)."""

from __future__ import annotations

import inspect
from typing import Protocol, runtime_checkable

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.schema import EnrichmentResult

# The full set of canonical fields a registry walk tries to fill by default.
DEFAULT_WANT: frozenset[str] = frozenset(
    {"mpn", "manufacturer", "description", "datasheet_url", "stock", "package",
     "price_breaks", "specs"}
)


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
    def __init__(self, sources: list[Source]):
        self.sources = list(sources)

    def enrich(self, mpn: str, category: str, want: set[str] | None = None,
               progress=None) -> EnrichmentResult:
        remaining = set(want) if want is not None else set(DEFAULT_WANT)
        result = EnrichmentResult(category=category)
        for source in self.sources:
            if not remaining:
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
                continue  # a dead source never blocks
            result.merge_missing(partial)
            remaining -= result.filled_fields()
        return result
