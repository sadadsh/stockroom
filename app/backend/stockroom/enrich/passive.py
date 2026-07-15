"""The offline passive fast path: an MPN alone recovers a passive's specs + assets.

A resistor / capacitor / inductor MPN deterministically encodes its value,
tolerance, case size and (for many families) power rating, so a passive needs no
network to enrich: give the MPN and this module decodes the specs and resolves the
KiCad *stock* symbol / footprint / 3D model it should use. This is the owner's
headline "drop the MPN and you are done" path for passives (no asset files, no
typing, no APIs).

Two responsibilities, both pure and Qt-free:
  * parse_passive_mpn(mpn)  -> decode a known passive MPN into a PassiveSpec.
  * resolve_passive_assets  -> map (kind, case) to KiCad stock lib_ids, with an
                               offline presence check against the installed libs.
plus detect_passive() (auto-detect + override) so the UI can flag a part passive
from its category / refdes / MPN family without a full decode.

Value decoding is family-agnostic and standards-based (RKM / IEC 60062 letter
notation, EIA 3- and 4-digit codes); only the *shape* of each MPN (where the case,
tolerance and value sit) is per-family, so a new family is one row in FAMILIES.
Where a family's encoding is not confidently known a field is left empty rather
than guessed: an honest gap beats confident-wrong data (a wrong resistance or
package is worse than a blank one).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# EIA imperial case -> KiCad metric suffix (the stock Resistor_SMD / Capacitor_SMD /
# Inductor_SMD footprint naming, e.g. "R_0603_1608Metric"). Verified against the
# installed KiCad 10 footprint libraries.
_EIA_TO_METRIC: dict[str, str] = {
    "0075": "0200Metric",
    "0100": "0300Metric",
    "0201": "0603Metric",
    "0402": "1005Metric",
    "0603": "1608Metric",
    "0805": "2012Metric",
    "1008": "2520Metric",
    "1206": "3216Metric",
    "1210": "3225Metric",
    "1218": "3246Metric",
    "1806": "4516Metric",
    "1812": "4532Metric",
    "2010": "5025Metric",
    "2220": "5750Metric",
    "2512": "6332Metric",
    "2725": "6864Metric",
}

# EIA tolerance letters (IEC 60062) shared by resistors and capacitors.
_TOLERANCE: dict[str, str] = {
    "B": "0.1%",
    "C": "0.25%",
    "D": "0.5%",
    "F": "1%",
    "G": "2%",
    "J": "5%",
    "K": "10%",
    "M": "20%",
    "Z": "+80/-20%",
}

# The standard JEITA thick-film power rating by case for general-purpose chip
# resistors (the base RC / RMCF / CRCW series). Anti-surge / pulse-rated series
# differ, so a family opts in to this map only when its base series follows it.
_STD_POWER: dict[str, str] = {
    "0201": "0.05 W",
    "0402": "0.063 W",
    "0603": "0.1 W",
    "0805": "0.125 W",
    "1206": "0.25 W",
    "1210": "0.5 W",
    "2010": "0.75 W",
    "2512": "1 W",
}

_KIND_SYMBOL: dict[str, str] = {"resistor": "Device:R", "capacitor": "Device:C",
                                "inductor": "Device:L"}
_KIND_FP_LIB: dict[str, str] = {"resistor": "Resistor_SMD", "capacitor": "Capacitor_SMD",
                                "inductor": "Inductor_SMD"}
_KIND_FP_PREFIX: dict[str, str] = {"resistor": "R", "capacitor": "C", "inductor": "L"}


# --------------------------------------------------------------------------- #
# Value decoders (standards-based, family-agnostic).
# --------------------------------------------------------------------------- #
_RKM_R = re.compile(r"(\d*)([RKM])(\d*)")
_RKM_C = re.compile(r"(\d*)([RPN])(\d*)")


def decode_resistance(code: str) -> float | None:
    """Decode a resistance code to ohms. Accepts RKM / IEC 60062 letter notation
    ("4K70" = 4700, "1R00" = 1.0, "0R10" = 0.1, "100R" = 100, "1K1" = 1100), EIA
    4-digit (3 significant figures + decade, "1101" = 1100), and EIA 3-digit
    (2 significant figures + decade, "103" = 10000). Returns None if unrecognized."""
    code = (code or "").strip().upper()
    if not code:
        return None
    m = _RKM_R.fullmatch(code)
    if m:
        left, letter, right = m.groups()
        mult = {"R": 1.0, "K": 1e3, "M": 1e6}[letter]
        return float(f"{left or '0'}.{right or '0'}") * mult
    if code.isdigit():
        if len(code) == 4:
            return int(code[:3]) * (10 ** int(code[3]))
        if len(code) == 3:
            return int(code[:2]) * (10 ** int(code[2]))
        if len(code) <= 2:
            return float(code)
    return None


def decode_capacitance(code: str) -> float | None:
    """Decode a capacitance code to farads. Accepts the EIA 3-digit picofarad code
    ("104" = 100000 pF = 100 nF) and R/decimal picofarad notation ("4R7" = 4.7 pF).
    Returns None if unrecognized."""
    code = (code or "").strip().upper()
    if not code:
        return None
    m = re.fullmatch(r"(\d*)R(\d*)", code)
    if m:
        left, right = m.groups()
        return float(f"{left or '0'}.{right or '0'}") * 1e-12
    if code.isdigit():
        if len(code) == 3:
            return int(code[:2]) * (10 ** int(code[2])) * 1e-12
        if len(code) <= 2:
            return float(code) * 1e-12
    return None


def _fmt_num(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def _fmt_ohms(x: float) -> str:
    if x >= 1e6:
        return f"{_fmt_num(x / 1e6)} MOhm"
    if x >= 1e3:
        return f"{_fmt_num(x / 1e3)} kOhm"
    return f"{_fmt_num(x)} Ohm"


def _fmt_farads(x: float) -> str:
    if x >= 1e-6:
        return f"{_fmt_num(x / 1e-6)} µF"
    if x >= 1e-9:
        return f"{_fmt_num(x / 1e-9)} nF"
    return f"{_fmt_num(x / 1e-12)} pF"


# --------------------------------------------------------------------------- #
# The parsed passive spec.
# --------------------------------------------------------------------------- #
@dataclass
class PassiveSpec:
    kind: str                        # "resistor" | "capacitor" | "inductor"
    mpn: str
    manufacturer: str = ""
    family: str = ""
    value: str = ""                  # display string, e.g. "1.1 kOhm"
    value_ohms: float | None = None
    value_farads: float | None = None
    value_henries: float | None = None
    tolerance: str = ""
    package: str = ""                # EIA imperial case, e.g. "0603"
    power: str = ""
    voltage: str = ""
    dielectric: str = ""

    def to_specs(self) -> dict[str, str]:
        """Display-ready spec rows, Title Case keys (design contract), only the facts
        actually known. Feeds PartRecord.specs so a passive carries its key specs."""
        out: dict[str, str] = {}
        label = {"resistor": "Resistance", "capacitor": "Capacitance",
                 "inductor": "Inductance"}[self.kind]
        if self.value:
            out[label] = self.value
        if self.tolerance:
            out["Tolerance"] = self.tolerance
        if self.package:
            out["Package"] = self.package
        if self.power:
            out["Power"] = self.power
        if self.voltage:
            out["Voltage"] = self.voltage
        if self.dielectric:
            out["Dielectric"] = self.dielectric
        return out


# --------------------------------------------------------------------------- #
# Family table. Each row knows the MPN shape (a regex with named groups) and how
# to read the case size; value/tolerance decode is shared. Adding a family is one
# row here plus a size map if the family codes its case.
# --------------------------------------------------------------------------- #
@dataclass
class _Family:
    name: str
    manufacturer: str
    kind: str
    pattern: re.Pattern
    # None => the `size` group already holds a literal EIA case (e.g. "0603");
    # a dict => the `size` group is a code to look up (Panasonic ERJ etc.).
    size_map: dict[str, str] | None = None
    std_power: bool = False


# Resistors -------------------------------------------------------------------
# Yageo RC: RC<case><tol><TCR>-<taping><value><suffix>. Tolerance sits right after
# the case; the value trails after the "-07" taping code.
_RC_YAGEO = _Family(
    "RC", "Yageo", "resistor",
    re.compile(r"^RC(?P<size>\d{4})(?P<tol>[BDFGJ])[A-Z]?-\d{2}"
               r"(?P<value>\d+[RKM]\d*|[RKM]\d+|\d{3,4})[A-Z]*$"),
    std_power=True,
)
# Stackpole RMCF/RMCP: RMC[FP]<case><tol><packaging><value>.
_RMCF_STACKPOLE = _Family(
    "RMCF", "Stackpole", "resistor",
    re.compile(r"^RMC[FP](?P<size>\d{4})(?P<tol>[BDFGJ])[A-Z]?"
               r"(?P<value>\d+[RKM]\d*|[RKM]\d+|\d{3,4})[A-Z]*$"),
    std_power=True,
)
# Vishay CRCW: CRCW<case><value><tol><TCR/packaging>. Tolerance sits AFTER the value.
_CRCW_VISHAY = _Family(
    "CRCW", "Vishay", "resistor",
    re.compile(r"^CRCW(?P<size>\d{4})(?P<value>\d+[RKM]\d*|[RKM]\d+|\d{4})"
               r"(?P<tol>[BDFGJ])[A-Z]*$"),
    std_power=True,
)
# Panasonic ERJ: ERJ-<case code><type?><tol><value><suffix>. Case is CODED (ERJ-P03
# is the 0603 case, verified against the owner's ERJ-P03F1101V record). Only codes
# grounded in real parts are mapped; unknown codes leave the package blank.
_ERJ_PANASONIC = _Family(
    "ERJ", "Panasonic", "resistor",
    re.compile(r"^ERJ-?(?P<size>P?[AB]?\d+)[A-Z]*?(?P<tol>[BCDFGJ])"
               r"(?P<value>\d+[RKM]\d*|[RKM]\d+|\d{3,4})[A-Z]?$"),
    size_map={
        "P02": "0402", "P03": "0603", "P06": "0805", "P08": "1206",
        "PA2": "0402", "PA3": "0603", "PB3": "0603",
        "2": "0402", "3": "0603", "6": "0805", "8": "1206", "14": "1210",
    },
)

# Capacitors ------------------------------------------------------------------
# Samsung CL: CL<case><dielectric><value><tol>...  Case is coded.
_CL_SAMSUNG = _Family(
    "CL", "Samsung", "capacitor",
    re.compile(r"^CL(?P<size>\d{2})[A-Z](?P<value>\d{3})(?P<tol>[BCDFGJKMZ])[A-Z0-9]*$"),
    size_map={"03": "0201", "05": "0402", "10": "0603", "21": "0805",
              "31": "1206", "32": "1210", "43": "1812", "55": "2220"},
)

# Inductors -------------------------------------------------------------------
# Murata LQ-series (LQW/LQG/LQM/LQH/LQP). Only the KIND is decoded offline: the
# inductance encoding differs across these families (the RF nano-henry "N"-decimal
# vs the wire-wound micro-henry decade code, with a type-code letter in between that
# collides with the value), and the Murata case code is per-series and not a clean
# EIA case. Both would be confidently-wrong from a single regex, so value and package
# are left for jlcsearch to fill (blank beats wrong). Kind detection is reliable.
_LQ_MURATA = _Family(
    "LQ", "Murata", "inductor",
    re.compile(r"^LQ[WGMHP][0-9A-Z]{2}[A-Z0-9]+$"),
    size_map=None,
)

FAMILIES: tuple[_Family, ...] = (
    _RC_YAGEO, _RMCF_STACKPOLE, _CRCW_VISHAY, _ERJ_PANASONIC, _CL_SAMSUNG, _LQ_MURATA,
)

_DISTRIBUTOR_PREFIX = re.compile(r"^\d{1,4}-")


def _clean_mpn(mpn: str) -> str:
    return _DISTRIBUTOR_PREFIX.sub("", (mpn or "").strip().upper())


def parse_passive_mpn(mpn: str) -> PassiveSpec | None:
    """Decode a known passive MPN into a PassiveSpec, or None if the MPN is not a
    recognized passive family. Strips a leading distributor prefix (Mouser "667-")
    before matching. Never raises: an unrecognized or malformed value simply leaves
    that field empty."""
    cleaned = _clean_mpn(mpn)
    if not cleaned:
        return None
    for fam in FAMILIES:
        m = fam.pattern.match(cleaned)
        if not m:
            continue
        groups = m.groupdict()
        spec = PassiveSpec(kind=fam.kind, mpn=cleaned, manufacturer=fam.manufacturer,
                           family=fam.name)
        # Case size: literal EIA token, or a family code looked up in size_map.
        size_raw = groups.get("size", "")
        if fam.size_map is not None:
            spec.package = fam.size_map.get(size_raw, "")
        elif size_raw in _EIA_TO_METRIC:
            spec.package = size_raw
        # Tolerance.
        tol = groups.get("tol", "")
        if tol:
            spec.tolerance = _TOLERANCE.get(tol, "")
        # Value.
        value_code = groups.get("value", "")
        if fam.kind == "resistor":
            ohms = decode_resistance(value_code)
            if ohms is not None:
                spec.value_ohms = ohms
                spec.value = _fmt_ohms(ohms)
            if spec.package and fam.std_power:
                spec.power = _STD_POWER.get(spec.package, "")
            elif fam.name == "ERJ" and size_raw == "P03":
                spec.power = "0.2 W"  # ERJ-P03 anti-surge 0603 (grounded in the owner's part)
        elif fam.kind == "capacitor":
            farads = decode_capacitance(value_code)
            if farads is not None:
                spec.value_farads = farads
                spec.value = _fmt_farads(farads)
        # Inductors: kind only (see _LQ_MURATA). No offline value/package decode.
        return spec
    return None


# --------------------------------------------------------------------------- #
# Passive detection (auto-detect + override), independent of a full MPN decode.
# --------------------------------------------------------------------------- #
_CATEGORY_KIND: dict[str, str] = {
    "resistors": "resistor", "resistor": "resistor",
    "capacitors": "capacitor", "capacitor": "capacitor",
    "inductors": "inductor", "inductor": "inductor",
    "ferrites": "ferrite", "ferrite beads": "ferrite",
}
_REFDES_KIND: dict[str, str] = {"R": "resistor", "C": "capacitor", "L": "inductor",
                                "FB": "ferrite"}
_KINDS = frozenset({"resistor", "capacitor", "inductor", "ferrite"})


def detect_passive(mpn: str = "", category: str = "", refdes: str = "",
                   override: str | None = None) -> str | None:
    """Best-effort passive classification. `override` wins absolutely: a kind string
    forces it, "none" clears it. Otherwise the first passive signal wins, in order
    category -> refdes -> MPN family; None if nothing indicates a passive."""
    if override:
        ov = override.strip().lower()
        if ov in _KINDS:
            return ov
        if ov in ("none", "active", "off", "false"):
            return None
    cat = (category or "").strip().lower()
    if cat in _CATEGORY_KIND:
        return _CATEGORY_KIND[cat]
    ref = (refdes or "").strip().upper()
    mref = re.match(r"^([A-Z]{1,2})\d", ref)
    if mref and mref.group(1) in _REFDES_KIND:
        return _REFDES_KIND[mref.group(1)]
    spec = parse_passive_mpn(mpn)
    if spec is not None:
        return spec.kind
    return None


# --------------------------------------------------------------------------- #
# KiCad stock-asset resolution (offline).
# --------------------------------------------------------------------------- #
@dataclass
class ResolvedPassive:
    kind: str
    package: str
    symbol: str          # stock symbol lib_id, e.g. "Device:R"
    footprint: str       # stock footprint lib_id, e.g. "Resistor_SMD:R_0603_1608Metric"
    model_name: str      # e.g. "R_0603_1608Metric"
    model_3d: str        # relative stock 3D path, e.g. "Resistor_SMD.3dshapes/R_0603_1608Metric.wrl"
    present: bool = False  # a matching stock .kicad_mod was found on disk (advisory)


def find_kicad_footprints_root() -> Path | None:
    """The installed KiCad stock footprints directory (holding the *.pretty libs),
    newest install first, or None if KiCad is not installed. Mirrors the kicad-cli
    discovery so the presence check works without KiCad on PATH."""
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        for env in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            root = Path(base) / "KiCad"
            try:
                if not root.is_dir():
                    continue
                vers = sorted((d for d in root.iterdir() if d.is_dir() and d.name[:1].isdigit()),
                              key=lambda d: tuple(int(p) if p.isdigit() else -1
                                                  for p in d.name.split(".")), reverse=True)
            except OSError:
                continue
            for ver in vers:
                candidates.append(ver / "share" / "kicad" / "footprints")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"))
    else:
        candidates += [Path("/usr/share/kicad/footprints"),
                       Path("/usr/local/share/kicad/footprints")]
    for cand in candidates:
        try:
            if cand.is_dir():
                return cand
        except OSError:
            continue
    return None


def resolve_passive_assets(kind: str, package: str,
                           footprints_root: Path | None = None) -> ResolvedPassive | None:
    """Resolve (kind, EIA case) to the KiCad *stock* symbol/footprint/3D lib_ids.

    The lib_ids are always canonical and correct (never fabricated, never blank);
    `present` is an advisory flag set only when a matching stock .kicad_mod is found
    under `footprints_root` (or the installed KiCad libs when None). Returns None for
    an unknown kind or an EIA case with no stock footprint mapping."""
    kind = (kind or "").strip().lower()
    package = (package or "").strip()
    if kind not in _KIND_SYMBOL or package not in _EIA_TO_METRIC:
        return None
    metric = _EIA_TO_METRIC[package]
    prefix = _KIND_FP_PREFIX[kind]
    fp_lib = _KIND_FP_LIB[kind]
    name = f"{prefix}_{package}_{metric}"
    resolved = ResolvedPassive(
        kind=kind,
        package=package,
        symbol=_KIND_SYMBOL[kind],
        footprint=f"{fp_lib}:{name}",
        model_name=name,
        model_3d=f"{fp_lib}.3dshapes/{name}.wrl",
    )
    root = footprints_root if footprints_root is not None else find_kicad_footprints_root()
    if root is not None:
        try:
            resolved.present = (Path(root) / f"{fp_lib}.pretty" / f"{name}.kicad_mod").is_file()
        except OSError:
            resolved.present = False
    return resolved
