"""Thin response DTOs over the engine dataclasses. These are a PRESENTATION shape,
never a second schema of record: the source of truth stays the PartRecord JSON and
the derived index (spec sections 5.1, 5.2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from stockroom.store.index import Facets as _Facets
from stockroom.store.index import IndexRow


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


class SetSpecsBody(BaseModel):
    """Persist canonical spec data onto a record (M6i). `specs` maps a spec name to
    {value, source?, confidence?}; a typed body means a malformed container (a list or
    scalar instead of an object) is a clean 422, never an opaque 500 from set_specs
    calling .items() on a non-mapping. Inner values stay Any (the value is free-form)."""

    specs: dict[str, Any] = {}
    overwrite: bool = False
