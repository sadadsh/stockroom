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


# -- Phase 3 HUD rebuild (HUD-01, HUD-02): the overlay is a real heads-up display whose
#    bridge exposes report + received + action + complete, with a per-requirement checklist,
#    an X / Y meter, a Your Turn block, a Complete flash, theme + reduced-motion awareness. --


def test_overlay_exposes_the_full_bridge():
    js = build_overlay_js(["kicad_symbol"], "DigiKey")
    for method in ("report", "received", "action", "complete"):
        assert method in js


def test_overlay_renders_a_row_per_needed_requirement_with_a_stable_id():
    js = build_overlay_js(["kicad_symbol", "kicad_footprint"], "DigiKey")
    assert "__stockroom_row_kicad_symbol__" in js
    assert "__stockroom_row_kicad_footprint__" in js
    assert "__stockroom_row_kicad_model__" not in js  # a not-needed requirement has no row


def test_overlay_received_marks_the_row_and_advances_the_meter():
    js = build_overlay_js(["kicad_symbol", "kicad_footprint"], "DigiKey")
    # the received path touches the meter element and marks the row received
    assert "__stockroom_meter__" in js
    assert "sk-rec" in js
    # an internal received set makes a duplicate received() a no-op
    assert "REC" in js


def test_overlay_meter_starts_at_zero_over_total_with_a_title_case_label():
    js = build_overlay_js(["kicad_symbol", "kicad_footprint", "kicad_model"], "DigiKey")
    assert "0 / 3" in js
    assert "Files Captured" in js  # Title Case meter label


def test_overlay_complete_flash_triggers_when_the_count_reaches_total():
    js = build_overlay_js(["kicad_symbol"], "DigiKey")
    assert "__stockroom_complete__" in js
    assert "Complete" in js
    assert "COUNT>=TOTAL" in js.replace(" ", "")  # the flash reveals at full


def test_overlay_action_needsuser_reveals_your_turn():
    js = build_overlay_js(["kicad_symbol"], "DigiKey")
    assert "__stockroom_yourturn__" in js
    assert "Your Turn" in js  # Title Case interactive label
    assert "needsUser" in js


def test_overlay_part_name_shows_when_passed_and_is_absent_when_blank():
    with_name = build_overlay_js(["kicad_symbol"], "DigiKey", "BQ24074")
    assert "BQ24074" in with_name
    assert "BQ24074" not in build_overlay_js(["kicad_symbol"], "DigiKey")


def test_overlay_has_no_em_dash():
    js = build_overlay_js(["kicad_symbol", "altium_symbol"], "DigiKey", "BQ24074")
    assert "—" not in js


def test_overlay_defines_both_color_scheme_rules():
    compact = build_overlay_js(["kicad_symbol"], "DigiKey").replace(" ", "")
    assert "prefers-color-scheme:dark" in compact  # a dark override exists alongside light


def test_overlay_reduced_motion_disables_the_panel_and_the_complete_flash():
    js = build_overlay_js(["kicad_symbol"], "DigiKey")
    assert "prefers-reduced-motion" in js
    assert "animation:none" in js.replace(" ", "")  # the flash animation is removed


def test_overlay_names_digikey_as_the_vendor_pill():
    assert "DigiKey" in build_overlay_js(["kicad_symbol"], "DigiKey")


def test_overlay_still_a_guarded_iife_with_the_new_hud():
    js = build_overlay_js(["kicad_symbol", "altium_symbol"], "DigiKey", "BQ24074").strip()
    assert js.startswith("(") and js.rstrip(";").endswith(")()")
    assert "try" in js and "catch" in js
