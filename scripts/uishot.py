#!/usr/bin/env python3
"""Screenshot the REAL Stockroom SPA headlessly, in both themes, from Linux or Windows.

Why this exists
---------------
The Windows pixel gate (`winshot`) only works when the desktop session is CONNECTED; on a
locked or disconnected session Windows hands back a 640x480 black frame, which stalled
visual verification for days at a stretch. This tool removes that dependency entirely: it
substitutes Playwright for pywebview as `run_windowed`'s `open_window` callable, so the
app boots exactly as it does on Windows -- real FastAPI context, real per-launch bearer
token injected into index.html from the first byte -- and only the window is different.

It is NOT a replacement for a real Windows shot when the thing under test is WebView2
behaviour (font rasterisation, the host chrome, DPI). It IS the right tool for layout,
spacing, tokens, hierarchy, empty states, and both-theme checks -- i.e. most UI work.

Usage
-----
    uv run python scripts/uishot.py --surface components
    uv run python scripts/uishot.py --surface search --themes dark
    uv run python scripts/uishot.py --surface components --width 1100   # narrow-width clipping
    uv run python scripts/uishot.py --surface all --out build/shots

`--width` is the lever for responsive checks: the detail pane's fixed-width chain means
the Specifications column collapses below ~1166px, so shooting at 1100 reproduces the
clipping the owner reported without touching a real window.

Exit code is non-zero if a requested surface could not be reached, so this can gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "build" / "shots"
DEFAULT_LIB = REPO / "libraries"

# Token probe: the values a visual regression most often silently breaks. Reported with
# every run so a shot is never interpreted against an unknown token state.
PROBE_JS = """() => {
  const cs = getComputedStyle(document.documentElement);
  const names = ['--c-band','--c-canvas','--r-card','--r-control',
                 '--fs-2xs','--fs-base','--fs-title'];
  const vars = Object.fromEntries(names.map(n => [n, cs.getPropertyValue(n).trim()]));
  const pick = (sel, prop) => {
    const el = document.querySelector(sel);
    return el ? getComputedStyle(el)[prop] : null;
  };
  return {
    vars,
    bandBg: pick('.bg-band', 'backgroundColor'),
    controlRadius: pick('.rounded-control', 'borderRadius'),
    docScrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
  };
}"""


def _goto_surface(page, surface: str) -> bool:
    """Navigate to a named surface. Returns False if it could not be reached."""
    if surface == "components":
        rows = page.locator('[data-dev-id^="list.row"]')
        if rows.count():
            rows.first.click()
            page.wait_for_timeout(1200)
        return True
    if surface == "search":
        page.keyboard.press("Control+k")
        page.wait_for_timeout(1200)
        return page.locator('[data-dev-id="search.root"]').count() > 0
    if surface in {"projects", "settings"}:
        nav = page.locator(f'[data-dev-id="rail.nav-{surface}"]')
        if not nav.count():
            return False
        nav.first.click()
        page.wait_for_timeout(1500)
        return True
    raise SystemExit(f"unknown surface: {surface}")


def _close_surface(page, surface: str) -> None:
    if surface == "search":
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)


def run(args) -> int:
    from playwright.sync_api import sync_playwright

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    surfaces = (
        ["components", "search", "projects", "settings"]
        if args.surface == "all"
        else [args.surface]
    )
    themes = [t.strip() for t in args.themes.split(",") if t.strip()]
    failures: list[str] = []

    def opener(base_url: str, _token: str) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--force-color-profile=srgb"])
            page = browser.new_page(
                viewport={"width": args.width, "height": args.height},
                device_scale_factor=args.scale,
            )
            console: list[str] = []
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console.append(str(e)))

            page.goto(base_url, wait_until="networkidle")
            page.wait_for_timeout(1200)

            for surface in surfaces:
                if not _goto_surface(page, surface):
                    print(f"  !! could not reach surface: {surface}")
                    failures.append(surface)
                    continue
                for theme in themes:
                    page.evaluate(
                        "t => document.documentElement.setAttribute('data-theme', t)", theme
                    )
                    page.wait_for_timeout(600)
                    path = out / f"{surface}-{theme}-{args.width}w.png"
                    page.screenshot(path=str(path), full_page=args.full_page)
                    print(f"  shot {path.name}")
                _close_surface(page, surface)

            probe = page.evaluate(PROBE_JS)
            print("  probe " + json.dumps(probe))
            # A horizontal overflow means content is being clipped at this width.
            if probe["docScrollW"] > probe["clientW"]:
                print(
                    f"  !! horizontal overflow: scrollWidth={probe['docScrollW']} "
                    f"> clientWidth={probe['clientW']} (content is clipped at {args.width}px)"
                )
            if console:
                print(f"  console errors ({len(console)}): {console[:4]}")
            browser.close()

    sys.path.insert(0, str(REPO / "app" / "backend"))
    from stockroom.host.run import run_windowed

    print(f"booting app (library={args.library}) ...")
    run_windowed(libraries_root=Path(args.library), open_window=opener)
    if failures:
        print(f"FAILED to reach: {', '.join(failures)}")
        return 1
    print(f"ok -> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--surface", default="components",
                    choices=["components", "search", "projects", "settings", "all"])
    ap.add_argument("--themes", default="dark,light", help="comma list: dark,light")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--scale", type=int, default=2, help="device scale factor (DPR)")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--library", default=str(DEFAULT_LIB))
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
