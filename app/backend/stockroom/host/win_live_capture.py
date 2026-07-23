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


def main() -> int:
    import webview

    live = "--live" in sys.argv
    digikey = "--digikey" in sys.argv and not live
    fixture = "--fixture" in sys.argv and not digikey and not live
    captured: list[dict] = []
    W._emit_to_spa = lambda payload: captured.append(payload)
    base = _serve()
    mode = "live" if live else "digikey" if digikey else "fixture" if fixture else "download"
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
                _drive_live
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
