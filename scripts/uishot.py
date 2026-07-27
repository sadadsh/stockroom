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
  // The RESOLVED size of real text, not the declared token. A custom property holding a calc()
  // reports its declared text verbatim, so `--fs-base: calc(12px * clamp(...))` looked identical at
  // every window width and proved nothing about whether the responsive scale actually responds.
  // This reads the computed font-size off elements that USE the scale.
  const fs = {
    base: pick('.text-base', 'fontSize') || pick('body', 'fontSize'),
    xs: pick('.text-xs', 'fontSize'),
    title: pick('.text-title', 'fontSize'),
  };
  return {
    vars,
    fs,
    bandBg: pick('.bg-band', 'backgroundColor'),
    controlRadius: pick('.rounded-control', 'borderRadius'),
    docScrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    // THE RAIL'S ACTUAL STATE AT CAPTURE. The nav rail peeks open on hover as an opaque overlay
    // that floats OVER the page, and the theme toggle sits at the bottom of the rail - so clicking
    // it to reach light theme parked the pointer on the rail and photographed the overlay covering
    // the components list, in every light shot, silently, since the peek shipped. Reported on every
    // run because a shot with the rail open is not a shot of the page, and nothing else says so.
    railW: (() => {
      const r = document.querySelector('[data-dev-id="rail.root"]');
      return r ? Math.round(r.getBoundingClientRect().width) : null;
    })(),
    railHovered: (() => {
      const r = document.querySelector('[data-dev-id="rail.root"]');
      return r ? r.matches(':hover') : null;
    })(),
  };
}"""


# Box probe: what a named element ACTUALLY measures on screen, and how much of it is EMPTY.
#
# Every layout slice in this repo has had to answer the same two questions and has answered them
# by eye, which is how a 205px-wide Specifications column and a 965px portrait 3D stage both
# shipped. `w`/`h` settle "is this column squished"; `tail` settles "is this column mostly dead
# space" - it is the distance from the bottom of the element's LAST rendered child to the bottom of
# the element's own content box, which is the number a person reads as a void. `overflowX`/`clipped`
# say whether the box is lying about what it contains.
#
# It reports EVERY match for an id, not just the first: a repeated dev-id (`detail.spec-group`) is
# exactly where a per-instance overflow hides.
MEASURE_JS = """(ids) => {
  const out = {};
  for (const id of ids) {
    const els = Array.from(document.querySelectorAll(`[data-dev-id="${id}"]`));
    out[id] = els.map((el) => {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const padB = parseFloat(cs.paddingBottom) || 0;
      // the visible bottom edge of real content, over element children only: text nodes have no
      // box, so a text-only container reports tail 0 rather than a false void.
      const kids = Array.from(el.children);
      const lastBottom = kids.length
        ? Math.max(...kids.map((k) => k.getBoundingClientRect().bottom))
        : r.bottom - padB;
      // WHERE the box sits, and where its glyph sits inside it. The batch plan flagged that this
      // probe could say a box had no dead space at its FOOT while saying nothing about its
      // position - so "why is this icon 11px right of the others" was unanswerable without
      // reasoning about flex maths, which is exactly what burned a session's passes.
      const svg = el.querySelector("svg");
      const sr = svg && svg.getBoundingClientRect();
      return {
        w: Math.round(r.width),
        h: Math.round(r.height),
        left: Math.round(r.left * 10) / 10,
        top: Math.round(r.top * 10) / 10,
        // the centre of the FIRST svg glyph inside the box, in page coordinates: the number that
        // settles whether a row of icons shares one centre line.
        glyphCx: sr ? Math.round((sr.left + sr.width / 2) * 10) / 10 : null,
        padL: Math.round(parseFloat(cs.paddingLeft) || 0),
        padR: Math.round(parseFloat(cs.paddingRight) || 0),
        justify: cs.justifyContent,
        gap: cs.columnGap,
        scrollW: el.scrollWidth,
        scrollH: el.scrollHeight,
        // dead space at the foot of the box, in CSS px. Negative would mean content overflows.
        tail: Math.round(r.bottom - padB - lastBottom),
        overflowX: el.scrollWidth > el.clientWidth,
        clipped: el.scrollHeight > el.clientHeight,
      };
    });
  }
  return out;
}"""


# How long a real UI transition is allowed to take before we call it a failure. A ceiling, never a
# detector: every wait below polls for the element it actually needs and returns the instant it is
# there, so this only bounds how long a genuine failure takes to report. A fixed sleep in its place
# reported "the parts list is empty" on any machine slower than the sleep - a WRONG answer, not a
# slow one, which is exactly what a clock-as-detector produces.
_UI_TIMEOUT_MS = 10_000


def _api_path(url: str) -> str:
    """The path of `url` with its per-launch host and query stripped, so repeats of the same
    failing endpoint collapse into one counted line instead of N unique ones."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return parts.path or url


def _vanishes(locator, timeout_ms: int = _UI_TIMEOUT_MS) -> bool:
    """True once `locator` is gone. The closing twin of `_appears`: dismissing a modal and then
    clicking what it covered has to wait on the modal ACTUALLY being gone, not on a sleep."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        locator.wait_for(state="detached", timeout=timeout_ms)
        return True
    except PlaywrightTimeoutError:
        return False


def _appears(locator, timeout_ms: int = _UI_TIMEOUT_MS) -> bool:
    """True once `locator` is actually visible, polled. False if it never shows within the ceiling.

    This is the success signal a `wait_for_timeout` was standing in for. It returns as soon as the
    element is there (usually far under the ceiling), and a False here means the element genuinely
    never rendered - so the caller's failure message is a diagnosis rather than a guess.
    """
    # imported here, not at module scope: playwright is a dev-only dependency and the rest of this
    # script's helpers must stay importable without it (the same reason `main` defers its import).
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
        return True
    except PlaywrightTimeoutError:
        return False


# The `lib_symbols` block a real .kicad_sch always carries: KiCad copies every symbol it places
# INTO the file, so the sheet stands alone. The seed omitted it, and kicanvas threw
# `Cannot read properties of undefined (reading 'by_name')` out of `get lib_symbol` on EVERY
# Projects shot - so the viewer in those screenshots had crashed mid-paint and nobody could tell.
# Proven not to be a viewer bug: the same vendored bundle paints KiCad 10's own pic_programmer
# demo (.kicad_sch 20260101 and .kicad_pcb 20260206) with zero console errors.
# Text is Device:R and Device:C verbatim from KiCad 10.0.4's `Device.kicad_sym`, whitespace
# collapsed and renamed to the lib-id form a schematic uses.
_LIB_SYMBOLS = (
    "\t(lib_symbols\n"
    "\t\t(symbol \"Device:R\" (pin_numbers (hide yes)) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes) (property \"Reference\" \"R\" (at 2.032 0 90) (effects (font (size 1.27 1.27)))) (property \"Value\" \"R\" (at 0 0 90) (effects (font (size 1.27 1.27)))) (property \"Footprint\" \"\" (at -1.778 0 90) (effects (font (size 1.27 1.27)) (hide yes))) (property \"Datasheet\" \"~\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property \"Description\" \"Resistor\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property \"ki_keywords\" \"R res resistor\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property \"ki_fp_filters\" \"R_*\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (symbol \"R_0_1\" (rectangle (start -1.016 -2.54) (end 1.016 2.54) (stroke (width 0.254) (type default)) (fill (type none)))) (symbol \"R_1_1\" (pin passive line (at 0 3.81 270) (length 1.27) (name \"~\" (effects (font (size 1.27 1.27)))) (number \"1\" (effects (font (size 1.27 1.27))))) (pin passive line (at 0 -3.81 90) (length 1.27) (name \"~\" (effects (font (size 1.27 1.27)))) (number \"2\" (effects (font (size 1.27 1.27)))))) (embedded_fonts no))\n"
    "\t\t(symbol \"Device:C\" (pin_numbers (hide yes)) (pin_names (offset 0.254)) (exclude_from_sim no) (in_bom yes) (on_board yes) (property \"Reference\" \"C\" (at 0.635 2.54 0) (effects (font (size 1.27 1.27)) (justify left))) (property \"Value\" \"C\" (at 0.635 -2.54 0) (effects (font (size 1.27 1.27)) (justify left))) (property \"Footprint\" \"\" (at 0.9652 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes))) (property \"Datasheet\" \"~\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property \"Description\" \"Unpolarized capacitor\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property \"ki_keywords\" \"cap capacitor\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property \"ki_fp_filters\" \"C_*\" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (symbol \"C_0_1\" (polyline (pts (xy -2.032 0.762) (xy 2.032 0.762)) (stroke (width 0.508) (type default)) (fill (type none))) (polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762)) (stroke (width 0.508) (type default)) (fill (type none)))) (symbol \"C_1_1\" (pin passive line (at 0 3.81 270) (length 2.794) (name \"~\" (effects (font (size 1.27 1.27)))) (number \"1\" (effects (font (size 1.27 1.27))))) (pin passive line (at 0 -3.81 90) (length 2.794) (name \"~\" (effects (font (size 1.27 1.27)))) (number \"2\" (effects (font (size 1.27 1.27)))))) (embedded_fonts no))\n"
    "\t)\n"
)


def _seed_workspace(base: Path, source: Path | None = None) -> tuple[Path, Path]:
    """Build a throwaway library + KiCad project so the PROJECT surfaces can actually be shot.

    Without this, `--surface projects` only ever reaches "No projects are registered.", so the Health
    tab (Prepare, Assign Components, Rules Check, BOM) was not visually verifiable at all and a
    screenshot of it proved nothing. The seed is deliberately the awkward real-world case rather than
    a tidy one: the schematic's passives are placed from KiCad's DEFAULT library, so they carry the
    generic `Device:R` symbol that identifies no part, which is exactly what the assign surface is for.

    `source` is the library to COPY (default: the real one). It exists because `--library` used to
    be accepted and then silently ignored whenever the seed ran -- and `--click` implies the seed,
    so every clicked shot secretly photographed the real library no matter what was asked for.
    That cost a wrong read on 2026-07-27: a shot aimed at a library holding 184 CAD assets showed
    "holds no CAD files of its own", which looked like a backend bug and was the flag being dropped.
    A flag that is accepted and ignored is worse than no flag.

    Returns (libraries_root, project_dir). Both live under `base`, never in the owner's real library.
    """
    import shutil
    import subprocess

    libs = base / "libraries"
    shutil.copytree(source or DEFAULT_LIB, libs)
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

    # A part carrying the data Batch 3 stopped discarding, so the surfaces that show it can actually
    # be SEEN. Nothing in a real library has any of this yet (no part has been re-enriched since),
    # and a screenshot of a surface with no data proves nothing.
    #   - two distributors' descriptions and a spec they disagree about -> the alternates disclosure
    #   - six HTS codes -> the repeated-family row that collapses them
    #   - DigiKey stored FIRST with a full ladder, Mouser second -> proves the Mouser-first reorder
    #     is doing the work rather than the record order happening to be right
    #   - a SIX-tier ladder -> five bulk tiers is ODD, which is the case that used to leave a hole
    (parts / "vendordata.json").write_text(json.dumps({
        "id": "vendordata", "display_name": "AAA Vendor Data Probe",
        "category": "ICs",
        "description": "3A step-down converter, WSON-8",
        "mpn": "TPS62130RGTR", "manufacturer": "Texas Instruments",
        "datasheet": {"file": "", "source_url": "https://ti.com/lit/ds/symlink/tps62130.pdf",
                      "fetched_at": ""},
        "purchase": [
            {"vendor": "DigiKey", "url": "https://www.digikey.com/en/products/detail/x",
             "part_number": "296-35116-1-ND",
             "price_breaks": [{"qty": q, "price": p} for q, p in
                              ((1, 2.41), (10, 2.15), (25, 1.98), (100, 1.72),
                               (250, 1.55), (500, 1.41))],
             "stock": 4821, "currency": "USD", "fetched_at": ""},
            {"vendor": "Mouser", "url": "https://www.mouser.com/ProductDetail/y",
             "part_number": "595-TPS62130RGTR",
             "price_breaks": [{"qty": q, "price": p} for q, p in
                              ((1, 2.38), (10, 2.11), (100, 1.69), (1000, 1.32))],
             "stock": 12750, "currency": "USD", "fetched_at": ""},
        ],
        "specs": {
            "Package": "WSON-8", "Product Category": "Buck Converters",
            "Output Current": "3 A", "Tolerance": "1%",
            "Lifecycle": "Active", "Lead Time": "16 Weeks",
            "Country of Origin": "Japan", "US Tariff %": 0.0,
            "ECCN": "3A991",
            # a product photo, so the Sourcing column's Product Photo affordance is actually
            # reachable in a shot (punch 7 moved it there from a floating chip)
            "Image": "https://example.invalid/tps62130.jpg",
            "HTS Code (US)": "8542.39.0001", "HTS Code (CN)": "8542330000",
            "HTS Code (CA)": "8542.39.00.01", "HTS Code (JP)": "854239",
            "HTS Code (MX)": "85423901", "HTS Code (EU TARIC)": "8542390000",
        },
        "enrichment": {
            "Product Category": {"source": "mouser", "confidence": "high"},
            "Lead Time": {"source": "digikey", "confidence": "high"},
            "US Tariff %": {"source": "mouser", "confidence": "high"},
        },
        "alternates": {
            "description": [
                {"value": "3A step-down converter, WSON-8", "source": "mouser",
                 "confidence": "high"},
                {"value": "Buck Switching Regulator IC Positive Adjustable 3A",
                 "source": "digikey", "confidence": "high"},
            ],
            "Tolerance": [
                {"value": "1%", "source": "mouser", "confidence": "high"},
                {"value": "2%", "source": "digikey", "confidence": "high"},
            ],
        },
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

    # The field a KiCad placement carries its durable Stockroom binding in. Read from the registry so
    # the seed cannot drift from the app it is shooting.
    sys.path.insert(0, str(REPO / "app" / "backend"))
    from stockroom.projects.binding import field_for  # noqa: E402

    bind_field = field_for("kicad")

    placed = [0]  # placement index, so no two symbols land on the same coordinate

    def sym(ref, lib_id, value, footprint, uid, *, bound="", mpn=""):
        """One placed symbol. `bound` stamps the durable binding an earlier assignment would have
        left; `mpn` writes an MPN property, so a bound placement whose MPN disagrees with its part
        renders the DRIFT state. `uid=""` omits the uuid entirely, which is the legacy file that can
        only be bound by designator (the weak-link state)."""
        # Laid out on a real grid. Every symbol used to be written `(at 10 10 0)`, so the viewer
        # drew ten parts stacked on one another - which no KiCad-authored sheet ever looks like,
        # and which made the Projects screenshot useless as a picture of the viewer working.
        i = placed[0]
        placed[0] += 1
        x, y = 25.4 + (i % 5) * 25.4, 25.4 + (i // 5) * 25.4
        extra = ""
        if bound:
            extra += f'\t\t(property "{bind_field}" "{bound}" (at 0 0 0) (hide yes))\n'
        if mpn:
            extra += f'\t\t(property "MPN" "{mpn}" (at 0 0 0) (hide yes))\n'
        return (
            "\t(symbol\n"
            f'\t\t(lib_id "{lib_id}")\n\t\t(at {x} {y} 0)\n\t\t(unit 1)\n'
            "\t\t(in_bom yes)\n\t\t(dnp no)\n"
            + (f'\t\t(uuid "{uid}")\n' if uid else "")
            + f'\t\t(property "Reference" "{ref}" (at {x} {y - 2.54} 0))\n'
            f'\t\t(property "Value" "{value}" (at {x + 2.54} {y} 0))\n'
            f'\t\t(property "Footprint" "{footprint}" (at {x} {y} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            f'\t\t(property "Datasheet" "~" (at {x} {y} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            + extra
            + '\t\t(instances\n\t\t\t(project "SeedBoard"\n'
            f'\t\t\t\t(path "/seed"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n'
            "\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n"
        )

    r_fp, c_fp = "Resistor_SMD:R_0402_1005Metric", "Capacitor_SMD:C_0402_1005Metric"
    body = "".join([
        # Three unassigned 10k resistors: one group, two indistinguishable candidates.
        *[sym(f"R{n}", "Device:R", "10k", r_fp, f"s-r{n}") for n in (1, 2, 3)],
        # A 47k group nothing in the library matches, so the honest no-candidate state renders too.
        sym("R11", "Device:R", "47k", r_fp, "s-r11"),
        # Already assigned, and the four states the record has to tell apart. Without these the
        # bound ledger could only ever be shot empty, which would prove nothing about it.
        sym("R9", "Device:R", "10k", r_fp, "s-r9", bound="r10k1", mpn="RC0402FR-0710KL"),
        sym("R10", "Device:R", "10k", r_fp, "s-r10", bound="r10k1", mpn="WRONG-MPN"),
        sym("R12", "Device:R", "10k", r_fp, "", bound="r10k1", mpn="RC0402FR-0710KL"),
        *[sym(f"C{n}", "Device:C", "100n", c_fp, f"s-c{n}",
              bound="c100n", mpn="CL05B104KO5NNNC") for n in (1, 2)],
        sym("C3", "Device:C", "100n", c_fp, "s-c3", bound="c100n-deleted"),
    ])
    (proj / "SeedBoard.kicad_sch").write_text(
        "(kicad_sch\n\t(version 20260306)\n" + _LIB_SYMBOLS + body + ")\n", encoding="utf-8")

    # The per-user files a real KiCad project accumulates and, crucially, COMMITS: `.kicad_prl` is
    # one person's window layout and `fp-info-cache` is a regenerated machine cache, so both change
    # on every open and are what make two peers conflict on every pull. Seeded committed on purpose:
    # without them the Sync Hygiene surface could only ever be shot in its empty state, which would
    # prove nothing about it.
    (proj / "SeedBoard.kicad_prl").write_text('{"board":{"visible_layers":"fffffff"}}\n',
                                              encoding="utf-8")
    (proj / "fp-info-cache").write_text("# regenerated footprint cache\n", encoding="utf-8")
    backups = proj / "SeedBoard-backups"
    backups.mkdir(exist_ok=True)
    (backups / "SeedBoard-2026.zip").write_text("archive\n", encoding="utf-8")

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


# Health-tab surfaces, mapped to the dev-id they scroll to. The Health tab is far taller than one
# viewport, so "shoot the Health tab" is not a single shot and pretending otherwise means whatever is
# below the fold never gets looked at.
_HEALTH_SECTIONS = {
    "project-health": "projects.assign",
    "project-hygiene": "projects.hygiene",
    "project-library-pin": "projects.library-pin",
}


def _goto_surface(page, surface: str, select: str = "") -> bool:
    """Navigate to a named surface. Returns False if it could not be reached."""
    if surface in _HEALTH_SECTIONS:
        # The seeded project is already selected by _register_seed; open its Health tab and scroll the
        # requested section into view. `--full-page` cannot substitute for this: the app's #root is
        # `overflow:hidden` and the real scroller is an inner pane, so a full-page capture is still
        # exactly one viewport tall and silently misses everything below the fold.
        tab = page.get_by_role("tab", name="Health")
        if not tab.count():
            return False
        tab.first.click()
        page.wait_for_timeout(2000)
        section = page.locator(f'[data-dev-id="{_HEALTH_SECTIONS[surface]}"]')
        if not section.count():
            return False
        section.first.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        return True
    if surface in {"components", "part-vendor-data"}:
        # Navigate EXPLICITLY, never assume the app is still where it booted: when the run seeds a
        # project it registers it through the real Projects surface, so by the time a surface driver
        # runs the app is sitting on Projects. Without this, `--surface components --seed` produced a
        # screenshot of the PROJECTS page and reported success.
        nav = page.locator('[data-dev-id="rail.nav-components"]')
        if not nav.count():
            return False
        nav.first.click()
        # WAIT ON THE THING, not on a clock. A fixed sleep here reported "the parts list is empty"
        # on any machine slower than the sleep, which is a wrong diagnosis rather than a slow one:
        # `_appears` polls for the row itself and returns the moment it is there.
        # The row id is `components.row`. This used to look for `list.row`, which matches NOTHING, so
        # the click never happened and the driver returned True regardless - a selector that cannot
        # fail, reporting a shot it never took. Now an absent list is a failure, loudly.
        rows = page.locator('[data-dev-id="components.row"]')
        if not _appears(rows.first):
            print("  components: no part rows ever rendered, so a shot would prove nothing")
            return False
        if surface == "components":
            # WHICH part. Default is the first row, which is whatever sorts first by category - a
            # capacitor in the seeded library. That is fine for a layout shot and useless for any
            # shot about an ASSET: the part carrying a STEP model is several rows down, so a driven
            # 3D control (`--click detail.model-view-top`) landed on a part with no model at all and
            # the control was not on the page. `--select` names the row instead of hoping.
            if select:
                wanted = rows.filter(has_text=select)
                if not wanted.count():
                    names = rows.all_inner_texts()
                    print(
                        f"  components: no part row matching {select!r}; the list holds: "
                        + " | ".join(n.split("\n")[0] for n in names)
                    )
                    return False
                wanted.first.click()
            else:
                rows.first.click()
            _appears(page.locator('[data-dev-id="detail.root"]'))
            _await_land_pattern(page)
            return True
        # part-vendor-data: the seeded probe part is the only one carrying alternates and an HTS
        # family, and it is named to sort first. Both disclosures are OPENED, because what is behind
        # them is the entire point of the shot.
        probe = rows.filter(has_text="AAA Vendor Data Probe")
        if not probe.count():
            print("  part-vendor-data: the seeded probe part is not in the list")
            return False
        probe.first.click()
        missing = []
        for dev_id in ("detail.spec-family", "detail.alternates"):
            control = page.locator(f'[data-dev-id="{dev_id}"] button').first
            if not _appears(control):
                missing.append(dev_id)
                continue
            control.click()
            # the SUCCESS signal for a disclosure is its own aria-expanded, not a settle delay
            from playwright.sync_api import expect as _expect

            try:
                _expect(control).to_have_attribute(
                    "aria-expanded", "true", timeout=_UI_TIMEOUT_MS
                )
            except AssertionError:
                print(f"  part-vendor-data: {dev_id} did not open when clicked")
                return False
        if missing:
            # Name WHICH control is absent: "1/2 present" sends the next reader hunting, and the
            # whole reason this surface exists is to make the new controls observable.
            print(f"  part-vendor-data: these controls are not on the page: {', '.join(missing)}")
            return False
        return True
    if surface == "ingest":
        # Add-A-Part is a MODAL over Components, not a rail destination, so it is reached by
        # driving the real button - the same path a user takes. Without this surface the whole
        # add lane (and the bulk import panel inside it) could not be seen at all, and a UI you
        # cannot see is a defect in the harness, not an excuse to ship it unlooked-at.
        dialog = page.locator('[data-dev-id="addpart.root"]')
        # A second theme pass runs against the SAME page, where the dialog is already open and its
        # scrim swallows every click. Clicking the trigger again then times out for 30 s and reports
        # a failure that is really "already there", so the open state is checked first.
        if dialog.count():
            return True
        nav = page.locator('[data-dev-id="rail.nav-components"]')
        if not nav.count():
            return False
        nav.first.click()
        trigger = page.locator('[data-dev-id="components.add-parts"]')
        if not _appears(trigger.first):
            print("  ingest: the Add Parts button never rendered")
            return False
        trigger.first.click()
        # The SUCCESS signal is the dialog itself, never a sleep.
        if not _appears(page.locator('[data-dev-id="addpart.root"]').first):
            print("  ingest: the Add-A-Part dialog did not open")
            return False
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


def _set_theme(page, theme: str) -> str | None:
    """Switch the theme through the app's OWN toggle, and return an error string on failure.

    This used to be `documentElement.setAttribute('data-theme', t)`, which is a LIE for anything
    theme-dependent that is not pure CSS. Stamping the attribute flips the CSS variable set, so a
    shot looks convincingly light or dark - but `ThemeProvider`'s React state never moves, so every
    component that branches on `useTheme().theme` keeps rendering the theme it booted in.

    MEASURED 2026-07-25, and it silently invalidated a real verification: `PreviewImage`,
    `StockAssetPreview`, `SvgViewport` and `SvgDiffViewport` all pick their CSS `filter` from
    `theme === "dark"`. Under attribute-stamping, a "light" capture still carried `invert(1)`, so
    black KiCad line-art rendered as pure white rgb(255) on a light rgb(245) card in BOTH shots. A
    fix to that very filter measured as having made things WORSE, when what was actually being
    photographed was this function.

    So: read the real state back off the root (ThemeProvider mirrors its state there, so the
    attribute is a faithful readout even though it is not a control), and click the real toggle
    until it agrees. Fails LOUDLY - a theme that cannot be reached must never be photographed as
    though it had been, because a wrong shot reads as evidence.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    if page.evaluate("() => document.documentElement.dataset.theme || ''") == theme:
        return None
    toggle = page.locator('[data-dev-id="rail.theme-toggle"]')
    if not _appears(toggle):
        return f"rail.theme-toggle not reachable, cannot switch to {theme}"

    # The var the whole palette hangs off, sampled BEFORE the click so the wait below can require
    # that the theme's CSS actually took effect - not merely that an attribute changed. Two signals,
    # because the attribute is React's claim and the computed var is the browser's.
    before = page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--c-canvas').trim()"
    )
    toggle.click()
    try:
        # POLL the success signal, do not sleep toward it. `wait_for_function` returns the instant
        # the condition holds (typically one frame), so the ceiling here is a BACKSTOP that only a
        # genuine failure reaches - a fixed wait would have been both slower and, if the app were
        # ever slower than the guess, a false pass photographing the previous theme.
        page.wait_for_function(
            """([want, before]) => {
                 const root = document.documentElement;
                 const now = getComputedStyle(root).getPropertyValue('--c-canvas').trim();
                 return root.dataset.theme === want && now !== before;
               }""",
            arg=[theme, before],
            timeout=_UI_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        got = page.evaluate("() => document.documentElement.dataset.theme || ''")
        return (
            f"theme stuck at {got!r}, wanted {theme!r} "
            f"(--c-canvas still {before!r} after clicking rail.theme-toggle)"
        )
    return _park_pointer_off_rail(page)


def _await_land_pattern(page) -> None:
    """Wait for the part's land pattern to ARRIVE before anything is photographed.

    The 3D viewer fetches the footprint's pads asynchronously and builds the board and the pad
    geometry only once it lands. Everything before that is a model alone on an empty stage, and the
    two look enough alike at a glance that a capture taken early reads as a real scene.

    MEASURED 2026-07-26: four identical runs of one bundle, and ONE of them photographed a model-only
    scene - the board's horizon sampled 40 (the bare canvas colour) instead of 46, which is a
    difference big enough to have been read as a regression in the material being tuned at the time.
    A shot harness that is right three times in four is not a measuring instrument.

    The pads/board CHIPS are the honest DOM signal: `Glb3DView` renders them only when a land pattern
    with at least one pad exists, so their presence is the arrival event itself rather than a proxy
    for it. Absence is legitimate - plenty of parts have no footprint - so this cannot fail the run;
    but it must never be SILENT, because "no board in this shot" and "the board had not loaded yet"
    are indistinguishable in the image and only one of them is a fact about the part."""
    if _appears(page.locator('[data-dev-id="detail.model-show-board"]'), 4000):
        return
    if _appears(page.locator('[data-dev-id="detail.model-layers"]'), 500):
        print("  note: no land pattern for this part, so the 3D stage carries no board or pads")


def _park_pointer_off_rail(page) -> str | None:
    """Move the pointer off the rail and WAIT for the hover-peek to actually close.

    The theme toggle lives at the bottom of the nav rail, so clicking it leaves Playwright's pointer
    parked ON the rail - and the rail peeks open on hover as an opaque 190px overlay that floats OVER
    the page. The result was that every LIGHT capture (light is the theme we have to click to reach)
    photographed the peek covering the components list, while every DARK capture, which needs no
    click, showed the rail collapsed.

    MEASURED 2026-07-26: the two themes of one run disagreed about the whole left column, and the
    components list has therefore been un-critiqueable from a light shot ever since the peek shipped
    in `9f76b4e`. Nothing failed; the shot just quietly contained a state no user had asked for.

    The peek is pure CSS `:hover`, so its WIDTH is the honest readout - there is no React state to
    ask. Poll that, rather than sleeping and hoping: the transition carries a 150ms hover-intent
    delay, so a guessed wait would be either too short or needlessly slow."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    rail = page.locator('[data-dev-id="rail.root"]')
    if not _appears(rail, 1000):
        return None  # no rail on this surface; nothing to park away from
    # FOCUS, not hover - and it took three wrong answers to find that, so all three are recorded:
    #   * "wait for the width to return to its resting value" - the resting value has to be sampled
    #     BEFORE parking, when the rail is already open, so the target WAS the open width and the
    #     condition passed instantly. A check that cannot fail is worse than none; it shipped a shot
    #     with the rail wide open while reporting success.
    #   * "wait for width < 120px" - a rail the user PINNED open is legitimately 190px, so width
    #     alone cannot tell open-by-accident from open-on-purpose, and this would hang on the latter.
    #   * "wait for :hover to clear" - measured `railHovered: false` while the rail sat at 190px, so
    #     hover was never the mechanism at all. Moving the mouse could not have helped.
    # The collapsed rail carries `focus-within:w-[190px]` so a keyboard user can reach it, and
    # `toggle.click()` leaves the browser's focus ON the theme button, which lives in the rail. So
    # the rail expands and stays expanded, and it is the FOCUS that has to leave.
    box = page.viewport_size or {"width": 1600, "height": 1000}
    page.mouse.move(box["width"] - 40, box["height"] // 2)
    page.evaluate(
        """() => {
             const a = document.activeElement;
             if (a && a !== document.body && typeof a.blur === 'function') a.blur();
           }"""
    )
    try:
        page.wait_for_function(
            """() => {
                 const r = document.querySelector('[data-dev-id="rail.root"]');
                 if (!r) return true;
                 // both states that widen a COLLAPSED rail, asked of the browser directly rather
                 // than inferred from a width that a pinned rail shares
                 return !r.matches(':hover') && !r.contains(document.activeElement);
               }""",
            timeout=_UI_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        return "the rail stayed expanded over the page and would cover the components list"
    return None


def _fill_dev_ids(page, pairs: list[str]) -> list[str]:
    """Fill each `DEV_ID=TEXT` input, so a shot can show a surface in its WORKING state.

    An empty form tells you almost nothing: a disabled primary and an enabled one are
    indistinguishable when every control is disabled because the field is blank. Measured on the
    bulk-import panel - its accent primary looked perfectly ready while it was disabled, which is
    the misleading state a reviewer needs to SEE to catch.

    Returns the `DEV_ID=TEXT` entries whose element was never found, never a silent skip. `\n` in
    TEXT is a real newline, so a multi-line paste can be reproduced.
    """
    missing: list[str] = []
    for pair in pairs:
        dev_id, _, value = pair.partition("=")
        target = page.locator(f'[data-dev-id="{dev_id}"]')
        if not _appears(target.first):
            missing.append(pair)
            continue
        target.first.fill(value.replace("\\n", "\n"))
    return missing


def _click_dev_ids(page, dev_ids: list[str]) -> list[str]:
    """Click each `data-dev-id` in turn, so a shot can reach a control behind a popover.

    Added because a slice cannot be reviewed if it cannot be SEEN, and several real controls live
    one click deep: the CAD readiness detail, the filters panel, the remove-element chips. Without
    this the only options were to shoot the collapsed surface and hope, or to skip the visual check
    and admit it, and the third time that came up it became a flag.

    Returns the ids that were NOT found, so a typo'd id is reported instead of silently producing a
    shot of the wrong state. A shot that misses is worse than no shot, because it reads as evidence.
    """
    missing: list[str] = []
    for dev_id in dev_ids:
        target = page.locator(f'[data-dev-id="{dev_id}"]')
        # POLL, do not sample. `count()` asks whether the element exists AT THIS INSTANT, which is a
        # clock-as-detector in disguise: any control that renders asynchronously is reported absent
        # simply because the check ran first. MEASURED - the 3D viewer's controls only exist once
        # the GLB has been fetched and three.js lazily imported, so `--click detail.model-view-top`
        # reported "no such data-dev-id" on a part that definitely has one. `_appears` returns the
        # moment the element is really there, and its ceiling only bounds how long a GENUINE
        # absence takes to report.
        if not _appears(target.first):
            missing.append(dev_id)
            continue
        target.first.click()
        # a settle wait, not a detector: the click has already landed, and this only lets the
        # resulting transition finish before the next click or the capture.
        page.wait_for_timeout(700)
    return missing


def _hover_dev_ids(page, dev_ids: list[str]) -> list[str]:
    """Hover each `data-dev-id`, so a shot can show a control's REVEALED state.

    The app's destructive/pending language (the shared compact `IconButton`) is a glyph at rest that
    expands to state its consequence on hover or keyboard focus. A static shot therefore only ever
    photographed the collapsed glyph, which is the half that needed no review. Hovering is not a
    detail here: it IS the state under test.

    Returns the ids that were NOT found, for the same reason `_click_dev_ids` does - a shot that
    silently misses reads as evidence.
    """
    missing: list[str] = []
    for dev_id in dev_ids:
        target = page.locator(f'[data-dev-id="{dev_id}"]')
        if not target.count():
            missing.append(dev_id)
            continue
        target.first.hover()
        # The reveal is a 150ms width transition, so this waits for the ANIMATION to land rather
        # than for an unknown condition - a legitimate settle, not a detector.
        page.wait_for_timeout(350)
    return missing


def _close_surface(page, surface: str) -> None:
    if surface == "search":
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)


def run(args) -> int:
    import tempfile

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

    # A project surface needs a project. `project-health` implies the seed, so the surface can never be
    # requested in a state where it silently degrades to the "No projects are registered" empty view
    # and a green shot proves nothing.
    #
    # A --click ALSO implies the seed, and that one was learned the hard way on 2026-07-25: a
    # settings shot ran `--click settings.library-lfs.adopt` against the DEFAULT library, which is
    # the owner's real in-repo one, and the click did exactly what the button says - it wrote
    # workspace hygiene rules and committed them to the real repository. A screenshot tool must not
    # be able to mutate the thing it is photographing. The seed COPIES the real library, so the shot
    # still shows real content; only the writes are thrown away.
    # `part-vendor-data` implies the seed for the same reason a project surface does: the data it
    # exists to show (alternates, an HTS family) is on the seeded probe part and nowhere in a real
    # library, so without the seed the shot would silently photograph an ordinary part.
    clicking = bool(args.click)
    seed = (args.seed or clicking
            or any(s.startswith("project-") or s == "part-vendor-data" for s in surfaces))
    if clicking and not args.seed:
        print("  --click implies --seed: clicks can mutate, and the default library is the real one")
    scratch: tempfile.TemporaryDirectory | None = None
    library = Path(args.library)
    seed_project: Path | None = None
    if seed:
        scratch = tempfile.TemporaryDirectory(prefix="uishot-seed-")
        library, seed_project = _seed_workspace(Path(scratch.name), Path(args.library))
        print(f"  seeded library + project under {scratch.name}")

    def opener(base_url: str, token: str) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--force-color-profile=srgb"])
            page = browser.new_page(
                viewport={"width": args.width, "height": args.height},
                device_scale_factor=args.scale,
                # The app already ships `transition: none !important` under this media query
                # (styles/index.css), so asking for it means there is NOTHING left to settle after a
                # theme switch or a click - which is what lets the waits below be real signals
                # instead of guessed durations. This harness shoots layout, spacing, tokens and
                # hierarchy; a mid-transition frame is noise in every one of those.
                reduced_motion="reduce",
            )
            console: list[str] = []
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            # WITH the stack. An uncaught "Cannot read properties of undefined" names neither the
            # file nor the frame, so the message alone cannot start a diagnosis - and the kicanvas
            # throw sat unread in every Projects shot for exactly that reason.
            page.on(
                "pageerror",
                lambda e: console.append(
                    f"{e.message}\n      {getattr(e, 'stack', '') or ''}".rstrip()
                ),
            )
            # A failing REQUEST is invisible in the console when the app swallows it (an <img> that
            # 500s, a fetch inside a try/catch), so the harness watched the page and could not see
            # the API break underneath it. `GET /api/previews/model/*.glb` 500ed in the live app for
            # weeks with every shot reported clean.
            http: dict[str, int] = {}

            def _note_response(r) -> None:
                if r.status >= 400:
                    http[f"{r.status} {r.request.method} {_api_path(r.url)}"] = (
                        http.get(f"{r.status} {r.request.method} {_api_path(r.url)}", 0) + 1
                    )

            page.on("response", _note_response)
            def _note_failed(req) -> None:
                # `requestfailed` hands back a Request, NOT a Response - so `.request` does not
                # exist on it and reaching for it raised INSIDE the event handler, which surfaced
                # as an unrelated `Locator.count` failure several calls later.
                key = f"FAILED {req.method} {_api_path(req.url)}"
                http[key] = http.get(key, 0) + 1

            page.on("requestfailed", _note_failed)

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
                if not _goto_surface(page, surface, args.select):
                    print(f"  !! could not reach surface: {surface}")
                    failures.append(surface)
                    continue
                # Reaching a surface means CLICKING its nav item, which lives in the rail - so the
                # pointer and the focus ring are both left sitting on the rail afterwards. Parking
                # used to happen only after a theme switch, so a dark-only run photographed a rail
                # that no user had touched (`railHovered: true` in the probe of every such shot).
                parked = _park_pointer_off_rail(page)
                if parked:
                    print(f"  !! {parked}")
                    failures.append(f"{surface}:rail")
                # ONCE per surface, before the theme loop. Clicking per theme TOGGLED a popover
                # shut on the second theme, so the dark shot showed it open and the light shot
                # showed it closed; a comment in this very function claimed the opposite was safer.
                # Switching the theme only sets a root data attribute, so nothing unmounts and an
                # open popover stays open. Caught by shooting both themes, which is the point.
                if args.click:
                    absent = _click_dev_ids(page, args.click)
                    if absent:
                        print(f"  !! no such data-dev-id: {', '.join(absent)}")
                        failures.append(f"{surface}:click")
                for theme in themes:
                    # The theme toggle lives on the RAIL, which a modal surface covers with a
                    # scrim - so on a modal surface the toggle is unclickable and the run died
                    # with a 30 s timeout on the second theme. Close the modal, switch, reopen.
                    # `_goto_surface` is idempotent and already re-drives the real button.
                    modal = page.locator('[data-dev-id="addpart.root"]')
                    reopen = bool(modal.count())
                    if reopen:
                        page.keyboard.press("Escape")
                        _vanishes(modal.first)
                    # Through the real toggle, never by stamping the attribute: see _set_theme.
                    theme_err = _set_theme(page, theme)
                    if reopen and not theme_err and not _goto_surface(page, surface, args.select):
                        print(f"  !! could not reopen {surface} after the theme switch")
                        failures.append(f"{surface}:{theme}")
                        continue
                    if theme_err:
                        print(f"  !! {theme_err}")
                        failures.append(f"{surface}:{theme}")
                        continue
                    # No settle wait here on purpose. `_set_theme` has already confirmed the
                    # COMPUTED `--c-canvas` changed, and the context runs with reduced motion so
                    # transitions are `none` - so there is no state left in flight to sleep toward.
                    # A `wait_for_timeout(600)` used to sit here; it was pacing, not detection.
                    # Hover LAST and per theme, unlike --click: a theme switch does not unmount
                    # anything, but moving the pointer is not sticky the way an open popover is, and
                    # the hovered state is what needs to appear in BOTH shots.
                    # PER THEME, like --hover and unlike --click. A modal surface is closed and
                    # reopened around the theme toggle, which UNMOUNTS the form and resets its
                    # React state - so a fill done once before the loop was silently wiped and the
                    # shot showed an empty field with a disabled primary. Measured: the first
                    # --fill run produced exactly the empty state it was added to escape.
                    if args.fill:
                        absent = _fill_dev_ids(page, args.fill)
                        if absent:
                            print(f"  !! no such data-dev-id to fill: {', '.join(absent)}")
                            failures.append(f"{surface}:fill")
                    if args.hover:
                        gone = _hover_dev_ids(page, args.hover)
                        if gone:
                            print(f"  !! no such data-dev-id to hover: {', '.join(gone)}")
                            failures.append(f"{surface}:hover")
                    path = out / f"{surface}-{theme}-{args.width}w.png"
                    page.screenshot(path=str(path), full_page=args.full_page)
                    print(f"  shot {path.name}")
                    # Measured per THEME, in the same state the shot captured, so a number can
                    # never be quoted against a layout the screenshot does not show.
                    if args.measure:
                        boxes = page.evaluate(MEASURE_JS, args.measure)
                        for dev_id in args.measure:
                            hits = boxes.get(dev_id) or []
                            if not hits:
                                print(f"  !! no such data-dev-id to measure: {dev_id}")
                                failures.append(f"{surface}:measure")
                                continue
                            for i, b in enumerate(hits):
                                tag = f"{dev_id}[{i}]" if len(hits) > 1 else dev_id
                                flags = "".join(
                                    [" OVERFLOW-X" if b["overflowX"] else "",
                                     " CLIPPED-Y" if b["clipped"] else ""]
                                )
                                glyph = (
                                    f" glyphCx={b['glyphCx']}" if b.get("glyphCx") is not None
                                    else ""
                                )
                                print(
                                    f"  measure {theme} {tag}: {b['w']}x{b['h']} "
                                    f"@({b['left']},{b['top']}) "
                                    f"scroll={b['scrollW']}x{b['scrollH']} "
                                    f"tail={b['tail']}px{glyph} "
                                    f"pad={b['padL']}/{b['padR']} justify={b['justify']} "
                                    f"gap={b['gap']}{flags}"
                                )
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
            for label, n in sorted(http.items()):
                # A 5xx is OUR backend breaking and is never acceptable; a 4xx can be legitimate
                # (asking for a preview a part genuinely has no asset for), so it is reported
                # without the alarm rather than hidden.
                mark = "  !! " if label.startswith("5") or label.startswith("FAILED") else "  http "
                print(f"{mark}{label} x{n}")
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
    ap.add_argument(
        "--click",
        action="append",
        default=[],
        metavar="DEV_ID",
        help="click this data-dev-id before shooting (repeatable), to reach a control behind a "
        "popover. An id that does not exist is reported, never silently skipped.",
    )
    ap.add_argument("--surface", default="components",
                    choices=["components", "search", "projects", "project-health", "project-hygiene",
                             "project-library-pin", "part-vendor-data", "ingest", "settings", "all"])
    ap.add_argument(
        "--fill", action="append", default=[], metavar="DEV_ID=TEXT",
        help="type TEXT into this data-dev-id before each capture, so a form is shot in its "
             "WORKING state rather than empty (an empty form hides whether a control is enabled). "
             "Repeatable; use \\n for a newline. An id that does not exist is reported.",
    )
    ap.add_argument(
        "--hover", action="append", default=[], metavar="DEV_ID",
        help="hover this data-dev-id before each capture, so a control whose label only appears on "
             "hover/focus (the destructive + pending IconButton language) is actually visible in "
             "the shot. Repeatable. An id that does not exist is reported, never silently skipped.",
    )
    ap.add_argument(
        "--select", default="", metavar="TEXT",
        help="select the components row whose text contains TEXT, instead of the first row. The "
             "first row is whatever sorts first by category, which is the wrong part for any shot "
             "about a specific asset (a 3D model, a symbol). A TEXT that matches nothing is a loud "
             "failure listing what the library does hold, never a silent fallback to row one.",
    )
    ap.add_argument(
        "--measure", action="append", default=[], metavar="DEV_ID",
        help="report this data-dev-id's measured box after each capture (repeatable): width, "
             "height, scroll size, and `tail` - the dead space between its last child and its own "
             "bottom edge. This is how a column-balance or dead-space claim is backed by a number "
             "instead of an impression. An id that does not exist is reported, never skipped.",
    )
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
