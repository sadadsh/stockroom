"""Measured DigiKey embedded-route controls stay independently selectable."""

from __future__ import annotations

import pytest

from stockroom.capture.browser import PlaywrightCaptureBrowser, chromium_unavailable_reason
from stockroom.capture.vendors import DigiKeyUltraLibrarianAdapter

_MODELS_HTML = """
<!doctype html>
<html>
  <body>
    <section id="snapmagic-media-active">
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
  </body>
</html>
"""


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_snapmagic_and_ultralibrarian_routes_select_their_own_controls(tmp_path):
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
            report = adapter.drive(
                page,
                ["altium"],
                expected_manufacturer="Texas Instruments",
                expected_mpn="TPD6E05U06RVZR",
            )

            modal_id = (
                "snapeda-export-options"
                if adapter.evidence_provider_key == "digikey-snapmagic"
                else "ultralib-export-options"
            )
            checked = page.locator(f"#{modal_id} input:checked")
            assert report.selected == ["altium"]
            assert report.submitted is True
            assert checked.count() == 2
            assert {
                checked.nth(index).get_attribute("name")
                for index in range(checked.count())
            } == {
                "snapeda-format-selection"
                if modal_id == "snapeda-export-options"
                else "ultra-format-selection",
                "snapeda-format-selection-3d"
                if modal_id == "snapeda-export-options"
                else "ultra-format-selection-3d",
            }
