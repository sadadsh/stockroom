"""Retained candidates: honest outcomes, and provenance that survives deduplication."""

from __future__ import annotations

import zipfile
from pathlib import Path

from stockroom.ingest.candidates import (
    KIND_FOOTPRINT,
    KIND_MODEL,
    KIND_SYMBOL,
    RetainedCandidateStore,
    ValidationOutcome,
    inspect_artifact,
)

MANUFACTURER = "ON Semiconductor"
MPN = "S1M"
PACKAGE = "SMA"
STEP = "ISO-10303-21;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def _symbol(
    *,
    entry: str = MPN,
    mpn: str = MPN,
    manufacturer: str = MANUFACTURER,
    package: str = PACKAGE,
    pins: tuple[str, ...] = ("1", "2"),
) -> str:
    properties = [
        '(property "Reference" "D" (at 0 0 0))',
        f'(property "Value" "{entry}" (at 0 0 0))',
    ]
    if mpn:
        properties.append(f'(property "Manufacturer Part Number" "{mpn}" (at 0 0 0))')
    if manufacturer:
        properties.append(f'(property "Manufacturer" "{manufacturer}" (at 0 0 0))')
    if package:
        properties.append(f'(property "Package" "{package}" (at 0 0 0))')
    pin_text = "\n".join(
        f'\t\t\t(pin passive line (at 0 0 0) (length 2.54)\n'
        f'\t\t\t\t(name "P{number}" (effects (font (size 1.27 1.27))))\n'
        f'\t\t\t\t(number "{number}" (effects (font (size 1.27 1.27))))\n'
        f"\t\t\t)"
        for number in pins
    )
    property_text = "\n".join(f"\t\t{item}" for item in properties)
    return (
        "(kicad_symbol_lib\n"
        "\t(version 20251024)\n"
        '\t(generator "kicad_symbol_editor")\n'
        f'\t(symbol "{entry}"\n'
        f"{property_text}\n"
        f'\t\t(symbol "{entry}_0_1"\n'
        f"{pin_text}\n"
        "\t\t)\n"
        "\t)\n"
        ")\n"
    )


def _footprint(*, name: str = PACKAGE, pads: tuple[str, ...] = ("1", "2")) -> str:
    pad_text = "\n".join(
        f'\t(pad "{number}" smd rect (at {index} 0) (size 1 1) (layers "F.Cu"))'
        for index, number in enumerate(pads)
    )
    return (
        f'(footprint "{name}"\n'
        "\t(version 20240108)\n"
        '\t(generator "pcbnew")\n'
        '\t(layer "F.Cu")\n'
        f"{pad_text}\n"
        ")\n"
    )


def _package_zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def _complete(**overrides) -> dict[str, str]:
    members = {
        "KiCad/S1M.kicad_sym": _symbol(),
        "KiCad/SMA.kicad_mod": _footprint(),
        "S1M.step": STEP,
        "README.txt": "import instructions",
    }
    members.update(overrides)
    return members


def _store(tmp_path: Path) -> RetainedCandidateStore:
    return RetainedCandidateStore(tmp_path / "Candidates")


def _retain(store, package, **kwargs):
    return store.retain_package(
        component_id="cmp-1",
        provider_id=kwargs.pop("provider_id", "digikey"),
        package_path=package,
        source_url=kwargs.pop("source_url", "https://example.invalid/S1M"),
        expected_mpn=kwargs.pop("expected_mpn", MPN),
        expected_manufacturer=kwargs.pop("expected_manufacturer", MANUFACTURER),
        expected_package=kwargs.pop("expected_package", PACKAGE),
        **kwargs,
    )


def _by_kind(candidates, kind):
    return next(item for item in candidates if item.artifact_kind == kind)


# --- outcomes ---------------------------------------------------------------


def test_a_complete_matching_package_is_ready_to_import(tmp_path):
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    retained = _retain(_store(tmp_path), package)
    symbol = _by_kind(retained, KIND_SYMBOL)
    footprint = _by_kind(retained, KIND_FOOTPRINT)
    model = _by_kind(retained, KIND_MODEL)
    assert symbol.validation_result == "Ready To Import"
    assert footprint.validation_result == "Ready To Import"
    assert model.validation_result == "Ready To Import"
    assert symbol.mpn == MPN and symbol.manufacturer == MANUFACTURER
    assert symbol.pins == ("1", "2") and footprint.pads == ("1", "2")
    assert footprint.package == PACKAGE
    # every field the model promises is populated from the artifact, not invented
    assert symbol.component_id == "cmp-1"
    assert symbol.provider_id == "digikey"
    assert symbol.source_url == "https://example.invalid/S1M"
    assert symbol.artifact_digest and symbol.source_package_digest
    assert symbol.original_filename == "S1M.kicad_sym"
    assert (tmp_path / "Candidates" / symbol.stored_path).is_file()
    assert symbol.detected_format == "kicad_symbol_library"
    assert symbol.selected_slot == "" and symbol.rejected is False


def test_a_symbol_only_package_is_a_partial_package(tmp_path):
    package = _package_zip(tmp_path / "partial.zip", {"KiCad/S1M.kicad_sym": _symbol()})
    retained = _retain(_store(tmp_path), package)
    symbol = _by_kind(retained, KIND_SYMBOL)
    assert symbol.validation_result == "Partial Package"
    assert any("complete symbol, footprint and model set" in m for m in symbol.validation_messages)


def test_a_foreign_mpn_is_a_component_mismatch(tmp_path):
    package = _package_zip(
        tmp_path / "other.zip",
        _complete(**{"KiCad/S1M.kicad_sym": _symbol(entry="OTHER", mpn="OTHER")}),
    )
    retained = _retain(_store(tmp_path), package)
    symbol = _by_kind(retained, KIND_SYMBOL)
    assert symbol.validation_result == "Component Mismatch"
    assert any("does not match" in message for message in symbol.validation_messages)


def test_a_foreign_package_is_a_package_mismatch(tmp_path):
    # the symbol carries no Package property, so the FOOTPRINT is the only package claim
    package = _package_zip(
        tmp_path / "pkg.zip",
        {
            "KiCad/S1M.kicad_sym": _symbol(package=""),
            "KiCad/SOD.kicad_mod": _footprint(name="SOD-123"),
            "S1M.step": STEP,
        },
    )
    retained = _retain(_store(tmp_path), package)
    footprint = _by_kind(retained, KIND_FOOTPRINT)
    assert footprint.validation_result == "Package Mismatch"


def test_pins_and_pads_that_disagree_are_a_package_mismatch(tmp_path):
    package = _package_zip(
        tmp_path / "pinpad.zip",
        _complete(**{"KiCad/SMA.kicad_mod": _footprint(pads=("1", "2", "3"))}),
    )
    retained = _retain(_store(tmp_path), package)
    symbol = _by_kind(retained, KIND_SYMBOL)
    footprint = _by_kind(retained, KIND_FOOTPRINT)
    assert symbol.validation_result == "Package Mismatch"
    assert footprint.validation_result == "Package Mismatch"
    assert any("pad identifiers" in message for message in symbol.validation_messages)


def test_a_symbol_with_nothing_provable_needs_manual_review(tmp_path):
    package = _package_zip(
        tmp_path / "anon.zip",
        _complete(
            **{"KiCad/S1M.kicad_sym": _symbol(entry="SYM1", mpn="", manufacturer="", package="")}
        ),
    )
    retained = _retain(_store(tmp_path), package)
    symbol = _by_kind(retained, KIND_SYMBOL)
    assert symbol.validation_result == "Manual Review Required"
    assert symbol.manual_review_required is True


def test_a_legacy_lib_is_manual_review_because_no_tested_parser_exists(tmp_path):
    facts = inspect_artifact(tmp_path / "device.lib", expected_mpn=MPN)
    assert facts.outcome is ValidationOutcome.MANUAL_REVIEW_REQUIRED
    assert any("no tested parser" in message for message in facts.messages)


def test_an_unparseable_symbol_is_an_invalid_file(tmp_path):
    package = _package_zip(
        tmp_path / "bad.zip", _complete(**{"KiCad/S1M.kicad_sym": "not an s-expression at all"})
    )
    retained = _retain(_store(tmp_path), package)
    symbol = next(item for item in retained if item.original_filename.endswith(".kicad_sym"))
    assert symbol.validation_result == "Invalid File"
    assert symbol.rejected is True


def test_a_model_without_a_step_header_is_an_invalid_file(tmp_path):
    package = _package_zip(tmp_path / "nostep.zip", _complete(**{"S1M.step": "not a step file"}))
    retained = _retain(_store(tmp_path), package)
    model = next(item for item in retained if item.original_filename.endswith(".step"))
    assert model.validation_result == "Invalid File"


def test_supporting_material_is_an_unsupported_file_and_is_still_retained(tmp_path):
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    retained = _retain(_store(tmp_path), package)
    readme = next(item for item in retained if item.original_filename == "README.txt")
    assert readme.validation_result == "Unsupported File"
    assert (tmp_path / "Candidates" / readme.stored_path).is_file()


def test_the_outcome_vocabulary_is_exactly_the_agreed_strings():
    assert [item.value for item in ValidationOutcome] == [
        "Ready To Import",
        "Partial Package",
        "Manual Review Required",
        "Component Mismatch",
        "Package Mismatch",
        "Unsupported File",
        "Invalid File",
        "Imported",
        "Import Failed",
    ]


def test_an_existing_library_entry_name_forces_manual_review(tmp_path):
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    retained = _retain(_store(tmp_path), package, existing_library_names=("S1M",))
    symbol = _by_kind(retained, KIND_SYMBOL)
    assert symbol.validation_result == "Manual Review Required"
    assert any("already exists" in message for message in symbol.validation_messages)


# --- dedupe, provenance, re-processing --------------------------------------


def test_identical_bytes_from_two_providers_are_one_artifact_with_two_provenances(tmp_path):
    store = _store(tmp_path)
    first = _package_zip(tmp_path / "digikey.zip", _complete())
    # a different package (an extra README) carrying the SAME symbol bytes
    second = _package_zip(tmp_path / "mouser.zip", _complete(**{"NOTICE.txt": "second provider"}))
    a = _retain(store, first, provider_id="digikey")
    b = _retain(store, second, provider_id="mouser", source_url="https://other.invalid/S1M")
    symbol_a = _by_kind(a, KIND_SYMBOL)
    symbol_b = _by_kind(b, KIND_SYMBOL)
    assert symbol_a.candidate_id == symbol_b.candidate_id
    assert symbol_a.artifact_digest == symbol_b.artifact_digest
    assert [item.provider_id for item in symbol_b.provenances] == ["digikey", "mouser"]
    assert len(set(symbol_b.source_package_digests)) == 2
    # one stored artifact, two provenance records
    stored = sorted((tmp_path / "Candidates" / "artifacts").iterdir())
    assert len(stored) == len({item.artifact_digest for item in store.all_candidates()})


def test_reprocessing_a_known_package_returns_the_existing_candidates(tmp_path):
    store = _store(tmp_path)
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    first = _retain(store, package)
    again = _retain(store, package)
    assert [item.candidate_id for item in again] == [item.candidate_id for item in first]
    assert all(item.validation_result != "Invalid File" for item in again)
    assert len(store.candidates_for("cmp-1")) == len(first)


def test_a_reloaded_store_still_knows_the_package(tmp_path):
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    first = _retain(_store(tmp_path), package)
    again = _retain(_store(tmp_path), package)
    assert [item.candidate_id for item in again] == [item.candidate_id for item in first]


# --- the provider package is kept until import succeeds ---------------------


def test_the_provider_package_is_kept_until_every_candidate_imports(tmp_path):
    store = _store(tmp_path)
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    retained = _retain(store, package)
    digest = retained[0].source_package_digest
    assert store.package_path(digest) is not None
    importable = [
        item
        for item in retained
        if item.validation_result not in {"Unsupported File", "Invalid File"}
    ]
    for item in importable[:-1]:
        store.mark_imported(item.candidate_id)
    assert store.package_path(digest) is not None
    store.mark_imported(importable[-1].candidate_id)
    assert store.package_path(digest) is None


def test_a_person_can_remove_the_retained_package_themselves(tmp_path):
    store = _store(tmp_path)
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    retained = _retain(store, package)
    digest = retained[0].source_package_digest
    store.release_package(digest)
    assert store.package_path(digest) is None


def test_a_failed_import_keeps_the_package_and_records_why(tmp_path):
    store = _store(tmp_path)
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    retained = _retain(store, package)
    symbol = _by_kind(retained, KIND_SYMBOL)
    store.mark_import_failed(symbol.candidate_id, "the category library was locked")
    assert store.candidate(symbol.candidate_id).validation_result == "Import Failed"
    assert store.package_path(retained[0].source_package_digest) is not None


def test_a_slot_selection_and_a_rejection_are_recorded(tmp_path):
    store = _store(tmp_path)
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    retained = _retain(store, package)
    footprint = _by_kind(retained, KIND_FOOTPRINT)
    store.select_slot(footprint.candidate_id, "kicad_footprint")
    store.reject(_by_kind(retained, KIND_MODEL).candidate_id, "the person prefers their own model")
    reloaded = RetainedCandidateStore(tmp_path / "Candidates")
    assert reloaded.candidate(footprint.candidate_id).selected_slot == "kicad_footprint"
    assert reloaded.candidate(_by_kind(retained, KIND_MODEL).candidate_id).rejected is True


# --- Altium and P-CAD containers -------------------------------------------
# What a tested reader returns is claimed and nothing else: entry names, not geometry.

_ALTIUM_FIXTURES = Path(__file__).resolve().parents[1] / "altium" / "fixtures"


def test_a_native_schlib_is_validated_by_its_entry_name_only(tmp_path):
    facts = inspect_artifact(_ALTIUM_FIXTURES / "sample.SchLib", expected_mpn=MPN)
    assert facts.outcome is ValidationOutcome.READY_TO_IMPORT
    assert facts.detected_format == "altium_schlib"
    assert facts.mpn == MPN
    # the container's geometry and electrical content are explicitly NOT claimed
    assert any("not validated here" in message for message in facts.messages)
    assert facts.pins == () and facts.pads == ()


def test_a_native_schlib_for_another_part_is_a_component_mismatch():
    facts = inspect_artifact(_ALTIUM_FIXTURES / "sample.SchLib", expected_mpn="NOT-THIS-PART")
    assert facts.outcome is ValidationOutcome.COMPONENT_MISMATCH


def test_a_native_pcblib_is_validated_by_its_package_entry():
    facts = inspect_artifact(
        _ALTIUM_FIXTURES / "sample.PcbLib",
        expected_mpn=MPN,
        expected_package="DIOM5227X270N",
    )
    assert facts.outcome is ValidationOutcome.READY_TO_IMPORT
    assert facts.package == "DIOM5227X270N"
    facts = inspect_artifact(
        _ALTIUM_FIXTURES / "sample.PcbLib", expected_mpn=MPN, expected_package="SOD-123"
    )
    assert facts.outcome is ValidationOutcome.PACKAGE_MISMATCH


def test_an_intlib_container_is_manual_review_not_a_native_validation(tmp_path):
    compiled = tmp_path / "Library.IntLib"
    compiled.write_bytes((_ALTIUM_FIXTURES / "sample.SchLib").read_bytes())
    facts = inspect_artifact(compiled, expected_mpn=MPN)
    assert facts.outcome is ValidationOutcome.MANUAL_REVIEW_REQUIRED
    assert any("only the compiled Altium container" in m for m in facts.messages)


def test_an_intlib_that_is_not_an_ole_container_is_invalid(tmp_path):
    compiled = tmp_path / "Library.IntLib"
    compiled.write_text("not a compound file", encoding="utf-8")
    assert inspect_artifact(compiled).outcome is ValidationOutcome.INVALID_FILE


def test_an_unparseable_pcad_library_is_invalid(tmp_path):
    lia = tmp_path / "part.lia"
    lia.write_text('ACCEL_ASCII "X"\n(symbolDef "S")\n', encoding="utf-8")
    facts = inspect_artifact(lia, expected_mpn=MPN)
    assert facts.outcome is ValidationOutcome.INVALID_FILE
    assert facts.detected_format == "pcad_ascii_library"


def test_a_wrl_model_is_retained_but_never_claimed_valid(tmp_path):
    model = tmp_path / "part.wrl"
    model.write_text("#VRML V2.0 utf8\n", encoding="utf-8")
    facts = inspect_artifact(model)
    assert facts.outcome is ValidationOutcome.MANUAL_REVIEW_REQUIRED
    assert any("no tested VRML parser" in message for message in facts.messages)


def test_a_prohibited_artifact_is_an_invalid_file(tmp_path):
    payload = tmp_path / "setup.exe"
    payload.write_bytes(b"MZ")
    facts = inspect_artifact(payload)
    assert facts.outcome is ValidationOutcome.INVALID_FILE
    assert facts.kind == "prohibited"
