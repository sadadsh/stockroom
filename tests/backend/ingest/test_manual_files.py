from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from stockroom.altium.ul_import import UltraLibrarianImportError
from stockroom.ingest.manual_files import (
    apply_manual_cad_proposal,
    discard_all_manual_cad_proposals,
    discard_manual_cad_proposal,
    import_manual_cad_files,
    propose_manual_cad_files,
)
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import AssetRef, PartRecord


@pytest.fixture(autouse=True)
def _release_manual_proposal_snapshots():
    discard_all_manual_cad_proposals()
    yield
    discard_all_manual_cad_proposals()


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


def test_manual_intake_preserves_the_selected_eda_and_one_shared_3d_model(
    tmp_path: Path, monkeypatch
) -> None:
    selected = (tmp_path / "selected.zip",)
    selected[0].write_bytes(b"selected")
    symbol = tmp_path / "candidate.kicad_sym"
    footprint = tmp_path / "candidate.kicad_mod"
    model = tmp_path / "candidate.step"
    sch = tmp_path / "candidate.SchLib"
    pcb = tmp_path / "candidate.PcbLib"
    for path in (symbol, footprint, model, sch, pcb):
        path.write_bytes(path.name.encode())

    record = PartRecord(
        id="example",
        display_name="Example",
        category="ICs",
        mpn="EXAMPLE-1",
        manufacturer="Example Corp",
    )
    attached_kicad: list[StagingCandidate] = []
    attached_altium: list[tuple[Path, ...]] = []

    class Ops:
        def load_record(self, part_id):
            assert part_id == record.id
            return record

        def attach_altium_assets(self, part_id, *paths, **kwargs):
            assert part_id == record.id
            attached_altium.append(paths)
            record.assets_for("altium").symbol = AssetRef(file="altium/candidate.SchLib")
            record.assets_for("altium").footprint = AssetRef(file="altium/candidate.PcbLib")

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
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
            attached_kicad.append(candidate)
            assert candidate.symbol_lib_path is None
            assert candidate.footprint_variants == []
            assert candidate.model_path == model
            record.assets_for("kicad").model = AssetRef(file="models/candidate.step")

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr(
        "stockroom.ingest.manual_files._discover_native_altium",
        lambda *_: [sch, pcb],
    )
    ctx = SimpleNamespace(ops=Ops(), profile=object(), repo=object(), cli=object())

    result = import_manual_cad_files(ctx, record.id, selected, edas=("altium",))

    assert len(attached_kicad) == 1
    assert attached_altium == [(sch, pcb)]
    assert result["attached"] == ["altium_footprint", "altium_symbol", "kicad_model"]
    assert result["remaining"] == ["kicad_footprint", "kicad_symbol"]


def test_manual_proposal_defers_mutation_and_carries_the_selected_eda_into_apply(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "selected.zip"
    selected.write_bytes(b"selected")
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="EXAMPLE-1",
        manufacturer="Example Corp",
    )
    ctx = SimpleNamespace(ops=SimpleNamespace(load_record=lambda _part_id: record))
    applied: list[tuple[object, str, tuple[Path, ...], tuple[str, ...]]] = []
    monkeypatch.setattr(
        "stockroom.ingest.manual_files._manual_attachment_preview",
        lambda *args, **kwargs: (
            [{"role": "Altium Symbol", "file_name": "selected.SchLib", "target": "Active Altium Symbol"}],
            [],
            [],
            [],
            "",
        ),
    )
    monkeypatch.setattr(
        "stockroom.ingest.manual_files.import_manual_cad_files",
        lambda received_ctx, part_id, paths, *, edas: applied.append(
            (received_ctx, part_id, paths, edas)
        ) or {"attached": ["altium_symbol"]},
    )

    proposal = propose_manual_cad_files(
        ctx,
        "part-1",
        (selected,),
        edas=("altium",),
    )

    assert applied == []
    assert proposal["remaining_roles"] == ["3D Model", "Altium Footprint"]
    assert proposal["automatic_apply_ready"] is True
    result = apply_manual_cad_proposal(ctx, "part-1", proposal["proposal_token"])
    assert result == {"attached": ["altium_symbol"]}
    assert len(applied) == 1
    assert applied[0][:2] == (ctx, "part-1")
    assert applied[0][2] != (selected,)
    assert applied[0][3] == ("altium",)


def test_manual_proposal_marks_an_exact_selected_eda_package_safe_for_automatic_apply(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "complete.zip"
    selected.write_bytes(b"complete")
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="EXAMPLE-1",
        manufacturer="Example Corp",
    )
    ctx = SimpleNamespace(ops=SimpleNamespace(load_record=lambda _part_id: record))
    monkeypatch.setattr(
        "stockroom.ingest.manual_files._manual_attachment_preview",
        lambda *args, **kwargs: (
            [
                {"role": "KiCad Symbol", "file_name": "complete.kicad_sym", "target": "Active KiCad Symbol"},
                {"role": "KiCad Footprint", "file_name": "complete.kicad_mod", "target": "Active KiCad Footprint"},
                {"role": "3D Model", "file_name": "complete.step", "target": "Shared 3D Model"},
            ],
            [],
            [],
            [],
            "",
        ),
    )

    proposal = propose_manual_cad_files(ctx, "part-1", (selected,), edas=("kicad",))

    assert proposal["remaining_roles"] == []
    assert proposal["automatic_apply_ready"] is True


def test_manual_proposal_does_not_auto_apply_two_files_mapped_to_one_required_role(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "ambiguous.zip"
    selected.write_bytes(b"ambiguous")
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="EXAMPLE-1",
        manufacturer="Example Corp",
    )
    ctx = SimpleNamespace(ops=SimpleNamespace(load_record=lambda _part_id: record))
    monkeypatch.setattr(
        "stockroom.ingest.manual_files._manual_attachment_preview",
        lambda *args, **kwargs: (
            [
                {"role": "KiCad Symbol", "file_name": "one.kicad_sym", "target": "Active KiCad Symbol"},
                {"role": "KiCad Symbol", "file_name": "two.kicad_sym", "target": "Active KiCad Symbol"},
                {"role": "KiCad Footprint", "file_name": "complete.kicad_mod", "target": "Active KiCad Footprint"},
                {"role": "3D Model", "file_name": "complete.step", "target": "Shared 3D Model"},
            ],
            [],
            [],
            [],
            "",
        ),
    )

    proposal = propose_manual_cad_files(ctx, "part-1", (selected,), edas=("kicad",))

    assert proposal["remaining_roles"] == ["KiCad Symbol"]
    assert proposal["automatic_apply_ready"] is False


def test_manual_proposal_requires_exact_punctuation_preserving_candidate_identity(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "complete.zip"
    selected.write_bytes(b"complete")
    symbol = tmp_path / "candidate.kicad_sym"
    footprint = tmp_path / "candidate.kicad_mod"
    model = tmp_path / "candidate.step"
    for path in (symbol, footprint, model):
        path.write_bytes(path.name.encode())
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="ABM13W-32.0000MHZ-5-DH7G-T5",
        manufacturer="Abracon",
    )

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            assert len(inputs) == 1
            assert inputs[0] != selected
            assert inputs[0].name == selected.name
            assert inputs[0].read_bytes() == b"complete"
            return [
                StagingCandidate(
                    vendor="manual",
                    symbol_lib_path=symbol,
                    symbol_name="ABM13W-32-0000MHZ-5-DH7G-T5",
                    footprint_variants=[footprint],
                    model_path=model,
                    mpn="ABM13W-32-0000MHZ-5-DH7G-T5",
                )
            ]

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr("stockroom.ingest.manual_files._discover_native_altium", lambda *_: [])
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        profile=object(),
        repo=object(),
        cli=object(),
    )

    proposal = propose_manual_cad_files(ctx, record.id, (selected,), edas=("kicad",))

    assert proposal["attachments"] == [
        {"role": "KiCad Symbol", "file_name": symbol.name, "target": "Active KiCad Symbol"},
        {
            "role": "KiCad Footprint",
            "file_name": footprint.name,
            "target": "Active KiCad Footprint",
        },
        {"role": "3D Model", "file_name": model.name, "target": "Shared 3D Model"},
    ]
    assert proposal["remaining_roles"] == ["Exact MPN Identity"]
    assert proposal["remaining_status"] == ["Exact MPN Identity"]
    assert proposal["automatic_apply_ready"] is False
    assert "ABM13W-32-0000MHZ-5-DH7G-T5" in proposal["review_required_reason"]


def test_manual_proposal_marks_only_an_exact_parsed_mpn_automatic_apply_ready(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "complete.zip"
    selected.write_bytes(b"complete")
    symbol = tmp_path / "candidate.kicad_sym"
    footprint = tmp_path / "candidate.kicad_mod"
    model = tmp_path / "candidate.step"
    for path in (symbol, footprint, model):
        path.write_bytes(path.name.encode())
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="ABM13W-32.0000MHZ-5-DH7G-T5",
        manufacturer="Abracon",
    )

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            assert len(inputs) == 1
            assert inputs[0] != selected
            assert inputs[0].name == selected.name
            assert inputs[0].read_bytes() == b"complete"
            return [
                StagingCandidate(
                    vendor="manual",
                    symbol_lib_path=symbol,
                    symbol_name=record.mpn,
                    footprint_variants=[footprint],
                    model_path=model,
                    mpn=record.mpn,
                )
            ]

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr("stockroom.ingest.manual_files._discover_native_altium", lambda *_: [])
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        profile=object(),
        repo=object(),
        cli=object(),
    )

    proposal = propose_manual_cad_files(ctx, record.id, (selected,), edas=("kicad",))

    assert proposal["remaining_roles"] == []
    assert proposal["remaining_status"] == []
    assert proposal["review_required_reason"] == ""
    assert proposal["automatic_apply_ready"] is True


def test_manual_proposal_with_no_parsed_mpn_stays_review_only_with_identity_remaining(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "complete.zip"
    selected.write_bytes(b"complete")
    symbol = tmp_path / "candidate.kicad_sym"
    footprint = tmp_path / "candidate.kicad_mod"
    model = tmp_path / "candidate.step"
    for path in (symbol, footprint, model):
        path.write_bytes(path.name.encode())
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="LM358DR",
        manufacturer="Texas Instruments",
    )

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            assert len(inputs) == 1
            assert inputs[0] != selected
            assert inputs[0].name == selected.name
            assert inputs[0].read_bytes() == b"complete"
            return [
                StagingCandidate(
                    vendor="manual",
                    symbol_lib_path=symbol,
                    symbol_name="",
                    footprint_variants=[footprint],
                    model_path=model,
                    mpn="",
                )
            ]

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr("stockroom.ingest.manual_files._discover_native_altium", lambda *_: [])
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        profile=object(),
        repo=object(),
        cli=object(),
    )

    proposal = propose_manual_cad_files(ctx, record.id, (selected,), edas=("kicad",))

    assert proposal["remaining_roles"] == ["Exact MPN Identity"]
    assert proposal["remaining_status"] == ["Exact MPN Identity"]
    assert proposal["automatic_apply_ready"] is False
    assert "no parsed MPN" in proposal["review_required_reason"]


def test_discard_consumes_only_the_owned_parts_proposal_and_preserves_selected_file(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "reviewed.zip"
    selected.write_bytes(b"reviewed")
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="LM358DR",
        manufacturer="Texas Instruments",
    )
    monkeypatch.setattr(
        "stockroom.ingest.manual_files._manual_attachment_preview",
        lambda *args, **kwargs: ([], [], [], [], ""),
    )
    ctx = SimpleNamespace(ops=SimpleNamespace(load_record=lambda _part_id: record))
    proposal = propose_manual_cad_files(ctx, record.id, (selected,), edas=("kicad",))
    token = proposal["proposal_token"]

    assert discard_manual_cad_proposal("another-part", token) is False
    assert discard_manual_cad_proposal(record.id, token) is True
    assert selected.read_bytes() == b"reviewed"
    try:
        apply_manual_cad_proposal(ctx, record.id, token)
    except ValueError as exc:
        assert "missing, expired" in str(exc)
    else:
        raise AssertionError("a discarded proposal remained applicable")


def test_exact_kicad_identity_does_not_bless_unproven_native_altium_files(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "mixed.zip"
    selected.write_bytes(b"mixed")
    symbol = tmp_path / "exact.kicad_sym"
    footprint = tmp_path / "exact.kicad_mod"
    model = tmp_path / "exact.step"
    unrelated_sch = tmp_path / "unrelated.SchLib"
    unrelated_pcb = tmp_path / "unrelated.PcbLib"
    for path in (symbol, footprint, model, unrelated_sch, unrelated_pcb):
        path.write_bytes(path.name.encode())
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="LM358DR",
        manufacturer="Texas Instruments",
    )

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            assert len(inputs) == 1
            return [
                StagingCandidate(
                    vendor="manual",
                    symbol_lib_path=symbol,
                    symbol_name=record.mpn,
                    footprint_variants=[footprint],
                    model_path=model,
                    mpn=record.mpn,
                )
            ]

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr(
        "stockroom.ingest.manual_files._discover_native_altium",
        lambda *_args: [unrelated_sch, unrelated_pcb],
    )
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        profile=object(),
        repo=object(),
        cli=object(),
    )

    proposal = propose_manual_cad_files(
        ctx,
        record.id,
        (selected,),
        edas=("kicad", "altium"),
    )

    assert proposal["remaining_roles"] == ["Exact Altium Identity"]
    assert proposal["automatic_apply_ready"] is False
    assert "native Altium" in proposal["review_required_reason"]


def test_exact_native_altium_symbol_can_supply_its_own_identity_binding(
    tmp_path: Path, monkeypatch
) -> None:
    selected = Path("tests/backend/altium/fixtures/sample.SchLib").resolve()
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="Diodes",
        mpn="S1M",
        manufacturer="Diodes Inc",
    )
    record.assets_for("kicad").model = AssetRef(file="models/existing.step")
    record.assets_for("altium").footprint = AssetRef(file="altium/existing.PcbLib")

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            assert len(inputs) == 1
            return []

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        profile=object(),
        repo=object(),
        cli=object(),
    )

    proposal = propose_manual_cad_files(ctx, record.id, (selected,), edas=("altium",))

    assert proposal["attachments"] == [
        {
            "role": "Altium Symbol",
            "file_name": "sample.SchLib",
            "target": "Active Altium Symbol",
        }
    ]
    assert proposal["remaining_roles"] == []
    assert proposal["review_required_reason"] == ""
    assert proposal["automatic_apply_ready"] is True
    assert discard_manual_cad_proposal(record.id, proposal["proposal_token"]) is True


def test_two_exact_native_libraries_with_the_same_name_remain_ambiguous(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "selected.zip"
    selected.write_bytes(b"selected")
    first = tmp_path / "one" / "duplicate.SchLib"
    second = tmp_path / "two" / "duplicate.SchLib"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="Diodes",
        mpn="S1M",
        manufacturer="Diodes Inc",
    )
    record.assets_for("kicad").model = AssetRef(file="models/existing.step")
    record.assets_for("altium").footprint = AssetRef(file="altium/existing.PcbLib")

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            assert len(inputs) == 1
            return []

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr(
        "stockroom.ingest.manual_files._discover_native_altium",
        lambda *_args: [first, second],
    )
    monkeypatch.setattr(
        "stockroom.ingest.manual_files.read_symbol_names",
        lambda _path: [record.mpn],
    )
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        profile=object(),
        repo=object(),
        cli=object(),
    )

    proposal = propose_manual_cad_files(ctx, record.id, (selected,), edas=("altium",))

    assert proposal["remaining_roles"] == ["Altium Symbol"]
    assert proposal["automatic_apply_ready"] is False


def test_proposal_previews_and_applies_one_owned_snapshot_not_reopened_user_paths(
    tmp_path: Path, monkeypatch
) -> None:
    selected = tmp_path / "selected.zip"
    selected.write_bytes(b"reviewed bytes")
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="LM358DR",
        manufacturer="Texas Instruments",
    )
    preview_paths: list[Path] = []
    applied_paths: list[Path] = []

    def preview(_ctx, _part_id, paths, *, edas):
        assert edas == ("kicad",)
        preview_paths.extend(paths)
        assert paths[0].read_bytes() == b"reviewed bytes"
        selected.write_bytes(b"swapped after preview")
        return ([], [], [], [], "")

    def apply_files(_ctx, _part_id, paths, *, edas):
        assert edas == ("kicad",)
        applied_paths.extend(paths)
        assert paths[0].read_bytes() == b"reviewed bytes"
        return {"attached": [], "remaining": [], "complete": True}

    monkeypatch.setattr("stockroom.ingest.manual_files._manual_attachment_preview", preview)
    monkeypatch.setattr("stockroom.ingest.manual_files.import_manual_cad_files", apply_files)
    ctx = SimpleNamespace(ops=SimpleNamespace(load_record=lambda _part_id: record))

    proposal = propose_manual_cad_files(ctx, record.id, (selected,), edas=("kicad",))
    result = apply_manual_cad_proposal(ctx, record.id, proposal["proposal_token"])

    assert result["complete"] is True
    assert preview_paths == applied_paths
    assert preview_paths != [selected]
    owned_root = preview_paths[0].parent.parent
    assert not owned_root.exists()
    assert selected.read_bytes() == b"swapped after preview"


def test_discard_and_ttl_expiry_remove_only_proposal_owned_snapshots(
    tmp_path: Path, monkeypatch
) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="LM358DR",
        manufacturer="Texas Instruments",
    )
    preview_paths: list[Path] = []
    now = [1_000.0]

    def preview(_ctx, _part_id, paths, *, edas):
        preview_paths.extend(paths)
        return ([], [], [], [], "")

    monkeypatch.setattr("stockroom.ingest.manual_files._manual_attachment_preview", preview)
    monkeypatch.setattr("stockroom.ingest.manual_files.time.monotonic", lambda: now[0])
    ctx = SimpleNamespace(ops=SimpleNamespace(load_record=lambda _part_id: record))

    first_proposal = propose_manual_cad_files(ctx, record.id, (first,), edas=("kicad",))
    first_snapshot = preview_paths[-1]
    assert first_snapshot != first
    first_root = first_snapshot.parent.parent
    assert first_root.is_dir()
    now[0] += 30 * 60
    second_proposal = propose_manual_cad_files(ctx, record.id, (second,), edas=("kicad",))
    second_snapshot = preview_paths[-1]
    second_root = second_snapshot.parent.parent

    assert not first_root.exists()
    assert second_root.is_dir()
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert discard_manual_cad_proposal(record.id, first_proposal["proposal_token"]) is False
    assert discard_manual_cad_proposal(record.id, second_proposal["proposal_token"]) is True
    assert not second_root.exists()
    assert second.read_bytes() == b"second"
