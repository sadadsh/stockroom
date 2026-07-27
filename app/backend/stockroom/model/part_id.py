"""The part id: `slug(mpn) + "-" + sha256(mpn)[:4]`.

DECIDED in `docs/specs/2026-07-27-owner-spec-complete-trusted-library.md` section 9. The id is
a FILENAME (`parts/<id>.json`) and a git path (`sourced/<id>/<vendor>.json`), so it must be
stable forever, unique, Windows-safe, and a PURE function of something immutable.

Why each half:

- **The stem is a slug of the MPN**, so a human reading `git log` or a directory listing sees
  what the part is. `display_name` is DERIVED and carries the human naming scheme; the id does
  not have to, and must not, because a naming-scheme change is a re-derive and an id that
  moved would be a rename of every file in the library.
- **The suffix is 4 hex of sha256(mpn), because slugging is LOSSY and collides.** Measured in
  the owner's own library: `MAX6817EUT+T` (owned) and `MAX6817EUT-T` slug identically, and a
  filename collision silently MERGES two parts. The fingerprint makes that impossible while
  keeping the readable stem.
- **Manufacturer is deliberately absent.** It comes from a source and varies between them
  ("Texas Instruments" vs "TI"), so an id built on it would not be stable.

PRIOR ART evaluated before hand-rolling (2026-07-27), external and internal:

- **`python-slugify` (un33k)** - the standard slugifier, wraps Unidecode for transliteration.
  REJECTED, and the reason is the one property that matters here: its output depends on a
  third-party transliteration table that changes between releases. A part id is a permanent
  git path, so an upgrade that re-transliterates one character would rename records and every
  raw payload filed beside them. A dependency whose output may move cannot back a forever-name.
- **`pathvalidate` (thombashi)** - validates and sanitizes filenames per platform, including
  the Windows device names. REJECTED as a dependency, ADOPTED as a source: it SANITIZES
  (mutates input toward legality), while this module needs a total, frozen predicate over a
  fixed alphabet. Our alphabet `[a-z0-9-]` is already a strict subset of every platform's
  legal set, so validation reduces to one regex plus one membership test, and the reserved-name
  list is taken from Microsoft's own naming documentation rather than from a package.
- **`stockroom.model.category.slugify`** (in-repo) - REJECTED for this use: it folds
  separators to UNDERSCORE for KiCad library nicknames, and the decided id alphabet is
  `[a-z0-9-]`. Reusing it would emit `max6817eut_t`, violating the decision. It stays the
  right function for its own job; the two slugs answer different questions.

Deliberately a leaf module: stdlib only, no project imports, so anything may import it.
"""

from __future__ import annotations

import hashlib
import re

# Four hex characters = 65,536 buckets, applied only to MPNs that already share a slug. It is
# a de-collider for a lossy slug, not a content hash, so it is sized for readability.
FINGERPRINT_LEN = 4

# The fallback stem for an MPN that slugs to nothing (punctuation- or unicode-only). The
# fingerprint still separates two such parts, so `part-<hex>` is unique, not a bucket.
FALLBACK_STEM = "part"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PART_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Names Windows refuses to open, with or without an extension: `CON.json` is unopenable, and
# the failure lands at the OS layer where no application error message explains it. Source:
# Microsoft, "Naming Files, Paths, and Namespaces" (learn.microsoft.com), which lists CON,
# PRN, AUX, NUL, COM0-COM9 and LPT0-LPT9 (plus superscript COM/LPT variants, which cannot
# survive slugging and so need no entry here).
#
# The library is a Windows-first git checkout, and Windows applies the check to the name
# BEFORE the first period, which is why the whole id - not just its first token - is what
# gets validated below.
WINDOWS_RESERVED_STEMS: frozenset[str] = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(10)}
    | {f"lpt{n}" for n in range(10)}
)


def slug_mpn(mpn: str) -> str:
    """The readable stem of an MPN: lowercase, every non-alphanumeric run folded to one
    hyphen, hyphens trimmed off both ends. LOSSY on purpose (it is for humans); the
    fingerprint is what carries the exactness."""
    return _SLUG_RE.sub("-", (mpn or "").strip().lower()).strip("-")


def mpn_fingerprint(mpn: str) -> str:
    """The first `FINGERPRINT_LEN` hex characters of sha256 over the EXACT MPN bytes.

    Exact means exact: `MAX6817EUT+T` and `MAX6817EUT-T` differ here even though their slugs
    do not, and that is the entire reason this exists.
    """
    return hashlib.sha256((mpn or "").encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


def is_reserved_stem(name: str) -> bool:
    """Whether `name` is a Windows device name that cannot be used as a file stem."""
    return (name or "").strip().lower() in WINDOWS_RESERVED_STEMS


def make_part_id(mpn: str) -> str:
    """The part id for `mpn`. Raises ValueError for a blank MPN.

    A part with no MPN has no stable identity, so inventing one here would hand out an id that
    changes the moment the MPN arrives - and the id is a git path, so changing it is a rename
    of the record AND of every raw payload filed beside it.
    """
    if not (mpn or "").strip():
        raise ValueError("a part id needs an MPN: there is nothing stable to derive it from")
    stem = slug_mpn(mpn) or FALLBACK_STEM
    # Defence in depth. The `-<hex>` suffix already means the composed name can never EQUAL a
    # reserved stem, so this branch is unreachable today; it is here so a future change to the
    # suffix cannot silently reintroduce `CON.json`, and `is_valid_part_id` enforces the same
    # rule on ids this function did not produce.
    if is_reserved_stem(stem):
        stem = f"{FALLBACK_STEM}-{stem}"
    return f"{stem}-{mpn_fingerprint(mpn)}"


def is_valid_part_id(part_id: str) -> bool:
    """Whether `part_id` is safe as a filename and a git path on every platform.

    Lowercase `[a-z0-9-]`, no leading/trailing or doubled hyphen, and never a Windows device
    name. Says nothing about whether the id matches any particular MPN - `part_id_matches`
    answers that.
    """
    if not part_id or not _PART_ID_RE.match(part_id):
        return False
    return not is_reserved_stem(part_id)


def part_id_matches(part_id: str, mpn: str) -> bool:
    """Whether `part_id` is exactly what this scheme derives from `mpn`.

    The id is a pure function of the MPN, so this is checkable rather than assumed: a
    hand-edited id, a record whose MPN was corrected without a re-file, or an id minted by an
    older scheme all fail here.
    """
    try:
        return part_id == make_part_id(mpn)
    except ValueError:
        return False
