"""StmIndex: the derived, never-committed SQLite index over the CubeMX MCU XML set.

Mirrors store/index.py's LibraryIndex shape exactly: a stdlib-only, Qt-free build
of a flat, query-fast normalized store from a text source of truth (the CubeMX XML
tree, not the JSON parts library, but the same "derived cache, rebuild on demand"
idea). StmIndex.build parses every device XML into the Phase 1 schema; StmIndex.load
opens a file-backed index and refuses it (returns None) when its stamped
classifier/geometry revision does not match this module's build code, or the file
is missing/corrupt - a stale or code-incompatible index is never silently trusted.

Only the six spine tables (source_artifact, mcu, mcu_package_pin, pin_function,
pin_role, meta) are populated end to end in this module's first task; mcu_spec /
mcu_peripheral extraction and package_geometry population are added on top of this
same build loop by later tasks/plans - see stm/geometry.py (PACKAGE_GEOMETRY) and
this phase's Plan 02 (self-audit gate + check_availability guard).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stockroom.stm import geometry as geometry_mod
from stockroom.stm import source as source_mod

logger = logging.getLogger(__name__)

# Classification revision: bump whenever canonical()/electrical_class()/roles() or
# the schema's classification-derived columns change meaning, so a database built
# by older classification code is never silently trusted (StmIndex.load() checks
# this against the stamped meta.classifier_rev).
#   rev 1 (2026-07-23): initial port of canonical/electrical_class/_is_analog/roles
#     from legacy/tools/stm32_db.py, unchanged; mcu_package_pin keyed by
#     (mcu_id, physical_pin_number, raw_pin_name) so same-position PINREMAP
#     identities are never collapsed.
CLASSIFIER_REV = 1

# Alternate-function (AF0-15 mux) revision, stamped into meta.af_schema_rev the
# same way CLASSIFIER_REV/GEOMETRY_REV are - StmIndex.load() refuses a file
# whose stamped af_schema_rev does not match this constant (Phase 2, DATA-08).
#   rev 1 (2026-07-23): initial AF0-15 mux join (parse_gpio_ip_xml), keyed by
#     raw_pin_name (never canonical_pin_name - PINREMAP/_C-suffix collisions
#     collapse under the regex-derived canonical name). F1's classic
#     __HAL_AFIO_REMAP_* legacy shape is recognized and skipped (zero rows,
#     no gate trip); the 100%-join-resolution gate binds to FILE resolution
#     only (a device's declared GPIO IP version resolving to an actual
#     GPIO-<version>_Modes.xml on disk), never to content shape.
AF_SCHEMA_REV = 1

_NS = re.compile(r"\{[^}]*\}")


def _tag(el: ET.Element) -> str:
    return _NS.sub("", el.tag)


# ─────────────────────────────────────────────────────────────────────────────
# Parse — one CubeMX MCU XML -> structured data
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Signal:
    name: str
    io_modes: str = ""


@dataclass
class Pin:
    position: str  # raw CubeMX Position string: "1".."N" (perimeter) or "A1".."AB12" (BGA)
    name: str  # raw CubeMX pin name, e.g. "PC13-ANTI_TAMP", "VBAT"
    type: str  # Power / I/O / MonoIO / Reset / Boot / NC
    signals: list[Signal] = field(default_factory=list)

    @property
    def signal_names(self) -> set[str]:
        return {s.name for s in self.signals}


@dataclass
class Peripheral:
    name: str  # <IP Name="..."> e.g. USART, SPI, TIM, ADC, USB, CAN
    instance_name: str
    version: str


@dataclass
class McuData:
    ref_name: str
    family: str
    line: str
    package: str
    has_power_pad: bool = False  # root <Mcu HasPowerPad="..">, build-time audit signal only
    vdd_min: str = ""
    vdd_max: str = ""
    pins: list[Pin] = field(default_factory=list)
    # Spec-matrix fields (mcu_spec, 1:1 with mcu). Populated from the per-MCU XML's
    # top-level <Core>/<Frequency>/<Flash>/<Ram>/<CCMRam>/<IONb>/<Die>/<Voltage>/
    # <Current>/<Temperature> children.
    core: str = ""
    frequency_mhz: int | None = None
    flash_kb: int | None = None
    ram_kb: int | None = None
    ccm_ram_kb: int | None = None
    io_count: int | None = None
    die: str = ""
    current_run_ma: int | None = None  # <Current Run="..">, datasheet mA scale
    current_lowest_ua: int | None = None  # <Current Lowest="..">, datasheet uA scale
    temp_min_c: int | None = None
    temp_max_c: int | None = None
    peripherals: list[Peripheral] = field(default_factory=list)


def _to_int(text: str | None) -> int | None:
    """Parse a CubeMX numeric string (may carry a decimal point) to an int, or
    None when absent/unparseable - never raises."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_mcu_xml(path: Path) -> McuData:
    """Parse one CubeMX device XML. Every <Pin>, including alphanumeric BGA/WLCSP
    ball positions, is kept - MODIFIED from Hardware's stm32_db.py, which silently
    dropped any Position that failed int() (Pitfall 2). The raw Position string is
    always captured as-is; typed geometry (numeric side vs. alnum row/col) is
    derived downstream in the build loop via stm.geometry.per_pin_geometry, not
    here (this function stays a pure structural parse).

    Also walks the spec-matrix elements. Text-content elements (Core, Frequency,
    Flash, Ram, CCMRam, IONb, Die) are read via el.text; attribute-valued elements
    (Voltage Min/Max, Current Lowest/Run, Temperature Min/Max) are read via
    el.get(...) - mixing these up is an easy, real parsing bug (verified against a
    real sample: <Core>Arm Cortex-M4</Core> is text, <Voltage Max=".." Min=".."/>
    is attributes). Flash/Ram may repeat per suffix group; the MAX across repeats
    is kept, since a device XML can carry more than one flash/RAM size option.
    """
    root = ET.parse(path).getroot()
    mcu = McuData(
        ref_name=root.get("RefName", path.stem),
        family=root.get("Family", ""),
        line=root.get("Line", ""),
        package=root.get("Package", ""),
        has_power_pad=(root.get("HasPowerPad", "") or "").strip().lower() == "true",
    )
    for el in root:
        tag = _tag(el)
        if tag == "Voltage":
            mcu.vdd_min = el.get("Min", "") or mcu.vdd_min
            mcu.vdd_max = el.get("Max", "") or mcu.vdd_max
            continue
        if tag == "Current":
            mcu.current_run_ma = _to_int(el.get("Run")) or mcu.current_run_ma
            mcu.current_lowest_ua = _to_int(el.get("Lowest")) or mcu.current_lowest_ua
            continue
        if tag == "Temperature":
            mcu.temp_min_c = _to_int(el.get("Min"))
            mcu.temp_max_c = _to_int(el.get("Max"))
            continue
        if tag == "Core":
            mcu.core = (el.text or "").strip() or mcu.core
            continue
        if tag == "Frequency":
            mcu.frequency_mhz = _to_int(el.text) or mcu.frequency_mhz
            continue
        if tag == "Flash":
            v = _to_int(el.text)
            if v is not None:
                mcu.flash_kb = v if mcu.flash_kb is None else max(mcu.flash_kb, v)
            continue
        if tag == "Ram":
            v = _to_int(el.text)
            if v is not None:
                mcu.ram_kb = v if mcu.ram_kb is None else max(mcu.ram_kb, v)
            continue
        if tag == "CCMRam":
            mcu.ccm_ram_kb = _to_int(el.text)
            continue
        if tag == "IONb":
            mcu.io_count = _to_int(el.text)
            continue
        if tag == "Die":
            mcu.die = (el.text or "").strip() or mcu.die
            continue
        if tag == "IP":
            mcu.peripherals.append(
                Peripheral(
                    name=el.get("Name", ""),
                    instance_name=el.get("InstanceName", ""),
                    version=el.get("Version", ""),
                )
            )
            continue
        if tag != "Pin":
            continue
        pos_raw = (el.get("Position", "") or "").strip()
        pin = Pin(position=pos_raw, name=el.get("Name", "").strip(), type=el.get("Type", ""))
        for child in el:
            if _tag(child) == "Signal":
                pin.signals.append(Signal(child.get("Name", ""), child.get("IOModes", "")))
        mcu.pins.append(pin)
    return mcu


# ─────────────────────────────────────────────────────────────────────────────
# AF0-15 mux (Phase 2, DATA-04) — join a device's declared GPIO IP version to
# its GPIO-<version>_Modes.xml. NEW: no Hardware equivalent exists (the legacy
# app never built this join at all).
# ─────────────────────────────────────────────────────────────────────────────
class StmGpioModesNotFoundError(Exception):
    """Raised when a device's declared GPIO IP Version has no matching
    GPIO-<version>_Modes.xml on disk under the source's IP/ directory - the
    literal 100%-join-resolution gate (DATA-04). The build refuses to
    complete rather than silently shipping a device with an unresolved AF
    join; zero orphans is the only acceptable outcome."""


class StmAfParseError(Exception):
    """Raised when a GPIO_AF SpecificParameter's PossibleValue matches
    NEITHER the AF0-15 shape (``^GPIO_AF(\\d+)_(.+)$``) NOR the F1 legacy
    ``__HAL_AFIO_REMAP_`` prefix - a genuinely unrecognized value shape that
    must be surfaced, never silently dropped (DATA-04/Pitfall-1: "surfaced
    and handled, never silently mis-parsed")."""


_AF_PATTERN = re.compile(r"^GPIO_AF(\d+)_(.+)$")
_LEGACY_AFIO_REMAP_PREFIX = "__HAL_AFIO_REMAP_"


def _is_legacy_afio_remap(value: str) -> bool:
    """True for F1's classic peripheral-level partial-remap tokens (e.g.
    ``__HAL_AFIO_REMAP_TIM2_PARTIAL_2``). The classic F1 line (F100/F103/
    F105/F107) predates the AF0-15 mux entirely - verified this session by
    parsing every GPIO_AF SpecificParameter value in its 7 GPIO Modes files:
    100% carry this exact prefix. These contribute zero pin_alternate_function
    rows and must NOT trip the join gate (an architecturally true zero, not a
    parsing gap)."""
    return value.startswith(_LEGACY_AFIO_REMAP_PREFIX)


def parse_gpio_ip_xml(ip_dir: Path, version: str) -> dict[str, list[tuple[str, int, str]]]:
    """Parse one ``GPIO-<version>_Modes.xml`` into
    ``{raw_pin_name: [(signal, af_index, peripheral), ...]}``.

    Raises StmGpioModesNotFoundError when the resolved file does not exist on
    disk - this IS the literal 100%-join-resolution gate (DATA-04).

    A real ElementTree parse (never a brittle ``/>`` string scan) is required:
    STM32N6's per-device ``<IP Name="GPIO">`` element is NOT self-closing (it
    has ``<ContextSplit>`` children) while F0's is - only ``.get()``/``.attrib``
    handle both forms uniformly. This function itself must also handle two
    distinct GPIO_AF shapes, verified against the real source this session:
    the modern AF0-15 shape, where ``<SpecificParameter Name="GPIO_AF">`` is a
    DIRECT child of ``<PinSignal>``, and F1's legacy shape, where that same
    element is nested one level deeper inside a ``<RemapBlock>`` child of
    ``<PinSignal>`` (confirmed against the real
    ``GPIO-STM32F103xC_gpio_v1_0_Modes.xml`` - not the shape the phase's
    initial research described, which assumed a direct child uniformly). GPIO_AF
    SpecificParameter elements are therefore located by walking each
    PinSignal's FULL subtree (``ps.iter()``), not just its direct children, so
    both shapes resolve to the same classification path.
    """
    path = Path(ip_dir) / f"GPIO-{version}_Modes.xml"
    if not path.exists():
        raise StmGpioModesNotFoundError(
            f"GPIO IP version {version!r} has no matching Modes file at "
            f"{path} - 100%-join-resolution gate (DATA-04)"
        )
    root = ET.parse(path).getroot()
    result: dict[str, list[tuple[str, int, str]]] = {}
    for gp in root:
        if _tag(gp) != "GPIO_Pin":
            continue
        pin_name = (gp.get("Name", "") or "").strip()
        if not pin_name:
            continue
        entries: list[tuple[str, int, str]] = []
        for ps in gp:
            if _tag(ps) != "PinSignal":
                continue
            signal = (ps.get("Name", "") or "").strip()
            for sp in ps.iter():
                if _tag(sp) != "SpecificParameter" or sp.get("Name") != "GPIO_AF":
                    continue
                for pv in sp:
                    if _tag(pv) != "PossibleValue":
                        continue
                    value = (pv.text or "").strip()
                    m = _AF_PATTERN.match(value)
                    if m:
                        entries.append((signal, int(m.group(1)), m.group(2)))
                    elif _is_legacy_afio_remap(value):
                        continue
                    else:
                        raise StmAfParseError(
                            f"unrecognized GPIO_AF value {value!r} for pin "
                            f"{pin_name!r} signal {signal!r} in {path.name} - "
                            "matches neither the AF0-15 shape nor the F1 "
                            "legacy __HAL_AFIO_REMAP_ prefix"
                        )
        if entries:
            result[pin_name] = entries
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Classify — a pin's electrical class, canonical name, and roles
# (REUSE VERBATIM from legacy/tools/stm32_db.py:143-250 - generic per-pin-nature
# classifiers, nothing NETDECK/switch-fabric-specific)
# ─────────────────────────────────────────────────────────────────────────────
_PORT = re.compile(r"^P([A-Z])(\d{1,2})")


def canonical(pin: Pin) -> tuple[str, str | None, int | None]:
    """(canonical_pin_name, gpio_port, gpio_index)."""
    m = _PORT.match(pin.name)
    if m:
        port, idx = m.group(1), int(m.group(2))
        return f"P{port}{idx}", port, idx
    return pin.name.replace("_", "").replace(" ", ""), None, None


def electrical_class(pin: Pin) -> str:
    name = pin.name.upper()
    if "NPOR" in name or "PDR_ON" in name or name == "RFU":
        return "io"
    if pin.type == "Reset":
        return "reset"
    if pin.type == "Boot":
        return "boot"
    if pin.type == "NC":
        return "nc"
    if pin.type == "Power":
        if name.startswith("VSS"):
            return "ground"
        if name.startswith("VCAP"):
            return "vcap"
        if name.startswith("VREF") and name.rstrip().endswith("-"):
            return "ground"
        return "power"
    return "io"  # I/O, MonoIO


def _is_analog(pin: Pin) -> bool:
    if any("ADC" in s.name or "DAC" in s.name for s in pin.signals):
        return True
    return any("Analog" in s.io_modes for s in pin.signals)


def roles(pin: Pin) -> list[tuple[str, str]]:
    """List of (role_name, role_class) for this pin on this MCU."""
    ec = electrical_class(pin)
    name = pin.name.upper()
    sigs = " ".join(s.name for s in pin.signals).upper()
    out: list[tuple[str, str]] = []

    if ec == "power":
        if "DSI" in name and "12" in name:
            out.append(("vcap_dsi", "local_card"))
        elif name.startswith("VBAT"):
            out.append(("power_vbat", "power"))
        elif name.startswith("VDDA"):
            out.append(("power_vdda", "power"))
        elif name.startswith("VREF"):
            out.append(("power_vref", "power"))
        else:
            out.append(("power_vdd", "power"))
    elif ec == "ground":
        out.append(("ground", "ground"))
    elif ec == "vcap":
        if "DSI" in name:
            out.append(("vcap_dsi", "local_card"))
        else:
            out.append(("vcap", "local_card"))
    elif ec == "reset":
        out.append(("reset_nrst", "service"))
    elif ec == "boot":
        out.append(("boot", "service"))
    elif ec == "nc":
        pass
    else:  # io - HSE only (OSC_IN/OSC_OUT), NOT LSE OSC32 (plain GPIO)
        if "OSC_OUT" in name or "RCC_OSC_OUT" in sigs:
            out.append(("oscillator_hse_out", "local_card"))
        elif "OSC_IN" in name or "RCC_OSC_IN" in sigs:
            out.append(("oscillator_hse_in", "local_card"))
        if "SWDIO" in sigs or "JTMS" in sigs:
            out.append(("swdio", "service"))
        if "SWCLK" in sigs or "JTCK" in sigs:
            out.append(("swclk", "service"))
        if "TRACESWO" in sigs or "JTDO" in sigs or "-SWO" in sigs or "_SWO" in sigs:
            out.append(("swo", "service"))
        if "JTDI" in sigs or "NJTRST" in sigs or "JTRST" in sigs:
            out.append(("jtag_extra", "service"))
        if _is_analog(pin):
            out.append(("analog", "io"))
        if "GPIO" in sigs:
            out.append(("gpio", "io"))
        if not any(rc == "io" for _, rc in out):
            out.append(("gpio", "io"))  # every I/O pin carries an IO identity

    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for rn, rc in out:
        if rn not in seen:
            seen.add(rn)
            uniq.append((rn, rc))
    return uniq


# ─────────────────────────────────────────────────────────────────────────────
# Schema — the Phase 1 nine-table subset of INTERFACES.md section 1
# (everything except the AF-mux join table, which is Phase 2's addition)
# ─────────────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE source_artifact (
    id INTEGER PRIMARY KEY, path TEXT, imported_at TEXT);

-- one row per CubeMX pinout key (RefName), narrowed to pinout identity only.
-- ref_name is the CubeMX RefName stored AS-IS (a pinout key, e.g.
-- 'STM32F407V(E-G)Tx'), NOT an orderable MPN.
CREATE TABLE mcu (
    id INTEGER PRIMARY KEY, source_artifact_id INTEGER NOT NULL,
    ref_name TEXT NOT NULL,
    family TEXT,
    line TEXT,
    package_name TEXT, pin_count INTEGER,
    vdd_min TEXT, vdd_max TEXT, imported_at TEXT NOT NULL);

-- 1:1 with mcu. Spec-matrix fields (Task 2 populates this).
-- current_run_ua stores the raw <Current Run=".."> value AS CubeMX reports it
-- (datasheet-scale, typically mA for the run/active current) - the column name is
-- the frozen INTERFACES.md contract name; it is NOT rescaled to true microamps.
-- current_lowest_ua stores <Current Lowest=".."> (typically already uA-scale,
-- e.g. standby/deep-sleep current). Column names kept exactly as INTERFACES.md
-- section 1 specifies them.
CREATE TABLE mcu_spec (
    mcu_id INTEGER PRIMARY KEY,
    core TEXT,
    flash_kb INTEGER, ram_kb INTEGER, ccm_ram_kb INTEGER,
    max_freq_mhz INTEGER, io_count INTEGER,
    vdd_min REAL, vdd_max REAL,
    temp_min_c INTEGER, temp_max_c INTEGER,
    current_run_ua INTEGER, current_lowest_ua INTEGER,
    die TEXT);

-- one row per <IP Name=... InstanceName=... Version=.../> element (Task 2 populates this).
CREATE TABLE mcu_peripheral (
    id INTEGER PRIMARY KEY, mcu_id INTEGER NOT NULL,
    peripheral_name TEXT NOT NULL,
    instance_name TEXT, version TEXT);

-- physical_pin_number is TEXT (widened from Hardware's INTEGER) so BGA/WLCSP ball
-- labels ("A1".."AB12") are never coerced/dropped. Keyed by (mcu_id,
-- physical_pin_number, raw_pin_name) - NOT just (mcu_id, physical_pin_number) -
-- so two distinct pin identities sharing one physical position (e.g. a
-- Variant="PINREMAP" alternate identity) each persist as their own row.
CREATE TABLE mcu_package_pin (
    id INTEGER PRIMARY KEY, mcu_id INTEGER NOT NULL, package_name TEXT,
    physical_pin_number TEXT NOT NULL,
    position_kind TEXT NOT NULL CHECK(position_kind IN ('numeric','alnum')),
    bga_row TEXT, bga_col INTEGER,
    canonical_pin_name TEXT NOT NULL, raw_pin_name TEXT NOT NULL, pin_type TEXT,
    electrical_class TEXT NOT NULL
        CHECK(electrical_class IN ('io','power','ground','reset','boot','vcap','nc')),
    gpio_port TEXT, gpio_pin_index INTEGER,
    lqfp_side TEXT CHECK(lqfp_side IN ('left','bottom','right','top')),
    source_confidence REAL DEFAULT 0.9,
    UNIQUE(mcu_id, physical_pin_number, raw_pin_name));

CREATE TABLE pin_function (
    id INTEGER PRIMARY KEY, mcu_package_pin_id INTEGER NOT NULL,
    function_name TEXT NOT NULL, signal TEXT, io_modes TEXT);

CREATE TABLE pin_role (
    id INTEGER PRIMARY KEY, mcu_package_pin_id INTEGER NOT NULL,
    role_name TEXT NOT NULL, role_class TEXT NOT NULL,
    UNIQUE(mcu_package_pin_id, role_name));

-- hand-curated, datasheet-cited geometry CubeMX omits (Plan 02 populates this).
CREATE TABLE package_geometry (
    package_name TEXT PRIMARY KEY,
    body_shape TEXT NOT NULL CHECK(body_shape IN ('qfp','qfn','bga','wlcsp')),
    pin_count INTEGER, rows INTEGER, cols INTEGER,
    pitch_mm REAL, body_mm REAL,
    has_center_pad INTEGER DEFAULT 0,
    depopulation TEXT,
    citation TEXT, notes TEXT);

-- the AF0-15 mux (Phase 2), sourced from GPIO IP XML, joined onto
-- mcu_package_pin by raw_pin_name (NEVER canonical_pin_name - two
-- same-position PINREMAP identities, or a plain ball and its _C-suffix
-- sibling, share a canonical name but must each carry their own AF set).
CREATE TABLE pin_alternate_function (
    id INTEGER PRIMARY KEY, mcu_package_pin_id INTEGER NOT NULL,
    af_index INTEGER NOT NULL CHECK(af_index BETWEEN 0 AND 15),
    signal TEXT NOT NULL,
    peripheral TEXT,
    UNIQUE(mcu_package_pin_id, af_index, signal));

CREATE INDEX ix_pin_mcu     ON mcu_package_pin(mcu_id);
CREATE INDEX ix_role_pin    ON pin_role(mcu_package_pin_id);
CREATE INDEX ix_func_pin    ON pin_function(mcu_package_pin_id);
CREATE INDEX ix_mcu_family  ON mcu(family);
CREATE INDEX ix_mcu_package ON mcu(package_name);
CREATE INDEX ix_periph_mcu  ON mcu_peripheral(mcu_id);
CREATE INDEX ix_periph_name ON mcu_peripheral(peripheral_name);
CREATE INDEX ix_af_pin      ON pin_alternate_function(mcu_package_pin_id);
CREATE INDEX ix_af_signal   ON pin_alternate_function(signal);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Self-audit — a build-time HARD GATE (DATA-07), not a warning. Pitfall 2
# (dropped packages) and Pitfall 6 (trust with no ground truth) are locked out
# structurally: a defective build never becomes a loadable index. AF-range
# checks are explicitly OUT of Phase 1's gate scope (no AF join table exists yet).
# ─────────────────────────────────────────────────────────────────────────────
class StmSourceCoverageError(Exception):
    """Raised by StmIndex.build(..., require_all_families=True) when
    check_availability reports the source is F-only (DATA-01's build guard):
    the build refuses to promise "all families" against a source that looks
    F-only, unless the caller explicitly descopes by NOT requiring it."""


class StmAuditFailure(Exception):
    """Raised when a freshly built index fails its structural self-audit. The
    build refuses to complete (no index is returned) - callers never receive a
    structurally defective StmIndex silently. Never names a raw wildcarded
    ref_name as if it were an orderable part; issues are addressed by
    mcu id + package_name only."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("STM index self-audit failed:\n- " + "\n- ".join(issues))


def run_self_audit(conn: sqlite3.Connection) -> None:
    """Run the Phase 1 structural self-audit over a freshly built connection.
    Raises StmAuditFailure (never returns a partial pass/fail value) on any of:

      1. Pin-count reconciliation: mcu.pin_count disagrees with the matching
         package_geometry.pin_count, where a geometry entry exists for that
         package.
      2. Non-empty/zero-pin check: any mcu ends with zero parsed
         mcu_package_pin rows (the Pitfall 2 regression lock).
      3. Spec completeness: any mcu lacks a mcu_spec row, or that row has a
         null core/ram_kb.

    flash_kb and max_freq_mhz are DELIBERATELY excluded from the hard-gate
    completeness check (this differs from an earlier, narrower reading of
    DATA-07 verified only against the phase's own committed fixtures, all of
    which happen to carry both fields). Running this gate against the REAL
    all-families source (2,123 device XML, 2026-07-23) empirically showed
    core and ram_kb are 100% universal, but 11 devices (STM32H5E4/E5 external-
    flash security-line variants) carry no <Flash> element at all, and 760
    devices (35.8% of the real source - STM32C0/G4/H5/H7/U0/U3/U5/WB/WBA/WB0/
    WL3/N6/MP1/MP2 among others) carry no <Frequency> element. This is a
    genuine CubeMX data-availability gap, not a parser defect: enforcing
    flash_kb/max_freq_mhz as hard-required would make DATA-01's own all-
    families ingest structurally impossible to pass, which cannot have been
    the intent. Both fields remain nullable columns, queryable, and simply
    absent where CubeMX itself provides no fact - never a fabricated value.

    AF-range checks are explicitly OUT of this gate's scope (Phase 2 extends
    it once the AF-mux join table exists).
    """
    issues: list[str] = []

    # 1. Pin-count reconciliation against the curated package_geometry table.
    # Tolerance of +/-1 (not strict equality): confirmed against the real
    # all-families source (2026-07-23) that CubeMX itself is inconsistent about
    # whether an exposed thermal pad is numbered as its OWN distinct pin
    # position - 12 STM32WBA devices (UFQFPN32/48) carry position "33"/"49"
    # named "VSS (exposed pad)" that most other devices sharing that same
    # package_name do NOT number separately. This is a genuine CubeMX
    # per-device labeling quirk (same package_name, different pad-numbering
    # convention), not a parser regression - a >=2-pin gap (the actual Pitfall
    # 2 failure mode: losing dozens of pins) still fails loudly.
    for row in conn.execute(
        "SELECT m.id AS mcu_id, m.package_name, m.pin_count AS parsed_count, "
        "g.pin_count AS geometry_count "
        "FROM mcu m JOIN package_geometry g ON g.package_name = m.package_name "
        "WHERE g.pin_count IS NOT NULL AND ABS(m.pin_count - g.pin_count) > 1"
    ):
        issues.append(
            f"pin-count mismatch: mcu id {row['mcu_id']} (package "
            f"{row['package_name']}) parsed {row['parsed_count']} pins but "
            f"package_geometry states {row['geometry_count']}"
        )

    # 2. Zero-pin check: every mcu must have at least one mcu_package_pin row.
    for row in conn.execute(
        "SELECT m.id AS mcu_id, m.package_name, "
        "COUNT(p.id) AS n_pins "
        "FROM mcu m LEFT JOIN mcu_package_pin p ON p.mcu_id = m.id "
        "GROUP BY m.id HAVING n_pins = 0"
    ):
        issues.append(
            f"zero-pin package: mcu id {row['mcu_id']} (package "
            f"{row['package_name']}) parsed zero pins"
        )

    # 3. Spec completeness: every mcu needs a non-null mcu_spec row. Only
    # core/ram_kb are hard-required (empirically 100% universal against the
    # real all-families source); flash_kb/max_freq_mhz are real, legitimate
    # CubeMX omissions for a meaningful minority of devices - see the
    # docstring above.
    for row in conn.execute(
        "SELECT m.id AS mcu_id, m.package_name, s.mcu_id AS spec_mcu_id, "
        "s.core, s.ram_kb "
        "FROM mcu m LEFT JOIN mcu_spec s ON s.mcu_id = m.id"
    ):
        if row["spec_mcu_id"] is None:
            issues.append(
                f"missing mcu_spec row: mcu id {row['mcu_id']} (package "
                f"{row['package_name']})"
            )
            continue
        missing_fields = [name for name in ("core", "ram_kb") if row[name] is None]
        if missing_fields:
            issues.append(
                f"incomplete mcu_spec: mcu id {row['mcu_id']} (package "
                f"{row['package_name']}) missing {', '.join(missing_fields)}"
            )

    if issues:
        raise StmAuditFailure(issues)


class StmIndex:
    """A derived SQLite index over the CubeMX MCU XML tree.

    Build with `StmIndex.build(cubemx_source)` (in-memory by default, or pass a
    `db_path` under per-machine state - see stm.source.default_index_path()).
    Load a file-backed index with `StmIndex.load(db_path)`; it returns None
    (never a partially-usable object) on any stamp mismatch or corruption.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ---- build -------------------------------------------------------------
    @classmethod
    def build(
        cls,
        cubemx_source: Path,
        db_path: str | Path = ":memory:",
        progress=None,
        require_all_families: bool = False,
    ) -> "StmIndex":
        """
        require_all_families: when True, refuses to build at all
        (StmSourceCoverageError) if check_availability reports the source is
        F-only. Defaults to False so fixture-scoped/dev builds (e.g. the
        committed F0-F7-only test fixtures) keep working unchanged; Plan 04's
        real all-families integration build passes True to make DATA-01's
        "all families" claim an enforced gate, not just an honest stamp.
        Regardless of this flag, the stamped meta.all_families value always
        reflects check_availability's real verdict - it is never optimistically
        set True for an F-only source.
        """
        cubemx_source = Path(cubemx_source)
        availability = source_mod.check_availability(cubemx_source)
        if require_all_families and not availability.all_families:
            raise StmSourceCoverageError(
                f"source at {cubemx_source} looks F-only "
                f"({availability.family_count} families, "
                f"{availability.device_xml_count} device XML) - refusing to "
                "build an all-families index. Pass require_all_families=False "
                "to explicitly descope, or point at the real CubeMX mcu/ tree."
            )
        is_file_backed = str(db_path) != ":memory:"
        sha = source_mod.source_sha256(cubemx_source)

        if is_file_backed:
            existing_path = Path(db_path)
            if existing_path.exists():
                existing = cls.load(existing_path)
                if existing is not None:
                    row = existing._conn.execute(
                        "SELECT value FROM meta WHERE key='source_sha256'"
                    ).fetchone()
                    if row and row["value"] == sha:
                        if progress:
                            progress({"pct": 100, "message": "unchanged source, skip rebuild"})
                        return existing
                    existing.close()

        # check_same_thread=False so a warm index can be read from the API's
        # threadpool worker threads (mirrors store/index.py's LibraryIndex.build).
        if is_file_backed:
            out_path = Path(db_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.exists():
                out_path.unlink()
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)

        source_path = str(cubemx_source)
        built_at = datetime.now(timezone.utc).isoformat()
        art_id = conn.execute(
            "INSERT INTO source_artifact (path, imported_at) VALUES (?,?)",
            (source_path, built_at),
        ).lastrowid

        files = source_mod.device_xml_files(cubemx_source)
        total = len(files)
        power_pad_observed: dict[str, set[bool]] = {}
        n_mcu = 0
        # AF0-15 mux ingest (Phase 2, DATA-04): ip_dir is the sibling IP/
        # directory the GPIO Modes files live under, exactly CubeMX's own
        # mcu/IP/ layout. af_cache holds one parsed {raw_pin_name: [...]}
        # dict per GPIO IP version per build - 2,123 real devices resolve to
        # only ~96 distinct Modes files, so re-parsing per-device would be
        # wasteful. legacy_afio_device_count tracks F1-shaped devices (logged
        # as an accounted-for zero, never an orphan); af_orphan_join_count
        # stays 0 in the normal path (a real orphan already raises
        # StmGpioModesNotFoundError directly, well before this counter would
        # ever need to be non-zero - kept as an explicit, defense-in-depth
        # value the self-audit re-asserts rather than only trusting the raise).
        ip_dir = cubemx_source / "IP"
        af_cache: dict[str, dict[str, list[tuple[str, int, str]]]] = {}
        legacy_afio_device_count = 0
        af_orphan_join_count = 0
        for i, f in enumerate(files):
            if progress and i % 25 == 0:
                progress({"pct": int(100 * i / total) if total else 0, "message": f.stem})
            mcu = parse_mcu_xml(f)
            power_pad_observed.setdefault(mcu.package, set()).add(mcu.has_power_pad)
            distinct_positions = sorted({p.position for p in mcu.pins})
            pin_count = len(distinct_positions)
            mcu_id = conn.execute(
                "INSERT INTO mcu (source_artifact_id, ref_name, family, line, "
                "package_name, pin_count, vdd_min, vdd_max, imported_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    art_id,
                    mcu.ref_name,
                    mcu.family,
                    mcu.line,
                    mcu.package,
                    pin_count,
                    mcu.vdd_min,
                    mcu.vdd_max,
                    built_at,
                ),
            ).lastrowid
            n_mcu += 1

            conn.execute(
                "INSERT INTO mcu_spec (mcu_id, core, flash_kb, ram_kb, ccm_ram_kb, "
                "max_freq_mhz, io_count, vdd_min, vdd_max, temp_min_c, temp_max_c, "
                "current_run_ua, current_lowest_ua, die) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mcu_id,
                    mcu.core,
                    mcu.flash_kb,
                    mcu.ram_kb,
                    mcu.ccm_ram_kb,
                    mcu.frequency_mhz,
                    mcu.io_count,
                    float(mcu.vdd_min) if mcu.vdd_min else None,
                    float(mcu.vdd_max) if mcu.vdd_max else None,
                    mcu.temp_min_c,
                    mcu.temp_max_c,
                    mcu.current_run_ma,
                    mcu.current_lowest_ua,
                    mcu.die,
                ),
            )
            for periph in mcu.peripherals:
                conn.execute(
                    "INSERT INTO mcu_peripheral (mcu_id, peripheral_name, "
                    "instance_name, version) VALUES (?,?,?,?)",
                    (mcu_id, periph.name, periph.instance_name, periph.version),
                )

            pin_ids_by_raw_name: dict[str, list[int]] = {}
            for pin in mcu.pins:
                ec = electrical_class(pin)
                canon, port, idx = canonical(pin)
                geo = geometry_mod.per_pin_geometry(mcu.package, pin.position, pin_count)
                pin_id = conn.execute(
                    "INSERT INTO mcu_package_pin (mcu_id, package_name, "
                    "physical_pin_number, position_kind, bga_row, bga_col, "
                    "canonical_pin_name, raw_pin_name, pin_type, electrical_class, "
                    "gpio_port, gpio_pin_index, lqfp_side) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        mcu_id,
                        mcu.package,
                        pin.position,
                        geo["position_kind"],
                        geo["bga_row"],
                        geo["bga_col"],
                        canon,
                        pin.name,
                        pin.type,
                        ec,
                        port,
                        idx,
                        geo["lqfp_side"],
                    ),
                ).lastrowid
                pin_ids_by_raw_name.setdefault(pin.name, []).append(pin_id)
                for s in pin.signals:
                    conn.execute(
                        "INSERT INTO pin_function (mcu_package_pin_id, function_name, "
                        "signal, io_modes) VALUES (?,?,?,?)",
                        (pin_id, s.name, s.name, s.io_modes),
                    )
                for rn, rc in roles(pin):
                    conn.execute(
                        "INSERT OR IGNORE INTO pin_role (mcu_package_pin_id, role_name, "
                        "role_class) VALUES (?,?,?)",
                        (pin_id, rn, rc),
                    )

            # AF0-15 mux ingest (Phase 2, DATA-04): the GPIO IP version for
            # this device is read from the mcu_peripheral row just inserted
            # above, matched by the EXACT peripheral_name = 'GPIO' (never a
            # substring/LIKE '%GPIO%' test - STM32U5 also carries an
            # LPBAMLPGPIO instance whose name contains "GPIO"). A device with
            # no GPIO peripheral row at all (synthetic fixtures exercising
            # unrelated behavior) simply gets zero AF rows - not an error.
            gpio_peripheral = conn.execute(
                "SELECT version FROM mcu_peripheral WHERE mcu_id = ? AND "
                "peripheral_name = 'GPIO'",
                (mcu_id,),
            ).fetchone()
            if gpio_peripheral is not None and gpio_peripheral["version"]:
                version = gpio_peripheral["version"]
                if version not in af_cache:
                    try:
                        af_cache[version] = parse_gpio_ip_xml(ip_dir, version)
                    except StmGpioModesNotFoundError:
                        af_orphan_join_count += 1
                        raise
                af_map = af_cache[version]
                if not af_map:
                    # Every GPIO_AF value in this version's Modes file was
                    # either absent or a recognized F1 legacy AFIO-remap
                    # token (parse_gpio_ip_xml raises on any genuinely
                    # unrecognized shape, so an empty result here can only
                    # mean the architecturally-true F1 zero-AF-mux case).
                    legacy_afio_device_count += 1
                for raw_name, af_list in af_map.items():
                    pin_ids = pin_ids_by_raw_name.get(raw_name)
                    if not pin_ids:
                        # Shared-Modes-file superset case: this GPIO_Pin
                        # entry belongs to a different package/density
                        # variant sharing the same IP version - silently
                        # skipped, never gate-counted.
                        continue
                    for pin_id in pin_ids:
                        for signal, af_index, peripheral in af_list:
                            conn.execute(
                                "INSERT OR IGNORE INTO pin_alternate_function "
                                "(mcu_package_pin_id, af_index, signal, peripheral) "
                                "VALUES (?,?,?,?)",
                                (pin_id, af_index, signal, peripheral),
                            )

        logger.info(
            "AF join: legacy AFIO-remap family: %d devices, 0 AF rows, expected",
            legacy_afio_device_count,
        )

        # package_geometry is a static, curated reference table (stm.geometry.
        # PACKAGE_GEOMETRY) - populated in full regardless of which packages this
        # particular build happened to ingest, since it documents package
        # mechanical facts, not per-build ingest results.
        for package_name, entry in geometry_mod.PACKAGE_GEOMETRY.items():
            conn.execute(
                "INSERT OR REPLACE INTO package_geometry (package_name, body_shape, "
                "pin_count, rows, cols, pitch_mm, body_mm, has_center_pad, "
                "depopulation, citation, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    package_name,
                    entry["body_shape"],
                    entry.get("pin_count"),
                    entry.get("rows"),
                    entry.get("cols"),
                    entry.get("pitch_mm"),
                    entry.get("body_mm"),
                    int(entry.get("has_center_pad", 0)),
                    entry.get("depopulation"),
                    entry.get("citation"),
                    entry.get("notes"),
                ),
            )
        power_pad_flags = geometry_mod.audit_has_power_pad(power_pad_observed)

        # The honest, code-level "does this source really span every family"
        # verdict - check_availability's own report, never re-derived from the
        # naive families_seen-during-ingest tally (which would silently agree
        # with whatever this one build happened to parse instead of the
        # independently-computed, re-runnable availability check).
        for key, value in (
            ("classifier_rev", str(CLASSIFIER_REV)),
            ("geometry_rev", str(geometry_mod.GEOMETRY_REV)),
            ("source_sha256", sha),
            ("source_file_count", str(total)),
            ("source_path", source_path),
            ("built_at", built_at),
            ("all_families", "true" if availability.all_families else "false"),
            ("device_xml_count", str(availability.device_xml_count)),
            ("family_count", str(availability.family_count)),
            ("power_pad_flags", ",".join(power_pad_flags)),
        ):
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))

        try:
            run_self_audit(conn)
        except StmAuditFailure:
            conn.close()
            raise

        conn.commit()
        if progress:
            progress({"pct": 100, "message": "done"})
        return cls(conn)

    # ---- load ----------------------------------------------------------------
    @classmethod
    def load(cls, db_path: str | Path) -> "StmIndex | None":
        """Open a file-backed index, or return None (never a partial object) when
        the file is missing/corrupt, or its stamped classifier_rev/geometry_rev
        does not match this module's build code (DATA-08's load-refusal gate)."""
        if str(db_path) == ":memory:":
            return None
        p = Path(db_path)
        if not p.exists():
            return None
        try:
            conn = sqlite3.connect(str(p), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        except sqlite3.Error:
            return None
        try:
            classifier_rev = int(meta.get("classifier_rev", "-1"))
            geometry_rev = int(meta.get("geometry_rev", "-1"))
        except (TypeError, ValueError):
            conn.close()
            return None
        if classifier_rev != CLASSIFIER_REV or geometry_rev != geometry_mod.GEOMETRY_REV:
            conn.close()
            return None
        return cls(conn)

    # ---- queries ---------------------------------------------------------------
    def mcu_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM mcu").fetchone()[0]

    def meta(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM meta")}

    def close(self) -> None:
        self._conn.close()
