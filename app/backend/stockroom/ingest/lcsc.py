"""LCSC part-number ingestion. There is no KiCad zip for LCSC/EasyEDA, so the
ecosystem standard is an API fetch and convert keyed on the Cxxxxx id. We shell
out to easyeda2kicad (kept at arm's length as a subprocess so its AGPL license
does not reach Stockroom's code) and feed the produced symbol, footprint, and 3D
model into the same staging path (spec section 5)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import DetectedSource

_LCSC_RE = re.compile(r"^C\d+$", re.IGNORECASE)


def is_lcsc_id(text: str) -> bool:
    return bool(_LCSC_RE.match(text.strip())) if text else False


def _default_runner(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise IngestError(f"easyeda2kicad failed: {proc.stderr.strip() or proc.stdout.strip()}")


def fetch_lcsc(lcsc_id: str, workdir: Path, runner=None) -> DetectedSource:
    if not is_lcsc_id(lcsc_id):
        raise IngestError(f"not an LCSC part number: {lcsc_id!r}")
    runner = runner or _default_runner
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    base = workdir / "lib"
    cmd = [
        "easyeda2kicad",
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
