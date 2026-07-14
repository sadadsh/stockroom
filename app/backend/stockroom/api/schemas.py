"""Thin response DTOs over the engine dataclasses. These are a PRESENTATION shape,
never a second schema of record: the source of truth stays the PartRecord JSON and
the derived index (spec sections 5.1, 5.2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

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
    """One net class the Editor submits (M7e). `name` is required (a class with no name
    is a clean 422, never a silent drop); every other KiCad-10 dimension/color field is
    optional and passes through (extra=allow) so the reconcile can field-merge only the
    edited keys onto the on-disk class, preserving fields the UI never models."""

    model_config = ConfigDict(extra="allow")

    name: str


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
