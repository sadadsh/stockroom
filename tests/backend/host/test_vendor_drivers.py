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


def test_digikey_driver_navigates_to_the_models_page_and_drives_a_provider_download():
    # Live-validated 2026-07-23: product page -> the stable eda-cad-model-link -> /en/models/<id>,
    # then the provider left-bar rows + the Select Download Format modal + the footer download button.
    js = build_driver_js("digikey", ["kicad", "altium"])
    low = js.lower()
    # phase 1: find + open the dedicated CAD models page via its stable link/href
    assert "eda-cad-model-link" in js and "/models/" in js
    # phase 2: the provider left-bar rows, the format control, the export modal, the download button
    assert "media-active" in low  # #<prov>-media-active provider rows
    assert "select download format" in low  # the control that opens the modal
    assert "export-options" in low  # the #<prov>-export-options format modal
    assert "btn-download-" in low  # the footer #btn-download-<Provider> that fires exportUltraFile
    # reports every step into the overlay bridge, guarded, one self-contained IIFE
    assert "__STOCKROOM_OVERLAY__" in js
    assert js.count("try") >= 4 and js.count("catch") >= 4
    assert js.count("report(") >= 4
    stripped = js.strip()
    assert stripped.startswith("(") and stripped.rstrip(";").endswith(")()")


def test_digikey_driver_enumerates_visible_providers_preferring_snapmagic():
    # Per-part coverage varies (owner: "DigiKey shows which suppliers have what"), so the reactor
    # enumerates only the VISIBLE provider rows (a display:none row has offsetParent===null), in
    # preference order SnapMagic first - the owner's proven, reliable two-format source (Ultra
    # Librarian errors on the 2nd file). The preference order is encoded in the reactor.
    low = build_driver_js("digikey", ["kicad"]).lower()
    assert "offsetparent" in low  # visibility gate = adaptive coverage, not a fixed provider
    sm = low.find("snapmagic")
    assert 0 <= sm < low.find("ultra librarian") < low.find("cadenas")


def test_digikey_reactor_advances_on_the_real_browser_download_event():
    # The reactor advances to the next format ONLY on the browser's REAL download-completed event
    # (relayed to window.__SR_DL__), not a timer or a phantom vendor modal - this is what avoids the
    # preemption + phantom-modal hang. So the driver installs the __SR_DL__ bridge and awaits it.
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "window.__SR_DL__" in js  # the real-download-event bridge the host relays into
    # advances only on a real per-format 'completed' (the host relays it when a file is captured)
    assert "awaitDownload" in js and "'completed'" in js and "evt.format===spec.key" in js
    # It must NOT gate the next format on a timer/poll or the old capture-flag: those were the bugs.
    assert "__SR_FMT_DONE__" not in js
    assert "waitFor" not in js  # no fixed-interval polling


def test_digikey_reactor_is_event_driven_not_timed():
    # "React to what's happening live, no timers": stepping is MutationObserver-driven (until reacts
    # the instant the DOM satisfies a predicate); timers appear ONLY as never-hang watchdogs.
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "MutationObserver" in js and "requestAnimationFrame" in js  # event-driven, debounced
    assert "elementFromPoint" in js  # a real hit-test at the click moment, not a blind click
    assert "GEN_WD" in js  # the single watchdog is the only timer (a never-hang backstop)


def test_digikey_reactor_recovers_like_a_human_refresh_and_your_turn():
    # It never gets left on a hang: a stall/error refreshes the page (the owner's move), bounded so it
    # can't loop; a Cloudflare / login wall hands off to the user via the overlay "Your Turn".
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "location.reload" in js and "MAX_REFRESH" in js  # bounded refresh recovery
    assert "senseError" in js and "senseWall" in js  # watches for the error toast + the wall
    assert ".action({needsUser:true" in js  # Cloudflare/login -> "Your Turn" hand-off


def test_digikey_driver_is_resilient_via_a_text_and_label_match():
    # DigiKey's element ids change, so the format is chosen by its STABLE data-original label text.
    js = build_driver_js("digikey", ["kicad"])
    assert "textContent" in js or "innerText" in js
    assert "data-original" in js


def test_digikey_driver_gates_requested_formats():
    # only the requested tools are targeted; an un-requested format's name never appears anywhere
    both = build_driver_js("digikey", ["kicad", "altium"]).lower()
    assert "kicad" in both and "altium" in both
    only_kicad = build_driver_js("digikey", ["kicad"])
    assert '"kicad"' in only_kicad  # requested format key encoded via json.dumps
    assert "altium" not in only_kicad.lower()  # the Altium spec (name + regex) is gated out entirely


def test_digikey_driver_selects_the_eda_format_plus_the_3d_step_model():
    # One download per format carries the symbol + footprint (the chosen EDA format) AND the 3D
    # model (the STEP radio, selected alongside), then the footer download button fires it.
    low = build_driver_js("digikey", ["kicad"]).lower()
    assert "kicad" in low  # the 2D EDA format radio, matched by data-original label
    assert "step" in low  # the 3D model radio, selected in the same modal
    assert "btn-download-" in low  # the footer download button that fires the real download


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


def test_digikey_driver_iterates_sources_not_hardcoding_ultra_librarian():
    # Owner 2026-07-23: don't always use Ultra Librarian - try each visible source IN ORDER until one
    # actually offers the requested format (+ its 3D). The generated machine falls through sources.
    js = build_driver_js("digikey", ["kicad"])
    low = js.lower()
    assert "tryprovider" in low  # a per-source attempt iterated over the present providers
    assert "trying the next source" in low  # a source lacking the format falls through to the next
    # it still keys the format off the stable data-original label + selects the STEP 3D radio
    assert "data-original" in js and "step" in low
