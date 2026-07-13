"""The duplicates surface (M6e). Groups library parts that share an MPN (a real
accidental duplicate: the same part recorded twice) or a footprint name (often a
legitimate shared standard footprint, so this half is informational). Read-only
over the derived index; the keep/delete resolution reuses the existing atomic
DELETE /api/library/parts/{id}, so there is no new mutation primitive here.

No em dashes anywhere (standing owner rule)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.api.schemas import DuplicateGroup, DuplicatesDTO, PartSummary


def duplicates_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @r.get("/duplicates")
    def duplicates(request: Request) -> dict:
        ctx = request.app.state.ctx

        def groups(pairs: dict[str, list[str]]) -> list[DuplicateGroup]:
            out: list[DuplicateGroup] = []
            for key in sorted(pairs):
                rows = [row for row in (ctx.index.get(pid) for pid in pairs[key]) if row]
                # keep-candidate first: complete before incomplete, then fewest
                # missing fields, then name, so "keep the first, delete the rest"
                # is the obvious default in the compare view.
                rows.sort(key=lambda row: (not row.is_complete, len(row.missing), row.display_name.lower()))
                out.append(
                    DuplicateGroup(key=key, parts=[PartSummary.from_row(row) for row in rows])
                )
            return out

        return DuplicatesDTO(
            by_mpn=groups(ctx.index.duplicates_by_mpn()),
            by_footprint=groups(ctx.index.duplicates_by_footprint()),
        ).model_dump()

    return r
