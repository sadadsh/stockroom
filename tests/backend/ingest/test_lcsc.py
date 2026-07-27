import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.lcsc import fetch_lcsc, is_lcsc_id


def test_is_lcsc_id():
    assert is_lcsc_id("C2040")
    assert is_lcsc_id("c2040")
    assert not is_lcsc_id("TPS62130")
    assert not is_lcsc_id("C")
    assert not is_lcsc_id("")


def test_fetch_lcsc_invalid_id_raises(tmp_path):
    with pytest.raises(IngestError):
        fetch_lcsc("not-an-id", tmp_path)


def test_fetch_lcsc_locates_outputs(tmp_path):
    # A fake runner that writes the files easyeda2kicad would produce.
    def fake_runner(cmd):
        # cmd is the arg list; find the --output base
        base = None
        for a in cmd:
            if a.startswith("--output"):
                base = a.split("=", 1)[1] if "=" in a else None
        if base is None:
            base = cmd[cmd.index("--output") + 1]
        from pathlib import Path
        base = Path(base)
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".kicad_sym").write_text("(kicad_symbol_lib)")
        pretty = Path(str(base) + ".pretty")
        pretty.mkdir(parents=True, exist_ok=True)
        (pretty / "C2040.kicad_mod").write_text("(footprint)")
        shapes = Path(str(base) + ".3dshapes")
        shapes.mkdir(parents=True, exist_ok=True)
        (shapes / "C2040.wrl").write_text("wrl")
        (shapes / "C2040.step").write_text("step")

    d = fetch_lcsc("C2040", tmp_path, runner=fake_runner)
    assert d.vendor == "lcsc"
    assert d.symbol_path.suffix == ".kicad_sym"
    assert d.footprint_paths[0].name == "C2040.kicad_mod"
    assert d.model_path.name == "C2040.step"  # step preferred over wrl


def test_fetch_lcsc_runner_failure_raises(tmp_path):
    def failing_runner(cmd):
        raise RuntimeError("network down")

    with pytest.raises(IngestError):
        fetch_lcsc("C2040", tmp_path, runner=failing_runner)


def test_the_converter_is_found_beside_the_running_interpreter(tmp_path, monkeypatch):
    """The host runs from `<install>/.venv/Scripts/python.exe`, and a subprocess does NOT get
    that directory on PATH just because the interpreter lives there. Invoking a bare
    "easyeda2kicad" therefore resolves only if the venv happens to be activated - and when it
    does not, the failure is SILENT: the import degrades to "no files", which is exactly the
    outcome the whole CAD lane exists to prevent. So the executable is looked for next to
    sys.executable first, and only then left to PATH.
    """
    from stockroom.ingest import lcsc as lcsc_mod

    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    exe = scripts / "easyeda2kicad.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(lcsc_mod.sys, "executable", str(scripts / "python.exe"))

    assert lcsc_mod.converter_command() == str(exe)


def test_the_converter_falls_back_to_path_when_it_is_not_beside_the_interpreter(tmp_path, monkeypatch):
    """A normal install (pipx, a system install, Linux CI) has it on PATH and nowhere near the
    interpreter. That must keep working, so the fallback is the bare name, not a hard error."""
    from stockroom.ingest import lcsc as lcsc_mod

    monkeypatch.setattr(lcsc_mod.sys, "executable", str(tmp_path / "python"))
    assert lcsc_mod.converter_command() == "easyeda2kicad"


def test_the_converted_footprint_is_upgraded_to_the_current_kicad_format(tmp_path):
    """MEASURED, on the real converter and the real part (C7666 = SN74LVC1G08DBVR):
    easyeda2kicad v1.0.1 emits a KiCad 5 legacy `(module ...)` footprint, and Stockroom's own
    byte-preserving layer REFUSES it - `Footprint.load` raises "not a .kicad_mod file (missing
    footprint)". Every non-passive would have failed at attach.

    The geometry was fine (5 pads, 0.95 mm pitch, correct SOT-23-5); only the dialect was old.
    So the fix is KiCad's OWN upgrade path, `kicad-cli fp upgrade`, which the CLI wrapper already
    exposes - not a hand-rolled s-expression rewrite.
    """
    upgraded: list = []

    class _Cli:
        def fp_upgrade(self, pretty_dir):
            upgraded.append(pretty_dir)

    def fake_runner(cmd):
        from pathlib import Path

        base = Path(cmd[cmd.index("--output") + 1])
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".kicad_sym").write_text("(kicad_symbol_lib)", encoding="utf-8")
        pretty = Path(str(base) + ".pretty")
        pretty.mkdir(parents=True, exist_ok=True)
        (pretty / "C7666.kicad_mod").write_text("(module legacy)", encoding="utf-8")

    fetch_lcsc("C7666", tmp_path, runner=fake_runner, cli=_Cli())
    assert upgraded, "the converted .pretty must be upgraded before anything tries to parse it"
    assert upgraded[0].name.endswith(".pretty")


def test_an_upgrade_failure_does_not_lose_the_conversion(tmp_path):
    """No kicad-cli (Linux CI, a machine without KiCad) must not turn a successful conversion
    into an error - the symbol and 3D model are still good, and the footprint may already be in
    the modern dialect."""
    class _Cli:
        def fp_upgrade(self, pretty_dir):
            raise RuntimeError("kicad-cli not available")

    def fake_runner(cmd):
        from pathlib import Path

        base = Path(cmd[cmd.index("--output") + 1])
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".kicad_sym").write_text("(kicad_symbol_lib)", encoding="utf-8")
        pretty = Path(str(base) + ".pretty")
        pretty.mkdir(parents=True, exist_ok=True)
        (pretty / "C7666.kicad_mod").write_text("(footprint modern)", encoding="utf-8")

    d = fetch_lcsc("C7666", tmp_path, runner=fake_runner, cli=_Cli())
    assert d.footprint_paths[0].name == "C7666.kicad_mod"
