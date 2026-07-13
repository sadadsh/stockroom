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
