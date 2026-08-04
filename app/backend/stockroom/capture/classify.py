"""Classify a captured file (or a vendor zip's contents) into the capture
Requirements it satisfies, and into the three groups the intake surface has to
name out loud: importable CAD, supporting material that is never auto-imported,
and prohibited executable/script content.

Pure (no pywebview). Extension semantics are kept consistent with
ingest/fingerprint.py (.kicad_sym/.lib symbol, .step/.stp/.wrl model) and
altium/extract.py (.schlib/.pcblib/.intlib), plus .kicad_mod footprint,
.pretty footprint directories and .zip.

The prohibited set is imported from ingest/sandbox.py rather than restated here:
what this module names for a person and what the sandbox refuses to extract must
be the same list, or one of them is lying.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from stockroom.capture.requirements import Requirement
from stockroom.ingest.sandbox import (
    MAX_COMPRESSION_RATIO,
    MAX_MEMBER_EXPANDED_BYTES,
    MAX_MEMBERS,
    MAX_NESTED_ARCHIVE_DEPTH,
    PROHIBITED_SUFFIXES,
    prohibited_reason,
)

_SUFFIX_REQ: dict[str, Requirement] = {
    ".kicad_sym": Requirement.KICAD_SYMBOL,
    ".lib": Requirement.KICAD_SYMBOL,
    ".kicad_mod": Requirement.KICAD_FOOTPRINT,
    # A `.pretty` is KiCad's footprint LIBRARY directory. Vendors ship it as a directory
    # inside the bundle, so its own entry names a footprint role even before its members
    # are read.
    ".pretty": Requirement.KICAD_FOOTPRINT,
    ".step": Requirement.KICAD_MODEL,
    ".stp": Requirement.KICAD_MODEL,
    ".wrl": Requirement.KICAD_MODEL,
    ".schlib": Requirement.ALTIUM_SYMBOL,
    ".pcblib": Requirement.ALTIUM_FOOTPRINT,
}
# A compiled Altium IntLib carries both symbol and footprint.
_INTLIB_REQS = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})
# A P-CAD ASCII library (.LIA) does too, and Altium Designer imports it directly. MEASURED
# 2026-07-27 on Ultra Librarian's PCAD v15 export for a real part: `ACCEL_ASCII` header, exactly
# one `symbolDef` (schematic symbol), one `patternDef` (PCB footprint) and one `compDef`, with 69
# pads and 212 pin references. It is delivered nested under `AltiumV15/`, never loose.
#
# This remains a supported legacy fallback. Ultra Librarian's current primary Altium export is
# native .SchLib/.PcbLib; its older "Altium Designer (script based)" row ships a Delphi script and
# no libraries, while PCAD v15 supplies this importable .LIA shape.
#
# A `.lia` is importable only through the proven normalization in `altium/converter.py`
# (`convert_pcad_ascii`, fed by `stockroom.pcad`). Nothing imports the raw file.
_LIA_REQS = _INTLIB_REQS
LIA_IMPORT_ROUTE = "stockroom.altium.converter.convert_pcad_ascii"

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
    ".pretty": ("kicad", "footprint"),
    ".step": ("shared", "model"),
    ".stp": ("shared", "model"),
    ".wrl": ("shared", "model"),
    ".schlib": ("altium", "symbol"),
    ".pcblib": ("altium", "footprint"),
    ".intlib": ("altium", "symbol"),
    ".lia": ("altium", "symbol"),
}

# Group 2: material a person genuinely wants kept beside a part -- datasheets, provider
# import instructions, licences, preview images -- and which is never auto-imported into a
# library. Recognized so it can be RETAINED and labelled, not silently discarded as unknown.
_SUPPORTING_SUFFIXES = frozenset(
    {
        ".pdf", ".txt", ".md", ".rst", ".htm", ".html", ".csv", ".rtf", ".doc", ".docx",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tif", ".tiff",
        ".json", ".xml", ".yml", ".yaml", ".ini", ".dcm", ".epw", ".nfo",
    }
)
# Provider bundles ship these with no extension at all.
_SUPPORTING_STEMS = frozenset(
    {"readme", "read me", "license", "licence", "notice", "copying", "changelog", "instructions"}
)


class AssetGroup(str, Enum):
    """The three groups intake must name explicitly, plus the honest fourth.

    ``IMPORTABLE_CAD`` is the only group anything is ever imported from.
    ``SUPPORTING`` is retained beside the part and never auto-imported.
    ``PROHIBITED`` is executable, script or shortcut content and is refused.
    ``UNKNOWN`` is a file nothing here recognizes -- which is not a verdict of safe.
    """

    IMPORTABLE_CAD = "importable_cad"
    SUPPORTING = "supporting"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


@dataclass
class ClassifiedAsset:
    tool: str  # "kicad" | "altium" | "shared" | "mixed" | "unknown"
    kind: str  # "symbol" | "footprint" | "model" | "zip" | "unknown"
    requirements: frozenset[Requirement]
    group: AssetGroup = AssetGroup.UNKNOWN
    # Member names (or this file's own name) that carry executable/script content.
    prohibited_members: tuple[str, ...] = field(default_factory=tuple)


def _reqs_for_suffix(suffix: str) -> frozenset[Requirement]:
    s = suffix.lower()
    if s == ".intlib":
        return _INTLIB_REQS
    if s == ".lia":
        return _LIA_REQS
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


def _is_supporting(name: str) -> bool:
    pure = Path(name)
    return pure.suffix.lower() in _SUPPORTING_SUFFIXES or pure.stem.lower() in _SUPPORTING_STEMS


def _prohibited_by_name(name: str) -> bool:
    return Path(name).suffix.lower() in PROHIBITED_SUFFIXES


def _prohibited_by_content(path: Path) -> bool:
    """True when the leading bytes are executable/script/shortcut content.

    A path that cannot be read is not a verdict: classification of a bare NAME (the
    common case for a planned download) must not depend on the file existing.
    """
    try:
        with open(path, "rb") as handle:
            return bool(prohibited_reason(handle.read(8)))
    except OSError:
        return False


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
    # Executable/script content is refused by NAME and by leading bytes, before anything
    # else is attempted: a `.step` that is really a PE is a content/extension mismatch that
    # cannot be safely identified, and the honest answer is prohibited, not "model".
    if _prohibited_by_name(p.name) or _prohibited_by_content(p):
        return ClassifiedAsset(
            tool="unknown",
            kind="unknown",
            requirements=frozenset(),
            group=AssetGroup.PROHIBITED,
            prohibited_members=(p.name,),
        )
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
    if reqs:
        group = AssetGroup.IMPORTABLE_CAD
    elif _is_supporting(p.name):
        group = AssetGroup.SUPPORTING
    else:
        group = AssetGroup.UNKNOWN
    return ClassifiedAsset(tool=tool, kind=kind, requirements=reqs, group=group)


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
                    group=AssetGroup.IMPORTABLE_CAD,
                )
            if ole.exists(["FileHeader"]):
                header = ole.openstream(["FileHeader"]).read()
                if b"LibRef" in header or b"LIBREF" in header:
                    return ClassifiedAsset(
                        tool="altium", kind="symbol",
                        requirements=frozenset({Requirement.ALTIUM_SYMBOL}),
                        group=AssetGroup.IMPORTABLE_CAD,
                    )
    except Exception:  # noqa: BLE001 - an unreadable OLE is simply not classifiable
        return None
    return None


def _read_nested_archive(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes | None:
    """The inner archive's bytes, or None when the shared bounds refuse it.

    The former implementation called `inner_fh.read()` with no argument, which hands a
    hostile bundle the whole expanded member. The declared size, the compression ratio
    and the actual read are all bounded by the same constants the sandbox extracts with.
    """
    if info.file_size > MAX_MEMBER_EXPANDED_BYTES:
        return None
    if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        return None
    with zf.open(info) as inner_fh:
        payload = inner_fh.read(MAX_MEMBER_EXPANDED_BYTES + 1)
    if len(payload) > MAX_MEMBER_EXPANDED_BYTES:
        return None
    return payload


def _classify_zip(path: Path, depth: int = 0) -> ClassifiedAsset:
    reqs: set[Requirement] = set()
    prohibited: list[str] = []
    supporting = False
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist()[:MAX_MEMBERS]:
                name = info.filename
                reqs |= _reqs_for_suffix(Path(name).suffix)
                if _prohibited_by_name(name):
                    prohibited.append(name)
                elif _is_supporting(name):
                    supporting = True
                # a zip nested INSIDE the bundle counts by its members too - vendors wrap
                # the Altium set that way, and a valid download must never classify as
                # unknown over its packaging. The depth is the shared nesting bound, which
                # is 1: the one level that has ever been observed in a real download.
                if Path(name).suffix.lower() == ".zip" and depth < MAX_NESTED_ARCHIVE_DEPTH:
                    try:
                        payload = _read_nested_archive(zf, info)
                        if payload is None:
                            continue
                        with zipfile.ZipFile(io.BytesIO(payload)) as inner:
                            for iinfo in inner.infolist()[:MAX_MEMBERS]:
                                iname = iinfo.filename
                                reqs |= _reqs_for_suffix(Path(iname).suffix)
                                if _prohibited_by_name(iname):
                                    prohibited.append(f"{name}!{iname}")
                                elif _is_supporting(iname):
                                    supporting = True
                    except (zipfile.BadZipFile, OSError, KeyError):
                        # a corrupt inner archive is not a corrupt bundle
                        continue
    except (zipfile.BadZipFile, OSError):
        return ClassifiedAsset(
            tool="unknown", kind="zip", requirements=frozenset(), group=AssetGroup.UNKNOWN
        )
    if prohibited:
        group = AssetGroup.PROHIBITED
    elif reqs:
        group = AssetGroup.IMPORTABLE_CAD
    elif supporting:
        group = AssetGroup.SUPPORTING
    else:
        group = AssetGroup.UNKNOWN
    return ClassifiedAsset(
        tool=_tool_for_reqs(reqs),
        kind="zip",
        requirements=frozenset(reqs),
        group=group,
        prohibited_members=tuple(prohibited),
    )


__all__ = [
    "AssetGroup",
    "ClassifiedAsset",
    "LIA_IMPORT_ROUTE",
    "classify_asset",
]
