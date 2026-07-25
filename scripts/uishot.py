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


def _seed_workspace(base: Path) -> tuple[Path, Path]:
    """Build a throwaway library + KiCad project so the PROJECT surfaces can actually be shot.

    Without this, `--surface projects` only ever reaches "No projects are registered.", so the Health
    tab (Prepare, Assign Components, Rules Check, BOM) was not visually verifiable at all and a
    screenshot of it proved nothing. The seed is deliberately the awkward real-world case rather than
    a tidy one: the schematic's passives are placed from KiCad's DEFAULT library, so they carry the
    generic `Device:R` symbol that identifies no part, which is exactly what the assign surface is for.

    Returns (libraries_root, project_dir). Both live under `base`, never in the owner's real library.
    """
    import shutil
    import subprocess

    libs = base / "libraries"
    shutil.copytree(DEFAULT_LIB, libs)
    parts = libs / "Stockroom" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    # Two library resistors that are genuinely hard to tell apart: same value and package, different
    # tolerance. Neither may ever be auto-assigned, and both must be offered as candidates.
    for pid, mpn, tol, tier in (("r10k1", "RC0402FR-0710KL", "1%", "1005Metric"),
                                ("r10k5", "RC0402JR-0710KL", "5%", "1005Metric")):
        (parts / f"{pid}.json").write_text(json.dumps({
            "id": pid, "display_name": f"10k 0402 {tol}", "category": "Resistors",
            "description": f"10 kOhm {tol} 0402 thick film", "mpn": mpn,
            "manufacturer": "Yageo", "passive": True,
            "eda": {"kicad": {"symbol": {"lib": "Device", "name": "R"},
                              "footprint": {"lib": "Resistor_SMD", "name": f"R_0402_{tier}"}}},
            "specs": {"Resistance": "10 kOhm", "Tolerance": tol, "Package": "0402"},
        }, indent=2), encoding="utf-8")
    (parts / "c100n.json").write_text(json.dumps({
        "id": "c100n", "display_name": "100nF 0402", "category": "Capacitors",
        "description": "100 nF 16V X7R 0402", "mpn": "CL05B104KO5NNNC",
        "manufacturer": "Samsung", "passive": True,
        "eda": {"kicad": {"symbol": {"lib": "Device", "name": "C"},
                          "footprint": {"lib": "Capacitor_SMD", "name": "C_0402_1005Metric"}}},
        "specs": {"Capacitance": "100 nF", "Package": "0402"},
    }, indent=2), encoding="utf-8")

    # The in-repo library is backed by the ENCLOSING app repo, so a copy in a temp directory has no
    # git at all and registering a project (which commits the project record) fails. Give the seeded
    # library its own repo so every library-side mutation behaves as it does for real.
    for cmd in (["init", "-b", "main"], ["config", "user.email", "shot@local"],
                ["config", "user.name", "shot"], ["add", "-A"], ["commit", "-m", "seed library"]):
        subprocess.run(["git", "-C", str(libs), *cmd], check=True, capture_output=True)

    proj = base / "SeedBoard"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "SeedBoard.kicad_pro").write_text("{}", encoding="utf-8")

    def sym(ref, lib_id, value, footprint, uid):
        return (
            "\t(symbol\n"
            f'\t\t(lib_id "{lib_id}")\n\t\t(at 10 10 0)\n\t\t(unit 1)\n'
            "\t\t(in_bom yes)\n\t\t(dnp no)\n"
            f'\t\t(uuid "{uid}")\n'
            f'\t\t(property "Reference" "{ref}" (at 10 8 0))\n'
            f'\t\t(property "Value" "{value}" (at 12 10 0))\n'
            f'\t\t(property "Footprint" "{footprint}" (at 10 10 0))\n'
            '\t\t(property "Datasheet" "~" (at 10 10 0))\n'
            '\t\t(instances\n\t\t\t(project "SeedBoard"\n'
            f'\t\t\t\t(path "/seed"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n'
            "\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n"
        )

    r_fp, c_fp = "Resistor_SMD:R_0402_1005Metric", "Capacitor_SMD:C_0402_1005Metric"
    body = "".join([
        # Five 10k resistors: one group, two indistinguishable candidates.
        *[sym(f"R{n}", "Device:R", "10k", r_fp, f"s-r{n}") for n in (1, 2, 3, 9, 10)],
        # A 47k group nothing in the library matches, so the honest no-candidate state renders too.
        sym("R11", "Device:R", "47k", r_fp, "s-r11"),
        # Three 100nF capacitors: a second kind, proving groups do not bleed across symbols.
        *[sym(f"C{n}", "Device:C", "100n", c_fp, f"s-c{n}") for n in (1, 2, 3)],
    ])
    (proj / "SeedBoard.kicad_sch").write_text(
        "(kicad_sch\n\t(version 20260306)\n" + body + ")\n", encoding="utf-8")

    for cmd in (["init", "-b", "main"], ["config", "user.email", "shot@local"],
                ["config", "user.name", "shot"], ["add", "."], ["commit", "-m", "seed board"]):
        subprocess.run(["git", "-C", str(proj), *cmd], check=True, capture_output=True)
    return libs, proj


def _dismiss_onboarding(page, base_url: str, token: str) -> None:
    """Mark onboarding complete for a SEEDED library, then reload.

    `library_location.ships_in_repo` treats only the library committed inside the app repo as
    pre-onboarded, so a throwaway library in a temp directory lands on the first-run welcome screen and
    the nav rail is never reachable. Completing onboarding is a genuine user action, so the seed run
    performs it rather than faking the gate away.
    """
    page.request.post(f"{base_url.rstrip('/')}/api/onboarding/complete",
                      headers={"Authorization": f"Bearer {token}"})
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1500)


def _register_seed(page, proj: Path) -> bool:
    """Register the seeded project through the REAL register control, then select it. Driving the app's
    own affordance (rather than posting to the API) keeps this a genuine end-to-end path."""
    page.locator('[data-dev-id="rail.nav-projects"]').first.click()
    page.wait_for_timeout(800)
    box = page.locator('[data-dev-id="projects.register-input"]')
    if not box.count():
        return False
    box.first.fill(str(proj))
    page.locator('[data-dev-id="projects.register-action"]').first.click()
    page.wait_for_timeout(2500)
    rows = page.locator('[data-dev-id="projects.row"]')
    if not rows.count():
        return False
    rows.first.click()
    page.wait_for_timeout(1500)
    return True


def _goto_surface(page, surface: str) -> bool:
    """Navigate to a named surface. Returns False if it could not be reached."""
    if surface == "project-health":
        # The seeded project is already selected by _register_seed; open its Health tab and scroll the
        # assign surface into view (it sits below Prepare, so a viewport shot would otherwise miss it).
        tab = page.get_by_role("tab", name="Health")
        if not tab.count():
            return False
        tab.first.click()
        page.wait_for_timeout(2000)
        section = page.locator('[data-dev-id="projects.assign"]')
        if section.count():
            section.first.scroll_into_view_if_needed()
            page.wait_for_timeout(800)
        return True
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

    import tempfile

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    surfaces = (
        ["components", "search", "projects", "settings"]
        if args.surface == "all"
        else [args.surface]
    )
    themes = [t.strip() for t in args.themes.split(",") if t.strip()]
    failures: list[str] = []

    # A project surface needs a project. `project-health` implies the seed, so the surface can never be
    # requested in a state where it silently degrades to the "No projects are registered" empty view
    # and a green shot proves nothing.
    seed = args.seed or any(s.startswith("project-") for s in surfaces)
    scratch: tempfile.TemporaryDirectory | None = None
    library = Path(args.library)
    seed_project: Path | None = None
    if seed:
        scratch = tempfile.TemporaryDirectory(prefix="uishot-seed-")
        library, seed_project = _seed_workspace(Path(scratch.name))
        print(f"  seeded library + project under {scratch.name}")

    def opener(base_url: str, token: str) -> None:
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

            if seed_project is not None:
                _dismiss_onboarding(page, base_url, token)
            if seed_project is not None and not _register_seed(page, seed_project):
                print("  !! could not register the seeded project")
                failures.append("seed")
                browser.close()
                return

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

    print(f"booting app (library={library}) ...")
    try:
        run_windowed(libraries_root=library, open_window=opener)
    finally:
        if scratch is not None:
            scratch.cleanup()
    if failures:
        print(f"FAILED to reach: {', '.join(failures)}")
        return 1
    print(f"ok -> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--surface", default="components",
                    choices=["components", "search", "projects", "project-health",
                             "settings", "all"])
    ap.add_argument("--seed", action="store_true",
                    help="seed a throwaway library + KiCad project (implied by a project-* surface)")
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
