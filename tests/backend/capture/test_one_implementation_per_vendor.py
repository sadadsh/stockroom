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
    worst possible reason: seeing no vendors at all."""
    js_vendors = _js_driver_vendors()
    adapter_keys = {adapter.capability.key for adapter in all_adapters()}
    assert js_vendors, "parsed ZERO JS drivers - the parser is broken, not the codebase clean"
    assert adapter_keys, "the Python adapter registry is empty"
    # and the alias map must be doing real work rather than sitting unused
    assert "snapeda" in js_vendors or "snapmagic" in js_vendors


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
