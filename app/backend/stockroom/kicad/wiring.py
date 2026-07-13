"""Wire Stockroom's active profile into KiCad: SR_LIB variable + lib-table rows.

Runs on first setup and on every profile switch. Idempotent, scoped, safe,
aware (spec section 4): re-running changes nothing; it never disturbs
non-Stockroom rows; it backs up KiCad's own config before touching it; and it
reports when a running KiCad means a restart is needed for the new rows to load.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.common_json import write_env_var
from stockroom.kicad.config import detect_running_kicad
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
        # 1. category libraries on disk
        self._ensure_category_libs(profile, report)

        # 2. SR_LIB points at the active profile folder (absolute)
        sr_value = str(profile.root.resolve())
        report.sr_lib_value = sr_value
        write_env_var(self.kicad_dir / "kicad_common.json", _SR_LIB, sr_value)

        # 3. register every category in both global tables (idempotent append)
        sym_path = self.kicad_dir / "sym-lib-table"
        fp_path = self.kicad_dir / "fp-lib-table"
        sym_table = self._load_or_new(sym_path, "sym_lib_table")
        fp_table = self._load_or_new(fp_path, "fp_lib_table")
        for cat in CATEGORIES:
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

        # 4. aware: a running KiCad must restart to load table changes
        report.kicad_running = bool(self._running_detector())
        made_changes = (
            report.symbol_rows_added or report.footprint_rows_added or report.libs_created
        )
        report.restart_needed = report.kicad_running and bool(made_changes)
        return report
