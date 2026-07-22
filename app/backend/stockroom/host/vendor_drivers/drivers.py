"""Build the auto-click driver script injected into a vendor CAD page (Ultra Librarian /
SnapEDA). Pure string builder - no pywebview - so it imports and unit-tests on Linux; the
actual injection is host-side (window.py) on the cad window's `loaded` event.

The script is assembled per REQUESTED format so it only ever attempts what the part needs (a
KiCad-only capture never mentions Altium). EACH step runs in try/catch and reports its outcome
through `window.__STOCKROOM_OVERLAY__.report({step, ok, message})`; a step whose target is not
found degrades to a guidance message, never a dead stop or a throw.

Selectors are OWNER-VALIDATE: the live vendor pages are login-gated and change, so a Windows +
owner pass (Phase C, win_live_capture against the real pages) confirms them against the live DOM
and dates the confirmation. The fixture-based tests are the deterministic guard.
"""

from __future__ import annotations

import json

# OWNER-VALIDATE: confirm against the live pages (Phase C). First-guess selectors below.
_VENDORS: dict[str, dict] = {
    "ultralibrarian": {
        "label": "Ultra Librarian",
        "consent": ["#onetrust-accept-btn-handler", "[aria-label='accept cookies']"],
        "kicad": ["[data-ecad='KiCad']", "label[for*='KiCad']", "button[title*='KiCad']"],
        "altium": ["[data-ecad='Altium']", "label[for*='Altium']", "button[title*='Altium']"],
        "download": ["button.download", "[data-testid='download']", "a[download]"],
    },
    "snapeda": {
        "label": "SnapEDA",
        "consent": [".cookie-accept", "[aria-label='accept cookies']"],
        "kicad": ["a[href*='kicad']", "[data-format='kicad']", "button[title*='KiCad']"],
        "altium": ["a[href*='altium']", "[data-format='altium']", "button[title*='Altium']"],
        "download": ["a.download-button", "[data-testid='download']", "a[download]"],
    },
}

_HELPERS = (
    "function report(step,ok,msg){try{var o=window.__STOCKROOM_OVERLAY__;"
    "o&&o.report({step:step,ok:ok,message:msg});}catch(e){}}"
    "function click(sels){for(var i=0;i<sels.length;i++){"
    "var el=document.querySelector(sels[i]);if(el){el.click();return true;}}return false;}"
)


def _step(step: str, selectors: list[str], ok_msg: str, fail_msg: str) -> str:
    j = json.dumps
    return (
        f"try{{var _ok=click({j(selectors)});"
        f"report({j(step)},_ok,_ok?{j(ok_msg)}:{j(fail_msg)});}}"
        f"catch(e){{report({j(step)},false,{j(fail_msg)});}}"
    )


# DigiKey aggregates the SnapEDA / Ultra Librarian / SamacSys downloads on the product page
# (its "EDA / CAD Models" section) rather than behind format toggles, and needs no login to
# browse - so its driver GUIDES rather than force-clicks: it scrolls the CAD section into view
# and highlights it, then reports what to download. It finds the section by a few id selectors
# (OWNER-VALIDATE) but degrades to a heading-text match (cad / symbol / eda), so a DigiKey markup
# change never breaks it - no selector tuning required.
_DIGIKEY_DRIVER = (
    "function report(step,ok,msg){try{var o=window.__STOCKROOM_OVERLAY__;"
    "o&&o.report({step:step,ok:ok,message:msg});}catch(e){}}"
    "report('start',true,'DigiKey gathers the SnapEDA, Ultra Librarian and SamacSys downloads in one place.');"
    "try{"
    "var el=null,sels=['#cad-models','[data-testid=\"cad-models\"]','#eda-models','#ecad-models'];"
    "for(var i=0;i<sels.length;i++){el=document.querySelector(sels[i]);if(el)break;}"
    "if(!el){var hs=document.querySelectorAll('h2,h3,h4');"
    "for(var j=0;j<hs.length;j++){var t=(hs[j].textContent||'').toLowerCase();"
    "if(t.indexOf('cad')>=0||t.indexOf('symbol')>=0||t.indexOf('eda')>=0){el=hs[j];break;}}}"
    "if(el){el.scrollIntoView({behavior:'smooth',block:'center'});"
    "try{el.style.outline='2px solid #5fd39a';el.style.outlineOffset='4px';}catch(e){}"
    "report('cad',true,'Download the symbol, footprint and 3D model from this CAD Models section.');}"
    "else{report('cad',false,'Scroll to the EDA / CAD Models section and download the files.');}"
    "}catch(e){report('cad',false,'Scroll to the EDA / CAD Models section and download the files.');}"
)


def _digikey_driver_js() -> str:
    return f"(function(){{{_DIGIKEY_DRIVER}}})();"


def build_driver_js(vendor: str, formats: list[str]) -> str:
    key = (vendor or "").strip().lower()
    if key == "digikey":
        return _digikey_driver_js()
    spec = _VENDORS.get(key)
    if spec is None:
        # Guidance-only: never click anything, but tell the overlay so it can guide manually.
        return (
            "(function(){try{var o=window.__STOCKROOM_OVERLAY__;"
            "o&&o.report({step:'driver',ok:false,message:'No automation for this vendor; "
            "select KiCad and Altium and click Download.'});}catch(e){}})();"
        )
    j = json.dumps
    steps = [f"report({j('start')},true,{j(spec['label'] + ' guided capture')});"]
    steps.append(_step("consent", spec["consent"], "", "dismiss the cookie banner"))
    if "kicad" in formats:
        steps.append(_step("kicad", spec["kicad"], "KiCad selected", "pick KiCad"))
    if "altium" in formats:
        steps.append(_step("altium", spec["altium"], "Altium selected", "pick Altium"))
    steps.append(_step("download", spec["download"], "Download clicked", "click Download"))
    body = _HELPERS + "".join(steps)
    return f"(function(){{{body}}})();"
