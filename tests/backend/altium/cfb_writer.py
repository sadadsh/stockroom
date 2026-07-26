"""A minimal OLE2/CFB writer for TESTS ONLY: one root storage holding one stream.

olefile (the production reader) is read-only, and a real .SchDoc is an OLE compound
file, so end-to-end reader tests need a way to author one. This writes the smallest
spec-compliant layout: 512-byte sectors, one FAT sector, one directory sector, and
the stream stored in REGULAR sectors. The stream content is zero-padded to 4096 bytes
(the mini-stream cutoff) so it never needs a mini-FAT; the SchDoc record parser stops
cleanly at a zero length word, so the padding is invisible to it.
"""

from __future__ import annotations

import struct

SECTOR = 512
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


def _dir_entry(name: str, entry_type: int, *, child=NOSTREAM, start=ENDOFCHAIN, size=0) -> bytes:
    raw_name = name.encode("utf-16-le") + b"\x00\x00"
    entry = bytearray(128)
    entry[0 : len(raw_name)] = raw_name
    struct.pack_into("<H", entry, 64, len(raw_name))  # name length incl. terminator
    entry[66] = entry_type  # 5 = root storage, 2 = stream, 0 = unused
    entry[67] = 1  # color: black
    struct.pack_into("<III", entry, 68, NOSTREAM, NOSTREAM, child)  # left/right/child
    struct.pack_into("<I", entry, 116, start)
    struct.pack_into("<Q", entry, 120, size)
    return bytes(entry)


def write_cfb(path, stream_name: str, content: bytes) -> None:
    """Write `content` as the single stream `stream_name` of a new compound file."""
    data = content + b"\x00" * max(0, 4096 - len(content))
    n_stream_sectors = (len(data) + SECTOR - 1) // SECTOR
    # sector 0 = FAT, sector 1 = directory, sectors 2.. = the stream
    fat = [FATSECT, ENDOFCHAIN]
    for i in range(n_stream_sectors):
        fat.append(2 + i + 1 if i + 1 < n_stream_sectors else ENDOFCHAIN)
    fat += [FREESECT] * (SECTOR // 4 - len(fat))

    header = bytearray(SECTOR)
    header[0:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<H", header, 24, 0x003E)  # minor version
    struct.pack_into("<H", header, 26, 0x0003)  # major version 3 (512-byte sectors)
    struct.pack_into("<H", header, 28, 0xFFFE)  # little-endian marker
    struct.pack_into("<H", header, 30, 9)  # sector shift: 512
    struct.pack_into("<H", header, 32, 6)  # mini sector shift: 64
    struct.pack_into("<I", header, 44, 1)  # number of FAT sectors
    struct.pack_into("<I", header, 48, 1)  # first directory sector
    struct.pack_into("<I", header, 56, 4096)  # mini stream cutoff
    struct.pack_into("<I", header, 60, ENDOFCHAIN)  # first mini-FAT sector (none)
    struct.pack_into("<I", header, 64, 0)  # number of mini-FAT sectors
    struct.pack_into("<I", header, 68, ENDOFCHAIN)  # first DIFAT sector (none)
    struct.pack_into("<I", header, 72, 0)  # number of DIFAT sectors
    difat = [0] + [FREESECT] * 108  # FAT lives in sector 0
    struct.pack_into("<109I", header, 76, *difat)

    directory = (
        _dir_entry("Root Entry", 5, child=1)
        + _dir_entry(stream_name, 2, start=2, size=len(data))
        + _dir_entry("", 0)
        + _dir_entry("", 0)
    )

    blob = bytes(header) + struct.pack(f"<{len(fat)}I", *fat) + directory + data
    pad = (-len(blob)) % SECTOR
    with open(path, "wb") as fh:
        fh.write(blob + b"\x00" * pad)
