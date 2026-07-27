"""The real asset sources the completion engine drives.

Each source answers one question: *given a part record, can I get it the files it is missing,
with no human in the loop?* The engine (`capture/complete.py`) knows nothing about any of
them; it iterates whatever is registered. So a new way to obtain files -- an Altium symbol
writer, a vendor API, a second catalogue -- is a new class here, not an edit anywhere else.

A source declines by returning `SourceOutcome(skipped=...)`. Declining is a first-class,
correct answer: 19 of the owner's 66 file-less parts are genuinely not in the LCSC catalogue,
and a source that guessed at them would attach a WRONG footprint, which is strictly worse
than attaching none.
"""

from __future__ import annotations

from stockroom.capture.complete import SourceOutcome
from stockroom.capture.requirements import Requirement
from stockroom.enrich.bulk import lcsc_id_for


class LcscSource:
    """Real symbol + footprint + 3D model, converted from the LCSC/EasyEDA catalogue.

    No login, no API key and no vendor download page: an LCSC part number is enough, and
    `ingest/lcsc.fetch_lcsc` already wraps the conversion (including the mandatory
    `fp_upgrade` off easyeda2kicad's KiCad 5 `(module ...)` dialect). This class is the seam
    that points that capability at a part which ALREADY LANDED, rather than at one being
    added -- which is the whole gap: `bulk_import` adds parts and never revisits one it has
    already added, so 66 parts that landed before the CAD lanes existed have been reporting
    "Already There" and being skipped ever since.

    The id is looked for on the record first (enrichment stored an LCSC product URL for 46 of
    the 66) and only then online, because a lookup that rediscovers what is already on disk is
    pure cost repeated per part.
    """

    key = "lcsc"

    def __init__(self, make_pipeline, *, resolve_online=None, run_write=None):
        # A FACTORY, not a pipeline. Each part converts inside its own sandbox which is torn
        # down immediately, so a 10,000-part run holds one tree at a time instead of 10,000.
        # It also means no handle is captured across a run long enough to be closed underneath
        # it, which is what failed 37 of 166 parts on the owner's real library.
        self._make_pipeline = make_pipeline
        self._resolve_online = resolve_online
        self._run_write = run_write or (lambda fn: fn())

    def provides(self) -> frozenset[Requirement]:
        return frozenset({
            Requirement.KICAD_SYMBOL,
            Requirement.KICAD_FOOTPRINT,
            Requirement.KICAD_MODEL,
        })

    def _lcsc_id(self, record) -> tuple[str, str]:
        """(id, error). `lcsc_id_for` reads `.purchase` and `.specs`, which a PartRecord and a
        StagingCandidate both carry, so the one regex serves both callers instead of drifting
        into two copies."""
        found = lcsc_id_for(record)
        if found:
            return found, ""
        if self._resolve_online is None:
            return "", ""
        try:
            return (self._resolve_online(record.mpn) or ""), ""
        except Exception as exc:  # noqa: BLE001 - a catalogue outage is a row, not a crash
            return "", str(exc)

    def supply(self, record) -> SourceOutcome:
        lcsc_id, error = self._lcsc_id(record)
        if error:
            return SourceOutcome(error=error)
        if not lcsc_id:
            return SourceOutcome(
                skipped=f"no LCSC part number for {record.mpn or record.id}"
            )

        pipeline = self._make_pipeline()
        try:
            try:
                candidates = pipeline.inspect(lcsc_ids=[lcsc_id])
            except Exception as exc:  # noqa: BLE001 - a convert failure degrades this part only
                return SourceOutcome(error=str(exc))
            if not candidates:
                return SourceOutcome(error=f"the converter produced nothing for {lcsc_id}")

            candidate = candidates[0]
            # The converter names its output after the LCSC id; the library is keyed on the
            # manufacturer part and every part already filed is named that way. Forcing it
            # here also guarantees the non-empty entry name `attach_assets` requires to place
            # a symbol at all.
            candidate.entry_name = record.mpn or candidate.entry_name or candidate.mpn

            offered: list[Requirement] = []
            if candidate.symbol_lib_path is not None:
                offered.append(Requirement.KICAD_SYMBOL)
            if candidate.footprint_variants:
                offered.append(Requirement.KICAD_FOOTPRINT)
            if candidate.model_path is not None:
                offered.append(Requirement.KICAD_MODEL)
            if not offered:
                return SourceOutcome(error=f"{lcsc_id} converted with no symbol, footprint or 3D")

            try:
                self._run_write(lambda: pipeline.attach_assets(record.id, candidate))
            except Exception as exc:  # noqa: BLE001 - the attach is atomic; a failure is a row
                return SourceOutcome(error=str(exc))
            return SourceOutcome(satisfied=tuple(offered))
        finally:
            # Unconditional. The failure paths are exactly the ones that leak, and at 10,000
            # parts a leaked sandbox per part fills a disk.
            pipeline.cleanup()
