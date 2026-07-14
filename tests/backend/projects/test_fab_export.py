"""M7i fab-prep: build a downloadable manufacturing bundle (gerbers + drill + placement)
from a project's .kicad_pcb via kicad-cli.

The subprocess runner is exercised with kicad-cli faked (monkeypatched subprocess.run),
exactly like test_checks.py, so the honest-completion guards stay deterministic and
cross-platform: a missing cli / a failed plot / an empty output is NEVER a fabricated or
empty zip. One real-cli smoke test (guarded by shutil.which) proves the actual flags.
"""

from __future__ import annotations

import io
import shutil
import types
import zipfile
from pathlib import Path

import pytest

from stockroom.kicad.errors import KiCadCliError
from stockroom.projects import fab_export


# ---- a faked kicad-cli ------------------------------------------------------


def _fake_cli(monkeypatch, *, record=None, fail=False, write=True):
    """Fake subprocess.run: recognise the gerbers / drill / pos subcommand from the argv,
    write realistic output files into the run's -o target (unless write=False), and record
    each argv (unless record is None). fail=True returns a non-zero exit with no files."""

    def fake_run(cmd, **kw):
        if record is not None:
            record.append(list(cmd))
        if fail:
            return types.SimpleNamespace(returncode=1, stdout="could not open board")
        if write:
            _emit(cmd)
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(fab_export.subprocess, "run", fake_run)


def _emit(cmd):
    """Materialise the files the real kicad-cli would write for this subcommand."""
    sub = cmd[cmd.index("export") + 1]  # gerbers | drill | pos
    src = Path(cmd[-1])
    stem = src.stem
    out = _out_value(cmd)
    if sub == "gerbers":
        d = Path(out)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}-F_Cu.gtl").write_text("G04 front copper*", encoding="utf-8")
        (d / f"{stem}-B_Cu.gbl").write_text("G04 back copper*", encoding="utf-8")
        (d / f"{stem}-Edge_Cuts.gm1").write_text("G04 edge*", encoding="utf-8")
        (d / f"{stem}-job.gbrjob").write_text("{}", encoding="utf-8")
    elif sub == "drill":
        d = Path(out)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}.drl").write_text("M48", encoding="utf-8")
        if "--generate-map" in cmd:
            (d / f"{stem}-drl_map.pdf").write_bytes(b"%PDF-1.5")
    elif sub == "pos":
        f = Path(out)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("Ref,Val,Package,PosX,PosY,Rot,Side\n", encoding="utf-8")


def _out_value(cmd):
    for flag in ("-o", "--output"):
        if flag in cmd:
            return cmd[cmd.index(flag) + 1]
    raise AssertionError(f"no -o in {cmd}")


def _board(tmp_path) -> Path:
    p = tmp_path / "board.kicad_pcb"
    p.write_text("(kicad_pcb)", encoding="utf-8")
    return p


def _names(bundle) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(bundle["data"])) as z:
        return sorted(z.namelist())


# ---- the honest-completion guards -------------------------------------------


def test_no_cli_raises_kicadcli_error_not_a_fabricated_zip(tmp_path):
    with pytest.raises(KiCadCliError) as e:
        fab_export.build_fab_bundle(_board(tmp_path), "")
    assert "not found" in str(e.value).lower()


def test_a_failed_plot_raises_not_an_empty_zip(tmp_path, monkeypatch):
    _fake_cli(monkeypatch, fail=True)
    with pytest.raises(KiCadCliError) as e:
        fab_export.build_fab_bundle(_board(tmp_path), "/fake/kicad-cli")
    assert "could not open board" in str(e.value)


def test_no_files_produced_raises_not_an_empty_zip(tmp_path, monkeypatch):
    # kicad-cli exits 0 but writes nothing (a crash / bad board): never a valid empty bundle.
    _fake_cli(monkeypatch, write=False)
    with pytest.raises(KiCadCliError) as e:
        fab_export.build_fab_bundle(_board(tmp_path), "/fake/kicad-cli")
    assert "no fab files" in str(e.value).lower()


def test_spawn_failure_raises_kicadcli_error(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        raise OSError("no such executable")

    monkeypatch.setattr(fab_export.subprocess, "run", boom)
    with pytest.raises(KiCadCliError) as e:
        fab_export.build_fab_bundle(_board(tmp_path), "/fake/kicad-cli")
    assert "no such executable" in str(e.value)


def test_missing_board_file_is_a_value_error_400_not_502(tmp_path, monkeypatch):
    _fake_cli(monkeypatch)
    with pytest.raises(ValueError):
        fab_export.build_fab_bundle(tmp_path / "gone.kicad_pcb", "/fake/kicad-cli")


def test_rejects_unknown_drill_format(tmp_path, monkeypatch):
    _fake_cli(monkeypatch)
    with pytest.raises(ValueError):
        fab_export.build_fab_bundle(_board(tmp_path), "/c", drill_format="rout")


def test_rejects_unknown_pos_format(tmp_path, monkeypatch):
    _fake_cli(monkeypatch)
    with pytest.raises(ValueError):
        fab_export.build_fab_bundle(_board(tmp_path), "/c", pos_format="xml")


# ---- the produced bundle ----------------------------------------------------


def test_zips_the_gerber_drill_and_placement_files(tmp_path, monkeypatch):
    _fake_cli(monkeypatch)
    bundle = fab_export.build_fab_bundle(_board(tmp_path), "/fake/kicad-cli")
    assert bundle["filename"] == "board-fab.zip"
    assert bundle["content_type"] == "application/zip"
    names = _names(bundle)
    assert "board-F_Cu.gtl" in names and "board-B_Cu.gbl" in names
    assert "board-job.gbrjob" in names
    assert "board.drl" in names and "board-drl_map.pdf" in names
    assert "board-pos.csv" in names
    # the returned files list mirrors the zip
    assert sorted(bundle["files"]) == names


def test_include_pos_false_omits_the_placement_file(tmp_path, monkeypatch):
    record = []
    _fake_cli(monkeypatch, record=record)
    bundle = fab_export.build_fab_bundle(_board(tmp_path), "/c", include_pos=False)
    assert not any("pos" in cmd for cmd in record)  # the pos subcommand never ran
    assert not any(n.endswith("pos.csv") for n in _names(bundle))


def test_drill_map_false_omits_the_map(tmp_path, monkeypatch):
    _fake_cli(monkeypatch)
    bundle = fab_export.build_fab_bundle(_board(tmp_path), "/c", drill_map=False)
    assert not any(n.endswith("drl_map.pdf") for n in _names(bundle))


def test_drill_format_gerber_is_passed_through(tmp_path, monkeypatch):
    record = []
    _fake_cli(monkeypatch, record=record)
    fab_export.build_fab_bundle(_board(tmp_path), "/c", drill_format="gerber")
    drill = next(cmd for cmd in record if "drill" in cmd)
    assert drill[drill.index("--format") + 1] == "gerber"


def test_protel_ext_false_passes_no_protel_ext(tmp_path, monkeypatch):
    record = []
    _fake_cli(monkeypatch, record=record)
    fab_export.build_fab_bundle(_board(tmp_path), "/c", protel_ext=False)
    gerbers = next(cmd for cmd in record if "gerbers" in cmd)
    assert "--no-protel-ext" in gerbers


def test_protel_ext_true_default_does_not_pass_no_protel_ext(tmp_path, monkeypatch):
    record = []
    _fake_cli(monkeypatch, record=record)
    fab_export.build_fab_bundle(_board(tmp_path), "/c")
    gerbers = next(cmd for cmd in record if "gerbers" in cmd)
    assert "--no-protel-ext" not in gerbers


def test_pos_gerber_emits_two_sided_files_not_a_broken_side_both(tmp_path, monkeypatch):
    # kicad-cli rejects --side both for Gerber placement, so the gerber format must plot front
    # and back separately; a single default run would always 502 and make the option a stub.
    record = []
    _fake_cli(monkeypatch, record=record)
    bundle = fab_export.build_fab_bundle(_board(tmp_path), "/c", pos_format="gerber")
    pos_runs = [cmd for cmd in record if "pos" in cmd]
    assert len(pos_runs) == 2
    sides = {cmd[cmd.index("--side") + 1] for cmd in pos_runs}
    assert sides == {"front", "back"}
    assert all("both" not in cmd for cmd in pos_runs)
    names = _names(bundle)
    assert "board-pos-front.gbr" in names and "board-pos-back.gbr" in names


def test_run_decodes_kicad_cli_output_as_utf8_replace(tmp_path, monkeypatch):
    # kicad-cli emits UTF-8; on a non-English Windows the OS default codec (cp1252) would raise
    # UnicodeDecodeError on its output. Pin encoding=utf-8/errors=replace (checks.py convention)
    # so a decode never breaks a successful export nor mislabels a failure.
    seen = {}

    def capture(cmd, **kw):
        seen.update(kw)
        _emit(cmd)
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(fab_export.subprocess, "run", capture)
    fab_export.build_fab_bundle(_board(tmp_path), "/c")
    assert seen.get("encoding") == "utf-8"
    assert seen.get("errors") == "replace"


def test_a_decode_error_is_a_kicadcli_error_not_a_500(tmp_path, monkeypatch):
    # Belt and suspenders: even a surprise decode/other error from the spawn is a labeled
    # KiCadCliError (-> 502), never an unmapped 500 / a ValueError mislabeled 400.
    def boom(cmd, **kw):
        raise UnicodeDecodeError("utf-8", b"\x81", 0, 1, "invalid start byte")

    monkeypatch.setattr(fab_export.subprocess, "run", boom)
    with pytest.raises(KiCadCliError):
        fab_export.build_fab_bundle(_board(tmp_path), "/fake/kicad-cli")


# ---- a real kicad-cli smoke test (skipped where the cli is absent, e.g. Windows CI) --


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed")
def test_real_cli_produces_a_gerber_drill_and_job(tmp_path):
    fixture = Path(__file__).parent.parent / "fixtures" / "kicad" / "minimal.kicad_pcb"
    board = tmp_path / "smoke.kicad_pcb"
    board.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    bundle = fab_export.build_fab_bundle(board, shutil.which("kicad-cli"))
    names = _names(bundle)
    assert any(n.endswith(".gbrjob") for n in names), names
    assert any(n.endswith(".drl") for n in names), names
    assert any(n.endswith((".gtl", ".gbl", ".gbr")) for n in names), names
    assert bundle["filename"] == "smoke-fab.zip"


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed")
def test_real_cli_leaves_the_project_tree_untouched(tmp_path):
    # READ-ONLY guarantee: kicad-cli writes a <board>.kicad_prl next to the board it opens, so a
    # naive run would drop that (and dirty a git-tracked project). The export must run against a
    # copy and leave the project dir holding ONLY the original board.
    fixture = Path(__file__).parent.parent / "fixtures" / "kicad" / "minimal.kicad_pcb"
    proj = tmp_path / "proj"
    proj.mkdir()
    board = proj / "board.kicad_pcb"
    board.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    fab_export.build_fab_bundle(board, shutil.which("kicad-cli"))
    assert [p.name for p in proj.iterdir()] == ["board.kicad_pcb"]
