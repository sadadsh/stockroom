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

if TYPE_CHECKING:
    from stockroom.ingest.staging import StagingCandidate


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
        if _manufacturer_key(observed.manufacturer) != _manufacturer_key(requested_manufacturer):
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


def page_identity(vendor_key: str, url: str) -> PageIdentity | None:
    """Read identity from the canonical detail URL shapes used by current adapters."""
    segments = [_decode_segment(segment) for segment in urlparse(url or "").path.split("/") if segment]
    try:
        if vendor_key == "ultralibrarian":
            index = segments.index("details")
            # /details/<guid>/<manufacturer>/<mpn>
            return PageIdentity(mpn=segments[index + 3], manufacturer=segments[index + 2])
        if vendor_key == "snapmagic":
            index = segments.index("parts")
            # /parts/<mpn>/<manufacturer>/view-part/
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
        if requested_manufacturer and (
            _manufacturer_key(detail.manufacturer) != _manufacturer_key(requested_manufacturer)
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
        if vendor_key in {"ultralibrarian", "snapmagic"} and detail is None:
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
            and _manufacturer_key(candidate_manufacturer) != requested_manufacturer_key
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
