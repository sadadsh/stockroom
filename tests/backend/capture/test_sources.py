"""The real asset sources the completion engine drives.

The engine is source-agnostic and tested separately; these tests pin what each source
actually DOES with the repo's existing seams, and especially the two things that bite at
scale: a per-part sandbox that is always torn down, and a source that declines cleanly
rather than guessing.
"""

from types import SimpleNamespace

import pytest

from stockroom.capture.complete import complete_part
from stockroom.capture.requirements import Requirement
from stockroom.capture.sources import LcscSource
from stockroom.ingest.errors import IngestError
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import AssetRef, PartRecord, Purchase


def _rec(
    mpn="TPS62130RGTR",
    manufacturer="Texas Instruments",
    purchase=(),
    specs=None,
) -> PartRecord:
    return PartRecord(
        id="p1",
        display_name=mpn,
        category="ICs",
        mpn=mpn,
        manufacturer=manufacturer,
        purchase=list(purchase),
        specs=dict(specs or {}),
    )


class FakePipeline:
    """Stands in for IngestPipeline. Records what it was asked and whether it was cleaned up."""

    def __init__(self, candidates=None, raises=None):
        self.candidates = candidates if candidates is not None else []
        self.raises = raises
        self.inspected: list[str] = []
        self.attached: list[tuple[str, StagingCandidate]] = []
        self.origins = []
        self.cleaned = 0

    def inspect(self, inputs=(), lcsc_ids=(), workdir=None):
        self.inspected.extend(lcsc_ids)
        if self.raises is not None:
            raise self.raises
        return list(self.candidates)

    def attach_assets(self, part_id, candidate, *, origin=None):
        self.attached.append((part_id, candidate))
        self.origins.append(origin)
        return None

    def cleanup(self):
        self.cleaned += 1


def _cand(symbol=True, footprint=True, model=True) -> StagingCandidate:
    return StagingCandidate(
        vendor="lcsc",
        symbol_lib_path=("/tmp/x.kicad_sym" if symbol else None),
        symbol_name="C7666",
        footprint_variants=(["/tmp/x.kicad_mod"] if footprint else []),
        category="ICs",
        mpn="C7666",
        display_name="C7666",
        entry_name="",
        model_path=("/tmp/x.step" if model else None),
    )


def _identity(
    *,
    lcsc=None,
    mpn="TPS62130RGTR",
    manufacturer="Texas Instruments",
    calls=None,
):
    def resolve(lcsc_id):
        if calls is not None:
            calls.append(lcsc_id)
        return SimpleNamespace(
            lcsc=lcsc or lcsc_id,
            mpn=mpn,
            manufacturer=manufacturer,
        )

    return resolve


# --- resolving the LCSC part number ------------------------------------------------------


def test_reads_the_lcsc_id_off_the_record_without_any_network():
    # 46 of the owner's 66 file-less parts already carry an LCSC product URL from enrichment.
    # Paying for a lookup to rediscover what is already on disk is waste at 10k parts.
    pipe = FakePipeline(candidates=[_cand()])
    calls = []
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: calls.append(mpn) or "",
        resolve_identity=_identity(),
    )
    rec = _rec(purchase=[Purchase(vendor="lcsc", url="https://lcsc.com/product-detail/C7666.html")])
    src.supply(rec)
    assert pipe.inspected == ["C7666"]
    assert calls == []  # never went online


def test_falls_back_to_the_online_catalogue_when_the_record_has_no_id():
    pipe = FakePipeline(candidates=[_cand()])
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C41040738",
        resolve_identity=_identity(),
    )
    src.supply(_rec())
    assert pipe.inspected == ["C41040738"]


def test_declines_cleanly_when_no_lcsc_part_number_exists_anywhere():
    # 19 of the 66 are genuinely not in the LCSC catalogue. That is a SKIP with a reason, not
    # an error and not a guess: a wrong footprint is worse than no footprint.
    pipe = FakePipeline()
    src = LcscSource(lambda: pipe, resolve_online=lambda mpn: "")
    outcome = src.supply(_rec())
    assert outcome.satisfied == ()
    assert outcome.error == ""
    assert "no LCSC part number" in outcome.skipped
    assert pipe.inspected == []  # nothing was even started


def test_an_online_resolver_that_raises_is_a_decline_not_a_crash():
    def boom(_mpn):
        raise RuntimeError("catalogue timeout")

    src = LcscSource(lambda: FakePipeline(), resolve_online=boom)
    outcome = src.supply(_rec())
    assert "catalogue timeout" in outcome.error
    assert outcome.satisfied == ()


# --- fail-closed catalogue identity --------------------------------------------------------


def test_exact_lcsc_product_identity_allows_attachment():
    pipe = FakePipeline(candidates=[_cand()])
    identity_calls = []
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda _mpn: "C7666",
        resolve_identity=_identity(calls=identity_calls),
    )

    outcome = src.supply(_rec())

    assert outcome.error == ""
    assert identity_calls == ["C7666"]
    assert pipe.attached


def test_near_match_mpn_returns_an_explicit_identity_error_and_attaches_nothing():
    candidate = _cand()
    pipe = FakePipeline(candidates=[candidate])
    rec = _rec(purchase=[Purchase(vendor="lcsc", url="https://lcsc.com/product-detail/C7666.html")])
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda _mpn: pytest.fail("stored id must avoid search"),
        resolve_identity=_identity(mpn="TPS62130RGTRG"),
    )

    outcome = src.supply(rec)

    assert "LCSC exact identity verification failed" in outcome.error
    assert "exact candidate" in outcome.error
    assert pipe.inspected == []
    assert pipe.attached == []
    assert candidate.entry_name == ""


def test_wrong_stored_lcsc_id_fails_before_conversion_and_attaches_nothing():
    pipe = FakePipeline(candidates=[_cand()])
    rec = _rec(purchase=[Purchase(vendor="lcsc", url="https://lcsc.com/product-detail/C7666.html")])
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda _mpn: pytest.fail("stored id must avoid search"),
        resolve_identity=_identity(lcsc="C9999"),
    )

    outcome = src.supply(rec)

    assert "LCSC exact identity verification failed" in outcome.error
    assert "C9999, not C7666" in outcome.error
    assert pipe.inspected == []
    assert pipe.attached == []


def test_wrong_manufacturer_returns_an_explicit_identity_error_and_attaches_nothing():
    pipe = FakePipeline(candidates=[_cand()])
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda _mpn: "C7666",
        resolve_identity=_identity(manufacturer="Texas Instrumental"),
    )

    outcome = src.supply(_rec())

    assert "LCSC exact identity verification failed" in outcome.error
    assert "manufacturer" in outcome.error
    assert pipe.inspected == []
    assert pipe.attached == []


# --- converting and attaching -------------------------------------------------------------


def test_attaches_the_converted_files_under_the_real_manufacturer_part_number():
    # The converter names everything after the LCSC id ("C7666"). The library is keyed on the
    # manufacturer part, and every part already in the owner's library is filed that way, so
    # the entry name is forced here rather than left to the converter.
    pipe = FakePipeline(candidates=[_cand()])
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
        now_iso=lambda: "2026-07-28T12:00:00Z",
    )
    src.supply(_rec(mpn="TPS62130RGTR"))
    part_id, candidate = pipe.attached[0]
    assert part_id == "p1"
    assert candidate.entry_name == "TPS62130RGTR"
    assert pipe.origins[0].vendor == "lcsc"
    assert pipe.origins[0].url == "https://jlcpcb.com/partdetail/C7666"
    assert pipe.origins[0].captured_at == "2026-07-28T12:00:00Z"
    assert pipe.origins[0].extra["conversion"] == "easyeda2kicad"


def test_reports_the_asset_kinds_the_candidate_actually_carried():
    pipe = FakePipeline(candidates=[_cand(model=False)])
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
    )
    outcome = src.supply(_rec())
    assert Requirement.KICAD_SYMBOL in outcome.satisfied
    assert Requirement.KICAD_FOOTPRINT in outcome.satisfied
    assert Requirement.KICAD_MODEL not in outcome.satisfied


def test_a_conversion_that_produces_nothing_is_an_error_row():
    pipe = FakePipeline(candidates=[])
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
    )
    outcome = src.supply(_rec())
    assert "C7666" in outcome.error
    assert pipe.attached == []


def test_a_converter_failure_is_reported_never_raised():
    pipe = FakePipeline(raises=IngestError("easyeda2kicad failed: no such part"))
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
    )
    outcome = src.supply(_rec())
    assert "no such part" in outcome.error


# --- the property that decides whether 10,000 parts fit on the disk ------------------------


@pytest.mark.parametrize(
    "pipe",
    [
        FakePipeline(candidates=[_cand()]),  # success
        FakePipeline(candidates=[]),  # nothing converted
        FakePipeline(raises=IngestError("converter exploded")),  # hard failure
    ],
)
def test_the_per_part_sandbox_is_always_torn_down(pipe):
    """Each part converts into its own sandbox. At 10,000 parts a leaked tree per part fills
    a disk, and the failure paths are exactly the ones a happy-path test never covers."""
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
    )
    src.supply(_rec())
    assert pipe.cleaned == 1


def test_a_fresh_pipeline_is_built_per_part():
    # One pipeline reused across a long run accumulates owned tempdirs and outlives handles it
    # captured at construction -- the same class of bug that failed 37 of 166 parts once.
    made = []

    def make():
        p = FakePipeline(candidates=[_cand()])
        made.append(p)
        return p

    src = LcscSource(
        make,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
    )
    src.supply(_rec())
    src.supply(_rec())
    assert len(made) == 2


def test_the_attach_is_pushed_through_the_supplied_write_lane():
    # Git commits stay serialized against every other writer while the slow network work
    # never occupies the single write worker -- the same split bulk_import uses.
    pipe = FakePipeline(candidates=[_cand()])
    ran = []

    def write_lane(fn):
        ran.append("write")
        return fn()

    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
        run_write=write_lane,
    )
    src.supply(_rec())
    assert ran == ["write"]
    assert pipe.attached


# --- through the engine, end to end --------------------------------------------------------


def test_the_engine_never_calls_kicad_only_acquisition_fully_complete():
    """Wires the real source to the real engine. The engine re-reads the record to decide, so
    this also proves the source's claim is CHECKED rather than believed."""
    rec = _rec()
    pipe = FakePipeline(candidates=[_cand()])

    def attach(part_id, candidate, *, origin=None):
        for kind in ("symbol", "footprint", "model"):
            rec.assets_for("kicad").set(kind, AssetRef(lib="SR-ICs", name=rec.mpn))

    pipe.attach_assets = attach
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
    )
    item = complete_part("p1", load_record=lambda _pid: rec, sources=[src])
    assert item.status == "improved"
    assert item.sources == ["lcsc"]
    assert item.remaining == ["altium_symbol", "altium_footprint"]


def test_a_source_claiming_success_it_did_not_deliver_cannot_fake_a_completion():
    # The "success reported by the code that STARTED the work" failure, blocked structurally:
    # the engine believes the record on disk, never the source's own report.
    rec = _rec()
    pipe = FakePipeline(candidates=[_cand()])
    pipe.attach_assets = lambda part_id, candidate, **_kwargs: None  # attaches nothing at all
    src = LcscSource(
        lambda: pipe,
        resolve_online=lambda mpn: "C7666",
        resolve_identity=_identity(),
    )
    item = complete_part("p1", load_record=lambda _pid: rec, sources=[src])
    assert item.status == "unchanged"
    assert item.sources == []
