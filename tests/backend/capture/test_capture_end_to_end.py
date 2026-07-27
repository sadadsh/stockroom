"""The whole capture chain, driven for real, on Linux OR Windows.

THIS IS THE TEST THAT COULD NOT EXIST BEFORE. Guided capture lived inside a Windows-only WebView2
window reached through `window.pywebview.api`, so from Linux the flow degraded to "pick the files
yourself" and nothing below the URL layer was observable. Every claim about capture was therefore
made from an adjacent layer - which is exactly how a driver that selected Altium only, never
consented and never clicked Download stayed green for months.

What it actually exercises, end to end, in a real browser:
    open the vendor page -> expand the accordions -> tick BOTH format checkboxes -> accept the
    required consent -> submit -> the browser performs a REAL download -> the file lands on disk
    -> `classify_asset` reads it and reports the requirements it satisfies.

The vendor is a local stand-in serving the REAL captured markup; see
`vendor_fixture_server.py` for exactly which part is verbatim and which stands in for the
vendor's own JS.
"""

from __future__ import annotations

import pytest

from stockroom.capture.browser import (
    CapturedFile,
    PlaywrightCaptureBrowser,
    chromium_unavailable_reason,
)
from stockroom.capture.classify import classify_asset
from stockroom.capture.requirements import Requirement
from stockroom.capture.vendors import UltraLibrarianAdapter, formats_for, get_adapter

from .vendor_fixture_server import serve_fixture_vendor

_NO_BROWSER = chromium_unavailable_reason()

# The reason is the REAL one, never a guessed one. An earlier version printed "chromium is not
# installed" for every cause, and the actual failure was a TMPDIR that did not exist - so the skip
# line actively misdirected. If this skips, read the reason: it names what to fix.
pytestmark = pytest.mark.skipif(_NO_BROWSER is not None, reason=str(_NO_BROWSER))


@pytest.fixture
def vendor():
    base, shutdown = serve_fixture_vendor()
    try:
        yield base
    finally:
        shutdown()


def _capture(tmp_path, base_url: str, formats: list[str]):
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "dl", headless=True)
    adapter = UltraLibrarianAdapter()
    with browser.session() as page:
        page.goto(base_url)
        report = adapter.drive(page, formats)
        # Wait on the real signal - a file arriving - never on a clock.
        page.wait_for_event("download", timeout=15_000) if report.submitted else None
    return report, browser.captured


def test_both_formats_are_selected_and_one_download_lands(tmp_path, vendor):
    """The owner's requirement, verbatim: *"kicad and altium at once"*."""
    report, captured = _capture(tmp_path, vendor, ["kicad", "altium"])
    assert report.selected == ["kicad", "altium"], report
    assert report.missed == [], report
    assert report.submitted is True
    assert len(captured) == 1, f"expected ONE download carrying both formats, got {captured}"
    assert captured[0].path.exists()
    assert captured[0].path.stat().st_size > 0


def test_the_downloaded_file_really_carries_both_tools(tmp_path, vendor):
    """Classification is the layer that decides what gets attached, so assert THERE - not on the
    fact that a file arrived. A zip that lands but classifies as nothing satisfies no requirement
    and would leave the part exactly as incomplete as before."""
    _, captured = _capture(tmp_path, vendor, ["kicad", "altium"])
    classified = classify_asset(captured[0].path)
    assert Requirement.KICAD_SYMBOL in classified.requirements
    assert Requirement.KICAD_FOOTPRINT in classified.requirements
    assert Requirement.KICAD_MODEL in classified.requirements
    assert Requirement.ALTIUM_SYMBOL in classified.requirements
    assert Requirement.ALTIUM_FOOTPRINT in classified.requirements


def test_a_kicad_only_capture_does_not_drag_in_altium(tmp_path, vendor):
    """The control that makes the test above mean something: if the adapter ticked everything it
    could find, both tests would pass and neither would prove it CHOSE."""
    report, captured = _capture(tmp_path, vendor, ["kicad"])
    assert report.selected == ["kicad"], report
    classified = classify_asset(captured[0].path)
    assert Requirement.KICAD_SYMBOL in classified.requirements
    assert Requirement.ALTIUM_SYMBOL not in classified.requirements
    assert Requirement.ALTIUM_FOOTPRINT not in classified.requirements


def test_the_kicad_v5_export_is_never_the_one_taken(tmp_path, vendor):
    """KiCad 5 emits `(module ...)` footprints that `Footprint.load` REFUSES. Ultra Librarian
    lists v5 one row ABOVE v6+, so an off-by-one row silently poisons the library."""
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "dl", headless=True)
    with browser.session() as page:
        page.goto(vendor)
        UltraLibrarianAdapter().drive(page, ["kicad"])
        checked = page.eval_on_selector_all(
            "input[name=exports]:checked", "els => els.map(e => e.id)"
        )
    assert checked == ["KiCADv6"], checked


def test_the_required_consent_is_accepted(tmp_path, vendor):
    """Ultra Librarian will not export without it; owner chose auto-tick 2026-07-27."""
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "dl", headless=True)
    with browser.session() as page:
        page.goto(vendor)
        UltraLibrarianAdapter().drive(page, ["kicad", "altium"])
        unticked = page.eval_on_selector_all(
            "input[type=checkbox][id^=consent-]", "els => els.filter(e => !e.checked).length"
        )
    assert unticked == 0


def test_nothing_is_reported_downloaded_before_a_file_exists(tmp_path, vendor):
    """`SUCCESS IS REPORTED BY WHAT OBSERVES IT`. `captured` is appended only after `save_as`
    returns, so a report of a download always has a readable file behind it."""
    _, captured = _capture(tmp_path, vendor, ["kicad", "altium"])
    assert captured, "a submitted capture reported no file at all"
    for item in captured:
        assert isinstance(item, CapturedFile)
        assert item.path.is_file(), f"{item.path} was reported captured but is not on disk"


def test_the_adapter_registry_declares_ultra_librarian_as_one_download(tmp_path):
    """Capability is DATA the engine reads, so it must say the true thing: Ultra Librarian's own
    site gives both formats in ONE export, so the engine must NOT sequence it."""
    adapter = get_adapter("ultralibrarian")
    assert adapter is not None
    assert adapter.capability.formats_exclusive is False
    assert adapter.capability.version_pins["kicad"] == "KiCADv6"
    assert set(adapter.capability.tools) == {"kicad", "altium"}


def test_formats_are_derived_from_requirements_not_hardcoded():
    assert formats_for([Requirement.KICAD_SYMBOL]) == ["kicad"]
    assert formats_for([Requirement.ALTIUM_FOOTPRINT]) == ["altium"]
    assert formats_for([Requirement.KICAD_MODEL, Requirement.ALTIUM_SYMBOL]) == ["kicad", "altium"]
    assert formats_for([]) == []
