"""Locate the CubeMX MCU XML source tree + the derived index path (Qt-free, stdlib-only).

The CubeMX database (ST's own STM32CubeMX install, or a synced copy of it) is the
read-only ground truth every STM32 device XML is parsed from. It is NOT bundled with
this app and NOT committed: the user (or an env var, in tests/CI) points at it.

default_cubemx_source() uses only a configured source or a real Windows all-families tree.
Tests inject their own fixture explicitly; production discovery never crosses into WSL or
silently substitutes a partial development database.
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.store.machine_config import config_dir

# The F0-F7 families alone (Hardware's whole prior scope) are exactly six:
# STM32F0, F1, F2, F3, F4, F7 (confirmed against legacy/tools/stm32_authority.py's
# FAMILY_ELECTRICAL/BOOTLOADER_PINS keys). A source reporting strictly this set
# (or fewer) is F-only by construction, never "all families" - the real
# all-families source spans ~20+ family lines (confirmed 28 distinct root
# Family values against the real Windows-side source this session).
_F_ONLY_FAMILY_CEILING = 6

# The confirmed Windows all-families candidates. Order: the synced STMP copy first (stable,
# versioned), then the per-user and system-wide CubeMX installs. Resolve these from Windows
# environment roots; `/mnt/c/...` is a WSL path and is never valid in the Windows-only app.
_WINDOWS_HOME = Path(os.environ.get("USERPROFILE") or Path.home())
_LOCAL_APP_DATA = Path(
    os.environ.get("LOCALAPPDATA") or (_WINDOWS_HOME / "AppData" / "Local")
)
_PROGRAM_FILES = Path(os.environ.get("ProgramFiles") or "C:/Program Files")
_WINDOWS_CANDIDATES = (
    str(_WINDOWS_HOME / "STMP" / "cubemx_db" / "mcu"),
    str(_LOCAL_APP_DATA / "Programs" / "STM32CubeMX" / "db" / "mcu"),
    str(
        _PROGRAM_FILES
        / "STMicroelectronics"
        / "STM32Cube"
        / "STM32CubeMX"
        / "db"
        / "mcu"
    ),
)


def default_cubemx_source() -> Path | None:
    """Locate the CubeMX MCU XML directory, or None if nothing is found.

    MachineConfig.stm_cubemx_source (the settings-page-less, PATCH /api/settings
    -settable override, Phase 3 API-02) wins outright when set and valid.
    Otherwise STM32_CUBEMX (or the legacy HWKIT_CUBEMX) wins when set and valid.
    Otherwise the confirmed Windows all-families candidates are tried. A missing source remains
    missing; tests and development tools must inject fixtures explicitly.
    """
    from stockroom.store.machine_config import MachineConfig

    configured = (MachineConfig.load().stm_cubemx_source or "").strip()
    configured_source = normalize_cubemx_source(Path(configured)) if configured else None
    if configured_source is not None and has_device_xml(configured_source):
        return configured_source
    env = os.environ.get("STM32_CUBEMX") or os.environ.get("HWKIT_CUBEMX")
    env_source = normalize_cubemx_source(Path(env)) if env else None
    if env_source is not None and has_device_xml(env_source):
        return env_source
    for candidate in _WINDOWS_CANDIDATES:
        c = Path(candidate)
        if has_device_xml(c):
            return c
    return None


def expected_cubemx_source() -> Path:
    """The path the status surface should NAME: the discovered source when one exists,
    else the primary all-families candidate (where a fresh CubeMX install lands), so
    status can always report a concrete expected location on a bare machine and
    source_present carries the honest "it is not there". Build-time callers keep using
    default_cubemx_source(), whose None still fails loudly."""
    found = default_cubemx_source()
    return found if found is not None else Path(_WINDOWS_CANDIDATES[0])


def default_index_path() -> Path:
    """Where the derived STM index lives (per-machine state, never committed).

    STOCKROOM_STM_INDEX overrides for tests/portable installs (mirrors
    STOCKROOM_CONFIG_DIR); otherwise config_dir()/stm/index.sqlite.
    """
    override = os.environ.get("STOCKROOM_STM_INDEX")
    if override:
        return Path(override)
    return config_dir() / "stm" / "index.sqlite"


def _is_device_xml(path: Path) -> bool:
    """True when path's root element is <Mcu> - a real per-device pinout XML,
    not an auxiliary CubeMX database file. The real all-families source tree
    also carries non-device XML alongside the device files (confirmed this
    session: compatibility.xml and rules.xml both have a <rules> root, not
    <Mcu>) - excluding by filename alone (just "families.xml") is not enough;
    a bare glob("*.xml") would otherwise feed these through parse_mcu_xml as if
    they were devices, producing garbage zero-pin/blank-family mcu rows that
    then trip the self-audit gate for the wrong reason. Uses iterparse (stops
    after the first start event) so this is a cheap tag peek, not a full parse.
    """
    try:
        for _, el in ET.iterparse(path, events=("start",)):
            return el.tag.rsplit("}", 1)[-1] == "Mcu"
    except (ET.ParseError, OSError):
        return False
    return False


def has_device_xml(source_dir: Path) -> bool:
    """Whether ``source_dir`` contains at least one real CubeMX device XML.

    A directory, or even a directory containing auxiliary CubeMX XML, is not a usable source.
    Keep this short-circuiting predicate shared by discovery and the status API so the UI never
    calls an empty folder authoritative and destroys a previously working derived index.
    """

    source_dir = Path(source_dir)
    try:
        if not source_dir.is_dir():
            return False
        return any(
            path.name != "families.xml" and _is_device_xml(path)
            for path in source_dir.glob("*.xml")
            if path.is_file()
        )
    except OSError:
        return False


def normalize_cubemx_source(selected: Path) -> Path:
    """Resolve a person-selected CubeMX folder to the device-XML directory it owns.

    The native picker cannot reasonably expect a person to know CubeMX's internal ``db/mcu``
    layout. Accept either that data directory itself or the application install root, preferring
    the selected folder when it is already usable. An unrecognized selection is returned unchanged
    so status can name it honestly and the build can reject it without touching an existing index.
    """

    selected = Path(selected)
    if has_device_xml(selected):
        return selected
    for nested in (selected / "mcu", selected / "db" / "mcu"):
        if has_device_xml(nested):
            return nested
    return selected


def device_xml_files(source_dir: Path) -> list[Path]:
    """Every real per-device CubeMX XML under source_dir, sorted: excludes
    families.xml by name (mirrors Hardware's build_database family_prefix skip)
    AND any other non-<Mcu>-root auxiliary XML (compatibility.xml, rules.xml,
    ...). The single shared definition of "a device XML" - StmIndex.build,
    check_availability, and source_sha256 all walk exactly this set, so
    device_xml_count/source_sha256/the actual ingest loop can never silently
    disagree about what counts as a device.
    """
    source_dir = Path(source_dir)
    candidates = sorted(p for p in source_dir.glob("*.xml") if p.name != "families.xml")
    return [p for p in candidates if _is_device_xml(p)]


def source_sha256(source_dir: Path) -> str:
    """Content identity of the CubeMX source: sha256 over sorted (name, bytes)
    of every device XML (see device_xml_files).

    Shared by StmIndex.build (skip-rebuild on an unchanged source) and
    check_availability, so both walk the exact same file set the same way.
    """
    h = hashlib.sha256()
    for f in device_xml_files(source_dir):
        h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


@dataclass
class AvailabilityReport:
    """DATA-01 SC1's real, code-level, re-runnable "is this an all-families
    source" check - the formal version of a one-off directory listing."""

    source_path: str
    device_xml_count: int
    family_count: int
    families: list[str] = field(default_factory=list)
    all_families: bool = False


def check_availability(source: Path) -> AvailabilityReport:
    """Count device XML (see device_xml_files) and distinct root Family
    attribute values under ``source``. all_families is True only when the
    source spans MORE than the F0-F7 six-family set - never presented as True
    for a source that merely looks like the WSL F-only fixture, regardless of
    file count.
    """
    source = Path(source)
    files = device_xml_files(source)
    families: set[str] = set()
    for f in files:
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        fam = root.get("Family", "")
        if fam:
            families.add(fam)
    family_count = len(families)
    return AvailabilityReport(
        source_path=str(source),
        device_xml_count=len(files),
        family_count=family_count,
        families=sorted(families),
        all_families=family_count > _F_ONLY_FAMILY_CEILING,
    )
