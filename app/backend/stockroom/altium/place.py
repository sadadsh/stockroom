"""Place a part from the generated `.DbLib` onto a real Altium schematic, then verify it landed.

Why this exists
---------------
`altium_dblib_verify.py` proves Altium can CONNECT to the data source, and that is where the
2026-07-26 deadline bug was found. It does not prove the next step: that Altium can turn a
database row into a component on a sheet. Those are different mechanisms and only one of them
was ever measured, so "the library works" rested on an untested half.

The untested half was not hypothetical, and running this found a real blocker on its first pass:
the emitted `.DbLib` declared NO KEY FIELD, so Altium indexed ZERO components from a table it had
connected to perfectly well. See `dblib.KEY_COLUMN` for the measurement. The library reported
"Connected" with a populated field grid the whole time it was unusable, which is the second time in
one day that this library looked healthy while being broken. **Connecting is not indexing, and
neither is placing.** Each step has to be measured where it actually happens.

What this gate CANNOT reach, stated so nobody mistakes its silence for coverage: the drag from the
Components panel. `PlaceLibraryComponent` returns False for ANY database library, even when handed
the full parameter string Altium's own `GetComponentPlacementParameters` produced for that item,
while the identical call returns True for a `.SchLib`. The scripting API simply does not place from
a database library, so the last hop is a human action or a real-pointer GUI drive.

What it measures, and in what order
-----------------------------------
1. **Resolution, before anything is placed.** `FindComponentSymbol` and `FindModelLibraryPath` are
   asked where the symbol and the footprint actually resolve to. This runs FIRST and is appended to
   a progress log immediately, so the answer survives even if the placement later hangs.
2. **Placement.** `PlaceLibraryComponent` puts the row on a new sheet, which is saved to a real
   `.SchDoc`.
3. **An INDEPENDENT verdict from outside Altium.** `schdoc.read_schdoc_components` re-reads the
   saved file and reports what is actually in it. Altium's own word is never sufficient: the 3D
   embed work spent ten boots on a script that reported success while writing nothing.

`TLibIdentifierKind` is passed as an integer and every kind is tried, because DelphiScript exposes
no constant for it and the documented order (Any, NameNoType, NameWithType, FullPath) is an
ordering claim rather than a measured one. Trying all four costs nothing inside one boot and turns
a guess into a reported fact.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.altium.driver import AltiumDriver, RunOutcome
from stockroom.altium.embed3d import delphi_quote
from stockroom.altium.schdoc import read_schdoc_components
from stockroom.text import counted

# The document kind strings Altium's own API takes. Named so a reader does not have to know that
# 'SCH' is a document kind while 'PCBLIB' is a MODEL type; they are different vocabularies that
# happen to look alike.
_SCH_KIND = "SCH"
_PCBLIB_MODEL_TYPE = "PCBLIB"


@dataclass(frozen=True)
class PlaceResult:
    """The outcome of a place, carrying BOTH verdicts separately.

    `symbol_library` / `footprint_library` are what ALTIUM said it resolved. `placed_*` are what the
    saved file says, read back with no Altium involved. They are never merged into one "it worked",
    because a disagreement between them is the finding rather than something to average out.
    """

    status: str  # ok | not-installed | busy | dialog | exited | timeout | not-placed
    detail: str
    # What Altium resolved, before placing. Empty means it could not resolve that asset at all.
    symbol_library: str = ""
    symbol_reference: str = ""
    footprint_library: str = ""
    # What the saved .SchDoc contains, read from outside Altium.
    placed_design_item_ids: tuple[str, ...] = ()
    placed_footprints: tuple[str, ...] = ()
    placed_parameters: dict[str, str] = field(default_factory=dict)
    altium_log: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def resolved_symbol(self) -> bool:
        return bool(self.symbol_library)

    @property
    def resolved_footprint(self) -> bool:
        return bool(self.footprint_library)


def parse_resolution(log: str) -> dict[str, str]:
    """The `KEY=VALUE` lines the script writes, as a dict.

    The script emits machine-readable lines alongside its human ones so this parser never has to
    read prose. A key repeated (one line per identifier kind tried) keeps the FIRST non-empty
    value, since that is the kind that actually resolved.
    """
    out: dict[str, str] = {}
    for line in (log or "").splitlines():
        line = line.strip()
        if not line.startswith("SR-") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key[3:].strip(), value.strip()
        if value and not out.get(key):
            out[key] = value
    return out


def render_place_script(
    *,
    dblib_win: str,
    design_item_id: str,
    schdoc_win: str,
    marker_win: str,
    progress_win: str,
    table: str = "Parts",
    procedure: str = "SRPlace",
) -> str:
    """The DelphiScript that resolves, places and saves, as text.

    `table` is the DbLib table name, swept as one of the candidate library identifiers: Altium
    presents each table in a database library as if it were a distinct library, so the table name
    is a real candidate for the identifier and not a guess worth skipping.
    """
    return _TEMPLATE.format(
        procedure=procedure,
        table=delphi_quote(table),
        dblib=delphi_quote(dblib_win),
        item=delphi_quote(design_item_id),
        schdoc=delphi_quote(schdoc_win),
        marker=delphi_quote(marker_win),
        progress=delphi_quote(progress_win),
        sch_kind=delphi_quote(_SCH_KIND),
        model_type=delphi_quote(_PCBLIB_MODEL_TYPE),
    )


# ONE template, no per-case branching. Every non-obvious line is commented in the GENERATED script,
# because the next person to debug this will be reading Altium's copy of it and not this file.
_TEMPLATE = """{{ GENERATED by stockroom.altium.place -- do not hand-edit.
  Resolves a DbLib row's symbol and footprint, places it on a new sheet, and saves.
  Resolution is logged BEFORE the placement is attempted, so a hang during placement still
  leaves the answer to the question that actually matters. }}
Procedure {procedure};
Var
    ILM        : IIntegratedLibraryManager;
    Doc        : IServerDocument;
    Sheet      : ISch_Document;
    Iterator   : ISch_Iterator;
    Comp       : ISch_Component;
    L          : TStringList;
    P          : TStringList;
    DbLibPath  : String;
    ItemId     : String;
    SchPath    : String;
    SymLib     : WideString;
    SymRef     : WideString;
    FpLib      : WideString;
    ModelName  : WideString;
    Placed     : Boolean;
    SaveOk     : Boolean;
    kind       : Integer;
    idx        : Integer;
    Ids        : TStringList;
    Keys       : TStringList;
    DbDoc      : IDatabaseLibDocument;
    DbKey      : String;
    PlaceParams: WideString;
    BestParams : WideString;
    tbl        : Integer;
    Orcad      : Boolean;
    found      : Integer;
Begin
    DbLibPath := {dblib};
    ItemId    := {item};
    SchPath   := {schdoc};
    L := TStringList.Create;
    P := TStringList.Create;
    Ids := Nil;
    DbDoc := Nil;
    DbKey := '';
    BestParams := '';
    PlaceParams := '';
    SymLib := ''; SymRef := ''; FpLib := ''; ModelName := '';
    Placed := False;
    found := 0;
    Try
        Try
            If Not FileExists(DbLibPath) Then L.Add('FAIL: the .DbLib is not readable: ' + DbLibPath)
            Else
            Begin
                ILM := IntegratedLibraryManager;
                If ILM = Nil Then L.Add('FAIL: no IntegratedLibraryManager')
                Else
                Begin
                    {{ Install the DbLib for this session. Placing from a library Altium has not
                      been told about is the most likely way to get a false negative here. }}
                    {{ INSTALL, then activate. ActivateLibrary alone only activates a library
                      Altium already knows about: measured 2026-07-26, a run that called it on an
                      uninstalled .DbLib reported AvailableLibraryCount=1 and that one library was
                      Altium's own stock Simulation Generic Components.IntLib. Every lookup below
                      then failed for want of a library rather than for want of a resolvable path,
                      which would have read as "the Stockroom library is broken". }}
                    ILM.InstallLibrary(DbLibPath);
                    ILM.ActivateLibrary(DbLibPath);
                    L.Add('SR-DbLib=' + DbLibPath);
                    L.Add('SR-DesignItemId=' + ItemId);
                    L.Add('SR-InstalledLibraryCount=' + IntToStr(ILM.InstalledLibraryCount));
                    L.Add('SR-AvailableLibraryCount=' + IntToStr(ILM.AvailableLibraryCount));
                    {{ WHICH libraries, not just how many. A count alone cannot distinguish "our
                      DbLib is installed and the lookup key is wrong" from "the install silently did
                      nothing and this is somebody else's library", and those have opposite fixes. }}
                    For kind := 0 To ILM.InstalledLibraryCount - 1 Do
                    Begin
                        Try
                            L.Add('SR-Installed' + IntToStr(kind) + '=' + ILM.InstalledLibraryPath(kind));
                        Except
                            L.Add('note: InstalledLibraryPath rejected index ' + IntToStr(kind));
                        End;
                    End;
                    For kind := 0 To ILM.AvailableLibraryCount - 1 Do
                    Begin
                        Try
                            L.Add('SR-Library' + IntToStr(kind) + '=' + ILM.AvailableLibraryPath(kind));
                        Except
                            L.Add('note: AvailableLibraryPath rejected index ' + IntToStr(kind));
                        End;
                    End;
                    {{ What Altium thinks this item IS, independent of whether it can be placed. A
                      display path for an item it cannot resolve a symbol for is a very different
                      finding from no display path at all. }}
                    For kind := 0 To 3 Do
                    Begin
                        Try
                            L.Add('SR-DisplayPath' + IntToStr(kind) + '=' +
                                  ILM.FindComponentDisplayPath(kind, DbLibPath, ItemId));
                        Except
                            L.Add('note: FindComponentDisplayPath rejected kind ' + IntToStr(kind));
                        End;
                        Try
                            PlaceParams := ILM.GetComponentPlacementParameters(kind, DbLibPath, ItemId);
                            L.Add('SR-PlacementParams' + IntToStr(kind) + '=' + PlaceParams);
                            If (PlaceParams <> '') And (BestParams = '') Then BestParams := PlaceParams;
                        Except
                            L.Add('note: GetComponentPlacementParameters rejected kind ' + IntToStr(kind));
                        End;
                    End;

                    {{ ASK THE DATABASE SUBSYSTEM ITSELF, before asking the library manager.
                      A .DbLib is served by a different subsystem from an .IntLib, and the question
                      "does Altium read our table, and under what KEY" is answerable directly rather
                      than inferred from a failed lookup. GetAllComponentKeys returns the identifiers
                      Altium actually indexes: if those are not the MPN then every lookup below was
                      simply asking for the wrong name. }}
                    Try
                        DbDoc := ILM.GetAvailableDBLibDocAtPath(DbLibPath);
                    Except
                        DbDoc := Nil;
                        L.Add('note: GetAvailableDBLibDocAtPath raised');
                    End;
                    If DbDoc = Nil Then L.Add('SR-DbLibDocument=<none>')
                    Else
                    Begin
                        L.Add('SR-DbLibDocument=' + DbDoc.GetFileName);
                        L.Add('SR-DbConnectionString=' + DbDoc.GetConnectionString);
                        L.Add('SR-DbLibrarySearchPath=' + DbDoc.GetLibrarySearchPath);
                        L.Add('SR-DbTableCount=' + IntToStr(DbDoc.GetTableCount));
                        For idx := 0 To DbDoc.GetTableCount - 1 Do
                            L.Add('SR-DbTable' + IntToStr(idx) + '=' + DbDoc.GetTableNameAt(idx));
                        tbl := DbDoc.GetTableIndex({table});
                        L.Add('SR-DbTableIndex=' + IntToStr(tbl));
                        If tbl >= 0 Then
                        Begin
                            L.Add('SR-DbKeyFieldCount=' + IntToStr(DbDoc.GetKeyFieldCount(tbl)));
                            For idx := 0 To DbDoc.GetKeyFieldCount(tbl) - 1 Do
                                L.Add('SR-DbKeyField' + IntToStr(idx) + '=' + DbDoc.GetKeyField(False, tbl, idx));
                            Try
                                L.Add('SR-DbLibRefField=' + DbDoc.GetLibraryRefFieldName(tbl, Orcad));
                                L.Add('SR-DbLibPathField=' + DbDoc.GetLibraryPathFieldName(tbl));
                            Except
                                L.Add('note: the library ref/path field names could not be read');
                            End;
                            Keys := TStringList.Create;
                            Try
                                DbDoc.GetAllComponentKeys(tbl, Keys);
                                L.Add('SR-DbComponentKeyCount=' + IntToStr(Keys.Count));
                                For idx := 0 To Keys.Count - 1 Do
                                Begin
                                    If idx >= 5 Then Break;
                                    L.Add('SR-DbComponentKey' + IntToStr(idx) + '=' + Keys[idx]);
                                End;
                                {{ Resolve the SYMBOL through the database subsystem, using Altium's
                                  OWN key rather than the MPN we assumed. This is the call that says
                                  whether `LibrarySearchPath=.` resolves a bare filename. }}
                                If Keys.Count > 0 Then
                                Begin
                                    L.Add('SR-DbSchLibRef=' + DbDoc.GetSchLibRefForComponent(tbl, Keys[0]));
                                    L.Add('SR-DbSchLibPath=' + DbDoc.GetSchLibPathForComponent(tbl, Keys[0]));
                                    DbKey := Keys[0];
                                End;
                            Except
                                L.Add('note: GetAllComponentKeys raised for table ' + IntToStr(tbl));
                            End;
                            Keys.Free;
                        End;
                    End;

                    {{ RESOLUTION FIRST, swept across every IDENTIFIER FORM and every identifier
                      KIND, because both are unknowns and neither is worth a guess.

                      The kind is an unknown because DelphiScript exposes no constant for
                      TLibIdentifierKind, so the documented order (Any, NameNoType, NameWithType,
                      FullPath) is an ordering CLAIM rather than something measured.

                      The identifier is an unknown because a .DbLib is not one library: Altium's own
                      documentation says each TABLE in the linked database presents as if it were a
                      distinct library, so the name it wants may be the file, the file without its
                      extension, or the table. Sweeping 4 kinds x N forms inside a single boot costs
                      nothing and reports WHICH combination works, which is a fact rather than a
                      hypothesis. Guarded per attempt: a rejected combination must be reported, not
                      fatal. }}
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
                            Try
                                If SymLib = '' Then
                                    If ILM.FindComponentSymbol(kind, Ids[idx], ItemId, SymLib, SymRef) Then
                                    Begin
                                        L.Add('SR-SymbolKind=' + IntToStr(kind));
                                        L.Add('SR-SymbolIdentifier=' + Ids[idx]);
                                    End;
                            Except
                                L.Add('note: FindComponentSymbol rejected kind ' + IntToStr(kind) +
                                      ' id ' + Ids[idx]);
                            End;
                            Try
                                If FpLib = '' Then
                                Begin
                                    FpLib := ILM.FindModelLibraryPath(kind, Ids[idx], ItemId, ModelName, {model_type});
                                    If FpLib <> '' Then L.Add('SR-FootprintIdentifier=' + Ids[idx]);
                                End;
                            Except
                                L.Add('note: FindModelLibraryPath rejected kind ' + IntToStr(kind) +
                                      ' id ' + Ids[idx]);
                            End;
                        End;
                    End;
                    L.Add('SR-SymbolLibrary=' + SymLib);
                    L.Add('SR-SymbolReference=' + SymRef);
                    L.Add('SR-FootprintLibrary=' + FpLib);
                    L.Add('SR-FootprintModel=' + ModelName);
                    {{ Flush what we know BEFORE the placement, which is the step that could hang.
                      A timeout then still answers the question this whole script exists for. }}
                    P.Assign(L);
                    P.SaveToFile({progress});

                    {{ PLACEMENT. A new sheet, so nothing pre-existing can be mistaken for a
                      success, and an explicit location so Altium has no reason to wait for a
                      cursor. }}
                    Doc := CreateNewDocumentFromDocumentKind({sch_kind});
                    If Doc = Nil Then L.Add('FAIL: Altium would not create a schematic document')
                    Else
                    Begin
                        Client.ShowDocument(Doc);
                        {{ Place with the parameter string Altium ITSELF produced for this item.
                          `GetComponentPlacementParameters` exists to build exactly this argument,
                          and for a database library it is not optional: it is what carries
                          `PlacingFromDatabase=TRUE`, the resolved footprint and every mapped column.
                          A bare location was enough for a file-based library and returned False for
                          every database one. }}
                        If BestParams <> '' Then
                        Begin
                            Placed := ILM.PlaceLibraryComponent(ItemId, DbLibPath,
                                          BestParams + '|Location.X=100000|Location.Y=100000');
                            L.Add('SR-PlaceReturnedWithParams=' + BoolToStr(Placed, True));
                        End;
                        If Not Placed Then
                        Begin
                            Placed := ILM.PlaceLibraryComponent(ItemId, DbLibPath,
                                                                'Location.X=100000|Location.Y=100000');
                            L.Add('SR-PlaceReturned=' + BoolToStr(Placed, True));
                        End;
                        {{ Retry with the key the DATABASE subsystem reports, when that differs from
                          the MPN we assumed. Assuming the design item id equals the MPN is exactly
                          the kind of guess this script exists to replace with a measurement. }}
                        If (Not Placed) And (DbKey <> '') And (DbKey <> ItemId) Then
                        Begin
                            Placed := ILM.PlaceLibraryComponent(DbKey, DbLibPath,
                                                                'Location.X=100000|Location.Y=100000');
                            L.Add('SR-PlaceReturnedWithDbKey=' + BoolToStr(Placed, True));
                        End;

                        {{ Altium's return value is not the verdict. Count what is actually on the
                          sheet, which is a different question and the one that matters. }}
                        Sheet := SchServer.GetCurrentSchDocument;
                        If Sheet = Nil Then L.Add('FAIL: no current schematic after the place')
                        Else
                        Begin
                            Iterator := Sheet.SchIterator_Create;
                            Iterator.AddFilter_ObjectSet(MkSet(eSchComponent));
                            Comp := Iterator.FirstSchObject;
                            While Comp <> Nil Do
                            Begin
                                found := found + 1;
                                L.Add('SR-OnSheet=' + Comp.DesignItemId + ' libref=' + Comp.LibReference);
                                Comp := Iterator.NextSchObject;
                            End;
                            Sheet.SchIterator_Destroy(Iterator);
                            L.Add('SR-ComponentsOnSheet=' + IntToStr(found));

                            {{ Name it, MARK IT MODIFIED, then save. A document created in memory
                              has no filename, and saving one without giving it a path opens a modal
                              Save As that nothing headless can answer.

                              `Modified := True` is the load-bearing line and it was missing:
                              measured 2026-07-26, DoSafeChangeFileNameAndSave returned True on a
                              sheet that genuinely held the placed component and wrote NO FILE
                              ANYWHERE on disk. A document Altium does not consider dirty short
                              circuits its save and still reports success, which is the same
                              "success without a write" that cost the 3D embed ten boots. }}
                            Doc.SetFileName(SchPath);
                            Doc.Modified := True;
                            SaveOk := Doc.DoFileSave({sch_kind});
                            If Not SaveOk Then
                                SaveOk := Doc.DoSafeChangeFileNameAndSave(SchPath, {sch_kind});
                            L.Add('SR-Saved=' + BoolToStr(SaveOk, True));
                            L.Add('SR-SavedTo=' + Doc.FileName);
                            If Not SaveOk Then L.Add('FAIL: the save was REFUSED for ' + SchPath);
                        End;
                        Client.CloseDocument(Doc);
                    End;
                End;
            End;
        Except
            L.Add('FAIL: Altium raised an exception during the place');
        End;
    Finally
        {{ The marker is written on EVERY path, so the caller never infers an outcome from how long
          the run took. }}
        L.Add('DONE placed=' + IntToStr(found));
        L.SaveToFile({marker});
        L.Free;
        P.Free;
        If Ids <> Nil Then Ids.Free;
    End;
    TerminateWithExitCode(0);
End;
"""


def place_from_dblib(
    dblib: Path,
    design_item_id: str,
    *,
    schdoc: Path | None = None,
    driver: AltiumDriver | None = None,
    workdir: Path | None = None,
    timeout: int = 300,
) -> PlaceResult:
    """Place `design_item_id` from `dblib` onto a fresh sheet and report what actually landed.

    A run Altium calls successful but whose saved `.SchDoc` holds no component comes back
    `not-placed`. That is the same stance the 3D embed takes, and for the same measured reason:
    Altium reporting success is not evidence that anything was written.
    """
    drv = driver or AltiumDriver()
    dblib = Path(dblib)
    if not dblib.exists():
        return PlaceResult("not-placed", f"The database library {dblib.name} does not exist.")

    work = Path(workdir) if workdir else drv.host.windows_temp() / "stockroom-place"
    work.mkdir(parents=True, exist_ok=True)
    pas = work / "SRPlace.pas"
    prj = work / "SRPlace.PrjScr"
    marker = work / "SRPlace.txt"
    progress = work / "SRPlace-progress.txt"
    out_doc = Path(schdoc) if schdoc else work / "SRPlace.SchDoc"

    # Both are re-read after the run; a stale copy from an earlier boot would otherwise be reported
    # as this run's result, which is the single easiest way to manufacture a false success.
    marker.unlink(missing_ok=True)
    progress.unlink(missing_ok=True)
    out_doc.unlink(missing_ok=True)

    pas.write_text(
        render_place_script(
            dblib_win=drv.host.to_windows_path(str(dblib)),
            design_item_id=design_item_id,
            schdoc_win=drv.host.to_windows_path(str(out_doc)),
            marker_win=drv.host.to_windows_path(str(marker)),
            progress_win=drv.host.to_windows_path(str(progress)),
        ),
        encoding="utf-8",
        newline="\r\n",
    )
    prj.write_text(
        "[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n[Document1]\r\n"
        f"DocumentPath={pas.name}\r\n",
        encoding="utf-8",
    )

    outcome: RunOutcome = drv.run_script(
        project=prj, proc=f"{pas.name}>SRPlace", marker=marker, timeout=timeout
    )
    # The progress file is read WHATEVER the outcome. On a timeout it still carries the resolution
    # answer, which is the expensive half to obtain and the reason it is flushed separately.
    log = outcome.marker_text or (
        progress.read_text(encoding="utf-8", errors="replace") if progress.exists() else ""
    )
    res = parse_resolution(log)
    # MEASURED 2026-07-26: DelphiScript does not marshal `out WideString` back to the caller, so
    # FindComponentSymbol's ASymbolLibraryPath arrives empty even on a run that returns True and
    # then places successfully. Reading resolution from those out-params made a working library
    # report `<UNRESOLVED>`, which is a false negative in the gate itself. The signals that do
    # survive are the function's RETURN value (recorded as SymbolKind/SymbolIdentifier when true)
    # and FindComponentDisplayPath, which returns its answer normally.
    display = next(
        (v for k, v in sorted(res.items()) if k.startswith("DisplayPath") and v),
        "",
    )
    common = {
        "symbol_library": res.get("SymbolLibrary") or display,
        "symbol_reference": res.get("SymbolReference") or res.get("SymbolIdentifier", ""),
        "footprint_library": res.get("FootprintLibrary") or res.get("FootprintIdentifier", ""),
        "altium_log": log,
    }
    if not outcome.ok:
        return PlaceResult(outcome.status, outcome.detail, **common)
    if "FAIL" in log:
        first = next(
            (ln for ln in log.splitlines() if "FAIL" in ln), "the script reported a failure"
        )
        return PlaceResult("not-placed", first.strip(), **common)

    placed = read_schdoc_components(out_doc) if out_doc.exists() else []
    if not placed:
        return PlaceResult(
            "not-placed",
            "Altium reported success but the saved schematic holds no component, so nothing was "
            "actually placed. Do not treat this as done.",
            **common,
        )
    ids = tuple(str(c.get("design_item_id") or "") for c in placed)
    footprints = tuple(str(c.get("footprint") or "") for c in placed if c.get("footprint"))
    params = dict(placed[0].get("params") or {})
    return PlaceResult(
        "ok",
        f"Placed {design_item_id} from {dblib.name} onto {out_doc.name} "
        f"({counted(len(placed), 'component')}, footprint {footprints[0] if footprints else 'MISSING'}).",
        placed_design_item_ids=ids,
        placed_footprints=footprints,
        placed_parameters=params,
        **common,
    )
