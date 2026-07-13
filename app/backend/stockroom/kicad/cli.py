"""Thin wrapper over the kicad-cli binary (KiCad 10)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from stockroom.kicad.errors import KiCadCliError


def _version_key(name: str) -> tuple[int, ...]:
    """Sort key for KiCad version-named install dirs so 10.0 ranks ABOVE 9.0
    (numeric, not lexicographic — a plain string sort would pick 9.0 as 'newest')."""
    return tuple(int(p) if p.isdigit() else -1 for p in name.split("."))


def _standard_kicad_cli_paths() -> list[Path]:
    """The standard per-OS KiCad install locations, newest version first, so kicad-cli
    is found even when KiCad's installer did not add its bin/ to PATH (the common
    Windows case that crashed startup)."""
    if sys.platform.startswith("win"):
        out: list[Path] = []
        seen: set[Path] = set()
        for env in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            root = Path(base) / "KiCad"
            if root in seen or not root.is_dir():
                continue
            seen.add(root)
            vers = [d for d in root.iterdir() if d.is_dir() and d.name[:1].isdigit()]
            for ver_dir in sorted(vers, key=lambda d: _version_key(d.name), reverse=True):
                out.append(ver_dir / "bin" / "kicad-cli.exe")
        return out
    if sys.platform == "darwin":
        return [Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")]
    # linux + other unixes: PATH is the norm; a couple of common absolute fallbacks
    return [Path("/usr/bin/kicad-cli"), Path("/usr/local/bin/kicad-cli")]


def find_kicad_cli(override: str | None = None) -> str | None:
    """Locate the kicad-cli binary. Order: explicit override (a path or a name on
    PATH), then PATH, then the standard KiCad install locations for this OS. Returns
    the absolute path, or None if KiCad is not installed — the app then runs without
    previews/import and surfaces an honest error only when a KiCad op is requested."""
    if override:
        p = Path(override)
        if p.is_file():
            return str(p)
        on_path = shutil.which(override)
        if on_path:
            return on_path
    on_path = shutil.which("kicad-cli")
    if on_path:
        return on_path
    for cand in _standard_kicad_cli_paths():
        if cand.is_file():
            return str(cand)
    return None


class KiCadCli:
    def __init__(self, binary: str | None = None):
        # Non-fatal: resolve the binary via robust discovery but DO NOT raise if it is
        # absent, so the app still starts (library browse/search/mutations/sync work
        # without kicad-cli). A KiCad operation (preview/import/wiring) raises a clear
        # KiCadCliError only when actually invoked.
        self.binary = find_kicad_cli(binary)

    @property
    def available(self) -> bool:
        return self.binary is not None

    def _run(self, *args: str) -> str:
        if self.binary is None:
            raise KiCadCliError(
                "kicad-cli not found; install KiCad 10 (or set its path in settings) — "
                "symbol/footprint previews and library import need it"
            )
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
