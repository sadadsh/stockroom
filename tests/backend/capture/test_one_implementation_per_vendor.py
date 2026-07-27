"""ONE implementation per vendor. Enforced, not intended.

Owner, 2026-07-27: *"everything about our code should be unified, things should work exactly how u
test them and remain that way for all devices - no stray code that would confuse u later on in
current branches"*.

THE FAILURE THIS PREVENTS, which nearly shipped the same day it was named.
Guided capture had a Windows-only path (injected JS drivers inside the WebView2 capture window) and
was gaining a cross-platform one (Python adapters driven by Playwright). For a while BOTH described
how to capture from Ultra Librarian. That is worse than either alone:

  * the tests exercise the Python one on Linux while Windows runs the JS one, so a green suite says
    nothing about what the owner experiences - the exact layer gap that let a driver which selected
    Altium only, never consented and never clicked Download stay green for months;
  * the two drift, and the next session cannot tell which is authoritative.

So a vendor may be implemented in exactly one place. When a vendor is ported to a Python adapter,
its JS driver is DELETED in the same change - not deprecated, not left behind a flag.
"""

from __future__ import annotations

import re
from pathlib import Path

from stockroom.capture.vendors import all_adapters

_DRIVERS = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "backend"
    / "stockroom"
    / "host"
    / "vendor_drivers"
    / "drivers.py"
)
# Vendor keys as the JS driver layer spells them, mapped to the adapter registry's spelling.
# SnapEDA is `snapmagic` in the CAD-source registry and `snapeda` in the driver layer; the two
# names are the SAME vendor, so the check must see through the alias or it would miss a real clash.
_ALIASES = {"snapeda": "snapmagic", "snapmagic": "snapeda"}


def _js_driver_vendors() -> set[str]:
    """Vendor keys still implemented as injected JS in the host layer."""
    source = _DRIVERS.read_text(encoding="utf-8")
    keys: set[str] = set()
    # the `_VENDORS` table
    table = re.search(r"_VENDORS:\s*dict\[str,\s*dict\]\s*=\s*\{(.*?)\n\}", source, re.S)
    if table:
        keys |= set(re.findall(r'^\s*"([a-z0-9_]+)":\s*\{', table.group(1), re.M))
    # any vendor with its own dedicated builder, e.g. `_digikey_driver_js`
    keys |= {
        name for name in re.findall(r"^def _([a-z0-9_]+)_driver_js\(", source, re.M)
    }
    return keys


def test_no_vendor_is_implemented_twice():
    js_vendors = _js_driver_vendors()
    adapter_keys = {adapter.capability.key for adapter in all_adapters()}
    aliased = {_ALIASES.get(key, key) for key in adapter_keys} | adapter_keys

    clashes = sorted(js_vendors & aliased)
    assert not clashes, (
        "these vendors have BOTH an injected-JS driver and a Python capture adapter: "
        f"{clashes}. Pick one - delete the JS driver in the same change that adds the adapter. "
        "Two implementations mean the tests and the owner's machine can disagree silently."
    )


def test_the_check_can_actually_see_both_sides():
    """Anti-vacuous guard. If either side parsed to nothing, the test above would pass for the
    worst possible reason: seeing no vendors at all.

    It no longer asserts that any PARTICULAR vendor is still implemented as JS, because that made
    the guard fail the moment a vendor was correctly ported - punishing exactly the migration this
    file exists to encourage. SnapEDA was the last one, deleted 2026-07-27 when `SnapMagicAdapter`
    landed. The parser is proved on a synthetic source instead, so it can never go quietly blind.
    """
    adapter_keys = {adapter.capability.key for adapter in all_adapters()}
    assert adapter_keys, "the Python adapter registry is empty"
    assert _DRIVERS.is_file(), f"the JS driver module is missing at {_DRIVERS}"
    # The real file may legitimately contain ZERO js vendors (every one ported). What must never
    # break silently is the PARSER, so run it against a source that definitely contains both shapes.
    import re as _re

    sample = (
        '_VENDORS: dict[str, dict] = {\n    "examplevendor": {\n        "label": "X",\n    },\n}\n'
        "def _othervendor_driver_js(page):\n    return ''\n"
    )
    table = _re.search(r"_VENDORS:\s*dict\[str,\s*dict\]\s*=\s*\{(.*?)\n\}", sample, _re.S)
    assert table, "the _VENDORS table pattern no longer matches its own shape"
    assert set(_re.findall(r'^\s*"([a-z0-9_]+)":\s*\{', table.group(1), _re.M)) == {"examplevendor"}
    assert set(_re.findall(r"^def _([a-z0-9_]+)_driver_js\(", sample, _re.M)) == {"othervendor"}


def test_a_vendor_implemented_on_both_sides_is_detected_through_its_alias():
    """The alias map must do REAL work, proved directly rather than by hoping live data exercises it.

    SnapEDA is `snapmagic` in the CAD-source registry and `snapeda` in the driver layer; the same
    vendor under two names is the case a naive set-intersection would miss entirely.
    """
    js_vendors = {"snapeda"}
    adapter_keys = {"snapmagic"}
    aliased = {_ALIASES.get(key, key) for key in adapter_keys} | adapter_keys
    assert sorted(js_vendors & aliased) == ["snapeda"], (
        "the alias map failed to connect snapeda to snapmagic, so a genuine double "
        "implementation of that vendor would go unreported"
    )


def test_ultra_librarian_lives_only_in_the_python_adapter():
    """The concrete instance this was written for: UL was ported to Python, so its JS driver must
    be gone. Named explicitly so a re-add is caught by a test that says why."""
    js_vendors = _js_driver_vendors()
    assert "ultralibrarian" not in js_vendors
    assert "ultralibrarian" in {adapter.capability.key for adapter in all_adapters()}


def test_every_adapter_pins_a_version_for_every_tool_it_claims():
    """The cross-vendor hazard, made structural. Ultra Librarian offers KiCAD v5 one row above v6+,
    and SnapEDA offers 'V3 & Prior' / 'V4 & Later' / 'V6 & Later'. KiCad 5 emits `(module ...)`
    footprints that `Footprint.load` REFUSES, so an unpinned version silently poisons the library
    far from the cause. A tool a vendor claims to serve must name WHICH export to take."""
    for adapter in all_adapters():
        capability = adapter.capability
        for tool in capability.tools:
            assert capability.version_pins.get(tool), (
                f"{capability.key} claims to serve {tool} but pins no specific export for it; "
                "an unpinned version is how a KiCad-5 footprint reaches the library"
            )
