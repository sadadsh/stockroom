"""Embed a STEP model into a footprint's `.PcbLib` as an Altium 3D Body.

Why this cannot be done any other way
-------------------------------------
Altium takes a 3D model as a 3D Body object stored INSIDE the footprint's `.PcbLib`, an OLE2
compound binary. No database column, path or reference mechanism can carry one, which is why
the registry lists the model as an asset Altium cannot be given BY REFERENCE. So Stockroom
makes Altium itself write it, through a generated DelphiScript, and then verifies the container
from OUTSIDE Altium.

The one call that matters
-------------------------
**The body must be added to the BOARD, not to the footprint.** `Fp.AddPCBObject(Body)` attaches
it to the footprint group in memory (a live count really does return 1) and it is silently
dropped on save; `Board.AddPCBObject(Body)`, with the target footprint made current first,
persists it. That single call cost ten Altium boots and nine wrong hypotheses on 2026-07-25,
and both community scripts used as references have it wrong, so it is asserted by a test rather
than left as a comment.

Measured proof that the payload lands (`scripts/altium_probe.py`, variant `board-add`): a new
`Library/Models/0` stream appears, `Library/Models/Data` goes 0 -> 162 bytes, the footprint's
own `Data` stream grows by 832 bytes, and the file grows 112,640 -> 178,176 bytes. The failing
variants change no stream at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from stockroom.altium.driver import AltiumDriver, RunOutcome

# A model payload is stored as a numbered stream inside the `Models` storage. Matched
# case-insensitively on the FULL path: an earlier check used `name.startswith("models")`, which
# can never match `Library/Models/Data` because the path begins with `Library/`, and that
# predicate would have reported a real success as a failure.
_MODEL_STREAM = re.compile(r"^library/models/(\d+)$", re.IGNORECASE)
_MODEL_INDEX = re.compile(r"^library/models/data$", re.IGNORECASE)


@dataclass(frozen=True)
class EmbedResult:
    """The outcome of an embed, carrying BOTH verdicts: what Altium said, and what the file
    says. They are reported separately on purpose, because a disagreement is a finding rather
    than something to average out."""

    status: str  # ok | not-installed | busy | dialog | exited | timeout | not-written
    detail: str
    embedded: int = 0  # model payload streams found in the saved container
    payload_bytes: int = 0
    # Superseded payloads left behind by an in-place replace. Altium does not prune them, so they
    # are REPORTED rather than quietly inflating a git-synced binary.
    orphaned: int = 0
    altium_log: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def delphi_quote(text: str) -> str:
    """A Delphi single-quoted literal. Doubles embedded apostrophes, so a path under
    `C:\\Users\\O'Brien\\` cannot end the string early and break the script."""
    return "'" + str(text).replace("'", "''") + "'"


def ole_streams(path: Path) -> dict[str, int]:
    """Every stream in an OLE2 container as full path -> size in bytes.

    Read from outside Altium, so it is a genuinely independent check on Altium's own report.
    """
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        return {"/".join(parts): ole.get_size("/".join(parts)) for parts in ole.listdir(streams=True)}


def embedded_models(streams: dict[str, int]) -> dict[int, int]:
    """Model payload streams as index -> size, from a container's stream map.

    Takes the map rather than a path so the predicate is testable exhaustively without needing
    an Altium install to author a container for every case.
    """
    out: dict[int, int] = {}
    for name, size in streams.items():
        hit = _MODEL_STREAM.match(name)
        if hit and size > 0:
            out[int(hit.group(1))] = size
    return out


def has_embedded_model(streams: dict[str, int]) -> bool:
    """True when the container holds at least one non-empty model payload.

    An empty `Library/Models/Data` index with no numbered payload streams is what EVERY failed
    embed produced, so emptiness is the exact signature being excluded here.
    """
    return bool(embedded_models(streams))


def model_index_bytes(streams: dict[str, int]) -> int:
    """Size of the `Library/Models/Data` index, which lists the embedded models. Zero on a
    library with no 3D bodies."""
    for name, size in streams.items():
        if _MODEL_INDEX.match(name):
            return size
    return 0


def parse_model_index(blob: bytes) -> tuple[dict[str, str], ...]:
    """The `Library/Models/Data` index as one dict per embedded model.

    The format, read off a real container rather than taken from a spec: a sequence of
    `<u32 length><payload>` records, where the payload is NUL-terminated `KEY=VALUE|KEY=VALUE`
    text carrying `EMBED`, `MODELSOURCE`, `ID` (a GUID minted per embed), `ROTX/ROTY/ROTZ`, `DZ`,
    `CHECKSUM` and `NAME` (the model's file name).

    Deliberately total: a short, truncated or foreign blob yields the records it can read and
    then stops, because this feeds a readiness check that must never raise on a file some other
    tool wrote.
    """
    out: list[dict[str, str]] = []
    offset = 0
    while offset + 4 <= len(blob):
        size = int.from_bytes(blob[offset : offset + 4], "little")
        offset += 4
        if size <= 0 or offset + size > len(blob):
            break
        text = blob[offset : offset + size].rstrip(b"\x00").decode("latin-1")
        offset += size
        fields: dict[str, str] = {}
        for pair in text.split("|"):
            key, sep, value = pair.partition("=")
            if sep:
                fields[key.strip().upper()] = value.strip()
        if fields:
            out.append(fields)
    return tuple(out)


def read_model_index(pcblib: Path) -> tuple[dict[str, str], ...]:
    """`parse_model_index` for a library on disk. Empty when the file is not a readable
    container or carries no model index, which is a legitimate state, not an error."""
    import olefile

    try:
        with olefile.OleFileIO(str(pcblib)) as ole:
            if not ole.exists("Library/Models/Data"):
                return ()
            return parse_model_index(ole.openstream("Library/Models/Data").read())
    except Exception:
        return ()


def model_name_present(records: tuple[dict[str, str], ...], name: str) -> bool:
    """Whether a model with this file name is already embedded.

    Compared case-insensitively, because these names come from Windows paths where
    `PART.STP` and `part.stp` are the same file and a case-sensitive check would embed a
    duplicate.
    """
    wanted = Path(name).name.casefold()
    return any(Path(r.get("NAME", "")).name.casefold() == wanted for r in records)


def render_embed_script(
    *,
    pcblib_win: str,
    step_win: str,
    marker_win: str,
    footprints: tuple[str, ...] = (),
    procedure: str = "SREmbed3D",
) -> str:
    """The DelphiScript that performs the embed, as text.

    `footprints` restricts the edit to named entries; empty means every footprint in the
    library, which is what a single-part Stockroom library always wants. The filter list is
    always built and always consulted, empty or not, so there is ONE code path rather than a
    rarely-taken generated branch that nothing would exercise.

    Re-running is safe: any existing body already referencing this model file is removed first,
    so an embed is idempotent instead of stacking duplicate bodies on every run.
    """
    wanted_adds = "".join(
        f"                Wanted.Add({delphi_quote(name)});\n" for name in footprints
    )
    return _TEMPLATE.format(
        procedure=procedure,
        lib=delphi_quote(pcblib_win),
        step=delphi_quote(step_win),
        marker=delphi_quote(marker_win),
        wanted_adds=wanted_adds or "                { no filter: every footprint }\n",
    )


# Kept as ONE template with no per-tool branching. Every line that is not obvious is commented in
# the generated script itself, because the next person to debug it will be reading Altium's copy.
_TEMPLATE = """{{ GENERATED by stockroom.altium.embed3d -- do not hand-edit.
  Embeds a STEP model as a 3D Body in a .PcbLib, then saves and reports.
  The body is added to the BOARD, never to the footprint: Fp.AddPCBObject attaches it in memory
  and it is silently dropped on save. Verified 2026-07-25. }}
Procedure {procedure};
Var
    CurrentLib : IPCB_Library;
    Fp         : IPCB_LibComponent;
    Body       : IPCB_ComponentBody;
    Model      : IPCB_Model;
    Board      : IPCB_Board;
    Doc        : IServerDocument;
    BIter      : IPCB_GroupIterator;
    Old        : IPCB_ComponentBody;
    Stale      : TObjectList;
    Wanted     : TStringList;
    L          : TStringList;
    LibPath    : String;
    StepPath   : String;
    StepName   : String;
    SaveOk     : Boolean;
    j, k       : Integer;
    added      : Integer;
    removed    : Integer;
    DoIt       : Boolean;
Begin
    LibPath  := {lib};
    StepPath := {step};
    StepName := ExtractFileName(StepPath);
    L := TStringList.Create;
    added := 0;
    removed := 0;
    Try
        Try
            If Not FileExists(StepPath) Then L.Add('FAIL: the model file is not readable: ' + StepPath)
            Else If Not FileExists(LibPath) Then L.Add('FAIL: the library is not readable: ' + LibPath)
            Else
            Begin
                Wanted := TStringList.Create;
{wanted_adds}                Doc := Client.OpenDocument('PCBLIB', LibPath);
                If Doc = Nil Then L.Add('FAIL: Altium would not open ' + LibPath)
                Else
                Begin
                    Client.ShowDocument(Doc);
                    CurrentLib := PCBServer.GetCurrentPCBLibrary;
                    If CurrentLib = Nil Then L.Add('FAIL: the document opened but is not a PcbLib')
                    Else
                    Begin
                        PCBServer.PreProcess;
                        For j := 0 To CurrentLib.ComponentCount - 1 Do
                        Begin
                            Fp := CurrentLib.GetComponent(j);
                            {{ An EMPTY filter means every footprint, so the same two lines run in
                              both cases and neither is an untested path. }}
                            DoIt := True;
                            If Wanted.Count > 0 Then DoIt := Wanted.IndexOf(Fp.Name) >= 0;
                            If DoIt Then Begin
                            {{ Make this footprint current BEFORE touching it: the library's Board
                              exposes the current component's primitives, and that is the object graph
                              the save serialises. }}
                            CurrentLib.SetState_CurrentComponent(Fp);
                            Board := CurrentLib.Board;
                            Fp.BeginModify;
                            {{ Idempotent: drop any body already referencing this same model file, so
                              re-running never stacks duplicates. Collected first, because removing
                              during iteration invalidates the iterator. }}
                            Stale := TObjectList.Create;
                            Stale.OwnsObjects := False;
                            BIter := Fp.GroupIterator_Create;
                            BIter.AddFilter_ObjectSet(MkSet(eComponentBodyObject));
                            Old := BIter.FirstPCBObject;
                            While Old <> Nil Do
                            Begin
                                If Old.Model <> Nil Then
                                    If SameString(ExtractFileName(Old.Model.FileName), StepName, False) Then
                                        Stale.Add(Old);
                                Old := BIter.NextPCBObject;
                            End;
                            Fp.GroupIterator_Destroy(BIter);
                            For k := 0 To Stale.Count - 1 Do
                            Begin
                                Board.RemovePCBObject(Stale.Items(k));
                                removed := removed + 1;
                            End;
                            Stale.Free;

                            Body := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
                            If Body = Nil Then L.Add('FAIL: could not create a body object')
                            Else
                            Begin
                                {{ The second argument is the EMBED flag: True stores the geometry in
                                  the library, which is what a git-synced shared library needs, since a
                                  linked path cannot survive the library moving to another machine. }}
                                Model := Body.ModelFactory_FromFilename(StepPath, True);
                                If Model = Nil Then L.Add('FAIL: Altium could not load ' + StepPath)
                                Else
                                Begin
                                    Body.BeginModify;
                                    {{ Assign FIRST, then derive: SetState_FromModel reads the body's
                                      CURRENT model, so deriving before assigning derives from nothing. }}
                                    Body.Model := Model;
                                    Body.SetState_FromModel;
                                    Body.Layer := eTopLayer;
                                    Board.AddPCBObject(Body);
                                    Body.EndModify;
                                    PCBServer.SendMessageToRobots(Board.I_ObjectAddress, c_Broadcast,
                                                                  PCBM_BoardRegisteration, Body.I_ObjectAddress);
                                    added := added + 1;
                                    L.Add('embedded ' + StepName + ' into ' + Fp.Name);
                                End;
                            End;
                            Fp.EndModify;
                            Fp.GraphicallyInvalidate;
                            End; {{ DoIt }}
                        End;
                        Wanted.Free;
                        PCBServer.PostProcess;
                        CurrentLib.RefreshView;
                        Board.ViewManager_FullUpdate;
                        {{ DoFileSave is a FUNCTION. Calling it as a procedure throws the answer away,
                          which made a REFUSED save look exactly like a successful one. }}
                        SaveOk := Doc.DoFileSave('PcbLib');
                        If SaveOk Then L.Add('saved ' + Doc.FileName)
                        Else L.Add('FAIL: the save was REFUSED for ' + Doc.FileName);
                        Client.CloseDocument(Doc);
                    End;
                End;
            End;
        Except
            L.Add('FAIL: Altium raised an exception during the embed');
        End;
    Finally
        {{ The marker is written on EVERY path, so the caller never has to infer an outcome from
          how long the run took. }}
        L.Add('DONE added=' + IntToStr(added) + ' removed=' + IntToStr(removed));
        L.SaveToFile({marker});
        L.Free;
    End;
    TerminateWithExitCode(0);
End;
"""


def embed_model(
    pcblib: Path,
    step: Path,
    *,
    footprints: tuple[str, ...] = (),
    driver: AltiumDriver | None = None,
    workdir: Path | None = None,
    timeout: int = 240,
    replace: bool = False,
) -> EmbedResult:
    """Embed `step` into every (or every named) footprint of `pcblib`, in place.

    Returns a result carrying both Altium's own log and an independent count of the model
    payloads found in the saved container. A run that Altium reports as fine but that wrote no
    payload comes back `not-written`, which is exactly the failure that went unnoticed for ten
    boots when only Altium's word was consulted.

    Already embedded is a SKIP, not a repeat. Measured 2026-07-25 by running it twice: Altium
    replaces the 3D body but keeps the superseded model payload in the container, so a blind
    re-embed added another 63 KB to a git-synced binary every time. Since the model index can be
    read from outside Altium, the second run costs nothing at all now. `replace=True` overrides
    for a model whose geometry genuinely changed, and the result then reports how many superseded
    payloads the container is carrying rather than hiding the cost.
    """
    drv = driver or AltiumDriver()
    pcblib, step = Path(pcblib), Path(step)
    if not pcblib.exists():
        return EmbedResult("not-written", f"The library {pcblib.name} does not exist.")
    if not step.exists():
        return EmbedResult("not-written", f"The 3D model {step.name} does not exist.")

    existing = read_model_index(pcblib)
    if model_name_present(existing, step.name) and not replace:
        payloads = _payloads(pcblib)
        return EmbedResult(
            "ok",
            f"{step.name} is already embedded in {pcblib.name}; nothing to do. Pass replace to "
            "re-embed a model whose geometry changed.",
            embedded=len(payloads),
            payload_bytes=sum(payloads.values()),
        )

    work = Path(workdir) if workdir else drv.host.windows_temp() / "stockroom-embed3d"
    work.mkdir(parents=True, exist_ok=True)
    pas = work / "SREmbed3D.pas"
    prj = work / "SREmbed3D.PrjScr"
    marker = work / "SREmbed3D.txt"

    pas.write_text(
        render_embed_script(
            pcblib_win=drv.host.to_windows_path(str(pcblib)),
            step_win=drv.host.to_windows_path(str(step)),
            marker_win=drv.host.to_windows_path(str(marker)),
            footprints=footprints,
        ),
        encoding="utf-8",
        newline="\r\n",
    )
    # A .PrjScr wrapper, because a bare --script form resolves the procedure less reliably than
    # a one-document script project does.
    prj.write_text(
        "[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n[Document1]\r\n"
        f"DocumentPath={pas.name}\r\n",
        encoding="utf-8",
    )

    before = _payloads(pcblib)
    outcome: RunOutcome = drv.run_script(
        project=prj, proc=f"{pas.name}>SREmbed3D", marker=marker, timeout=timeout
    )
    if not outcome.ok:
        return EmbedResult(outcome.status, outcome.detail, altium_log=outcome.marker_text)

    after = _payloads(pcblib)
    if "FAIL" in outcome.marker_text:
        first = next(
            (ln for ln in outcome.marker_text.splitlines() if "FAIL" in ln), "the script reported a failure"
        )
        return EmbedResult("not-written", first.strip(), altium_log=outcome.marker_text)
    if len(after) <= len(before):
        return EmbedResult(
            "not-written",
            "Altium reported success but the library gained no 3D model payload, so nothing "
            "was actually written. Do not treat this as done.",
            embedded=len(after),
            payload_bytes=sum(after.values()),
            altium_log=outcome.marker_text,
        )
    # A payload per embed, and Altium never prunes the superseded ones. Counting them here is the
    # honest alternative to pretending an in-place replace is free.
    orphaned = max(0, len(after) - 1)
    detail = (
        f"Embedded {step.name} into {pcblib.name} "
        f"({sum(after.values()) - sum(before.values())} bytes of model payload added)."
    )
    if orphaned:
        detail += (
            f" The container also carries {orphaned} superseded model "
            f"{'payload' if orphaned == 1 else 'payloads'} that Altium does not prune; restore the "
            "library from git before re-embedding if the size matters."
        )
    return EmbedResult(
        "ok",
        detail,
        embedded=len(after),
        payload_bytes=sum(after.values()),
        orphaned=orphaned,
        altium_log=outcome.marker_text,
    )


def main(argv: list[str] | None = None) -> int:
    """`python -m stockroom.altium.embed3d <library.PcbLib> <model.step> [footprint ...]`

    A real CLI so the seam can be driven directly on a machine with Altium, which is how it gets
    verified against the owner's own libraries without going through the whole app.
    """
    import argparse

    ap = argparse.ArgumentParser(description="Embed a STEP model into a .PcbLib as a 3D Body")
    ap.add_argument("pcblib", type=Path)
    ap.add_argument("step", type=Path)
    ap.add_argument("footprints", nargs="*", help="limit to these entries (default: all)")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument(
        "--replace",
        action="store_true",
        help="re-embed even if this model is already present (for changed geometry)",
    )
    args = ap.parse_args(argv)

    result = embed_model(
        args.pcblib,
        args.step,
        footprints=tuple(args.footprints),
        timeout=args.timeout,
        replace=args.replace,
    )
    print(f"{result.status}: {result.detail}")
    if result.altium_log:
        print("--- Altium said ---")
        print(result.altium_log)
    return 0 if result.ok else 1


def _payloads(pcblib: Path) -> dict[int, int]:
    """Model payloads in a container, or empty if it cannot be read as one. A library Altium has
    not yet touched can legitimately be unreadable here; that is not an error to raise, it is a
    baseline of zero."""
    try:
        return embedded_models(ole_streams(pcblib))
    except Exception:
        return {}


if __name__ == "__main__":
    import sys

    sys.exit(main())
