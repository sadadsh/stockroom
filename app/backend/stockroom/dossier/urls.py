"""Reading a URL for what it proves about who published it.

Two questions come up everywhere in the dossier and must be answered the same way each time:
whose site is this, and is it the manufacturer's own. Getting the second one wrong is what let a
distributor's listing be presented as the official manufacturer page.

Deliberately structural. There is no network call here and no allow-list of hand-collected
manufacturer domains to go stale: the provider registry already knows the distributor and CAD
hosts, and a manufacturer host is recognised by its own name appearing in its own domain. A host
this cannot place comes back unplaced, which the caller reports as unverified rather than
promoting on a guess.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from stockroom.providers import ProviderRecord, provider_for_host

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Corporate boilerplate that appears in a legal name and never in a domain. Removed before
# matching so `STMicroelectronics N.V.` is compared on the part of the name that identifies it.
_CORPORATE_WORDS: frozenset[str] = frozenset(
    {
        "ag", "co", "company", "corp", "corporation", "electronic", "electronics", "gmbh",
        "group", "holdings", "inc", "incorporated", "industries", "international", "kk",
        "limited", "llc", "ltd", "microelectronics", "nv", "plc", "sa", "semiconductor",
        "semiconductors", "solutions", "technologies", "technology",
    }
)

# File extensions that say a link is the document itself rather than a page describing it.
_PDF_SUFFIXES: tuple[str, ...] = (".pdf",)


def host_of(url: object) -> str:
    """The lower-cased host of a URL, without a `www.` prefix. "" when there is no host."""
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        host = urlsplit(text).netloc.casefold()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def provider_of(url: object) -> ProviderRecord | None:
    """The registered provider serving this URL, or None when no provider claims the host."""
    host = host_of(url)
    return provider_for_host(host) if host else None


def is_pdf(url: object, mime_type: object = "") -> bool:
    """True when the reference is to a PDF rather than to a page about one."""
    if "pdf" in str(mime_type or "").casefold():
        return True
    path = urlsplit(str(url or "")).path.casefold()
    return path.endswith(_PDF_SUFFIXES)


def _name_tokens(manufacturer: object) -> list[str]:
    words = [word for word in _NON_ALNUM.split(str(manufacturer or "").casefold()) if word]
    return [word for word in words if word not in _CORPORATE_WORDS]


def _domain_label(host: str) -> str:
    """The registrable label of a host: `st` for `www.st.com`, `analog` for `analog.com`."""
    parts = [part for part in host.split(".") if part]
    if len(parts) < 2:
        return _NON_ALNUM.sub("", host)
    # A two-part public suffix (`co.uk`, `com.cn`) leaves the label one place further left.
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov"} and len(parts[-1]) == 2:
        return _NON_ALNUM.sub("", parts[-3])
    return _NON_ALNUM.sub("", parts[-2])


def matches_manufacturer(url: object, manufacturer: object) -> bool:
    """True when this URL's host is plausibly the manufacturer's own.

    Three structural matches, in increasing looseness, and nothing beyond them:
      * a name word appears inside the domain label (`vishay` in `vishay`);
      * the domain label is the start of a name word (`st` of `stmicroelectronics`);
      * the domain label is the acronym of the name words (`ti` of `texas instruments`).

    A host a registered provider already claims is never a manufacturer host, whatever its name
    happens to contain - that is what stops a distributor's listing being promoted.
    """
    host = host_of(url)
    if not host:
        return False
    if provider_for_host(host) is not None:
        return False
    label = _domain_label(host)
    if not label:
        return False
    tokens = _name_tokens(manufacturer)
    if not tokens:
        return False
    for token in tokens:
        if len(token) >= 3 and token in label:
            return True
        if len(label) >= 2 and token.startswith(label):
            return True
    acronym = "".join(token[0] for token in tokens)
    return len(acronym) >= 2 and acronym == label


__all__ = ["host_of", "is_pdf", "matches_manufacturer", "provider_of"]
