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
from datetime import UTC, datetime

from stockroom.enrich.datasheet import extract_datasheet_specs
from stockroom.enrich.errors import EnrichError
from stockroom.ingest.staging import StagingCandidate
from stockroom.mutation.library_ops import staged_missing_fields
from stockroom.text import fullest_name

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
    """The M2 completeness gate, evaluated on exactly the StagedPart the add would use.

    This used to hand-build a StagedPart from the candidate's fields, on the belief that
    `to_staged_part` would reject an asset-less candidate. It does not - staging.py:65 says a
    candidate may stage with no asset files at all. The hand-built copy dropped
    `datasheet_meta`, so a part whose datasheet is a known URL rather than a downloaded PDF was
    reported missing a datasheet here while `add_part` would have accepted it: the two halves of
    one gate disagreeing, which is the exact failure staged_missing_fields exists to prevent."""
    return staged_missing_fields(candidate.to_staged_part())


@dataclass
class ImportItem:
    """One query's outcome. `query` is what the user supplied and `mpn` what it resolved to;
    keeping both is what lets a report say "595-TPS62130RGTR -> TPS62130RGTR" instead of
    silently substituting one for the other."""

    query: str
    mpn: str = ""
    part_id: str = ""
    status: str = ""  # added | would-add | exists | duplicate | incomplete | error
    display_name: str = ""
    category: str = ""
    missing: list[str] = field(default_factory=list)
    error: str = ""
    resolved_by: str = ""  # which distributor recognised the stock number, if any
    # What CAD the part landed with. "kicad-stock" means a real, placeable symbol +
    # footprint + 3D model (KiCad's own, referenced by lib_id); "none" means the record
    # landed on identity alone and still needs a capture. The owner's question is "did I
    # get the FILES", and a report that cannot tell those apart cannot answer it.
    assets: str = ""


@dataclass
class ImportReport:
    items: list[ImportItem] = field(default_factory=list)

    def of(self, *statuses: str) -> list[ImportItem]:
        return [i for i in self.items if i.status in statuses]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.items:
            out[i.status] = out.get(i.status, 0) + 1
        return out


def _candidate_for(mpn: str, category: str) -> StagingCandidate:
    from stockroom.model.part import Provenance

    return StagingCandidate(
        vendor="bulk",
        symbol_lib_path=None,
        symbol_name="",
        footprint_variants=[],
        category=category,
        mpn=mpn,
        display_name=mpn,
        entry_name=mpn,
        # A Provenance MUST exist before enrichment runs. `enrich_candidate` records the pulled
        # datasheet URL only `if candidate.provenance is not None`, so a candidate without one
        # silently loses it - and the datasheet is a required passport field. MEASURED on the
        # owner's real library: 76 of 166 parts landed "Needs More / Missing datasheet" with
        # their symbol, footprint and 3D already resolved, blocked on this one dropped string.
        provenance=Provenance(source="bulk"),
    )


def _passive_record(candidate: StagingCandidate):
    """A passive PartRecord carrying KiCad STOCK symbol/footprint/3D references, or None when
    this part is not an addable passive.

    This is what turns an import into PLACEABLE parts instead of bare records. A resistor,
    capacitor or inductor MPN deterministically encodes its case, and KiCad already ships the
    generic symbol, footprint and 3D model for that case - so the files need no vendor, no
    login and no network. Roughly half the owner's Component Register is jellybean passives.

    Returns None rather than guessing whenever the MPN cannot be decoded and no package can be
    resolved (`PassiveNeedsInputError`): the part then takes the ordinary file-less add and is
    reported as still needing a capture. A wrong footprint is worse than no footprint.
    """
    from stockroom.ingest.passive_add import (
        PassiveAddError,
        PassiveNeedsInputError,
        build_passive_record,
    )

    if not candidate.mpn:
        return None
    purchase = candidate.purchase[0] if candidate.purchase else None
    datasheet_url = ""
    if candidate.provenance is not None and candidate.provenance.source_url:
        datasheet_url = candidate.provenance.source_url
    try:
        build = build_passive_record(
            candidate.mpn,
            category=candidate.category or None,
            manufacturer=candidate.manufacturer or None,
            datasheet_url=datasheet_url or None,
            purchase_part_number=(purchase.part_number if purchase else None),
            specs=dict(candidate.specs) or None,
            price_breaks=(list(purchase.price_breaks) if purchase else None),
            stock=(purchase.stock if purchase else None),
        )
    except (PassiveNeedsInputError, PassiveAddError):
        return None
    record = build.record
    # Carry the purchase link across verbatim: the passport's sourcing field needs a real URL,
    # and build_passive_record only reconstructs one when the input WAS a Mouser link.
    if purchase is not None and purchase.url and not any(p.url for p in record.purchase):
        record.purchase = [purchase]
    return record


def _lookup(index):
    """The index to query RIGHT NOW. `index` may be the object itself (tests, short calls) or a
    zero-argument callable that returns the current one - which is what a long run must pass,
    since the handle it starts with will not survive a rebuild."""
    return index() if callable(index) else index


def _promote_datasheet_manufacturer(candidate: StagingCandidate) -> None:
    """Prefer a provably fuller manufacturer spelling from the exact datasheet.

    Distributor catalogues commonly return short names such as ``TI``.  The
    downloaded PDF is already part of the import and can carry the full maker
    name, but the ordinary enrichment walk stops asking for manufacturer after
    the short catalogue value fills that field.  Only inspect short, single-word
    values, require the exact requested MPN to occur in the PDF, and use the
    existing conservative abbreviation proof.  An unrelated name never wins.
    """

    current = candidate.manufacturer.strip()
    identifier = candidate.mpn.strip()
    path = candidate.datasheet_path
    compact = "".join(character for character in current if character.isalnum())
    if not current or not identifier or path is None or " " in current or len(compact) > 5:
        return
    try:
        result = extract_datasheet_specs(
            path,
            known_mpn=identifier,
            page_limit=None,
        )
    except (EnrichError, OSError):
        return
    if result.mpn is None or str(result.mpn.value) != identifier:
        return
    observed = "" if result.manufacturer is None else str(result.manufacturer.value).strip()
    promoted = fullest_name((current, observed))
    if not promoted or promoted == current:
        return
    alternates = candidate.alternates.setdefault("manufacturer", [])
    if not any(str(entry.get("value", "")).strip() == current for entry in alternates):
        alternates.append({"value": current, "source": "", "confidence": ""})
    candidate.manufacturer = promoted


def bulk_import(
    queries,
    pipeline,
    ops,
    *,
    index,
    category: str = "Other",
    dry_run: bool = False,
    on_progress=None,
) -> ImportReport:
    """Import a list of part numbers into the library, one atomic add each.

    Each query is RESOLVED to a manufacturer part number first (a distributor stock number is
    meaningless to every source but the distributor that issued it), then enriched, then added
    through the ordinary `add_part` seam so the complete-to-add gate and the git transaction are
    exactly the ones a single add uses. Nothing here bypasses a gate.

    Nothing aborts the batch: an enrichment that raises, an add that fails and a part that never
    reaches completeness are all ROWS in the report, so a 169-part run always finishes and always
    says what happened to every line.
    """
    report = ImportReport()
    seen_queries: set[str] = set()
    added_mpns: set[str] = set()
    todo = [q.strip() for q in queries if q and q.strip()]
    total = len(todo)

    for done, query in enumerate(todo):
        if on_progress is not None:
            on_progress(done, total, query)
        if query in seen_queries:
            report.items.append(ImportItem(query=query, status="duplicate"))
            continue
        seen_queries.add(query)
        item = ImportItem(query=query)
        report.items.append(item)
        try:
            resolved = pipeline.resolve_to_mpn(query)
            item.mpn = resolved.mpn
            item.resolved_by = resolved.vendor
            # Check the library BEFORE enriching: a re-run over a list that is already imported
            # must cost no network at all, or "run it again to catch the stragglers" is a
            # full-price operation every time.
            #
            # RE-READ per part, never captured for the run. MEASURED on the owner's real app:
            # 37 of 166 parts failed with "Cannot operate on a closed database", because a
            # 28-minute run outlives the sqlite handle - the background sync loop rebuilds the
            # index while the import is going and closes the connection the run started with.
            existing = _lookup(index).find_by_mpn(item.mpn)
            if existing:
                item.status = "exists"
                item.part_id = existing[0].id
                continue
            if item.mpn in added_mpns:
                # Two different queries can name one device (a Mouser SKU and a DigiKey number).
                # The index cannot know: it is rebuilt after the run, not during it.
                item.status = "duplicate"
                continue
            candidate = _candidate_for(item.mpn, category)
            pipeline.enrich_candidate(candidate)
            _promote_datasheet_manufacturer(candidate)
            item.category = candidate.category
            item.display_name = candidate.display_name
            # A passive resolves KiCad's own stock symbol/footprint/3D from its MPN alone, so it
            # lands PLACEABLE with no download. Decided before the gate, because the two paths
            # have different (both legitimate) completeness rules: a passive's stock lib_ids
            # satisfy symbol/footprint, which a StagedPart has no way to express.
            passive = _passive_record(candidate)
            if passive is not None:
                item.assets = "kicad-stock"
                item.category = passive.category or item.category
                missing = passive.missing_fields()
                if missing:
                    item.status = "incomplete"
                    item.missing = missing
                    continue
                if dry_run:
                    item.status = "would-add"
                    added_mpns.add(item.mpn)
                    continue
                record = ops.add_passive_part(passive)
                item.status = "added"
                item.part_id = getattr(record, "id", "")
                item.display_name = getattr(record, "display_name", "") or item.display_name
                added_mpns.add(item.mpn)
                continue

            # Non-passive CAD is admitted only by the coherent provider-evidence workflow.
            # LCSC may still supply exact product identity and specification metadata, but it
            # has no CAD conversion or production symbol/footprint/model authority.
            item.assets = "none"
            missing = _missing_for(candidate)
            if missing:
                item.status = "incomplete"
                item.missing = missing
                continue
            if dry_run:
                item.status = "would-add"
                added_mpns.add(item.mpn)
                continue
            record = ops.add_part(
                candidate.to_staged_part(), now=datetime.now(UTC).isoformat()
            )
            item.status = "added"
            item.part_id = getattr(record, "id", "")
            item.display_name = getattr(record, "display_name", "") or item.display_name
            added_mpns.add(item.mpn)
        except Exception as exc:  # noqa: BLE001 - one bad part never aborts the batch
            item.status = "error"
            item.error = str(exc)
    return report
