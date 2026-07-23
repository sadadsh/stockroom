"""Build the guided-capture heads-up display injected into a vendor CAD page. Pure string
builder (no pywebview) - imports and unit-tests on Linux; window.py injects it on the cad
window's `loaded` event, before the vendor driver.

The overlay is a compact fixed HUD rendered INSIDE the vendor's own page (the remote DigiKey
product page), so a user watches the capture complete instead of guessing. It shows the part
name + a DigiKey vendor pill, a per-requirement checklist, an X / Y "Files Captured" meter, the
current auto-action line, a Your Turn block when the user must act, and a Complete flash when
every needed file has landed. Its `window.__STOCKROOM_OVERLAY__` bridge is host to page ONLY:

  report({step, ok, message}) - the Phase 2 vendor driver narrates each auto-click step here.
  received({requirement})     - the host ticks a checklist row green + advances the meter as a
                                file lands (window.py pushes this).
  action({action, message, needsUser}) - update the auto-action line; reveal the Your Turn block
                                when the step needs the user.
  complete()                  - reveal the Complete flash (also fired automatically at full meter).

It renders in the REMOTE page (not the SPA), so styling is INLINE only - no SPA design tokens
reach here, no per-launch token, no js_api. Theme-aware via prefers-color-scheme, motion disabled
under prefers-reduced-motion. A single guarded IIFE with every method wrapped in try/catch, so a
missing element or a hostile/changing DOM is a silent no-op, never a throw.
"""

from __future__ import annotations

import html
import json

_LABELS = {
    "kicad_symbol": "KiCad Symbol",
    "kicad_footprint": "KiCad Footprint",
    "kicad_model": "KiCad 3D Model",
    "altium_symbol": "Altium Symbol",
    "altium_footprint": "Altium Footprint",
}

# The HUD stylesheet: light styles by default, a dark override under prefers-color-scheme, and a
# reduced-motion rule that removes the panel transition and the Complete flash animation. Received
# green is 3:1+ on both surfaces (#1a7f37 on white, #3fb950 on slate). Card 14px / inner 8px radius.
_STYLE = (
    "#__stockroom_overlay__{position:fixed;top:16px;right:16px;z-index:2147483647;width:300px;"
    "box-sizing:border-box;font:13px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',"
    "system-ui,sans-serif;color:#1f2328;background:linear-gradient(180deg,#ffffff,#f4f6f8);"
    "border:1px solid #d0d7de;border-radius:14px;"
    "box-shadow:0 8px 28px rgba(31,35,40,.16),0 2px 6px rgba(31,35,40,.08);"
    "padding:14px 15px;overflow:hidden;transition:opacity .2s ease;}"
    "#__stockroom_overlay__ *{box-sizing:border-box;margin:0;}"
    ".sk-hd{display:flex;align-items:center;justify-content:space-between;gap:8px;}"
    ".sk-brand{display:flex;align-items:center;gap:7px;}"
    ".sk-dot{width:8px;height:8px;border-radius:999px;background:#bf8700;"
    "box-shadow:0 0 0 3px rgba(191,135,0,.16);}"
    ".sk-name{font-weight:600;font-size:12px;color:#656d76;}"
    ".sk-vendor{font-weight:600;font-size:11px;padding:3px 9px;border-radius:999px;"
    "color:#0a3069;background:#ddf4ff;border:1px solid #b6e3ff;white-space:nowrap;}"
    ".sk-part{font-size:16px;font-weight:650;letter-spacing:-.01em;margin-top:9px;color:#1f2328;"
    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}"
    ".sk-meter{margin-top:13px;}"
    ".sk-meter-top{display:flex;align-items:baseline;justify-content:space-between;}"
    ".sk-meter-label{font-size:11px;font-weight:600;color:#656d76;}"
    ".sk-meter-num{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;color:#1f2328;}"
    ".sk-track{display:flex;gap:4px;margin-top:7px;}"
    ".sk-seg{flex:1;height:6px;border-radius:999px;background:#e7ebef;transition:background .25s ease;}"
    ".sk-seg.sk-on{background:#1a7f37;}"
    ".sk-list{display:flex;flex-direction:column;gap:2px;margin-top:13px;}"
    ".sk-row{display:flex;align-items:center;gap:9px;padding:5px 7px;border-radius:8px;"
    "color:#656d76;transition:color .2s ease,background .2s ease;}"
    ".sk-mark{width:16px;height:16px;border-radius:999px;border:1.5px solid #afb8c1;flex:none;"
    "display:flex;align-items:center;justify-content:center;font-size:11px;line-height:1;color:#fff;}"
    ".sk-row.sk-rec{color:#1f2328;background:rgba(26,127,55,.08);}"
    ".sk-row.sk-rec .sk-mark{background:#1a7f37;border-color:#1a7f37;}"
    ".sk-lbl{font-size:13px;}"
    ".sk-action{font-size:12px;color:#656d76;margin-top:13px;padding-top:11px;"
    "border-top:1px solid #d8dee4;line-height:1.4;}"
    ".sk-turn{display:none;margin-top:10px;padding:10px 11px;border-radius:8px;"
    "background:#fff8e6;border:1px solid #f2d492;}"
    ".sk-turn.sk-show{display:block;}"
    ".sk-turn-h{font-size:12px;font-weight:700;color:#9a6700;}"
    ".sk-turn-m{font-size:12.5px;color:#4d3800;line-height:1.4;margin-top:3px;}"
    ".sk-complete{position:absolute;inset:0;display:none;flex-direction:column;align-items:center;"
    "justify-content:center;gap:10px;"
    "background:linear-gradient(180deg,rgba(26,127,55,.97),rgba(19,101,45,.98));color:#ffffff;}"
    ".sk-complete.sk-show{display:flex;animation:sk-pop .32s ease-out;}"
    ".sk-check{width:52px;height:52px;border-radius:999px;background:rgba(255,255,255,.16);"
    "border:2px solid rgba(255,255,255,.85);display:flex;align-items:center;justify-content:center;"
    "font-size:28px;line-height:1;animation:sk-ring .4s ease-out;}"
    ".sk-complete-t{font-size:17px;font-weight:700;}"
    "@keyframes sk-pop{from{opacity:0;transform:scale(.96);}to{opacity:1;transform:scale(1);}}"
    "@keyframes sk-ring{from{transform:scale(.7);opacity:0;}to{transform:scale(1);opacity:1;}}"
    "@media (prefers-color-scheme: dark){"
    "#__stockroom_overlay__{color:#e6edf3;background:linear-gradient(180deg,#161b22,#0d1117);"
    "border-color:#2a3441;box-shadow:0 12px 34px rgba(0,0,0,.5),0 2px 8px rgba(0,0,0,.4);}"
    ".sk-name{color:#8b949e;}"
    ".sk-vendor{color:#79c0ff;background:rgba(56,139,253,.15);border-color:rgba(56,139,253,.4);}"
    ".sk-part{color:#e6edf3;}"
    ".sk-meter-label{color:#8b949e;}.sk-meter-num{color:#e6edf3;}"
    ".sk-seg{background:#21262d;}.sk-seg.sk-on{background:#3fb950;}"
    ".sk-mark{border-color:#484f58;}"
    ".sk-row{color:#8b949e;}.sk-row.sk-rec{color:#e6edf3;background:rgba(63,185,80,.12);}"
    ".sk-row.sk-rec .sk-mark{background:#238636;border-color:#2ea043;}"
    ".sk-action{color:#8b949e;border-top-color:#21262d;}"
    ".sk-turn{background:rgba(187,128,9,.12);border-color:rgba(187,128,9,.45);}"
    ".sk-turn-h{color:#e3a008;}.sk-turn-m{color:#f0d999;}"
    ".sk-complete{background:linear-gradient(180deg,rgba(35,134,54,.97),rgba(26,101,44,.98));}"
    "}"
    "@media (prefers-reduced-motion: reduce){"
    "#__stockroom_overlay__{transition:none;}"
    ".sk-seg{transition:none;}"
    ".sk-row{transition:none;}"
    ".sk-complete.sk-show{animation:none;}"
    ".sk-check{animation:none;}"
    "}"
)


def _rows_html(needs: list[str]) -> tuple[str, int]:
    """The checklist rows for the needed requirements (in _LABELS order preserved by `needs`),
    each with a stable id keyed by its requirement value, and the count of rows (the meter total)."""
    rows = []
    for n in needs:
        label = _LABELS.get(n)
        if label is None:
            continue
        rows.append(
            f'<div id="__stockroom_row_{n}__" class="sk-row">'
            '<span class="sk-mark"></span>'
            f'<span class="sk-lbl">{label}</span></div>'
        )
    return "".join(rows), len(rows)


def build_overlay_js(needs: list[str], vendor: str, part_name: str = "") -> str:
    """The guided-capture HUD as a single guarded IIFE string. `needs` are the Requirement `.value`
    strings this capture collects; `vendor` is the display label shown in the pill (e.g. DigiKey);
    `part_name` is shown as the header focal point when non-empty (Plan 03 threads it through). Every
    interpolated value is HTML-escaped then JSON-encoded, so neither the page markup nor the JS
    string can be broken out of. `needs` + `total` are baked in so received() and the meter work with
    no server round trip."""
    vendor = html.escape(vendor or "the vendor")
    rows, total = _rows_html(list(needs))
    segs = "".join('<span class="sk-seg"></span>' for _ in range(total))
    part = f'<div class="sk-part">{html.escape(part_name)}</div>' if part_name else ""

    inner = (
        '<div class="sk-hd">'
        '<span class="sk-brand"><span class="sk-dot"></span>'
        '<span class="sk-name">Stockroom</span></span>'
        f'<span class="sk-vendor">{vendor}</span></div>'
        f"{part}"
        '<div class="sk-meter"><div class="sk-meter-top">'
        '<span class="sk-meter-label">Files Captured</span>'
        f'<span class="sk-meter-num" id="__stockroom_meter__">0 / {total}</span></div>'
        f'<div class="sk-track">{segs}</div></div>'
        f'<div class="sk-list">{rows}</div>'
        '<div class="sk-action" id="__stockroom_action__">'
        "Watching for downloads. Follow the guidance in the window.</div>"
        '<div class="sk-turn" id="__stockroom_yourturn__">'
        '<div class="sk-turn-h">Your Turn</div>'
        '<div class="sk-turn-m" id="__stockroom_turnmsg__"></div></div>'
        '<div class="sk-complete" id="__stockroom_complete__">'
        '<div class="sk-check">✓</div>'
        '<div class="sk-complete-t">Complete</div></div>'
    )

    j = json.dumps
    return (
        "(function(){try{"
        "var st=document.createElement('style');"
        f"st.textContent={j(_STYLE)};"
        "(document.head||document.documentElement).appendChild(st);"
        "var prev=document.getElementById('__stockroom_overlay__');if(prev)prev.remove();"
        "var wrap=document.createElement('div');wrap.id='__stockroom_overlay__';"
        f"wrap.innerHTML={j(inner)};"
        "(document.body||document.documentElement).appendChild(wrap);"
        f"var TOTAL={total};var COUNT=0;var REC={{}};"
        "function byId(id){return document.getElementById(id);}"
        "function setAction(m){try{var a=byId('__stockroom_action__');"
        "if(a&&m!=null)a.textContent=String(m);}catch(e){}}"
        "function showComplete(){try{var c=byId('__stockroom_complete__');"
        "if(c)c.className='sk-complete sk-show';}catch(e){}}"
        "window.__STOCKROOM_OVERLAY__={"
        "report:function(x){try{if(x&&x.message!=null)setAction(x.message);}catch(e){}},"
        "received:function(x){try{"
        "var r=x&&(x.requirement!=null?x.requirement:x);if(r==null)return;r=String(r);"
        "if(REC[r])return;REC[r]=true;COUNT++;"
        "var row=byId('__stockroom_row_'+r+'__');"
        "if(row){if(row.className.indexOf('sk-rec')<0)row.className=row.className+' sk-rec';"
        "var m=row.querySelector('.sk-mark');if(m)m.textContent='\\u2713';}"
        "var segs=document.querySelectorAll('#__stockroom_overlay__ .sk-seg');"
        "for(var i=0;i<segs.length;i++){segs[i].className=(i<COUNT)?'sk-seg sk-on':'sk-seg';}"
        "var mt=byId('__stockroom_meter__');if(mt)mt.textContent=COUNT+' / '+TOTAL;"
        "if(TOTAL>0&&COUNT>=TOTAL)showComplete();}catch(e){}},"
        "action:function(x){try{if(!x)return;setAction(x.message);"
        "var t=byId('__stockroom_yourturn__'),tm=byId('__stockroom_turnmsg__');"
        "if(x.needsUser){if(tm&&x.message!=null)tm.textContent=String(x.message);"
        "if(t)t.className='sk-turn sk-show';}else{if(t)t.className='sk-turn';}}catch(e){}},"
        "complete:function(){showComplete();}};"
        "}catch(e){}})();"
    )
