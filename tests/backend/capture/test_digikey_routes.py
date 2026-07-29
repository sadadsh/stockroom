"""Measured DigiKey embedded-route controls stay independently selectable."""

from __future__ import annotations

import pytest

from stockroom.capture.browser import PlaywrightCaptureBrowser, chromium_unavailable_reason
from stockroom.capture.vendors import DigiKeyUltraLibrarianAdapter

_MODELS_HTML = """
<!doctype html>
<html>
  <body>
    <section id="snap-media-active">
      <button onclick="document.getElementById('snapeda-export-options').hidden=false">
        Select Download Format
      </button>
    </section>
    <div id="snapeda-export-options" hidden>
      <input id="snap-kicad" type="radio" name="snapeda-format-selection">
      <label for="snap-kicad" data-original="KiCAD v6+">KiCAD v6+</label>
      <input id="snap-altium" type="radio" name="snapeda-format-selection">
      <label for="snap-altium" data-original="Altium Designer">Altium Designer</label>
      <input id="snap-step" type="radio" name="snapeda-format-selection-3d">
      <label for="snap-step" data-original="STEP">STEP</label>
      <button id="btn-download-SnapMagic">Download</button>
    </div>
    <section id="ultra-media-active">
      <button onclick="document.getElementById('ultralib-export-options').hidden=false">
        Select Download Format
      </button>
    </section>
    <div id="ultralib-export-options" hidden>
      <input id="ul-kicad" type="radio" name="ultra-format-selection">
      <label for="ul-kicad" data-original="KiCAD v6+">KiCAD v6+</label>
      <input id="ul-altium" type="radio" name="ultra-format-selection">
      <label for="ul-altium" data-original="Altium Designer (script based)">
        Altium Designer (script based)
      </label>
      <input id="ul-step" type="radio" name="ultra-format-selection-3d">
      <label for="ul-step" data-original="STEP">STEP</label>
      <button id="btn-download-Ultra">Download</button>
    </div>
    <section id="traceparts-media-active">
      <button onclick="document.getElementById('traceparts-export-options').hidden=false">
        Select Download Format
      </button>
    </section>
    <div id="traceparts-export-options" hidden>
      <input id="trace-step" type="radio" name="traceparts-format-selection">
      <label for="trace-step" data-original="STEP AP214">STEP AP214</label>
      <button id="btn-clear-selection-traceParts">Clear</button>
      <button id="btn-download-traceParts">Download</button>
    </div>
    <section id="mfr-media-active" hidden></section>
    <section id="cadenas-media-active" hidden></section>
    <div id="mfr-export-options"></div>
  </body>
</html>
"""

_EXTERNAL_SNAP_HTML = """
<!doctype html>
<html>
  <body>
    <section id="snap-media-active">
      <a href="https://www.snapmagic.com/parts/example/view-part/">View on SnapMagic</a>
    </section>
  </body>
</html>
"""

_HYDRATING_TRACE_HTML = """
<!doctype html>
<html>
  <body>
    <section id="snap-media-active" hidden></section>
    <section id="ultra-media-active" hidden></section>
    <section id="traceparts-media-active" hidden>
      <button onclick="document.getElementById('traceparts-export-options').hidden=false">
        Select Download Format
      </button>
    </section>
    <div id="traceparts-export-options" hidden>
      <input id="trace-step" type="radio" name="traceparts-format-selection">
      <label for="trace-step" data-original="STEP AP214">STEP AP214</label>
      <button id="btn-clear-selection-traceParts">Clear</button>
      <button id="btn-download-traceParts">Download</button>
    </div>
    <script>
      setTimeout(() => {
        document.getElementById("traceparts-media-active").hidden = false;
      }, 75);
    </script>
  </body>
</html>
"""


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_embedded_routes_select_only_their_own_measured_controls(tmp_path):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/texas-instruments/"
        "TPD6E05U06RVZR/4307639"
    )
    routes = surface.capture_routes()
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/4307639",
            lambda route: route.fulfill(status=200, content_type="text/html", body=_MODELS_HTML),
        )
        for adapter in routes:
            page.goto("https://www.digikey.com/en/models/4307639")
            requested_format = (
                "model"
                if adapter.evidence_provider_key == "digikey-traceparts"
                else "altium"
            )
            report = adapter.drive(
                page,
                [requested_format],
                expected_manufacturer="Texas Instruments",
                expected_mpn="TPD6E05U06RVZR",
            )

            modal_id = {
                "digikey-snapmagic": "snapeda-export-options",
                "digikey-traceparts": "traceparts-export-options",
                "digikey-ultralibrarian": "ultralib-export-options",
            }[adapter.evidence_provider_key]
            checked = page.locator(f"#{modal_id} input:checked")
            assert report.selected == [requested_format]
            assert report.submitted is True
            expected_names = {
                "digikey-snapmagic": {
                    "snapeda-format-selection",
                    "snapeda-format-selection-3d",
                },
                "digikey-traceparts": {"traceparts-format-selection"},
                "digikey-ultralibrarian": {
                    "ultra-format-selection",
                    "ultra-format-selection-3d",
                },
            }[adapter.evidence_provider_key]
            assert checked.count() == len(expected_names)
            assert {
                checked.nth(index).get_attribute("name")
                for index in range(checked.count())
            } == expected_names


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_current_external_snapmagic_row_is_not_reported_as_a_download(tmp_path):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/te-connectivity-amp-connectors/"
        "5212034-1/2038204"
    )
    snap = surface.capture_routes()[0]
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/2038204",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_EXTERNAL_SNAP_HTML,
            ),
        )
        page.goto("https://www.digikey.com/en/models/2038204")
        report = snap.drive(
            page,
            ["kicad"],
            expected_manufacturer="TE Connectivity AMP Connectors",
            expected_mpn="5212034-1",
        )

    assert report.submitted is False
    assert report.route_unavailable is True
    assert report.selected == []
    assert "external provider link" in report.message


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_waits_for_provider_hydration_before_declaring_a_hidden_row_absent(tmp_path):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/te-connectivity-amp-connectors/"
        "5212034-1/2038204"
    )
    traceparts = surface.capture_routes()[1]
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/2038204",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_HYDRATING_TRACE_HTML,
            ),
        )
        page.goto("https://www.digikey.com/en/models/2038204")
        report = traceparts.drive(
            page,
            ["model"],
            expected_manufacturer="TE Connectivity AMP Connectors",
            expected_mpn="5212034-1",
        )

    assert report.selected == ["model"], report
    assert report.submitted is True
