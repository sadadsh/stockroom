"""Isolated native Altium authoring proof for one supported canonical profile.

This is deliberately a proof adapter, not the production Altium bridge. It consumes one strict
``CanonicalPassiveBundle`` JSON document, writes only beneath a caller-owned empty output
directory, and asks the installed Altium Designer to author both binary libraries in one
DelphiScript run. The script closes and reopens its own output before reporting semantics. Exact
manufacturer/MPN identities vary, but the admitted geometry remains the one diode/SMA shared
template contract that this renderer and its readback have live-qualified.

Python then performs an independent readback from outside Altium:

* authoritative SchLib and PcbLib entry names through :mod:`stockroom.altium.oleread`;
* the PcbLib model index through :mod:`stockroom.altium.embed3d`;
* the numbered, zlib-compressed OLE model payload, byte-for-byte against the input STEP file.

The two bootstraps are explicit. ``factory`` uses the editor servers' in-memory library factories.
``workspace`` uses ``DM_CreateNewDocument`` and the normal server-document save path. Keeping the
choice in evidence makes a live probe discriminating rather than an opaque fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import olefile

from stockroom.domain import CanonicalPassiveBundle
from stockroom.templates import representative_passive_template

from .driver import AltiumDriver
from .embed3d import delphi_quote, model_name_present, read_model_index
from .oleread import read_footprint_names, read_symbol_names

Bootstrap = Literal["factory", "workspace"]

_SUPPORTED_PROFILE = representative_passive_template()
_SUPPORTED_PACKAGE = _SUPPORTED_PROFILE.package
_SUPPORTED_BODY = (
    _SUPPORTED_PROFILE.body_min_x_nm,
    _SUPPORTED_PROFILE.body_min_y_nm,
    _SUPPORTED_PROFILE.body_max_x_nm,
    _SUPPORTED_PROFILE.body_max_y_nm,
)
_SUPPORTED_TERMINALS = tuple(
    (
        terminal.number,
        terminal.role,
        terminal.x_nm,
        terminal.y_nm,
        terminal.rotation_udeg,
        terminal.electrical_type,
    )
    for terminal in _SUPPORTED_PROFILE.terminals
)
_ROLE_PIN_NAME = {"cathode": "K", "anode": "A"}
_IDENTIFIER_SLUG_LIMIT = 40
_MAX_ALTIUM_IDENTIFIER_LENGTH = 104
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+\Z")
_SAFE_PROCEDURE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
_MODEL_PAYLOAD = re.compile(r"^Library/Models/(\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NativeAuthoringNames:
    """Collision-safe Altium identifiers derived from one exact canonical identity."""

    symbol: str
    footprint: str

    @property
    def schlib_filename(self) -> str:
        return f"{self.symbol}.SchLib"

    @property
    def pcblib_filename(self) -> str:
        return f"{self.footprint}.PcbLib"


@dataclass(frozen=True, slots=True)
class NativeAuthoringResult:
    """One isolated authoring attempt and the evidence it retained."""

    status: str
    detail: str
    output_dir: Path
    schlib: Path
    pcblib: Path
    semantic_marker: Path
    evidence: Path
    semantic_report: dict[str, object] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _validated_supported_bundle(
    bundle: CanonicalPassiveBundle,
) -> CanonicalPassiveBundle:
    """Revalidate all links, then admit only the geometry this script really renders."""

    if not isinstance(bundle, CanonicalPassiveBundle):
        raise TypeError("bundle must be a CanonicalPassiveBundle")
    checked = CanonicalPassiveBundle.model_validate(bundle.model_dump(mode="python"))
    package = next(claim.value for claim in checked.claims if claim.key == "package")
    value = next(claim.value for claim in checked.claims if claim.key == "value")
    for text, field_name in (
        (checked.manufacturer.authoritative_key, "manufacturer"),
        (checked.identity.mpn_canonical, "MPN"),
        (value, "value"),
        (package, "package"),
    ):
        if not text.isascii():
            raise ValueError(
                f"canonical {field_name} contains non-ASCII text whose exact AD26 "
                "round-trip has not been independently qualified"
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in text):
            raise ValueError(
                f"canonical {field_name} contains a control character that DelphiScript "
                "cannot preserve"
            )
    templates = tuple(
        (template.template_id, template.kind, template.contract_digest)
        for template in checked.artifacts.shared_templates
    )
    body = checked.definition.body
    body_contract = (
        body.min_x_nm,
        body.min_y_nm,
        body.max_x_nm,
        body.max_y_nm,
    )
    terminal_contract = tuple(
        (
            terminal.number,
            terminal.role,
            terminal.position.x_nm,
            terminal.position.y_nm,
            terminal.rotation_udeg,
            terminal.electrical_type,
        )
        for terminal in checked.definition.terminals
    )
    bindings = {binding.tool: binding for binding in checked.artifacts.tool_bindings}
    binding_contract = {
        tool: (
            binding.symbol_template_id,
            binding.footprint_template_id,
            tuple(item.tool_terminal for item in binding.terminal_bindings),
        )
        for tool, binding in bindings.items()
    }
    expected_templates = tuple(
        (template.template_id, template.kind, template.contract_digest)
        for template in _SUPPORTED_PROFILE.artifacts
    )
    expected_bindings = {
        binding.tool: (
            binding.symbol_template_id,
            binding.footprint_template_id,
            tuple(terminal.tool_terminal for terminal in binding.terminal_bindings),
        )
        for binding in _SUPPORTED_PROFILE.tool_bindings
    }

    if (
        checked.definition.definition_kind != "two_pin_passive"
        or checked.definition.functional_kind != _SUPPORTED_PROFILE.functional_kind
        or package != _SUPPORTED_PACKAGE
        or templates != expected_templates
        or body_contract != _SUPPORTED_BODY
        or terminal_contract != _SUPPORTED_TERMINALS
        or binding_contract != expected_bindings
    ):
        raise ValueError(
            "native Altium authoring supports only the exact two-pin diode/SMA "
            "shared-template geometry and KiCad 1/2 plus Altium C/A terminal contract"
        )
    return checked


def _load_supported_bundle(path: Path) -> CanonicalPassiveBundle:
    try:
        bundle = CanonicalPassiveBundle.model_validate_json(Path(path).read_bytes())
    except Exception as exc:
        raise ValueError(f"{Path(path).name} is not a valid canonical passive bundle") from exc
    return _validated_supported_bundle(bundle)


def _identifier_slug(value: str) -> str:
    characters = [
        character if character.isascii() and character.isalnum() else "_" for character in value
    ]
    slug = re.sub(r"_+", "_", "".join(characters)).strip("_")
    return (slug or "PART")[:_IDENTIFIER_SLUG_LIMIT]


def _names_for_supported_bundle(bundle: CanonicalPassiveBundle) -> NativeAuthoringNames:
    slug = _identifier_slug(bundle.identity.mpn_canonical)
    identity = bundle.identity.component_id
    names = NativeAuthoringNames(
        symbol=f"SYM_{slug}__{identity}",
        footprint=f"FP_{slug}__{identity}",
    )
    for name in (names.symbol, names.footprint):
        if (
            len(name) > _MAX_ALTIUM_IDENTIFIER_LENGTH
            or _SAFE_IDENTIFIER.fullmatch(name) is None
            or ".." in name
        ):
            raise AssertionError("derived Altium identifier violated its bounded safe contract")
    if names.symbol.casefold() == names.footprint.casefold():
        raise AssertionError("derived Altium symbol and footprint identifiers collided")
    return names


def native_authoring_names(bundle: CanonicalPassiveBundle) -> NativeAuthoringNames:
    """Return bounded path-safe names carrying the full exact component identity."""

    checked = _validated_supported_bundle(bundle)
    return _names_for_supported_bundle(checked)


def _altium_terminal_semantics(
    bundle: CanonicalPassiveBundle,
) -> tuple[tuple[str, str], tuple[str, str]]:
    binding = next(
        binding for binding in bundle.artifacts.tool_bindings if binding.tool == "altium"
    )
    role_by_number = {terminal.number: terminal.role for terminal in bundle.definition.terminals}
    terminals = tuple(
        (
            item.tool_terminal,
            _ROLE_PIN_NAME[role_by_number[item.canonical_terminal]],
        )
        for item in binding.terminal_bindings
    )
    if len(terminals) != 2:
        raise AssertionError("validated two-pin profile produced a non-two-pin binding")
    return terminals


def expected_semantic_report(
    bundle: CanonicalPassiveBundle,
    step_name: str,
    bootstrap: Bootstrap,
) -> dict[str, object]:
    """The exact native semantics the generated script must read back after reopen."""

    checked = _validated_supported_bundle(bundle)
    names = _names_for_supported_bundle(checked)
    terminals = _altium_terminal_semantics(checked)
    return {
        "bootstrap": bootstrap,
        "canonical_digest": checked.canonical_digest(),
        "footprint": {
            "component_body_count": 1,
            "embedded_models": [Path(step_name).name],
            "name": names.footprint,
            "pad_count": 2,
            "pads": [number for number, _name in terminals],
        },
        "identity": {
            "component_id": checked.identity.component_id,
            "manufacturer": checked.manufacturer.authoritative_key,
            "mpn": checked.identity.mpn_canonical,
        },
        "schema_version": 1,
        "status": "ok",
        "symbol": {
            "name": names.symbol,
            "parameters": {
                "MF": checked.manufacturer.authoritative_key,
                "MP": checked.identity.mpn_canonical,
            },
            "pin_count": 2,
            "pins": [{"name": name, "number": number} for number, name in terminals],
        },
    }


def render_native_authoring_script(
    bundle: CanonicalPassiveBundle,
    *,
    schlib_win: str,
    pcblib_win: str,
    step_win: str,
    marker_win: str,
    bootstrap: Bootstrap = "factory",
    procedure: str = "SRNativeAuthoring",
) -> str:
    """Render the single-run native SchLib/PcbLib/STEP authoring script."""

    if bootstrap not in ("factory", "workspace"):
        raise ValueError("bootstrap must be 'factory' or 'workspace'")
    if _SAFE_PROCEDURE.fullmatch(procedure) is None:
        raise ValueError("procedure must be a bounded DelphiScript identifier")
    checked = _validated_supported_bundle(bundle)
    names = _names_for_supported_bundle(checked)
    terminals = _altium_terminal_semantics(checked)
    value = next(claim.value for claim in checked.claims if claim.key == "value")
    package = next(claim.value for claim in checked.claims if claim.key == "package")

    if bootstrap == "factory":
        sch_create = """
            SchLib := SchServer.CreateSchLibrary;
            SchDoc := Nil;
"""
        sch_save = """
                    SchLib.TransferComponentsPrimitivesToEditor;
                    SchLib.SaveToFile(SchPath);
                    SaveOk := FileExists(SchPath);
"""
        pcb_create = """
            PcbLib := PCBServer.CreatePCBLibrary;
            PcbDoc := Nil;
"""
        pcb_save = """
                    Footprint.TransferAllPrimitivesBackFromBoard;
                    SaveOk := PcbLib.SaveComponentWithLibrary(FootprintName, PcbPath);
"""
    else:
        sch_create = """
            WorkSpace := GetWorkSpace;
            If WorkSpace = Nil Then
            Begin
                Ok := False;
                FailureCode := 'workspace-nil';
            End;
            If Ok Then
            Begin
                NewDocumentPath := WorkSpace.DM_CreateNewDocument('SCHLIB');
                SchDoc := Client.GetDocumentByPath(NewDocumentPath);
                If SchDoc = Nil Then SchDoc := Client.LastActiveDocumentOfType('SCHLIB');
                If SchDoc <> Nil Then Client.ShowDocument(SchDoc);
                SchLib := SchServer.GetCurrentSchDocument;
            End;
"""
        sch_save = """
                    SchLib.TransferComponentsPrimitivesToEditor;
                    SaveOk := SchDoc.DoSafeChangeFileNameAndSave(SchPath, 'SchLib');
                    Client.CloseDocument(SchDoc);
                    SchDoc := Nil;
"""
        pcb_create = """
            WorkSpace := GetWorkSpace;
            If WorkSpace = Nil Then
            Begin
                Ok := False;
                FailureCode := 'workspace-nil';
            End;
            If Ok Then
            Begin
                NewDocumentPath := WorkSpace.DM_CreateNewDocument('PCBLIB');
                PcbDoc := Client.GetDocumentByPath(NewDocumentPath);
                If PcbDoc = Nil Then PcbDoc := Client.LastActiveDocumentOfType('PCBLIB');
                If PcbDoc <> Nil Then Client.ShowDocument(PcbDoc);
                PcbLib := PCBServer.GetCurrentPCBLibrary;
            End;
"""
        pcb_save = """
                    Footprint.TransferAllPrimitivesBackFromBoard;
                    SaveOk := PcbDoc.DoSafeChangeFileNameAndSave(PcbPath, 'PcbLib');
                    Client.CloseDocument(PcbDoc);
                    PcbDoc := Nil;
"""

    success = json.dumps(
        expected_semantic_report(checked, Path(step_win).name, bootstrap),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    replacements = {
        "__PROCEDURE__": procedure,
        "__SCHLIB__": delphi_quote(schlib_win),
        "__PCBLIB__": delphi_quote(pcblib_win),
        "__STEP__": delphi_quote(step_win),
        "__MARKER__": delphi_quote(marker_win),
        "__SYMBOL__": delphi_quote(names.symbol),
        "__FOOTPRINT__": delphi_quote(names.footprint),
        "__SYMBOL_DESCRIPTION__": delphi_quote(f"{value} diode"),
        "__FOOTPRINT_DESCRIPTION__": delphi_quote(f"{package} diode footprint"),
        "__MANUFACTURER__": delphi_quote(checked.manufacturer.authoritative_key),
        "__MPN__": delphi_quote(checked.identity.mpn_canonical),
        "__PIN1_NUMBER__": delphi_quote(terminals[0][0]),
        "__PIN1_NAME__": delphi_quote(terminals[0][1]),
        "__PIN2_NUMBER__": delphi_quote(terminals[1][0]),
        "__PIN2_NAME__": delphi_quote(terminals[1][1]),
        "__STEP_NAME__": delphi_quote(Path(step_win).name),
        "__BOOTSTRAP__": bootstrap,
        "__SUCCESS_JSON__": delphi_quote(success),
        "__SCH_CREATE__": sch_create.rstrip(),
        "__SCH_SAVE__": sch_save.rstrip(),
        "__PCB_CREATE__": pcb_create.rstrip(),
        "__PCB_SAVE__": pcb_save.rstrip(),
    }
    token_pattern = re.compile(
        "|".join(re.escape(token) for token in sorted(replacements, key=len, reverse=True))
    )
    return token_pattern.sub(lambda match: replacements[match.group(0)], _SCRIPT_TEMPLATE)


_SCRIPT_TEMPLATE = r"""{ GENERATED by stockroom.altium.native_authoring -- scratch proof only.
  Creates one native SchLib and one native PcbLib, embeds one STEP payload, closes and reopens
  both files, and writes strict semantic JSON. It never opens or mutates an active library. }
Procedure __PROCEDURE__;
Var
    Ok                 : Boolean;
    SaveOk             : Boolean;
    Stage              : String;
    FailureCode        : String;
    SchPath            : String;
    PcbPath            : String;
    StepPath           : String;
    StepName           : String;
    MarkerPath         : String;
    SymbolName         : String;
    FootprintName      : String;
    NewDocumentPath    : String;
    Report             : TStringList;
    WorkSpace          : IWorkSpace;
    SchDoc             : IServerDocument;
    PcbDoc             : IServerDocument;
    ReadSchDoc         : IServerDocument;
    ReadPcbDoc         : IServerDocument;
    SchLib             : ISch_Lib;
    SchComponent       : ISch_Component;
    SchRect            : ISch_Rectangle;
    SchPin             : ISch_Pin;
    SchParameter       : ISch_Parameter;
    SchObject          : ISch_BasicContainer;
    SchIterator        : ISch_Iterator;
    PcbLib             : IPCB_Library;
    Footprint          : IPCB_LibComponent;
    Board              : IPCB_Board;
    PcbPad             : IPCB_Pad;
    PersistedPad       : IPCB_Pad;
    Body               : IPCB_ComponentBody;
    PersistedBody      : IPCB_ComponentBody;
    Model              : IPCB_Model;
    PcbPrimitive       : IPCB_Primitive;
    PcbIterator        : IPCB_GroupIterator;
    PinCount           : Integer;
    PadCount           : Integer;
    BodyCount          : Integer;
    SeenPinC           : Boolean;
    SeenPinA           : Boolean;
    SeenPadC           : Boolean;
    SeenPadA           : Boolean;
    SeenMF             : Boolean;
    SeenMP             : Boolean;
    SeenModel          : Boolean;
    j                  : Integer;
Begin
    SchPath       := __SCHLIB__;
    PcbPath       := __PCBLIB__;
    StepPath      := __STEP__;
    StepName      := __STEP_NAME__;
    MarkerPath    := __MARKER__;
    SymbolName    := __SYMBOL__;
    FootprintName := __FOOTPRINT__;
    Ok            := True;
    SaveOk        := False;
    Stage         := 'initialize';
    FailureCode   := 'altium-exception';
    SchDoc        := Nil;
    PcbDoc        := Nil;
    ReadSchDoc    := Nil;
    ReadPcbDoc    := Nil;
    Report        := TStringList.Create;
    Try
        Try
            If Not FileExists(StepPath) Then
            Begin
                Ok := False;
                FailureCode := 'step-not-found';
            End;

            If Ok Then
            Begin
                Stage := 'start-editor-servers';
                If SchServer = Nil Then Client.StartServer('SCH');
                If PCBServer = Nil Then Client.StartServer('PCB');
                If SchServer = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'sch-server-nil';
                End;
                If PCBServer = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'pcb-server-nil';
                End;
            End;

            If Ok Then
            Begin
                Stage := 'create-sch-library';
__SCH_CREATE__
                If SchLib = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'sch-library-nil';
                End;
            End;

            If Ok Then
            Begin
                Stage := 'author-sch-library';
                SchComponent := SchLib.GetState_SchComponentByLibRef('Component_1');
                If SchComponent <> Nil Then SchLib.RemoveSchComponent(SchComponent);
                SchComponent := SchServer.SchObjectFactory(eSchComponent, eCreate_Default);
                If SchComponent = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'sch-component-factory-nil';
                End;
                If Ok Then
                Begin
                    SchComponent.CurrentPartID := 1;
                    SchComponent.SetState_PartCountNoPart0(1);
                    SchComponent.DisplayMode := 0;
                    SchComponent.LibReference := SymbolName;
                    SchComponent.ComponentDescription := __SYMBOL_DESCRIPTION__;
                    SchLib.AddSchComponent(SchComponent);
                    SchLib.SetState_Current_SchComponent(SchComponent);

                    SchRect := SchServer.SchObjectFactory(eRectangle, eCreate_Default);
                    If SchRect = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'sch-rectangle-factory-nil';
                    End
                    Else
                    Begin
                        SchRect.Location := Point(MMsToCoord(-1.0), MMsToCoord(-0.5));
                        SchRect.Corner := Point(MMsToCoord(1.0), MMsToCoord(0.5));
                        SchRect.OwnerPartId := 1;
                        SchRect.OwnerPartDisplayMode := 0;
                        SchRect.IsSolid := False;
                        SchComponent.AddSchObject(SchRect);
                    End;
                End;

                If Ok Then
                Begin
                    SchPin := SchServer.SchObjectFactory(ePin, eCreate_Default);
                    If SchPin = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'sch-pin-c-factory-nil';
                    End
                    Else
                    Begin
                        SchPin.Location := Point(MMsToCoord(-2.54), 0);
                        SchPin.Orientation := eRotate0;
                        SchPin.PinLength := MMsToCoord(1.54);
                        SchPin.Designator := __PIN1_NUMBER__;
                        SchPin.Name := __PIN1_NAME__;
                        SchPin.Description := 'Cathode';
                        SchPin.Electrical := eElectricPassive;
                        SchPin.ShowName := True;
                        SchPin.ShowDesignator := True;
                        SchPin.OwnerPartId := 1;
                        SchPin.OwnerPartDisplayMode := 0;
                        SchComponent.AddSchObject(SchPin);
                    End;
                End;

                If Ok Then
                Begin
                    SchPin := SchServer.SchObjectFactory(ePin, eCreate_Default);
                    If SchPin = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'sch-pin-a-factory-nil';
                    End
                    Else
                    Begin
                        SchPin.Location := Point(MMsToCoord(2.54), 0);
                        SchPin.Orientation := eRotate180;
                        SchPin.PinLength := MMsToCoord(1.54);
                        SchPin.Designator := __PIN2_NUMBER__;
                        SchPin.Name := __PIN2_NAME__;
                        SchPin.Description := 'Anode';
                        SchPin.Electrical := eElectricPassive;
                        SchPin.ShowName := True;
                        SchPin.ShowDesignator := True;
                        SchPin.OwnerPartId := 1;
                        SchPin.OwnerPartDisplayMode := 0;
                        SchComponent.AddSchObject(SchPin);
                    End;
                End;

                If Ok Then
                Begin
                    SchParameter := SchServer.SchObjectFactory(eParameter, eCreate_Default);
                    If SchParameter = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'sch-mf-parameter-factory-nil';
                    End
                    Else
                    Begin
                        SchParameter.Name := 'MF';
                        SchParameter.Text := __MANUFACTURER__;
                        SchParameter.ShowName := False;
                        SchParameter.OwnerPartId := 1;
                        SchParameter.OwnerPartDisplayMode := 0;
                        SchComponent.AddSchObject(SchParameter);
                    End;
                End;

                If Ok Then
                Begin
                    SchParameter := SchServer.SchObjectFactory(eParameter, eCreate_Default);
                    If SchParameter = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'sch-mp-parameter-factory-nil';
                    End
                    Else
                    Begin
                        SchParameter.Name := 'MP';
                        SchParameter.Text := __MPN__;
                        SchParameter.ShowName := False;
                        SchParameter.OwnerPartId := 1;
                        SchParameter.OwnerPartDisplayMode := 0;
                        SchComponent.AddSchObject(SchParameter);
                    End;
                End;

                If Ok Then
                Begin
__SCH_SAVE__
                    If (Not SaveOk) Or (Not FileExists(SchPath)) Then
                    Begin
                        Ok := False;
                        FailureCode := 'sch-save-refused';
                    End;
                End;
            End;

            If Ok Then
            Begin
                Stage := 'create-pcb-library';
__PCB_CREATE__
                If PcbLib = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'pcb-library-nil';
                End;
            End;

            If Ok Then
            Begin
                Stage := 'author-pcb-library';
                For j := PcbLib.ComponentCount - 1 DownTo 0 Do
                Begin
                    Footprint := PcbLib.GetComponent(j);
                    If SameString(Footprint.Name, 'PCBComponent_1', False) Then
                        If Not PcbLib.DeRegisterComponent(Footprint) Then
                        Begin
                            Ok := False;
                            FailureCode := 'pcb-default-remove-refused';
                        End;
                End;
            End;

            If Ok Then
            Begin
                { Altium's CreateFootprintInLibrary example uses CreatePCBLibComp followed by
                  RegisterComponent. AD26 returned Nil from IPCB_Library.AddComponent in both
                  factory and workspace bootstraps during the isolated proof. }
                Footprint := PCBServer.CreatePCBLibComp;
                If Footprint = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'pcb-component-factory-nil';
                End
                Else
                Begin
                    Footprint.Name := FootprintName;
                    Footprint.Description := __FOOTPRINT_DESCRIPTION__;
                    If Not PcbLib.RegisterComponent(Footprint) Then
                    Begin
                        Ok := False;
                        FailureCode := 'pcb-component-register-refused';
                    End
                    Else
                    Begin
                        PcbLib.SetState_CurrentComponent(Footprint);
                        Board := PcbLib.Board;
                        If Board = Nil Then
                        Begin
                            Ok := False;
                            FailureCode := 'pcb-board-nil';
                        End;
                    End;
                End;
            End;

            If Ok Then
            Begin
                PCBServer.PreProcess;
                Footprint.BeginModify;

                PcbPad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);
                If PcbPad = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'pcb-pad-c-factory-nil';
                End
                Else
                Begin
                    PcbPad.BeginModify;
                    PcbPad.Name := __PIN1_NUMBER__;
                    PcbPad.X := MMsToCoord(-2.2);
                    PcbPad.Y := 0;
                    PcbPad.Layer := eTopLayer;
                    PcbPad.Mode := ePadMode_Simple;
                    PcbPad.TopShape := eRectangular;
                    PcbPad.TopXSize := MMsToCoord(1.8);
                    PcbPad.TopYSize := MMsToCoord(2.2);
                    PcbPad.HoleSize := 0;
                    Board.AddPCBObject(PcbPad);
                    PcbPad.EndModify;
                    PCBServer.SendMessageToRobots(
                        Board.I_ObjectAddress, c_Broadcast,
                        PCBM_BoardRegisteration, PcbPad.I_ObjectAddress);
                End;

                If Ok Then
                Begin
                    PcbPad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);
                    If PcbPad = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'pcb-pad-a-factory-nil';
                    End
                    Else
                    Begin
                        PcbPad.BeginModify;
                        PcbPad.Name := __PIN2_NUMBER__;
                        PcbPad.X := MMsToCoord(2.2);
                        PcbPad.Y := 0;
                        PcbPad.Layer := eTopLayer;
                        PcbPad.Mode := ePadMode_Simple;
                        PcbPad.TopShape := eRectangular;
                        PcbPad.TopXSize := MMsToCoord(1.8);
                        PcbPad.TopYSize := MMsToCoord(2.2);
                        PcbPad.HoleSize := 0;
                        Board.AddPCBObject(PcbPad);
                        PcbPad.EndModify;
                        PCBServer.SendMessageToRobots(
                            Board.I_ObjectAddress, c_Broadcast,
                            PCBM_BoardRegisteration, PcbPad.I_ObjectAddress);
                    End;
                End;

                If Ok Then
                Begin
                    Body := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
                    If Body = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'pcb-body-factory-nil';
                    End
                    Else
                    Begin
                        Model := Body.ModelFactory_FromFilename(StepPath, True);
                        If Model = Nil Then
                        Begin
                            Ok := False;
                            FailureCode := 'step-model-factory-nil';
                        End
                        Else
                        Begin
                            Body.BeginModify;
                            Body.Model := Model;
                            Body.SetState_FromModel;
                            Body.Layer := eTopLayer;
                            Board.AddPCBObject(Body);
                            Body.EndModify;
                            PCBServer.SendMessageToRobots(
                                Board.I_ObjectAddress, c_Broadcast,
                                PCBM_BoardRegisteration, Body.I_ObjectAddress);
                        End;
                    End;
                End;

                Footprint.EndModify;
                PCBServer.PostProcess;
                PcbLib.RefreshView;
                Board.ViewManager_FullUpdate;

                If Ok Then
                Begin
__PCB_SAVE__
                    If (Not SaveOk) Or (Not FileExists(PcbPath)) Then
                    Begin
                        Ok := False;
                        FailureCode := 'pcb-save-refused';
                    End;
                End;
            End;

            If Ok Then
            Begin
                Stage := 'readback-sch-library';
                ReadSchDoc := Client.OpenDocument('SCHLIB', SchPath);
                If ReadSchDoc = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'sch-reopen-nil';
                End
                Else
                Begin
                    Client.ShowDocument(ReadSchDoc);
                    SchLib := SchServer.GetCurrentSchDocument;
                    If SchLib = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'sch-readback-library-nil';
                    End;
                End;
            End;

            If Ok Then
            Begin
                SchComponent := SchLib.GetState_SchComponentByLibRef(SymbolName);
                If SchComponent = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'sch-readback-component-nil';
                End;
            End;

            If Ok Then
            Begin
                PinCount := 0;
                SeenPinC := False;
                SeenPinA := False;
                SeenMF := False;
                SeenMP := False;
                SchIterator := SchComponent.SchIterator_Create;
                SchIterator.AddFilter_ObjectSet(MkSet(ePin, eParameter));
                SchObject := SchIterator.FirstSchObject;
                While SchObject <> Nil Do
                Begin
                    If SchObject.ObjectId = ePin Then
                    Begin
                        SchPin := SchObject;
                        PinCount := PinCount + 1;
                        If (SchPin.Designator = __PIN1_NUMBER__) And
                           (SchPin.Name = __PIN1_NAME__) Then
                            SeenPinC := True;
                        If (SchPin.Designator = __PIN2_NUMBER__) And
                           (SchPin.Name = __PIN2_NAME__) Then
                            SeenPinA := True;
                    End
                    Else If SchObject.ObjectId = eParameter Then
                    Begin
                        SchParameter := SchObject;
                        If (SchParameter.Name = 'MF') And
                           (SchParameter.Text = __MANUFACTURER__) Then SeenMF := True;
                        If (SchParameter.Name = 'MP') And
                           (SchParameter.Text = __MPN__) Then SeenMP := True;
                    End;
                    SchObject := SchIterator.NextSchObject;
                End;
                SchComponent.SchIterator_Destroy(SchIterator);
                If (PinCount <> 2) Or (Not SeenPinC) Or (Not SeenPinA) Or
                   (Not SeenMF) Or (Not SeenMP) Then
                Begin
                    Ok := False;
                    FailureCode := 'sch-semantic-mismatch';
                End;
            End;
            If ReadSchDoc <> Nil Then
            Begin
                Client.CloseDocument(ReadSchDoc);
                ReadSchDoc := Nil;
            End;

            If Ok Then
            Begin
                Stage := 'readback-pcb-library';
                ReadPcbDoc := Client.OpenDocument('PCBLIB', PcbPath);
                If ReadPcbDoc = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'pcb-reopen-nil';
                End
                Else
                Begin
                    Client.ShowDocument(ReadPcbDoc);
                    PcbLib := PCBServer.GetCurrentPCBLibrary;
                    If PcbLib = Nil Then
                    Begin
                        Ok := False;
                        FailureCode := 'pcb-readback-library-nil';
                    End;
                End;
            End;

            If Ok Then
            Begin
                Footprint := Nil;
                For j := 0 To PcbLib.ComponentCount - 1 Do
                    If PcbLib.GetComponent(j).Name = FootprintName Then
                        Footprint := PcbLib.GetComponent(j);
                If Footprint = Nil Then
                Begin
                    Ok := False;
                    FailureCode := 'pcb-readback-component-nil';
                End;
            End;

            If Ok Then
            Begin
                PcbLib.SetState_CurrentComponent(Footprint);
                Board := PcbLib.Board;
                PadCount := 0;
                BodyCount := 0;
                SeenPadC := False;
                SeenPadA := False;
                SeenModel := False;
                PcbIterator := Footprint.GroupIterator_Create;
                PcbIterator.AddFilter_ObjectSet(
                    MkSet(ePadObject, eComponentBodyObject));
                PcbPrimitive := PcbIterator.FirstPCBObject;
                While PcbPrimitive <> Nil Do
                Begin
                    If PcbPrimitive.ObjectId = ePadObject Then
                    Begin
                        PersistedPad := PcbPrimitive;
                        PadCount := PadCount + 1;
                        If PersistedPad.Name = __PIN1_NUMBER__ Then SeenPadC := True;
                        If PersistedPad.Name = __PIN2_NUMBER__ Then SeenPadA := True;
                    End
                    Else If PcbPrimitive.ObjectId = eComponentBodyObject Then
                    Begin
                        PersistedBody := PcbPrimitive;
                        BodyCount := BodyCount + 1;
                        If PersistedBody.Model <> Nil Then
                            If SameString(PersistedBody.Model.Name, StepName, False) Or
                               SameString(
                                   ExtractFileName(PersistedBody.Model.FileName),
                                   StepName, False) Then SeenModel := True;
                    End;
                    PcbPrimitive := PcbIterator.NextPCBObject;
                End;
                Footprint.GroupIterator_Destroy(PcbIterator);
                If (PadCount <> 2) Or (BodyCount <> 1) Or
                   (Not SeenPadC) Or (Not SeenPadA) Or (Not SeenModel) Then
                Begin
                    Ok := False;
                    FailureCode := 'pcb-semantic-mismatch';
                End;
            End;
            If ReadPcbDoc <> Nil Then
            Begin
                Client.CloseDocument(ReadPcbDoc);
                ReadPcbDoc := Nil;
            End;
        Except
            Ok := False;
            FailureCode := 'altium-exception';
        End;
    Finally
        If ReadSchDoc <> Nil Then Client.CloseDocument(ReadSchDoc);
        If ReadPcbDoc <> Nil Then Client.CloseDocument(ReadPcbDoc);
        If SchDoc <> Nil Then Client.CloseDocument(SchDoc);
        If PcbDoc <> Nil Then Client.CloseDocument(PcbDoc);
        If Ok Then
            Report.Text := __SUCCESS_JSON__
        Else
            Report.Text :=
                '{"bootstrap":"__BOOTSTRAP__","code":"' + FailureCode +
                '","schema_version":1,"stage":"' + Stage + '","status":"error"}';
        Report.SaveToFile(MarkerPath);
        Report.Free;
    End;
    TerminateWithExitCode(0);
End;
"""


def read_embedded_model_payloads(pcblib: Path) -> tuple[bytes, ...]:
    """Return Altium's numbered embedded model streams as their original bytes.

    AD26 stores each STEP payload in ``Library/Models/<n>`` using zlib. A foreign or older file may
    carry an uncompressed stream, so decompression failure leaves the original bytes available for
    an honest mismatch rather than raising.
    """

    numbered: list[tuple[int, bytes]] = []
    with olefile.OleFileIO(str(Path(pcblib))) as container:
        for parts in container.listdir(streams=True):
            name = "/".join(parts)
            match = _MODEL_PAYLOAD.match(name)
            if match is None:
                continue
            raw = container.openstream(parts).read()
            try:
                payload = zlib.decompress(raw)
            except zlib.error:
                payload = raw
            numbered.append((int(match.group(1)), payload))
    return tuple(payload for _index, payload in sorted(numbered))


def author_native_component(
    canonical_json: Path,
    step: Path,
    output_dir: Path,
    *,
    bootstrap: Bootstrap = "factory",
    driver: AltiumDriver | None = None,
    timeout: int = 300,
) -> NativeAuthoringResult:
    """Author and independently verify one isolated native Altium component."""

    canonical_json = Path(canonical_json)
    step = Path(step)
    if not canonical_json.is_file():
        raise ValueError(f"canonical JSON does not exist: {canonical_json}")
    if not step.is_file():
        raise ValueError(f"STEP input does not exist: {step}")
    if b"ISO-10303-21" not in step.read_bytes()[:256]:
        raise ValueError(f"{step.name} is not an ISO-10303-21 STEP file")
    if bootstrap not in ("factory", "workspace"):
        raise ValueError("bootstrap must be 'factory' or 'workspace'")

    bundle = _load_supported_bundle(canonical_json)
    names = _names_for_supported_bundle(bundle)
    root = Path(output_dir)
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise ValueError("output_dir must be a new or existing empty directory")
    else:
        root.mkdir(parents=True)

    inputs = root / "Inputs"
    artifacts = root / "Artifacts"
    run = root / "Run"
    evidence_dir = root / "Evidence"
    for directory in (inputs, artifacts, run, evidence_dir):
        directory.mkdir()

    canonical_copy = inputs / "Canonical.json"
    step_copy = inputs / step.name
    shutil.copy2(canonical_json, canonical_copy)
    shutil.copy2(step, step_copy)

    schlib = artifacts / names.schlib_filename
    pcblib = artifacts / names.pcblib_filename
    marker = evidence_dir / "Native Authoring Result.json"
    evidence = evidence_dir / "Independent Verification.json"
    pas = run / "SRNativeAuthoring.pas"
    project = run / "SRNativeAuthoring.PrjScr"

    drv = driver or AltiumDriver()
    pas.write_text(
        render_native_authoring_script(
            bundle,
            schlib_win=drv.host.to_windows_path(str(schlib)),
            pcblib_win=drv.host.to_windows_path(str(pcblib)),
            step_win=drv.host.to_windows_path(str(step_copy)),
            marker_win=drv.host.to_windows_path(str(marker)),
            bootstrap=bootstrap,
        ),
        encoding="utf-8",
        newline="\r\n",
    )
    project.write_text(
        f"[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n[Document1]\r\nDocumentPath={pas.name}\r\n",
        encoding="utf-8",
    )

    outcome = drv.run_script(
        project=project,
        proc=f"{pas.name}>SRNativeAuthoring",
        marker=marker,
        timeout=timeout,
    )
    if not outcome.ok:
        document = _base_evidence(bundle, bootstrap, canonical_copy, step_copy)
        document.update(
            {
                "detail": outcome.detail,
                "driver_status": outcome.status,
                "status": outcome.status,
            }
        )
        _write_json(evidence, document)
        return NativeAuthoringResult(
            outcome.status,
            outcome.detail,
            root,
            schlib,
            pcblib,
            marker,
            evidence,
        )

    try:
        semantic = json.loads(outcome.marker_text)
    except json.JSONDecodeError:
        semantic = None
    expected = expected_semantic_report(bundle, step_copy.name, bootstrap)
    if semantic != expected:
        detail = (
            "Altium wrote a marker, but its post-reopen semantic report did not match the "
            "qualified canonical result."
        )
        document = _base_evidence(bundle, bootstrap, canonical_copy, step_copy)
        document.update(
            {
                "altium_semantic_readback": semantic,
                "detail": detail,
                "expected_semantics": expected,
                "status": "native-failed",
            }
        )
        _write_json(evidence, document)
        return NativeAuthoringResult(
            "native-failed",
            detail,
            root,
            schlib,
            pcblib,
            marker,
            evidence,
            semantic,
        )

    failures: list[str] = []
    symbol_names: list[str] = []
    footprint_names: list[str] = []
    model_records: tuple[dict[str, str], ...] = ()
    payloads: tuple[bytes, ...] = ()
    try:
        symbol_names = read_symbol_names(schlib)
    except Exception as exc:
        failures.append(f"SchLib OLE readback failed: {exc}")
    try:
        footprint_names = read_footprint_names(pcblib)
    except Exception as exc:
        failures.append(f"PcbLib OLE readback failed: {exc}")
    try:
        model_records = read_model_index(pcblib)
        payloads = read_embedded_model_payloads(pcblib)
    except Exception as exc:
        failures.append(f"PcbLib model OLE readback failed: {exc}")

    source_step = step_copy.read_bytes()
    payload_match = source_step in payloads
    if symbol_names != [names.symbol]:
        failures.append(f"SchLib names are {symbol_names!r}, expected [{names.symbol!r}]")
    if footprint_names != [names.footprint]:
        failures.append(f"PcbLib names are {footprint_names!r}, expected [{names.footprint!r}]")
    if not model_name_present(model_records, step_copy.name):
        failures.append(f"PcbLib model index does not name {step_copy.name}")
    if not payload_match:
        failures.append("embedded OLE model payload does not exactly match the STEP input bytes")

    independent = {
        "footprint_names": footprint_names,
        "model_index": list(model_records),
        "model_payload_count": len(payloads),
        "model_payload_sha256": [hashlib.sha256(payload).hexdigest() for payload in payloads],
        "step_payload_exact_match": payload_match,
        "step_sha256": hashlib.sha256(source_step).hexdigest(),
        "symbol_names": symbol_names,
    }
    document = _base_evidence(bundle, bootstrap, canonical_copy, step_copy)
    document.update(
        {
            "altium_semantic_readback": semantic,
            "artifacts": {
                "pcblib": _artifact_evidence(pcblib),
                "schlib": _artifact_evidence(schlib),
            },
            "detail": "Native libraries and embedded STEP passed both readback layers."
            if not failures
            else failures[0],
            "failures": failures,
            "independent_readback": independent,
            "status": "ok" if not failures else "verification-failed",
        }
    )
    _write_json(evidence, document)
    if failures:
        return NativeAuthoringResult(
            "verification-failed",
            failures[0],
            root,
            schlib,
            pcblib,
            marker,
            evidence,
            semantic,
        )
    return NativeAuthoringResult(
        "ok",
        "Native libraries and embedded STEP passed both readback layers.",
        root,
        schlib,
        pcblib,
        marker,
        evidence,
        semantic,
    )


def _base_evidence(
    bundle: CanonicalPassiveBundle,
    bootstrap: Bootstrap,
    canonical: Path,
    step: Path,
) -> dict[str, object]:
    names = _names_for_supported_bundle(bundle)
    return {
        "bootstrap": bootstrap,
        "canonical_digest": bundle.canonical_digest(),
        "native_names": {
            "footprint": names.footprint,
            "symbol": names.symbol,
        },
        "inputs": {
            "canonical": _artifact_evidence(canonical),
            "step": _artifact_evidence(step),
        },
        "schema_version": 1,
    }


def _artifact_evidence(path: Path) -> dict[str, object]:
    data = Path(path).read_bytes()
    return {
        "name": Path(path).name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    """Run the proof adapter directly on a machine with Altium Designer."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Author isolated native Altium libraries from qualified canonical JSON"
    )
    parser.add_argument("canonical_json", type=Path)
    parser.add_argument("step", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--bootstrap",
        choices=("factory", "workspace"),
        default="factory",
    )
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)

    result = author_native_component(
        args.canonical_json,
        args.step,
        args.output_dir,
        bootstrap=args.bootstrap,
        timeout=args.timeout,
    )
    print(
        json.dumps(
            {
                "detail": result.detail,
                "evidence": str(result.evidence),
                "output_dir": str(result.output_dir),
                "status": result.status,
            },
            sort_keys=True,
        )
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
