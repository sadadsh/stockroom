"""Thin wrapper over the kicad-cli binary (KiCad 10)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from stockroom.kicad.errors import KiCadCliError


class KiCadCli:
    def __init__(self, binary: str | None = None):
        resolved = shutil.which(binary or "kicad-cli")
        if resolved is None:
            raise KiCadCliError(f"kicad-cli not found: {binary or 'kicad-cli'}")
        self.binary = resolved

    def _run(self, *args: str) -> str:
        proc = subprocess.run(
            [self.binary, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise KiCadCliError(f"kicad-cli {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    def version(self) -> str:
        return self._run("version").strip()

    def sym_upgrade(self, src: Path, dst: Path) -> None:
        self._run("sym", "upgrade", "-o", str(Path(dst)), str(Path(src)))

    def fp_upgrade(self, pretty_dir: Path) -> None:
        """Upgrade every footprint in a .pretty directory to the current KiCad
        format, in place. A no-op-equivalent rewrite for already-current
        footprints; normalizes older and foreign-origin footprints."""
        self._run("fp", "upgrade", str(Path(pretty_dir)))

    def sym_export_svg(
        self, lib: Path, symbol: str, out_dir: Path, *, black_and_white: bool = False
    ) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        args = ["sym", "export", "svg", "-o", str(out_dir), "-s", symbol]
        if black_and_white:
            args.append("--black-and-white")
        args.append(str(Path(lib)))
        self._run(*args)
        return sorted(out_dir.glob("*.svg"))

    def fp_export_svg(
        self,
        pretty_dir: Path,
        footprint: str,
        out_dir: Path,
        layers: str = "F.Cu,F.SilkS,F.Fab",
    ) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # kicad-cli requires the .pretty DIRECTORY plus --fp, never a bare .kicad_mod.
        self._run(
            "fp", "export", "svg",
            "-o", str(out_dir),
            "--fp", footprint,
            "-l", layers,
            str(Path(pretty_dir)),
        )
        svgs = sorted(out_dir.glob("*.svg"))
        if not svgs:
            raise KiCadCliError(f"no SVG produced for footprint {footprint}")
        return svgs[0]
