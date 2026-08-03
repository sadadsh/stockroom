from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from stockroom.altium.ul_import import UltraLibrarianImportError
from stockroom.ingest.manual_files import import_manual_cad_files
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import AssetRef, PartRecord


def test_manual_intake_inspects_the_whole_selection_and_keeps_every_useful_kicad_role(
    tmp_path: Path, monkeypatch
) -> None:
    selected = (tmp_path / "symbol.zip", tmp_path / "footprint.kicad_mod", tmp_path / "body.step")
    for path in selected:
        path.write_bytes(path.name.encode())
    symbol = tmp_path / "candidate.kicad_sym"
    footprint = tmp_path / "candidate.kicad_mod"
    model = tmp_path / "candidate.step"
    for path in (symbol, footprint, model):
        path.write_bytes(path.name.encode())

    record = PartRecord(
        id="example",
        display_name="Example",
        category="ICs",
        mpn="EXAMPLE-1",
        manufacturer="Example Corp",
    )
    inspected = []

    class Ops:
        def load_record(self, part_id):
            assert part_id == record.id
            return record

        def attach_altium_assets(self, *args, **kwargs):
            raise AssertionError("no native Altium files were supplied")

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            inspected.append(tuple(inputs))
            return [
                StagingCandidate(
                    vendor="manual",
                    symbol_lib_path=symbol,
                    symbol_name="EXAMPLE-1",
                    footprint_variants=[footprint],
                    model_path=model,
                    mpn="EXAMPLE-1",
                )
            ]

        def attach_assets(self, part_id, candidate, **kwargs):
            assert part_id == record.id
            assert candidate.symbol_lib_path == symbol
            assert candidate.chosen_footprint == footprint
            assert candidate.model_path == model
            record.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="EXAMPLE-1")
            record.assets_for("kicad").footprint = AssetRef(lib="SR-ICs", name="EXAMPLE-1")
            record.assets_for("kicad").model = AssetRef(file="models/candidate.step")

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr("stockroom.ingest.manual_files._discover_native_altium", lambda *_: [])
    monkeypatch.setattr(
        "stockroom.ingest.manual_files.convert_ul_altium_package",
        lambda *args, **kwargs: (_ for _ in ()).throw(UltraLibrarianImportError("not a UL package")),
    )
    ctx = SimpleNamespace(ops=Ops(), profile=object(), repo=object(), cli=object())

    result = import_manual_cad_files(ctx, record.id, selected)

    assert inspected == [selected]
    assert result["attached"] == ["kicad_footprint", "kicad_model", "kicad_symbol"]
    assert result["remaining"] == ["altium_footprint", "altium_symbol"]
    assert result["complete"] is False
