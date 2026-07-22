from stockroom.host.overlay import build_overlay_js


def test_overlay_lists_each_needed_requirement_label():
    js = build_overlay_js(["kicad_symbol", "altium_footprint"], "UltraLibrarian")
    assert "KiCad Symbol" in js
    assert "Altium Footprint" in js
    assert "KiCad 3D Model" not in js  # a not-needed requirement is not shown


def test_overlay_defines_the_bridge_and_report():
    js = build_overlay_js(["kicad_symbol"], "SnapEDA")
    assert "window.__STOCKROOM_OVERLAY__" in js
    assert "report" in js


def test_overlay_injects_a_fixed_container():
    js = build_overlay_js(["kicad_symbol"], "UltraLibrarian")
    assert "position:fixed" in js.replace(" ", "")


def test_overlay_names_the_vendor():
    assert "UltraLibrarian" in build_overlay_js(["kicad_symbol"], "UltraLibrarian")


def test_overlay_respects_reduced_motion():
    assert "prefers-reduced-motion" in build_overlay_js(["kicad_symbol"], "UltraLibrarian")


def test_overlay_is_a_guarded_iife():
    js = build_overlay_js(["kicad_symbol"], "UltraLibrarian").strip()
    assert js.startswith("(") and js.rstrip(";").endswith(")()")
    assert "try" in js and "catch" in js


def test_overlay_empty_needs_still_valid():
    js = build_overlay_js([], "UltraLibrarian")
    assert "window.__STOCKROOM_OVERLAY__" in js
