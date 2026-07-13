from pathlib import Path

import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.staging import StagingCandidate


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
