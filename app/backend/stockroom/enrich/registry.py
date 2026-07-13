"""The priority-registry with a remaining-set fall-through (spec section 6.1).

Sources are tried in priority order (LCSC/easyeda -> scrape -> optional Mouser);
each fills only what is still missing, then the next handles only the leftovers;
the walk stops once nothing remains (KiCost distributor.py pattern, verified in
the research). A source that fails is skipped and the walk continues, so a dead
source can never wall a part off from reaching complete (source-agnostic
completeness, the load-bearing rule)."""

from __future__ import annotations

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


class SourceRegistry:
    def __init__(self, sources: list[Source]):
        self.sources = list(sources)

    def enrich(self, mpn: str, category: str, want: set[str] | None = None) -> EnrichmentResult:
        remaining = set(want) if want is not None else set(DEFAULT_WANT)
        result = EnrichmentResult(category=category)
        for source in self.sources:
            if not remaining:
                break
            try:
                partial = source.enrich(mpn, category, set(remaining))
            except EnrichError:
                continue  # a dead source never blocks
            result.merge_missing(partial)
            remaining -= result.filled_fields()
        return result
