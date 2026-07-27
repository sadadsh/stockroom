"""WHICH credentialed adapter fetches the raw payload for each source. Data, not a branch.

The sibling of `derive.payloads`, and deliberately a SEPARATE registry from it:

    derive.payloads   source -> pure parser.   No credentials. Runs on a fresh clone.
    importer.sources  source -> live fetcher.  Needs API keys. Runs only where they exist.

Splitting them is what makes a re-derive possible without credentials (see `derive/payloads.py`),
and keeping the FETCH side here is what keeps `if source == "mouser"` out of the import engine.
Adding a distributor is one entry in each table plus a `fetch_payload` on its adapter.

The two tables must stay in step, or the importer would store a payload nothing can parse - which
would look like a successful import and derive to nothing. That is gated by
`tests/backend/importer/test_source_registry.py`, which asserts every fetcher has a parser and
that the fetch order matches the parse priority order.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class PayloadFetcher(Protocol):
    """What the importer needs of a source: is it usable here, and what did it return.

    Structural rather than a base class, so the existing `MouserAdapter` / `DigiKeyAdapter`
    satisfy it as they are - they already carry `enabled` and now carry `fetch_payload`. A new
    adapter needs no inheritance, which is what keeps this a registry and not a hierarchy.
    """

    last_status: str

    @property
    def enabled(self) -> bool: ...

    def fetch_payload(self, mpn: str) -> dict | None: ...


def _mouser(config) -> PayloadFetcher:
    from stockroom.enrich.mouser import MouserAdapter

    return MouserAdapter(api_key=getattr(config, "mouser_api_key", "") or "")


def _digikey(config) -> PayloadFetcher:
    from stockroom.enrich.digikey_api import DigiKeyAdapter

    return DigiKeyAdapter(
        client_id=getattr(config, "digikey_client_id", "") or "",
        client_secret=getattr(config, "digikey_client_secret", "") or "",
    )


# Source key -> a builder taking the machine config. SAME ORDER as `derive.payloads`, because the
# order there decides which vendor's answer wins a field and an importer that fetched in a
# different order would make the two halves describe different priorities.
SOURCE_BUILDERS: tuple[tuple[str, Callable[[object], PayloadFetcher]], ...] = (
    ("mouser", _mouser),
    ("digikey", _digikey),
)


def build_sources(config) -> list[tuple[str, PayloadFetcher]]:
    """Every source that is actually USABLE on this machine, in priority order.

    A source with no credentials is OMITTED rather than included-and-failing, so the importer's
    own report can say "digikey: not configured" instead of logging 158 identical failures. It is
    not an error: a machine with only a Mouser key imports Mouser evidence and can be re-derived
    later when a DigiKey key is added - additively, because `sourced/` is append-only.
    """
    out: list[tuple[str, PayloadFetcher]] = []
    for key, build in SOURCE_BUILDERS:
        adapter = build(config)
        if adapter.enabled:
            out.append((key, adapter))
    return out


def source_names() -> tuple[str, ...]:
    return tuple(key for key, _ in SOURCE_BUILDERS)
