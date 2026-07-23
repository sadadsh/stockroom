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
# side). The driver is an EVENT-DRIVEN REACTOR, not a timed script: on the product page it reacts to
# the models link and navigates; on the models page it reacts to each control the instant it is
# actionable, and it advances to the next format ONLY on the browser's REAL download-completed event
# (relayed via window.__SR_DL__) - so it never preempts a still-generating download and never waits on
# a phantom UI modal. It recovers like a human - refresh on a stall/error, hand off to the user on a
# Cloudflare/login wall. Provider coverage VARIES, so it enumerates the VISIBLE rows (owner 2026-07-23:
# "DigiKey shows which suppliers have what"), preferring SnapMagic (the owner's reliable source).

# Preference-ordered providers: (id-prefix, display label). SnapMagic FIRST - it is the owner's
# proven, reliable two-format source (Ultra Librarian errors on the 2nd file and needs a refresh +
# Cloudflare check). Only VISIBLE rows are ever driven, so a part offering only Ultra Librarian just
# falls through to it, and the reactor's refresh recovery handles UL's second-file stall.
_DIGIKEY_PROVIDER_KEYS: list[list[str]] = [
    ["snapmagic", "SnapMagic"],
    ["ultra", "Ultra Librarian"],
    ["mfr", "Manufacturer Provided"],
    ["traceparts", "TraceParts"],
    ["cadenas", "CADENAS"],
]

# The reactor's shared primitives. Everything is EVENT-DRIVEN: until() reacts to a real DOM mutation
# the instant a predicate is satisfied (a MutationObserver, rAF-debounced), with a watchdog ONLY as a
# never-hang backstop - no fixed-interval polling, no fixed sleeps used as gates. vis()/actionable()
# are the visibility + real hit-test (elementFromPoint at the click moment - a display:none provider
# row has offsetParent===null). senseError()/senseWall() are what the reactor watches to recover like
# a human: a "download failed" toast -> refresh; a Cloudflare / verify / login wall -> hand off via
# the overlay "Your Turn".
_DIGIKEY_HELPERS = (
    "function trace(){try{var a=['[SRDRV]'].concat([].slice.call(arguments));"
    "console.log.apply(console,a);}catch(e){}}"
    "function report(step,ok,msg){trace('report',step,ok,msg);"
    "try{var o=window.__STOCKROOM_OVERLAY__;o&&o.report({step:step,ok:ok,message:msg});}catch(e){}}"
    "function yourTurn(msg){trace('yourTurn',msg);"
    "try{var o=window.__STOCKROOM_OVERLAY__;o&&o.action({needsUser:true,message:msg});}catch(e){}}"
    "function clearTurn(){try{var o=window.__STOCKROOM_OVERLAY__;o&&o.action({needsUser:false});}catch(e){}}"
    "function vis(el){try{return !!(el&&el.offsetParent!==null&&el.getClientRects().length);}catch(e){return false;}}"
    "function actionable(el){try{if(!vis(el))return false;var r=el.getBoundingClientRect();"
    "var x=r.left+r.width/2,y=r.top+r.height/2;if(x<0||y<0||x>innerWidth||y>innerHeight)return true;"
    "var t=document.elementFromPoint(x,y);return !!(t&&(t===el||el.contains(t)||t.contains(el)));}catch(e){return true;}}"
    "function labelInput(l){try{return l.htmlFor?document.getElementById(l.htmlFor):"
    "(l.querySelector('input')||l.previousElementSibling);}catch(e){return null;}}"
    "function observe(cb){var s=0;var o=new MutationObserver(function(){if(s)return;"
    "s=requestAnimationFrame(function(){s=0;cb();});});"
    "try{o.observe(document.documentElement,{childList:true,subtree:true,attributes:true,characterData:true});}catch(e){}return o;}"
    "function until(pred,cb,wd){var done=false,o=null;function fin(v){if(done)return;done=true;"
    "try{o&&o.disconnect();}catch(e){}clearTimeout(t);cb(v);}"
    "function chk(){var v=null;try{v=pred();}catch(e){v=null;}if(v)fin(v);}"
    "o=observe(chk);var t=setTimeout(function(){fin(null);},wd||30000);chk();}"
    "function txt(el){try{return (el.innerText||el.textContent||'').toLowerCase();}catch(e){return '';}}"
    "function senseError(){try{var ns=document.querySelectorAll("
    "'[role=alert],.toast,.notification,[class*=error i],[class*=toast i],[class*=alert i]');"
    "for(var i=0;i<ns.length;i++){if(vis(ns[i])){var t=txt(ns[i]);"
    "if(/download failed|failed to (generate|download|create)|model download failed|"
    "unable to (generate|download)|something went wrong/.test(t))return true;}}return false;}catch(e){return false;}}"
    "function senseWall(){try{if(document.querySelector("
    "'iframe[src*=\"challenges.cloudflare.com\"],#challenge-running,#cf-challenge-running,.cf-turnstile'))return true;"
    "var b=(document.body&&document.body.innerText||'').toLowerCase();"
    "if(/verify you are (a )?human|checking your browser|complete the security check|"
    "review the security of your connection/.test(b))return true;"
    "if(document.querySelector('input[type=password]')&&/sign ?in|log ?in/.test(b))return true;"
    "return false;}catch(e){return false;}}"
)

# The download bridge + recovery. window.__SR_DL__ receives the browser's REAL download lifecycle
# (the host relays CoreWebView2 StateChanged: started / completed / interrupted). awaitDownload
# resolves onDone ONLY on a real 'completed' - so the next format fires after the file truly lands
# (no preemption) - and onFail on an 'interrupted', a visible "download failed" toast, or a stall
# watchdog. recover() is the human's move: on a wall, hand off + wait for it to clear, then refresh;
# else refresh once (bounded across reloads via sessionStorage). A fresh document re-injects the
# reactor scoped to whatever is still needed, and the host dedups anything already captured.
_DIGIKEY_REACTOR = (
    "window.__SR_DL_CB__=null;"
    "window.__SR_DL__=function(evt){trace('dl',evt&&evt.state);var cb=window.__SR_DL_CB__;if(cb)cb(evt);};"
    "function awaitDownload(spec,onDone,onFail){var settled=false,obs=null,wd=null;"
    "function settle(fn,why){if(settled)return;settled=true;window.__SR_DL_CB__=null;"
    "try{obs&&obs.disconnect();}catch(e){}clearTimeout(wd);trace('await',spec.key,why);fn(why);}"
    "window.__SR_DL_CB__=function(evt){"
    "if(evt&&evt.state==='completed'&&(!evt.format||evt.format===spec.key))settle(onDone,'completed');};"
    "function pg(){if(senseWall())settle(onFail,'wall');else if(senseError())settle(onFail,'error');}"
    "obs=observe(pg);wd=setTimeout(function(){settle(onFail,'timeout');},GEN_WD);pg();}"
    "function refreshes(){try{return parseInt(sessionStorage.getItem('__SR_REFRESH__')||'0',10)||0;}catch(e){return 0;}}"
    "function refresh(){try{sessionStorage.setItem('__SR_REFRESH__',''+(refreshes()+1));}catch(e){}"
    "trace('refresh',refreshes());location.reload();}"
    "function recover(spec,done){if(senseWall()){"
    "yourTurn('Please finish the quick verification in this window; I will continue right after.');"
    "until(function(){return !senseWall();},function(){clearTurn();refresh();},170000);return;}"
    "if(refreshes()>=MAX_REFRESH){report(spec.key,false,"
    "'Could not fetch '+spec.name+' automatically; the files are here to grab by hand.');done();return;}"
    "report(spec.key,false,'That stalled; refreshing to try '+spec.name+' again.');refresh();}"
)

# Phase 1 (product page): react to the CAD models link, navigate in-place (a fresh document, so the
# host re-injects the reactor on the models page). Phase 2 (models page): react to the provider bar,
# enumerate the VISIBLE provider rows in preference order, then drive each requested format in turn.
_DIGIKEY_RUN = (
    "function gotoModels(){until(function(){"
    "var a=document.querySelector('[data-testid=\"eda-cad-model-link\"]');"
    "if(!a){var as=document.querySelectorAll('a[href]');for(var i=0;i<as.length;i++){"
    "if(/\\/models\\//.test(as[i].getAttribute('href')||'')){a=as[i];break;}}}"
    "return (a&&a.getAttribute('href'))?a:null;},function(a){"
    "if(!a){report('cad',false,'Open the EDA / CAD Models section on this page to download the files.');return;}"
    "report('cad',true,'Opening the EDA / CAD Models page.');"
    "var h=a.getAttribute('href');location.href=(h.charAt(0)==='/')?(location.origin+h):h;},15000);}"
    "function providers(){var present=[];for(var i=0;i<PROVS.length;i++){var k=PROVS[i][0];"
    "if(vis(document.querySelector('#'+k+'-media-active')))present.push(PROVS[i]);}return present.length?present:null;}"
    "function runModels(){until(providers,function(present){"
    "if(!present){report('provider',false,'No CAD provider is offered here; download the files from this page by hand.');return;}"
    "report('provider',true,'Providers here: '+present.map(function(p){return p[1];}).join(', ')+'.');"
    "driveFormats(present);},15000);}"
    "function driveFormats(present){var qi=0;function nextFmt(){"
    "if(qi>=SPECS.length){report('done',true,'All requested downloads are done.');"
    "try{sessionStorage.removeItem('__SR_REFRESH__');}catch(e){}return;}"
    "var spec=SPECS[qi++];trace('nextFmt',qi+'/'+SPECS.length,spec.key);downloadFormat(present,spec,nextFmt);}nextFmt();}"
)

# Per-format: react through each visible provider IN ORDER until one actually offers the format (its
# export modal has a matching data-original label), pick it + the STEP 3D radio, click Download (each
# click gated on actionable()), then AWAIT the real browser download. It does NOT hardcode a provider;
# whatever visible source can deliver the format wins ("trying the next source" otherwise).
_DIGIKEY_DOWNLOAD = (
    "function fmtBtn(){var cs=document.querySelectorAll('a.btn-download-model,a.dk-btn__primary,button,a');"
    "for(var i=0;i<cs.length;i++){if(vis(cs[i])&&/select download format/i.test(cs[i].textContent||''))return cs[i];}return null;}"
    "function exportModal(){var m=document.querySelector('[id$=\"-export-options\"]');return (m&&m.querySelector('label'))?m:null;}"
    "function dlBtn(){var m=document.querySelector('[id$=\"-export-options\"]');"
    "var d=(m&&m.querySelector('[id^=\"btn-download-\"]'))||document.querySelector('[id^=\"btn-download-\"]');"
    "return (d&&!d.disabled&&actionable(d))?d:null;}"
    "function closeModal(){try{var x=document.querySelector('[id$=\"-export-options\"] .dk-modal__close,"
    "[id$=\"-export-options\"] [data-modal-dismiss]');if(x)x.click();}catch(e){}}"
    "function pickFormat(spec){var m=exportModal();if(!m)return false;var ls=m.querySelectorAll('label'),has=false;"
    "for(var j=0;j<ls.length;j++){var t=(ls[j].getAttribute('data-original')||ls[j].textContent||'').trim();"
    "if(spec.re.test(t)){has=true;var inp=labelInput(ls[j]);try{(inp||ls[j]).click();}catch(e){}break;}}"
    "if(has){for(var k=0;k<ls.length;k++){var t2=(ls[k].getAttribute('data-original')||ls[k].textContent||'').trim();"
    "if(/^step$/i.test(t2)){var si=labelInput(ls[k]);try{(si||ls[k]).click();}catch(e){}break;}}}return has;}"
    "function downloadFormat(present,spec,done){var pi=0;function tryProvider(){"
    "if(pi>=present.length){report(spec.key,false,'No visible source offers '+spec.name+'; download it by hand.');done();return;}"
    "var prov=present[pi++];trace('tryProvider',spec.key,prov[1]);"
    "if(!fmtBtn()){var row=document.querySelector('#'+prov[0]+'-media-active');if(row){try{row.click();}catch(e){}}}"
    "until(function(){var b=fmtBtn();return actionable(b)?b:null;},function(btn){"
    "if(!btn){report('provider',false,prov[1]+' did not open; trying the next source.');tryProvider();return;}"
    "try{btn.click();}catch(e){}"
    "until(exportModal,function(modal){"
    "if(!modal){report('provider',false,prov[1]+' showed no formats; trying the next source.');tryProvider();return;}"
    "if(!pickFormat(spec)){report('provider',false,prov[1]+' has no '+spec.name+'; trying the next source.');closeModal();tryProvider();return;}"
    "report(spec.key,true,'Selected '+spec.name+' plus the 3D model from '+prov[1]+'.');"
    "until(dlBtn,function(dl){"
    "if(!dl){report('download',false,'Select a format, then click Download.');return;}"
    "try{dl.click();}catch(e){}"
    "report('download',true,'Downloading '+spec.name+' from '+prov[1]+'; watching for the file.');"
    "awaitDownload(spec,function(){report('progress',true,'Finished '+spec.name+'.');done();},"
    "function(why){recover(spec,done);});},12000);},12000);},12000);}tryProvider();}"
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
        # One reactor per document (the host re-injects on every `loaded`; the models page fires it more
        # than once). A real navigation (product -> /models/, or a recovery reload) is a fresh document,
        # so the guard resets and the reactor runs again, scoped to whatever is still needed.
        "if(window.__SR_DK_RUNNING__)return;window.__SR_DK_RUNNING__=true;"
        # The watchdog is the ONLY timer - a never-hang backstop, not a step gate. GEN_WD: a file must
        # actually land (be captured) within this (server-side generation, under the SPA's 180s); else
        # recover (refresh). MAX_REFRESH bounds human-style refresh recovery across reloads.
        "var GEN_WD=150000,MAX_REFRESH=3;"
        + _DIGIKEY_HELPERS
        + _DIGIKEY_REACTOR
        + _DIGIKEY_RUN
        + _DIGIKEY_DOWNLOAD
        + "var PROVS=" + json.dumps(_DIGIKEY_PROVIDER_KEYS) + ";"
        + "var SPECS=" + _digikey_format_specs_js(fmts) + ";"
        + "report('start',true," + json.dumps(start_msg) + ");"
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
