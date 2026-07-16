"""Stockroom's OWN versioned, category-keyed canonical enrichment schema.

Every scraped or API field is normalized into this shape, never passed through
under a supplier's field names, so a distributor redesign renaming a field cannot
silently break enrichment (spec section 6.1; research risk 5, Ki-nTree #165). Each
field carries the source it came from and a confidence, so a later, higher-trust
source (the datasheet) can be preferred over a lower-trust one (a scrape).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Bump when the canonical shape changes; a stored EnrichmentResult records the
# version it was produced under so a reader can migrate or discard it.
# v2: added country_of_origin + tariff_rate (the Mouser page's own US-import fields).
SCHEMA_VERSION = 2

# Confidence ranked low -> high so a merge can compare sources.
CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

_UNSAFE = re.compile(r"[\\/\s:*?\"<>|]+")


def normalize_mpn(mpn: str) -> str:
    """Uppercase, collapse path separators / wildcards / whitespace to a single
    dash, so the result is a stable, filesystem-safe cache key (KiABOM pattern,
    verified in the research: never trust a raw MPN as a filename)."""
    return _UNSAFE.sub("-", mpn.strip()).upper()


@dataclass
class Sourced:
    value: Any
    source: str
    confidence: str = "medium"


@dataclass
class PriceBreak:
    qty: int
    price: float
    currency: str = "USD"


@dataclass
class CanonicalSpecs:
    package: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    pinout: list[dict] = field(default_factory=list)


# The single-valued Sourced fields on EnrichmentResult, in merge/report order.
# lifecycle / lead_time / product_url (M7d) feed the BOM procurement + export layer:
# a part's manufacturing status, its manufacturer lead time, and its distributor
# product page. Populated where a source carries them (the Mouser API); a scrape that
# does not surface them leaves them None, so procurement degrades honestly, never
# inventing a status or a lead.
_SOURCED_FIELDS: tuple[str, ...] = (
    "mpn",
    "manufacturer",
    "description",
    "datasheet_url",
    "stock",
    "package",
    "lifecycle",
    "lead_time",
    "product_url",
    # v2 import fields, both lifted from the distributor product page itself (never a
    # researched/estimated rate): the manufacturing origin country, and the effective US
    # import-tariff percentage Mouser bakes into its price ladder (DecTariffUnitPrice /
    # DecUnitPrice). A part with no tariff shown yields 0.0; an unread page leaves them None.
    "country_of_origin",
    "tariff_rate",
)


@dataclass
class EnrichmentResult:
    category: str = ""
    mpn: Sourced | None = None
    manufacturer: Sourced | None = None
    description: Sourced | None = None
    datasheet_url: Sourced | None = None
    stock: Sourced | None = None
    package: Sourced | None = None
    # M7d procurement fields (see _SOURCED_FIELDS note). dist_pns maps a lowercase
    # distributor name ("mouser"/"lcsc"/"digikey") to that distributor's own part number,
    # so an order export can say "order from {dist} by {this P/N}".
    lifecycle: Sourced | None = None
    lead_time: Sourced | None = None
    product_url: Sourced | None = None
    country_of_origin: Sourced | None = None
    tariff_rate: Sourced | None = None
    dist_pns: dict[str, str] = field(default_factory=dict)
    price_breaks: list[PriceBreak] = field(default_factory=list)
    specs: dict[str, Sourced] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def filled_fields(self) -> set[str]:
        out = {name for name in _SOURCED_FIELDS if getattr(self, name) is not None}
        if self.price_breaks:
            out.add("price_breaks")
        if self.specs:
            out.add("specs")
        if self.dist_pns:
            out.add("dist_pns")
        return out

    def merge_missing(self, other: "EnrichmentResult") -> None:
        """Fill only fields still empty on self from other; NEVER overwrite a field
        already set (spec section 6.1: enrichment never silently overwrites; the
        first, higher-priority source wins). Specs and distributor P/Ns merge
        key-by-key, only for keys not already present."""
        for name in _SOURCED_FIELDS:
            if getattr(self, name) is None and getattr(other, name) is not None:
                setattr(self, name, getattr(other, name))
        if not self.price_breaks and other.price_breaks:
            self.price_breaks = list(other.price_breaks)
        for key, val in other.specs.items():
            self.specs.setdefault(key, val)
        for key, val in other.dist_pns.items():
            self.dist_pns.setdefault(key, val)
