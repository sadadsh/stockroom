"""Read component/footprint entry NAMES from Altium .SchLib/.PcbLib (OLE2 compound files),
read-only via olefile. Each component is a top-level storage holding a 'Data' stream; the
storage name is the entry name (the value Altium's [Library Ref]/[Footprint Ref] resolves).
We never open or write the graphics.

A .PcbLib also carries metadata storages (FileVersionInfo, Library) that happen to hold a
'Data' stream, so a naive walk returns them as false-positive footprints; the metadata
blocklist below excludes them. Verified against real vendor libraries."""
from __future__ import annotations

from pathlib import Path

import olefile

# Top-level storages/streams that carry a 'Data' child but are NOT components. Lower-cased.
_META_ENTRIES = frozenset({
    "fileheader", "fileversioninfo", "library", "storage", "sectionkeys",
    "header", "data", "componentparamstoc", "models", "textures", "additional",
})


def _component_storages(path) -> list[str]:
    """Top-level storage names in an Altium OLE lib that hold a component (a 'Data' child
    stream), minus the known metadata entries. In a .SchLib these are symbol names; in a
    .PcbLib, footprint names."""
    with olefile.OleFileIO(str(Path(path))) as ole:
        entries = ole.listdir(streams=True, storages=True)
    tops = {e[0] for e in entries}
    return sorted(
        name for name in tops
        if [name, "Data"] in entries and name.lower() not in _META_ENTRIES
    )


def read_symbol_names(path) -> list[str]:
    return _component_storages(path)


def read_footprint_names(path) -> list[str]:
    return _component_storages(path)
