"""RUN the Ultra Librarian driver against Ultra Librarian's REAL export panel.

Every other driver test in this repo asserts that a selector STRING appears in the generated
script. That check cannot fail for a wrong selector, and it did not: `drivers.py` shipped
`[data-ecad='KiCad']`, `button.download` and `[data-testid='download']` for Ultra Librarian, and
measurement on the owner's machine (2026-07-27, scripts/vendorprobe.py) found that NONE of the
three matches anything on the page. The string tests were green the whole time.

So this test executes the real generated JS against the real captured DOM
(`fixtures/ul-export-panel.html`) in jsdom, and asserts the OUTCOME: after the driver runs, the
KiCad and Altium checkboxes are both checked, the required consent is accepted, and the export was
submitted. A wrong selector makes it fail, which is the entire point.

MEASURED FACTS this encodes (all from driving the live page, negative-controlled):
  * the format controls are CHECKBOXES sharing one group (`input[name=exports]`), NOT radios, so
    ONE download delivers both formats - proven by clicking both and reading the state back:
    {"checkedNow":["AltiumDesigner","KiCADv6"],"bothHeld":true}.
  * KiCAD offers v5 (`#KiCAD`) and v6+ (`#KiCADv6`). v6+ is the one to take: the repo's own trap
    log records that KiCad 5 `(module ...)` footprints are REFUSED by `Footprint.load`.
  * the panel's submit is `#submit-export`; `#export-selection-btn` merely OPENS the panel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from stockroom.host.vendor_drivers.drivers import build_driver_js

_FIXTURE = Path(__file__).parent / "fixtures" / "ul-export-panel.html"
_JSDOM = Path(__file__).resolve().parents[3] / "app" / "frontend" / "node_modules" / "jsdom"


def _node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not installed; `gates.sh` fails when this test skips")
    if not _JSDOM.is_dir():
        pytest.skip("jsdom is not installed (npm ci in app/frontend); gates.sh fails on a skip")
    return exe


_RUNNER = r"""
const {JSDOM} = require(process.argv[2]);
const fs = require('fs');
const html = fs.readFileSync(process.argv[3], 'utf8');
const driver = fs.readFileSync(process.argv[4], 'utf8');
const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'https://app.ultralibrarian.com/details/x?open=exports'});
const {window} = dom;
// The overlay bridge the driver reports through. Collect what it says so the test can assert the
// driver is HONEST about what it did, not only that it did it.
const reports = [];
window.__STOCKROOM_OVERLAY__ = {
  report: (r) => reports.push(r),
  action: (a) => reports.push({step: 'action', ...a}),
};
const submitted = [];
const btn = window.document.querySelector('#submit-export');
if (btn) btn.addEventListener('click', () => submitted.push('submit-export'));
try { window.eval(driver); } catch (e) { console.error('DRIVER THREW: ' + e); process.exit(3); }
const checked = [...window.document.querySelectorAll('input[name=exports]')]
  .filter((i) => i.checked).map((i) => i.id);
const consents = [...window.document.querySelectorAll('input[type=checkbox][id^=consent-]')]
  .map((i) => ({id: i.id, checked: i.checked}));
console.log(JSON.stringify({checked, consents, submitted, reports}));
"""


def _run_driver(formats: list[str], tmp_path: Path) -> dict:
    node = _node()
    driver_js = tmp_path / "driver.js"
    driver_js.write_text(build_driver_js("ultralibrarian", formats), encoding="utf-8")
    runner = tmp_path / "runner.js"
    runner.write_text(_RUNNER, encoding="utf-8")
    proc = subprocess.run(
        [node, str(runner), str(_JSDOM), str(_FIXTURE), str(driver_js)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"runner failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_fixture_is_the_real_page_and_starts_with_nothing_selected():
    """Anti-vacuous guard. If the fixture ever loses its controls, or arrives pre-checked, every
    assertion below would pass for the wrong reason."""
    html = _FIXTURE.read_text(encoding="utf-8")
    assert 'name="exports"' in html
    assert 'id="KiCADv6"' in html and 'id="AltiumDesigner"' in html
    assert 'id="submit-export"' in html
    assert 'id="consent-TIInfoShare"' in html
    # nothing is pre-checked on a freshly loaded panel
    assert ' checked' not in html.split('id="submit-export"')[0].split('name="exports"')[1][:400]


def test_both_formats_are_selected_by_one_run(tmp_path):
    """The owner's requirement, verbatim: *"kicad and altium at once"*. On Ultra Librarian that is
    ONE download with two boxes ticked, not two sequenced downloads."""
    out = _run_driver(["kicad", "altium"], tmp_path)
    assert set(out["checked"]) == {"KiCADv6", "AltiumDesigner"}, out


def test_kicad_v6_is_taken_and_the_v5_export_is_not(tmp_path):
    """KiCad 5 emits `(module ...)` footprints, which this repo's `Footprint.load` REFUSES - a
    documented trap that already cost a session. Picking the wrong row downloads a file the app
    cannot ingest, which looks like a capture failure much later."""
    out = _run_driver(["kicad"], tmp_path)
    assert "KiCADv6" in out["checked"]
    assert "KiCAD" not in out["checked"]


def test_only_the_requested_format_is_selected(tmp_path):
    """A KiCad-only part must not download Altium. This is the control that proves the two-format
    result above is the driver choosing, not the driver ticking everything it can find."""
    out = _run_driver(["kicad"], tmp_path)
    assert out["checked"] == ["KiCADv6"], out
    out = _run_driver(["altium"], tmp_path)
    assert out["checked"] == ["AltiumDesigner"], out


def test_the_required_consent_is_accepted(tmp_path):
    """Owner's decision, 2026-07-27, asked and answered: always auto-tick. Ultra Librarian will not
    export without it, and it is per-manufacturer, so a 90-part sitting would otherwise cost 90
    manual ticks."""
    out = _run_driver(["kicad", "altium"], tmp_path)
    assert out["consents"], "the fixture carries no consent checkbox to accept"
    assert all(c["checked"] for c in out["consents"]), out


def test_the_export_is_actually_submitted(tmp_path):
    """The download only happens if #submit-export is clicked. Selecting formats and stopping is
    the failure that reads as success."""
    out = _run_driver(["kicad", "altium"], tmp_path)
    assert out["submitted"] == ["submit-export"], out


def test_the_driver_says_what_it_did(tmp_path):
    """`SUCCESS IS REPORTED BY WHAT OBSERVES IT`: the overlay must name the formats it selected, so
    the HUD cannot claim a format it never ticked."""
    out = _run_driver(["kicad", "altium"], tmp_path)
    said = " ".join(str(r.get("message", "")) for r in out["reports"]).lower()
    assert "kicad" in said and "altium" in said, out["reports"]
