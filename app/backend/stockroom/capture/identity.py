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
    if not same_mpn(observed.mpn, requested_mpn):
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


# Legal entity forms, not descriptive words. A company is the same company with or without the
# form its registration takes, and distributor catalogues carry it while model libraries usually
# do not: the owner's own record says "Abracon LLC" where Ultra Librarian says "Abracon", and an
# exact-MPN match was being discarded over that alone. Deliberately NOT extended to descriptors
# such as "electronics", "semiconductor" or "technologies" - dropping those starts merging names
# that a person would not merge, and this comparison is what stops another manufacturer's
# footprint being attached to a board.
_MANUFACTURER_ENTITY_FORMS = frozenset(
    {
        "ag",
        "bv",
        "co",
        "company",
        "corp",
        "corporation",
        "gmbh",
        "inc",
        "incorporated",
        "kg",
        "kk",
        "limited",
        "llc",
        "ltd",
        "nv",
        "plc",
        "pte",
        "pty",
        "sa",
        "sarl",
        "spa",
        "srl",
    }
)


def _manufacturer_tokens(value: str) -> tuple[str, ...]:
    """The identifying words of a manufacturer name, without its legal entity form."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    words = "".join(
        character if character.isalnum() else " " for character in normalized
    ).split()
    identifying = tuple(word for word in words if word not in _MANUFACTURER_ENTITY_FORMS)
    # A name that is ONLY an entity form identifies nobody; keep it whole rather than empty so it
    # can never compare equal to an unrelated manufacturer.
    return identifying or tuple(words)


_MPN_SLUG_SEPARATORS = ".-_ /"


def _same_slugged_mpn(observed: str, requested: str) -> bool:
    """Accept a separator difference that a URL slug provably destroyed, and nothing else.

    Provider identities here are parsed out of a detail URL, and a slug cannot carry every
    separator a real MPN uses: Ultra Librarian publishes Abracon's ABM13W-32.0000MHZ-5-DH7G-T5 as
    ``ABM13W-32-0000MHZ-5-DH7G-T5``. Demanding punctuation fidelity from a source that already
    discarded it rejected an exact match on every MPN containing a period.

    Deliberately narrow: only separators fold, and only against each other. Every alphanumeric
    character, their order, and the number of separator positions must still agree, so
    ``ABC-1`` never becomes ``ABC1`` or ``ABC-2``. `_mpn_key` remains the primary comparison and
    is still exact; this is the one concession made to a lossy carrier.
    """

    def parts(value: str) -> list[str] | None:
        normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
        if not normalized or not any(character in normalized for character in _MPN_SLUG_SEPARATORS):
            return None
        separated = "".join(
            "\x00" if character in _MPN_SLUG_SEPARATORS else character for character in normalized
        )
        return separated.split("\x00")

    observed_parts = parts(observed)
    requested_parts = parts(requested)
    if observed_parts is None or requested_parts is None:
        return False
    return observed_parts == requested_parts


def same_mpn(left: str, right: str) -> bool:
    """Whether two MPN spellings name the same part number. THE MPN comparison for capture.

    Exact after case and Unicode folding, plus the one concession `_same_slugged_mpn` documents:
    a separator difference a lossy carrier provably destroyed. Public because more than one seam
    now needs it - the provider identity gate that has always used it, and the DigiKey models id
    recovered from browser history, whose only evidence is a page title. A second comparison would
    be a second answer to "is this the requested part", which is the question the whole exact
    identity gate exists to answer once.
    """

    return _mpn_key(left) == _mpn_key(right) or _same_slugged_mpn(left, right)


def _manufacturer_key(value: str) -> str:
    """Normalize presentation separators and the legal entity form, not words or aliases."""
    return "".join(_manufacturer_tokens(value))


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
    if _leads_manufacturer(left, right) or _leads_manufacturer(right, left):
        return True
    if _is_single_token_truncation(left, right):
        # "Micro" is not Microchip. The shared abbreviation proof accepts a truncation, which is
        # right for reconciling a canonical field and wrong here: this comparison decides whether
        # another manufacturer's footprint may be attached to a board.
        return False
    return is_abbreviation_of(left, right) or is_abbreviation_of(right, left)


def _is_single_token_truncation(left: str, right: str) -> bool:
    """One single-word name is a character prefix of the other single-word name.

    Distinct from an initialism, which is what the abbreviation proof exists for: "TI" is not a
    character prefix of "TexasInstruments", so it stays acceptable, while "Micro"/"Microchip" -
    two different companies - no longer does.
    """

    first = _manufacturer_tokens(left)
    second = _manufacturer_tokens(right)
    if len(first) != 1 or len(second) != 1:
        return False
    short, long_form = sorted((first[0], second[0]), key=len)
    return short != long_form and long_form.startswith(short)


def _leads_manufacturer(shorter: str, longer: str) -> bool:
    """True when one name is the LEADING words of the other, whole words only.

    A model library lists the brand; a distributor record appends what it trades under. "Murata"
    heads "Murata Electronics", "Vishay" heads "Vishay Intertechnology", "Nexperia" heads
    "Nexperia USA", "Wurth Elektronik" heads "Wurth Elektronik eiSos" - all one company, and each
    was discarding an exact-MPN match.

    Leading and whole-word, not containment, because those are what keep it closed: "Micro" does
    not head "Microchip" (one token, not a prefix of the token sequence), and "Semiconductor
    Components" does not head "ON Semiconductor" (wrong first word). A trailing difference is a
    descriptor; a differing FIRST word is a different company.
    """

    left = _manufacturer_tokens(shorter)
    right = _manufacturer_tokens(longer)
    if not left or not right or len(left) >= len(right):
        return False
    return right[: len(left)] == left


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
