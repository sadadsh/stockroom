"""Locate the CubeMX MCU XML source tree + the derived index path (Qt-free, stdlib-only).

The CubeMX database (ST's own STM32CubeMX install, or a synced copy of it) is the
read-only ground truth every STM32 device XML is parsed from. It is NOT bundled with
this app and NOT committed: the user (or an env var, in tests/CI) points at it.

default_cubemx_source() prefers a real all-families tree over the WSL fixture: the
fixture at ~/git/STMP/src/cubemx_db/mcu is F0-F7 only (~427 XML) and is never the
right answer for "all families" - it is a last-resort, loudly-logged fallback so a
Linux dev/CI box without the Windows-side tree can still run something.
"""

from __future__ import annotations

import hashlib
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.store.machine_config import config_dir

logger = logging.getLogger(__name__)

# The F0-F7 families alone (Hardware's whole prior scope) are exactly six:
# STM32F0, F1, F2, F3, F4, F7 (confirmed against legacy/tools/stm32_authority.py's
# FAMILY_ELECTRICAL/BOOTLOADER_PINS keys). A source reporting strictly this set
# (or fewer) is F-only by construction, never "all families" - the real
# all-families source spans ~20+ family lines (confirmed 28 distinct root
# Family values against the real Windows-side source this session).
_F_ONLY_FAMILY_CEILING = 6

# The two confirmed Windows-side all-families candidates (verified 2026-07-23: each
# reports 2,136 device XML, spanning every STM32 family CubeMX ships). Order: the
# synced STMP copy first (stable, versioned), then the live CubeMX install.
_WINDOWS_CANDIDATES = (
    "/mnt/c/Users/Sadad Haidari/STMP/cubemx_db/mcu",
    "/mnt/c/Users/Sadad Haidari/AppData/Local/Programs/STM32CubeMX/db/mcu",
)
# The WSL-native fixture: F0-F7 only (~427 XML), a test/dev fallback, never
# presented as "all families" (DATA-01's whole point).
_FIXTURE_FALLBACK = Path.home() / "git" / "STMP" / "src" / "cubemx_db" / "mcu"


def default_cubemx_source() -> Path | None:
    """Locate the CubeMX MCU XML directory, or None if nothing is found.

    MachineConfig.stm_cubemx_source (the settings-page-less, PATCH /api/settings
    -settable override, Phase 3 API-02) wins outright when set and valid.
    Otherwise STM32_CUBEMX (or the legacy HWKIT_CUBEMX) wins when set and valid.
    Otherwise the confirmed Windows-side all-families candidates are tried first;
    only if neither exists does this fall back to the WSL F-only fixture, with a
    loud warning log line so the fallback is never silently mistaken for coverage
    of every family.
    """
    from stockroom.store.machine_config import MachineConfig

    configured = (MachineConfig.load().stm_cubemx_source or "").strip()
    if configured and Path(configured).is_dir():
        return Path(configured)
    env = os.environ.get("STM32_CUBEMX") or os.environ.get("HWKIT_CUBEMX")
    if env and Path(env).is_dir():
        return Path(env)
    for candidate in _WINDOWS_CANDIDATES:
        c = Path(candidate)
        if c.is_dir() and any(c.glob("*.xml")):
            return c
    if _FIXTURE_FALLBACK.is_dir() and any(_FIXTURE_FALLBACK.glob("*.xml")):
        logger.warning(
            "STM32 CubeMX source: falling back to the WSL F-only fixture at %s "
            "(F0-F7 only, ~427 device XML). This is NOT an all-families source - "
            "point STM32_CUBEMX at the real CubeMX mcu/ tree for full coverage.",
            _FIXTURE_FALLBACK,
        )
        return _FIXTURE_FALLBACK
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
    except ET.ParseError:
        return False
    return False


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
