import pytest

from stockroom.host.vendor_drivers.drivers import build_driver_js


@pytest.mark.parametrize(
    "vendor",
    ["digikey", "ultralibrarian", "snapmagic", "samacsys", "unknown"],
)
def test_retired_host_driver_is_guidance_only(vendor: str) -> None:
    script = build_driver_js(vendor, ["kicad", "altium"])

    assert "__STOCKROOM_OVERLAY__" in script
    assert vendor in script
    assert "kicad, altium" in script
    assert ".click()" not in script
    assert "querySelector" not in script
    assert "location." not in script


def test_retired_host_driver_does_not_expose_the_task_url() -> None:
    task_url = "https://example.invalid/part?credential=secret"

    script = build_driver_js("digikey", ["kicad"], target_url=task_url)

    assert task_url not in script
    assert "credential" not in script
    assert "secret" not in script


def test_retired_host_driver_quotes_untrusted_labels_as_json() -> None:
    script = build_driver_js("vendor';throw new Error('bad')//", ["kicad"])

    assert "throw new Error" in script
    assert 'message:"No injected' in script
    assert "\\u0027" not in script
