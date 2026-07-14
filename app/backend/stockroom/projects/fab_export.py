"""M7i fab-prep: produce a downloadable manufacturing bundle (gerbers + drill + placement)
from a project's .kicad_pcb via kicad-cli.

Read-only: it never mutates the board. It plots into a throwaway temp dir and zips the
result, so no export artifact is ever left in the project tree or committed. Mirrors
projects/checks.py's kicad-cli subprocess convention (CREATE_NO_WINDOW, a hard timeout, and
an honest loud failure on a missing cli / a failed run) and projects/bom_export.py's
{data, filename, content_type} download contract.

Honest completion (spec section 2.2): a missing kicad-cli, a failed plot, or an empty output
raises KiCadCliError (the API maps it to 502), NEVER a fabricated or empty zip; a board file
that is not on disk is a ValueError (400). Nothing requested is silently dropped: if the
placement file is requested and its plot fails, the whole export fails loudly.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

from stockroom.kicad.errors import KiCadCliError

# CREATE_NO_WINDOW on Windows so a shelled-out kicad-cli never flashes a console window (the
# host is windowed); a harmless 0 on POSIX. Mirrors projects/checks.py.
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0

# A plot of a large board can take a while; match the checks.py DRC/ERC ceiling.
_TIMEOUT = 300

DRILL_FORMATS = ("excellon", "gerber")
POS_FORMATS = ("csv", "ascii", "gerber")
# The placement file extension kicad-cli writes per --format.
_POS_EXT = {"csv": "csv", "ascii": "pos", "gerber": "gbr"}


def build_fab_bundle(
    pcb_path,
    cli: str,
    *,
    drill_format: str = "excellon",
    drill_map: bool = True,
    include_pos: bool = True,
    pos_format: str = "csv",
    protel_ext: bool = True,
) -> dict:
    """Plot the fab set for `pcb_path` via `cli` (a kicad-cli path) and return the zipped
    bundle as {data: bytes, filename, content_type, files: [names]}.

    Raises KiCadCliError (-> 502) for a missing cli / a failed plot / an empty output, and
    ValueError (-> 400) for a board file not on disk or an unknown option. Never returns a
    fabricated or empty zip."""
    if not cli:
        raise KiCadCliError("kicad-cli was not found; install KiCad to export fab files")
    if drill_format not in DRILL_FORMATS:
        raise ValueError(f"unknown drill format: {drill_format}")
    if pos_format not in POS_FORMATS:
        raise ValueError(f"unknown placement format: {pos_format}")
    pcb = Path(pcb_path)
    if not pcb.is_file():
        raise ValueError(f"board file not found: {pcb.name}")

    with tempfile.TemporaryDirectory(prefix="stockroom-fab-") as tmp:
        out = Path(tmp)
        stem = pcb.stem

        # Gerbers (+ the .gbrjob job file kicad-cli emits alongside them). -o is a directory.
        gerbers = [cli, "pcb", "export", "gerbers", "-o", str(out)]
        if not protel_ext:
            gerbers.append("--no-protel-ext")
        gerbers.append(str(pcb))
        _run(gerbers)

        # Drill files. -o is a directory and kicad-cli wants a trailing separator.
        drill = [cli, "pcb", "export", "drill", "-o", str(out) + os.sep, "--format", drill_format]
        if drill_map:
            drill.append("--generate-map")
        drill.append(str(pcb))
        _run(drill)

        # Placement / centroid file for assembly. -o is a FILE, not a directory.
        if include_pos:
            pos_out = out / f"{stem}-pos.{_POS_EXT[pos_format]}"
            _run([cli, "pcb", "export", "pos", "-o", str(pos_out),
                  "--format", pos_format, str(pcb)])

        files = sorted(p for p in out.iterdir() if p.is_file())
        if not files:
            raise KiCadCliError("kicad-cli produced no fab files")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, arcname=f.name)
        return {
            "data": buf.getvalue(),
            "filename": f"{stem}-fab.zip",
            "content_type": "application/zip",
            "files": [f.name for f in files],
        }


def _run(cmd: list) -> None:
    """Run one kicad-cli plot command, raising KiCadCliError on a spawn failure, a timeout,
    or a non-zero exit (never a silent partial success)."""
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, creationflags=_NO_WINDOW, timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise KiCadCliError(f"kicad-cli timed out after {_TIMEOUT}s")
    except OSError as e:
        raise KiCadCliError(str(e))
    if proc.returncode != 0:
        err = (proc.stdout or "").strip() or f"kicad-cli exited {proc.returncode}"
        raise KiCadCliError(err)
