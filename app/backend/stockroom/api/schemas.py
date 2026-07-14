"""Thin response DTOs over the engine dataclasses. These are a PRESENTATION shape,
never a second schema of record: the source of truth stays the PartRecord JSON and
the derived index (spec sections 5.1, 5.2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from stockroom.store.index import Facets as _Facets
from stockroom.store.index import IndexRow
from stockroom.store.project_index import ProjectIndexRow


class PartSummary(BaseModel):
    id: str
    display_name: str
    category: str
    mpn: str
    manufacturer: str
    is_complete: bool
    missing: list[str] = []

    @classmethod
    def from_row(cls, row: IndexRow) -> "PartSummary":
        return cls(
            id=row.id,
            display_name=row.display_name,
            category=row.category,
            mpn=row.mpn,
            manufacturer=row.manufacturer,
            is_complete=row.is_complete,
            missing=list(row.missing),
        )


class FacetsDTO(BaseModel):
    by_category: dict[str, int]
    by_manufacturer: dict[str, int]
    complete: int
    incomplete: int

    @classmethod
    def from_facets(cls, f: _Facets) -> "FacetsDTO":
        return cls(
            by_category=f.by_category,
            by_manufacturer=f.by_manufacturer,
            complete=f.complete,
            incomplete=f.incomplete,
        )


class DuplicateGroup(BaseModel):
    """Parts that share one duplicate key (an MPN or a footprint name), the members
    ordered most-complete-first so the keep-candidate is the first entry."""

    key: str
    parts: list[PartSummary]


class DuplicatesDTO(BaseModel):
    by_mpn: list[DuplicateGroup]
    by_footprint: list[DuplicateGroup]


class EditFieldBody(BaseModel):
    field: str
    value: object


class MoveBody(BaseModel):
    category: str


class ProjectSummary(BaseModel):
    """The list shape for a registered KiCad project (M7), served from the derived
    project index. board_count/sheet_count and has_git are the digest fields the
    Projects list renders; the full record (paths, git_root, audit_digest) loads on
    detail. A presentation shape, never a second schema of record."""

    id: str
    name: str
    root: str
    board_count: int
    sheet_count: int
    has_git: bool
    registered_at: str

    @classmethod
    def from_row(cls, row: ProjectIndexRow) -> "ProjectSummary":
        return cls(
            id=row.id,
            name=row.name,
            root=row.root,
            board_count=row.board_count,
            sheet_count=row.sheet_count,
            has_git=row.has_git,
            registered_at=row.registered_at,
        )


class RegisterProjectBody(BaseModel):
    """Register an external KiCad project by its directory path (absolute). A bad or
    non-project dir raises ValueError in the store, mapped to 400 by the error layer."""

    root: str


class SetSpecsBody(BaseModel):
    """Persist canonical spec data onto a record (M6i). `specs` maps a spec name to
    {value, source?, confidence?}; a typed body means a malformed container (a list or
    scalar instead of an object) is a clean 422, never an opaque 500 from set_specs
    calling .items() on a non-mapping. Inner values stay Any (the value is free-form)."""

    specs: dict[str, Any] = {}
    overwrite: bool = False


class NetClassDTO(BaseModel):
    """One net class the Editor submits (M7e). `name` is required and non-blank (a blank
    name is a clean 422, never a silent drop by the reconcile which keys on a truthy name);
    every other KiCad-10 dimension/color field is optional and passes through (extra=allow)
    so the reconcile can field-merge only the edited keys onto the on-disk class, preserving
    fields the UI never models."""

    model_config = ConfigDict(extra="allow")

    name: str

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a net class name must not be blank")
        return v


class SetNetClassesBody(BaseModel):
    """Edit a project's net classes (M7e). `classes` is the full edited set; `deleted`
    names classes to remove; `floor` selects the fab-house dimension floor the returned
    validation checks against (default no floor)."""

    classes: list[NetClassDTO]
    deleted: list[str] = []
    floor: str = "none"


class SetDesignRulesBody(BaseModel):
    """Edit a project's board design-rule constraints (M7e). `rules` field-merges into
    board.design_settings.rules (an omitted rule is preserved); the size lists, when
    provided, replace their board.design_settings arrays wholesale."""

    rules: dict[str, Any]
    track_widths: list[Any] | None = None
    via_dimensions: list[Any] | None = None
    diff_pair_dimensions: list[Any] | None = None


class SetSettingsBody(BaseModel):
    """Edit a project's board setup + overall thickness (its .kicad_pcb) and/or its .kicad_pro
    settings: ERC/DRC rule severities, the ERC pin-conflict matrix, project text variables
    (M7f-A + A2). Every field is optional so the editor can save any concern alone; whichever
    are given land in one atomic commit on the project's own git. The engine validates each and
    surfaces a bad value (unsupported key, non-positive thickness, unknown severity rule id,
    malformed pin map, blank text-var name) as a 400.

    `erc_severities`/`drc_severities` are {rule_id: level} maps merged per-rule (a sibling rule
    is preserved); `erc_pin_map` is the full 12x12 matrix; `text_variables` is the COMPLETE
    desired map (a key absent from it is deleted). text_variables uses None for 'not submitted'
    so an empty {} still means 'clear all vars'."""

    board_setup: dict[str, Any] | None = None
    thickness: float | None = None
    erc_severities: dict[str, Any] | None = None
    drc_severities: dict[str, Any] | None = None
    erc_pin_map: list[list[int]] | None = None
    text_variables: dict[str, Any] | None = None


class ConformTarget(BaseModel):
    """The target size/thickness (mm) for one object-conform category (M7f-B). Either may be None
    to leave that dimension untouched; the engine rejects a category that sets neither, and a
    non-positive or non-finite value, as a 400."""

    size: float | None = None
    thickness: float | None = None


class ConformBody(BaseModel):
    """Preview or apply an object conform (M7f-B): normalize the font size (and, where a font
    carries one, its thickness) of existing text objects to a house standard. `pcb_targets` keys
    are silk/fab/copper; `sch_targets` keys are text/labels; only the categories present are
    conformed. An empty selection is a 400."""

    pcb_targets: dict[str, ConformTarget] | None = None
    sch_targets: dict[str, ConformTarget] | None = None

    def pcb(self) -> dict:
        return {k: v.model_dump() for k, v in (self.pcb_targets or {}).items()}

    def sch(self) -> dict:
        return {k: v.model_dump() for k, v in (self.sch_targets or {}).items()}


class StackupBody(BaseModel):
    """Preview or apply a stackup change (M7f-C): EITHER apply a fab preset via `preset_key` (a
    whole-block generate that also sets board thickness), OR edit individual fields
    (`copper_finish`, `dielectric_constraints`, and per-layer `layer_edits` =
    {layer_name: {thickness?, material?, epsilon_r?, loss_tangent?}}). Exactly one mode per request;
    the engine rejects both / neither, an unknown or layer-count-mismatched preset, and a bad field
    value (blank finish, non-positive/non-finite number, a JSON bool where a number is expected) as
    a 400. `layer_edits` values are left loosely typed so a bool reaches the validator (which rejects
    it) instead of being silently coerced to a number."""

    preset_key: str | None = None
    copper_finish: str | None = None
    dielectric_constraints: bool | None = None
    layer_edits: dict[str, dict[str, Any]] | None = None


class ManualFillBody(BaseModel):
    """Manually link one placed component to a chosen shared-library part (M7f-D): the residual
    filler for a component Prepare / Complete-All could not match automatically. `ref` is the
    component's reference designator, `part_id` the library part id. Fills ALL of the part's identity
    fields (overwrite allowed, since this is an explicit user choice) and repoints the symbol lib_id, as
    one atomic commit. An unknown part or a missing ref is a 400."""

    ref: str
    part_id: str
