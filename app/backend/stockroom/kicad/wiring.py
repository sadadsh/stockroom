"""Wire Stockroom's active profile into KiCad: SR_LIB variable + lib-table rows.

Runs on first setup and on every profile switch. Idempotent, scoped, safe,
aware (spec section 4): re-running changes nothing; it never disturbs
non-Stockroom rows; it backs up KiCad's own config before touching it; and it
reports when a running KiCad means a restart is needed for the new rows to load.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.common_json import write_env_var
from stockroom.kicad.config import detect_kicad_version, detect_running_kicad
from stockroom.kicad.lib_table import LibTable
from stockroom.model.category import (
    CATEGORIES,
    category_footprint_lib,
    category_nickname,
    category_symbol_lib,
)
from stockroom.store.profile import Profile

_SR_LIB = "SR_LIB"


@dataclass
class WiringReport:
    sr_lib_value: str = ""
    categories_registered: list[str] = field(default_factory=list)
    symbol_rows_added: int = 0
    footprint_rows_added: int = 0
    libs_created: list[str] = field(default_factory=list)
    kicad_running: bool = False
    restart_needed: bool = False
    # auto_wire outcomes: why wiring was not attempted / what failed mid-way.
    # Both empty on a fully applied wiring.
    skipped: str = ""
    error: str = ""


class KiCadWiring:
    def __init__(self, kicad_dir: Path, cli=None, running_detector=detect_running_kicad):
        self.kicad_dir = Path(kicad_dir)
        self.cli = cli
        self._running_detector = running_detector

    def _ensure_category_libs(self, profile: Profile, report: WiringReport) -> None:
        lib = profile.library
        lib.symbols_dir.mkdir(parents=True, exist_ok=True)
        lib.footprints_dir.mkdir(parents=True, exist_ok=True)
        for cat in CATEGORIES:
            sym_path = lib.symbol_lib_path(cat)
            if not sym_path.exists():
                if self.cli is None:
                    raise ValueError(
                        f"kicad-cli is required to create category library {sym_path.name}"
                    )
                create_empty_symbol_lib(self.cli, sym_path)
                report.libs_created.append(sym_path.name)
            ensure_footprint_lib(lib.footprint_lib_path(cat))

    def _load_or_new(self, path: Path, kind: str) -> LibTable:
        return LibTable.load(path) if path.exists() else LibTable.new(kind)

    def apply(self, profile: Profile) -> WiringReport:
        report = WiringReport()
        # KiCad installed but never run: its version config dir does not exist yet
        self.kicad_dir.mkdir(parents=True, exist_ok=True)

        # 1. SR_LIB points at the active profile folder (absolute). FIRST, so a
        # switch on a machine whose kicad-cli is missing still repoints KiCad at
        # the right library before the category-lib step can fail.
        sr_value = str(profile.root.resolve())
        report.sr_lib_value = sr_value
        sr_changed = write_env_var(self.kicad_dir / "kicad_common.json", _SR_LIB, sr_value)

        # 2. register categories in both global tables (idempotent append), but only
        # those whose symbol lib exists or can be created: a row pointing at a file
        # that will not exist leaves KiCad showing a broken library per category.
        can_create = self.cli is not None and getattr(self.cli, "available", True)
        sym_path = self.kicad_dir / "sym-lib-table"
        fp_path = self.kicad_dir / "fp-lib-table"
        sym_table = self._load_or_new(sym_path, "sym_lib_table")
        fp_table = self._load_or_new(fp_path, "fp_lib_table")
        for cat in CATEGORIES:
            if not (profile.library.symbol_lib_path(cat).exists() or can_create):
                continue
            nickname = category_nickname(cat)
            if sym_table.append_kicad_lib(
                nickname,
                f"${{{_SR_LIB}}}/symbols/{category_symbol_lib(cat)}",
                f"Stockroom {cat}",
            ):
                report.symbol_rows_added += 1
            if fp_table.append_kicad_lib(
                nickname,
                f"${{{_SR_LIB}}}/footprints/{category_footprint_lib(cat)}",
                f"Stockroom {cat}",
            ):
                report.footprint_rows_added += 1
            report.categories_registered.append(cat)
        sym_table.save(sym_path)
        fp_table.save(fp_path)

        # 3. category libraries on disk (LAST: the only step that needs kicad-cli)
        self._ensure_category_libs(profile, report)

        # 4. aware: a running KiCad must restart to pick up table changes AND an
        # SR_LIB repoint (env vars are read at startup) - the switch scenario is
        # exactly an SR_LIB-only change on an already-wired machine.
        report.kicad_running = bool(self._running_detector())
        made_changes = (
            sr_changed
            or report.symbol_rows_added
            or report.footprint_rows_added
            or report.libs_created
        )
        report.restart_needed = report.kicad_running and bool(made_changes)
        return report


def kicad_present(kicad_dir: Path, cli=None) -> bool:
    """Evidence that KiCad exists on this machine: its CLI was discovered, or its
    config dir (or the version-parent base, e.g. ~/.config/kicad) exists."""
    if cli is not None and getattr(cli, "available", False):
        return True
    kdir = Path(kicad_dir)
    try:
        return kdir.is_dir() or kdir.parent.is_dir()
    except OSError:
        return False


def _cli_version(cli) -> str | None:
    """major.minor of the installed kicad-cli ("9.0.2-release" -> "9.0"), or None."""
    if cli is None or not getattr(cli, "available", False):
        return None
    try:
        text = str(cli.version())
    except Exception:  # noqa: BLE001 - version discovery is best-effort
        return None
    m = re.match(r"\s*(\d+)\.(\d+)", text)
    return f"{m.group(1)}.{m.group(2)}" if m else None


def auto_wire(
    kicad_dir: Path,
    profile: Profile,
    cli=None,
    running_detector=detect_running_kicad,
    explicit: bool = False,
) -> WiringReport:
    """The never-raises wiring used on boot and on every profile/library switch, so
    KiCad always points at the active library without a manual Doctor click. Skips
    honestly when KiCad is not on this machine (never invents a config tree for it);
    captures a mid-wiring failure into the report instead of breaking the caller.
    explicit=True means the dir was user-chosen (an override) and is wired as-is;
    otherwise a missing dir is re-derived from the INSTALLED KiCad's version so a
    fabricated default (10.0 on a KiCad 9 machine) never poisons autodetection."""
    kdir = Path(kicad_dir)
    if not kicad_present(kdir, cli):
        report = WiringReport()
        report.skipped = "KiCad was not found on this machine (no CLI, no config dir)"
        return report
    if not explicit and not kdir.is_dir():
        detected = detect_kicad_version(kdir.parent)
        if detected:
            kdir = kdir.parent / detected
        else:
            version = _cli_version(cli)
            if version is None:
                report = WiringReport()
                report.skipped = (
                    "KiCad has no config dir yet and its version could not be "
                    "determined, so nothing was wired"
                )
                return report
            kdir = kdir.parent / version
    try:
        return KiCadWiring(kdir, cli=cli, running_detector=running_detector).apply(profile)
    except Exception as exc:  # noqa: BLE001 - boot/switch must survive any wiring failure
        report = WiringReport()
        report.error = f"{type(exc).__name__}: {exc}"
        return report
