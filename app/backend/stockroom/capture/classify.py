"""Classify a captured file (or a vendor zip's contents) into the capture
Requirements it satisfies. Pure (no pywebview). Extension semantics are kept
consistent with ingest/fingerprint.py (.kicad_sym/.lib symbol, .step/.stp/.wrl
model) and altium/extract.py (.schlib/.pcblib/.intlib), plus .kicad_mod
footprint and .zip.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from stockroom.capture.requirements import Requirement

_SUFFIX_REQ: dict[str, Requirement] = {
    ".kicad_sym": Requirement.KICAD_SYMBOL,
    ".lib": Requirement.KICAD_SYMBOL,
    ".kicad_mod": Requirement.KICAD_FOOTPRINT,
    ".step": Requirement.KICAD_MODEL,
    ".stp": Requirement.KICAD_MODEL,
    ".wrl": Requirement.KICAD_MODEL,
    ".schlib": Requirement.ALTIUM_SYMBOL,
    ".pcblib": Requirement.ALTIUM_FOOTPRINT,
}
# A compiled Altium IntLib carries both symbol and footprint.
_INTLIB_REQS = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})

_TOOL_FOR_REQ = {
    Requirement.KICAD_SYMBOL: "kicad",
    Requirement.KICAD_FOOTPRINT: "kicad",
    Requirement.KICAD_MODEL: "shared",
    Requirement.ALTIUM_SYMBOL: "altium",
    Requirement.ALTIUM_FOOTPRINT: "altium",
}
_KIND_FOR_SUFFIX = {
    ".kicad_sym": ("kicad", "symbol"),
    ".lib": ("kicad", "symbol"),
    ".kicad_mod": ("kicad", "footprint"),
    ".step": ("shared", "model"),
    ".stp": ("shared", "model"),
    ".wrl": ("shared", "model"),
    ".schlib": ("altium", "symbol"),
    ".pcblib": ("altium", "footprint"),
    ".intlib": ("altium", "symbol"),
}


@dataclass
class ClassifiedAsset:
    tool: str  # "kicad" | "altium" | "shared" | "mixed" | "unknown"
    kind: str  # "symbol" | "footprint" | "model" | "zip" | "unknown"
    requirements: frozenset[Requirement]


def _reqs_for_suffix(suffix: str) -> frozenset[Requirement]:
    s = suffix.lower()
    if s == ".intlib":
        return _INTLIB_REQS
    req = _SUFFIX_REQ.get(s)
    return frozenset({req}) if req is not None else frozenset()


def _tool_for_reqs(reqs: set[Requirement]) -> str:
    if not reqs:
        return "unknown"
    tools = {_TOOL_FOR_REQ[r] for r in reqs}
    # A lone 3D model is "shared" whether loose or zipped (consistency with the loose path).
    if tools == {"shared"}:
        return "shared"
    if tools <= {"kicad", "shared"}:
        return "kicad"
    if tools == {"altium"}:
        return "altium"
    return "mixed"


def _is_zip(path: Path) -> bool:
    """True if the file is a zip archive by CONTENT (magic bytes), regardless of its name."""
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def classify_asset(path: Path) -> ClassifiedAsset:
    p = Path(path)
    suffix = p.suffix.lower()
    reqs = _reqs_for_suffix(suffix)
    # A vendor CAD download can arrive WITHOUT a useful suffix: WebView2 saves a download with no
    # Content-Disposition filename as a GUID ".tmp" (live-observed 2026-07-23 for DigiKey / Ultra
    # Librarian bundles). If the suffix carries no known requirement and is not an EDA extension, but
    # the file is a zip by content, classify it by its members - never drop a valid bundle over its
    # name. A recognized suffix (.kicad_sym, .schlib, ...) still wins so a stray zip-looking asset is
    # not mis-scanned.
    if suffix == ".zip" or (not reqs and suffix not in _KIND_FOR_SUFFIX and _is_zip(p)):
        return _classify_zip(p)
    if not reqs and suffix not in _KIND_FOR_SUFFIX:
        # A loose Altium library saved under a GUID ".tmp" name (WebView2 with no
        # Content-Disposition filename) is an OLE compound file: classify by CONTENT,
        # never drop a valid download over its name (mirrors the zip-by-content rule).
        ole = _classify_ole(p)
        if ole is not None:
            return ole
    tool, kind = _KIND_FOR_SUFFIX.get(suffix, ("unknown", "unknown"))
    return ClassifiedAsset(tool=tool, kind=kind, requirements=reqs)


_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _classify_ole(path: Path) -> ClassifiedAsset | None:
    """Classify an OLE compound file by its Altium streams: a .SchLib carries symbol
    names in FileHeader (LibRef records), a .PcbLib carries the Library/Data name
    records. None when the file is not OLE or matches neither shape."""
    try:
        with open(path, "rb") as fh:
            if fh.read(8) != _OLE_MAGIC:
                return None
    except OSError:
        return None
    try:
        import olefile

        # Discriminate by the AUTHORITATIVE streams, not the permissive name fallbacks
        # (read_footprint_names' storage-walk would match a SchLib's component storages
        # too): Library/Data is the .PcbLib name table; a FileHeader with LibRef records
        # is the .SchLib component list.
        with olefile.OleFileIO(str(path)) as ole:
            if ole.exists(["Library", "Data"]):
                return ClassifiedAsset(
                    tool="altium", kind="footprint",
                    requirements=frozenset({Requirement.ALTIUM_FOOTPRINT}),
                )
            if ole.exists(["FileHeader"]):
                header = ole.openstream(["FileHeader"]).read()
                if b"LibRef" in header or b"LIBREF" in header:
                    return ClassifiedAsset(
                        tool="altium", kind="symbol",
                        requirements=frozenset({Requirement.ALTIUM_SYMBOL}),
                    )
    except Exception:  # noqa: BLE001 - an unreadable OLE is simply not classifiable
        return None
    return None


def _classify_zip(path: Path) -> ClassifiedAsset:
    reqs: set[Requirement] = set()
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                reqs |= _reqs_for_suffix(Path(name).suffix)
                # a zip nested INSIDE the bundle (one level) counts by its members too -
                # vendors wrap the Altium set that way, and a valid download must never
                # classify as unknown over its packaging
                if Path(name).suffix.lower() == ".zip":
                    try:
                        import io

                        with zf.open(name) as inner_fh:
                            with zipfile.ZipFile(io.BytesIO(inner_fh.read())) as inner:
                                for iname in inner.namelist():
                                    reqs |= _reqs_for_suffix(Path(iname).suffix)
                    except (zipfile.BadZipFile, OSError, KeyError):
                        continue
    except (zipfile.BadZipFile, OSError):
        return ClassifiedAsset(tool="unknown", kind="zip", requirements=frozenset())
    return ClassifiedAsset(tool=_tool_for_reqs(reqs), kind="zip", requirements=frozenset(reqs))
