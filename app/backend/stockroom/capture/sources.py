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

from datetime import datetime, timezone

from stockroom.capture.complete import SourceOutcome
from stockroom.capture.identity import PageIdentity, exact_observation_error, select_exact_candidate
from stockroom.capture.requirements import Requirement
from stockroom.enrich.bulk import lcsc_id_for
from stockroom.model.asset import AssetOrigin


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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

    def __init__(
        self,
        make_pipeline,
        *,
        resolve_online=None,
        resolve_identity=None,
        run_write=None,
        now_iso=None,
    ):
        # A FACTORY, not a pipeline. Each part converts inside its own sandbox which is torn
        # down immediately, so a 10,000-part run holds one tree at a time instead of 10,000.
        # It also means no handle is captured across a run long enough to be closed underneath
        # it, which is what failed 37 of 166 parts on the owner's real library.
        self._make_pipeline = make_pipeline
        self._resolve_online = resolve_online
        self._resolve_identity = resolve_identity
        self._run_write = run_write or (lambda fn: fn())
        self._now_iso = now_iso or _utc_now_iso

    def provides(self) -> frozenset[Requirement]:
        return frozenset(
            {
                Requirement.KICAD_SYMBOL,
                Requirement.KICAD_FOOTPRINT,
                Requirement.KICAD_MODEL,
            }
        )

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

    def _verified_identity(self, record, lcsc_id: str):
        """Resolve the catalogue identity behind an id and require an exact record match.

        The converter identifies its candidate as the LCSC C-number, not the manufacturer's
        MPN. Therefore a stored C-number is not identity evidence by itself: it may be stale or
        belong to a nearby search result. The product page supplies the independent MPN and
        manufacturer which the shared fail-closed selector can compare before any rename or
        attachment occurs.
        """
        error_prefix = f"LCSC exact identity verification failed for {lcsc_id.upper()}"
        if self._resolve_identity is None:
            return None, f"{error_prefix}: product identity lookup is unavailable"
        try:
            identity = self._resolve_identity(lcsc_id)
        except Exception as exc:  # noqa: BLE001 - a catalogue outage is a row, not a crash
            return None, f"{error_prefix}: {exc}"
        if identity is None:
            return None, f"{error_prefix}: the product page exposed no identity"

        observed_lcsc = (getattr(identity, "lcsc", "") or "").strip().upper()
        if observed_lcsc != lcsc_id.strip().upper():
            return (
                None,
                f"{error_prefix}: the product page identifies LCSC id "
                f"{observed_lcsc or '<missing>'}, not {lcsc_id.upper()}",
            )

        # Product-page identity is checked before conversion. EasyEDA names converted candidates
        # after the C-number, so the independently observed identity is then projected onto each
        # candidate and the shared candidate selector still rejects ambiguity by file order.
        identity_mpn = (getattr(identity, "mpn", "") or "").strip()
        identity_manufacturer = (getattr(identity, "manufacturer", "") or "").strip()
        if not identity_mpn:
            return None, f"{error_prefix}: the product page exposed no manufacturer MPN"
        identity_error = exact_observation_error(
            record,
            PageIdentity(mpn=identity_mpn, manufacturer=identity_manufacturer),
        )
        if identity_error:
            return None, f"{error_prefix}: {identity_error}"
        return (identity_mpn, identity_manufacturer), ""

    def supply(self, record) -> SourceOutcome:
        lcsc_id, error = self._lcsc_id(record)
        if error:
            return SourceOutcome(error=error)
        if not lcsc_id:
            return SourceOutcome(skipped=f"no LCSC part number for {record.mpn or record.id}")

        identity, error = self._verified_identity(record, lcsc_id)
        if error:
            return SourceOutcome(error=error)
        identity_mpn, identity_manufacturer = identity

        pipeline = self._make_pipeline()
        try:
            try:
                candidates = pipeline.inspect(lcsc_ids=[lcsc_id])
            except Exception as exc:  # noqa: BLE001 - a convert failure degrades this part only
                return SourceOutcome(error=str(exc))
            if not candidates:
                return SourceOutcome(error=f"the converter produced nothing for {lcsc_id}")

            for candidate in candidates:
                candidate.mpn = identity_mpn
                candidate.manufacturer = identity_manufacturer
            selection = select_exact_candidate(
                record,
                candidates,
                vendor_key=self.key,
                detail_url="",
            )
            if selection.error:
                return SourceOutcome(
                    error=(
                        f"LCSC exact identity verification failed for {lcsc_id.upper()}: "
                        f"{selection.error}"
                    )
                )
            candidate = selection.candidate
            if candidate is None:
                return SourceOutcome(
                    error=(
                        f"LCSC exact identity verification failed for {lcsc_id.upper()}: "
                        "the converter exposed no attachable candidate"
                    )
                )
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
                origin = AssetOrigin(
                    vendor="lcsc",
                    url=f"https://jlcpcb.com/partdetail/{lcsc_id.upper()}",
                    captured_at=self._now_iso(),
                    extra={
                        "conversion": "easyeda2kicad",
                        "lcsc_id": lcsc_id.upper(),
                    },
                )
                self._run_write(lambda: pipeline.attach_assets(record.id, candidate, origin=origin))
            except Exception as exc:  # noqa: BLE001 - the attach is atomic; a failure is a row
                return SourceOutcome(error=str(exc))
            return SourceOutcome(satisfied=tuple(offered))
        finally:
            # Unconditional. The failure paths are exactly the ones that leak, and at 10,000
            # parts a leaked sandbox per part fills a disk.
            pipeline.cleanup()
