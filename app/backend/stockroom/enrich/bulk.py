"""Bulk MPN-list / BOM import (spec section 8.1).

Given a pasted MPN list or a BOM CSV, enrich each part and report per-part which
ones reached complete and what the rest are still missing. This NEVER commits and
NEVER aborts the batch on one bad part: the caller commits the complete ones and
reads the report for the rest. Completeness is evaluated through the SAME M2 gate
(staged_missing_fields) so bulk and single-add can never disagree; a bare MPN with
no assets is correctly reported incomplete, not force-added (source-agnostic
completeness)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.ingest.staging import StagingCandidate
from stockroom.mutation.library_ops import staged_missing_fields

# CSV header names that mark the MPN column, lowercased, checked in order.
_MPN_HEADERS = ("mpn", "manufacturer part number", "part number", "part#", "partnumber")


def parse_mpn_list(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        seen.setdefault(s, None)
    return list(seen)


def parse_bom_csv(text: str) -> list[str]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    col = None
    for name in _MPN_HEADERS:
        if name in header:
            col = header.index(name)
            break
    if col is None:
        return []
    out: list[str] = []
    for row in rows[1:]:
        if col < len(row):
            val = row[col].strip()
            if val:
                out.append(val)
    return out


@dataclass
class BulkItem:
    mpn: str
    candidate: StagingCandidate | None
    complete: bool
    missing: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class BulkReport:
    items: list[BulkItem] = field(default_factory=list)

    def complete_items(self) -> list[BulkItem]:
        return [i for i in self.items if i.complete]

    def incomplete_items(self) -> list[BulkItem]:
        return [i for i in self.items if not i.complete]


def _bare_candidate(mpn: str, category: str) -> StagingCandidate:
    """A candidate carrying only the MPN and category; assets are absent, so a
    part that cannot be sourced end-to-end is honestly reported incomplete."""
    return StagingCandidate(
        vendor="bulk",
        symbol_lib_path=None,
        symbol_name="",
        footprint_variants=[],
        category=category,
        mpn=mpn,
        display_name=mpn,
        entry_name=mpn,
    )


def bulk_enrich(mpns, pipeline, category: str = "Other", candidate_factory=None) -> BulkReport:
    factory = candidate_factory or _bare_candidate
    report = BulkReport()
    for mpn in mpns:
        candidate = factory(mpn, category)
        error = ""
        try:
            pipeline.enrich_candidate(candidate)
        except Exception as exc:  # noqa: BLE001 - one bad part never aborts the batch
            error = str(exc)
        missing = _missing_for(candidate)
        report.items.append(
            BulkItem(
                mpn=mpn,
                candidate=candidate,
                complete=not missing and not error,
                missing=missing,
                error=error,
            )
        )
    return report


def _missing_for(candidate: StagingCandidate) -> list[str]:
    """Evaluate the M2 completeness gate on the enriched candidate WITHOUT
    requiring it to project to a StagedPart (a bare-MPN candidate has no symbol,
    which to_staged_part would reject); build the presence view directly from the
    candidate so we can report incomplete parts rather than crash on them."""
    from stockroom.mutation.library_ops import StagedPart

    staged = StagedPart(
        display_name=candidate.display_name,
        category=candidate.category,
        mpn=candidate.mpn,
        manufacturer=candidate.manufacturer,
        description=candidate.description,
        symbol_source=candidate.symbol_lib_path,
        symbol_source_name=candidate.symbol_name,
        entry_name=candidate.entry_name,
        footprint_source=candidate.chosen_footprint,
        model_source=candidate.model_path,
        datasheet_source=candidate.datasheet_path,
        purchase=list(candidate.purchase),
    )
    return staged_missing_fields(staged)
