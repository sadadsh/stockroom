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


# DigiKey serves CAD files through a DEDICATED models page, not an in-page section (live-validated
# 2026-07-23 against the signed-in DOM). The product page carries a link
# `a[data-testid="eda-cad-model-link"]` -> href `/en/models/<productId>`; that page lists the
# aggregating providers as left-bar rows (`#ultra-media-active`, `#mfr-media-active`,
# `#snapmagic-media-active`, `#traceparts-media-active`, `#cadenas-media-active`), the ones NOT
# offered for the part hidden with display:none (so `offsetParent===null`). A provider's "Select
# Download Format" control (`a.btn-download-model`, onclick=displayExportModal) opens a
# `#<prov>-export-options` modal of radio formats keyed by a STABLE `data-original` label
# (KiCAD v6+, Altium Designer, STEP, ...); picking one calls toggleRadioButton and enables the footer
# `#btn-download-<Provider>` (onclick=exportUltraFile) that fires the real download (intercepted host
# side). So the driver is a TWO-PHASE state machine: on the product page navigate to the models page;
# on the models page, per REQUESTED format, drive the visible providers' modal to select + download.
# Every step is guarded and reported into the overlay; a missing target degrades to guidance. The
# per-part provider coverage VARIES, so it enumerates the VISIBLE provider rows (owner note
# 2026-07-23: "DigiKey shows which suppliers have what"), preferring Ultra Librarian.

# Preference-ordered providers: (id-prefix, display label). Ultra Librarian (most complete) first.
_DIGIKEY_PROVIDER_KEYS: list[list[str]] = [
    ["ultra", "Ultra Librarian"],
    ["mfr", "Manufacturer Provided"],
    ["snapmagic", "SnapMagic"],
    ["traceparts", "TraceParts"],
    ["cadenas", "CADENAS"],
]

# Guarded shared helpers: overlay report, a visibility test (a display:none provider row has
# offsetParent===null), and the input a <label> controls. All guarded so a changed DOM degrades.
_DIGIKEY_HELPERS = (
    "function report(step,ok,msg){try{var o=window.__STOCKROOM_OVERLAY__;"
    "o&&o.report({step:step,ok:ok,message:msg});}catch(e){}}"
    "function vis(el){try{return !!(el&&el.offsetParent!==null);}catch(e){return false;}}"
    "function labelInput(l){try{return l.htmlFor?document.getElementById(l.htmlFor):"
    "(l.querySelector('input')||l.previousElementSibling);}catch(e){return null;}}"
)

# Phase 1 (product page): find the CAD models link and navigate to it in-place (the <a> may be
# target=_blank; setting location.href keeps it in the cad window so the driver re-injects on the
# models page). Bounded tick loop for DigiKey's async render, then degrade to guidance.
_DIGIKEY_GOTO_MODELS = (
    "function gotoModels(){var tries=0;function tick(){tries++;try{"
    "var a=document.querySelector('[data-testid=\"eda-cad-model-link\"]');"
    "if(!a){var as=document.querySelectorAll('a[href]');for(var i=0;i<as.length;i++){"
    "if(/\\/models\\//.test(as[i].getAttribute('href')||'')){a=as[i];break;}}}"
    "if(a&&a.getAttribute('href')){report('cad',true,'Opening the EDA / CAD Models page.');"
    "var h=a.getAttribute('href');location.href=(h.charAt(0)==='/')?(location.origin+h):h;return;}"
    "}catch(e){}"
    "if(tries<14){setTimeout(tick,800);}else{report('cad',false,"
    "'Open the EDA / CAD Models section on this page to download the files.');}}"
    "setTimeout(tick,600);}"
)

# Phase 2 (models page): wait for the provider bar, enumerate the VISIBLE provider rows in
# preference order, then drive each requested format sequentially through downloadFormat.
_DIGIKEY_RUN_MODELS = (
    "function runModels(){var tries=0;function tick(){tries++;try{"
    "var present=[];for(var i=0;i<PROVS.length;i++){var k=PROVS[i][0];"
    "var el=document.querySelector('#'+k+'-media-active');if(vis(el)){present.push(PROVS[i]);}}"
    "if(present.length){report('provider',true,'Providers offered here: '"
    "+present.map(function(p){return p[1];}).join(', ')+'.');driveFormats(present);return;}"
    "}catch(e){}"
    "if(tries<16){setTimeout(tick,800);}else{report('provider',false,"
    "'No CAD provider is offered for this part; download the files from this page manually.');}}"
    "setTimeout(tick,700);}"
    "function driveFormats(present){var qi=0;function nextFmt(){"
    "if(qi>=SPECS.length){report('done',true,'All requested downloads were triggered.');return;}"
    "var spec=SPECS[qi++];try{downloadFormat(present,spec,nextFmt);}"
    "catch(e){report(spec.key,false,'Select '+spec.name+' and download it from this page.');nextFmt();}}"
    "nextFmt();}"
)

# The per-format download sub-sequence (async, since the row content + modal lazy-load): open the
# preferred present provider, open its Select Download Format modal, pick the format radio by its
# stable data-original label AND the STEP 3D radio (one download = symbol + footprint + 3D model),
# then click the footer #btn-download-<Provider>. Each stage guarded + reported.
_DIGIKEY_DOWNLOAD_FORMAT = (
    "function fmtBtn(){var cs=document.querySelectorAll('a.btn-download-model,a.dk-btn__primary,button,a');"
    "for(var i=0;i<cs.length;i++){if(vis(cs[i])&&/select download format/i.test(cs[i].textContent||'')){return cs[i];}}return null;}"
    "function downloadFormat(present,spec,done){var prov=present[0];"
    # Expand the provider row ONLY if its Select Download Format control is not already visible -
    # re-clicking an already-open accordion would TOGGLE it closed and break the 2nd (Altium) pass.
    "try{if(!fmtBtn()){var row=document.querySelector('#'+prov[0]+'-media-active');if(row)row.click();}}catch(e){}"
    "setTimeout(function(){try{var btn=fmtBtn();if(btn)btn.click();}catch(e){}"
    "setTimeout(function(){var picked=false;try{"
    "var modal=document.querySelector('[id$=\"-export-options\"]');if(modal){"
    "var ls=modal.querySelectorAll('label');"
    "for(var j=0;j<ls.length;j++){var t=(ls[j].getAttribute('data-original')||ls[j].textContent||'').trim();"
    "if(spec.re.test(t)){var inp=labelInput(ls[j]);try{(inp||ls[j]).click();picked=true;}catch(e){}break;}}"
    "for(var m=0;m<ls.length;m++){var t2=(ls[m].getAttribute('data-original')||ls[m].textContent||'').trim();"
    "if(/^step$/i.test(t2)){var si=labelInput(ls[m]);try{(si||ls[m]).click();}catch(e){}break;}}}"
    "}catch(e){}"
    "report(spec.key,picked,picked?('Selected '+spec.name+' plus the 3D model; downloading.'):"
    "('Pick '+spec.name+' in the Choose Download Format dialog.'));"
    "setTimeout(function(){var fired=false;try{"
    "var modal2=document.querySelector('[id$=\"-export-options\"]');"
    "var dl=(modal2&&modal2.querySelector('[id^=\"btn-download-\"]'))||document.querySelector('[id^=\"btn-download-\"]');"
    "if(dl&&!dl.disabled){dl.click();fired=true;}}catch(e){}"
    "report('download',fired,fired?('Downloading the '+spec.name+' symbol, footprint and 3D model.'):"
    "('Select a format, then click Download.'));"
    # DigiKey shows a "Downloading... may take a few minutes" progress modal after Download; the NEXT
    # format cannot open its picker until that clears (live-observed 2026-07-23: a fixed gap raced the
    # still-open modal and the Altium pass no-op'd). Poll it OUT (up to 90s), then move to the next.
    "var waited=0;function waitDl(){var busy=false;try{"
    "var dlg=document.querySelectorAll('.dk-modal,[role=\"dialog\"],aside,.modal');"
    "for(var w=0;w<dlg.length;w++){if(vis(dlg[w])&&/downloading/i.test(dlg[w].textContent||'')){busy=true;break;}}"
    "}catch(e){}waited+=1200;if(busy&&waited<90000){setTimeout(waitDl,1200);}"
    "else{report('progress',true,busy?('Still downloading '+spec.name+'; continuing.'):"
    "('Finished the '+spec.name+' download.'));setTimeout(done,2500);}}"
    "setTimeout(waitDl,2500);"
    "},900);},1600);},2400);}"
)


def _digikey_format_specs_js(formats: list[str]) -> str:
    """The requested formats as a JS array of {key,name,re} - `re` a real RegExp literal matching
    the modal's stable data-original label. ONLY requested formats are emitted, so an un-requested
    format's quoted name never appears in the generated script (the only-requested-formats contract).
    """
    specs = []
    if "kicad" in formats:
        specs.append(("kicad", "KiCad", "/kicad\\s*v6/i"))
    if "altium" in formats:
        specs.append(("altium", "Altium", "/^altium designer$/i"))
    return (
        "["
        + ",".join(
            "{key:" + json.dumps(k) + ",name:" + json.dumps(n) + ",re:" + r + "}"
            for (k, n, r) in specs
        )
        + "]"
    )


def _digikey_driver_js(formats: list[str]) -> str:
    fmts = [f for f in ("kicad", "altium") if f in (formats or [])]
    names = [{"kicad": "KiCad", "altium": "Altium"}[f] for f in fmts]
    start_msg = "Getting the " + (" and ".join(names) or "CAD") + " files from DigiKey."
    body = (
        _DIGIKEY_HELPERS
        + "var PROVS=" + json.dumps(_DIGIKEY_PROVIDER_KEYS) + ";"
        + "var SPECS=" + _digikey_format_specs_js(fmts) + ";"
        + "report('start',true," + json.dumps(start_msg) + ");"
        + _DIGIKEY_GOTO_MODELS
        + _DIGIKEY_RUN_MODELS
        + _DIGIKEY_DOWNLOAD_FORMAT
        + "try{if(location.pathname.indexOf('/models/')>=0){runModels();}else{gotoModels();}}"
        "catch(e){report('driver',false,'Open the EDA / CAD Models section and download the files.');}"
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
