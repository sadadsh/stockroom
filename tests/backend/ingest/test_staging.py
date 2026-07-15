import shutil
from pathlib import Path

import pytest

from tests.backend.conftest import requires_kicad_cli
from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import DetectedSource
from stockroom.ingest.staging import StagingCandidate, build_candidates, merge_candidates
from stockroom.model.part import Provenance, Purchase


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


def test_to_staged_part_projects_purchase_for_the_gate():
    # A purchase link is a required passport field (spec section 6); the candidate
    # must carry it through to the StagedPart or the gate is unsatisfiable via ingest.
    c = _candidate(purchase=[Purchase(vendor="Mouser", url="https://mouser.com/p/1")])
    sp = c.to_staged_part()
    assert sp.purchase and sp.purchase[0].url == "https://mouser.com/p/1"


def test_to_staged_part_purchase_defaults_empty():
    sp = _candidate().to_staged_part()
    assert sp.purchase == []


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


# -- merge_candidates: a part often arrives split across two vendor files -------


def _full(name="TESTPART", mpn="", model=None, datasheet=None) -> StagingCandidate:
    gaps = []
    if model is None:
        gaps.append("no 3D model in this package")
    if datasheet is None:
        gaps.append("no datasheet in this package")
    return StagingCandidate(
        vendor="snapeda",
        symbol_lib_path=Path("/stage/sym.kicad_sym"),
        symbol_name=name,
        footprint_variants=[Path("/stage/fp.kicad_mod")],
        model_path=model,
        datasheet_path=datasheet,
        display_name=name,
        entry_name=name,
        mpn=mpn,
        gaps=gaps,
    )


def _fragment(model=None, datasheet=None, mpn="") -> StagingCandidate:
    return StagingCandidate(
        vendor="partial",
        symbol_lib_path=None,
        symbol_name="",
        footprint_variants=[],
        model_path=model,
        datasheet_path=datasheet,
        mpn=mpn,
        gaps=["package contains only a 3D model; attach it to an existing part"],
    )


def test_merge_folds_a_model_fragment_into_the_sole_full_candidate():
    full = _full()
    frag = _fragment(model=Path("/drop/only.step"))
    merged = merge_candidates([full, frag])
    assert len(merged) == 1
    assert merged[0].symbol_name == "TESTPART"
    assert merged[0].model_path == Path("/drop/only.step")
    # the absorbed asset's gap is gone, the datasheet gap honestly remains
    assert not any("3D model" in g for g in merged[0].gaps)
    assert any("datasheet" in g for g in merged[0].gaps)


def test_merge_matches_a_named_fragment_by_mpn_among_many():
    a = _full(name="PARTA", mpn="MPN-A")
    b = _full(name="PARTB", mpn="MPN-B")
    frag = _fragment(model=Path("/drop/b.step"), mpn="mpn-b")
    merged = merge_candidates([a, b, frag])
    assert len(merged) == 2
    by_name = {c.symbol_name: c for c in merged}
    assert by_name["PARTB"].model_path == Path("/drop/b.step")
    assert by_name["PARTA"].model_path is None


def test_merge_leaves_an_anonymous_fragment_when_ambiguous():
    a = _full(name="PARTA")
    b = _full(name="PARTB")
    frag = _fragment(model=Path("/drop/x.step"))
    merged = merge_candidates([a, b, frag])
    # no identity and two possible owners: never guess, keep the attach card
    assert len(merged) == 3


def test_merge_never_overwrites_an_asset_the_full_candidate_already_has():
    full = _full(model=Path("/zip/original.step"))
    frag = _fragment(model=Path("/drop/other.step"))
    merged = merge_candidates([full, frag])
    # the full candidate keeps its own model; the fragment still needs a decision
    assert len(merged) == 2
    assert merged[0].model_path == Path("/zip/original.step")


def test_merge_keeps_symbol_bearing_candidates_apart():
    a = _full(name="PARTA", mpn="SAME")
    b = _full(name="PARTB", mpn="SAME")
    assert len(merge_candidates([a, b])) == 2


def test_merge_folds_a_datasheet_fragment_too():
    full = _full()
    frag = _fragment(datasheet=Path("/drop/part.pdf"))
    merged = merge_candidates([full, frag])
    assert len(merged) == 1
    assert merged[0].datasheet_path == Path("/drop/part.pdf")
    assert not any("datasheet" in g for g in merged[0].gaps)


def test_merge_is_a_no_op_without_fragments():
    a, b = _full(name="PARTA"), _full(name="PARTB")
    assert merge_candidates([a, b]) == [a, b]
