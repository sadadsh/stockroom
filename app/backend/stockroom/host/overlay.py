"""Build the guided-capture overlay injected into a vendor CAD page. Pure string builder (no
pywebview) - imports and unit-tests on Linux; window.py injects it on the cad window's `loaded`
event, before the vendor driver.

The overlay is a small fixed panel that shows, inside the vendor's own page, what this part is
here to collect (its Requirement checklist) and a live status line the driver reports into via
`window.__STOCKROOM_OVERLAY__.report({step, ok, message})` - so the window can say
"Selected KiCad + Altium, click Download" or "Please pick the format" instead of leaving the user
guessing. It renders in the REMOTE vendor page (not the SPA), so its styling is a neutral dark
card with inline styles - no SPA design tokens reach here. Reduced-motion respected. Guarded so
it never throws on an unexpected page.
"""

from __future__ import annotations

import json

_LABELS = {
    "kicad_symbol": "KiCad Symbol",
    "kicad_footprint": "KiCad Footprint",
    "kicad_model": "KiCad 3D Model",
    "altium_symbol": "Altium Symbol",
    "altium_footprint": "Altium Footprint",
}

_CONTAINER_STYLE = (
    "position:fixed;top:16px;right:16px;z-index:2147483647;max-width:280px;"
    "background:#0b0f14;color:#e6edf3;font:13px/1.45 system-ui,-apple-system,sans-serif;"
    "border:1px solid #22303c;border-radius:12px;box-shadow:0 10px 34px rgba(0,0,0,.5);"
    "padding:12px 14px;"
)


def build_overlay_js(needs: list[str], vendor: str) -> str:
    vendor = vendor or "the vendor"
    rows = "".join(
        f'<li style="margin:2px 0;">{_LABELS[n]}</li>' for n in needs if n in _LABELS
    )
    inner = (
        '<div style="font-weight:600;margin-bottom:6px;">Stockroom Guided Capture</div>'
        f'<div style="opacity:.7;margin-bottom:8px;">Getting these from {vendor}:</div>'
        f'<ul style="margin:0 0 8px;padding-left:16px;">{rows}</ul>'
        '<div id="__stockroom_overlay_status__" '
        'style="padding-top:8px;border-top:1px solid #22303c;opacity:.85;">'
        "Follow the highlighted steps and click Download.</div>"
    )
    j = json.dumps
    return (
        "(function(){try{"
        "var st=document.createElement('style');"
        "st.textContent='#__stockroom_overlay__{transition:opacity .2s ease}"
        "@media (prefers-reduced-motion: reduce){#__stockroom_overlay__{transition:none}}';"
        "(document.head||document.documentElement).appendChild(st);"
        "var prev=document.getElementById('__stockroom_overlay__');if(prev)prev.remove();"
        "var wrap=document.createElement('div');wrap.id='__stockroom_overlay__';"
        f"wrap.setAttribute('style',{j(_CONTAINER_STYLE)});"
        f"wrap.innerHTML={j(inner)};"
        "(document.body||document.documentElement).appendChild(wrap);"
        "window.__STOCKROOM_OVERLAY__={report:function(x){try{"
        "var s=document.getElementById('__stockroom_overlay_status__');"
        "if(s&&x&&x.message)s.textContent=x.message;}catch(e){}}};"
        "}catch(e){}})();"
    )
