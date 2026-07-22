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
    if tools <= {"kicad", "shared"}:
        return "kicad"
    if tools == {"altium"}:
        return "altium"
    return "mixed"


def classify_asset(path: Path) -> ClassifiedAsset:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".zip":
        return _classify_zip(p)
    reqs = _reqs_for_suffix(suffix)
    tool, kind = _KIND_FOR_SUFFIX.get(suffix, ("unknown", "unknown"))
    return ClassifiedAsset(tool=tool, kind=kind, requirements=reqs)


def _classify_zip(path: Path) -> ClassifiedAsset:
    reqs: set[Requirement] = set()
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                reqs |= _reqs_for_suffix(Path(name).suffix)
    except (zipfile.BadZipFile, OSError):
        return ClassifiedAsset(tool="unknown", kind="zip", requirements=frozenset())
    return ClassifiedAsset(tool=_tool_for_reqs(reqs), kind="zip", requirements=frozenset(reqs))
