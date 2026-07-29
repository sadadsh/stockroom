"""Convert a recognized Ultra Librarian Altium script package to native libraries.

Ultra Librarian's "Altium Designer (script based)" export is not a CAD library.  It is an
Altium scripting project containing one ASCII component payload and the provider's importer.
This module turns that package into the native ``.SchLib``/``.PcbLib`` pair Stockroom can verify
and attach.

The downloaded package is executable code, so recognition is deliberately narrow:

* exactly one ``UL_Import.pas`` is present;
* its directory contains exactly one ``.PrjScr`` and one ``.txt`` payload;
* the project references that importer;
* the payload filename agrees with the requested MPN; and
* the importer contains the measured Ultra Librarian entry point and native-output operations.

Only a sandbox copy is modified and executed.  The provider download remains untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from unicodedata import normalize

from stockroom.altium.driver import AltiumDriver
from stockroom.altium.embed3d import delphi_quote
from stockroom.altium.oleread import read_footprint_names, read_symbol_names
from stockroom.ingest.sandbox import unpack_inputs

_SCHEMA = "stockroom.ul-altium-import/1"
_IMPORT_NAME = "ul_import.pas"
# SHA-256 of the real 42,296-byte UL_Import.pas delivered by DigiKey's embedded Ultra Librarian
# exporter for TPD6E05U06RVZR on 2026-07-28. Downloaded provider code is executable code: a future
# revision must be reviewed and added explicitly, never accepted because it resembles this one.
_APPROVED_IMPORTER_REVISIONS = {
    "b72e1c403b593203355fed535d4fd7cadb9aea645378f2de8999d42b2648e4af": 26,
}
_APPROVED_STATIC_MEMBER_SHA256 = {
    "ul_form.pas": "d7ccdcbe73dd1952be590a0c2aa44ca75ade59ad02e665baee2df9c104337449",
    "ul_form.dfm": "83d07d5ca1bdc034a33aa31e1bd972b3c6acf31b668c7cb9e70decaf73a5fe32",
    ".prjscr": "2b4c327ec41a351d16930be994458834afb5742c57edd2ce8deb1b47172887a9",
}
_REQUIRED_IMPORT_MARKERS = (
    "Procedure ImportAscIIData(InFileName : String);",
    "InitLibDocs(",
    "DoSafeChangeFileNameAndSave(BasePath + '.PcbLib'",
    "DoSafeChangeFileNameAndSave(BasePath + '.SchLib'",
)


class UltraLibrarianImportError(RuntimeError):
    """A detected UL script package could not be converted safely."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _preflight_script_archive(path: Path) -> None:
    """Reject unsafe or unreviewed script archives before extraction."""

    if not path.is_file() or not zipfile.is_zipfile(path):
        return
    with zipfile.ZipFile(path) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if not any(PurePosixPath(item.filename).name.casefold() == _IMPORT_NAME for item in files):
            return
        if len(files) != 6:
            raise UltraLibrarianImportError(
                f"the Ultra Librarian script archive has {len(files)} files; expected six"
            )
        folded: set[str] = set()
        for item in files:
            name = item.filename
            pure = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or pure.is_absolute()
                or ".." in pure.parts
                or ":" in pure.parts[0]
            ):
                raise UltraLibrarianImportError(
                    f"the Ultra Librarian archive has an unsafe member: {name!r}"
                )
            key = name.casefold()
            if key in folded:
                raise UltraLibrarianImportError(
                    "the Ultra Librarian archive has duplicate or case-colliding members"
                )
            folded.add(key)
            unix_mode = item.external_attr >> 16
            if item.create_system == 3 and stat.S_IFMT(unix_mode) not in {0, stat.S_IFREG}:
                raise UltraLibrarianImportError(
                    f"the Ultra Librarian archive has a non-regular member: {name!r}"
                )
            if item.flag_bits & 0x1:
                raise UltraLibrarianImportError("the Ultra Librarian script archive is encrypted")
            if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise UltraLibrarianImportError(
                    "the Ultra Librarian script archive uses unsupported compression"
                )
            if item.file_size <= 0 or item.file_size > 5 * 1024 * 1024:
                raise UltraLibrarianImportError(
                    f"the Ultra Librarian archive member has an unsafe size: {name!r}"
                )
            if item.compress_size and item.file_size / item.compress_size > 100:
                raise UltraLibrarianImportError(
                    f"the Ultra Librarian archive member has an unsafe compression ratio: {name!r}"
                )
            if pure.suffix.casefold() in {".zip", ".7z", ".rar", ".tar"}:
                raise UltraLibrarianImportError(
                    "the Ultra Librarian script archive contains a nested archive"
                )

        roots = [item for item in files if len(PurePosixPath(item.filename).parts) == 1]
        altium = [
            item
            for item in files
            if len(PurePosixPath(item.filename).parts) == 2
            and PurePosixPath(item.filename).parts[0].casefold() == "altiumdesigner"
        ]
        if (
            len(roots) != 1
            or PurePosixPath(roots[0].filename).suffix.casefold() not in {".step", ".stp"}
            or len(altium) != 5
        ):
            raise UltraLibrarianImportError(
                "the Ultra Librarian script archive does not match the reviewed six-file shape"
            )
        names = {PurePosixPath(item.filename).name.casefold(): item for item in altium}
        if (
            len(names) != 5
            or not {"ul_import.pas", "ul_form.pas", "ul_form.dfm"} <= set(names)
            or sum(name.endswith(".txt") for name in names) != 1
            or sum(name.endswith(".prjscr") for name in names) != 1
        ):
            raise UltraLibrarianImportError(
                "the Ultra Librarian Altium directory has unexpected members"
            )
        for member_name in ("ul_form.pas", "ul_form.dfm"):
            if (
                _sha256_bytes(archive.read(names[member_name]))
                != _APPROVED_STATIC_MEMBER_SHA256[member_name]
            ):
                raise UltraLibrarianImportError(
                    f"the Ultra Librarian static member is not reviewed: {member_name}"
                )
        project_name = next(name for name in names if name.endswith(".prjscr"))
        if (
            _sha256_bytes(archive.read(names[project_name]))
            != _APPROVED_STATIC_MEMBER_SHA256[".prjscr"]
        ):
            raise UltraLibrarianImportError(
                "the Ultra Librarian scripting project revision is not reviewed"
            )


@dataclass(frozen=True)
class UltraLibrarianScriptPackage:
    """The single, recognized provider import unit inside a sandbox copy."""

    project: Path
    importer: Path
    payload: Path
    schlib: Path
    pcblib: Path
    symbol_name: str
    footprint_name: str


@dataclass(frozen=True)
class UltraLibrarianImportResult:
    """Verified native outputs and the retained conversion evidence."""

    schlib: Path
    pcblib: Path
    marker: Path
    workdir: Path

    @property
    def libraries(self) -> tuple[Path, Path]:
        return self.schlib, self.pcblib

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def _identity_key(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def _unique_payload_value(payload_text: str, pattern: str, label: str) -> str:
    values = {
        normalize("NFKC", match.group(1)).strip()
        for match in re.finditer(pattern, payload_text, flags=re.MULTILINE)
    }
    if len(values) != 1 or not next(iter(values), ""):
        raise UltraLibrarianImportError(
            f"the Ultra Librarian payload does not contain one exact {label}"
        )
    return next(iter(values))


def _payload_contract(
    payload: Path,
    *,
    expected_manufacturer: str,
    expected_mpn: str,
    step_names: frozenset[str],
) -> tuple[str, str]:
    try:
        text = payload.read_text(encoding="cp1252")
    except UnicodeError as exc:
        raise UltraLibrarianImportError(
            "the Ultra Librarian ASCII component payload is not Windows-1252 text"
        ) from exc
    if not text.startswith("# Created by Ultra Librarian "):
        raise UltraLibrarianImportError("the ASCII component payload has no Ultra Librarian header")
    component = _unique_payload_value(
        text,
        r'^Component \(Name "([^"\r\n]+)"\)',
        "component name",
    )
    footprint = _unique_payload_value(
        text,
        r'^Footprint \(Name "([^"\r\n]+)"\)',
        "footprint name",
    )
    manufacturer = _unique_payload_value(
        text,
        r'^Parameter \(Name "Manufacturer_Name"\).*?\(Value "([^"\r\n]+)"\)',
        "manufacturer",
    )
    mpn = _unique_payload_value(
        text,
        r'^Parameter \(Name "Manufacturer_Part_Number"\).*?\(Value "([^"\r\n]+)"\)',
        "manufacturer part number",
    )
    if _identity_key(component) != _identity_key(expected_mpn):
        raise UltraLibrarianImportError(
            f"the Ultra Librarian component {component!r} does not match MPN {expected_mpn!r}"
        )
    if _identity_key(mpn) != _identity_key(expected_mpn):
        raise UltraLibrarianImportError(
            f"the Ultra Librarian embedded MPN {mpn!r} does not match {expected_mpn!r}"
        )
    if _identity_key(manufacturer) != _identity_key(expected_manufacturer):
        raise UltraLibrarianImportError(
            "the Ultra Librarian embedded manufacturer "
            f"{manufacturer!r} does not match {expected_manufacturer!r}"
        )
    for match in re.finditer(
        r'^Step \(Name "([^"\r\n]+)"\)',
        text,
        flags=re.MULTILINE,
    ):
        step_name = normalize("NFKC", match.group(1)).strip()
        if (
            not step_name
            or Path(step_name).name != step_name
            or "/" in step_name
            or "\\" in step_name
            or step_name.casefold() not in step_names
        ):
            raise UltraLibrarianImportError(
                f"the Ultra Librarian payload has an unsafe or missing STEP reference: {step_name!r}"
            )
    return component, footprint


def _casefold_glob(directory: Path, suffix: str) -> list[Path]:
    wanted = suffix.casefold()
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() == wanted
        ),
        key=lambda path: path.name.casefold(),
    )


def _recognize_package(
    roots: Iterable[Path],
    *,
    expected_manufacturer: str,
    expected_mpn: str,
) -> UltraLibrarianScriptPackage | None:
    roots = tuple(Path(root) for root in roots)
    importers = sorted(
        (
            path
            for root in roots
            for path in root.rglob("*")
            if path.is_file() and path.name.casefold() == _IMPORT_NAME
        ),
        key=lambda path: str(path).casefold(),
    )
    if not importers:
        return None
    if len(importers) != 1:
        raise UltraLibrarianImportError(
            f"the download contains {len(importers)} Ultra Librarian importers; expected one"
        )

    importer = importers[0]
    package_roots = [root for root in roots if importer.is_relative_to(root)]
    if len(package_roots) != 1:
        raise UltraLibrarianImportError(
            "the Ultra Librarian importer has an ambiguous sandbox root"
        )
    package_root = package_roots[0]
    directory = importer.parent
    projects = _casefold_glob(directory, ".PrjScr")
    payloads = _casefold_glob(directory, ".txt")
    if len(projects) != 1 or len(payloads) != 1:
        raise UltraLibrarianImportError(
            "the Ultra Librarian importer directory must contain exactly one PrjScr and one "
            "ASCII component payload"
        )
    project = projects[0]
    payload = payloads[0]
    package_files = sorted(
        (path for path in package_root.rglob("*") if path.is_file()),
        key=lambda path: str(path).casefold(),
    )
    root_steps = [
        path
        for path in package_files
        if path.parent == package_root and path.suffix.casefold() in {".step", ".stp"}
    ]
    if len(package_files) != 6 or len(root_steps) != 1:
        raise UltraLibrarianImportError(
            "the Ultra Librarian script package does not match the reviewed six-file shape"
        )
    form_pas = directory / "UL_Form.pas"
    form_dfm = directory / "UL_Form.dfm"
    if not form_pas.is_file() or not form_dfm.is_file():
        raise UltraLibrarianImportError(
            "the Ultra Librarian script package is missing its reviewed static members"
        )
    expected_key = _identity_key(expected_mpn)
    if not expected_key or _identity_key(payload.stem) != expected_key:
        raise UltraLibrarianImportError(
            f"the Ultra Librarian payload {payload.name!r} does not match MPN {expected_mpn!r}"
        )

    try:
        importer_digest = hashlib.sha256(importer.read_bytes()).hexdigest()
        importer_text = importer.read_text(encoding="utf-8-sig")
        project_text = project.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise UltraLibrarianImportError(
            "the Ultra Librarian scripting project is not readable text"
        ) from exc
    if importer_digest not in _APPROVED_IMPORTER_REVISIONS:
        raise UltraLibrarianImportError(
            "the Ultra Librarian importer revision has not been reviewed; refusing to execute "
            f"SHA-256 {importer_digest}"
        )
    for static_path, key in ((form_pas, "ul_form.pas"), (form_dfm, "ul_form.dfm")):
        if (
            hashlib.sha256(static_path.read_bytes()).hexdigest()
            != _APPROVED_STATIC_MEMBER_SHA256[key]
        ):
            raise UltraLibrarianImportError(
                f"the Ultra Librarian static member is not reviewed: {static_path.name}"
            )
    if (
        hashlib.sha256(project.read_bytes()).hexdigest()
        != _APPROVED_STATIC_MEMBER_SHA256[".prjscr"]
    ):
        raise UltraLibrarianImportError(
            "the Ultra Librarian scripting project revision is not reviewed"
        )
    missing = [marker for marker in _REQUIRED_IMPORT_MARKERS if marker not in importer_text]
    if missing:
        raise UltraLibrarianImportError(
            "the Ultra Librarian importer does not match the supported native-library contract"
        )
    document_paths = {
        match.group(1).strip().replace("/", "\\").casefold()
        for match in re.finditer(
            r"(?im)^\s*DocumentPath\s*=\s*([^\r\n]+?)\s*$",
            project_text,
        )
    }
    if importer.name.casefold() not in {
        Path(document.replace("\\", "/")).name.casefold() for document in document_paths
    }:
        raise UltraLibrarianImportError(
            "the Ultra Librarian project does not reference its importer"
        )
    symbol_name, footprint_name = _payload_contract(
        payload,
        expected_manufacturer=expected_manufacturer,
        expected_mpn=expected_mpn,
        step_names=frozenset(path.name.casefold() for path in root_steps),
    )

    return UltraLibrarianScriptPackage(
        project=project,
        importer=importer,
        payload=payload,
        schlib=payload.with_suffix(".SchLib"),
        pcblib=payload.with_suffix(".PcbLib"),
        symbol_name=symbol_name,
        footprint_name=footprint_name,
    )


def _patch_reviewed_dialogs(importer_text: str, *, expected_calls: int) -> str:
    """Capture provider errors without showing dialogs; ignore one reviewed AD26 notice."""

    observed_calls = importer_text.count("ShowMessage(")
    if observed_calls != expected_calls:
        raise UltraLibrarianImportError(
            "the reviewed Ultra Librarian importer dialog contract changed "
            f"({observed_calls} calls, expected {expected_calls})"
        )
    if not observed_calls:
        return importer_text
    info_call = "ShowMessage('NOTE: This version of Altium has issues"
    if importer_text.count(info_call) != 1:
        raise UltraLibrarianImportError(
            "the reviewed Ultra Librarian informational-dialog contract changed"
        )
    patched = importer_text.replace(
        info_call,
        "StockroomIgnoreMessage('NOTE: This version of Altium has issues",
        1,
    )
    patched = patched.replace("ShowMessage(", "StockroomCaptureMessage(")

    global_var = "    BrokenSCHFontManager : Integer; // for Alitum 19's broken SCH FontManager"
    first_function = "Function CheckLeft(BaseStr: String, Srch: String): Boolean;"
    if patched.count(global_var) != 1 or patched.count(first_function) != 1:
        raise UltraLibrarianImportError("the reviewed Ultra Librarian declaration anchors changed")
    patched = patched.replace(
        global_var,
        global_var + "\n    StockroomProviderMessage : String;",
        1,
    )
    sink = """\
Procedure StockroomIgnoreMessage(MessageText : String);
Begin
End;

Procedure StockroomCaptureMessage(MessageText : String);
Begin
    If StockroomProviderMessage = '' Then
        StockroomProviderMessage := MessageText;
End;

"""
    return patched.replace(first_function, sink + first_function, 1)


def _patch_ad26_default_symbol(importer_text: str) -> str:
    """Remove the blank symbol AD26 creates when opening a new SchLib.

    The reviewed provider importer asks Altium to create a new schematic library and then adds
    the payload component. AD26 initializes that document with ``Component_1``; unless it is
    removed before parsing, the resulting library contains both identities and must fail exact
    readback. Patch only the pinned InitLibDocs body in the sandbox copy.
    """

    function_start = "Function InitLibDocs(BasePath: String,"
    function_end = "\nEnd;\n\nProcedure ImportAscIIData(InFileName : String);"
    if importer_text.count(function_start) != 1 or importer_text.count(function_end) != 1:
        raise UltraLibrarianImportError(
            "the reviewed Ultra Librarian library-initialization anchors changed"
        )
    before, remainder = importer_text.split(function_start, 1)
    body, after = remainder.split(function_end, 1)
    declaration_anchor = "    WorkSpace : IWorkSpace;\nBegin"
    removal_anchor = """\
    If sLib = Nil Then Begin
        ShowMessage('Nil sLib');
        Exit;
    End;
    // Done"""
    if body.count(declaration_anchor) != 1 or body.count(removal_anchor) != 1:
        raise UltraLibrarianImportError(
            "the reviewed Ultra Librarian default-symbol anchors changed"
        )
    body = body.replace(
        declaration_anchor,
        "    WorkSpace : IWorkSpace;\n    StockroomDefaultComponent : ISch_Component;\nBegin",
        1,
    )
    body = body.replace(
        removal_anchor,
        """\
    If sLib = Nil Then Begin
        ShowMessage('Nil sLib');
        Exit;
    End;
    StockroomDefaultComponent := sLib.GetState_SchComponentByLibRef('Component_1');
    If StockroomDefaultComponent <> Nil Then
        sLib.RemoveSchComponent(StockroomDefaultComponent);
    // Done""",
        1,
    )
    return before + function_start + body + function_end + after


def render_stockroom_wrapper(
    *,
    payload_win: str,
    schlib_win: str,
    pcblib_win: str,
    marker_win: str,
) -> str:
    """Render the parameterless, observable entry point appended to the sandbox copy."""

    success = json.dumps(
        {"schema": _SCHEMA, "status": "ok"},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    failure = json.dumps(
        {"code": "missing-native-output", "schema": _SCHEMA, "status": "error"},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    provider_failure = json.dumps(
        {"code": "provider-error", "schema": _SCHEMA, "status": "error"},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    exception_failure = json.dumps(
        {"code": "provider-exception", "schema": _SCHEMA, "status": "error"},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"""

Procedure StockroomImport;
Var
    Report : TStringList;
Begin
    Report := TStringList.Create();
    Try
        Try
            StockroomProviderMessage := '';
            ImportAscIIData({delphi_quote(payload_win)});
            If StockroomProviderMessage <> '' Then
                Report.Text := {delphi_quote(provider_failure)}
            Else If FileExists({delphi_quote(schlib_win)}) And
                    FileExists({delphi_quote(pcblib_win)}) Then
                Report.Text := {delphi_quote(success)}
            Else
                Report.Text := {delphi_quote(failure)};
        Except
            Report.Text := {delphi_quote(exception_failure)};
        End;
        Report.SaveToFile({delphi_quote(marker_win)});
    Finally
        Report.Free;
        TerminateWithExitCode(0);
    End;
End;
"""


def convert_ul_altium_package(
    inputs: Iterable[Path],
    *,
    expected_manufacturer: str,
    expected_mpn: str,
    driver: AltiumDriver | None = None,
    timeout: int = 300,
) -> UltraLibrarianImportResult | None:
    """Convert one recognized UL script package, or return ``None`` when none is present."""

    if not isinstance(expected_manufacturer, str) or not expected_manufacturer.strip():
        raise ValueError("expected_manufacturer must be canonical non-empty text")
    if expected_manufacturer != expected_manufacturer.strip():
        raise ValueError("expected_manufacturer must not contain surrounding whitespace")
    if not isinstance(expected_mpn, str) or not expected_mpn.strip():
        raise ValueError("expected_mpn must be canonical non-empty text")
    if expected_mpn != expected_mpn.strip():
        raise ValueError("expected_mpn must not contain surrounding whitespace")

    input_paths = [Path(path) for path in inputs]
    for path in input_paths:
        _preflight_script_archive(path)

    workdir = Path(tempfile.mkdtemp(prefix="sr-ul-altium-"))
    retain_workdir = False
    unpack_root = workdir / "Inputs"
    evidence_root = workdir / "Evidence"
    evidence_root.mkdir(parents=True)
    try:
        try:
            unpacked = unpack_inputs(input_paths, unpack_root)
        except Exception as exc:
            raise UltraLibrarianImportError(
                f"could not unpack the Ultra Librarian download: {exc}"
            ) from exc
        package = _recognize_package(
            (item.root for item in unpacked),
            expected_manufacturer=expected_manufacturer,
            expected_mpn=expected_mpn,
        )
        if package is None:
            return None
        native_outputs = [
            path
            for item in unpacked
            for path in item.root.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".schlib", ".pcblib", ".libpkg"}
        ]
        if native_outputs:
            raise UltraLibrarianImportError(
                "the script package already contains native outputs; refusing a stale conversion"
            )

        marker = evidence_root / "Ultra Librarian Import Result.json"
        drv = driver or AltiumDriver()
        original = package.importer.read_text(encoding="utf-8-sig")
        importer_digest = hashlib.sha256(package.importer.read_bytes()).hexdigest()
        patched = _patch_ad26_default_symbol(original)
        patched = _patch_reviewed_dialogs(
            patched,
            expected_calls=_APPROVED_IMPORTER_REVISIONS[importer_digest],
        )
        wrapper = render_stockroom_wrapper(
            payload_win=drv.host.to_windows_path(str(package.payload)),
            schlib_win=drv.host.to_windows_path(str(package.schlib)),
            pcblib_win=drv.host.to_windows_path(str(package.pcblib)),
            marker_win=drv.host.to_windows_path(str(marker)),
        )
        package.importer.write_text(
            patched.rstrip() + "\r\n" + wrapper.lstrip(),
            encoding="utf-8",
            newline="\r\n",
        )
        # Do not run the provider's broad project (it includes a GUI form and extensive unrelated
        # project settings). Build the smallest project that can expose the reviewed importer entry.
        run_project = package.importer.parent / "Stockroom UL Import.PrjScr"
        run_project.write_text(
            "[Design]\r\n"
            "Version=1.0\r\n"
            "HierarchyMode=0\r\n"
            "[Document1]\r\n"
            f"DocumentPath={package.importer.name}\r\n",
            encoding="utf-8",
            newline="",
        )

        outcome = drv.run_script(
            project=run_project,
            proc=f"{package.importer.name}>StockroomImport",
            marker=marker,
            timeout=timeout,
        )
        if not outcome.ok:
            raise UltraLibrarianImportError(
                f"Altium could not convert the Ultra Librarian package: {outcome.detail}"
            )
        try:
            report = json.loads(outcome.marker_text)
        except json.JSONDecodeError as exc:
            raise UltraLibrarianImportError(
                "Altium returned an unreadable Ultra Librarian conversion result"
            ) from exc
        if report != {"schema": _SCHEMA, "status": "ok"}:
            code = report.get("code", "unknown") if isinstance(report, dict) else "unknown"
            raise UltraLibrarianImportError(
                f"Altium did not produce both native Ultra Librarian outputs ({code})"
            )
        try:
            symbol_names = read_symbol_names(package.schlib)
            footprint_names = read_footprint_names(package.pcblib)
        except Exception as exc:
            raise UltraLibrarianImportError(
                f"Altium produced an unreadable native library: {exc}"
            ) from exc
        if symbol_names != [package.symbol_name]:
            raise UltraLibrarianImportError(
                "Altium output symbol identity does not match the provider payload "
                f"({symbol_names!r} != {[package.symbol_name]!r})"
            )
        if footprint_names != [package.footprint_name]:
            raise UltraLibrarianImportError(
                "Altium output footprint identity does not match the provider payload "
                f"({footprint_names!r} != {[package.footprint_name]!r})"
            )
        result = UltraLibrarianImportResult(
            schlib=package.schlib,
            pcblib=package.pcblib,
            marker=marker,
            workdir=workdir,
        )
        retain_workdir = True
        return result
    finally:
        if not retain_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


__all__ = [
    "UltraLibrarianImportError",
    "UltraLibrarianImportResult",
    "UltraLibrarianScriptPackage",
    "convert_ul_altium_package",
    "render_stockroom_wrapper",
]
