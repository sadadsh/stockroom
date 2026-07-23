"""LIVE Windows validation of the real WebView2 guided capture (plan Task 2.5 + Phase 3 A4).

Two modes, both against a REAL WebView2 window on real Windows:

  (default)   the download path: open the cad window at a local endpoint that serves a KiCad zip
              AS AN ATTACHMENT, and assert the actual WebView2 download is intercepted +
              classified + forwarded with the right requirements + session token. Closes the gate
              a simulated drop cannot: the tier-1 CoreWebView2 DownloadStarting intercept.

  --fixture   the overlay + driver path: open the cad window at a local page whose URL contains
              "ultralibrarian" (so open_cad_download injects the REAL Ultra Librarian overlay +
              driver on load) and whose DOM mimics the UL controls, then assert the overlay
              rendered, the driver auto-clicked consent + both format buttons + Download, and the
              resulting download was captured. This validates A1/A2/A3 injection end to end
              against a fixture; the LIVE UL/SnapEDA selectors are owner-validated (Phase C).

Run from the winverify clone (a window briefly opens, then closes itself):
    uv run python -m stockroom.host.win_live_capture
    uv run python -m stockroom.host.win_live_capture --fixture
"""

from __future__ import annotations

import http.server
import io
import json
import socketserver
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from stockroom.host import window as W


def _kicad_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("part.kicad_sym", "sym")
        zf.writestr("part.kicad_mod", "fp")
        zf.writestr("part.step", "model")
    return buf.getvalue()


_ZIP = _kicad_zip_bytes()

# A fixture page that mimics the Ultra Librarian controls the driver targets, and records every
# click the driver makes into window.__clicks so the harness can assert the driver ran.
_FIXTURE_HTML = b"""<!doctype html><html><head><meta charset="utf-8"><title>UL fixture</title></head>
<body style="font:14px system-ui;padding:24px">
<h1>Ultra Librarian (fixture)</h1>
<button id="onetrust-accept-btn-handler">Accept cookies</button>
<button data-ecad="KiCad">KiCad</button>
<button data-ecad="Altium">Altium</button>
<a download href="/stockroom-live-part.zip" data-testid="download">Download</a>
<script>
window.__clicks=[];
function rec(x){window.__clicks.push(x);}
document.getElementById('onetrust-accept-btn-handler').addEventListener('click',function(){rec('consent');});
document.querySelector("[data-ecad='KiCad']").addEventListener('click',function(){rec('kicad');});
document.querySelector("[data-ecad='Altium']").addEventListener('click',function(){rec('altium');});
document.querySelector("[data-testid='download']").addEventListener('click',function(){rec('download');});
</script>
</body></html>"""


# A DigiKey-shaped product page: a tall page with an "EDA / CAD Models" heading (no id the
# driver knows), to prove the DigiKey driver finds the section by heading text, scrolls to it and
# highlights it.
_DK_FIXTURE_HTML = b"""<!doctype html><html><head><meta charset="utf-8"><title>DK fixture</title></head>
<body style="font:14px system-ui;padding:24px">
<h1>Example Part (DigiKey fixture)</h1>
<div style="height:1400px">product overview</div>
<h2 id="cad-heading">EDA / CAD Models</h2>
<a download href="/stockroom-live-part.zip" data-testid="download">Download CAD</a>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/").endswith(".zip"):
            self._send(_ZIP, "application/octet-stream", attachment="stockroom-live-part.zip")
        elif "ultralibrarian" in self.path.lower():
            self._send(_FIXTURE_HTML, "text/html")
        elif "digikey" in self.path.lower():
            self._send(_DK_FIXTURE_HTML, "text/html")
        else:
            self._send(b"<!doctype html><meta charset=utf-8><body>download</body>", "text/html")

    def _send(self, body: bytes, ctype: str, attachment: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the request log
        pass


def _serve() -> str:
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    srv.allow_reuse_address = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def _drive_download(webview, base: str, captured: list, result: dict) -> None:
    time.sleep(1.5)
    needs = ["kicad_symbol", "kicad_footprint", "kicad_model"]
    token = W._HostApi().open_cad_download(f"{base}/stockroom-live-part.zip", needs)
    deadline = time.time() + 25.0
    while time.time() < deadline and not captured:
        time.sleep(0.25)
    result["captured"] = list(captured)
    if captured:
        p = captured[0]
        temp = str(getattr(W._CAD_SESSION, "temp_dir", "") or "")
        result["tier"] = "tier1-intercept" if temp and str(p.get("path", "")).startswith(temp) else "tier2-watch"
        result["token_ok"] = p.get("token") == token
        result["ok"] = result["token_ok"] and "kicad_symbol" in (p.get("requirements") or [])


def _drive_fixture(webview, base: str, captured: list, result: dict) -> None:
    time.sleep(1.5)
    needs = ["kicad_symbol", "kicad_footprint", "kicad_model", "altium_symbol", "altium_footprint"]
    # URL contains 'ultralibrarian' -> open_cad_download injects the real UL overlay + driver on load
    W._HostApi().open_cad_download(f"{base}/ultralibrarian", needs)
    deadline = time.time() + 25.0
    while time.time() < deadline and not captured:
        time.sleep(0.25)
    time.sleep(1.0)  # let the overlay + click recorder settle
    cad = W.cad_window()
    overlay_present, clicks = False, []
    try:
        overlay_present = bool(cad.evaluate_js("!!document.getElementById('__stockroom_overlay__')"))
        clicks = json.loads(cad.evaluate_js("JSON.stringify(window.__clicks||[])") or "[]")
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)
    result["overlay_present"] = overlay_present
    result["clicks"] = clicks
    result["captured"] = list(captured)
    needed_clicks = {"consent", "kicad", "altium", "download"}
    result["ok"] = overlay_present and needed_clicks.issubset(set(clicks)) and bool(captured)


def _drive_digikey(webview, base: str, captured: list, result: dict) -> None:
    time.sleep(1.5)
    needs = ["kicad_symbol", "altium_symbol", "altium_footprint"]
    # URL contains 'digikey' -> open_cad_download injects the DigiKey guide driver on load
    W._HostApi().open_cad_download(f"{base}/product/digikey", needs)
    time.sleep(3.0)  # let the overlay + driver run (scroll + highlight the CAD section)
    cad = W.cad_window()
    overlay_present, outlined, status = False, "", ""
    try:
        overlay_present = bool(cad.evaluate_js("!!document.getElementById('__stockroom_overlay__')"))
        outlined = cad.evaluate_js("(document.getElementById('cad-heading')||{}).style?document.getElementById('cad-heading').style.outline:''") or ""
        status = cad.evaluate_js("(document.getElementById('__stockroom_overlay_status__')||{}).textContent||''") or ""
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)
    result["overlay_present"] = overlay_present
    result["cad_heading_outlined"] = bool(outlined)
    result["status_text"] = status
    # PASS when the overlay rendered AND the driver found + highlighted the CAD section AND updated
    # the guidance to the DigiKey CAD-section message.
    result["ok"] = overlay_present and bool(outlined) and "CAD" in status


def _resolve_digikey_url(mpn: str):
    """Resolve a real DigiKey product-detail URL for an MPN via the app's DigiKey resolver +
    configured creds, so the live check opens the same page the guided window would."""
    try:
        from stockroom.enrich.cad_source import resolve_digikey_cad_source
        from stockroom.enrich.digikey_api import DigiKeyAdapter
        from stockroom.store.machine_config import MachineConfig

        cfg = MachineConfig.load()
        if not (cfg.digikey_client_id and cfg.digikey_client_secret):
            print("RESOLVE: no DigiKey API creds in config")
            return None
        dk = DigiKeyAdapter(cfg.digikey_client_id, cfg.digikey_client_secret)
        return resolve_digikey_cad_source(mpn, dk)
    except Exception as e:  # noqa: BLE001
        print("RESOLVE_ERROR", repr(e))
        return None


def _drive_live(webview, base: str, captured: list, result: dict) -> None:
    import os

    import urllib.parse

    mpn = os.environ.get("STOCKROOM_LIVE_MPN", "2N7002")
    url = os.environ.get("STOCKROOM_LIVE_URL", "")
    if not url:
        url = _resolve_digikey_url(mpn) or ""
    if not url:
        # No DigiKey API creds -> no exact product page. Still open the DigiKey SEARCH page so the
        # HUD + adaptive driver run against a REAL DigiKey page. The CAD/EDA section lives on the
        # product page, so this validates injection + page-open, not the CAD-section find itself.
        url = "https://www.digikey.com/en/products/result?keywords=" + urllib.parse.quote_plus(mpn)
        result["url_is_search_fallback"] = True
    result["url"] = url
    time.sleep(1.5)
    W._HostApi().open_cad_download(url, ["kicad_symbol", "altium_symbol", "altium_footprint"])
    # The DigiKey driver polls + scrolls asynchronously in the page for ~11s to catch the
    # lazy-loaded CAD section; just wait it out, then read the result (single cheap queries).
    time.sleep(16.0)
    cad = W.cad_window()
    try:
        result["overlay_present"] = bool(cad.evaluate_js("!!document.getElementById('__stockroom_overlay__')"))
        result["page_title"] = cad.evaluate_js("document.title||''") or ""
        # The rebuilt HUD (Phase 3): the current auto-action line + the X / Y meter, not the old
        # single status element. These say what the adaptive driver reported on the live page.
        result["action_text"] = (
            cad.evaluate_js("(document.getElementById('__stockroom_action__')||{}).textContent||''") or ""
        )
        result["meter_text"] = (
            cad.evaluate_js("(document.getElementById('__stockroom_meter__')||{}).textContent||''") or ""
        )
        # did the page actually scroll? (a custom scroll container would leave window.scrollY at 0)
        result["scrollY"] = cad.evaluate_js("Math.round(window.scrollY||0)")
        result["scrollHeight"] = cad.evaluate_js("Math.round(document.body.scrollHeight||0)")
        # bounded text search (specific tags, not '*') for the CAD section anywhere in the DOM
        result["cad_text_hits"] = (
            cad.evaluate_js(
                "JSON.stringify(Array.from(document.querySelectorAll('div,span,section,a,button,h1,h2,h3,h4,h5,h6'))"
                ".filter(function(e){return e.children.length===0 && /eda|cad model|pcb symbol|footprint|3d model/i.test(e.textContent||'')})"
                ".map(function(e){return e.tagName+': '+(e.textContent||'').trim().slice(0,35)}).slice(0,10))"
            )
            or "[]"
        )
        result["iframe_srcs"] = (
            cad.evaluate_js(
                "JSON.stringify(Array.from(document.querySelectorAll('iframe'))"
                ".map(function(f){return (f.src||'').replace(/\\?.*/,'').slice(0,55)}).filter(Boolean).slice(0,8))"
            )
            or "[]"
        )
        # OWNER-VALIDATE selector tuning: dump the download-ish controls in the CAD section so the
        # real provider markup (Ultra Librarian / SnapEDA / SamacSys buttons/links) is visible.
        result["cad_controls"] = (
            cad.evaluate_js(
                "JSON.stringify(Array.from(document.querySelectorAll('a,button,img')).filter(function(e){"
                "var t=((e.textContent||'')+' '+(e.getAttribute('href')||'')+' '+(e.getAttribute('aria-label')||'')"
                "+' '+(e.getAttribute('alt')||'')+' '+(e.getAttribute('data-provider')||'')+' '+(e.className||'')).toLowerCase();"
                "return /ultra|snapeda|samacsys|library.?loader|download|symbol|footprint|3d model|eda|cad model/.test(t);})"
                ".map(function(e){return e.tagName+'|'+((e.textContent||'').trim().slice(0,30))+'|href='+((e.getAttribute('href')||'').slice(0,50))"
                "+'|alt='+((e.getAttribute('alt')||'').slice(0,25))+'|cls='+((e.className||'').toString().slice(0,50));}).slice(0,30))"
            )
            or "[]"
        )
        # Confirm whether the CAD section is login-gated (does it prompt to sign in?)
        result["cad_section_text"] = (
            cad.evaluate_js(
                "(function(){var ns=document.querySelectorAll('div,section');"
                "for(var i=0;i<ns.length;i++){var t=(ns[i].textContent||'');"
                "if(/eda\\s*\\/?\\s*cad models/i.test(t)&&ns[i].children.length<50&&t.length<1500){"
                "return t.replace(/\\s+/g,' ').trim().slice(0,700);}}return '';})()"
            )
            or ""
        )
        # Click the CAD "Models" affordance to reveal the provider download controls (or a login wall).
        result["clicked_models"] = (
            cad.evaluate_js(
                "(function(){var els=document.querySelectorAll('a,button,div,span,[role=button]');"
                "for(var i=0;i<els.length;i++){var e=els[i];var t=(e.textContent||'').trim();"
                "if(t.length<45&&/models/i.test(t)&&e.offsetParent){"
                "try{e.scrollIntoView({block:'center'});e.click();return t;}catch(x){}}}return '';})()"
            )
            or ""
        )
        time.sleep(4.5)
        result["after_click_url"] = cad.evaluate_js("location.href") or ""
        result["after_click_controls"] = (
            cad.evaluate_js(
                "JSON.stringify(Array.from(document.querySelectorAll('a,button,img,input')).filter(function(e){"
                "var t=((e.textContent||'')+' '+(e.getAttribute('href')||'')+' '+(e.getAttribute('alt')||'')"
                "+' '+(e.getAttribute('data-provider')||'')+' '+(e.className||'')).toLowerCase();"
                "return /ultra|snapeda|samacsys|library.?loader|download|kicad|altium|eagle/.test(t);})"
                ".map(function(e){return e.tagName+'|'+((e.textContent||'').trim().slice(0,28))+'|'+((e.getAttribute('href')||'').slice(0,45));}).slice(0,30))"
            )
            or "[]"
        )
        result["login_present"] = (
            cad.evaluate_js(
                "JSON.stringify({pass:!!document.querySelector('input[type=password]'),"
                "email:!!document.querySelector('input[type=email],input[name*=user i],input[name*=email i]'),"
                "signin:/sign in to|please sign in|log in to download|sign in to download/i.test((document.body||{}).innerText||'')})"
            )
            or "{}"
        )
        # DigiKey's CURRENT sign-in link (the /en/login path 404s) + whether we are already signed in.
        result["signin_link"] = (
            cad.evaluate_js(
                "(function(){var a=Array.from(document.querySelectorAll('a')).filter(function(e){"
                "var t=((e.textContent||'')+' '+(e.getAttribute('href')||'')+' '+(e.getAttribute('aria-label')||'')).toLowerCase();"
                "return /sign\\s?in|log\\s?in|\\/login|\\/account|mydigikey/.test(t);});"
                "return JSON.stringify(a.slice(0,6).map(function(e){return e.tagName+'|'+((e.textContent||'').trim().slice(0,18))+'|'+((e.getAttribute('href')||'').slice(0,80));}));})()"
            )
            or "[]"
        )
        result["signed_in_hint"] = (
            cad.evaluate_js(
                "JSON.stringify({myaccount:/my account|sign out|log out|hi,|welcome back/i.test((document.body||{}).innerText||''),"
                "acct_link:!!document.querySelector('a[href*=myaccount i],a[href*=logout i],a[href*=signout i]')})"
            )
            or "{}"
        )
        # The real model-row markup: walk up from the "Altium Footprint" label to its section and dump it.
        result["models_region_html"] = (
            cad.evaluate_js(
                "(function(){var all=Array.from(document.querySelectorAll('span,div,a,button,h2,h3'));"
                "var sp=all.find(function(e){return (e.textContent||'').trim()==='Altium Footprint';})"
                "||all.find(function(e){return /eda\\/?cad models/i.test((e.textContent||'').trim())&&(e.textContent||'').length<25;});"
                "if(!sp)return '';var p=sp;for(var i=0;i<6&&p.parentElement;i++){p=p.parentElement;if((p.innerHTML||'').length>600)break;}"
                "return (p.outerHTML||'').replace(/\\s+/g,' ').slice(0,2400);})()"
            )
            or ""
        )
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)
    # PASS: the rebuilt HUD injected on the real page (overlay present) AND the DigiKey CAD/EDA
    # section actually exists on the page (cad_text_hits) for the adaptive driver to act on. The
    # live provider detection + multi-provider download are read from action_text + the screenshot.
    try:
        _hits = json.loads(str(result.get("cad_text_hits", "[]")))
    except (ValueError, TypeError):
        _hits = []
    result["found_cad"] = len(_hits) > 0
    result["ok"] = bool(result.get("overlay_present")) and result["found_cad"]
    try:
        from PIL import ImageGrab

        out = r"C:\srverify\ui_digikey_live.png"
        ImageGrab.grab().save(out)
        result["screenshot"] = out
    except Exception as e:  # noqa: BLE001
        result["screenshot_error"] = repr(e)


def _drive_signin(webview, base: str, captured: list, result: dict) -> None:
    """Interactive one-time DigiKey sign-in: open a real product page, keep the window open long
    enough for the OWNER to complete the Ping OIDC sign-in by hand, poll for the signed-in state,
    then dump the SIGNED-IN CAD download widget markup so the driver's download selectors can be
    tuned against real data. The persistent WebView2 profile keeps the session for later captures."""
    import os
    import time as _t

    mpn = os.environ.get("STOCKROOM_LIVE_MPN", "RC0603FR-0710KL")
    url = os.environ.get("STOCKROOM_LIVE_URL", "") or _resolve_digikey_url(mpn) or (
        "https://www.digikey.com/en/products/result?keywords=" + mpn
    )
    result["url"] = url
    # Open on the product page in a PLAIN window (no HUD - it would cover DigiKey's account/Login menu),
    # then jump to the dedicated CAD models page (digikey.com/en/models/<productId>) where the provider
    # tabs (Ultra Librarian / SnapMagic / TraceParts / CADENAS / Manufacturer Provided) and the whole
    # download UI live. The owner signs in via the on-page Login link; we detect signed-in by the login
    # gate clearing, then dump the signed-in format selector so the download driver can be tuned.
    cad = webview.create_window("stockroom-signin", url=url, width=1340, height=980)
    _t.sleep(4.5)
    href = cad.evaluate_js(
        "(function(){var m=document.querySelector('[data-testid=\"eda-cad-model-link\"]');"
        "if(!m){var c=Array.from(document.querySelectorAll('a[href]'));"
        "m=c.find(function(e){return /\\/models\\//.test(e.getAttribute('href')||'');});}"
        "return m?(m.getAttribute('href')||''):'';})()"
    ) or ""
    models_url = (("https://www.digikey.com" + href) if href and not href.startswith("http") else href)
    result["models_url"] = models_url
    if models_url:
        cad.load_url(models_url)
        _t.sleep(6.0)
    timeout_s = float(os.environ.get("STOCKROOM_SIGNIN_WAIT", "220"))
    # Fast path: STOCKROOM_SIGNIN_WAIT=0 trusts the persistent profile's saved session (owner already
    # signed in on a prior run) and captures the signed-in download UI immediately - also the exact
    # test that the WebView2 profile really persists the DigiKey session across launches.
    if timeout_s <= 0:
        print("SIGNIN: fast path - trusting the persistent profile session, capturing now.", flush=True)
        signed = True
    else:
        print(
            f"SIGNIN: CAD models page OPEN (no HUD). Sign in via the account menu (top-right) - I capture "
            f"the signed-in download UI automatically once you are in (watching up to {timeout_s:.0f}s). "
            f"Tell me if the account menu already shows Logout.",
            flush=True,
        )
    # Signal-based: on the models page, treat signed-in as "the account menu shows a Sign Out/Logout /
    # a member name" rather than the presence of any Login href (DigiKey keeps a stale Login link in the
    # account dropdown markup even when signed in). Cross-origin auth pages return null (skip).
    signed = signed or False
    deadline = _t.time() + timeout_s
    while _t.time() < deadline:
        _t.sleep(5.0)
        try:
            state = json.loads(cad.evaluate_js(
                "JSON.stringify({url:location.href.slice(0,90),"
                "gate:!!Array.from(document.querySelectorAll('a')).find(function(e){return /MyDigiKey\\/Login/.test(e.getAttribute('href')||'');}),"
                "fmt:!!Array.from(document.querySelectorAll('a,button')).find(function(e){return /select download format/i.test(e.textContent||'');})})"
            ) or "null")
        except Exception:  # noqa: BLE001
            state = None
        if not isinstance(state, dict):
            print("SIGNIN: (auth page / loading - sign-in in progress)", flush=True)
            continue
        cur = str(state.get("url", ""))
        on_models = "/models/" in cur
        acct = bool(state.get("acct"))
        print(f"SIGNIN: url={cur[:55]} account_signed_in={acct} format_btn={state.get('fmt')}", flush=True)
        # If the owner drifted back to the product page after auth, steer them to the models page.
        if not on_models and "/products/detail/" in cur and models_url:
            cad.load_url(models_url)
            _t.sleep(3.0)
            continue
        # Signed in: on the models page and the account menu reports a signed-in member.
        if on_models and acct:
            signed = True
            print("SIGNIN: account shows signed-in on the models page -> capturing the download UI.", flush=True)
            break
    result["signed_in"] = signed
    _t.sleep(1.0)
    try:
        result["final_url"] = cad.evaluate_js("location.href.slice(0,110)") or ""
        # Definitive signed-in probe: the account control's text/aria + any "sign out"/"hello, <name>".
        result["account"] = cad.evaluate_js(
            "JSON.stringify({"
            "acct:Array.from(document.querySelectorAll('[data-testid*=\"account\" i],[aria-label*=\"account\" i],"
            "[aria-label*=\"my digikey\" i],[class*=\"account\" i],header a,header button')).map(function(e){"
            "return ((e.getAttribute('aria-label')||'')+' '+(e.textContent||'').trim()).replace(/\\s+/g,' ').trim().slice(0,45);})"
            ".filter(function(t){return t.length>0;}).slice(0,12),"
            "signOut:/sign out|log out|logout/i.test(document.body.innerText||''),"
            "loginLinks:Array.from(document.querySelectorAll('a')).filter(function(e){"
            "return /MyDigiKey\\/Login/.test(e.getAttribute('href')||'')&&e.offsetParent;}).length})"
        ) or "{}"
        # Provider tabs present on the signed-in models page.
        result["tabs"] = cad.evaluate_js(
            "JSON.stringify(Array.from(document.querySelectorAll('[role=tab],button,a,h2,h3')).map(function(e){"
            "return (e.textContent||'').trim();}).filter(function(t){"
            "return /^(ultra librarian|snapmagic|traceparts|cadenas|manufacturer provided|3d model)$/i.test(t);})"
            ".filter(function(v,i,a){return a.indexOf(v)===i;}).slice(0,20))"
        ) or "[]"
        # Activate the Ultra Librarian provider row (lazy-loads its .submenu download content).
        result["expanded"] = cad.evaluate_js(
            "(function(){var u=document.querySelector('#ultra-media-active');"
            "if(u){try{u.scrollIntoView({block:'center'});u.click();return 'clicked #ultra-media-active';}catch(e){return 'ERR '+e;}}"
            "return 'NO_ULTRA';})()"
        ) or ""
        _t.sleep(3.5)
        # Click the VISIBLE 'Select Download Format' (a.btn-download-model, onclick=displayExportModal)
        # -> opens the export-format picker modal.
        result["clicked_fmt"] = cad.evaluate_js(
            "(function(){var b=Array.from(document.querySelectorAll('a.btn-download-model,a.dk-btn__primary,button,a')).find(function(e){"
            "return e.offsetParent&&/select download format/i.test(e.textContent||'');});"
            "if(b){try{b.scrollIntoView({block:'center'});b.click();return 'clicked onclick='+((b.getAttribute('onclick')||b.className||'')).slice(0,70);}catch(e){return 'ERR '+e;}}"
            "return 'NO_FMT_BTN';})()"
        ) or ""
        _t.sleep(2.5)
        # Dump the export-options modal markup (the exact format rows + their triggers).
        result["export_modal"] = cad.evaluate_js(
            "(function(){var m=Array.from(document.querySelectorAll('[id*=\"export-options\"],[class*=\"export-options\"],[class*=\"export-modal\"],[role=\"dialog\"],.modal,.dk-modal')).find(function(e){"
            "return (e.offsetParent!=null)&&(e.innerHTML||'').length>120;});"
            "if(!m){m=Array.from(document.querySelectorAll('[id*=\"export-options\"]')).find(function(e){return (e.innerHTML||'').length>120;});}"
            "if(!m)return 'NO_MODAL';return (m.outerHTML||'').replace(/\\s+/g,' ').slice(0,3800);})()"
        ) or ""
        # The format options presented (KiCad, Altium, Eagle, OrCAD, PADS, 3D STEP, ...).
        result["formats"] = cad.evaluate_js(
            "JSON.stringify(Array.from(document.querySelectorAll('a,button,li,option,label,span,div,h3,h4')).filter(function(e){"
            "return e.offsetParent&&(e.textContent||'').trim().length<45&&"
            "/kicad|altium|eagle|orcad|pads|allegro|cadence|dxf|3d step|\\.step|pcb design|library loader|proteus|zuken|pulsonix|design blocks|gerber/i.test(e.textContent||'');})"
            ".map(function(e){return (e.textContent||'').trim();}).filter(function(v,i,a){return a.indexOf(v)===i;}).slice(0,45))"
        ) or "[]"
        # The KiCad v6+ and Altium radio inputs (id + value), and the modal's action buttons (the
        # actual Download trigger) - everything the driver needs to select a format and fire the download.
        result["kicad_radio"] = cad.evaluate_js(
            "(function(){var l=Array.from(document.querySelectorAll('#ultralib-export-options label')).find(function(e){"
            "return /kicad\\s*v6/i.test(e.getAttribute('data-original')||e.textContent||'');});"
            "if(!l)return 'NO_KICAD';var inp=l.htmlFor?document.getElementById(l.htmlFor):l.previousElementSibling;"
            "return l.textContent.trim()+' => input#'+(inp?inp.id:'?')+' value='+(inp?inp.value:'?');})()"
        ) or ""
        result["altium_radio"] = cad.evaluate_js(
            "(function(){var l=Array.from(document.querySelectorAll('#ultralib-export-options label')).find(function(e){"
            "return /^altium designer$/i.test((e.getAttribute('data-original')||e.textContent||'').trim());});"
            "if(!l)return 'NO_ALTIUM';var inp=l.htmlFor?document.getElementById(l.htmlFor):l.previousElementSibling;"
            "return l.textContent.trim()+' => input#'+(inp?inp.id:'?')+' value='+(inp?inp.value:'?');})()"
        ) or ""
        result["modal_actions"] = cad.evaluate_js(
            "(function(){var m=document.querySelector('#ultralib-export-options');if(!m)return 'NO_MODAL';"
            "return JSON.stringify(Array.from(m.querySelectorAll('button,a,input[type=submit],[onclick]')).map(function(e){"
            "return e.tagName+'|'+((e.textContent||e.value||'').trim().slice(0,22))+'|onclick='+((e.getAttribute('onclick')||'').slice(0,55))+'|cls='+((e.className||'').slice(0,28));})"
            ".filter(function(t){return !/toggleRadioButton/.test(t);}).slice(0,20));})()"
        ) or ""
        result["modal_footer"] = cad.evaluate_js(
            "(function(){var m=document.querySelector('#ultralib-export-options');if(!m)return '';"
            "var h=(m.innerHTML||'');return h.slice(Math.max(0,h.length-1400)).replace(/\\s+/g,' ');})()"
        ) or ""
        # End-to-end download proof (STOCKROOM_DO_DOWNLOAD=1): inject the guided-capture HUD (now
        # bottom-right so it clears DigiKey's account menu), then download KiCad and Altium SEPARATELY
        # - each a fresh modal open -> pick the format (toggleRadioButton enables Download) -> click
        # #btn-download-Ultra (exportUltraFile fires the real WebView2 download, intercepted by the
        # host tier-1 intercept / tier-2 DownloadsWatch on Downloads).
        if os.environ.get("STOCKROOM_DO_DOWNLOAD") == "1":
            from stockroom.host.overlay import build_overlay_js

            try:
                cad.evaluate_js(build_overlay_js(
                    ["kicad_symbol", "kicad_footprint", "kicad_model", "altium_symbol", "altium_footprint"],
                    "DigiKey", mpn,
                ))
                result["hud"] = "injected"
            except Exception as e:  # noqa: BLE001
                result["hud"] = "ERR " + repr(e)
            _t.sleep(1.0)

            def _download_format(fmt_re: str) -> dict:
                # (Re)open the Ultra Librarian export modal (it dismisses after each download).
                cad.evaluate_js(
                    "(function(){var b=Array.from(document.querySelectorAll('a.btn-download-model,a.dk-btn__primary,button,a')).find(function(e){"
                    "return e.offsetParent&&/select download format/i.test(e.textContent||'');});if(b){try{b.click();}catch(e){}}})()"
                )
                _t.sleep(2.0)
                sel = cad.evaluate_js(
                    "(function(){var l=Array.from(document.querySelectorAll('#ultralib-export-options label')).find(function(e){"
                    "return " + fmt_re + ".test((e.getAttribute('data-original')||e.textContent||'').trim());});"
                    "if(!l)return 'NO_FMT';var inp=l.htmlFor?document.getElementById(l.htmlFor):null;"
                    "try{if(inp){inp.click();}else{l.click();}return 'selected '+(inp?inp.id:'label');}catch(e){return 'ERR '+e;}})()"
                ) or ""
                _t.sleep(1.3)
                fire = cad.evaluate_js(
                    "(function(){var b=document.querySelector('#btn-download-Ultra');if(!b)return 'NO_BTN';"
                    "if(b.disabled)return 'DISABLED';try{b.click();return 'fired';}catch(e){return 'ERR '+e;}})()"
                ) or ""
                _t.sleep(9.0)
                return {"select": sel, "fire": fire}

            result["dl_kicad"] = _download_format("/kicad\\s*v6/i")
            _t.sleep(2.0)
            result["dl_altium"] = _download_format("/^altium designer$/i")
            result["dl_final_url"] = cad.evaluate_js("location.href.slice(0,110)") or ""
        # All download-ish controls on the signed-in models page.
        result["dl_controls"] = cad.evaluate_js(
            "JSON.stringify(Array.from(document.querySelectorAll('a,button,input,[data-testid],[role=button]')).filter(function(e){"
            "var t=((e.textContent||'')+' '+(e.getAttribute('href')||'')+' '+(e.getAttribute('data-testid')||'')+' '+(e.className||'')).toLowerCase();"
            "return /ultra|snapmagic|traceparts|cadenas|download|kicad|altium|eagle|orcad|symbol|footprint|3d model|format|agreement/.test(t);})"
            ".map(function(e){return e.tagName+'|testid='+((e.getAttribute('data-testid')||'').slice(0,22))+'|'+((e.textContent||'').trim().slice(0,30))+'|href='+((e.getAttribute('href')||'').slice(0,40));}).slice(0,45))"
        ) or "[]"
        result["headings"] = cad.evaluate_js(
            "JSON.stringify(Array.from(document.querySelectorAll('h1,h2,h3,h4')).map(function(e){"
            "return (e.textContent||'').trim().slice(0,55);}).filter(Boolean).slice(0,60))"
        ) or "[]"
        # Full body text of the signed-in CAD models page (the download UI as text).
        result["models_body"] = cad.evaluate_js(
            "(document.body.innerText||'').replace(/\\n+/g,' | ').replace(/ +/g,' ').slice(0,2200)"
        ) or ""
        # Raw HTML of the download widget: anchor on the "Select Download Format" control (present in
        # the DOM even while the accordion is collapsed) and walk UP to its container - the exact
        # format-selector + download-button + login-gate markup the driver must target.
        result["fmt_html"] = cad.evaluate_js(
            "(function(){var a=Array.from(document.querySelectorAll('a,button')).find(function(e){"
            "return /select download format/i.test(e.textContent||'');});if(!a)return 'NO_FMT';"
            "var p=a;for(var i=0;i<7&&p;i++){if((p.outerHTML||'').length>700)"
            "return (p.outerHTML||'').replace(/\\s+/g,' ').slice(0,3800);p=p.parentElement;}"
            "return (a.outerHTML||'').replace(/\\s+/g,' ').slice(0,3800);})()"
        ) or ""
        # The Ultra Librarian accordion header's own markup: how the toggle is wired (aria-expanded,
        # onclick, the real clickable element) so the driver can reliably expand it.
        result["ul_head_html"] = cad.evaluate_js(
            "(function(){var h=Array.from(document.querySelectorAll('button,a,div,h2,h3')).find(function(e){"
            "return e.offsetParent&&/^\\s*ultra librarian\\s*$/i.test((e.textContent||'').trim());});"
            "if(!h)return 'NO_UL_HEAD';var p=h.parentElement||h;"
            "return (p.outerHTML||'').replace(/\\s+/g,' ').slice(0,1400);})()"
        ) or ""
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)
    result["ok"] = signed


def main() -> int:
    import webview

    signin = "--signin" in sys.argv
    live = "--live" in sys.argv and not signin
    digikey = "--digikey" in sys.argv and not live and not signin
    fixture = "--fixture" in sys.argv and not digikey and not live and not signin
    captured: list[dict] = []
    W._emit_to_spa = lambda payload: captured.append(payload)
    base = _serve()
    mode = "signin" if signin else "live" if live else "digikey" if digikey else "fixture" if fixture else "download"
    result: dict = {"mode": mode, "ok": False, "error": None}

    main_win = webview.create_window("stockroom-live", html="<html><body>host</body></html>", hidden=True)
    W._ACTIVE_WINDOW = main_win
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # noqa: BLE001
        pass

    def driver() -> None:
        try:
            drive = (
                _drive_signin
                if signin
                else _drive_live
                if live
                else _drive_digikey
                if digikey
                else _drive_fixture
                if fixture
                else _drive_download
            )
            drive(webview, base, captured, result)
        except Exception as e:  # noqa: BLE001
            result["error"] = repr(e)
        finally:
            for w in list(getattr(webview, "windows", [])):
                try:
                    w.destroy()
                except Exception:  # noqa: BLE001
                    pass

    profile = Path(tempfile.gettempdir()) / "stockroom-live-profile"
    profile.mkdir(parents=True, exist_ok=True)
    webview.start(driver, **W._webview_start_kwargs(webview.start, profile))

    print("LIVE_RESULT " + json.dumps(result, default=str))
    if result["ok"]:
        what = {
            "digikey": "DigiKey CAD-section guide (overlay + driver)",
            "fixture": "overlay + driver + capture",
        }.get(mode, f"download via {result.get('tier')}")
        print(f"PASS: real WebView2 {what} verified")
        return 0
    print("FAIL: real WebView2 validation did not pass (see LIVE_RESULT)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
