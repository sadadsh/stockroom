"""Drive the Windows DESKTOP: a real mouse, real clicks, and fast captures.

Owner, 2026-07-25: *"research how to control my windows and screenshot quickly like use the mouse"*.

THIS IS THE OTHER HALF OF `windrive.py`, NOT A REPLACEMENT. The two answer different questions and
the split is forced by how WebView2 works, not by taste:

  - `windrive.py` talks CDP to the page. It knows WHAT things are - it can find a control by
    `data-dev-id`, read its state, and assert on it - and it keeps working while the desktop is
    LOCKED, which is the failure that used to stall visual verification here for days.
  - this file drives the OS. It does what CDP structurally cannot: move a real pointer so real
    hover and pointer events fire, reach the window chrome, resize the window, answer a native file
    dialog, and photograph the whole desktop rather than one page's render.

RESEARCHED BEFORE BUILDING (2026-07-25), because the obvious approach is a dead end here:
  - **UI Automation (`pywinauto` backend="uia") cannot see inside the app's UI.** For WebView2 /
    Electron / CEF, the HTML layer needs BROWSER automation; UIA sees the host window and not the
    controls in it. So a pure pywinauto/pyautogui harness would have missed almost every control
    Stockroom has. That is why targeting stays on CDP and only the INPUT moves to the OS.
  - **Screenshot speed is not a detail.** `PIL.ImageGrab` is the legacy GDI path at roughly 100ms a
    frame; `mss` uses DXGI and lands near 3ms - 30-40x faster. `bettercam`/`dxcam` reach 240Hz+ via
    the Desktop Duplication API, which is more than anything here needs. ADOPTED: `mss`. REJECTED:
    ImageGrab (too slow, and it is what was installed), bettercam (a GPU-bound dependency for
    frame rates a screenshot tool does not need).
  - **Coordinates alone are fragile.** PyAutoGUI drives by coordinates and image matching with no UI
    semantics, so it cannot assert state and breaks whenever anything moves. REJECTED as the
    targeting layer; `pydirectinput` is used only to INJECT the input once CDP has said where.

THE BRIDGE, which is the whole point: ask CDP for an element's rect in PAGE space, convert it to
SCREEN space using the window's own position and its device pixel ratio, then move the real mouse
there. Semantic targeting, genuine input.

CONSTRAINT, stated rather than discovered later: real mouse input needs an UNLOCKED, non-minimised
desktop. `windrive.py` is the one that works on a locked machine. Neither replaces the other.

USAGE
    py windesk.py shot desk.png            # whole desktop, ~3ms via mss
    py windesk.py shot win.png --window    # just the Stockroom window
    py windesk.py hover detail.delete      # move the REAL mouse onto a control and hold it
    py windesk.py click detail.asset-hero  # real pointer press, not element.click()
    py windesk.py where detail.delete      # what screen pixel that control occupies
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE.parent / "app" / "backend",):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from windrive import DEFAULT_PORT, Drive, NoWindow  # noqa: E402

WINDOW_TITLE = "Stockroom"


def _require(module: str):
    """Import an OS-automation dependency, or say exactly how to get it.

    A bare ImportError here would send the next reader hunting; these three are installed into the
    INSTALL's venv (the Windows one), not the WSL one, and that distinction is the whole trap.
    """
    try:
        return __import__(module)
    except ImportError as exc:
        raise SystemExit(
            f"{module} is not installed in this python ({sys.executable}).\n"
            f"  Install it into the INSTALL's venv: "
            f'"<install>\\.venv\\Scripts\\python.exe" -m pip install mss pywinauto pydirectinput'
        ) from exc


def _window():
    """The Stockroom top-level window, via UI Automation.

    UIA is used for exactly this and no more: finding, focusing and measuring the HOST window. It
    cannot see the controls inside a WebView2, so nothing else is asked of it.
    """
    from pywinauto import Desktop

    matches = [
        w for w in Desktop(backend="uia").windows()
        if WINDOW_TITLE.lower() in (w.window_text() or "").lower()
    ]
    if not matches:
        raise SystemExit(
            f"no window titled {WINDOW_TITLE!r} is open. Start it with `windrive.py up`."
        )
    if len(matches) > 1:
        titles = ", ".join(f'"{w.window_text()}"' for w in matches)
        raise SystemExit(
            f"{len(matches)} windows match {WINDOW_TITLE!r} ({titles}). Close the extras - "
            "guessing which one to drive is how a tour ends up describing the wrong window."
        )
    return matches[0]


def _window_rect() -> tuple[int, int, int, int]:
    r = _window().rectangle()
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _page_to_screen(drive: Drive, dev_id: str) -> tuple[int, int]:
    """The screen pixel at the CENTRE of a control, from its page rect.

    Page space is CSS pixels inside the web view; screen space is physical pixels on the desktop.
    Converting needs three things and silently produces a plausible-but-wrong point if any is
    skipped: the window's own position, the border/title-bar inset between the window origin and
    the page origin, and `devicePixelRatio` for display scaling. The inset is READ from the page
    (`window.screenX/screenY` are the web view's own screen position) rather than assumed from a
    title-bar height, because that height changes with the theme and the DPI.
    """
    box = drive.eval(
        """
        (() => {
          const el = document.querySelector(%s);
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return JSON.stringify({
            x: r.left + r.width / 2,
            y: r.top + r.height / 2,
            w: r.width, h: r.height,
            originX: window.screenX, originY: window.screenY,
            dpr: window.devicePixelRatio || 1,
          });
        })()
        """
        % _json_str(dev_id)
    )
    if not box:
        raise SystemExit(f"no element with data-dev-id={dev_id!r} is on the page right now")
    import json

    b = json.loads(box)
    if not b["w"] or not b["h"]:
        raise SystemExit(f"{dev_id} has zero size, so it has no point to click")
    return (
        int(round(b["originX"] + b["x"] * b["dpr"])),
        int(round(b["originY"] + b["y"] * b["dpr"])),
    )


def _json_str(value: str) -> str:
    import json

    selector = value if value.startswith("[") else f'[data-dev-id="{value}"]'
    return json.dumps(selector)


def _move(x: int, y: int) -> None:
    pdi = _require("pydirectinput")
    # DISABLE the library's own failsafe and pause. The failsafe aborts when the pointer reaches a
    # screen corner, which a legitimate click near the edge of a maximised window can do; the
    # default 0.1s pause per call turns a ten-step interaction into a second of nothing.
    pdi.FAILSAFE = False
    pdi.PAUSE = 0
    pdi.moveTo(x, y)


def cmd_where(args) -> int:
    drive = Drive(args.port)
    try:
        x, y = _page_to_screen(drive, args.dev_id)
    finally:
        drive.close()
    left, top, width, height = _window_rect()
    print(f"{args.dev_id} -> screen ({x}, {y}); window at ({left}, {top}) {width}x{height}")
    return 0


def cmd_hover(args) -> int:
    """Move the REAL pointer onto a control and leave it there.

    This is the thing `element.click()` cannot do. A reveal-on-hover control - the delete button's
    expanding label, a tooltip, a chip that only appears under the cursor - has no state to set
    from script; it responds to a pointer actually being over it.
    """
    drive = Drive(args.port)
    try:
        x, y = _page_to_screen(drive, args.dev_id)
        _window().set_focus()
        _move(x, y)
        time.sleep(args.settle)
        print(f"pointer on {args.dev_id} at ({x}, {y})")
        if args.shot:
            cmd_shot(argparse.Namespace(out=args.shot, window=True, port=args.port))
    finally:
        drive.close()
    return 0


def cmd_click(args) -> int:
    drive = Drive(args.port)
    try:
        x, y = _page_to_screen(drive, args.dev_id)
        _window().set_focus()
        _move(x, y)
        pdi = _require("pydirectinput")
        pdi.click()
        time.sleep(args.settle)
        print(f"clicked {args.dev_id} with a real pointer at ({x}, {y})")
    finally:
        drive.close()
    return 0


def cmd_shot(args) -> int:
    """Capture via mss (DXGI): about 3ms, against roughly 100ms for PIL.ImageGrab."""
    mss = _require("mss")
    region = None
    if getattr(args, "window", False):
        left, top, width, height = _window_rect()
        region = {"left": left, "top": top, "width": width, "height": height}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with mss.mss() as sct:
        shot = sct.grab(region or sct.monitors[0])
        mss.tools.to_png(shot.rgb, shot.size, output=str(out))
    print(f"{out} ({shot.size[0]}x{shot.size[1]}) in {(time.time() - started) * 1000:.0f}ms")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    shot = sub.add_parser("shot", help="capture the desktop, or just the app window")
    shot.add_argument("out")
    shot.add_argument("--window", action="store_true", help="crop to the Stockroom window")
    shot.set_defaults(func=cmd_shot)

    for name, fn, helptext in (
        ("hover", cmd_hover, "move the real pointer onto a control"),
        ("click", cmd_click, "press a control with the real pointer"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("dev_id")
        p.add_argument("--settle", type=float, default=0.25)
        p.add_argument("--shot", default="", help="capture the window afterwards")
        p.set_defaults(func=fn)

    where = sub.add_parser("where", help="what screen pixel a control occupies")
    where.add_argument("dev_id")
    where.set_defaults(func=cmd_where)

    args = ap.parse_args()
    try:
        return args.func(args)
    except NoWindow as exc:
        print(f"NO WINDOW: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
