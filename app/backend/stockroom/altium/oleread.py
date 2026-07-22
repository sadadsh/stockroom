"""Read component/footprint entry NAMES from Altium .SchLib/.PcbLib (OLE2 compound files),
read-only via olefile. We read the AUTHORITATIVE name records, not the top-level OLE storage
names, because storage names are truncated to 31 chars (so a long symbol/footprint name would
be silently wrong) and a metadata storage can look like a component. The authoritative sources:

- .SchLib: the `FileHeader` stream, a pipe-delimited key=value blob carrying `LibRef<N>=<name>`.
- .PcbLib: the `Library/Data` stream, whose trailing records are `<u32 len><u8 namelen><name>`
  (len == namelen + 1).

A storage-name walk (with a narrow metadata blocklist) is kept only as a fallback for a file
that lacks those streams. We never open the graphics and never write Altium binary."""
from __future__ import annotations

import re
import struct
from pathlib import Path

import olefile

# Fallback-only: exact top-level metadata storages that carry a Data child in a real lib. Kept
# minimal + specific so it can never drop a legitimately-named component (e.g. a symbol "Header").
_META_ENTRIES = frozenset({"fileheader", "fileversioninfo", "library", "storage", "sectionkeys"})

# Altium varies the FileHeader key case by version (LibRef0= vs LIBREF0=), so match case-insensitively.
_LIBREF = re.compile(r"LibRef\d+=([^|]+)", re.IGNORECASE)


def _symbol_names_from_header(raw: bytes) -> list[str]:
    """Symbol names from a .SchLib FileHeader blob: the `LibRef<N>=<name>` records (full,
    untruncated). Order preserved, duplicates dropped."""
    names = [m.strip() for m in _LIBREF.findall(raw.decode("latin-1")) if m.strip()]
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def _footprint_names_from_data(raw: bytes) -> list[str]:
    """Footprint names from a .PcbLib Library/Data blob: `<u32 reclen><u8 namelen><name>` with
    reclen == namelen + 1 and an all-printable name. Order preserved, duplicates dropped."""
    names: list[str] = []
    i, n = 0, len(raw)
    while i + 5 <= n:
        reclen = struct.unpack_from("<I", raw, i)[0]
        if 2 <= reclen <= 256 and i + 4 + reclen <= n:
            namelen = raw[i + 4]
            if namelen == reclen - 1 and namelen >= 1:
                cand = raw[i + 5 : i + 5 + namelen]
                if all(0x20 <= b < 0x7F for b in cand):
                    names.append(cand.decode("latin-1"))
                    i += 4 + reclen
                    continue
        i += 1
    seen: set[str] = set()
    return [x for x in names if not (x in seen or seen.add(x))]


def _storage_walk(ole) -> list[str]:
    """Fallback: top-level storages holding a Data child, minus the narrow metadata set. Names
    may be 31-char-truncated (only used when the authoritative stream is absent)."""
    entries = ole.listdir(streams=True, storages=True)
    tops = {e[0] for e in entries}
    return sorted(
        name for name in tops if [name, "Data"] in entries and name.lower() not in _META_ENTRIES
    )


def read_symbol_names(path) -> list[str]:
    with olefile.OleFileIO(str(Path(path))) as ole:
        if ole.exists(["FileHeader"]):
            names = _symbol_names_from_header(ole.openstream(["FileHeader"]).read())
            if names:
                return names
        return _storage_walk(ole)


def read_footprint_names(path) -> list[str]:
    with olefile.OleFileIO(str(Path(path))) as ole:
        if ole.exists(["Library", "Data"]):
            names = _footprint_names_from_data(ole.openstream(["Library", "Data"]).read())
            if names:
                return names
        return _storage_walk(ole)


def pick_entry(names: list[str], kind: str, prefer: str | None = None) -> str:
    """Choose the one entry to bind from a library's entry names. A single entry is used; with
    several, an exact `prefer` (e.g. the MPN) wins; otherwise it is ambiguous and we fail loud
    rather than silently binding the alphabetically-first (which would place the wrong part)."""
    if not names:
        raise ValueError(f"no {kind} entry found in the library")
    if len(names) == 1:
        return names[0]
    if prefer and prefer in names:
        return prefer
    raise ValueError(
        f"the library has {len(names)} {kind} entries {names}; expected one, or a name matching "
        f"the MPN. Provide a single-part library or the exact entry name."
    )
