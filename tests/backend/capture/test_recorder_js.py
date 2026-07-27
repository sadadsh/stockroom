"""The session recorder actually records.

`scripts/capturerec.py` opens a visible browser for the OWNER to drive - clearing a Cloudflare
wall, signing in, choosing formats - and writes down what they did so an adapter can be authored
from a real journey instead of guessed selectors.

The browser has to be VISIBLE for that, which cannot run on a headless box. But the part that can
silently be wrong is the in-page recorder, and that CAN be tested anywhere: inject it, drive the
page, and assert the log. Without this, "I built you a recorder" would be a claim with nothing
behind it - and a recorder that captures nothing is worse than none, because the person spends
their time and gets an empty file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stockroom.capture.browser import PlaywrightCaptureBrowser, chromium_unavailable_reason

from .vendor_fixture_server import serve_fixture_vendor

_NO_BROWSER = chromium_unavailable_reason()
pytestmark = pytest.mark.skipif(_NO_BROWSER is not None, reason=str(_NO_BROWSER))

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "capturerec.py"


def _recorder_js() -> str:
    """The REAL recorder source, read out of the shipped script.

    Read rather than copied: a duplicated copy here would drift from the one the owner actually
    runs, and then this test would be reassuring about code nobody executes.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'_RECORDER_JS = r"""(.*?)"""', text, re.S)
    assert match, "could not find _RECORDER_JS in capturerec.py"
    return match.group(1)


@pytest.fixture
def page_with_recorder():
    base, shutdown = serve_fixture_vendor()
    browser = PlaywrightCaptureBrowser(download_dir=Path("/tmp/sr-rec-test"), headless=True)
    with browser.session() as page:
        page.goto(base)
        page.evaluate(_recorder_js())
        yield page
    shutdown()


def test_it_records_a_click_with_a_usable_selector(page_with_recorder):
    page = page_with_recorder
    page.evaluate("document.querySelector('a.accordion-toggle').click()")
    log = page.evaluate("window.__SR_REC__")
    clicks = [e for e in log if e.get("kind") == "click"]
    assert clicks, log
    assert clicks[0]["selector"], clicks[0]
    # the selector must be specific enough to re-find the control later
    assert page.locator(clicks[0]["selector"]).count() >= 1, clicks[0]


def test_it_records_which_checkbox_was_ticked(page_with_recorder):
    """The single most important thing to learn from a human's session: WHICH export they chose.
    Ultra Librarian lists KiCAD v5 directly above v6+, so 'they ticked a KiCad box' is not enough.
    """
    page = page_with_recorder
    page.evaluate("document.querySelector('#KiCADv6').click()")
    log = page.evaluate("window.__SR_REC__")
    checks = [e for e in log if e.get("kind") == "check"]
    assert checks, log
    assert checks[-1]["selector"] == "#KiCADv6", checks[-1]
    assert checks[-1]["checked"] is True


def test_a_password_is_never_written_down(page_with_recorder):
    """The recording is a file on disk that gets read later. A vendor sign-in is exactly what the
    person will type into it, so the value of a password field must never be captured - only the
    fact that one was filled."""
    page = page_with_recorder
    page.evaluate(
        "document.body.insertAdjacentHTML('beforeend',"
        "'<input id=pw type=password>')"
    )
    page.fill("#pw", "hunter2-should-never-appear")
    log = page.evaluate("window.__SR_REC__")
    fills = [e for e in log if e.get("kind") == "fill"]
    assert fills, log
    secret = [e for e in fills if e.get("selector") == "#pw"]
    assert secret, fills
    assert secret[0].get("secret") is True
    assert "value" not in secret[0], secret[0]
    assert "hunter2" not in repr(log)


def test_a_normal_field_value_is_kept_because_it_is_the_workflow(page_with_recorder):
    """The control that keeps the redaction test honest: if NOTHING were recorded, the password
    test would pass for the wrong reason."""
    page = page_with_recorder
    page.evaluate(
        "document.body.insertAdjacentHTML('beforeend','<input id=q type=text>')"
    )
    page.fill("#q", "TPD6E05U06RVZR")
    log = page.evaluate("window.__SR_REC__")
    fills = [e for e in log if e.get("selector") == "#q"]
    assert fills, log
    assert fills[0].get("value") == "TPD6E05U06RVZR"


def test_every_entry_carries_where_it_happened(page_with_recorder):
    """A journey is the ORDER and the PAGE, not a bag of clicks - the whole reason to watch a real
    session is to learn which step had to precede which."""
    page = page_with_recorder
    page.evaluate("document.querySelector('#KiCADv6').click()")
    log = page.evaluate("window.__SR_REC__")
    assert log
    for entry in log:
        assert entry.get("url"), entry
        assert entry.get("t"), entry
