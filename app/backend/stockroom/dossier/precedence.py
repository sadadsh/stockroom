"""Source precedence: which answer holds the slot, and what happened to the others.

One order, applied to every field, in one place:

    reviewed manual override
    > manufacturer datasheet
    > manufacturer API or official page
    > trusted authorized distributor
    > CAD provider
    > parsed or inferred

The second half of the rule matters as much as the first: a losing candidate is NEVER
discarded. It stays on the field with its own source, and the field is marked as conflicting so
the disagreement is visible where the value is read rather than buried in a diagnostics page
nobody opens. Two sources disagreeing about a part is data about the part.

Ties inside a tier are settled by the registry's own provider order and then by the source key,
so the answer never depends on which source happened to be merged first.

That is also where the owner's distributor ranking lives. Mouser, DigiKey and LCSC are one tier
because they are one CLASS of evidence - a distributor's own catalogue record - and the ranking
between them (Mouser > DigiKey > LCSC) is the order they are declared in
`stockroom.providers`. Ordering them by position rather than by tier keeps the five-tier
vocabulary intact and keeps all three honestly below the manufacturer's own word: a distributor
answer can never beat the datasheet, whichever distributor it is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from stockroom.dossier.units import NormalizedValue, comparable_key
from stockroom.providers import all_providers

# The tiers, strongest first. The order of this tuple IS the precedence.
SOURCE_TIERS: tuple[tuple[str, str], ...] = (
    ("manual_override", "Reviewed Manual Override"),
    ("manufacturer_datasheet", "Manufacturer Datasheet"),
    ("manufacturer_official", "Manufacturer API Or Official Page"),
    ("authorized_distributor", "Trusted Authorized Distributor"),
    ("cad_provider", "CAD Provider"),
    ("parsed", "Parsed Or Inferred"),
)

TIER_RANK: dict[str, int] = {key: index for index, (key, _) in enumerate(SOURCE_TIERS)}
TIER_LABELS: dict[str, str] = dict(SOURCE_TIERS)

# The tiers that make a value the manufacturer's own word. A value from one of these is
# `verified`; everything below is `unverified`, which is a statement about WHO said it and not
# a guess at how likely it is to be right.
AUTHORITATIVE_TIERS: frozenset[str] = frozenset(
    {"manual_override", "manufacturer_datasheet", "manufacturer_official"}
)

# Source keys whose tier is not decided by the provider registry. Everything else falls through
# to the registry, so adding a distributor there needs no edit here.
_EXPLICIT_TIERS: dict[str, str] = {
    "manual": "manual_override",
    "override": "manual_override",
    "user": "manual_override",
    "owner": "manual_override",
    "datasheet": "manufacturer_datasheet",
    "manufacturer_datasheet": "manufacturer_datasheet",
    "manufacturer": "manufacturer_official",
    "manufacturer_api": "manufacturer_official",
    "stm": "manufacturer_official",
    "derived": "parsed",
    "inferred": "parsed",
    "heuristic": "parsed",
    "provenance": "parsed",
    "import": "parsed",
}

# A suffix that says the value came from reading a page rather than from an answer the source
# gave us. A scraped distributor page is parsed data, whoever's page it was.
_PARSED_SUFFIXES: tuple[str, ...] = ("-scrape", "_scrape", "-html", "_html")

_DISTRIBUTORS: frozenset[str] = frozenset(
    item.key for item in all_providers() if item.distributor
)
_CAD_PROVIDERS: frozenset[str] = frozenset(
    item.key for item in all_providers() if not item.distributor and item.key != "manufacturer"
)
_PROVIDER_ORDER: dict[str, int] = {item.key: item.order for item in all_providers()}


def source_tier(source_id: object) -> str:
    """The precedence tier one source key belongs to.

    An unknown key is `parsed` rather than trusted: a source nobody has placed cannot be
    allowed to outrank the manufacturer's own document just because it is new.
    """
    key = str(source_id or "").strip().casefold()
    if not key:
        # No attribution at all. Deliberately the WEAKEST tier and not `manual_override`: an
        # override is a decision somebody recorded and signed, while an unattributed value is
        # only a value nothing on the record can account for. Promoting the second to the first
        # would let every unsourced spec outrank the manufacturer's own datasheet.
        return "parsed"
    if any(key.endswith(suffix) for suffix in _PARSED_SUFFIXES):
        return "parsed"
    explicit = _EXPLICIT_TIERS.get(key)
    if explicit is not None:
        return explicit
    if key in _DISTRIBUTORS:
        return "authorized_distributor"
    if key in _CAD_PROVIDERS:
        return "cad_provider"
    return "parsed"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One answer a source gave for one field, with everything needed to rank it."""

    value: object
    normalized: NormalizedValue
    source: str
    tier: str
    confidence: str = ""
    retrieved_at: str = ""
    # The key the source itself used, kept so the raw evidence level can name it.
    original_key: str = ""


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the precedence order decided, and everything it decided against."""

    preferred: Candidate | None
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)
    conflict_state: str = "none"
    # The pin that actually applied, or "" when nothing was pinned or the pinned source offered
    # nothing for this field. A pin nothing answers is reported as not in force rather than
    # silently obeyed, because obeying it would mean preferring an answer that does not exist.
    pinned_source: str = ""

    @property
    def distinct_values(self) -> int:
        return len({comparable_key(item.normalized) for item in self.candidates})


def _sort_key(item: Candidate, pinned: str) -> tuple[int, int, int, int, str]:
    return (
        # A reviewed VALUE override is the strongest decision there is and stays above a pin: a
        # person who typed an answer has said more than a person who chose whose answer to read.
        0 if item.tier == "manual_override" else 1,
        0 if pinned and item.source.casefold() == pinned else 1,
        TIER_RANK.get(item.tier, len(SOURCE_TIERS)),
        _PROVIDER_ORDER.get(item.source.casefold(), len(_PROVIDER_ORDER)),
        item.source.casefold(),
    )


def resolve(candidates: Sequence[Candidate], *, pinned_source: str = "") -> Resolution:
    """Rank every candidate and name the disagreement, without dropping any of them.

    `resolved` rather than `conflicting` when a reviewed decision is in force: the sources still
    disagree and every answer is still carried, but a person has already looked at it, and
    presenting that as an open conflict would ask them to settle it twice.

    `pinned_source` promotes ONE source above the computed order without removing anything. It
    is the whole mechanism behind a preferred-source control: the field keeps every candidate it
    had, keeps reporting the disagreement, and follows the pinned source as that source is
    refreshed - which a copied literal value could not do.
    """
    if not candidates:
        return Resolution(preferred=None, candidates=(), conflict_state="none")
    pinned = str(pinned_source or "").strip().casefold()
    in_force = pinned if any(item.source.casefold() == pinned for item in candidates) else ""
    ordered = tuple(sorted(candidates, key=lambda item: _sort_key(item, in_force)))
    preferred = ordered[0]
    distinct = {comparable_key(item.normalized) for item in ordered}
    if len(distinct) <= 1:
        state = "none"
    elif preferred.tier == "manual_override" or in_force:
        state = "resolved"
    else:
        state = "conflicting"
    return Resolution(
        preferred=preferred,
        candidates=ordered,
        conflict_state=state,
        pinned_source=in_force,
    )


__all__ = [
    "AUTHORITATIVE_TIERS",
    "SOURCE_TIERS",
    "TIER_LABELS",
    "TIER_RANK",
    "Candidate",
    "Resolution",
    "resolve",
    "source_tier",
]
