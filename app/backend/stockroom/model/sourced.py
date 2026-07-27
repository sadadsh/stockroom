"""`sourced/<id>/<vendor>.json`: the raw pull, byte for byte, as evidence.

DECIDED in `docs/specs/2026-07-27-owner-spec-complete-trusted-library.md` section 6 (D1) and
settled by section 10:

- **SOURCED is immutable.** Exactly what each source returned, per source, byte for byte.
  Never normalized, never overwritten, never merged. It is the evidence.
- **DERIVED is disposable**, and it is only safe to recompute because the evidence it was
  computed from is still here. "Import everything so we can change the way the data's
  manipulated later" is only possible if the authentic pull survives.
- **A re-derive READS this tree and NEVER writes it.** Nothing in the derivation path may
  import this module's writer.
- **It is COMMITTED, not cached.** Device parity settles what section 9 left open: a
  per-machine cache would let two devices derive different `display_name`, `category` and
  `specs` for the same part - "same info" broken by construction - and a re-derive on a fresh
  clone would need a full re-fetch from every distributor.

REJECTED (recorded so they are not re-proposed): storing payloads INLINE in the record (~300 MB
at 10k parts, and unreviewable diffs), and a per-machine cache (breaks device parity as above).
LFS stays available later for size with no schema change, because these are re-fetchable
evidence rather than authored truth - an LFS object still travels, so parity holds.

PRIOR ART (checked before writing, 2026-07-27): this is the raw/staged split every ELT tool
has landed on - dbt's "sources are immutable, models are rebuildable", Airbyte/Singer's raw
destination tables, and the data-lake bronze/silver/gold convention. All of them keep the
vendor response as-received and rebuild everything downstream. None is adopted as a dependency:
they are warehouse tooling, and the storage here has to be a git-mergeable file tree because
device parity is the requirement. What IS adopted from them is the rule that the raw layer is
append-only and never edited in place.

Why the bytes and not a re-serialized copy: `json.dumps(json.loads(x))` silently loses key
order, indentation, whitespace and the exact float spelling a vendor sent. That is a rewrite of
evidence, and the current schema already lost a value that way - `spec_hygiene.normalize_spec_*`
rewrote the winning value at IMPORT time, so the raw winner is gone from every existing record.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.model.part_id import is_valid_part_id

SOURCED_DIRNAME = "sourced"

# A source key: lowercase, starts alphanumeric, then alphanumerics/underscore/hyphen. Narrow on
# purpose - this becomes a filename, and a name that can contain a separator or a dot can
# escape the part's directory.
_SOURCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class SourcedPayloadExists(Exception):
    """Raised when a write would replace existing evidence without saying so.

    Append-only in practice: a re-pull is legitimate and rewrites exactly one file, but it has
    to be DELIBERATE (`refetch=True`). An accidental overwrite would destroy the only copy of
    what a source actually returned, and nothing downstream could tell.
    """


@dataclass
class SourceEntry:
    """One line of a record's `sources` INDEX: which source, when it was pulled, and where the
    payload sits. Never the payload itself - that is the whole point of D1, and it is what
    keeps `parts/<id>.json` small, readable and mergeable."""

    fetched_at: str = ""
    # Repo-relative POSIX path, normally `sourced/<id>/<source>.json`. Stored rather than
    # recomputed so a payload that later moves (to LFS, or to a renamed source) stays findable
    # from the record.
    file: str = ""
    # Keys a newer build wrote here, kept verbatim and re-emitted.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {**self.extra, "fetched_at": self.fetched_at, "file": self.file}

    @classmethod
    def from_dict(cls, d: dict) -> "SourceEntry":
        known = {"fetched_at", "file"}
        return cls(
            fetched_at=d.get("fetched_at", ""),
            file=d.get("file", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


def _check_source(source: str) -> str:
    if not source or not _SOURCE_NAME_RE.match(source):
        raise ValueError(
            f"unsafe source name {source!r}: expected lowercase [a-z0-9][a-z0-9_-]*"
        )
    return source


def _check_part_id(part_id: str) -> str:
    if not is_valid_part_id(part_id):
        raise ValueError(f"unsafe part id {part_id!r}")
    return part_id


def source_rel_path(part_id: str, source: str) -> str:
    """The repo-relative POSIX path of one source's payload. This exact string is what the
    record's `sources` index stores, so it must never be built with `str(Path)` - a Windows
    backslash in a committed record would not resolve on a peer."""
    return f"{SOURCED_DIRNAME}/{_check_part_id(part_id)}/{_check_source(source)}.json"


def sourced_dir(library_root: Path, part_id: str) -> Path:
    """The directory holding every raw payload for one part."""
    return Path(library_root) / SOURCED_DIRNAME / _check_part_id(part_id)


def sourced_file(library_root: Path, part_id: str, source: str) -> Path:
    return Path(library_root) / source_rel_path(part_id, source)


def write_payload(
    library_root: Path, part_id: str, source: str, payload: str | bytes, *, refetch: bool = False
) -> str:
    """Store one source's response verbatim. Returns the repo-relative path for the record's
    `sources` index.

    `payload` is written as bytes with no re-encoding, no re-serialization and no newline
    translation, so what comes back out is what the source sent. A `str` is encoded UTF-8 and
    nothing else.

    Refuses to replace DIFFERENT existing bytes unless `refetch=True`; rewriting identical
    bytes is a no-op, so an idempotent importer never has to special-case a part it already
    has.
    """
    path = sourced_file(library_root, part_id, source)
    data = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if path.exists():
        if path.read_bytes() == data:
            return source_rel_path(part_id, source)
        if not refetch:
            raise SourcedPayloadExists(
                f"{source_rel_path(part_id, source)} already holds different evidence; "
                f"pass refetch=True to record a new pull"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return source_rel_path(part_id, source)


def read_payload(library_root: Path, part_id: str, source: str) -> str:
    """The stored payload as text, decoded UTF-8. Raises FileNotFoundError when the part has
    no evidence from that source - never returns an empty string, which would read downstream
    as "the source returned nothing"."""
    return sourced_file(library_root, part_id, source).read_text(encoding="utf-8")


def read_json(library_root: Path, part_id: str, source: str):
    """The stored payload, parsed. This is the deriver's entry point: it READS."""
    return json.loads(read_payload(library_root, part_id, source))


def list_sources(library_root: Path, part_id: str) -> list[str]:
    """Every source this part has evidence from, sorted. Empty when it has none."""
    directory = sourced_dir(library_root, part_id)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json") if p.is_file())


def load_all(library_root: Path, part_id: str) -> dict[str, object]:
    """Every stored payload for a part, parsed and keyed by source. The whole evidence set a
    re-derive works from."""
    return {name: read_json(library_root, part_id, name) for name in list_sources(library_root, part_id)}
