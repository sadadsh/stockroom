"""Automatically install and independently verify the active Altium database library.

Generating ``Stockroom.DbLib`` is not enough. Altium only exposes file-based libraries that have
been installed into its machine preferences, and that preference is durable only after Altium
shuts down cleanly. The convergence sequence therefore has two deliberately separate sessions:

1. install the active ``.DbLib`` and let the driver close Altium gracefully;
2. launch a fresh Altium process, make no installation call, and prove that the persisted library
   still exposes a real database key whose symbol and footprint resolve.

Only that second-session evidence writes a machine-local receipt. A matching receipt avoids
spending an Altium license seat on every Stockroom launch. The receipt names the one accepted
Stockroom-managed DbLib and the installed X2 binary identity. Switching profiles verifies the new
target before removing the receipted predecessor; switching back reinstalls it, while an Altium
upgrade is reverified automatically. Selecting a profile with no generated DbLib removes only
Stockroom-receipted registrations, verifies their absence in a fresh process, and clears the
receipt. Unreceipted user libraries are never cleanup targets.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from stockroom.altium.driver import AltiumDriver, RunOutcome
from stockroom.altium.embed3d import delphi_quote
from stockroom.altium.install import InstallResult, install_library, is_installed, parse_installed
from stockroom.store.machine_config import config_dir

_RECEIPT_SCHEMA = 1
_DEFAULT_TABLE = "Parts"


class _ProbeHost(Protocol):
    def to_windows_path(self, path: str) -> str: ...

    def windows_temp(self) -> Path: ...


class AltiumDriverLike(Protocol):
    """Structural driver seam so persistence logic stays fully testable without Altium."""

    @property
    def host(self) -> _ProbeHost: ...

    @property
    def x2(self) -> Path | None: ...

    def run_script(
        self,
        *,
        proc: str,
        marker: Path,
        project: Path | None = None,
        script: Path | None = None,
        timeout: int = 180,
        allow_busy: bool = False,
        stop_after: bool = True,
        poll_seconds: float = 2.0,
    ) -> RunOutcome: ...


@dataclass(frozen=True)
class PersistenceVerification:
    """Evidence observed in a fresh Altium process that did not install the library."""

    status: str
    detail: str
    installed_paths: tuple[str, ...] = ()
    component_key: str = ""
    symbol_library: str = ""
    footprint_library: str = ""
    placement_parameters: str = ""
    altium_log: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class AltiumConvergenceResult:
    """The automatic setup outcome retained by the host for diagnostics."""

    status: str
    detail: str
    dblib: str = ""
    component_key: str = ""
    symbol_library: str = ""
    footprint_library: str = ""
    receipt_path: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"verified", "already-verified", "no-library"}


@dataclass(frozen=True)
class _ProbeComponent:
    key: str
    symbol_ref: str
    symbol_path: Path
    footprint_ref: str
    footprint_path: Path


@dataclass(frozen=True)
class _OwnedReceipt:
    """One DbLib path Stockroom may manage because its own receipt proves ownership."""

    dblib: Path
    dblib_key: str
    x2: dict[str, object]
    verified_at: str


def _probe_component(dblib: Path) -> tuple[_ProbeComponent | None, str]:
    """Choose a complete real row from Stockroom's generated SQLite source.

    AD26's ``GetAllComponentKeys`` is not a trustworthy enumerator: measured on two real DbLibs,
    it returned zero while ``GetComponentPlacementParameters`` resolved a known MPN from the same
    table. The deterministic source database is the authority for which MPN to probe; Altium still
    has to prove that exact MPN resolves after restart.
    """

    db = dblib.parent / "stockroom-parts.db"
    if not db.exists():
        return None, f"The generated Altium data source is missing at {db.as_posix()}."
    try:
        connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = connection.execute(
                'SELECT "MPN", "Library Ref", "Library Path", '
                '"Footprint Ref", "Footprint Path" FROM "Parts" ORDER BY "MPN"'
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return None, f"The generated Altium data source is unreadable: {exc}"

    first_incomplete = ""
    for raw in rows:
        key, symbol_ref, symbol_raw, footprint_ref, footprint_raw = (
            str(value or "").strip() for value in raw
        )
        if not all((key, symbol_ref, symbol_raw, footprint_ref, footprint_raw)):
            first_incomplete = first_incomplete or key or "<blank MPN>"
            continue
        symbol_path = Path(symbol_raw)
        if not symbol_path.is_absolute():
            symbol_path = dblib.parent / symbol_path
        footprint_path = Path(footprint_raw)
        if not footprint_path.is_absolute():
            footprint_path = dblib.parent / footprint_path
        if not symbol_path.is_file() or not footprint_path.is_file():
            first_incomplete = first_incomplete or key
            continue
        return (
            _ProbeComponent(
                key=key,
                symbol_ref=symbol_ref,
                symbol_path=symbol_path.resolve(strict=False),
                footprint_ref=footprint_ref,
                footprint_path=footprint_path.resolve(strict=False),
            ),
            "",
        )
    if not rows:
        return None, "The generated Altium data source has no parts."
    return (
        None,
        "The generated Altium data source has no row with an MPN and readable symbol and "
        f"footprint assets (first incomplete row: {first_incomplete or '<unknown>'}).",
    )


def _parse_values(log: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (log or "").splitlines():
        line = raw.strip()
        if not line.startswith("SR-") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values.setdefault(key[3:].strip(), value.strip())
    return values


def render_persistence_probe_script(
    *,
    dblib_win: str,
    marker_win: str,
    design_item_id: str,
    table: str = _DEFAULT_TABLE,
    procedure: str = "SRVerifyPersistentLibrary",
) -> str:
    """Render the read-only, fresh-session verification script.

    There is intentionally no ``InstallLibrary`` call. Activating a library that already appears
    in the persisted Installed list loads its database document for inspection without repairing
    a missing preference and thereby manufacturing the evidence this probe exists to obtain.
    """

    return _PROBE_TEMPLATE.format(
        procedure=procedure,
        dblib=delphi_quote(dblib_win),
        marker=delphi_quote(marker_win),
        item=delphi_quote(design_item_id),
        table=delphi_quote(table),
        model_type=delphi_quote("PCBLIB"),
    )


_PROBE_TEMPLATE = """{{ GENERATED by stockroom.altium.convergence -- do not hand-edit.
  This is a FRESH-SESSION probe. It must never install the library it verifies. }}
Procedure {procedure};
Var
    ILM             : IIntegratedLibraryManager;
    DbDoc           : IDatabaseLibDocument;
    Keys            : TStringList;
    Ids             : TStringList;
    L               : TStringList;
    DbLibPath       : String;
    InstalledPath   : String;
    DbKey           : String;
    SymLib          : WideString;
    SymRef          : WideString;
    FpLib           : WideString;
    ModelName       : WideString;
    PlacementParams : WideString;
    IsInstalled     : Boolean;
    FoundSymbol     : Boolean;
    i               : Integer;
    idx             : Integer;
    kind            : Integer;
    tbl             : Integer;
Begin
    DbLibPath := {dblib};
    L := TStringList.Create;
    Keys := Nil;
    Ids := Nil;
    DbDoc := Nil;
    DbKey := {item};
    SymLib := '';
    SymRef := '';
    FpLib := '';
    ModelName := '';
    PlacementParams := '';
    IsInstalled := False;
    FoundSymbol := False;
    Try
        Try
            If Not FileExists(DbLibPath) Then
                L.Add('FAIL: the .DbLib is not readable: ' + DbLibPath)
            Else
            Begin
                ILM := IntegratedLibraryManager;
                If ILM = Nil Then L.Add('FAIL: no IntegratedLibraryManager')
                Else
                Begin
                    L.Add('SR-DbLib=' + DbLibPath);
                    L.Add('SR-DbComponentKey=' + DbKey);
                    For i := 0 To ILM.InstalledLibraryCount - 1 Do
                    Begin
                        InstalledPath := ILM.InstalledLibraryPath(i);
                        L.Add('SR-Installed' + IntToStr(i) + '=' + InstalledPath);
                        If LowerCase(InstalledPath) = LowerCase(DbLibPath) Then
                            IsInstalled := True;
                    End;
                    L.Add('SR-IsInstalled=' + BoolToStr(IsInstalled, True));
                    If Not IsInstalled Then
                        L.Add('FAIL: the DbLib is absent from this fresh session')
                    Else
                    Begin
                        ILM.ActivateLibrary(DbLibPath);
                        Try
                            DbDoc := ILM.GetAvailableDBLibDocAtPath(DbLibPath);
                        Except
                            DbDoc := Nil;
                            L.Add('FAIL: GetAvailableDBLibDocAtPath raised');
                        End;
                        If DbDoc = Nil Then
                            L.Add('FAIL: the installed DbLib has no database document')
                        Else
                        Begin
                            L.Add('SR-DbTableCount=' + IntToStr(DbDoc.GetTableCount));
                            tbl := DbDoc.GetTableIndex({table});
                            L.Add('SR-DbTableIndex=' + IntToStr(tbl));
                            If tbl < 0 Then
                                L.Add('FAIL: the Parts table is unavailable')
                            Else
                            Begin
                                Keys := TStringList.Create;
                                Try
                                    DbDoc.GetAllComponentKeys(tbl, Keys);
                                Except
                                    L.Add('note: GetAllComponentKeys raised');
                                End;
                                L.Add('SR-DbComponentKeyCount=' + IntToStr(Keys.Count));
                                {{ AD26 can return zero here while resolving a KNOWN MPN through
                                  GetComponentPlacementParameters. Log the contradiction, but use
                                  the concrete key selected from Stockroom's source database. }}
                                Try
                                    L.Add('SR-DbSchLibRef=' +
                                          DbDoc.GetSchLibRefForComponent(tbl, DbKey));
                                    L.Add('SR-DbSchLibPath=' +
                                          DbDoc.GetSchLibPathForComponent(tbl, DbKey));
                                Except
                                    L.Add('note: direct database symbol lookup raised');
                                End;

                                Ids := TStringList.Create;
                                Ids.Add(DbLibPath);
                                Ids.Add(ExtractFileName(DbLibPath));
                                Ids.Add(ChangeFileExt(ExtractFileName(DbLibPath), ''));
                                Ids.Add({table});
                                Ids.Add(DbLibPath + '\\' + {table});
                                For idx := 0 To Ids.Count - 1 Do
                                Begin
                                    For kind := 0 To 3 Do
                                    Begin
                                        If Not FoundSymbol Then
                                        Begin
                                            Try
                                                FoundSymbol :=
                                                    ILM.FindComponentSymbol(
                                                        kind, Ids[idx], DbKey, SymLib, SymRef
                                                    );
                                                If FoundSymbol Then
                                                    L.Add('SR-SymbolIdentifier=' + Ids[idx]);
                                            Except
                                                L.Add(
                                                    'note: FindComponentSymbol rejected kind ' +
                                                    IntToStr(kind)
                                                );
                                            End;
                                        End;
                                        If FpLib = '' Then
                                        Begin
                                            Try
                                                FpLib := ILM.FindModelLibraryPath(
                                                    kind, Ids[idx], DbKey, ModelName, {model_type}
                                                );
                                            Except
                                                L.Add(
                                                    'note: FindModelLibraryPath rejected kind ' +
                                                    IntToStr(kind)
                                                );
                                            End;
                                        End;
                                        If PlacementParams = '' Then
                                        Begin
                                            Try
                                                PlacementParams :=
                                                    ILM.GetComponentPlacementParameters(
                                                        kind, Ids[idx], DbKey
                                                    );
                                            Except
                                                L.Add(
                                                    'note: placement parameters rejected kind ' +
                                                    IntToStr(kind)
                                                );
                                            End;
                                        End;
                                    End;
                                End;
                                L.Add('SR-SymbolResolved=' +
                                      BoolToStr(FoundSymbol, True));
                                L.Add('SR-SymbolLibrary=' + SymLib);
                                L.Add('SR-SymbolReference=' + SymRef);
                                L.Add('SR-FootprintLibrary=' + FpLib);
                                L.Add('SR-FootprintModel=' + ModelName);
                                L.Add('SR-PlacementParameters=' + PlacementParams);
                                If Not FoundSymbol Then
                                    L.Add('FAIL: the selected database part has no resolvable symbol');
                                If PlacementParams = '' Then
                                    L.Add(
                                        'FAIL: the selected database part has no placement parameters'
                                    );
                            End;
                        End;
                    End;
                End;
            End;
        Except
            L.Add('FAIL: Altium raised during fresh-session verification');
        End;
    Finally
        L.Add('DONE');
        L.SaveToFile({marker});
        If Ids <> Nil Then Ids.Free;
        If Keys <> Nil Then Keys.Free;
        L.Free;
    End;
    TerminateWithExitCode(0);
End;
"""


def render_installed_libraries_probe_script(
    *,
    marker_win: str,
    procedure: str = "SRListInstalledLibraries",
) -> str:
    """Render a fresh-session, read-only listing of every installed Altium library."""

    return _INSTALLED_LIBRARIES_PROBE_TEMPLATE.format(
        procedure=procedure,
        marker=delphi_quote(marker_win),
    )


_INSTALLED_LIBRARIES_PROBE_TEMPLATE = """{{ GENERATED by stockroom.altium.convergence.
  This is a FRESH-SESSION read-only probe. It must never change the installed library list. }}
Procedure {procedure};
Var
    ILM : IIntegratedLibraryManager;
    L   : TStringList;
    i   : Integer;
Begin
    L := TStringList.Create;
    Try
        Try
            ILM := IntegratedLibraryManager;
            If ILM = Nil Then
                L.Add('FAIL: no IntegratedLibraryManager')
            Else
            Begin
                For i := 0 To ILM.InstalledLibraryCount - 1 Do
                    L.Add('SR-Installed' + IntToStr(i) + '=' +
                          ILM.InstalledLibraryPath(i));
            End;
        Except
            L.Add('FAIL: Altium raised while listing installed libraries');
        End;
    Finally
        L.Add('DONE');
        L.SaveToFile({marker});
        L.Free;
    End;
    TerminateWithExitCode(0);
End;
"""


def verify_persistent_library(
    dblib: Path,
    *,
    driver: AltiumDriverLike | None = None,
    workdir: Path | None = None,
    timeout: int = 300,
) -> PersistenceVerification:
    """Verify a previously installed DbLib in a new Altium process without installing it."""

    drv = driver or AltiumDriver()
    target = Path(dblib)
    if not target.exists():
        return PersistenceVerification(
            "not-found", f"There is no database library at {target.as_posix()}."
        )
    component, component_error = _probe_component(target)
    if component is None:
        return PersistenceVerification("not-placeable", component_error)

    work = Path(workdir) if workdir else drv.host.windows_temp() / "stockroom-altium-persistence"
    work.mkdir(parents=True, exist_ok=True)
    pas = work / "SRVerifyPersistentLibrary.pas"
    project = work / "SRVerifyPersistentLibrary.PrjScr"
    marker = work / "SRVerifyPersistentLibrary.txt"
    marker.unlink(missing_ok=True)
    dblib_win = drv.host.to_windows_path(str(target))
    pas.write_text(
        render_persistence_probe_script(
            dblib_win=dblib_win,
            marker_win=drv.host.to_windows_path(str(marker)),
            design_item_id=component.key,
        ),
        encoding="utf-8",
        newline="\r\n",
    )
    project.write_text(
        f"[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n[Document1]\r\nDocumentPath={pas.name}\r\n",
        encoding="utf-8",
    )

    outcome: RunOutcome = drv.run_script(
        project=project,
        proc=f"{pas.name}>SRVerifyPersistentLibrary",
        marker=marker,
        timeout=timeout,
    )
    log = outcome.marker_text
    installed = parse_installed(log, "Installed")
    values = _parse_values(log)
    placement = values.get("PlacementParameters", "")
    symbol_resolved = values.get("SymbolResolved", "").casefold() == "true"
    footprint_from_parameters = (
        "ModelType0=PCBLIB" in placement and f"ModelName0={component.footprint_ref}" in placement
    )
    common = {
        "installed_paths": installed,
        "component_key": values.get("DbComponentKey", "") or component.key,
        # DelphiScript does not marshal FindComponentSymbol's out WideString values in AD26.
        # Its Boolean return is reliable, so pair it with the exact readable source asset selected
        # before launch rather than turning an empty out-param into a false negative.
        "symbol_library": (
            values.get("SymbolLibrary")
            or values.get("DbSchLibPath")
            or (str(component.symbol_path) if symbol_resolved else "")
        ),
        # FindModelLibraryPath has the same empty-out behavior on a DbLib. Altium's own placement
        # parameter string names the exact PCBLIB model; require that exact expected model.
        "footprint_library": values.get("FootprintLibrary")
        or (str(component.footprint_path) if footprint_from_parameters else ""),
        "placement_parameters": placement,
        "altium_log": log,
    }
    if not outcome.ok:
        return PersistenceVerification(outcome.status, outcome.detail, **common)
    if not is_installed(installed, dblib_win):
        return PersistenceVerification(
            "not-installed",
            f"{target.name} was absent from Altium's Installed list in a fresh process.",
            **common,
        )
    failures = [line.strip() for line in log.splitlines() if line.strip().startswith("FAIL:")]
    if failures:
        return PersistenceVerification("not-placeable", failures[0], **common)
    if not all(
        (
            common["component_key"],
            common["symbol_library"],
            common["footprint_library"],
            common["placement_parameters"],
        )
    ):
        return PersistenceVerification(
            "not-placeable",
            "The fresh session listed the library but did not resolve a complete placeable part.",
            **common,
        )
    return PersistenceVerification(
        "ok",
        f"Fresh Altium session resolved {common['component_key']} from {target.name}.",
        **common,
    )


def verify_libraries_absent(
    dblibs: tuple[Path, ...],
    *,
    driver: AltiumDriverLike | None = None,
    workdir: Path | None = None,
    timeout: int = 300,
) -> PersistenceVerification:
    """Prove receipted DbLib registrations are absent in a fresh, read-only Altium session."""

    drv = driver or AltiumDriver()
    targets = tuple(Path(item) for item in dblibs)
    work = (
        Path(workdir)
        if workdir
        else drv.host.windows_temp() / "stockroom-altium-absence"
    )
    work.mkdir(parents=True, exist_ok=True)
    pas = work / "SRListInstalledLibraries.pas"
    project = work / "SRListInstalledLibraries.PrjScr"
    marker = work / "SRListInstalledLibraries.txt"
    marker.unlink(missing_ok=True)
    pas.write_text(
        render_installed_libraries_probe_script(
            marker_win=drv.host.to_windows_path(str(marker)),
        ),
        encoding="utf-8",
        newline="\r\n",
    )
    project.write_text(
        f"[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n[Document1]\r\n"
        f"DocumentPath={pas.name}\r\n",
        encoding="utf-8",
    )

    outcome: RunOutcome = drv.run_script(
        project=project,
        proc=f"{pas.name}>SRListInstalledLibraries",
        marker=marker,
        timeout=timeout,
    )
    log = outcome.marker_text
    installed = parse_installed(log, "Installed")
    common = {"installed_paths": installed, "altium_log": log}
    if not outcome.ok:
        return PersistenceVerification(outcome.status, outcome.detail, **common)
    failures = [line.strip() for line in log.splitlines() if line.strip().startswith("FAIL:")]
    if failures:
        return PersistenceVerification("probe-failed", failures[0], **common)

    remaining = tuple(
        target
        for target in targets
        if is_installed(installed, drv.host.to_windows_path(str(target)))
    )
    if remaining:
        names = ", ".join(str(item) for item in remaining)
        return PersistenceVerification(
            "still-installed",
            f"A fresh Altium session still lists Stockroom-receipted DbLibs: {names}.",
            **common,
        )
    return PersistenceVerification(
        "ok",
        f"A fresh Altium session lists none of {len(targets)} receipted DbLib registrations.",
        **common,
    )


def default_receipt_path() -> Path:
    return config_dir() / "altium-library-receipts.json"


def _normalized(path: Path | str) -> str:
    return str(Path(path).resolve(strict=False)).replace("/", "\\").rstrip("\\").casefold()


def _x2_identity(driver: AltiumDriverLike) -> dict[str, object]:
    raw = getattr(driver, "x2", None)
    if raw is None:
        return {"path": "", "size": 0, "mtime_ns": 0}
    path = Path(raw)
    try:
        stat = path.stat()
    except OSError:
        return {"path": _normalized(path), "size": 0, "mtime_ns": 0}
    return {
        "path": _normalized(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _read_receipts(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"schema": _RECEIPT_SCHEMA, "libraries": []}
    if (
        not isinstance(data, dict)
        or data.get("schema") != _RECEIPT_SCHEMA
        or not isinstance(data.get("libraries"), list)
    ):
        return {"schema": _RECEIPT_SCHEMA, "libraries": []}
    return data


def _owned_receipts(path: Path) -> tuple[_OwnedReceipt, ...]:
    """Return only structurally complete receipts safe to use as uninstall authority."""

    by_key: dict[str, _OwnedReceipt] = {}
    for item in _read_receipts(path).get("libraries", []):
        if not isinstance(item, dict):
            continue
        raw = item.get("dblib")
        key = item.get("dblib_key")
        x2 = item.get("x2")
        evidence = item.get("evidence")
        verified_at = item.get("verified_at")
        if (
            not isinstance(raw, str)
            or not raw.strip()
            or not isinstance(key, str)
            or not isinstance(x2, dict)
            or not isinstance(evidence, dict)
            or evidence.get("status") != "ok"
            or not isinstance(evidence.get("component_key"), str)
            or not evidence.get("component_key")
        ):
            continue
        candidate = Path(raw)
        if not candidate.is_absolute() or candidate.suffix.casefold() != ".dblib":
            continue
        try:
            normalized = _normalized(candidate)
        except (OSError, ValueError):
            continue
        if normalized != key:
            continue
        receipt = _OwnedReceipt(
            dblib=candidate.resolve(strict=False),
            dblib_key=normalized,
            x2=x2,
            verified_at=verified_at if isinstance(verified_at, str) else "",
        )
        # A later receipt is the more recent accepted target and therefore the rollback choice.
        by_key.pop(normalized, None)
        by_key[normalized] = receipt
    return tuple(by_key.values())


def _receipt_matches(path: Path, dblib: Path, driver: AltiumDriverLike) -> bool:
    target = _normalized(dblib)
    identity = _x2_identity(driver)
    return any(item.dblib_key == target and item.x2 == identity for item in _owned_receipts(path))


def _replace_receipt_payload(path: Path, payload: dict) -> None:
    """Atomically replace a receipt only after the corresponding machine state is proven."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _write_receipt(
    path: Path,
    *,
    dblib: Path,
    driver: AltiumDriverLike,
    verification: PersistenceVerification,
) -> None:
    target = _normalized(dblib)
    entry = {
        "dblib": str(dblib.resolve(strict=False)),
        "dblib_key": target,
        "x2": _x2_identity(driver),
        "verified_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "evidence": asdict(verification),
    }
    # A successful convergence owns exactly one installed DbLib. Removing obsolete receipts is
    # what makes switching back reinstall that profile instead of trusting stale machine state.
    _replace_receipt_payload(path, {"schema": _RECEIPT_SCHEMA, "libraries": [entry]})


def _clear_receipt(path: Path) -> None:
    """Record that Stockroom currently owns no installed Altium DbLib."""

    _replace_receipt_payload(path, {"schema": _RECEIPT_SCHEMA, "libraries": []})


def _installed_contains(verification: PersistenceVerification, dblib_key: str) -> bool:
    for raw in verification.installed_paths:
        try:
            if _normalized(raw) == dblib_key:
                return True
        except (OSError, ValueError):
            continue
    return False


def _restore_last_receipted_target(
    *,
    fallback: _OwnedReceipt,
    candidate: Path,
    driver: AltiumDriverLike,
    work: Path,
    timeout: int,
    installer: Callable[..., InstallResult],
    verifier: Callable[..., PersistenceVerification],
) -> tuple[bool, str]:
    """Best-effort rollback that never drops the candidate before its predecessor is proven."""

    try:
        restored = installer(
            fallback.dblib,
            driver=driver,
            workdir=work / "rollback-install",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - return fail-closed evidence to the retry owner
        return False, f"Could not restore the last receipted DbLib: {exc}"
    if not restored.ok:
        return False, f"Could not restore the last receipted DbLib: {restored.detail}"

    try:
        restored_verification = verifier(
            fallback.dblib,
            driver=driver,
            workdir=work / "rollback-verify",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - return fail-closed evidence to the retry owner
        return False, f"Could not reverify the last receipted DbLib: {exc}"
    if not restored_verification.ok:
        return (
            False,
            f"Could not reverify the last receipted DbLib: {restored_verification.detail}",
        )

    try:
        removed_candidate = installer(
            candidate,
            uninstall=True,
            driver=driver,
            workdir=work / "rollback-remove-candidate",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - return fail-closed evidence to the retry owner
        return False, f"The previous DbLib was restored, but candidate rollback raised: {exc}"
    if not removed_candidate.ok:
        return (
            False,
            "The previous DbLib was restored, but candidate rollback failed: "
            f"{removed_candidate.detail}",
        )

    try:
        final_verification = verifier(
            fallback.dblib,
            driver=driver,
            workdir=work / "rollback-final-verify",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - return fail-closed evidence to the retry owner
        return False, f"Candidate rollback completed, but final predecessor proof raised: {exc}"
    if not final_verification.ok:
        return (
            False,
            "Candidate rollback completed, but the previous DbLib failed final proof: "
            f"{final_verification.detail}",
        )
    if _installed_contains(final_verification, _normalized(candidate)):
        return (
            False,
            "Candidate rollback reported success, but a fresh session still lists the candidate.",
        )
    return (
        True,
        f"Restored and reverified the last receipted DbLib at {fallback.dblib}.",
    )


def _cleanup_failure(
    *,
    detail: str,
    status: str = "cleanup-failed",
    target: Path,
    fallback: _OwnedReceipt,
    receipt: Path,
    verification: PersistenceVerification,
    driver: AltiumDriverLike,
    work: Path,
    timeout: int,
    installer: Callable[..., InstallResult],
    verifier: Callable[..., PersistenceVerification],
) -> AltiumConvergenceResult:
    rollback_ok, rollback_detail = _restore_last_receipted_target(
        fallback=fallback,
        candidate=target,
        driver=driver,
        work=work / "rollback",
        timeout=timeout,
        installer=installer,
        verifier=verifier,
    )
    rollback_state = (
        "The previous accepted profile remains active."
        if rollback_ok
        else "Rollback was incomplete; automatic convergence will retry without changing receipts."
    )
    return AltiumConvergenceResult(
        status,
        f"{detail} {rollback_detail} {rollback_state}",
        dblib=str(target),
        component_key=verification.component_key,
        symbol_library=verification.symbol_library,
        footprint_library=verification.footprint_library,
        receipt_path=str(receipt),
    )


def _clear_inactive_receipted_libraries(
    *,
    owned_receipts: tuple[_OwnedReceipt, ...],
    reason: str,
    receipt: Path,
    driver: AltiumDriverLike,
    work: Path,
    timeout: int,
    installer: Callable[..., InstallResult],
    absence_verifier: Callable[..., PersistenceVerification],
) -> AltiumConvergenceResult:
    """Remove only receipt-owned registrations when the active profile has no DbLib."""

    for index, old in enumerate(owned_receipts):
        try:
            cleanup = installer(
                old.dblib,
                uninstall=True,
                driver=driver,
                workdir=work / "cleanup" / str(index),
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - retain receipts as retry authority
            return AltiumConvergenceResult(
                "cleanup-failed",
                f"{reason} Removing receipted DbLib {old.dblib} raised: {exc}. "
                "The receipt was preserved so automatic convergence can retry.",
                receipt_path=str(receipt),
            )
        if not cleanup.ok:
            return AltiumConvergenceResult(
                "cleanup-failed",
                f"{reason} Removing receipted DbLib {old.dblib} failed: {cleanup.detail} "
                "The receipt was preserved so automatic convergence can retry.",
                receipt_path=str(receipt),
            )

    targets = tuple(item.dblib for item in owned_receipts)
    try:
        verification = absence_verifier(
            targets,
            driver=driver,
            workdir=work / "verify-absence",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - retain receipts as retry authority
        return AltiumConvergenceResult(
            "cleanup-failed",
            f"{reason} Fresh-session absence verification raised: {exc}. "
            "The receipt was preserved so automatic convergence can retry.",
            receipt_path=str(receipt),
        )
    if not verification.ok:
        return AltiumConvergenceResult(
            "cleanup-failed",
            f"{reason} Fresh-session absence verification failed: {verification.detail} "
            "The receipt was preserved so automatic convergence can retry.",
            receipt_path=str(receipt),
        )

    try:
        _clear_receipt(receipt)
    except Exception as exc:  # noqa: BLE001 - the unchanged receipt remains safe retry authority
        return AltiumConvergenceResult(
            "receipt-failed",
            f"{reason} The registrations were removed and independently verified, but the "
            f"machine receipt could not be cleared: {exc}. Automatic convergence can retry.",
            receipt_path=str(receipt),
        )
    count = len(owned_receipts)
    return AltiumConvergenceResult(
        "no-library",
        f"{reason} Removed {count} obsolete Stockroom-managed DbLib "
        f"{'registration' if count == 1 else 'registrations'} and verified the active profile "
        "has no Stockroom DbLib. Unreceipted user libraries were left untouched.",
        receipt_path=str(receipt),
    )


def converge_altium_library(
    dblib: Path | None,
    *,
    receipt_path: Path | None = None,
    driver: AltiumDriverLike | None = None,
    workdir: Path | None = None,
    timeout: int = 300,
    installer: Callable[..., InstallResult] = install_library,
    verifier: Callable[..., PersistenceVerification] = verify_persistent_library,
    absence_verifier: Callable[..., PersistenceVerification] = verify_libraries_absent,
) -> AltiumConvergenceResult:
    """Install, verify in a second process, then persist an idempotency receipt."""

    receipt = Path(receipt_path) if receipt_path else default_receipt_path()
    owned_receipts = _owned_receipts(receipt)
    if dblib is None:
        reason = "The active profile has no Altium database library yet."
        if owned_receipts:
            drv = driver or AltiumDriver()
            work = (
                Path(workdir)
                if workdir
                else drv.host.windows_temp() / "stockroom-altium-convergence"
            )
            return _clear_inactive_receipted_libraries(
                owned_receipts=owned_receipts,
                reason=reason,
                receipt=receipt,
                driver=drv,
                work=work,
                timeout=timeout,
                installer=installer,
                absence_verifier=absence_verifier,
            )
        return AltiumConvergenceResult(
            "no-library",
            reason,
            receipt_path=str(receipt),
        )
    target = Path(dblib)
    if not target.exists():
        reason = f"The active profile has no generated database library at {target.as_posix()}."
        if owned_receipts:
            drv = driver or AltiumDriver()
            work = (
                Path(workdir)
                if workdir
                else drv.host.windows_temp() / "stockroom-altium-convergence"
            )
            return _clear_inactive_receipted_libraries(
                owned_receipts=owned_receipts,
                reason=reason,
                receipt=receipt,
                driver=drv,
                work=work,
                timeout=timeout,
                installer=installer,
                absence_verifier=absence_verifier,
            )
        return AltiumConvergenceResult(
            "no-library",
            reason,
            dblib=str(target),
            receipt_path=str(receipt),
        )

    drv = driver or AltiumDriver()
    target_key = _normalized(target)
    obsolete = tuple(item for item in owned_receipts if item.dblib_key != target_key)
    if _receipt_matches(receipt, target, drv) and not obsolete:
        return AltiumConvergenceResult(
            "already-verified",
            f"{target.name} is already verified for this Altium installation.",
            dblib=str(target),
            receipt_path=str(receipt),
        )

    work = Path(workdir) if workdir else drv.host.windows_temp() / "stockroom-altium-convergence"
    install_result = installer(
        target,
        driver=drv,
        workdir=work / "install",
        timeout=timeout,
    )
    if not install_result.ok:
        return AltiumConvergenceResult(
            install_result.status,
            install_result.detail,
            dblib=str(target),
            receipt_path=str(receipt),
        )

    try:
        verification = verifier(
            target,
            driver=drv,
            workdir=work / "verify",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - a profile switch must restore accepted state
        if obsolete:
            return _cleanup_failure(
                status="verification-failed",
                detail=f"Candidate verification raised before cleanup: {exc}.",
                target=target,
                fallback=obsolete[-1],
                receipt=receipt,
                verification=PersistenceVerification(
                    "verification-failed",
                    f"Candidate verification raised: {exc}",
                ),
                driver=drv,
                work=work,
                timeout=timeout,
                installer=installer,
                verifier=verifier,
            )
        raise
    if not verification.ok:
        if obsolete:
            return _cleanup_failure(
                status=verification.status,
                detail=f"Candidate verification failed before cleanup: {verification.detail}",
                target=target,
                fallback=obsolete[-1],
                receipt=receipt,
                verification=verification,
                driver=drv,
                work=work,
                timeout=timeout,
                installer=installer,
                verifier=verifier,
            )
        return AltiumConvergenceResult(
            verification.status,
            verification.detail,
            dblib=str(target),
            component_key=verification.component_key,
            symbol_library=verification.symbol_library,
            footprint_library=verification.footprint_library,
            receipt_path=str(receipt),
        )

    if obsolete:
        fallback = obsolete[-1]
        cleanup_order = (*obsolete[:-1], fallback)
        for index, old in enumerate(cleanup_order):
            try:
                cleanup = installer(
                    old.dblib,
                    uninstall=True,
                    driver=drv,
                    workdir=work / "cleanup" / str(index),
                    timeout=timeout,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed and restore accepted state
                return _cleanup_failure(
                    detail=f"Removing receipted DbLib {old.dblib} raised: {exc}.",
                    target=target,
                    fallback=fallback,
                    receipt=receipt,
                    verification=verification,
                    driver=drv,
                    work=work,
                    timeout=timeout,
                    installer=installer,
                    verifier=verifier,
                )
            if not cleanup.ok:
                return _cleanup_failure(
                    detail=f"Removing receipted DbLib {old.dblib} failed: {cleanup.detail}",
                    target=target,
                    fallback=fallback,
                    receipt=receipt,
                    verification=verification,
                    driver=drv,
                    work=work,
                    timeout=timeout,
                    installer=installer,
                    verifier=verifier,
                )

        try:
            post_cleanup = verifier(
                target,
                driver=drv,
                workdir=work / "verify-after-cleanup",
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed and restore accepted state
            return _cleanup_failure(
                detail=f"Post-cleanup target verification raised: {exc}.",
                target=target,
                fallback=fallback,
                receipt=receipt,
                verification=verification,
                driver=drv,
                work=work,
                timeout=timeout,
                installer=installer,
                verifier=verifier,
            )
        remaining = tuple(
            old for old in obsolete if _installed_contains(post_cleanup, old.dblib_key)
        )
        if not post_cleanup.ok or remaining:
            failed_detail = (
                post_cleanup.detail
                if not post_cleanup.ok
                else "A fresh session still lists a receipted obsolete DbLib after cleanup."
            )
            return _cleanup_failure(
                detail=f"Post-cleanup target verification failed: {failed_detail}",
                target=target,
                fallback=fallback,
                receipt=receipt,
                verification=verification,
                driver=drv,
                work=work,
                timeout=timeout,
                installer=installer,
                verifier=verifier,
            )
        verification = post_cleanup

    try:
        _write_receipt(receipt, dblib=target, driver=drv, verification=verification)
    except Exception as exc:  # noqa: BLE001 - receipt commit must rollback the accepted target
        if obsolete:
            return _cleanup_failure(
                detail=f"Atomic receipt update failed: {exc}.",
                target=target,
                fallback=obsolete[-1],
                receipt=receipt,
                verification=verification,
                driver=drv,
                work=work,
                timeout=timeout,
                installer=installer,
                verifier=verifier,
            )
        return AltiumConvergenceResult(
            "receipt-failed",
            f"The DbLib was verified, but its machine receipt could not be written: {exc}",
            dblib=str(target),
            component_key=verification.component_key,
            symbol_library=verification.symbol_library,
            footprint_library=verification.footprint_library,
            receipt_path=str(receipt),
        )
    cleanup_detail = (
        f" Removed {len(obsolete)} obsolete Stockroom-managed DbLib "
        f"{'registration' if len(obsolete) == 1 else 'registrations'} and reverified the active "
        "profile."
        if obsolete
        else ""
    )
    return AltiumConvergenceResult(
        "verified",
        f"Installed {target.name} and verified {verification.component_key} in a fresh Altium "
        f"session.{cleanup_detail} No manual library setup is required.",
        dblib=str(target),
        component_key=verification.component_key,
        symbol_library=verification.symbol_library,
        footprint_library=verification.footprint_library,
        receipt_path=str(receipt),
    )


class AltiumLibraryConvergenceService:
    """Background owner that follows profile switches and retries ordinary seat contention."""

    def __init__(
        self,
        target: Callable[[], Path | None],
        *,
        result_sink: Callable[[AltiumConvergenceResult], None] | None = None,
        receipt_path: Path | None = None,
        poll_seconds: float = 10.0,
        retry_seconds: float = 30.0,
        driver_factory: Callable[[], AltiumDriverLike] = AltiumDriver,
    ) -> None:
        self.target = target
        self.result_sink = result_sink or (lambda _result: None)
        self.receipt_path = receipt_path
        self.poll_seconds = poll_seconds
        self.retry_seconds = retry_seconds
        self.driver_factory = driver_factory
        self.last_result: AltiumConvergenceResult | None = None
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def run_once(self) -> AltiumConvergenceResult:
        try:
            result = converge_altium_library(
                self.target(),
                receipt_path=self.receipt_path,
                driver=self.driver_factory(),
            )
        except Exception as exc:  # noqa: BLE001 - background setup must never kill Stockroom
            result = AltiumConvergenceResult(
                "failed",
                f"Automatic Altium library setup failed: {exc}",
                receipt_path=str(self.receipt_path or default_receipt_path()),
            )
        self.last_result = result
        self.result_sink(result)
        return result

    def start(self) -> threading.Event:
        if self._stop is not None:
            return self._stop
        stop = threading.Event()
        self._stop = stop

        def loop() -> None:
            while not stop.is_set():
                result = self.run_once()
                delay = self.poll_seconds if result.ok else self.retry_seconds
                if stop.wait(delay):
                    return

        self._thread = threading.Thread(
            target=loop,
            name="stockroom-altium-library-convergence",
            daemon=True,
        )
        self._thread.start()
        return stop

    def stop(self, timeout: float = 1.0) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
