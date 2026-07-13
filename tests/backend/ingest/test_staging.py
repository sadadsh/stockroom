import shutil
from pathlib import Path

import pytest

from tests.backend.conftest import requires_kicad_cli
from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import DetectedSource
from stockroom.ingest.staging import StagingCandidate, build_candidates
from stockroom.model.part import Provenance


def _candidate(**kw):
    base = dict(
        vendor="snapeda",
        symbol_lib_path=Path("/tmp/sym.kicad_sym"),
        symbol_name="TESTPART",
        footprint_variants=[Path("/tmp/a.kicad_mod"), Path("/tmp/b.kicad_mod")],
        entry_name="TPS62130RGTR",
        display_name="TPS62130 buck",
        category="ICs",
        mpn="TPS62130RGTR",
    )
    base.update(kw)
    return StagingCandidate(**base)


def test_chosen_footprint_defaults_to_first():
    c = _candidate()
    assert c.chosen_footprint == Path("/tmp/a.kicad_mod")


def test_chosen_footprint_honors_index():
    c = _candidate(chosen_footprint_index=1)
    assert c.chosen_footprint == Path("/tmp/b.kicad_mod")


def test_to_staged_part_maps_all_fields():
    c = _candidate(model_path=Path("/tmp/m.step"), datasheet_path=Path("/tmp/d.pdf"))
    sp = c.to_staged_part()
    assert sp.display_name == "TPS62130 buck"
    assert sp.category == "ICs"
    assert sp.symbol_source == Path("/tmp/sym.kicad_sym")
    assert sp.symbol_source_name == "TESTPART"
    assert sp.footprint_source == Path("/tmp/a.kicad_mod")
    assert sp.entry_name == "TPS62130RGTR"
    assert sp.model_source == Path("/tmp/m.step")
    assert sp.datasheet_source == Path("/tmp/d.pdf")


def test_to_staged_part_rejects_missing_symbol():
    c = _candidate(symbol_lib_path=None)
    with pytest.raises(IngestError):
        c.to_staged_part()


def test_to_staged_part_rejects_missing_footprint():
    c = _candidate(footprint_variants=[])
    with pytest.raises(IngestError):
        c.to_staged_part()


def _cli():
    from stockroom.kicad.cli import KiCadCli
    return KiCadCli()


@requires_kicad_cli
def test_build_candidates_from_snapeda(tmp_path, fixtures_dir):
    sym = tmp_path / "MyPart.kicad_sym"
    fp = tmp_path / "MyPart.kicad_mod"
    model = tmp_path / "MyPart.step"
    datasheet = tmp_path / "MyPart.pdf"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp)
    model.write_bytes(b"ISO-10303-21;\n")
    datasheet.write_bytes(b"%PDF-1.4\n")
    detected = DetectedSource("snapeda", sym, None, [fp], model, datasheet)
    prov = Provenance(source="snapeda")
    cands = build_candidates(_cli(), detected, tmp_path / "work", prov)
    assert len(cands) == 1
    c = cands[0]
    assert c.symbol_name == "TESTPART"
    assert c.entry_name == "TESTPART"
    assert c.model_path == model
    assert c.gaps == []  # symbol, footprint, and model all present


@requires_kicad_cli
def test_build_candidates_flags_missing_model(tmp_path, fixtures_dir):
    sym = tmp_path / "MyPart.kicad_sym"
    fp = tmp_path / "MyPart.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp)
    detected = DetectedSource("snapeda", sym, None, [fp], None, None)
    [c] = build_candidates(_cli(), detected, tmp_path / "work")
    assert any("3D model" in g for g in c.gaps)


def test_build_candidates_partial_is_model_only():
    model = Path("/tmp/only.step")
    detected = DetectedSource("partial", None, None, [], model, None)
    # partial does not need kicad-cli; pass None safely.
    [c] = build_candidates(None, detected, Path("/tmp"))
    assert c.symbol_lib_path is None
    assert c.model_path == model
    assert any("only a 3D model" in g for g in c.gaps)
