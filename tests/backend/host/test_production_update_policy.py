from __future__ import annotations

import inspect

from stockroom.host.release_runtime import (
    PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS,
    ProductionUpdateRuntime,
    UnavailableProductionUpdateRuntime,
)


def test_every_production_update_state_uses_the_one_minute_check_contract() -> None:
    default = inspect.signature(ProductionUpdateRuntime).parameters[
        "refresh_interval_seconds"
    ].default

    assert PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS == 60
    assert default == PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS
    assert (
        UnavailableProductionUpdateRuntime().status()["check_interval_seconds"]
        == PRODUCTION_UPDATE_CHECK_INTERVAL_SECONDS
    )
