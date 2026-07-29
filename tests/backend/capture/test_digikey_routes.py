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

_SIBLING_FIRST_HTML = """
<!doctype html>
<html>
  <body>
    <section id="snap-media-active">SnapMagic</section>
    <section id="ultra-media-active" hidden>
      <button onclick="document.getElementById('ultralib-export-options').hidden=false">
        Select Download Format
      </button>
    </section>
    <div id="ultralib-export-options" hidden>
      <input id="ul-kicad" type="radio" name="ultra-format-selection">
      <label for="ul-kicad" data-original="KiCAD v6+">KiCAD v6+</label>
      <input id="ul-step" type="radio" name="ultra-format-selection-3d">
      <label for="ul-step" data-original="STEP">STEP</label>
      <button id="btn-download-Ultra">Download</button>
    </div>
    <script>
      setTimeout(() => {
        document.getElementById("ultra-media-active").hidden = false;
      }, 75);
    </script>
  </body>
</html>
"""

_TRANSIENT_ULTRA_HTML = """
<!doctype html>
<html>
  <body>
    <section id="snap-media-active">SnapMagic</section>
    <section id="ultra-media-active" style="display: none"></section>
    <section id="traceparts-media-active" style="display: none"></section>
    <div id="ultralib-export-options" hidden></div>
  </body>
</html>
"""

_MANUFACTURER_EMBEDDED_HTML = """
<!doctype html>
<html>
  <body>
    <section id="mfr-media-active">Manufacturer Provided</section>
    <div id="mfr-model">
      <a onclick="displayExportModal('#mfr-export-options', 'CODACA')">
        Select Download Format
      </a>
    </div>
    <aside id="mfr-export-options">
      <input
        id="mfr-model-main"
        type="radio"
        name="mfr-format-selection-3d"
        value="https://mm.digikey.com/models/VSEB0630H%203D%20Model.stp"
      >
      <label for="mfr-model-main" data-original="VSEB0630H.stp">VSEB0630H.stp</label>
      <input
        id="mfr-model-footprint"
        type="radio"
        name="mfr-format-selection-3d"
        value="https://mm.digikey.com/models/VSEB0630H%20Footprint.stp"
      >
      <label for="mfr-model-footprint" data-original="VSEB0630H Footprint.stp">
        VSEB0630H Footprint.stp
      </label>
      <input
        id="mfr-model-symbol"
        type="radio"
        name="mfr-format-selection-3d"
        value="https://mm.digikey.com/models/VSEB0630H%20Symbol.stp"
      >
      <label for="mfr-model-symbol" data-original="VSEB0630H Symbol.stp">
        VSEB0630H Symbol.stp
      </label>
      <button id="btn-download-mfr" onclick="exportEdaModel(event)">Download</button>
    </aside>
    <section id="cadenas-media-active" hidden></section>
  </body>
</html>
"""

_MANUFACTURER_EXTERNAL_HTML = """
<!doctype html>
<html>
  <body>
    <section id="mfr-media-active">Manufacturer Provided</section>
    <div id="mfr-model">
      <a href="https://search.kemet.com/download/step/C0603C105K4RACAUTO7411">
        C0603C105K4RACAUTO7411.stp
      </a>
    </div>
    <aside id="mfr-export-options"></aside>
    <section id="cadenas-media-active" hidden></section>
  </body>
</html>
"""

_MANUFACTURER_EMPTY_HTML = """
<!doctype html>
<html>
  <body>
    <section id="mfr-media-active">Manufacturer Provided</section>
    <div id="mfr-model">0424750451 STP</div>
    <aside id="mfr-export-options"></aside>
    <section id="cadenas-media-active" hidden></section>
  </body>
</html>
"""

_CADENAS_VISIBLE_UNMEASURED_HTML = """
<!doctype html>
<html>
  <body>
    <section id="mfr-media-active" hidden></section>
    <section id="cadenas-media-active">CADENAS</section>
    <div id="cadenas-lib-model">3D Model</div>
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
    routes = surface.capture_routes()[:3]
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
def test_digikey_hidden_supplementary_rows_are_terminal_ledger_misses(
    tmp_path,
    monkeypatch,
):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/texas-instruments/"
        "TPD6E05U06RVZR/4307639"
    )
    monkeypatch.setattr(surface, "_wait_for_provider_surface", lambda _page, _route: None)
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/4307639",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_MODELS_HTML,
            ),
        )
        for adapter in surface.capture_routes()[3:]:
            page.goto("https://www.digikey.com/en/models/4307639")
            report = adapter.drive(
                page,
                ["model"],
                expected_manufacturer="Texas Instruments",
                expected_mpn="TPD6E05U06RVZR",
            )

            assert report.submitted is False
            assert report.route_unavailable is True
            assert report.blocked is False
            assert report.missed == ["model"]
            assert f"does not offer {adapter._route.label}" in report.message


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
@pytest.mark.parametrize(
    ("model_id", "manufacturer", "mpn", "html", "message"),
    (
        (
            "16731489",
            "CODACA",
            "VSEB0630H-2R2MC",
            _MANUFACTURER_EMBEDDED_HTML,
            "3 exact DigiKey-hosted STEP originals",
        ),
        (
            "8600948",
            "KEMET",
            "C0603C105K4RACAUTO7411",
            _MANUFACTURER_EXTERNAL_HTML,
            "external manufacturer STEP link on search.kemet.com",
        ),
        (
            "13559621",
            "Molex",
            "0424750451",
            _MANUFACTURER_EMPTY_HTML,
            "supplementary route remains explicitly unresolved",
        ),
    ),
)
def test_digikey_manufacturer_route_classifies_each_measured_shape_without_clicking(
    tmp_path,
    model_id,
    manufacturer,
    mpn,
    html,
    message,
):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        f"https://www.digikey.com/en/products/detail/{manufacturer.casefold()}/"
        f"{mpn}/{model_id}"
    )
    manufacturer_route = surface.capture_routes()[3]
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)
    model_url = f"https://www.digikey.com/en/models/{model_id}"

    with browser.session() as page:
        page.route(
            model_url,
            lambda route: route.fulfill(status=200, content_type="text/html", body=html),
        )
        page.goto(model_url)
        report = manufacturer_route.drive(
            page,
            ["model"],
            expected_manufacturer=manufacturer,
            expected_mpn=mpn,
        )

    assert report.submitted is False
    assert report.route_unavailable is False
    assert report.blocked is False
    assert report.missed == ["model"]
    assert message in report.message


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_visible_cadenas_row_is_explicitly_unresolved_without_a_guess(tmp_path):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/omron-automation-and-safety/"
        "E2E-X5Y1/1776201"
    )
    cadenas = surface.capture_routes()[4]
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/1776201",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_CADENAS_VISIBLE_UNMEASURED_HTML,
            ),
        )
        page.goto("https://www.digikey.com/en/models/1776201")
        report = cadenas.drive(
            page,
            ["model"],
            expected_manufacturer="Omron Automation and Safety",
            expected_mpn="E2E-X5Y1",
        )

    assert report.submitted is False
    assert report.route_unavailable is False
    assert report.blocked is False
    assert report.missed == ["model"]
    assert "no positive live CADENAS format/download contract" in report.message
    assert "no selector was guessed" in report.message


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
    snap = surface.capture_routes()[1]
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
    traceparts = surface.capture_routes()[2]
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


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_does_not_treat_a_fast_sibling_as_catalogue_ready(tmp_path):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/texas-instruments/"
        "TPD6E05U06RVZR/4307639"
    )
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/4307639",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_SIBLING_FIRST_HTML,
            ),
        )
        page.goto("https://www.digikey.com/en/models/4307639")
        report = surface.drive(
            page,
            ["kicad"],
            expected_manufacturer="Texas Instruments",
            expected_mpn="TPD6E05U06RVZR",
        )

    assert report.selected == ["kicad"], report
    assert report.submitted is True


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_retries_a_route_that_same_run_already_observed(tmp_path, monkeypatch):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/texas-instruments/"
        "TPD6E05U06RVZR/4307639"
    )
    monkeypatch.setattr(surface, "_wait_for_provider_surface", lambda _page, _route: None)
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/4307639",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_MODELS_HTML,
            ),
        )
        page.goto("https://www.digikey.com/en/models/4307639")
        surface._remember_visible_routes(page)

        page.unroute("https://www.digikey.com/en/models/4307639")
        page.route(
            "https://www.digikey.com/en/models/4307639",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_TRANSIENT_ULTRA_HTML,
            ),
        )
        page.goto("https://www.digikey.com/en/models/4307639")
        issue = surface.open_panel(
            page,
            expected_manufacturer="Texas Instruments",
            expected_mpn="TPD6E05U06RVZR",
        )

        assert "did not rehydrate" in issue
        assert "temporarily hid" in surface.retryable_download_issue(page)


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_digikey_requires_two_hidden_primary_route_renders_before_absence(
    tmp_path,
    monkeypatch,
):
    surface = DigiKeyUltraLibrarianAdapter()
    surface._exact_product_url = (
        "https://www.digikey.com/en/products/detail/texas-instruments/"
        "TPD6E05U06RVZR/4307639"
    )
    monkeypatch.setattr(surface, "_wait_for_provider_surface", lambda _page, _route: None)
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)

    with browser.session() as page:
        page.route(
            "https://www.digikey.com/en/models/4307639",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=_TRANSIENT_ULTRA_HTML,
            ),
        )
        page.goto("https://www.digikey.com/en/models/4307639")
        first = surface.open_panel(
            page,
            expected_manufacturer="Texas Instruments",
            expected_mpn="TPD6E05U06RVZR",
        )
        assert "one cold hidden placeholder" in first
        assert "first cold hidden" in surface.retryable_download_issue(page)

        page.goto("https://www.digikey.com/en/models/4307639")
        second = surface.open_panel(
            page,
            expected_manufacturer="Texas Instruments",
            expected_mpn="TPD6E05U06RVZR",
        )
        assert second == "DigiKey does not offer Ultra Librarian for this exact product."
        assert surface.retryable_download_issue(page) == ""
