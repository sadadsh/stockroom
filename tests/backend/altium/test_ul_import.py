from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from stockroom.altium import ul_import as ul_import_module
from stockroom.altium.converter import NativeAltiumConversion
from stockroom.altium.driver import RunOutcome
from stockroom.altium.oleread import read_footprint_names, read_symbol_names
from stockroom.altium.ul_import import (
    UltraLibrarianImportError,
    convert_ul_altium_package,
    render_stockroom_wrapper,
)
from tests.backend.pcad.test_normalize import SYNTHETIC as PCAD_LIBRARY

FIX = Path(__file__).parent / "fixtures"
SCHEMA = "stockroom.ul-altium-import/1"

IMPORTER = """\
Var
    BrokenSCHFontManager : Integer; // for Alitum 19's broken SCH FontManager

Function CheckLeft(BaseStr: String, Srch: String): Boolean;
Begin
    ShowMessage('NOTE: This version of Altium has issues in the test fixture');
    Result := True;
End;

Function InitLibDocs(BasePath: String, Out sLib : ISch_Document): Boolean;
Var
    WorkSpace : IWorkSpace;
Begin
    sLib := SchServer.GetSchDocumentByPath(BasePath + '.SchLib');
    If sLib = Nil Then Begin
        ShowMessage('Nil sLib');
        Exit;
    End;
    // Done
    Result := True;
End;

Procedure ImportAscIIData(InFileName : String);
Begin
    InitLibDocs(
    DoSafeChangeFileNameAndSave(BasePath + '.PcbLib', cDocKind_PcbLib);
    DoSafeChangeFileNameAndSave(BasePath + '.SchLib', cDocKind_SchLib);
End;
"""

PROJECT = """\
[Design]
Version=1.0
[Document1]
DocumentPath=UL_Import.pas
"""

MANUFACTURER = "ON Semiconductor"
MPN = "S1M"
FOOTPRINT = "DIOM5227X270N"


class _Host:
    @staticmethod
    def to_windows_path(path: str) -> str:
        return path


class _Driver:
    host = _Host()

    def __init__(self, *, report: dict | None = None) -> None:
        self.report = report or {"schema": SCHEMA, "status": "ok"}
        self.calls: list[dict] = []

    def run_script(self, **kwargs) -> RunOutcome:
        self.calls.append(kwargs)
        project = Path(kwargs["project"])
        payload = next(project.parent.glob("*.txt"))
        if self.report.get("status") == "ok":
            shutil.copy2(FIX / "sample.SchLib", payload.with_suffix(".SchLib"))
            shutil.copy2(FIX / "sample.PcbLib", payload.with_suffix(".PcbLib"))
        marker_text = json.dumps(
            self.report,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        Path(kwargs["marker"]).write_text(marker_text, encoding="utf-8")
        return RunOutcome("ok", "converted", marker_text)


def _package(
    tmp_path: Path,
    *,
    manufacturer: str = MANUFACTURER,
    mpn: str = MPN,
    component: str | None = None,
) -> Path:
    source = tmp_path / "Provider"
    source.mkdir()
    (source / "UL_Import.pas").write_text(IMPORTER, encoding="utf-8")
    (source / "UL_Form.pas").write_text("unit UL_Form;\n", encoding="utf-8")
    (source / "UL_Form.dfm").write_text("object ULForm: TULForm\nend\n", encoding="utf-8")
    (source / f"UL_Import_{mpn}.PrjScr").write_text(PROJECT, encoding="utf-8")
    (source / f"{mpn}.txt").write_text(
        "# Created by Ultra Librarian 8.3.384\n"
        f'Component (Name "{component or mpn}")\n'
        f'Footprint (Name "{FOOTPRINT}")\n'
        f'Parameter (Name "Manufacturer_Name") (Value "{manufacturer}")\n'
        f'Parameter (Name "Manufacturer_Part_Number") (Value "{mpn}")\n',
        encoding="cp1252",
    )
    step = tmp_path / f"{FOOTPRINT}.stp"
    step.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="ascii")
    archive = tmp_path / f"{mpn}.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(step, step.name)
        for path in source.iterdir():
            output.write(path, f"AltiumDesigner/{path.name}")
    return archive


def _approve_static_members(monkeypatch: pytest.MonkeyPatch, archive: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        names = {Path(name).name.casefold(): name for name in source.namelist()}
        static = {
            "ul_form.pas": hashlib.sha256(source.read(names["ul_form.pas"])).hexdigest(),
            "ul_form.dfm": hashlib.sha256(source.read(names["ul_form.dfm"])).hexdigest(),
            ".prjscr": hashlib.sha256(
                source.read(next(name for key, name in names.items() if key.endswith(".prjscr")))
            ).hexdigest(),
        }
    monkeypatch.setattr(ul_import_module, "_APPROVED_STATIC_MEMBER_SHA256", static)


def _approve_archive(monkeypatch: pytest.MonkeyPatch, archive: Path) -> None:
    _approve_static_members(monkeypatch, archive)
    with zipfile.ZipFile(archive) as source:
        digest = hashlib.sha256(source.read("AltiumDesigner/UL_Import.pas")).hexdigest()
    monkeypatch.setattr(
        ul_import_module,
        "_APPROVED_IMPORTER_REVISIONS",
        {digest: IMPORTER.count("ShowMessage(")},
    )


def test_ul_script_package_converts_a_sandbox_copy_to_native_libraries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path)
    _approve_archive(monkeypatch, archive)
    original = archive.read_bytes()
    driver = _Driver()

    result = convert_ul_altium_package(
        [archive],
        expected_manufacturer=MANUFACTURER,
        expected_mpn=MPN,
        driver=driver,
    )

    assert result is not None
    assert read_symbol_names(result.schlib) == ["S1M"]
    assert read_footprint_names(result.pcblib) == ["DIOM5227X270N"]
    assert result.preferred_footprint == "DIOM5227X270N"
    assert archive.read_bytes() == original
    assert driver.calls[0]["proc"] == "UL_Import.pas>StockroomImport"
    assert driver.calls[0]["project"].name == "Stockroom UL Import.PrjScr"
    project = driver.calls[0]["project"].read_text(encoding="utf-8")
    assert "DocumentPath=UL_Import.pas" in project
    assert "UL_Form.pas" not in project
    importer = result.schlib.parent / "UL_Import.pas"
    script = importer.read_text(encoding="utf-8")
    assert "Procedure StockroomImport;" in script
    assert "ImportAscIIData(" in script
    assert "TerminateWithExitCode(0)" in script
    assert "ShowMessage(" not in script
    assert "sLib.RemoveSchComponent(StockroomDefaultComponent)" in script
    assert result.workdir.exists()
    result.cleanup()
    assert not result.workdir.exists()


def test_manual_intake_does_not_launch_altium_for_a_script_only_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path)
    _approve_archive(monkeypatch, archive)
    driver = _Driver()

    with pytest.raises(UltraLibrarianImportError, match="requires Altium"):
        convert_ul_altium_package(
            [archive],
            expected_manufacturer=MANUFACTURER,
            expected_mpn=MPN,
            driver=driver,
            allow_altium=False,
        )

    assert driver.calls == []


def test_pcad_package_converts_without_launching_altium(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    source = tmp_path / "P-CAD Source"
    source.mkdir()
    lia = source / "EXACT-LONG-MPN.lia"
    lia.write_text(PCAD_LIBRARY, encoding="ascii")
    step = source / "DEFAULT.step"
    step.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="ascii")
    archive = tmp_path / "EXACT-LONG-MPN.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(lia, f"AltiumV15/{lia.name}")
        output.write(step, step.name)
    kicad_archive = tmp_path / "EXACT-LONG-MPN-KiCad.zip"
    with zipfile.ZipFile(kicad_archive, "w") as output:
        output.writestr(
            "EXACT-LONG-MPN.step",
            "ISO-10303-21;\n/* KiCad companion */\nEND-ISO-10303-21;\n",
        )

    calls: list[tuple[Path, Path, Path | None]] = []

    def convert_pcad_ascii(
        source_lia: Path,
        output_directory: Path,
        *,
        step_model: Path | None = None,
    ) -> NativeAltiumConversion:
        output_directory.mkdir(parents=True)
        schlib = output_directory / "EXACT-LONG-MPN.SchLib"
        pcblib = output_directory / "EXACT-LONG-MPN.PcbLib"
        shutil.copy2(FIX / "sample.SchLib", schlib)
        shutil.copy2(FIX / "sample.PcbLib", pcblib)
        calls.append((source_lia, output_directory, step_model))
        return NativeAltiumConversion(
            symbol_library=schlib,
            footprint_library=pcblib,
            symbol_entries=("EXACT-LONG-MPN",),
            footprint_entries=("DEFAULT", "MEDIUM", "LARGE"),
            source_sha256=hashlib.sha256(source_lia.read_bytes()).hexdigest(),
        )

    monkeypatch.setattr(
        "stockroom.altium.converter.convert_pcad_ascii",
        convert_pcad_ascii,
    )
    driver = _Driver()

    result = convert_ul_altium_package(
        [kicad_archive, archive],
        expected_manufacturer="Maker LLC",
        expected_mpn="EXACT-LONG-MPN",
        driver=driver,
    )

    assert result is not None
    assert [path.suffix for path in result.libraries] == [".SchLib", ".PcbLib"]
    assert result.preferred_footprint == "DEFAULT"
    assert len(calls) == 1
    assert calls[0][0].name == lia.name
    assert calls[0][2] is not None and calls[0][2].name == step.name
    assert driver.calls == []
    assert json.loads(result.marker.read_text(encoding="utf-8")) == {
        "schema": "stockroom.pcad-native-conversion/1",
        "source_sha256": hashlib.sha256(calls[0][0].read_bytes()).hexdigest(),
        "status": "ok",
    }
    result.cleanup()


def test_no_ul_importer_is_not_misclassified_as_executable_provider_code(tmp_path: Path):
    unrelated = tmp_path / "download.zip"
    with zipfile.ZipFile(unrelated, "w") as output:
        output.writestr("README.txt", "nothing executable")
    assert (
        convert_ul_altium_package(
            [unrelated],
            expected_manufacturer="Example",
            expected_mpn="ABC123",
            driver=_Driver(),
        )
        is None
    )


def test_ul_payload_must_match_the_requested_mpn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path, mpn="WRONG")
    _approve_archive(monkeypatch, archive)
    with pytest.raises(UltraLibrarianImportError, match="does not match MPN"):
        convert_ul_altium_package(
            [archive],
            expected_manufacturer=MANUFACTURER,
            expected_mpn="EXPECTED",
            driver=_Driver(),
        )


def test_unreviewed_importer_revision_is_never_executed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path)
    _approve_static_members(monkeypatch, archive)
    driver = _Driver()
    with pytest.raises(UltraLibrarianImportError, match="has not been reviewed"):
        convert_ul_altium_package(
            [archive],
            expected_manufacturer=MANUFACTURER,
            expected_mpn=MPN,
            driver=driver,
        )
    assert driver.calls == []


def test_lookalike_importer_without_native_output_contract_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path)
    rewritten = tmp_path / "lookalike.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rewritten, "w") as output:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith("UL_Import.pas"):
                data = b"Procedure ImportAscIIData(InFileName : String); Begin End;"
            output.writestr(name, data)
    _approve_archive(monkeypatch, rewritten)
    with pytest.raises(UltraLibrarianImportError, match="supported native-library contract"):
        convert_ul_altium_package(
            [rewritten],
            expected_manufacturer=MANUFACTURER,
            expected_mpn=MPN,
            driver=_Driver(),
        )


def test_missing_native_outputs_is_a_failed_conversion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path)
    _approve_archive(monkeypatch, archive)
    with pytest.raises(UltraLibrarianImportError, match="did not produce both"):
        convert_ul_altium_package(
            [archive],
            expected_manufacturer=MANUFACTURER,
            expected_mpn=MPN,
            driver=_Driver(
                report={
                    "code": "missing-native-output",
                    "schema": SCHEMA,
                    "status": "error",
                }
            ),
        )


def test_wrapper_quotes_windows_paths_and_writes_a_terminal_marker():
    text = render_stockroom_wrapper(
        payload_win=r"C:\Users\O'Brien\Part.txt",
        schlib_win=r"C:\Run\Part.SchLib",
        pcblib_win=r"C:\Run\Part.PcbLib",
        marker_win=r"C:\Run\Result.json",
    )
    assert r"'C:\Users\O''Brien\Part.txt'" in text
    assert "Report.SaveToFile('C:\\Run\\Result.json')" in text
    assert text.index("Report.SaveToFile") < text.index("TerminateWithExitCode")


def test_reviewed_provider_dialogs_become_nonblocking_and_count_is_pinned():
    source = """\
Var
    BrokenSCHFontManager : Integer; // for Alitum 19's broken SCH FontManager

Function CheckLeft(BaseStr: String, Srch: String): Boolean;
Begin
    ShowMessage('NOTE: This version of Altium has issues in AD26');
    ShowMessage('provider error');
End;
"""
    patched = ul_import_module._patch_reviewed_dialogs(
        source,
        expected_calls=2,
    )
    assert "Procedure StockroomIgnoreMessage" in patched
    assert "Procedure StockroomCaptureMessage" in patched
    assert "StockroomIgnoreMessage('NOTE:" in patched
    assert "StockroomCaptureMessage('provider error')" in patched
    assert patched.index("StockroomProviderMessage : String") < patched.index(
        "Function CheckLeft"
    )
    assert "ShowMessage(" not in patched

    with pytest.raises(UltraLibrarianImportError, match="dialog contract changed"):
        ul_import_module._patch_reviewed_dialogs(
            source,
            expected_calls=1,
        )


def test_unrecognized_extra_archive_member_is_rejected_before_the_driver_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path)
    _approve_archive(monkeypatch, archive)
    rewritten = tmp_path / "extra.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rewritten, "w") as output:
        for name in source.namelist():
            output.writestr(name, source.read(name))
        output.writestr("README.md", "unexpected")
    driver = _Driver()

    with pytest.raises(UltraLibrarianImportError, match="does not match the reviewed script shape"):
        convert_ul_altium_package(
            [rewritten],
            expected_manufacturer=MANUFACTURER,
            expected_mpn=MPN,
            driver=driver,
        )

    assert driver.calls == []


def test_one_altium_step_companion_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path)
    rewritten = tmp_path / "with-altium-step.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rewritten, "w") as output:
        for name in source.namelist():
            output.writestr(name, source.read(name))
        output.writestr("AltiumDesigner/provider-model.step", b"provider step")
    _approve_archive(monkeypatch, rewritten)

    result = convert_ul_altium_package(
        [rewritten],
        expected_manufacturer=MANUFACTURER,
        expected_mpn=MPN,
        driver=_Driver(),
    )

    assert result.schlib.name == f"{MPN}.SchLib"
    assert result.pcblib.name == f"{MPN}.PcbLib"


def test_identity_comparison_preserves_meaningful_punctuation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive = _package(tmp_path, component="S1-M")
    _approve_archive(monkeypatch, archive)

    with pytest.raises(UltraLibrarianImportError, match="component .* does not match MPN"):
        convert_ul_altium_package(
            [archive],
            expected_manufacturer=MANUFACTURER,
            expected_mpn=MPN,
            driver=_Driver(),
        )
