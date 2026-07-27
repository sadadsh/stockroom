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

ORDER IS THE CONTRACT. `merge_missing` gives the slot to whoever fills it FIRST, so the order of
this table decides which vendor's description and specs win. It is an explicit tuple rather than
dict insertion order or a set, because the derivation must be deterministic to be idempotent -
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

# Source key -> parser, in PRIORITY ORDER (first to fill a field keeps it).
#
# Mouser leads DigiKey only because that is the order the live registry already walks, so a
# re-derive reproduces the values the import produced rather than quietly re-picking winners the
# first time it runs. Changing this order is a legitimate derivation-rules change and must bump
# `RULESET_VERSION` in model/derived.py, which is exactly what that stamp is for.
PAYLOAD_PARSERS: tuple[tuple[str, PayloadParser], ...] = (
    ("mouser", parse_mouser_payload),
    ("digikey", parse_digikey_payload),
)

_BY_NAME: dict[str, PayloadParser] = dict(PAYLOAD_PARSERS)


def known_sources() -> tuple[str, ...]:
    """Source keys that can be re-derived from, in priority order."""
    return tuple(name for name, _ in PAYLOAD_PARSERS)


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
