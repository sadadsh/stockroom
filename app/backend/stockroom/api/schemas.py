"""Thin response DTOs over the engine dataclasses. These are a PRESENTATION shape,
never a second schema of record: the source of truth stays the PartRecord JSON and
the derived index (spec sections 5.1, 5.2)."""

from __future__ import annotations

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


class EditFieldBody(BaseModel):
    field: str
    value: object


class MoveBody(BaseModel):
    category: str
