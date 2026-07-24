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


def test_digikey_driver_verifies_the_selection_and_reacts_to_a_wrong_file():
    # Live 2026-07-23: the modal can open PRE-ARMED with a sticky prior selection (the persistent
    # profile restores it - the download button was already enabled 341ms in), and UL then served
    # its Altium+STEP bundle against a KiCad request. So the driver must not trust its clicks:
    # (1) pickVerified reads the modal's REAL selection state back (input.checked / aria-checked /
    # an active class), retries, and sweeps stale selections off before clicking Download; and
    # (2) a completed download of the WRONG format settles the await as 'wrongfile' immediately
    # (no watchdog wait) and the format is retried with the selection re-verified.
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "pickVerified" in js  # selection is verified against the DOM, not assumed from a click
    assert "isOn(" in js  # the readback: checked / aria-checked / active-class
    assert "'wrongfile'" in js  # a wrong-format completion is sensed and reacted to at once
    assert "aria-checked" in js  # custom toggles without a real input are still readable
    # the wrong-file path retries the same format once in place before refresh recovery
    assert "__retried" in js
    # Live 2026-07-23 (round 2): UL's async displayExportModal RE-RENDERS the format list and
    # restores its localStorage-sticky selection AFTER our clicks, then exportUltraFile reads
    # input:checked synchronously in the Download click chain. So the driver must (a) clear the
    # sticky keys so the re-render has nothing stale to restore - generically, ANY provider's
    # <prov>DownloadFormat* key, not a hardcoded UL pair - and (b) re-check the selection
    # SYNCHRONOUSLY in the same task as the Download click (atomic: a re-render cannot interpose),
    # re-picking reactively if it was wiped.
    assert "downloadformat" in js.lower()  # the generic sticky-key clear (any provider)
    assert "wiped" in js  # the wiped-selection sense + reactive re-pick before Download


def test_digikey_driver_scopes_every_control_to_the_provider_being_driven():
    # dkprobe 2026-07-23 (live DOM, ATMEGA328P-PU + USB4105-GF-A): every provider gets its OWN
    # modal and radio groups under one shared DigiKey system - and the names DIVERGE from the row
    # ids (row #snapmagic-media-active -> modal #snapeda-export-options + groups
    # snapeda-format-selection[-3d]; row #ultra-media-active -> modal #ultralib-export-options +
    # groups ultra-format-selection[-3d]). A document-wide control seek can drive the WRONG
    # provider's modal, so the format control, modal, selection verify, and download button are
    # all resolved per provider; the verify reads the SAME input[name=...]:checked the vendor's
    # export function reads; the vendor's own Clear Selection button resets stale state; and a
    # provider whose row only links out to the manufacturer's site is skipped fast.
    js = build_driver_js("digikey", ["kicad", "altium"])
    for token in (
        "ultralib-export-options",
        "snapeda-export-options",
        "traceparts-export-options",
        "mfr-export-options",
        "cadenas-export-options",
    ):
        assert token in js  # the provider tuple carries its exact modal id
    assert "-format-selection" in js  # verification via the vendor's own radio-group read
    assert "btn-clear-selection" in js  # the vendor's Clear Selection resets both groups
    assert "container-content" in js  # section-scoped fallback for the format control
    assert "externalOnly" in js  # a link-out-only provider row is sensed and skipped fast


def test_digikey_driver_falls_through_providers_before_refreshing():
    # The resilience ladder mirrors the human: a wrong file retries the SAME source once with the
    # selection re-verified; a second wrong file, an error toast, or a generation timeout moves to
    # the NEXT visible source; when every visible provider is exhausted WITHOUT the format - whether
    # a source genuinely lacks it OR the page loaded only empty provider skeletons - the bounded
    # refresh recovery reloads through the product page (live 2026-07-24: the Ultra Librarian
    # section came up as an unloaded skeleton, and the old immediate give-up stranded it).
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "fallthrough" in js  # error/timeout/second-wrongfile -> the next visible source
    # provider exhaustion ALWAYS routes to the bounded refresh recovery (no immediate hand-off that
    # stranded an empty-skeleton page); it still ends honestly after MAX_REFRESH via done(false)
    assert "if(pi>=present.length){recover(spec,done);return;}" in js
    assert "'wall'" in js  # a Cloudflare/login wall still hands off to the user immediately
    # Owner heuristic (2026-07-23): a SUCCESSFUL run's download STARTS within ~5s of the click
    # (observed +1.6s..+5.7s live). The host relays the real 'started' event; if nothing starts
    # within the start watchdog, the attempt is already dead - fail 'nostart' at once and fall
    # through, never wait out the 150s completion backstop on it.
    assert "'started'" in js and "'nostart'" in js and "START_WD" in js
    # ...but a heavy part's export can legitimately generate for 20-60s (live 2026-07-23, STM32:
    # the POST was still in flight when a hard 20s nostart killed and canceled it). When the
    # vendor's own downloading/generating indicator is visible (outside our overlay), the start
    # watchdog extends - bounded - instead of aborting a live generation.
    assert "senseBusy" in js and "slow generation" in js
    # A reloaded/renavigated models page comes up as an active-but-empty skeleton whose row
    # handlers bind late (live-dissected 2026-07-23): early clicks do nothing, a settled-page
    # click populates the section in ~3s. The driver knocks repeatedly (bounded), and on the
    # last knock calls the vendor's own displayExportModal directly; the control seek also
    # accepts an already-open provider modal.
    assert "__knock" in js
    assert "window.displayExportModal" in js  # the vendor-opener last-resort fallback


def test_digikey_reactor_is_event_driven_not_timed():
    # "React to what's happening live, no timers": stepping is MutationObserver-driven (until reacts
    # the instant the DOM satisfies a predicate); timers appear ONLY as never-hang watchdogs.
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "MutationObserver" in js and "requestAnimationFrame" in js  # event-driven, debounced
    assert "elementFromPoint" in js  # a real hit-test at the click moment, not a blind click
    assert "GEN_WD" in js  # the single watchdog is the only timer (a never-hang backstop)


def test_digikey_reactor_recovers_like_a_human_refresh_and_your_turn():
    # It never gets left on a hang: a stall/error re-navigates through the PRODUCT page (live
    # 2026-07-23: a reloaded models page never renders its provider controls again, so recovery
    # retraces the proven product -> models-link path; plain reload is only the fallback), bounded
    # so it can't loop; a Cloudflare / login wall hands off to the user via the overlay "Your Turn".
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "__SR_PRODUCT__" in js  # recovery retraces the proven product-page path
    assert "location.reload" in js and "MAX_REFRESH" in js  # bounded fallback refresh
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


def test_digikey_sensewall_detects_the_guest_download_limit_modal():
    # Live 2026-07-24 (THE root cause of "KiCad attached, Altium not"): browsing DigiKey as a
    # GUEST (not signed in) caps downloads at a small daily quota. The 1st download (KiCad) slips
    # under it; the 2nd (Altium) trips a "Download Speed Bump! ... you've hit today's guest limit
    # for downloads" modal with a Login button. senseWall must treat that modal as a wall so the
    # reactor hands off "Sign in" instead of silently retrying a download the quota will keep
    # blocking. Scoped to modal/dialog text (cheap), keyed on the quota wording.
    js = build_driver_js("digikey", ["kicad", "altium"])
    low = js.lower()
    assert "download speed bump" in low or "guest" in low
    assert "limit for downloads" in low or "guest download limit" in low or "guest limit" in low
    assert "role=dialog" in js or "modal" in low  # scans modal/dialog containers only


def test_digikey_sensewall_covers_the_two_step_digikey_login():
    # Live 2026-07-24: DigiKey's SSO login (auth.digikey.com, PingFederate) is TWO steps -
    # an EMAIL step with a Next button and NO password field, then a password step. The old
    # senseWall only saw a password-in-form, so on the email step it returned false and the
    # HUD wrongly said "Open the EDA / CAD Models section" while the user sat on a login page.
    # senseWall must treat the auth.digikey.com host as a wall (covers BOTH steps).
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "auth" in js and r"digikey\.com" in js  # the escaped auth-host regex
    assert "location.hostname" in js


def test_digikey_reactor_hands_off_the_wall_for_the_user_to_solve():
    # Owner 2026-07-24: the OS-level Turnstile auto-click only tripped Cloudflare's bot
    # detection (verify -> reset loop), so the driver NO LONGER clicks anything. When the
    # window opens onto (or hits) a login / Cloudflare wall, it hands off "Your Turn" and
    # WAITS for the USER to solve it before driving the models page - never a CAD-link hunt
    # on a wall page, and never a stashed rect for a host auto-click.
    js = build_driver_js("digikey", ["kicad", "altium"])
    # the hand-off names BOTH the sign-in and the Cloudflare verification the user finishes
    assert "sign-in" in js.lower() and "verification" in js.lower()
    assert "function drive()" in js
    # the wait POLLS senseWall on an interval, not a MutationObserver: a Cloudflare check that
    # clears in-place leaves the page settled with no further mutations, so a mutation-only
    # wait (until) would hang forever after the wall is gone (live 2026-07-24)
    assert "setInterval(function(){" in js
    assert "if(!senseWall())" in js
    # the your-turn hand-off is wired through the overlay action bridge
    assert ".action({needsUser:true" in js
    # the abandoned auto-click sensor is gone entirely (no rect stashed for the host)
    assert "__SR_CF_RECT__" not in js
    assert "cfRect" not in js


def test_digikey_done_message_is_honest_about_what_actually_landed():
    # Owner 2026-07-24: "why does it say downloaded?? it saying it downloaded should only say
    # download once the file lands." The reactor advanced through each format and reported
    # "All requested downloads are done." whether a format actually downloaded or was GIVEN UP
    # on (recover -> done, or "no source offers it" -> done). So a stalled/failed Altium rolled
    # up into "everything downloaded." The done callback must carry the real outcome, and the
    # final message must name what landed vs what could not.
    js = build_driver_js("digikey", ["kicad", "altium"])
    # the blanket optimistic message is gone
    assert "All requested downloads are done." not in js
    # the per-format done callback carries success/failure, and only a REAL completion is a win
    assert "done(true)" in js and "done(false)" in js
    # the aggregate reflects what actually landed vs what did not
    assert "missed" in js
    assert "could NOT" in js.lower() or "could not download" in js.lower()


def test_wall_clearance_never_hijacks_the_login_redirect_chain():
    # Live 2026-07-24: submitting the DigiKey sign-in makes the password field vanish
    # the instant the SSO redirect chain STARTS; recover() then refreshed to the product
    # URL immediately, aborting the chain before the session cookie landed - so every
    # login bounced straight back to sign-in. The wall-clear path must SETTLE first and
    # only refresh when this same document is still alive and still unwalled (a login
    # that navigated away died with the script; the re-injected reactor drives on).
    js = build_driver_js("digikey", ["kicad", "altium"])
    assert "setTimeout(function(){if(!senseWall())refresh();}" in js
    # the your-turn message covers signing in, not only captcha verification
    assert "Sign in" in js or "sign in" in js
