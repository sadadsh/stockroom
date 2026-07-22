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
    "report('start',true,'DigiKey lists the symbol, footprint and 3D model together. Download them and they attach here.');"
    # DigiKey renders the CAD section title as a <div> (not a heading), so match by the section's
    # own text across div/span/anchors (skipping our overlay), and use element.scrollIntoView -
    # which scrolls DigiKey's custom scroll container (window.scrollTo does not move it).
    "function findCad(){try{"
    "var sels=['#cad-models','[data-testid=\"cad-models\"]','#eda-models'];"
    "for(var i=0;i<sels.length;i++){var s=document.querySelector(sels[i]);if(s)return s;}"
    "var ov=document.getElementById('__stockroom_overlay__');"
    "var nodes=document.querySelectorAll('a,div,span,h1,h2,h3,h4,h5,h6');"
    "for(var j=0;j<nodes.length;j++){var n=nodes[j];if(ov&&ov.contains(n))continue;if(n.children.length>3)continue;"
    "var t=(n.textContent||'').trim().toLowerCase();"
    "if(t==='cad models'||t==='eda/cad models'||t==='eda models'||t.indexOf('pcb symbol, footprint')>=0){return n;}}"
    "}catch(e){}return null;}"
    "var tries=0;function tick(){tries++;var el=findCad();"
    "if(el){try{el.scrollIntoView({behavior:'smooth',block:'center'});}catch(e){}"
    "try{el.style.outline='2px solid #5fd39a';el.style.outlineOffset='4px';}catch(e){}"
    "report('cad',true,'Download the symbol, footprint and 3D model from this CAD Models section.');return;}"
    "if(tries<12){setTimeout(tick,900);}"
    "else{report('cad',false,'Open the EDA / CAD Models section on this page to download the symbol, footprint and 3D model.');}}"
    "setTimeout(tick,700);"
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
