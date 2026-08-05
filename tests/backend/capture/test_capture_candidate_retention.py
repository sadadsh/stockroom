"""Guided capture WRITES the retained-candidate store that provider coverage reads.

`downloaded` and `validated` are claims about bytes Stockroom is holding, so the directory those
claims are read from has to be the one a completed capture actually writes. These tests bind the
two ends together: the writer inside `_attach`, the reader inside the library router, and the one
root both of them name.
"""

from __future__ import annotations

from pathlib import Path

from stockroom.api.routers import library as library_router
from stockroom.capture import runner as capture_runner
from stockroom.capture.complete import Requirement, SourceOutcome
from stockroom.capture.guided import GuidedCaptureSource
from stockroom.capture.runner import capture_candidates_root, capture_state_root
from stockroom.ingest.candidates import RetainedCandidateStore
from stockroom.model.part import PartRecord
from stockroom.provider_coverage import provider_coverage
from tests.backend.ingest.test_candidates import (
    MANUFACTURER,
    MPN,
    _complete,
    _package_zip,
    _symbol,
)

_DETAIL_URL = "https://www.digikey.com/en/products/detail/onsemi/S1M"
_ROUTE = "digikey-ultralibrarian"
_PART_ID = "s1m-0000"


def _record() -> PartRecord:
    return PartRecord(
        id=_PART_ID,
        mpn=MPN,
        manufacturer=MANUFACTURER,
        display_name=MPN,
        category="Diodes",
        description="Surface mount rectifier",
    )


def _capture(tmp_path: Path, store, package: Path, monkeypatch) -> SourceOutcome:
    """Run one person-selected capture through the real receipt-binding and retention path."""

    source = GuidedCaptureSource(
        lambda: object(),
        vendor="digikey",
        download_root=tmp_path / "Task Downloads",
        candidate_store=store,
    )
    # Activation needs the whole ingest pipeline and a library. Retention is deliberately upstream
    # of it, so stubbing the attachment proves what `_attach` retains without rebuilding an attach.
    monkeypatch.setattr(
        source,
        "_attach_impl",
        lambda *args, **options: SourceOutcome(satisfied=(Requirement.KICAD_SYMBOL,)),
    )
    return source.attach_selected_files(
        _record(),
        (package,),
        detail_url=_DETAIL_URL,
        evidence_provider_key=_ROUTE,
    )


def _row(document, provider: str) -> dict:
    return next(row for row in document["rows"] if row["id"] == provider)


def test_a_completed_capture_retains_its_package_at_the_canonical_root(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture"))
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    store = RetainedCandidateStore(capture_candidates_root())

    outcome = _capture(tmp_path, store, package, monkeypatch)

    assert outcome.error == ""
    assert store.root == tmp_path / "Capture" / "Candidates"
    retained = store.candidates_for(_PART_ID)
    assert retained, "a completed capture retained nothing"
    assert {item.provider_id for item in retained} == {_ROUTE}
    # The untouched provider package is held beside the artifacts it produced.
    assert store.package_path(retained[0].source_package_digest) is not None


def test_coverage_reports_the_captured_provider_as_downloaded(monkeypatch, tmp_path):
    """A package Stockroom holds but could not prove out is `downloaded`, never `validated`."""

    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture"))
    package = _package_zip(tmp_path / "S1M.zip", {"KiCad/S1M.kicad_sym": _symbol()})
    store = RetainedCandidateStore(capture_candidates_root())

    _capture(tmp_path, store, package, monkeypatch)

    row = _row(
        provider_coverage(_record(), candidates=store.candidates_for(_PART_ID)),
        "ultralibrarian",
    )
    assert row["symbol"]["status"] == "downloaded"
    assert row["symbol"]["origin"] == "native_download"


def test_coverage_reports_an_inspected_capture_as_validated(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture"))
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    store = RetainedCandidateStore(capture_candidates_root())

    _capture(tmp_path, store, package, monkeypatch)

    row = _row(
        provider_coverage(_record(), candidates=store.candidates_for(_PART_ID)),
        "ultralibrarian",
    )
    assert row["symbol"]["status"] == "validated"
    assert row["footprint"]["status"] == "validated"
    assert row["symbol"]["origin"] == "validator"


def test_a_rejected_capture_stops_counting_as_coverage(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture"))
    package = _package_zip(tmp_path / "S1M.zip", {"KiCad/S1M.kicad_sym": _symbol()})
    store = RetainedCandidateStore(capture_candidates_root())

    _capture(tmp_path, store, package, monkeypatch)
    for candidate in store.candidates_for(_PART_ID):
        store.reject(candidate.candidate_id, "the person removed it")

    row = _row(
        provider_coverage(_record(), candidates=store.candidates_for(_PART_ID)),
        "ultralibrarian",
    )
    assert row["symbol"]["status"] == "unknown"


def test_capturing_the_same_package_twice_adds_no_duplicate(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture"))
    package = _package_zip(tmp_path / "S1M.zip", _complete())
    store = RetainedCandidateStore(capture_candidates_root())

    _capture(tmp_path, store, package, monkeypatch)
    first = [item.candidate_id for item in store.candidates_for(_PART_ID)]
    _capture(tmp_path, store, package, monkeypatch)
    second = store.candidates_for(_PART_ID)

    assert [item.candidate_id for item in second] == first
    assert all(len(item.provenances) == 1 for item in second)


def test_the_candidate_store_root_is_one_path_everywhere_it_is_constructed(monkeypatch, tmp_path):
    """The reader and the writer must be unable to drift onto separate directories."""

    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture"))
    assert capture_candidates_root() == capture_state_root() / "Candidates"
    assert library_router.capture_candidates_root is capture_runner.capture_candidates_root

    backend = Path(capture_runner.__file__).resolve().parents[1]
    naming = sorted(
        path.name
        for path in backend.rglob("*.py")
        if '"Candidates"' in path.read_text(encoding="utf-8")
    )
    assert naming == ["runner.py"], naming
