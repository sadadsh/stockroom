"""WHICH pure function turns one stored raw payload back into an EnrichmentResult.

A re-derive has to reconstruct a part from `sourced/<id>/<source>.json` and NOTHING else - no
network, no credentials, no cache. That is the whole reason the raw pulls are stored: the owner's
requirement is *"import everything so we can change the way the data's manipulated later (human
naming scheme for example)"*, and manipulating it later is only possible if the manipulation can
be run again offline.

WHY THIS IS A SECOND REGISTRY, and not the existing `enrich.registry` Source list.
A `Source` is a live, credentialed thing: `MouserAdapter` needs an API key, `DigiKeyAdapter` needs
an OAuth pair, and both report `enabled = False` without them. Re-deriving on a fresh clone with
no keys configured must still work - otherwise a machine that has never been given credentials
cannot rebuild the library it just pulled, which breaks device parity. So the DERIVE path depends
only on the credential-free parsers registered here, and never constructs a Source at all.

The cost of two registries is drift, so it is GATED: `tests/backend/derive/test_payload_registry.py`
asserts every source that can WRITE under `sourced/` has a parser here. Adding a distributor is
one entry in this table plus one `parse_*_payload` function; there is no `if source == "mouser"`
anywhere in the engine.

ORDER IS THE DEFAULT CONTRACT. `merge_missing` gives the slot to whoever fills it FIRST, so the
order of this table decides which vendor wins unless a canonical field has a measured,
field-specific order in `FIELD_SOURCE_PRIORITY`. Both are explicit tuples rather than dict
insertion order or a set, because the derivation must be deterministic to be idempotent -
"derive twice, get byte-identical records" is a spec acceptance test, and an unordered merge fails
it intermittently, which is the worst way to fail it.
"""

from __future__ import annotations

from collections.abc import Callable

from stockroom.enrich.digikey_api import parse_digikey_payload
from stockroom.enrich.mouser import parse_mouser_payload
from stockroom.enrich.schema import EnrichmentResult

# A parser takes the raw stored payload plus the part's MPN (identity, always available at derive
# time) and returns what that ONE source says. It never raises for a payload it cannot read: an
# unreadable payload is a source that contributes nothing, not a failed re-derive, because one
# corrupt file must not make a part unrebuildable.
PayloadParser = Callable[[dict | None, str], EnrichmentResult]

# Source key -> parser, in DEFAULT PRIORITY ORDER (first to fill a field keeps it).
#
# Mouser leads DigiKey only because that is the order the live registry already walks, so a
# re-derive reproduces the values the import produced rather than quietly re-picking winners the
# first time it runs. A field whose evidence supports a different choice is declared separately
# below instead of moving every other field with it.
PAYLOAD_PARSERS: tuple[tuple[str, PayloadParser], ...] = (
    ("mouser", parse_mouser_payload),
    ("digikey", parse_digikey_payload),
)

_BY_NAME: dict[str, PayloadParser] = dict(PAYLOAD_PARSERS)

# Canonical field -> source keys, best first. This is DATA, not a source-name branch in the derive
# engine. The owner-library sample found Mouser's short catalogue description both truncated and
# polluted while DigiKey's DetailedDescription was readable prose; that evidence says nothing
# about lifecycle, lead time, tariff, or every other field, so only `description` moves.
#
# Changing this table changes output from unchanged evidence and therefore requires a
# `RULESET_VERSION` bump in model/derived.py.
FIELD_SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "description": ("digikey", "mouser"),
}


def known_sources() -> tuple[str, ...]:
    """Source keys that can be re-derived from, in default priority order."""
    return tuple(name for name, _ in PAYLOAD_PARSERS)


def sources_for_field(field: str) -> tuple[str, ...]:
    """Every registered source in deterministic priority order for one canonical field.

    A field override may name only a subset; the remaining registered sources retain their
    default order afterward. That makes adding a third parser an honest fallback instead of
    silently making it ineligible for every existing field rule.
    """
    preferred = FIELD_SOURCE_PRIORITY.get(field, ())
    return preferred + tuple(source for source in known_sources() if source not in preferred)


def parser_for(source: str) -> PayloadParser | None:
    """The parser for a source, or None.

    None is a real answer and is handled, not raised: a library may hold a payload from a source
    a LATER build added and this one does not know, and refusing to derive such a part would make
    an older build unable to read a newer peer's library - the same forward-compatibility rule
    `PartRecord.extra` exists for. The payload stays on disk, untouched, and is used again as soon
    as a build that knows it runs.
    """
    return _BY_NAME.get(source)


def parse_one(source: str, payload: dict | None, mpn: str) -> EnrichmentResult:
    """What ONE source says about a part, or an empty result if it cannot be read.

    Swallowing the parse error is deliberate and narrow: the payload is EVIDENCE and stays on
    disk either way, so the honest outcome of an unreadable one is "this source contributed
    nothing to the derivation", never a crash that leaves the part with no derived block at all.
    """
    parser = parser_for(source)
    if parser is None:
        return EnrichmentResult()
    try:
        return parser(payload, mpn)
    except (KeyError, TypeError, ValueError, AttributeError):
        return EnrichmentResult()
