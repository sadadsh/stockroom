from stockroom.host.vendor_drivers.drivers import build_driver_js


def test_ultralibrarian_driver_targets_both_formats_and_is_guarded():
    js = build_driver_js("ultralibrarian", ["kicad", "altium"])
    assert "KiCad" in js and "Altium" in js  # both format selections attempted
    assert js.count("try") >= 3 and js.count("catch") >= 3  # each step guarded
    assert "__STOCKROOM_OVERLAY__" in js  # reports back to the overlay bridge
    stripped = js.strip()
    assert stripped.startswith("(") and stripped.rstrip(";").endswith(")()")  # a self-contained IIFE


def test_snapeda_driver_is_built_for_snapeda():
    js = build_driver_js("SnapEDA", ["kicad", "altium"])
    assert "snapeda" in js.lower()
    assert "try" in js and "catch" in js
    assert "__STOCKROOM_OVERLAY__" in js


def test_digikey_driver_dismisses_consent_finds_cad_and_opens_a_provider_control():
    # The adaptive state machine: dismiss consent -> keep findCad (custom-scroll container +
    # div-text match, live-validated) -> detect the aggregated providers -> open a download control.
    js = build_driver_js("digikey", ["kicad", "altium"])
    low = js.lower()
    # step 1: a cookie/consent banner is dismissed first
    assert "onetrust" in low or "accept" in low or "consent" in low
    # step 2: findCad KEPT verbatim in behavior (custom scroll container + div-text match)
    assert "scrollintoview" in low and "textcontent" in low
    # step 3: detects the three providers DigiKey aggregates in its EDA / CAD Models section
    assert ("ultra" in low or "librarian" in low) and "snapeda" in low and "samacsys" in low
    # step 4: opens the Download / Add To Library control (no user click)
    assert "download" in low and "add to library" in low
    # reports every step into the overlay bridge, guarded, one self-contained IIFE
    assert "__STOCKROOM_OVERLAY__" in js
    assert js.count("try") >= 4 and js.count("catch") >= 4
    assert js.count("report(") >= 4
    stripped = js.strip()
    assert stripped.startswith("(") and stripped.rstrip(";").endswith(")()")


def test_digikey_driver_prefers_ultra_librarian_before_snapeda_and_samacsys():
    # Ultra Librarian is the most-complete default, so it is detected/preferred first, then
    # SnapEDA, then SamacSys - the preference order is encoded in the generated machine.
    low = build_driver_js("digikey", ["kicad"]).lower()
    ul = low.find("ultra librarian")
    if ul < 0:
        ul = low.find("librarian")
    assert 0 <= ul < low.find("snapeda") < low.find("samacsys")


def test_digikey_driver_is_resilient_via_a_text_fallback():
    # DigiKey's markup changes, so the driver also matches by textContent, not brittle ids only.
    js = build_driver_js("digikey", ["kicad"])
    assert "textContent" in js or "innerText" in js


def test_unknown_vendor_is_a_guidance_only_noop():
    js = build_driver_js("mouser", ["kicad"])
    # a benign script: no auto-click attempts, but still reports guidance to the overlay
    assert ".click()" not in js
    assert "__STOCKROOM_OVERLAY__" in js
    assert "try" in js and "catch" in js  # still guarded, never throws


def test_only_requested_formats_are_gated_in():
    only_kicad = build_driver_js("ultralibrarian", ["kicad"])
    # the config the script reads carries exactly the requested formats
    assert '"kicad"' in only_kicad
    assert '"altium"' not in only_kicad


def test_blank_or_empty_vendor_is_guidance_only():
    assert "__STOCKROOM_OVERLAY__" in build_driver_js("", ["kicad"])
    assert ".click()" not in build_driver_js("", ["kicad"])
