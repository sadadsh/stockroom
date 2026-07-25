#!/usr/bin/env python3
"""Run a CONTROLLED PcbLib-write experiment inside the real Altium, one variant per boot.

Why this exists
---------------
Punch 16 (embed a STEP model into a footprint) has burned roughly ten Altium boots on hand-edited
one-off `.pas` files in `C:\\srprobe\\`. Every one of them repeated the same four steps by hand:
copy a library to a scratch path, write a script, run it through `altium.py`, then squint at the
bytes. That is the third-time-is-tooling threshold, so it is a script now.

What it adds over retyping the loop
-----------------------------------
1. **Every run is isolated.** A fresh copy of the baseline library per variant, so one experiment can
   never inherit another's edit (the earlier runs all shared ONE file, which is how a one-time
   normalisation got misread as "my edit landed").
2. **Two INDEPENDENT verdicts per boot.** Altium re-opens the file it just saved and counts what came
   back, AND `olefile` diffs the container from outside Altium. An agreement is trustworthy; a
   disagreement is itself the finding. Neither is inferred from elapsed time.
3. **A control in the same run.** Each variant may add a plain TRACK next to the 3D body, so a failure
   says WHICH it was: no track and no body means scripted PcbLib writes are broken here in general
   and the object API is the wrong layer; a track but no body makes it 3D-body-specific.

Usage
-----
    uv run python scripts/altium_probe.py --list
    uv run python scripts/altium_probe.py --variant board-add
    uv run python scripts/altium_probe.py --variant fp-add --keep

No em dashes anywhere (standing owner rule).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE_ROOT = Path("/mnt/c/srprobe")
RUN_DIR = PROBE_ROOT / "run"
BASELINE_LIB = PROBE_ROOT / "lib" / "tpd6e05u06rvzr.PcbLib"
STEP_FILE = PROBE_ROOT / "lib" / "TPD6E05U06RVZR.stp"


def _win(p: Path) -> str:
    out = subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True)
    return out.stdout.strip() or str(p)


# Each variant is the EDIT BLOCK only. The template around it (open, iterate footprints, save, close,
# re-open, count) is identical everywhere so a difference in outcome can only come from the edit.
#
# In scope inside a block: `Fp` (IPCB_LibComponent, already the library's current component), `Board`
# (IPCB_Board, re-read after SetState_CurrentComponent), `L` (the log), `StepPath`.
VARIANTS: dict[str, tuple[str, str]] = {
    # The baseline that is KNOWN to fail, kept so the harness itself can be proven able to show a
    # failure. A probe that only ever runs the hypothesis cannot tell success from a broken harness.
    "fp-add": (
        "current behaviour: body added with Fp.AddPCBObject, no BeginModify (known to NOT persist)",
        """
        Body := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
        Model := Body.ModelFactory_FromFilename(StepPath, True);
        If Model = Nil Then L.Add('FAIL: model nil')
        Else
        Begin
            Body.Model := Model;
            Body.SetState_FromModel;
            Fp.AddPCBObject(Body);
            L.Add('  added body via Fp.AddPCBObject to ' + Fp.Name);
        End;
        """,
    ),
    # The ISOLATION run. Identical to `board-add` except for the one call under test, so a pass here
    # would mean BeginModify/Layer were the cause and a fail pins it on `Board.AddPCBObject`. Without
    # this the winning variant changed four things at once and the finding would be a guess.
    "fp-add-full": (
        "3D body with BeginModify + Layer but still Fp.AddPCBObject (isolates the add call)",
        """
        Body := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
        Model := Body.ModelFactory_FromFilename(StepPath, True);
        If Model = Nil Then L.Add('FAIL: model nil')
        Else
        Begin
            Body.BeginModify;
            Body.Model := Model;
            Body.SetState_FromModel;
            Body.Layer := eTopLayer;
            Fp.AddPCBObject(Body);
            Body.EndModify;
            PCBServer.SendMessageToRobots(Board.I_ObjectAddress, c_Broadcast,
                                          PCBM_BoardRegisteration, Body.I_ObjectAddress);
            L.Add('  added body via Fp.AddPCBObject (with BeginModify + Layer)');
        End;
        """,
    ),
    # THE CONTROL PLUS THE HYPOTHESIS, in one boot.
    #
    # A track added exactly the way the one community script proven to write PcbLib primitives does it
    # (BrettLMiller/Altium-DelphiScripts OutlineRegionsOnLayer.pas: BeginModify, Board.AddPCBObject,
    # EndModify, then the BoardRegisteration broadcast). If the TRACK does not persist either, no 3D
    # hypothesis matters, because nothing scripted persists into a PcbLib on this install.
    "board-add": (
        "control track + 3D body, both via Board.AddPCBObject with BeginModify/EndModify",
        """
        Track := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
        Track.BeginModify;
        Track.Width := MilsToCoord(10);
        Track.Layer := eTopOverlay;
        Track.x1 := Board.XOrigin + MilsToCoord(-40);
        Track.y1 := Board.YOrigin + MilsToCoord(-40);
        Track.x2 := Board.XOrigin + MilsToCoord(40);
        Track.y2 := Board.YOrigin + MilsToCoord(-40);
        Board.AddPCBObject(Track);
        Track.EndModify;
        PCBServer.SendMessageToRobots(Board.I_ObjectAddress, c_Broadcast,
                                      PCBM_BoardRegisteration, Track.I_ObjectAddress);
        L.Add('  added control track via Board.AddPCBObject');

        Body := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
        Model := Body.ModelFactory_FromFilename(StepPath, True);
        If Model = Nil Then L.Add('FAIL: model nil')
        Else
        Begin
            Body.BeginModify;
            Body.Model := Model;
            Body.SetState_FromModel;
            Body.Layer := eTopLayer;
            Board.AddPCBObject(Body);
            Body.EndModify;
            PCBServer.SendMessageToRobots(Board.I_ObjectAddress, c_Broadcast,
                                          PCBM_BoardRegisteration, Body.I_ObjectAddress);
            L.Add('  added body via Board.AddPCBObject to ' + Fp.Name);
            L.Add('  model.name=' + Model.Name);
            L.Add('  body.OverallHeight=' + FloatToStr(CoordToMMs(Body.OverallHeight)));
        End;
        """,
    ),
}

TEMPLATE = r"""{ GENERATED by scripts/altium_probe.py -- variant: __VARIANT__
  Do not hand-edit; edit the VARIANTS table in the driver instead. }
Procedure SRProbe;
Var
    CurrentLib : IPCB_Library;
    Fp         : IPCB_LibComponent;
    Body       : IPCB_ComponentBody;
    Model      : IPCB_Model;
    Track      : IPCB_Track;
    Board      : IPCB_Board;
    Doc        : IServerDocument;
    BIter      : IPCB_GroupIterator;
    Prim       : IPCB_ComponentBody;
    L          : TStringList;
    LibPath    : String;
    StepPath   : String;
    SaveOk     : Boolean;
    j          : Integer;
    nBody      : Integer;
    nTrack     : Integer;
Begin
    LibPath  := '__LIB__';
    StepPath := '__STEP__';
    L := TStringList.Create;
    Try
        Try
            Doc := Client.OpenDocument('PCBLIB', LibPath);
            Client.ShowDocument(Doc);
            CurrentLib := PCBServer.GetCurrentPCBLibrary;
            If CurrentLib = Nil Then L.Add('FAIL: GetCurrentPCBLibrary nil')
            Else
            Begin
                PCBServer.PreProcess;
                For j := 0 To CurrentLib.ComponentCount - 1 Do
                Begin
                    Fp := CurrentLib.GetComponent(j);
                    CurrentLib.SetState_CurrentComponent(Fp);
                    Board := CurrentLib.Board;
                    Fp.BeginModify;
__EDIT__
                    Fp.EndModify;
                    Fp.GraphicallyInvalidate;
                End;
                PCBServer.PostProcess;
                CurrentLib.RefreshView;
                Board.ViewManager_FullUpdate;
                { DoFileSave is a FUNCTION; an earlier probe called it as a procedure and threw the
                  answer away, so a refused save looked exactly like a successful one. Spelled out
                  with If/Else rather than BoolToStr to keep the member surface small: an unknown
                  identifier does not raise, it stops the script loading and costs a whole boot. }
                SaveOk := Doc.DoFileSave('PcbLib');
                If SaveOk Then L.Add('DoFileSave=TRUE  file=' + Doc.FileName)
                Else L.Add('DoFileSave=FALSE (REFUSED)  file=' + Doc.FileName);
                Client.CloseDocument(Doc);

                { READ IT BACK from disk in this same run. Closing the document drops the in-memory
                  graph, so a count here is a count of what was actually serialised. The olefile pass
                  in the driver checks the same thing from OUTSIDE Altium, and the two must agree. }
                Doc := Client.OpenDocument('PCBLIB', LibPath);
                Client.ShowDocument(Doc);
                CurrentLib := PCBServer.GetCurrentPCBLibrary;
                nBody  := 0;
                nTrack := 0;
                If CurrentLib = Nil Then L.Add('FAIL: reopen gave no library')
                Else
                    For j := 0 To CurrentLib.ComponentCount - 1 Do
                    Begin
                        Fp := CurrentLib.GetComponent(j);
                        CurrentLib.SetState_CurrentComponent(Fp);
                        BIter := Fp.GroupIterator_Create;
                        BIter.AddFilter_ObjectSet(MkSet(eComponentBodyObject, eTrackObject));
                        Prim := BIter.FirstPCBObject;
                        While Prim <> Nil Do
                        Begin
                            If Prim.ObjectId = eComponentBodyObject Then
                            Begin
                                nBody := nBody + 1;
                                If Prim.Model = Nil Then L.Add('  persisted body with NO model')
                                Else L.Add('  persisted body model=' + Prim.Model.Name);
                            End
                            Else nTrack := nTrack + 1;
                            Prim := BIter.NextPCBObject;
                        End;
                        Fp.GroupIterator_Destroy(BIter);
                    End;
                L.Add('OK bodies=' + IntToStr(nBody) + ' tracks=' + IntToStr(nTrack));
            End;
        Except
            L.Add('FAIL: exception raised');
        End;
    Finally
        L.SaveToFile('__MARKER__');
        L.Free;
    End;
    TerminateWithExitCode(0);
End;
"""


def ole_entries(path: Path) -> dict[str, int]:
    """Every stream in the OLE container with its size, read from OUTSIDE Altium.

    Full paths WITH sizes, deliberately: an earlier check used
    `name.lower().startswith('models')`, which can never match `Library/Models/Data` because the path
    begins with `Library/`. That predicate would have missed a real success.
    """
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        return {"/".join(p): ole.get_size("/".join(p)) for p in ole.listdir(streams=True)}


def report_delta(baseline: Path, after: Path) -> bool:
    """Print the container diff. Returns True if anything looks like a 3D payload landed."""
    a, b = ole_entries(baseline), ole_entries(after)
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    print(f"  olefile: {baseline.stat().st_size} -> {after.stat().st_size} bytes")
    print(f"  new streams: {added or 'NONE'}")
    if removed:
        print(f"  removed streams: {removed}")
    for k in changed:
        print(f"  changed: {k}  {a[k]} -> {b[k]}  ({b[k] - a[k]:+d})")
    if not changed and not added:
        print("  changed: NOTHING (the save wrote an identical container)")
    # A real embedded STEP payload is large, so a model stream that is still empty is decisive.
    model_streams = {k: v for k, v in b.items() if "models" in k.lower() and k.endswith("Data")}
    for k, v in sorted(model_streams.items()):
        print(f"  model payload: {k} = {v} bytes" + ("  <-- EMPTY" if v == 0 else "  <-- HAS DATA"))
    return any(v > 0 for v in model_streams.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", help="which experiment to run")
    ap.add_argument("--list", action="store_true", help="list the variants and exit")
    ap.add_argument("--baseline", type=Path, default=BASELINE_LIB)
    ap.add_argument("--step", type=Path, default=STEP_FILE)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--keep", action="store_true", help="leave Altium running after the run")
    args = ap.parse_args()

    if args.list or not args.variant:
        for name, (why, _body) in VARIANTS.items():
            print(f"{name:14s} {why}")
        return 0 if args.list else 2
    if args.variant not in VARIANTS:
        print(f"unknown variant {args.variant!r}; --list shows them", file=sys.stderr)
        return 2
    for needed in (args.baseline, args.step):
        if not needed.exists():
            print(f"missing input: {needed}", file=sys.stderr)
            return 2

    why, edit = VARIANTS[args.variant]
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    lib = RUN_DIR / f"{args.variant}.PcbLib"
    pas = RUN_DIR / f"{args.variant}.pas"
    prj = RUN_DIR / f"{args.variant}.PrjScr"
    marker = RUN_DIR / f"{args.variant}.txt"
    shutil.copy2(args.baseline, lib)  # a FRESH copy, so no run inherits another's edit
    marker.unlink(missing_ok=True)

    pas.write_text(
        TEMPLATE.replace("__VARIANT__", args.variant)
        .replace("__LIB__", _win(lib))
        .replace("__STEP__", _win(args.step))
        .replace("__MARKER__", _win(marker))
        .replace("__EDIT__", edit),
        encoding="utf-8",
        newline="\r\n",
    )
    prj.write_text(
        f"[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n[Document1]\r\nDocumentPath={pas.name}\r\n",
        encoding="utf-8",
    )

    print(f"variant: {args.variant}  ({why})")
    print(f"library: {lib.as_posix()}  (fresh copy of {args.baseline.name})")
    cmd = [
        sys.executable, str(HERE / "altium.py"), "run",
        "--project", _win(prj), "--proc", f"{pas.name}>SRProbe",
        "--marker", str(marker), "--timeout", str(args.timeout),
    ]
    if not args.keep:
        cmd.append("--stop-after")
    rc = subprocess.run(cmd).returncode

    print("\n--- independent check, from outside Altium ---")
    if not lib.exists():
        print("  the library is GONE; nothing to inspect")
        return rc or 1
    try:
        report_delta(args.baseline, lib)
    except Exception as exc:  # a corrupt container is itself a result worth seeing
        print(f"  olefile could not read the result: {exc}")
        return rc or 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
