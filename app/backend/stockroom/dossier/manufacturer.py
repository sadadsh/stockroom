"""The manufacturer's own page, held apart from every distributor listing.

The bug this module exists to remove: the official manufacturer page was taken from the first
sourcing offer. A Mouser listing is Mouser's page about the part - it is not the manufacturer
saying anything - and presenting one as the other attributed a reseller's copy, pricing and
lifecycle wording to the company that made the part.

So an offer URL is never a candidate here. The only candidates are places that can actually
carry an official page, and each one is validated before it is called official: the host has to
be the manufacturer's own (`dossier.urls.matches_manufacturer`) or the source metadata has to
say the manufacturer supplied it. A URL that passes neither is still SHOWN - it is real data -
but as an unverified link, never as the official page.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from stockroom.dossier.fields import normalize_key
from stockroom.dossier.urls import host_of, matches_manufacturer, provider_of
from stockroom.providers import provider_label

# States, and the exact difference between them:
#   verified    the host is the manufacturer's own, or the source says the manufacturer gave it
#   unverified  a page was supplied but nothing proves whose it is
#   rejected    a candidate was a distributor's listing and was refused as the official page
#   absent      nothing supplied one, which is a complete answer
PAGE_STATES: tuple[str, ...] = ("verified", "unverified", "rejected", "absent")

# Source keys whose word is itself evidence: these name the manufacturer surface rather than a
# reseller's catalogue entry.
_OFFICIAL_SOURCES: frozenset[str] = frozenset({"manufacturer", "manufacturer_api", "datasheet"})

# Catalogue keys that can carry an official page. `product_url` is deliberately absent: that is
# the DISTRIBUTOR's product page, and reading it here is the exact confusion being removed.
_CATALOG_KEYS: tuple[str, ...] = (
    "manufacturer_page",
    "manufacturer_url",
    "manufacturer_product_url",
)

_SPEC_KEYS: frozenset[str] = frozenset({"manufacturer page", "manufacturer url"})


def _candidates(record) -> list[tuple[str, str]]:
    """(url, source) for everything that could be the manufacturer's page, best claim first."""
    out: list[tuple[str, str]] = []
    page = getattr(record, "manufacturer_page", None)
    if page is not None and page.url:
        out.append((page.url, page.source or "manufacturer"))
    for provider_key, payload in (getattr(record, "catalog", None) or {}).items():
        if not isinstance(payload, Mapping):
            continue
        for key in _CATALOG_KEYS:
            url = str(payload.get(key) or "")
            if url.startswith("https://"):
                out.append((url, str(provider_key)))
    for raw_key, value in (getattr(record, "specs", None) or {}).items():
        if normalize_key(raw_key) in _SPEC_KEYS and isinstance(value, str):
            if value.startswith("https://"):
                out.append((value, ""))
    return out


def manufacturer_page(record) -> dict[str, Any]:
    """The official manufacturer page for this part, with what proved it.

    Never derived from `record.purchase`. That is enforced by construction - the offers are not
    read in this module at all - rather than by a rule somewhere that a later change could slip
    past.
    """
    manufacturer = str(getattr(record, "manufacturer", "") or "")
    stored = getattr(record, "manufacturer_page", None)
    rejected: list[dict[str, str]] = []
    unverified: dict[str, Any] | None = None

    for url, source in _candidates(record):
        provider = provider_of(url)
        if provider is not None and provider.distributor:
            rejected.append(
                {
                    "url": url,
                    "sourceId": source,
                    "sourceLabel": provider_label(source) if source else "",
                    "reason": f"{provider.label} hosts its own listing, not the official page",
                }
            )
            continue
        if matches_manufacturer(url, manufacturer):
            return _page(url, source, "verified", "the host is the manufacturer's own domain",
                         stored, rejected)
        if source.casefold() in _OFFICIAL_SOURCES:
            return _page(url, source, "verified", "the source supplied it as the official page",
                         stored, rejected)
        if unverified is None:
            unverified = {"url": url, "source": source}

    if unverified is not None:
        return _page(
            unverified["url"], unverified["source"], "unverified",
            "nothing proves this host belongs to the manufacturer", stored, rejected,
        )
    return _page("", "", "rejected" if rejected else "absent", "", stored, rejected)


def _page(
    url: str,
    source: str,
    state: str,
    reason: str,
    stored,
    rejected: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "url": url,
        "host": host_of(url),
        "sourceId": source,
        "sourceLabel": provider_label(source) if source else "",
        "state": state,
        "verified": state == "verified",
        "reason": reason,
        "checkedAt": getattr(stored, "checked_at", "") or "",
        # Candidates refused as the official page, kept rather than dropped: a person needs to
        # see that a distributor link was considered and why it was not promoted.
        "rejectedCandidates": rejected,
    }


__all__ = ["PAGE_STATES", "manufacturer_page"]
