"""Guidance-only bridge for the retired pywebview capture window.

Provider automation belongs exclusively to :mod:`stockroom.capture.vendors`, where one
version-pinned browser implementation runs behind the API on every supported platform.  The
legacy host API may still open a remote page for an old caller, but it must never inject a second
vendor implementation or operate page controls.
"""

from __future__ import annotations

import json


def build_driver_js(vendor: str, formats: list[str], target_url: str = "") -> str:
    """Report useful manual guidance without inspecting or operating the provider page."""

    key = (vendor or "").strip() or "this vendor"
    requested = ", ".join(item for item in formats if isinstance(item, str) and item.strip())
    formats_text = requested or "the required CAD formats"
    message = (
        f"No injected automation is active for {key}; use Stockroom's managed capture route "
        f"for {formats_text}."
    )
    # The retired host bridge does not need the task URL. Deliberately consume but never inject it:
    # remote page content must not receive task identity through this compatibility no-op.
    _ = target_url
    return (
        "(function(){try{var o=window.__STOCKROOM_OVERLAY__;"
        "o&&o.report({step:'driver',ok:false,message:"
        + json.dumps(message)
        + "});}catch(e){}})();"
    )


__all__ = ["build_driver_js"]
