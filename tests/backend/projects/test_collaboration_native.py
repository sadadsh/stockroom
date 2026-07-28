"""Native fixture evidence for the collaboration prototype.

The Git/session tests prove preservation and synchronization. These checks prove
that the pinned KiCad fixture is accepted by the installed native tool without
rewriting source. Altium's checked-in AD26 SchDoc readback remains covered by
``tests/backend/altium/test_schdoc.py``; a real paired PcbDoc mutation fixture is a
separate Phase 0 gate and is not simulated here.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from stockroom.kicad.cli import find_kicad_cli


def _digest(paths: list[Path]) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _run(binary: str, *args: str) -> None:
    proc = subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_real_kicad_fixture_exports_bom_and_checks_without_source_changes(tmp_path):
    binary = find_kicad_cli()
    if binary is None:
        pytest.skip("kicad-cli is not installed")
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "kicad"
    project = fixtures / "minimal.kicad_pro"
    schematic = fixtures / "minimal.kicad_sch"
    board = fixtures / "minimal.kicad_pcb"
    sources = [project, schematic, board]
    before = _digest(sources)

    bom = tmp_path / "bom.csv"
    erc = tmp_path / "erc.json"
    drc = tmp_path / "drc.json"
    _run(binary, "sch", "export", "bom", "--output", str(bom), str(schematic))
    _run(binary, "sch", "erc", "--format", "json", "--output", str(erc), str(schematic))
    _run(binary, "pcb", "drc", "--format", "json", "--output", str(drc), str(board))

    assert bom.stat().st_size > 0
    assert erc.stat().st_size > 0
    assert drc.stat().st_size > 0
    assert _digest(sources) == before
