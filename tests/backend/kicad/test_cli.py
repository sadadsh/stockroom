
import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.errors import KiCadCliError
from tests.backend.conftest import requires_kicad_cli


def test_missing_binary_is_non_fatal_but_commands_raise(monkeypatch):
    # Construction MUST NOT raise when kicad-cli is absent (the app has to start
    # without it); a clear error surfaces only when a command is actually invoked.
    import stockroom.kicad.cli as cli_mod

    monkeypatch.setattr(cli_mod, "find_kicad_cli", lambda binary=None: None)
    cli = KiCadCli(binary="definitely-not-kicad-cli-xyz")
    assert cli.available is False
    with pytest.raises(KiCadCliError):
        cli.version()


@requires_kicad_cli
def test_version_reports_10():
    assert KiCadCli().version().startswith("10.")


@requires_kicad_cli
def test_sym_upgrade_produces_v10_stamp(tmp_path, fixtures_dir):
    dst = tmp_path / "upgraded.kicad_sym"
    KiCadCli().sym_upgrade(fixtures_dir / "legacy.lib", dst)
    text = dst.read_text(encoding="utf-8")
    assert "kicad_symbol_lib" in text
    assert "(version 2025" in text or "(version 2024" in text


@requires_kicad_cli
def test_sym_export_svg_writes_file(tmp_path, fixtures_dir):
    out = KiCadCli().sym_export_svg(fixtures_dir / "minimal.kicad_sym", "R_0603", tmp_path)
    assert out and all(p.suffix == ".svg" and p.exists() for p in out)


@requires_kicad_cli
def test_fp_upgrade_rewrites_footprint_to_current_format(tmp_path, fixtures_dir):
    import shutil

    from stockroom.kicad.cli import KiCadCli

    cli = KiCadCli()
    pretty = tmp_path / "in.pretty"
    pretty.mkdir()
    # one_footprint.kicad_mod carries an older (version 20240108) stamp.
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", pretty / "fp.kicad_mod")
    cli.fp_upgrade(pretty)
    # still a valid, parseable footprint after upgrade
    from stockroom.kicad.footprint import Footprint
    fp = Footprint.load(pretty / "fp.kicad_mod")
    assert fp.name  # non-empty name survives the upgrade


# --- Footprint fidelity: the preview must show what the PCB editor shows. -----------------------
# Owner, 2026-07-26: "the FOOTPRINT must show the COURTYARD and everything the PCB editor would
# show, exactly as it would", and separately "the 2D footprint preview has NO PAD NUMBERS".
#
# This REVERSES part of 58cc9bc, which dropped the courtyard on the grounds that it is a
# documentation layer that never gets printed. True for a fabrication view, and the wrong goal here:
# the owner is checking a footprint against a datasheet, which is what the editor view is for.

class _RecordingRunner:
    """Captures the argv kicad-cli would have been given, and makes the output file appear."""

    def __init__(self, out_dir):
        self.calls: list[list[str]] = []
        self._out = out_dir

    def __call__(self, *args):
        self.calls.append(list(args))
        self._out.mkdir(parents=True, exist_ok=True)
        (self._out / "fp.svg").write_text("<svg/>", encoding="utf-8")

        class _R:
            stdout = ""
            stderr = ""
        return _R()


def _export(tmp_path, **kw):
    from stockroom.kicad.cli import KiCadCli

    cli = KiCadCli()
    out = tmp_path / "out"
    rec = _RecordingRunner(out)
    cli._run = rec  # type: ignore[method-assign]
    cli.fp_export_svg(tmp_path / "SR-ICs.pretty", "SOIC-8", out, **kw)
    return rec.calls[0]


def test_the_footprint_export_includes_the_courtyard(tmp_path):
    argv = _export(tmp_path)
    layers = argv[argv.index("-l") + 1]
    assert "F.CrtYd" in layers, layers


def test_the_footprint_export_keeps_copper_silk_and_fab(tmp_path):
    """The courtyard is ADDED, never swapped in: dropping any of these would trade one missing
    layer for another."""
    argv = _export(tmp_path)
    layers = argv[argv.index("-l") + 1]
    for layer in ("F.Cu", "F.SilkS", "F.Fab"):
        assert layer in layers, layers


def test_the_footprint_export_asks_for_pad_numbers(tmp_path):
    """`--sketch-pads-on-fab-layers` is kicad-cli's own switch for "pad outlines AND THEIR NUMBERS
    on the fab layers" (read from `kicad-cli fp export svg --help`, not guessed). F.Fab is already
    in the layer list, so this is what puts the numbers on the preview."""
    argv = _export(tmp_path)
    assert "--sketch-pads-on-fab-layers" in argv, argv


def test_an_explicit_layer_list_still_wins(tmp_path):
    """Callers that ask for a specific set get exactly it - the preview endpoints pass their own."""
    argv = _export(tmp_path, layers="B.Cu")
    assert argv[argv.index("-l") + 1] == "B.Cu"
