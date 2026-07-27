"""LCSC part-number ingestion. There is no KiCad zip for LCSC/EasyEDA, so the
ecosystem standard is an API fetch and convert keyed on the Cxxxxx id. We shell
out to easyeda2kicad (kept at arm's length as a subprocess so its AGPL license
does not reach Stockroom's code) and feed the produced symbol, footprint, and 3D
model into the same staging path (spec section 5)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import DetectedSource

_LCSC_RE = re.compile(r"^C\d+$", re.IGNORECASE)


def is_lcsc_id(text: str) -> bool:
    return bool(_LCSC_RE.match(text.strip())) if text else False


def converter_command() -> str:
    """How to invoke easyeda2kicad on THIS machine.

    Beside the running interpreter first, then PATH. The Stockroom host runs from the install's
    own `.venv` (`<install>/.venv/Scripts/python.exe` on Windows), and a child process does NOT
    inherit that directory on PATH merely because the parent interpreter lives there - the venv
    would have to be activated, and the host does not activate one. A bare "easyeda2kicad" then
    raises FileNotFoundError, which the import layer degrades to "no files": a SILENT loss of
    exactly the symbols, footprints and 3D models this path exists to fetch.

    The bare name is still the fallback, so a pipx / system / Linux-CI install keeps working.
    """
    here = Path(sys.executable).parent
    for name in ("easyeda2kicad.exe", "easyeda2kicad"):
        candidate = here / name
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return "easyeda2kicad"


def _default_runner(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise IngestError(f"easyeda2kicad failed: {proc.stderr.strip() or proc.stdout.strip()}")


def fetch_lcsc(lcsc_id: str, workdir: Path, runner=None, cli=None) -> DetectedSource:
    if not is_lcsc_id(lcsc_id):
        raise IngestError(f"not an LCSC part number: {lcsc_id!r}")
    runner = runner or _default_runner
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    base = workdir / "lib"
    cmd = [
        converter_command(),
        "--full",
        f"--lcsc_id={lcsc_id.upper()}",
        "--output",
        str(base),
        "--overwrite",
    ]
    try:
        runner(cmd)
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(f"easyeda2kicad invocation failed: {exc}") from exc

    symbol = base.with_suffix(".kicad_sym")
    if not symbol.exists():
        raise IngestError(f"easyeda2kicad produced no symbol for {lcsc_id}")
    pretty = Path(str(base) + ".pretty")
    # MEASURED on the real converter (v1.0.1) and the real part C7666: it emits a KiCad 5 legacy
    # `(module ...)` footprint, which Stockroom's byte-preserving layer REFUSES outright
    # ("not a .kicad_mod file (missing footprint)"). The geometry was correct - 5 pads at 0.95 mm
    # for a SOT-23-5 - so only the dialect was wrong, and KiCad's OWN `fp upgrade` is the right
    # fix rather than a hand-rolled s-expression rewrite.
    #
    # Never fatal: no kicad-cli (Linux CI, a machine without KiCad) or an already-modern file
    # must not turn a good conversion into an error. The symbol and 3D model are unaffected.
    if cli is not None and pretty.is_dir():
        try:
            cli.fp_upgrade(pretty)
        except Exception:  # noqa: BLE001 - an un-upgradable footprint is reported downstream
            pass
    footprints = sorted(pretty.glob("*.kicad_mod")) if pretty.is_dir() else []
    shapes = Path(str(base) + ".3dshapes")
    model = None
    if shapes.is_dir():
        step = sorted(shapes.glob("*.step"))
        wrl = sorted(shapes.glob("*.wrl"))
        model = (step or wrl or [None])[0]
    return DetectedSource(
        vendor="lcsc",
        symbol_path=symbol,
        dcm_path=None,
        footprint_paths=footprints,
        model_path=model,
        datasheet_path=None,
    )
