"""Read placed components from an Altium .SchDoc (binary schematic), read-only.

A .SchDoc is an OLE2 compound file whose `FileHeader` stream is a sequence of
length-prefixed ASCII pipe records: `<u32 little-endian>` with the payload length
in the low 3 bytes and the record type in the high byte (0 = ASCII), then
`|KEY=VALUE|KEY=VALUE...` NUL-terminated. Object records carry `RECORD=<n>` and
point at their owner via `OWNERINDEX`, which counts records from zero starting at
the first record AFTER the file header record (python-altium's convention; a
stream with no header record indexes from its first record).

The records this reader uses:

- RECORD=1  SchComponent: LIBREFERENCE (the symbol entry), DESIGNITEMID (the DbLib
  item, i.e. the MPN for a Stockroom-placed part), PARTCOUNT/CURRENTPARTID.
- RECORD=34 Designator: NAME=Designator, TEXT=<ref>, owned by the component.
- RECORD=41 Parameter: NAME/TEXT pairs, owned by the component (a DbLib placement
  carries every Stockroom column here: MPN, Manufacturer, Description, ...).
- RECORD=44/45 Implementation list/implementation: the CURRENT footprint is the
  RECORD=45 with MODELTYPE=PCBLIB and ISCURRENT=T, owned (via 44) by the component.

Altium may write a key twice, `|NAME=x|%UTF8%NAME=x`, with the %UTF8% bytes
authoritative; that variant wins. A multi-part component (an op-amp's units)
places one RECORD=1 per unit sharing the designator; this reader collapses them
to ONE physical component. We never open the graphics and never write Altium
binary (same read-only stance as oleread.py).
"""

from __future__ import annotations

import struct
from pathlib import Path

import olefile

_ASCII_RECORD = 0


def _parse_records(raw: bytes) -> list[dict]:
    """The stream's ASCII pipe records, in order, each as {key: value}. Stops at a
    zero length word (zero padding) or a truncated tail."""
    records: list[dict] = []
    i, n = 0, len(raw)
    while i + 4 <= n:
        word = struct.unpack_from("<I", raw, i)[0]
        length = word & 0x00FFFFFF
        rectype = word >> 24
        if length == 0:
            break
        i += 4
        if i + length > n:
            break
        payload = raw[i : i + length]
        i += length
        if rectype != _ASCII_RECORD:
            # a non-ASCII record (not expected in a schematic FileHeader) is skipped,
            # but still consumes its length so framing stays aligned
            continue
        records.append(_parse_pipe_record(payload.rstrip(b"\x00")))
    return records


def _parse_pipe_record(payload: bytes) -> dict:
    """`|KEY=VALUE|...` -> {KEY: VALUE}. Values decode latin-1; a `%UTF8%KEY` twin
    decodes utf-8 and overrides the latin-1 spelling."""
    fields: dict[str, str] = {}
    utf8_keys: set[str] = set()
    for part in payload.split(b"|"):
        if not part or b"=" not in part:
            continue
        rk, rv = part.split(b"=", 1)
        key = rk.decode("latin-1")
        if key.upper().startswith("%UTF8%"):
            real = key[len("%UTF8%") :]
            fields[real] = rv.decode("utf-8", errors="replace")
            utf8_keys.add(real)
        elif key not in utf8_keys:
            fields[key] = rv.decode("latin-1")
    return fields


def _object_records(records: list[dict]) -> list[dict]:
    """Drop the file header record (HEADER=...) so OWNERINDEX matches list position."""
    if records and "HEADER" in records[0] and "RECORD" not in records[0]:
        return records[1:]
    return records


def _owner_component(objects: list[dict], start: int, comp_indices: set[int]) -> int | None:
    """Walk OWNERINDEX up from `start` to the owning RECORD=1, or None. Bounded by
    the object count so a corrupt cycle can never hang."""
    idx = start
    for _ in range(len(objects)):
        if idx in comp_indices:
            return idx
        if not (0 <= idx < len(objects)):
            return None
        raw = objects[idx].get("OWNERINDEX", "")
        try:
            idx = int(raw)
        except ValueError:
            return None
    return None


def _components_from_stream(raw: bytes) -> list[dict]:
    """Every physical placed component in a FileHeader stream:
    [{designator, lib_ref, design_item_id, params, footprint}]. Multi-part unit
    placements sharing a designator collapse to one entry (params merged, first
    unit's identity wins)."""
    objects = _object_records(_parse_records(raw))
    comp_indices = {i for i, r in enumerate(objects) if r.get("RECORD") == "1"}

    by_index: dict[int, dict] = {
        i: {
            "designator": "",
            "lib_ref": objects[i].get("LIBREFERENCE", ""),
            "design_item_id": objects[i].get("DESIGNITEMID", ""),
            "_part_id": objects[i].get("CURRENTPARTID", ""),
            "params": {},
            "footprint": "",
        }
        for i in comp_indices
    }

    for i, rec in enumerate(objects):
        kind = rec.get("RECORD")
        if kind == "34":
            owner = _owner_component(objects, i, comp_indices)
            if owner is not None and rec.get("TEXT"):
                by_index[owner]["designator"] = rec["TEXT"]
        elif kind == "41":
            owner = _owner_component(objects, i, comp_indices)
            name = rec.get("NAME", "")
            if owner is not None and name:
                by_index[owner]["params"][name] = rec.get("TEXT", "")
        elif kind == "45":
            if rec.get("MODELTYPE", "").upper() != "PCBLIB":
                continue
            if rec.get("ISCURRENT", "").upper() != "T":
                continue
            owner = _owner_component(objects, i, comp_indices)
            if owner is not None and rec.get("MODELNAME"):
                by_index[owner]["footprint"] = rec["MODELNAME"]

    # Collapse multi-part placements: same designator + same LIBREFERENCE with a
    # DIFFERENT unit id (CURRENTPARTID) is another unit of ONE physical component.
    # The same unit id repeated (two unannotated "R?" copies of a single-part
    # symbol) is two physical parts and never merges; a blank designator never
    # merges either.
    out: list[dict] = []
    seen: dict[tuple[str, str], dict] = {}
    for i in sorted(by_index):
        c = by_index[i]
        part_id = c.pop("_part_id")
        key = (c["designator"], c["lib_ref"])
        if c["designator"] and key in seen:
            merged, seen_part_ids = seen[key]
            if part_id not in seen_part_ids:
                seen_part_ids.add(part_id)
                for k, v in c["params"].items():
                    merged["params"].setdefault(k, v)
                if not merged["footprint"]:
                    merged["footprint"] = c["footprint"]
                continue
            # same unit id again: a distinct physical copy, falls through to append
        if c["designator"]:
            seen.setdefault(key, (c, {part_id}))
        out.append(c)
    return out


def read_schdoc_components(path) -> list[dict]:
    """Placed components from a .SchDoc file. [] when the OLE holds no FileHeader
    stream (not a schematic); raises on a file that is not an OLE container at all
    (the caller decides whether that is a per-sheet skip or an error)."""
    with olefile.OleFileIO(str(Path(path))) as ole:
        if not ole.exists(["FileHeader"]):
            return []
        return _components_from_stream(ole.openstream(["FileHeader"]).read())
