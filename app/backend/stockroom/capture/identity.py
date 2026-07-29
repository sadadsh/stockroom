"""Fail-closed identity acceptance for CAD downloaded through a browser.

The requested record name is not evidence about the downloaded bytes. A capture may land on a
nearby search result or a multi-part library, so the ingest candidate must identify the requested
MPN itself before it can be renamed or attached. A recognized vendor detail URL is independent
page-level evidence and, when present, must agree too.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from stockroom.text import is_abbreviation_of

if TYPE_CHECKING:
    from stockroom.ingest.staging import StagingCandidate


_PROVIDER_HOSTS = {
    "digikey": frozenset(
        {
            "digikey.com",
            "www.digikey.com",
        }
    ),
    # The browser surface belongs to DigiKey, but the retained artifact provenance names the
    # library that authored and exported the bytes. Keeping this key distinct prevents DigiKey
    # from looking like a fourth CAD author in variant history.
    "digikey-ultralibrarian": frozenset(
        {
            "digikey.com",
            "www.digikey.com",
        }
    ),
    "digikey-snapmagic": frozenset(
        {
            "digikey.com",
            "www.digikey.com",
        }
    ),
    "digikey-traceparts": frozenset(
        {
            "digikey.com",
            "www.digikey.com",
        }
    ),
    "digikey-manufacturer": frozenset(
        {
            "digikey.com",
            "www.digikey.com",
        }
    ),
    "digikey-cadenas": frozenset(
        {
            "digikey.com",
            "www.digikey.com",
        }
    ),
    "samacsys": frozenset(
        {
            "componentsearchengine.com",
            "www.componentsearchengine.com",
            "samacsys.com",
            "www.samacsys.com",
        }
    ),
    "ultralibrarian": frozenset(
        {
            "app.ultralibrarian.com",
            "www.ultralibrarian.com",
        }
    ),
    "snapmagic": frozenset(
        {
            "snapeda.com",
            "www.snapeda.com",
        }
    ),
}


@dataclass(frozen=True)
class PageIdentity:
    mpn: str
    manufacturer: str


@dataclass(frozen=True)
class CandidateSelection:
    candidate: StagingCandidate | None = None
    error: str = ""


def exact_observation_error(record: object, observed: PageIdentity) -> str:
    """Return why a provider identity is not the requested part, or an empty string."""

    requested_mpn = getattr(record, "mpn", "") or ""
    requested_manufacturer = getattr(record, "manufacturer", "") or ""
    if not requested_mpn.strip():
        return "cannot verify provider identity without a requested MPN"
    if _mpn_key(observed.mpn) != _mpn_key(requested_mpn):
        return (
            "the provider exposed no exact candidate: "
            f"MPN {observed.mpn!r} is not requested MPN {requested_mpn!r}"
        )
    if requested_manufacturer:
        if not observed.manufacturer.strip():
            return (
                "the provider exposed no exact candidate with manufacturer "
                f"{requested_manufacturer!r}"
            )
        if not _same_manufacturer(observed.manufacturer, requested_manufacturer):
            return (
                "the provider exact-MPN candidate identifies manufacturer "
                f"{observed.manufacturer!r}, not {requested_manufacturer!r}"
            )
    return ""


def _decode_segment(value: str) -> str:
    """Decode vendor paths that may have been percent-encoded more than once."""
    decoded = value
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded.strip()


def _mpn_key(value: str) -> str:
    """Case-insensitive but punctuation-preserving MPN comparison.

    Punctuation is meaningful in real MPNs, so unlike a search key this deliberately does not
    collapse ``-``, ``/`` or ``+``.
    """
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def _manufacturer_key(value: str) -> str:
    """Normalize presentation separators, not manufacturer words or aliases."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in normalized if character.isalnum())


def _same_manufacturer(left: str, right: str) -> bool:
    """Accept only an exact spelling or a provable abbreviation relationship.

    Distributor catalogues routinely identify Texas Instruments as ``TI``. Stockroom already has
    one deliberately narrow, adversarially tested abbreviation proof for canonical-field
    reconciliation; reusing that proof here avoids both a second alias table and the false-negative
    fallback observed on LCSC C962978. Unrelated short names such as ``TI`` and ``Toshiba`` still
    fail closed.
    """

    if _manufacturer_key(left) == _manufacturer_key(right):
        return True
    return is_abbreviation_of(left, right) or is_abbreviation_of(right, left)


def provider_url_allowed(
    vendor_key: str,
    url: str,
    *,
    allow_relative: bool = False,
) -> bool:
    """Only an official provider origin, or an explicitly allowed relative href, is trusted."""

    try:
        parsed = urlparse(url or "")
    except Exception:  # noqa: BLE001 - malformed URLs establish no identity
        return False
    if not parsed.netloc:
        return (
            allow_relative
            and not parsed.scheme
            and bool(parsed.path)
            and parsed.path.startswith("/")
        )
    return (
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() in _PROVIDER_HOSTS.get(vendor_key, ())
        and parsed.username is None
        and parsed.password is None
    )


def page_identity(
    vendor_key: str,
    url: str,
    *,
    allow_relative: bool = False,
) -> PageIdentity | None:
    """Read identity from the canonical detail URL shapes used by current adapters."""
    if not provider_url_allowed(vendor_key, url, allow_relative=allow_relative):
        return None
    segments = [
        _decode_segment(segment) for segment in urlparse(url or "").path.split("/") if segment
    ]
    try:
        if vendor_key == "ultralibrarian":
            index = segments.index("details")
            # Both current shapes are in circulation:
            # /details/<manufacturer>/<mpn> and /details/<guid>/<manufacturer>/<mpn>.
            # Identity is always the final two detail segments; an opaque catalogue id is not.
            detail_segments = segments[index + 1 :]
            if len(detail_segments) < 2:
                return None
            return PageIdentity(
                mpn=detail_segments[-1],
                manufacturer=detail_segments[-2],
            )
        if vendor_key == "snapmagic":
            index = segments.index("parts")
            # /parts/<mpn>/<manufacturer>/view-part/
            return PageIdentity(mpn=segments[index + 1], manufacturer=segments[index + 2])
        if vendor_key in {
            "digikey",
            "digikey-snapmagic",
            "digikey-traceparts",
            "digikey-ultralibrarian",
            "digikey-manufacturer",
            "digikey-cadenas",
        }:
            index = segments.index("detail")
            # /en/products/detail/<manufacturer>/<mpn>/<opaque-product-id>
            return PageIdentity(mpn=segments[index + 2], manufacturer=segments[index + 1])
        if vendor_key == "samacsys":
            index = segments.index("part-view")
            # /part-view/<mpn>/<manufacturer>
            return PageIdentity(mpn=segments[index + 1], manufacturer=segments[index + 2])
    except (ValueError, IndexError):
        return None
    return None


def _candidate_mpn_values(candidate: StagingCandidate) -> tuple[str, ...]:
    values = (
        getattr(candidate, "mpn", ""),
        getattr(candidate, "symbol_name", ""),
        getattr(candidate, "entry_name", ""),
        getattr(candidate, "display_name", ""),
    )
    return tuple(value for value in values if isinstance(value, str) and value.strip())


def select_exact_candidate(
    record: object,
    candidates: list[StagingCandidate],
    *,
    vendor_key: str,
    detail_url: str,
) -> CandidateSelection:
    """Return the one candidate demonstrably belonging to ``record``, else an error.

    An empty candidate list is not an identity failure: it may be an Altium-only download handled
    by the separate native-library seam. Once KiCad candidates exist, however, choosing by list
    order is forbidden.
    """
    requested_mpn = getattr(record, "mpn", "") or ""
    requested_manufacturer = getattr(record, "manufacturer", "") or ""
    if not requested_mpn.strip():
        return CandidateSelection(error="cannot attach downloaded CAD without a requested MPN")

    detail = page_identity(vendor_key, detail_url)
    if detail is not None:
        if _mpn_key(detail.mpn) != _mpn_key(requested_mpn):
            return CandidateSelection(
                error=(
                    "the vendor detail page identifies "
                    f"{detail.mpn!r}, not requested MPN {requested_mpn!r}"
                )
            )
        if requested_manufacturer and not _same_manufacturer(
            detail.manufacturer,
            requested_manufacturer,
        ):
            return CandidateSelection(
                error=(
                    "the vendor detail page identifies manufacturer "
                    f"{detail.manufacturer!r}, not {requested_manufacturer!r}"
                )
            )

    if not candidates:
        # A native Altium-only archive has no ingest candidate to interrogate. For the implemented
        # browser providers, the canonical detail page must therefore carry the exact identity;
        # otherwise `_attach_altium_assets` would fall back to an arbitrary first library entry.
        if (
            vendor_key
            in {
                "digikey-snapmagic",
                "digikey-ultralibrarian",
                "samacsys",
                "snapmagic",
                "ultralibrarian",
            }
            and detail is None
        ):
            return CandidateSelection(
                error=(
                    "the vendor page does not demonstrate the requested part identity; "
                    "refusing to attach an Altium-only download"
                )
            )
        return CandidateSelection()

    requested_mpn_key = _mpn_key(requested_mpn)
    requested_manufacturer_key = _manufacturer_key(requested_manufacturer)
    matches: list[StagingCandidate] = []
    mpn_matches = 0
    manufacturer_conflicts: list[str] = []
    for candidate in candidates:
        if requested_mpn_key not in {_mpn_key(value) for value in _candidate_mpn_values(candidate)}:
            continue
        mpn_matches += 1
        candidate_manufacturer = getattr(candidate, "manufacturer", "") or ""
        if (
            requested_manufacturer_key
            and candidate_manufacturer
            and not _same_manufacturer(candidate_manufacturer, requested_manufacturer)
        ):
            manufacturer_conflicts.append(candidate_manufacturer)
            continue
        if requested_manufacturer_key and not candidate_manufacturer and detail is None:
            continue
        matches.append(candidate)

    if len(matches) == 1:
        return CandidateSelection(candidate=matches[0])
    if len(matches) > 1:
        return CandidateSelection(
            error=(
                f"the download contains {len(matches)} candidates for requested MPN "
                f"{requested_mpn!r}; refusing to choose by file order"
            )
        )
    if manufacturer_conflicts:
        found = ", ".join(sorted(set(manufacturer_conflicts)))
        return CandidateSelection(
            error=(
                f"the candidate for {requested_mpn!r} identifies manufacturer {found!r}, "
                f"not {requested_manufacturer!r}"
            )
        )
    if mpn_matches and requested_manufacturer_key and detail is None:
        return CandidateSelection(
            error=(
                f"the download does not demonstrate manufacturer {requested_manufacturer!r} "
                f"for requested MPN {requested_mpn!r}"
            )
        )
    return CandidateSelection(
        error=f"the download does not contain an exact candidate for requested MPN {requested_mpn!r}"
    )
