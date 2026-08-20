"""Stockroom's OWN versioned, category-keyed canonical enrichment schema.

Every scraped or API field is normalized into this shape, never passed through
under a supplier's field names, so a distributor redesign renaming a field cannot
silently break enrichment (spec section 6.1; research risk 5, Ki-nTree #165). Each
field carries the source it came from and a confidence, so a later, higher-trust
source (the datasheet) can be preferred over a lower-trust one (a scrape).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Bump when the canonical shape changes; a stored EnrichmentResult records the
# version it was produced under so a reader can migrate or discard it.
# v5: binds every successful official payload to its query, canonical identity,
# and the exact values selected from it.  Old cache rows are deliberately missed:
# raw bytes without that identity binding are not safe initial-add evidence.
SCHEMA_VERSION = 5

# Confidence ranked low -> high so a merge can compare sources.
CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

# The closed vocabulary for EnrichmentResult.source_states. Fixed strings only, so a state
# can never smuggle an exception body, a URL, or credential material into a stored result:
#   success        - the source answered with data for this exact part
#   unavailable    - the source answered and does not carry this exact part
#   failed         - the source was attempted and could not answer (network/auth/rate limit)
#   not_configured - the source has no credentials on this machine and was never attempted
SOURCE_STATES: frozenset[str] = frozenset({"success", "unavailable", "failed", "not_configured"})

_UNSAFE = re.compile(r"[\\/\s:*?\"<>|]+")


def mpn_identity_key(mpn: object) -> str:
    """NFC/case-tolerant, punctuation-preserving key for exact MPN comparison."""
    return unicodedata.normalize("NFC", str(mpn or "")).strip().casefold()


def normalize_mpn(mpn: str) -> str:
    """Uppercase, collapse path separators / wildcards / whitespace to a single
    dash, so the result is a stable, filesystem-safe cache key (KiABOM pattern,
    verified in the research: never trust a raw MPN as a filename)."""
    return _UNSAFE.sub("-", mpn.strip()).upper()


# Distributor lifecycle tokens -> the library's canonical Title-Case status, so a part's
# manufacturing status reads consistently no matter the source: LCSC says "normal", Mouser's
# dataLayer says "none", others "eol"/"nrnd". An unknown token is Title-cased if it came in
# lower-case (cosmetic) and otherwise passed through untouched (never invent a status).
_LIFECYCLE_MAP = {
    "none": "Active", "normal": "Active", "active": "Active", "in production": "Active",
    "new": "New Product", "new product": "New Product", "preorder": "New Product",
    "eol": "End of Life", "end of life": "End of Life",
    "obsolete": "Obsolete", "discontinued": "Obsolete", "inactive": "Obsolete",
    "nrnd": "Not Recommended for New Designs",
    "not recommended for new designs": "Not Recommended for New Designs",
}


def normalize_lifecycle(raw):
    """Map a distributor lifecycle token to the canonical library status. A known token maps to
    its canonical form; an unknown all-lower token is Title-cased (so "normal"-style values are
    not shown verbatim); anything else is returned unchanged."""
    if not raw:
        return raw
    s = str(raw).strip()
    mapped = _LIFECYCLE_MAP.get(s.lower())
    if mapped:
        return mapped
    return s.title() if s and s == s.lower() else s


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
SOURCED_FIELDS: tuple[str, ...] = (
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


# The single-valued fields whose DISAGREEMENT between sources is real data worth keeping
# (Batch 3, punch 2/9). Two distributors describing the same part differently, naming a
# different package, or linking a different datasheet is information the owner asked to see
# ("see ALL DigiKey + Mouser data") - before this, the loser was dropped with no record
# anywhere, not even into a conflict list.
#
# `stock` and `product_url` are deliberately EXCLUDED: they are per-vendor BY NATURE (each
# distributor has its own live count and its own product page, and both live in dist_stock /
# dist_urls), so recording them as disagreements would bury the real ones in noise.
_PER_VENDOR_FIELDS: frozenset[str] = frozenset({"stock", "product_url"})
_CONFLICT_FIELDS: tuple[str, ...] = tuple(
    name for name in SOURCED_FIELDS if name not in _PER_VENDOR_FIELDS
)


def _norm_spec(value) -> str:
    """The comparison form of a spec value: sources agree when their values match after
    trimming and case-folding ("1%" == " 1% "), so formatting noise never fakes a conflict."""
    return str(value).strip().casefold()


def _record_conflict(store: dict[str, list["Sourced"]], key: str, kept: "Sourced",
                     loser: "Sourced") -> None:
    """Keep `loser` alongside the value that won `key`'s single slot. The kept value seeds
    the list so a reader always sees which answer is in force and which was set aside; a
    value already recorded (same after normalization) is never duplicated."""
    entries = store.setdefault(key, [kept])
    if all(_norm_spec(loser.value) != _norm_spec(s.value) for s in entries):
        entries.append(loser)


def _merge_conflict_maps(mine: dict[str, list["Sourced"]],
                         theirs: dict[str, list["Sourced"]]) -> None:
    """Fold another result's already-recorded disagreements into ours, key by key, without
    duplicating a value we already hold. A partial can arrive carrying its own conflicts (an
    adapter that merged two of its own answers); dropping them silently lost every
    disagreement found below the top level."""
    for key, entries in theirs.items():
        if not entries:
            continue
        ours = mine.setdefault(key, [entries[0]])
        for entry in entries:
            if all(_norm_spec(entry.value) != _norm_spec(s.value) for s in ours):
                ours.append(entry)


@dataclass
class EnrichmentResult:
    category: str = ""
    mpn: Sourced | None = None
    manufacturer: Sourced | None = None
    description: Sourced | None = None
    datasheet_url: Sourced | None = None
    stock: Sourced | None = None
    package: Sourced | None = None
    # M7d procurement fields (see SOURCED_FIELDS note). dist_pns maps a lowercase
    # distributor name ("mouser"/"lcsc"/"digikey") to that distributor's own part number,
    # so an order export can say "order from {dist} by {this P/N}".
    lifecycle: Sourced | None = None
    lead_time: Sourced | None = None
    product_url: Sourced | None = None
    country_of_origin: Sourced | None = None
    tariff_rate: Sourced | None = None
    dist_pns: dict[str, str] = field(default_factory=dict)
    # Each distributor's own PRODUCT PAGE url ("mouser"->..., "digikey"->...). When both APIs
    # answer a lookup we keep BOTH buy links, not only the pasted one, so the part carries every
    # place it can be ordered from (the owner's "store both the Mouser and DigiKey links").
    dist_urls: dict[str, str] = field(default_factory=dict)
    # Each distributor's OWN price ladder + live stock ("mouser"->[breaks...]), kept
    # alongside the merged primary ladder so the part can SHOW every vendor's prices
    # for comparison (owner 2026-07-24), not only the pasted vendor's.
    dist_price_breaks: dict[str, list[PriceBreak]] = field(default_factory=dict)
    dist_stock: dict[str, int | None] = field(default_factory=dict)
    # Provider-keyed structured catalogue intelligence. This is deliberately separate from
    # electrical `specs`: media, packaging equivalence, substitutions, recommendations and
    # associations have different semantics and must survive without being flattened into
    # display strings. Values are JSON-compatible versioned dictionaries.
    catalog: dict[str, dict] = field(default_factory=dict)
    price_breaks: list[PriceBreak] = field(default_factory=list)
    specs: dict[str, Sourced] = field(default_factory=dict)
    # Where two sources DISAGREE on a spec, every distinct value is kept here with its
    # source (the single-value specs slot still holds the first source's answer). The UI
    # shows all of them (owner 2026-07-24: "display all of it and only merge stuff thats
    # identical") - a disagreement is data, never silently discarded.
    spec_conflicts: dict[str, list[Sourced]] = field(default_factory=dict)
    # The same guarantee for the single-valued canonical fields (description, package,
    # datasheet_url, lifecycle, ...): the value that won the slot, plus every other answer a
    # source gave, each with its origin. See _CONFLICT_FIELDS for which fields participate.
    field_conflicts: dict[str, list[Sourced]] = field(default_factory=dict)
    # What actually happened to each consulted source, keyed by its lowercase vendor key
    # ("mouser"/"digikey"): one of SOURCE_STATES. This is the honest per-source verdict the
    # UI shows as a degraded state - before it existed, a failed official API was
    # indistinguishable from a part the distributor simply does not carry. Values are fixed
    # vocabulary only; no exception text or credential material ever lands here.
    source_states: dict[str, str] = field(default_factory=dict)
    # Complete decoded JSON returned by successful official distributor calls. These bytes are
    # not presentation data: the initial Add carries them to sourced/<id>/<provider>.json so a
    # later naming or derivation rule can be replayed without an immediate network Refresh.
    official_payloads: dict[str, dict] = field(default_factory=dict)
    # Provider-keyed identity bindings for ``official_payloads``.  The raw response remains
    # byte-for-byte evidence; this parallel index says which query produced it, which canonical
    # manufacturer MPN it proved, and which of its values were selected into the review.
    official_evidence: dict[str, dict] = field(default_factory=dict)
    # Authorities that independently proved the requested MPN. Official API providers are
    # represented by their successful source state; this list carries the non-API exception:
    # a manufacturer datasheet whose text contained the exact known MPN.
    identity_authorities: list[str] = field(default_factory=list)
    # Official keyword-search candidates returned when no exact manufacturer part number exists.
    # They are display-only recovery choices and never contribute identity or part fields until the
    # person explicitly chooses one and Stockroom performs a new exact lookup.
    identity_suggestions: dict[str, list[str]] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def filled_fields(self) -> set[str]:
        out = {name for name in SOURCED_FIELDS if getattr(self, name) is not None}
        if self.price_breaks:
            out.add("price_breaks")
        if self.specs:
            out.add("specs")
        if self.dist_pns:
            out.add("dist_pns")
        if self.dist_urls:
            out.add("dist_urls")
        if self.catalog:
            out.add("catalog")
        return out

    def merge_missing(self, other: "EnrichmentResult", record_conflicts: bool = True) -> None:
        """Fill only fields still empty on self from other; NEVER overwrite a field
        already set (spec section 6.1: enrichment never silently overwrites; the
        first, higher-priority source wins). Specs and distributor P/Ns merge
        key-by-key, only for keys not already present.

        `record_conflicts=False` merges without keeping the displaced values. Pass it when the
        two sides are the SAME authority read two ways - the six extraction techniques run over
        ONE document (JSON-LD, OpenGraph, __NEXT_DATA__, microdata, the site adapter, the
        heuristic). Their disagreements are artifacts of our own parsing, not two vendors saying
        different things, and surfacing "MPN - Maker | Mouser" from an og:title as an alternative
        description would bury the real DigiKey-vs-Mouser difference in noise.
        """
        for name in SOURCED_FIELDS:
            mine_field = getattr(self, name)
            theirs = getattr(other, name)
            if mine_field is None:
                if theirs is not None:
                    setattr(self, name, theirs)
                continue
            # The first source keeps the slot (spec 6.1), but the answer it displaced is
            # KEPT rather than dropped - identical after normalization is a plain merge.
            if theirs is None or name in _PER_VENDOR_FIELDS or not record_conflicts:
                continue
            if _norm_spec(theirs.value) != _norm_spec(mine_field.value):
                _record_conflict(self.field_conflicts, name, mine_field, theirs)
        if not self.price_breaks and other.price_breaks:
            self.price_breaks = list(other.price_breaks)
        for key, val in other.specs.items():
            mine = self.specs.get(key)
            if mine is None:
                self.specs[key] = val
                continue
            # identical after normalization is a MERGE (no conflict); a real disagreement
            # keeps every distinct value, each recorded once
            if _norm_spec(val.value) == _norm_spec(mine.value) or not record_conflicts:
                continue
            _record_conflict(self.spec_conflicts, key, mine, val)
        # Disagreements the other side had already recorded, and every vendor's OWN ladder /
        # live stock. All four were dropped here, which is why a second distributor's row
        # could render with no price and no stock (punch 4).
        _merge_conflict_maps(self.spec_conflicts, other.spec_conflicts)
        _merge_conflict_maps(self.field_conflicts, other.field_conflicts)
        for key, breaks in other.dist_price_breaks.items():
            self.dist_price_breaks.setdefault(key, list(breaks))
        for key, count in other.dist_stock.items():
            self.dist_stock.setdefault(key, count)
        for key, val in other.dist_pns.items():
            self.dist_pns.setdefault(key, val)
        for key, val in other.dist_urls.items():
            self.dist_urls.setdefault(key, val)
        for key, val in other.catalog.items():
            self.catalog.setdefault(key, dict(val))
        for key, val in other.source_states.items():
            self.source_states.setdefault(key, val)
        for key, val in other.official_payloads.items():
            self.official_payloads.setdefault(key, dict(val))
        for key, val in other.official_evidence.items():
            self.official_evidence.setdefault(key, dict(val))
        for authority in other.identity_authorities:
            if authority not in self.identity_authorities:
                self.identity_authorities.append(authority)
        for key, values in other.identity_suggestions.items():
            existing = self.identity_suggestions.setdefault(key, [])
            for value in values:
                if value not in existing:
                    existing.append(value)
