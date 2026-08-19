from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import cast

import pytest

from stockroom.capture.complete import CompletionEvidence
from stockroom.capture.requirements import Requirement
from stockroom.evidence import EvidenceStore
from stockroom.model.part import PartRecord
from stockroom.planning.production_composition import (
    ProductionApplicationContext,
    StockroomAcquisitionProviderAdapter,
    _canonical_capture_diagnostic_report,
    _CaptureRequest,
)
from stockroom.planning.provider_policy import (
    KICAD_CAD_OPERATION,
    AdapterOutcomeStatus,
    ExactPartIdentity,
)
from stockroom.workflow import StageContext


def test_copy_on_write_capture_report_cannot_claim_canonical_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = {
        "items": [
            {
                "part_id": "staged-part",
                "mpn": "PART-1",
                "display_name": "PART-1",
                "category": "ICs",
                "status": "completed",
                "needed": ["kicad_symbol"],
                "satisfied": ["kicad_symbol"],
                "remaining": [],
                "retained": 1,
                "sources": ["guided"],
                "notes": [],
                "error": "",
                "provider_outcomes": [{"status": "activated"}],
                "collection_complete": True,
                "completion_evidence": {
                    "state": "verified",
                    "manifest_digest": "sha256:" + "a" * 64,
                    "reason": "staging only",
                },
            }
        ],
        "counts": {"completed": 1},
        "retained": 1,
        "collection_complete": True,
        "stopped": False,
        "stop_reason": "",
    }
    record = SimpleNamespace(id="canonical-part", mpn="PART-1", category="ICs")
    monkeypatch.setattr(
        "stockroom.planning.production_composition.record_completion_evidence",
        lambda *_args, **_kwargs: CompletionEvidence.unverified("canonical projection missing"),
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition.completion_needs",
        lambda *_args, **_kwargs: [Requirement.KICAD_SYMBOL],
    )

    diagnostic = _canonical_capture_diagnostic_report(
        report,
        record=cast(PartRecord, record),
        evidence_store=EvidenceStore(tmp_path / "Evidence"),
        library=object(),
    )

    row = diagnostic["items"][0]
    assert row["part_id"] == "canonical-part"
    assert row["status"] == "unchanged"
    assert row["remaining"] == ["kicad_symbol"]
    assert row["completion_evidence"]["state"] == "unverified"
    assert row["provider_outcomes"] == [{"status": "activated"}]
    assert diagnostic["counts"] == {"unchanged": 1}


def test_durable_capture_options_cross_the_provider_worker_thread(tmp_path: Path) -> None:
    adapter = StockroomAcquisitionProviderAdapter(
        cast(ProductionApplicationContext, SimpleNamespace()),
        EvidenceStore(tmp_path / "Evidence"),
        tmp_path / "Staging",
    )
    identity = ExactPartIdentity("Texas Instruments", "TPS62130")
    context = cast(
        StageContext,
        SimpleNamespace(
            should_stop=lambda: True,
            item=SimpleNamespace(
                id="item-capture-1",
                payload={
                    "part_id": "tps62130",
                    "workflow_kind": "guided_capture",
                    "capture": {
                        "mode": "collect-all",
                        "vendor": "ultralibrarian",
                        "background": False,
                        "requested_requirements": [
                            "kicad_symbol",
                            "kicad_footprint",
                            "kicad_model",
                        ],
                    },
                },
            )
        ),
    )

    with adapter.capture_scope(context, identity):
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(adapter._capture_options, identity).result()
        assert request.mode == "collect-all"
        assert request.vendor == "ultralibrarian"
        assert request.background is False
        assert request.report_item_id == "item-capture-1"
        assert request.requested_requirements == (
            "kicad_symbol",
            "kicad_footprint",
            "kicad_model",
        )
        assert request.should_stop() is True

    default = adapter._capture_options(identity)
    assert default.mode == "automatic"
    assert default.vendor is None
    assert default.report_item_id is None
    assert default.should_stop() is False


def test_provider_navigation_starts_before_copy_on_write_staging_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live_record = object()
    live = cast(
        ProductionApplicationContext,
        SimpleNamespace(
            ops=SimpleNamespace(load_record=lambda _part_id: live_record),
            profile=SimpleNamespace(library=object()),
            config=object(),
            provider_browser_surface=object(),
        ),
    )
    adapter = StockroomAcquisitionProviderAdapter(
        live,
        EvidenceStore(tmp_path / "Evidence"),
        tmp_path / "Staging",
    )
    identity = ExactPartIdentity("Texas Instruments", "TPS62130")
    staging_started = Event()
    allow_staging = Event()
    isolated = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: object()),
        profile=object(),
        jobs=SimpleNamespace(run_write=lambda operation: operation()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
    )

    def seed(*_args, **_kwargs):
        staging_started.set()
        assert allow_staging.wait(5)
        return isolated

    def capture(context, **_kwargs):
        assert staging_started.wait(5)
        assert not allow_staging.is_set()
        assert context.ops.load_record("tps62130") is live_record
        allow_staging.set()
        assert context.profile is isolated.profile
        return {"counts": {}}

    monkeypatch.setattr(
        "stockroom.planning.production_composition._seed_copy_on_write_context",
        seed,
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition.run_guided_capture",
        capture,
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition.write_durable_capture_report",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition._canonical_capture_diagnostic_report",
        lambda report, **_kwargs: report,
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition.record_installed_kicad_role_evidence",
        lambda **_kwargs: None,
    )

    request = _CaptureRequest(
        vendor="ultralibrarian",
        should_stop=lambda: False,
    )
    adapter._acquire(identity, request)

    assert allow_staging.is_set()


def test_one_slow_capture_serves_both_cad_operations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = StockroomAcquisitionProviderAdapter(
        cast(
            ProductionApplicationContext,
            SimpleNamespace(
                ops=SimpleNamespace(load_record=lambda _part_id: object()),
                profile=SimpleNamespace(library=object()),
            ),
        ),
        EvidenceStore(tmp_path / "Evidence"),
        tmp_path / "Staging",
    )
    identity = ExactPartIdentity("Abracon LLC", "ABM13W-32.0000MHZ-5-DH7G-T5")
    context = cast(
        StageContext,
        SimpleNamespace(
            should_stop=lambda: False,
            item=SimpleNamespace(
                id="item-capture-slow",
                payload={
                    "part_id": "abm13w",
                    "workflow_kind": "guided_capture",
                    "capture": {
                        "mode": "finish-first",
                        "vendor": None,
                        "background": False,
                    },
                },
            ),
        ),
    )
    isolated = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: object()),
        profile=object(),
    )
    runs = {"count": 0}
    clock = iter((0.0, 45.0, 46.0))

    monkeypatch.setattr(
        "stockroom.planning.production_composition.time.monotonic",
        lambda: next(clock),
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition._seed_copy_on_write_context",
        lambda *_args, **_kwargs: isolated,
    )

    def run_capture(*_args, **_kwargs):
        runs["count"] += 1
        return {"counts": {"completed": 1}}

    monkeypatch.setattr(
        "stockroom.planning.production_composition.run_guided_capture",
        run_capture,
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition.write_durable_capture_report",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition._canonical_capture_diagnostic_report",
        lambda report, **_kwargs: report,
    )
    monkeypatch.setattr(
        "stockroom.planning.production_composition.record_installed_kicad_role_evidence",
        lambda **_kwargs: None,
    )

    with adapter.capture_scope(context, identity):
        request = adapter._capture_options(identity)
        adapter._acquire(identity, request)
        adapter._acquire(identity, request)

    assert runs["count"] == 1


def test_collect_all_honors_open_provider_even_with_a_complete_retained_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = StockroomAcquisitionProviderAdapter(
        cast(ProductionApplicationContext, SimpleNamespace()),
        EvidenceStore(tmp_path / "Evidence"),
        tmp_path / "Staging",
    )
    identity = ExactPartIdentity("Texas Instruments", "TPD6E05U06RVZR")
    retained_bundle = object()
    acquisitions: list[object] = []
    events: list[str] = []
    context = cast(
        StageContext,
        SimpleNamespace(
            should_stop=lambda: False,
            item=SimpleNamespace(
                id="item-explicit-provider",
                payload={
                    "part_id": "tpd6e05u06rvzr",
                    "workflow_kind": "guided_capture",
                    "capture": {
                        "mode": "collect-all",
                        "vendor": "ultralibrarian",
                        "background": False,
                    },
                },
            ),
        ),
    )

    def selection(_self, _identity):
        events.append("selection")
        return retained_bundle

    def acquire(_self, _identity, request):
        events.append("acquire")
        acquisitions.append(request)

    monkeypatch.setattr(StockroomAcquisitionProviderAdapter, "_selection", selection)
    monkeypatch.setattr(StockroomAcquisitionProviderAdapter, "_acquire", acquire)
    monkeypatch.setattr(
        StockroomAcquisitionProviderAdapter,
        "_provider_manifest",
        lambda *_args, **_kwargs: "sha256:" + "a" * 64,
    )

    with adapter.capture_scope(context, identity):
        outcome = adapter.execute(identity, KICAD_CAD_OPERATION)

    assert outcome.status is AdapterOutcomeStatus.SUCCESS
    assert events == ["acquire", "selection"]
    assert len(acquisitions) == 1
    assert acquisitions[0].vendor == "ultralibrarian"


def test_finish_first_reuses_a_complete_retained_bundle_without_network_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = StockroomAcquisitionProviderAdapter(
        cast(ProductionApplicationContext, SimpleNamespace()),
        EvidenceStore(tmp_path / "Evidence"),
        tmp_path / "Staging",
    )
    identity = ExactPartIdentity("Texas Instruments", "TPD6E05U06RVZR")
    retained_bundle = object()
    context = cast(
        StageContext,
        SimpleNamespace(
            should_stop=lambda: False,
            item=SimpleNamespace(
                id="item-retained-bundle",
                payload={
                    "part_id": "tpd6e05u06rvzr",
                    "workflow_kind": "guided_capture",
                    "capture": {
                        "mode": "finish-first",
                        "vendor": None,
                        "background": False,
                    },
                },
            ),
        ),
    )

    monkeypatch.setattr(
        StockroomAcquisitionProviderAdapter,
        "_selection",
        lambda _self, _identity: retained_bundle,
    )
    monkeypatch.setattr(
        StockroomAcquisitionProviderAdapter,
        "_acquire",
        lambda *_args, **_kwargs: pytest.fail("retained evidence reopened provider capture"),
    )
    monkeypatch.setattr(
        StockroomAcquisitionProviderAdapter,
        "_provider_manifest",
        lambda *_args, **_kwargs: "sha256:" + "a" * 64,
    )

    with adapter.capture_scope(context, identity):
        outcome = adapter.execute(identity, KICAD_CAD_OPERATION)

    assert outcome.status is AdapterOutcomeStatus.SUCCESS
