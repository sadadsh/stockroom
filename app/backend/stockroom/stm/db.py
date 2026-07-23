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

import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stockroom.stm import geometry as geometry_mod
from stockroom.stm import source as source_mod

# Classification revision: bump whenever canonical()/electrical_class()/roles() or
# the schema's classification-derived columns change meaning, so a database built
# by older classification code is never silently trusted (StmIndex.load() checks
# this against the stamped meta.classifier_rev).
#   rev 1 (2026-07-23): initial port of canonical/electrical_class/_is_analog/roles
#     from legacy/tools/stm32_db.py, unchanged; mcu_package_pin keyed by
#     (mcu_id, physical_pin_number, raw_pin_name) so same-position PINREMAP
#     identities are never collapsed.
CLASSIFIER_REV = 1

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
class McuData:
    ref_name: str
    family: str
    line: str
    package: str
    vdd_min: str = ""
    vdd_max: str = ""
    pins: list[Pin] = field(default_factory=list)


def parse_mcu_xml(path: Path) -> McuData:
    """Parse one CubeMX device XML. Every <Pin>, including alphanumeric BGA/WLCSP
    ball positions, is kept - MODIFIED from Hardware's stm32_db.py, which silently
    dropped any Position that failed int() (Pitfall 2). The raw Position string is
    always captured as-is; typed geometry (numeric side vs. alnum row/col) is
    derived downstream in the build loop via stm.geometry.per_pin_geometry, not
    here (this function stays a pure structural parse)."""
    root = ET.parse(path).getroot()
    mcu = McuData(
        ref_name=root.get("RefName", path.stem),
        family=root.get("Family", ""),
        line=root.get("Line", ""),
        package=root.get("Package", ""),
    )
    for el in root:
        tag = _tag(el)
        if tag == "Voltage":
            mcu.vdd_min = el.get("Min", "") or mcu.vdd_min
            mcu.vdd_max = el.get("Max", "") or mcu.vdd_max
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

CREATE INDEX ix_pin_mcu     ON mcu_package_pin(mcu_id);
CREATE INDEX ix_role_pin    ON pin_role(mcu_package_pin_id);
CREATE INDEX ix_func_pin    ON pin_function(mcu_package_pin_id);
CREATE INDEX ix_mcu_family  ON mcu(family);
CREATE INDEX ix_mcu_package ON mcu(package_name);
CREATE INDEX ix_periph_mcu  ON mcu_peripheral(mcu_id);
CREATE INDEX ix_periph_name ON mcu_peripheral(peripheral_name);
"""


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
    ) -> "StmIndex":
        cubemx_source = Path(cubemx_source)
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

        files = sorted(p for p in cubemx_source.glob("*.xml") if p.name != "families.xml")
        total = len(files)
        families_seen: set[str] = set()
        n_mcu = 0
        for i, f in enumerate(files):
            if progress and i % 25 == 0:
                progress({"pct": int(100 * i / total) if total else 0, "message": f.stem})
            mcu = parse_mcu_xml(f)
            families_seen.add(mcu.family)
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

        family_count = len(families_seen)
        # A naive placeholder: the honest, code-level "does this source really span
        # every family" gate is check_availability + the build guard (Plan 02 Task 3).
        # Until that guard is wired in, never optimistically claim all_families here.
        all_families = False
        for key, value in (
            ("classifier_rev", str(CLASSIFIER_REV)),
            ("geometry_rev", str(geometry_mod.GEOMETRY_REV)),
            ("source_sha256", sha),
            ("source_file_count", str(total)),
            ("source_path", source_path),
            ("built_at", built_at),
            ("all_families", "true" if all_families else "false"),
            ("device_xml_count", str(total)),
            ("family_count", str(family_count)),
        ):
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))

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
