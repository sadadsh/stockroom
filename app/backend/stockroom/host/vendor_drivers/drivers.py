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


# DigiKey serves the CAD files through its OWN "EDA / CAD Models" section (owner correction
# 2026-07-22: no navigation to a provider website), aggregating Ultra Librarian / SnapEDA /
# SamacSys there. So the driver is an ADAPTIVE STATE MACHINE, not guidance-only: dismiss consent,
# find the CAD section (KEEPING the live-validated div-text match + custom-scroll-container
# scrollIntoView - window.scrollTo does not move DigiKey's container), detect which providers
# DigiKey offers for THIS part in preference order (Ultra Librarian first as the most-complete
# default, then SnapEDA, then SamacSys), and open the preferred provider's download control - all
# guarded, reporting each step into the overlay, degrading a missing target to a guidance message.
#
# Per-part coverage VARIES, so `_DIGIKEY_PROVIDERS` is preference-ordered and Task 2 iterates the
# per-provider download sub-sequence across every present provider (the host CaptureSession dedups
# + accumulates, so combining providers is safe). Selectors are OWNER-VALIDATE against the live
# DigiKey + in-DigiKey provider markup (login-gated, changes); the resilient text/attr fallbacks
# and the fixture tests are the deterministic guard.
#
# Each provider entry: label + presence (selectors + provider-name text scoped to the CAD section)
# + download control (Download / Add To Library selectors + text) + per-format tool selectors
# (kicad / altium) + per-asset selectors (symbol+footprint, then the 3D model). Task 1 consumes
# label/present/download; Task 2 consumes the tool + asset fields.
_DIGIKEY_PROVIDERS: list[dict] = [
    {
        "label": "Ultra Librarian",
        "present": [
            "[data-provider='ultralibrarian']",
            "img[alt*='Ultra Librarian' i]",
            "a[href*='ultralibrarian']",
        ],
        "present_text": ["ultra librarian", "ultralibrarian"],
        "download": [
            "[data-provider='ultralibrarian'] button",
            "[data-testid*='ultralibrarian'] a[download]",
            "button[title*='Download' i]",
        ],
        "download_text": ["download", "add to library"],
        "kicad": ["[data-ecad='KiCad' i]", "label[for*='kicad' i]", "button[title*='KiCad' i]"],
        "kicad_text": ["kicad"],
        "altium": ["[data-ecad='Altium' i]", "label[for*='altium' i]", "button[title*='Altium' i]"],
        "altium_text": ["altium"],
        "symbolFootprint": [
            "a[href*='symbol' i]",
            "button[title*='Symbol' i]",
            "button[title*='Footprint' i]",
        ],
        "symbolFootprint_text": ["symbol", "footprint"],
        "model3d": ["a[href*='step' i]", "button[title*='3D' i]", "button[title*='Model' i]"],
        "model3d_text": ["3d", "model", "step"],
    },
    {
        "label": "SnapEDA",
        "present": ["[data-provider='snapeda']", "img[alt*='SnapEDA' i]", "a[href*='snapeda']"],
        "present_text": ["snapeda"],
        "download": [
            "[data-provider='snapeda'] a.download-button",
            "[data-testid*='snapeda'] a[download]",
            "a.download-button",
        ],
        "download_text": ["download", "add to library"],
        "kicad": ["a[href*='kicad' i]", "[data-format='kicad' i]", "button[title*='KiCad' i]"],
        "kicad_text": ["kicad"],
        "altium": ["a[href*='altium' i]", "[data-format='altium' i]", "button[title*='Altium' i]"],
        "altium_text": ["altium"],
        "symbolFootprint": [
            "a[href*='symbol' i]",
            "button[title*='Symbol' i]",
            "button[title*='Footprint' i]",
        ],
        "symbolFootprint_text": ["symbol", "footprint"],
        "model3d": ["a[href*='step' i]", "button[title*='3D' i]", "button[title*='Model' i]"],
        "model3d_text": ["3d", "model", "step"],
    },
    {
        "label": "SamacSys",
        "present": [
            "[data-provider='samacsys']",
            "img[alt*='SamacSys' i]",
            "a[href*='componentsearchengine']",
            "a[href*='samacsys']",
        ],
        "present_text": ["samacsys", "componentsearchengine"],
        "download": [
            "[data-provider='samacsys'] button",
            "[data-testid*='samacsys'] a[download]",
            "button[title*='Download' i]",
        ],
        "download_text": ["download", "add to library"],
        "kicad": ["[data-format='kicad' i]", "label[for*='kicad' i]", "button[title*='KiCad' i]"],
        "kicad_text": ["kicad"],
        "altium": ["[data-format='altium' i]", "label[for*='altium' i]", "button[title*='Altium' i]"],
        "altium_text": ["altium"],
        "symbolFootprint": [
            "a[href*='symbol' i]",
            "button[title*='Symbol' i]",
            "button[title*='Footprint' i]",
        ],
        "symbolFootprint_text": ["symbol", "footprint"],
        "model3d": ["a[href*='step' i]", "button[title*='3D' i]", "button[title*='Model' i]"],
        "model3d_text": ["3d", "model", "step"],
    },
]

# Guarded JS helpers shared by the DigiKey machine: report into the overlay bridge, click by
# selector list, click by scoped textContent match (skipping our own overlay node), a presence
# check, and a combined selector-then-text click that reports its own outcome. Every helper is
# guarded so a hostile / changed DOM degrades, never throws.
_DIGIKEY_HELPERS = (
    "function report(step,ok,msg){try{var o=window.__STOCKROOM_OVERLAY__;"
    "o&&o.report({step:step,ok:ok,message:msg});}catch(e){}}"
    "function click(sels){for(var i=0;i<sels.length;i++){try{"
    "var el=document.querySelector(sels[i]);if(el){el.click();return true;}}catch(e){}}return false;}"
    "function hasSel(sels){for(var i=0;i<sels.length;i++){try{"
    "if(document.querySelector(sels[i]))return true;}catch(e){}}return false;}"
    "function clickText(words){try{var ov=document.getElementById('__stockroom_overlay__');"
    "var nodes=document.querySelectorAll('a,button,div,span,label');"
    "for(var i=0;i<nodes.length;i++){var n=nodes[i];if(ov&&ov.contains(n))continue;"
    "if(n.children.length>3)continue;var t=(n.textContent||'').trim().toLowerCase();"
    "for(var k=0;k<words.length;k++){if(t.indexOf(words[k])>=0){try{n.click();return true;}catch(e){}}}}"
    "}catch(e){}return false;}"
    "function textPresent(words,scope){try{var root=scope||document;"
    "var nodes=root.querySelectorAll('a,div,span,img,button');"
    "for(var i=0;i<nodes.length;i++){var n=nodes[i];"
    "var alt=(n.getAttribute&&n.getAttribute('alt'))||'';"
    "var t=((n.textContent||'')+' '+alt).toLowerCase();"
    "for(var k=0;k<words.length;k++){if(t.indexOf(words[k])>=0)return true;}}"
    "}catch(e){}return false;}"
    "function tryClick(step,sels,words,okmsg,failmsg){try{var _ok=click(sels);"
    "if(!_ok&&words&&words.length){_ok=clickText(words);}"
    "report(step,_ok,_ok?okmsg:failmsg);return _ok;}catch(e){report(step,false,failmsg);return false;}}"
)

# Step 1: dismiss a DigiKey cookie/consent banner (resilient id + attribute + accept/agree text),
# guarded so no banner is a silent no-op reported as guidance.
_DIGIKEY_CONSENT = (
    "tryClick('consent',"
    "['#onetrust-accept-btn-handler','#onetrust-accept','[aria-label*=\"accept\" i]',"
    "'[aria-label*=\"agree\" i]','button[title*=\"accept\" i]'],"
    "['accept','agree','allow all','i agree'],"
    "'Dismissed the cookie banner.','No cookie banner to dismiss.');"
)

# Step 2: findCad KEPT verbatim (div-text match + element.scrollIntoView on DigiKey's custom
# scroll container). On success it hands the section to runProviders; a bounded tick loop waits
# for DigiKey's async render, then degrades to a guidance message.
_DIGIKEY_FINDCAD = (
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
    "report('cad',true,'Found the EDA / CAD Models section.');"
    "try{runProviders(el);}catch(e){report('cad',false,'Open the EDA / CAD Models section to download the files.');}return;}"
    "if(tries<12){setTimeout(tick,900);}"
    "else{report('cad',false,'Open the EDA / CAD Models section on this page to download the symbol, footprint and 3D model.');}}"
    "setTimeout(tick,700);"
)


def _digikey_providers_js(formats: list[str]) -> str:
    """The preference-ordered provider list as a JS array literal, with the per-format tool
    selectors GATED so an un-requested format's selectors (and its quoted name) never appear in the
    generated script (the only-requested-formats contract). Asset selectors are always present."""
    out: list[dict] = []
    for p in _DIGIKEY_PROVIDERS:
        d: dict = {
            "label": p["label"],
            "present": p["present"],
            "presentText": p["present_text"],
            "download": p["download"],
            "downloadText": p["download_text"],
            "symbolFootprint": p["symbolFootprint"],
            "symbolFootprintText": p["symbolFootprint_text"],
            "model3d": p["model3d"],
            "model3dText": p["model3d_text"],
        }
        if "kicad" in formats:
            d["kicad"] = p["kicad"]
            d["kicadText"] = p["kicad_text"]
        if "altium" in formats:
            d["altium"] = p["altium"]
            d["altiumText"] = p["altium_text"]
        out.append(d)
    return json.dumps(out)


def _digikey_runproviders_js(formats: list[str]) -> str:
    """Task 1 runProviders: detect the present providers from `_DIGIKEY_PROVIDERS` in preference
    order (report each present / skipped), then open the PREFERRED (first present) provider's
    download control. Task 2 replaces the open-only body with the full per-provider sub-sequence
    iterated across every present provider."""
    return (
        "function runProviders(sec){"
        "var provs=" + _digikey_providers_js(formats) + ";"
        "var present=[];"
        "for(var i=0;i<provs.length;i++){var pr=provs[i];var f=false;"
        "try{f=hasSel(pr.present)||textPresent(pr.presentText,sec);}catch(e){}"
        "if(f){present.push(pr);report('provider',true,'Found '+pr.label+' in the CAD Models section.');}"
        "else{report('provider',false,pr.label+' is not offered for this part; skipping.');}}"
        "if(!present.length){report('open',false,"
        "'No known CAD provider is offered; download the files from this section manually.');return;}"
        "var pref=present[0];"
        "tryClick('open',pref.download,pref.downloadText,"
        "'Opened '+pref.label+' download.','Open '+pref.label+' Download / Add To Library control.');"
        "}"
    )


def _digikey_driver_js(formats: list[str]) -> str:
    fmts = [f for f in ("kicad", "altium") if f in (formats or [])]
    body = (
        _DIGIKEY_HELPERS
        + "var formats=" + json.dumps(fmts) + ";"
        + "report('start',true,'DigiKey lists the symbol, footprint and 3D model together; getting them now.');"
        + _digikey_runproviders_js(fmts)
        + _DIGIKEY_CONSENT
        + _DIGIKEY_FINDCAD
    )
    return f"(function(){{{body}}})();"


def build_driver_js(vendor: str, formats: list[str]) -> str:
    key = (vendor or "").strip().lower()
    if key == "digikey":
        return _digikey_driver_js(formats)
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
