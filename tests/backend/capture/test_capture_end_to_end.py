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

import time

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
        if report.submitted:
            _wait_for_file(browser, page, before=0)
    return report, browser.captured


def _wait_for_file(browser, page, before: int, timeout_s: float = 60.0) -> bool:
    """True once a NEW file has actually been SAVED.

    NEVER `page.wait_for_event("download")` here either. The session registers an `on("download")`
    handler when it opens, and whichever listener is active when the event fires consumes it - so
    against this LOCALHOST fixture, where the download completes in well under a second, the
    handler always won and the wait always ran to its full 90s timeout. Measured 2026-07-27: three
    tests in this file each sat out that timeout and then failed, for files that were on disk the
    whole time. That is the same defect `capture/guided.py` had in production, and it is locked
    there by tests/backend/capture/test_guided_download_wait.py.

    AND IT SLEEPS THROUGH THE PAGE, for the same reason the production wait does. This helper used
    `time.sleep`, which passed only by accident: against a localhost fixture the download is already
    dispatched during `drive()`, so the loop never actually had to observe anything. A bare
    `time.sleep` blocks the thread that Playwright's sync api needs in order to deliver
    `on("download")` at all, so the moment the fixture or the machine got slower these tests would
    have failed with a phantom "no file downloaded" - the exact confusion that cost an hour today.
    Found by asking where ELSE the production defect existed, rather than assuming it was unique.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if len(browser.captured) > before:
            return True
        page.wait_for_timeout(200)
    return len(browser.captured) > before


def test_every_selectable_format_rides_one_download(tmp_path, vendor):
    """Ultra Librarian gives symbol, footprint AND the STEP in ONE export.

    CORRECTED 2026-07-27 against a real download. This used to ask for "kicad and altium" and
    assert both were selected - and on the live site that produced a zip with a KiCad symbol and
    footprint, NO 3D model, and an Altium *script* instead of libraries, while the run reported
    success. The 3D lives behind its own "3D CAD Model" accordion and was never ticked.
    """
    report, captured = _capture(tmp_path, vendor, ["kicad", "model"])
    assert report.selected == ["kicad", "model"], report
    assert report.missed == [], report
    assert report.submitted is True
    assert len(captured) == 1, f"expected ONE download carrying both formats, got {captured}"
    assert captured[0].path.exists()
    assert captured[0].path.stat().st_size > 0


def test_the_downloaded_file_really_carries_symbol_footprint_and_3d(tmp_path, vendor):
    """Classification is the layer that decides what gets ATTACHED, so assert there - not on the
    fact that a file arrived. A zip that lands but classifies as nothing satisfies no requirement
    and leaves the part exactly as incomplete as before, which is what a real run did."""
    _, captured = _capture(tmp_path, vendor, ["kicad", "model"])
    classified = classify_asset(captured[0].path)
    assert Requirement.KICAD_SYMBOL in classified.requirements
    assert Requirement.KICAD_FOOTPRINT in classified.requirements
    assert Requirement.KICAD_MODEL in classified.requirements


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
        UltraLibrarianAdapter().drive(page, ["kicad", "model"])
        unticked = page.eval_on_selector_all(
            "input[type=checkbox][id^=consent-]", "els => els.filter(e => !e.checked).length"
        )
    assert unticked == 0


def test_nothing_is_reported_downloaded_before_a_file_exists(tmp_path, vendor):
    """`SUCCESS IS REPORTED BY WHAT OBSERVES IT`. `captured` is appended only after `save_as`
    returns, so a report of a download always has a readable file behind it."""
    _, captured = _capture(tmp_path, vendor, ["kicad", "model"])
    assert captured, "a submitted capture reported no file at all"
    for item in captured:
        assert isinstance(item, CapturedFile)
        assert item.path.is_file(), f"{item.path} was reported captured but is not on disk"


def test_the_registry_does_not_claim_altium_the_app_cannot_yet_attach(tmp_path):
    """Capability is DATA the engine trusts, so it must say the TRUE thing.

    THE SUBTLE PART, and the reason this test is worth its length: the vendor is NOT the blocker.
    Ultra Librarian's Altium accordion holds three rows, from the real export panel captured at
    tests/backend/host/fixtures/ul-export-panel.html:

      * `#AltiumDesigner` "Altium Designer (script based)" -> `UL_Import.pas` + a `.PrjScr` and no
        libraries at all. Measuring ONLY this row produced the over-general conclusion "UL cannot
        supply Altium", which is wrong.
      * `#AltiumPCADV15` "PCAD v15" -> `AltiumV15/<stamp>.lia`, a P-CAD ASCII library Altium
        imports directly, carrying one symbolDef AND one patternDef.

    So UL genuinely can serve it. What cannot happen yet is STORING it: nothing turns a `.lia` into
    the record's Altium bundle (see the sibling test below). Because `provides()` is derived from
    `version_pins`, claiming altium here would schedule parts for requirements no code can satisfy -
    downloaded every run, never completed. Capability must describe the WHOLE path, vendor and app.
    """
    adapter = get_adapter("ultralibrarian")
    assert adapter is not None
    assert adapter.capability.formats_exclusive is False
    assert adapter.capability.version_pins["kicad"] == "KiCADv6"
    # Current live panel (2026-07-28). The older captured fixture uses `MfrThreeDModel`; the
    # adapter keeps that as a selector fallback but must declare the production control first.
    assert adapter.capability.version_pins["model"] == "ThreeDModel"

    # NOT altium - and the reason is a missing ATTACH, not a missing vendor feature. The PCAD row
    # really does deliver a `.lia` (proved by the fixture, which serves exactly that). But
    # `provides()` derives from these pins, so claiming altium would schedule parts for altium
    # requirements that `_attach` cannot satisfy and `normalize_altium_source` refuses outright -
    # a part requested and downloaded forever without ever completing.
    assert "altium" not in adapter.capability.tools
    assert "altium" not in adapter.capability.version_pins


def test_the_altium_attach_really_is_the_thing_that_is_missing(tmp_path):
    """Pins the REASON above to the code, so the capability is re-enabled for the right cause.

    If someone wires `.lia` through the attach path, this test starts failing and says so - which
    is the signal that the capability flip is now correct. Without it, the comment on
    UltraLibrarianAdapter is just prose that can quietly go stale.
    """
    from stockroom.altium.extract import normalize_altium_source

    lia = tmp_path / "2026-07-27_20-52-11.lia"
    lia.write_text('ACCEL_ASCII "X"\n(symbolDef "S")\n(patternDef "P")\n', encoding="utf-8")

    with pytest.raises(ValueError):
        normalize_altium_source(lia, out_dir=tmp_path)


def test_the_3d_model_is_its_own_export_category():
    """The defect this encodes: a 3D model is NOT part of the KiCad export. Asking only for
    "kicad" returns a symbol and a footprint and silently no STEP."""
    assert formats_for([Requirement.KICAD_SYMBOL]) == ["kicad"]
    assert formats_for([Requirement.KICAD_MODEL]) == ["model"]
    assert formats_for([Requirement.KICAD_SYMBOL, Requirement.KICAD_MODEL]) == ["kicad", "model"]
    assert formats_for([Requirement.ALTIUM_FOOTPRINT]) == ["altium"]
    assert formats_for([]) == []


def test_the_drive_report_never_claims_a_file_it_cannot_have_seen(tmp_path, vendor):
    """A drive can observe two things: which controls it SELECTED, and that it clicked submit.
    Whether files arrived is decided later by `classify_asset` on the real download.

    The wording used to be "Downloading kicad and altium together", and on the live vendor that
    was FALSE - the zip carried no Altium libraries at all. So the message must state intent, and
    the word "download" must not appear in it: the engine reports what landed, from the record.
    """
    report, _ = _capture(tmp_path, vendor, ["kicad", "model"])
    assert report.submitted is True
    assert "download" not in report.message.lower(), report.message
    assert "requested" in report.message.lower(), report.message
