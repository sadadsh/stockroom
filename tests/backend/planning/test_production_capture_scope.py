from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from stockroom.evidence import EvidenceStore
from stockroom.planning.production_composition import (
    ProductionApplicationContext,
    StockroomAcquisitionProviderAdapter,
)
from stockroom.planning.provider_policy import (
    KICAD_CAD_OPERATION,
    AdapterOutcomeStatus,
    ExactPartIdentity,
)
from stockroom.workflow import StageContext


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
        assert request.should_stop() is True

    default = adapter._capture_options(identity)
    assert default.mode == "automatic"
    assert default.vendor is None
    assert default.report_item_id is None
    assert default.should_stop() is False


def test_one_slow_capture_serves_both_cad_operations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = StockroomAcquisitionProviderAdapter(
        cast(ProductionApplicationContext, SimpleNamespace()),
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
        "stockroom.planning.production_composition.record_installed_kicad_role_evidence",
        lambda **_kwargs: None,
    )

    with adapter.capture_scope(context, identity):
        request = adapter._capture_options(identity)
        adapter._acquire(identity, request)
        adapter._acquire(identity, request)

    assert runs["count"] == 1


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
