from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from stockroom.evidence import EvidenceStore
from stockroom.planning.production_composition import (
    ProductionApplicationContext,
    StockroomAcquisitionProviderAdapter,
)
from stockroom.planning.provider_policy import ExactPartIdentity
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

    default = adapter._capture_options(identity)
    assert default.mode == "automatic"
    assert default.vendor is None
    assert default.report_item_id is None
