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

# Preference-ordered providers: [row-id prefix, display label, export-modal id, radio-group
# prefix]. SnapMagic FIRST - the owner's proven, reliable two-format source. Only VISIBLE rows are
# ever driven. The modal id and group prefix DIVERGE from the row id (dkprobe live DOM +
# DigiKey's own clearSelection() source, 2026-07-23): row #snapmagic-media-active drives modal
# #snapeda-export-options with groups snapeda-format-selection[-3d]; row #ultra-media-active
# drives #ultralib-export-options with groups ultra-format-selection[-3d]. Every control the
# driver touches is scoped through this tuple so it can never drive another provider's modal.
_DIGIKEY_PROVIDER_KEYS: list[list[str]] = [
    ["snapmagic", "SnapMagic", "snapeda-export-options", "snapeda"],
    ["ultra", "Ultra Librarian", "ultralib-export-options", "ultra"],
    ["mfr", "Manufacturer Provided", "mfr-export-options", "mfr"],
    ["traceparts", "TraceParts", "traceparts-export-options", "traceparts"],
    ["cadenas", "CADENAS", "cadenas-export-options", "cadenas"],
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
    "function txt(el){try{return (el.textContent||'').toLowerCase();}catch(e){return '';}}"
    "function senseError(){try{var ns=document.querySelectorAll("
    "'[role=alert],.toast,.notification,[class*=error i],[class*=toast i],[class*=alert i]');"
    "for(var i=0;i<ns.length;i++){if(vis(ns[i])){var t=txt(ns[i]);"
    "if(/download failed|failed to (generate|download|create)|model download failed|"
    "unable to (generate|download)|something went wrong/.test(t))return true;}}return false;}catch(e){return false;}}"
    # CHEAP - never read document.body.innerText (it forces a full layout; called on a health-check it
    # would starve the vendor's download JS). Cloudflare's interstitial is identifiable by its own
    # elements + the document title; a login wall by a password field in a form.
    "function senseWall(){try{if(document.querySelector("
    "'iframe[src*=\"challenges.cloudflare.com\"],#challenge-running,#cf-challenge-running,.cf-turnstile'))return true;"
    "var t=(document.title||'').toLowerCase();"
    "if(/just a moment|attention required|verify you are|checking your browser/.test(t))return true;"
    "if(document.querySelector('input[type=password]')&&document.querySelector('form input[type=password]'))return true;"
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
    "function awaitDownload(spec,onDone,onFail){var settled=false,iv=null,wd=null,sw=null;"
    "function settle(fn,why){if(settled)return;settled=true;window.__SR_DL_CB__=null;"
    "clearInterval(iv);clearTimeout(wd);clearTimeout(sw);trace('await',spec.key,why);fn(why);}"
    # A completed download of the WRONG format is sensed and reacted to AT ONCE: the vendor can
    # deliver the wrong file outright (live 2026-07-23: a sticky prior selection made UL serve its
    # Altium+STEP bundle against a KiCad request), and waiting out the watchdog on it left the
    # capture hanging 150s on a download that had already finished. A real 'started' event clears
    # the start watchdog (owner heuristic 2026-07-23: a successful run's download STARTS within
    # ~5s of the click - if nothing starts, the attempt is already dead, fail 'nostart' at once).
    "window.__SR_DL_CB__=function(evt){if(!evt)return;"
    "if(evt.state==='started'){trace('await',spec.key,'started');clearTimeout(sw);sw=null;return;}"
    "if(evt.state!=='completed')return;"
    "if(!evt.format||evt.format===spec.key){settle(onDone,'completed');}"
    "else{settle(onFail,'wrongfile');}};"
    "sw=setTimeout(function(){settle(onFail,'nostart');},START_WD);"
    # While the vendor generates the file server-side (up to a minute+), watch for a failure with a
    # LIGHT periodic health-check (a wall/error toast), NOT a per-frame MutationObserver: the download
    # phase mutates the DOM constantly (the spinner), so an every-frame observer that read innerText
    # would force a full layout every frame and STARVE the vendor's own download JS - the file would
    # never finish (live-observed 2026-07-23; the old light-poll driver completed, this did not). The
    # completion itself arrives as the real event above; this interval only catches a stall/wall.
    "iv=setInterval(function(){if(senseWall())settle(onFail,'wall');else if(senseError())settle(onFail,'error');},1500);"
    "wd=setTimeout(function(){settle(onFail,'timeout');},GEN_WD);}"
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
#
# The selection is VERIFIED, never assumed from a click (live 2026-07-23): the persistent profile
# restores the PREVIOUS session's selection, so the modal can open pre-armed (download button already
# enabled) on the WRONG format, and the provider then serves that wrong bundle. pickVerified clears
# stale state via the provider's own Clear Selection button, drives the provider's own radio groups,
# verifies with the vendor's own document-order input:checked read, tolerates a 3D radio that shares
# (and would steal) the format's radio group, and only then lets Download fire - re-checked
# synchronously in the click task. A wrong file that still slips through comes back as
# awaitDownload's 'wrongfile' and climbs the resilience ladder.
_DIGIKEY_DOWNLOAD = (
    # Every control is scoped through the provider tuple prov = [row, label, modalId, group]
    # (dkprobe live DOM 2026-07-23): a document-wide seek can find ANOTHER provider's "Select
    # Download Format" control or modal and silently drive the wrong source.
    "function fmtBtnFor(prov){var cs=document.querySelectorAll('a,button');"
    "for(var i=0;i<cs.length;i++){var n=cs[i];if(!vis(n))continue;"
    "var oc=n.getAttribute('onclick')||'';"
    "if(/displayExportModal/i.test(oc)&&oc.indexOf(prov[2])>=0)return n;}"
    "var region=document.querySelector('#'+prov[0]+'-container-content');"
    "if(region){var ns=region.querySelectorAll('a,button');"
    "for(var j=0;j<ns.length;j++){if(vis(ns[j])&&/select download format/i.test(ns[j].textContent||''))return ns[j];}}"
    "return null;}"
    # A dk-modal is position:fixed, so its offsetParent is ALWAYS null - vis() can never pass on
    # the modal element itself. And DigiKey NEVER updates aria-hidden: a visibly open modal still
    # carries aria-hidden="true" (probed live 2026-07-23: class "dk-modal visible", display:flex,
    # visibility:visible, aria-hidden "true"). Openness is the "visible" class, with a computed
    # display/visibility + client-rects fallback.
    "function modalShown(m){try{if(!m)return false;"
    "if(/\\bvisible\\b/.test(String(m.className||'')))return true;"
    "var cs=getComputedStyle(m);"
    "return cs.display!=='none'&&cs.visibility!=='hidden'&&cs.opacity!=='0'&&!!m.getClientRects().length;}"
    "catch(e){return false;}}"
    "function exportModalFor(prov){var m=document.getElementById(prov[2]);"
    "return (m&&modalShown(m)&&m.querySelector('label'))?m:null;}"
    # The download button lives INSIDE the provider's open modal: modal shown + enabled + visible
    # is sufficient context to click it. The strict elementFromPoint hit-test false-negatives on a
    # taller modal (live 2026-07-23, ATMEGA: enabled+visible footer never "actionable" for 12s on
    # a small desktop viewport) - scroll it into view instead of refusing to click.
    "function dlBtnFor(prov){var m=document.getElementById(prov[2]);"
    "if(!m||!modalShown(m))return null;"
    "var d=m.querySelector('[id^=\"btn-download-\"]');"
    "if(!d||d.disabled||!vis(d))return null;"
    "if(!actionable(d)){try{d.scrollIntoView({block:'center'});}catch(e){}}"
    "return d;}"
    "function closeModalFor(prov){try{var m=document.getElementById(prov[2]);if(!m)return;"
    "var x=m.querySelector('.dk-modal__close,[data-modal-dismiss]');if(x)x.click();}catch(e){}}"
    # A provider row can be a pure LINK-OUT to the manufacturer's site with no in-page export
    # (dkprobe: GCT's mfr row is one external href, its modal exists empty) - sense it and skip
    # fast instead of waiting out a watchdog.
    "function externalOnly(prov){if(fmtBtnFor(prov))return false;"
    "var region=document.querySelector('#'+prov[0]+'-container-content');if(!region)return false;"
    "var as=region.querySelectorAll('a[href]');"
    "for(var i=0;i<as.length;i++){var h=as[i].getAttribute('href')||'';"
    "if(vis(as[i])&&/^https?:/i.test(h)&&h.indexOf('digikey.com')<0)return true;}return false;}"
    "function findLabel(m,re){var ls=m.querySelectorAll('label');"
    "for(var j=0;j<ls.length;j++){var t=(ls[j].getAttribute('data-original')||ls[j].textContent||'').trim();"
    "if(re.test(t))return ls[j];}return null;}"
    "function isOn(l){try{var i=labelInput(l);if(i&&typeof i.checked==='boolean')return i.checked;"
    "var a=(l.getAttribute('aria-checked')||'').toLowerCase();if(a)return a==='true';"
    "return /\\b(active|checked|selected)\\b/i.test(l.className||'');}catch(e){return false;}}"
    "function setOn(l){try{var i=labelInput(l);(i||l).click();}catch(e){}}"
    # Providers persist the LAST exported selection in localStorage (UL: ultraDownloadFormat2D/3D,
    # live 2026-07-23) and their async modal re-render restores it - the source of the sticky wrong
    # format. Clear EVERY such key generically (any provider's <name>DownloadFormat<n> variant):
    # safe, the vendors' own code handles absence (it re-saves on the next export).
    "function clearSticky(){try{for(var i=localStorage.length-1;i>=0;i--){"
    "var k=localStorage.key(i);if(/downloadformat/i.test(k||''))localStorage.removeItem(k);}}catch(e){}}"
    # pickVerified drives the provider's OWN radio groups and verifies with the vendor's OWN read:
    # the export functions read input[name="<group>-format-selection[-3d]"]:checked in document
    # order, so that exact read - the checked input IS the one we clicked - is the only
    # verification that matches what the export will send. The provider's Clear Selection button
    # (vendor-supplied, resets both groups + their toggle bookkeeping) clears stale state first.
    # sel.ok() re-runs the verification at any later moment (the atomic pre-click check).
    "function pickVerified(modal,prov,spec,cb){var target=findLabel(modal,spec.re);"
    "if(!target){cb(false,null);return;}"
    "var step=findLabel(modal,/^step$/i);var g=prov[3],tries=0;"
    "function gIn(sfx){return document.querySelector('input[name=\"'+g+'-format-selection'+sfx+'\"]:checked');}"
    "function ok2d(){var ti=labelInput(target);var c=gIn('');return (c&&ti)?(c===ti):isOn(target);}"
    "function ok3d(w){if(!w)return true;var si=step?labelInput(step):null;var c=gIn('-3d');"
    "return (c&&si)?(c===si):isOn(step);}"
    "var sel={w:false};sel.ok=function(){return ok2d()&&ok3d(sel.w);};"
    "function attempt(){tries++;trace('pick',spec.key,'attempt',tries);clearSticky();"
    "var clr=modal.querySelector('[id^=\"btn-clear-selection-\"]');"
    "if(clr&&!clr.disabled){try{clr.click();}catch(e){}}"
    "setOn(target);sel.w=!!step;"
    "if(sel.w){setOn(step);"
    "if(!ok2d()){setOn(target);sel.w=false;trace('pick',spec.key,'step shares the group; format wins');}}"
    "until(function(){return sel.ok()?{k:1}:null;},function(v){"
    "if(v){trace('pick',spec.key,'verified step='+(sel.w?1:0));cb(true,sel);return;}"
    "if(tries<3){attempt();return;}"
    "if(ok2d()){sel.w=false;trace('pick',spec.key,'format on; step unverified');cb(true,sel);return;}"
    "cb(false,null);},2000);}attempt();}"
    # The Download click is ATOMIC with a SYNCHRONOUS selection re-check (sel.ok()): the vendor's
    # export handler reads input:checked synchronously in the click chain, so nothing can
    # re-render between this check and the read (live 2026-07-23: an async modal re-render wiped
    # a verified selection ~80ms before the click and the sticky wrong format was exported).
    "function selOn(sel){try{return !!(sel&&sel.ok());}catch(e){return false;}}"
    # The per-format resilience ladder, the human's own moves in order: a wrong file -> retry the
    # SAME source once with the selection re-verified; wrong again / an error toast / a generation
    # timeout -> FALL THROUGH to the next visible source; every offering source failed -> bounded
    # refresh recovery; no source offered it at all -> say so honestly (never refresh-loop after
    # something that is not there). A wall always hands off to the user at once.
    "function downloadFormat(present,spec,done){var pi=0,redrives=0,attempted=0;function tryProvider(){"
    "if(pi>=present.length){"
    "if(attempted){recover(spec,done);return;}"
    "report(spec.key,false,'No visible source offers '+spec.name+'; download it by hand.');done();return;}"
    "var prov=present[pi++];trace('tryProvider',spec.key,prov[1]);"
    "if(!fmtBtnFor(prov)){var row=document.querySelector('#'+prov[0]+'-media-active');if(row){try{row.click();}catch(e){}}}"
    "until(function(){var b=fmtBtnFor(prov);if(b&&actionable(b))return {b:b};"
    "if(externalOnly(prov))return {skip:1};return null;},function(v){"
    "if(!v){report('provider',false,prov[1]+' did not open; trying the next source.');tryProvider();return;}"
    "if(v.skip){trace('skip',prov[1],'external only');"
    "report('provider',false,prov[1]+' opens the manufacturer site; trying the next source.');tryProvider();return;}"
    "try{v.b.click();}catch(e){}"
    "until(function(){return exportModalFor(prov);},function(modal){"
    "if(!modal){report('provider',false,prov[1]+' showed no formats; trying the next source.');tryProvider();return;}"
    "pickVerified(modal,prov,spec,function(ok,sel){"
    "if(!ok){report('provider',false,prov[1]+' has no '+spec.name+'; trying the next source.');closeModalFor(prov);tryProvider();return;}"
    "report(spec.key,true,'Selected '+spec.name+' plus the 3D model from '+prov[1]+'.');"
    # The download seek SENSES two states, reacting to whichever happens first: the button
    # enables (atomic verify + click), or the vendor's async re-render WIPES the selection -
    # which can also close the modal and keep the button disabled forever (live 2026-07-23), so
    # the reaction is a full bounded re-drive of this provider: re-open the modal, re-pick,
    # re-seek. A watchdog dead-end recovers (refresh); it never strands the run.
    "function seekDl(){until(function(){var d=dlBtnFor(prov);if(d)return {d:d};"
    "if(!selOn(sel))return {re:1};return null;},function(v2){"
    "if(!v2){report('download',false,'Select a format, then click Download.');recover(spec,done);return;}"
    "if(v2.re){trace('pick',spec.key,'selection wiped; redriving');"
    "if(++redrives>3){recover(spec,done);return;}"
    "pi=Math.max(0,pi-1);tryProvider();return;}"
    "if(!selOn(sel)){trace('pick',spec.key,'selection wiped at click; repicking');"
    "if(++redrives>3){recover(spec,done);return;}"
    "var m2=exportModalFor(prov)||modal;pickVerified(m2,prov,spec,function(ok2,sel2){"
    "if(!ok2){recover(spec,done);return;}sel=sel2;seekDl();});return;}"
    "try{v2.d.click();}catch(e){}attempted++;"
    "report('download',true,'Downloading '+spec.name+' from '+prov[1]+'; watching for the file.');"
    "awaitDownload(spec,function(){report('progress',true,'Finished '+spec.name+'.');done();},"
    "function(why){"
    "if(why==='wall'){recover(spec,done);return;}"
    "if(why==='wrongfile'&&!spec.__retried){spec.__retried=1;"
    "report(spec.key,false,'That was not the '+spec.name+' file; selecting it again.');"
    "pi=Math.max(0,pi-1);tryProvider();return;}"
    "trace('fallthrough',spec.key,why);"
    "report(spec.key,false,'That did not work ('+why+'); trying the next source for '+spec.name+'.');"
    "tryProvider();});},12000);}seekDl();});},12000);},12000);}tryProvider();}"
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
        # START_WD: the owner's "a successful run downloads in under 5 seconds" heuristic with
        # margin - no real download start within it means the attempt is dead (nostart). Margin
        # matters: a larger part's export began 9.8s after the click (live 2026-07-23, ATMEGA).
        "var GEN_WD=150000,START_WD=20000,MAX_REFRESH=3;"
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
