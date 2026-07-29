"""Native fixture evidence for the collaboration prototype.

The Git/session tests prove preservation and synchronization. These checks prove
that the pinned KiCad fixture is accepted by the installed native tool without
rewriting source. Altium's checked-in AD26 SchDoc readback remains covered by
``tests/backend/altium/test_schdoc.py``; a real paired PcbDoc mutation fixture is a
separate Phase 0 gate and is not simulated here.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from stockroom.kicad.cli import find_kicad_cli
from stockroom.mutation.project_ops import ProjectOps
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo


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
    schematic_svg = tmp_path / "schematic-svg"
    board_png = tmp_path / "board.png"
    _run(binary, "sch", "export", "bom", "--output", str(bom), str(schematic))
    _run(binary, "sch", "erc", "--format", "json", "--output", str(erc), str(schematic))
    _run(binary, "pcb", "drc", "--format", "json", "--output", str(drc), str(board))
    _run(binary, "sch", "export", "svg", "--output", str(schematic_svg), str(schematic))
    _run(
        binary,
        "pcb",
        "render",
        "--output",
        str(board_png),
        "--width",
        "640",
        "--height",
        "480",
        "--quality",
        "basic",
        str(board),
    )

    assert bom.stat().st_size > 0
    assert erc.stat().st_size > 0
    assert drc.stat().st_size > 0
    assert next(schematic_svg.glob("*.svg")).stat().st_size > 0
    assert board_png.stat().st_size > 0
    assert _digest(sources) == before


def test_stockroom_edits_kicad_bom_field_then_native_cli_reopens_it(tmp_path):
    binary = find_kicad_cli()
    if binary is None:
        pytest.skip("kicad-cli is not installed")
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "kicad"
    project_root = tmp_path / "project"
    project_root.mkdir()
    for source in fixtures.glob("minimal.kicad_*"):
        shutil.copyfile(source, project_root / source.name)

    project_repo = GitRepo(project_root)
    project_repo.init()
    project_sources = sorted(project_root.glob("minimal.kicad_*"))
    project_repo.commit("Seed native KiCad proof", project_sources)

    library_root = tmp_path / "library"
    library_root.mkdir()
    library_repo = GitRepo(library_root)
    library_repo.init()
    seed = library_root / "seed.txt"
    seed.write_text("seed", encoding="utf-8")
    library_repo.commit("Seed library", [seed])
    store = ProjectStore(library_root / ".projects", library_repo)
    ops = ProjectOps(store)
    record = ops.register(project_root, eda="kicad")

    result = ops.set_fields(
        record.id,
        [{"ref": "R1", "field": "MPN", "value": "STOCKROOM-NATIVE-PROOF"}],
    )
    assert result["committed"]
    assert result["components"] == 1
    assert result["fields"] == 1

    reopened = ProjectOps(ProjectStore(library_root / ".projects", library_repo))
    rows = {row["ref"]: row for row in reopened.fields(record.id)["rows"]}
    assert rows["R1"]["fields"]["MPN"] == "STOCKROOM-NATIVE-PROOF"

    bom = tmp_path / "edited-bom.csv"
    schematic_svg = tmp_path / "edited-schematic-svg"
    schematic = project_root / "minimal.kicad_sch"
    _run(
        binary,
        "sch",
        "export",
        "bom",
        "--fields",
        "Reference,Value,MPN",
        "--output",
        str(bom),
        str(schematic),
    )
    _run(binary, "sch", "export", "svg", "--output", str(schematic_svg), str(schematic))
    assert bom.stat().st_size > 0
    assert next(schematic_svg.glob("*.svg")).stat().st_size > 0
    assert project_repo.is_clean(project_sources)
