"""Normalize any Altium library input to a loose (.SchLib, .PcbLib) pair so the DbLib always
references loose files (Altium's own IntLib->DbLib migration does the same).

A vendor delivers either loose .SchLib/.PcbLib or a compiled .IntLib. An .IntLib is a CFB
that embeds the source libraries under top-level SchLib/ and PCBLib/ storages, each stream
prefixed by a compression tag byte (0x02 = zlib, 0x00 = raw); the remainder is a byte-complete
standalone source CFB. We replicate KiCad's DecodeIntLibStream in pure Python (olefile + zlib),
decompressing the vendor's own embedded bytes verbatim. We never write Altium binary."""
from __future__ import annotations

import zlib
from pathlib import Path

import olefile

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EXTRACT_HINT = (
    "Open it in Altium (File > Open, then Extract) and provide the loose .SchLib/.PcbLib."
)


def _decode_stream(raw: bytes) -> bytes:
    """An IntLib embedded-library stream: byte 0 is a compression tag (0x02 = zlib, 0x00 =
    raw); the remainder is the standalone source CFB. Mirrors KiCad's DecodeIntLibStream."""
    if not raw:
        raise ValueError("empty IntLib stream")
    tag, body = raw[0], raw[1:]
    if tag == 0x02:
        return zlib.decompress(body)
    if tag == 0x00:
        return body
    raise ValueError(f"unknown IntLib stream compression tag {tag:#x}")


def extract_intlib(intlib_path, out_dir) -> tuple[Path, Path]:
    """Extract exactly one .SchLib + one .PcbLib from a single-part .IntLib into out_dir,
    returning their paths. Raises ValueError (with the Extract-in-Altium fallback) if the
    IntLib does not hold exactly one symbol lib and one footprint lib, so a placed part is
    never ambiguous or silently missing an asset."""
    intlib_path = Path(intlib_path)
    out_dir = Path(out_dir)
    with olefile.OleFileIO(str(intlib_path)) as ole:
        streams = ole.listdir(streams=True, storages=False)
        sch = sorted(s for s in streams if "/".join(s).lower().endswith(".schlib"))
        pcb = sorted(s for s in streams if "/".join(s).lower().endswith(".pcblib"))
        if len(sch) != 1 or len(pcb) != 1:
            raise ValueError(
                f"{intlib_path.name} is not a single-part IntLib "
                f"({len(sch)} symbol libraries, {len(pcb)} footprint libraries). {_EXTRACT_HINT}"
            )
        sch_bytes = _decode_stream(ole.openstream(sch[0]).read())
        pcb_bytes = _decode_stream(ole.openstream(pcb[0]).read())
    for label, data in (("symbol library", sch_bytes), ("footprint library", pcb_bytes)):
        if data[:8] != _CFB_MAGIC:
            raise ValueError(
                f"extracted {label} from {intlib_path.name} is not a valid library file. "
                f"{_EXTRACT_HINT}"
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = intlib_path.stem
    sch_out = out_dir / f"{stem}.SchLib"
    pcb_out = out_dir / f"{stem}.PcbLib"
    sch_out.write_bytes(sch_bytes)
    pcb_out.write_bytes(pcb_bytes)
    return sch_out, pcb_out


def normalize_altium_source(*sources, out_dir=None) -> tuple[Path, Path]:
    """Return a loose (schlib, pcblib) pair from EITHER a single .IntLib OR a .SchLib + .PcbLib
    pair (order-independent). For an .IntLib, `out_dir` is required (extraction target). Raises
    ValueError on any other combination, so the caller always gets exactly one of each."""
    paths = [Path(s) for s in sources]
    intlibs = [p for p in paths if p.suffix.lower() == ".intlib"]
    schlibs = [p for p in paths if p.suffix.lower() == ".schlib"]
    pcblibs = [p for p in paths if p.suffix.lower() == ".pcblib"]

    if len(intlibs) == 1 and not schlibs and not pcblibs:
        if out_dir is None:
            raise ValueError("out_dir is required to extract an .IntLib")
        return extract_intlib(intlibs[0], out_dir)
    if len(schlibs) == 1 and len(pcblibs) == 1 and not intlibs:
        return schlibs[0], pcblibs[0]
    raise ValueError(
        "provide either a single .IntLib or one .SchLib + one .PcbLib; got: "
        + (", ".join(p.name for p in paths) or "nothing")
    )
