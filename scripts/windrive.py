"""Drive the REAL Stockroom window on Windows, fast, the way a developer clicks around.

Owner, 2026-07-25: *"you need a system to be able to go in and click everything and see and it all
be quick like a developer seeing for themselves and clicking around"*.

WHAT WAS WRONG WITH WHAT WE HAD
  - `scripts/uishot.py` substitutes Playwright's Chromium for pywebview. Excellent for layout and
    tokens, and structurally unable to answer anything about WebView2 itself - DPI, font
    rasterisation, host chrome, a real app restart. It is also a fresh boot per shot.
  - `C:\\srdrive\\win_drive.py` did drive the real window, but it lived OUTSIDE the repo (so it was
    lost work), offered only eval/click/text, could not launch or stop the app, could not take a
    picture, and paid a fresh process and a fresh websocket for every single command.

So the loop was: launch by hand, run one command, run another command, go find a screenshot tool,
discover the shot was of the wrong window. This file makes that one connection and one command.

PRIOR ART EVALUATED (and `stockroom.host.cdp_probe` is ADOPTED, not reimplemented)
  - `stockroom.host.cdp_probe` - ADOPTED. Target discovery, the websocket client, Runtime.evaluate
    and the console tap already live there. This file hand-rolls NO CDP protocol logic.
  - Playwright - REJECTED for this job, for the reason above. It remains right for `uishot.py`.
  - pywebview `evaluate_js` - REJECTED. cdp_probe's own docstring records that it returns None from
    a background thread on a busy page, which is why CDP exists here at all.
  - WebDriver / msedgedriver - REJECTED. It launches and owns its own browser; this window is
    already running and must stay the one under test.
  - `winshot` / `PrintWindow` - REJECTED for the screenshot. `Page.captureScreenshot` returns the
    WebView2's OWN rendered buffer over the same connection, so it needs no desktop focus, cannot
    grab the wrong window, and keeps working while the desktop is locked - which is the failure that
    used to stall visual verification for days.

WHY IT RUNS WINDOWS-SIDE
CDP binds to Windows loopback, which WSL cannot reach. So the script must be executed by a Windows
python. It is written to be run either way and says which side it is on when it cannot connect.

USAGE
    py windrive.py up                     # launch the install with CDP on, wait for a REAL signal
    py windrive.py click detail.asset-hero --shot
    py windrive.py do click:rail.nav-components shot click:components.row shot text:detail.title
    py windrive.py shot out.png
    py windrive.py console                # what the page has logged since it booted
    py windrive.py down

`do` is the point: every step runs over ONE already-open connection, so clicking through five
screens costs one handshake instead of five process launches.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# The install is a git checkout of this same repo, so importing the backend works from either copy.
_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE.parent / "app" / "backend",):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from stockroom.host.cdp_probe import CDPClient, list_targets  # noqa: E402

DEFAULT_PORT = 9222


class NoWindow(RuntimeError):
    """No Stockroom page is answering on the CDP port. Says which side it looked from, because
    'connection refused' from WSL and from Windows mean two completely different things."""


def _page_ws(port: int) -> str:
    pages = [
        t for t in list_targets(port)
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
    ]
    if not pages:
        side = "WSL" if Path("/proc/version").exists() else "Windows"
        raise NoWindow(
            f"no Stockroom page answering on 127.0.0.1:{port} (looked from {side}). "
            + (
                "CDP binds to WINDOWS loopback, which WSL cannot reach - run this with the "
                "install's Windows python, e.g. `py windrive.py ...`."
                if side == "WSL"
                else "Start it with `windrive.py up`."
            )
        )
    # The app is one page; if a preview or a devtools target ever appears, the FIRST page target is
    # still the app itself, because the host opens it before anything else can exist.
    return pages[0]["webSocketDebuggerUrl"]


class Drive:
    """One open connection to the live window. Every command in a `do` batch reuses it."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.console: list[str] = []
        self.client = CDPClient(_page_ws(port), on_event=self._on_event)
        if not self.client.connect():
            raise NoWindow("the page target exists but the websocket refused the connection")
        self.client.enable()

    def _on_event(self, msg: dict) -> None:
        method = msg.get("method", "")
        if method == "Runtime.consoleAPICalled":
            params = msg.get("params", {})
            level = params.get("type", "log")
            from stockroom.host.cdp_probe import format_console_args

            self.console.append(f"{level}: {format_console_args(params.get('args', []))}")
        elif method == "Runtime.exceptionThrown":
            detail = msg.get("params", {}).get("exceptionDetails", {})
            self.console.append(f"error: {detail.get('text', 'exception')}")

    def eval(self, expression: str):
        # `@path` reads the expression from a FILE. Anything with quotes or parentheses in it is
        # unusable as an argv string across the WSL -> cmd.exe boundary: interop re-splits the
        # command line, so a one-line arrow function arrives shredded and argparse rejects the
        # fragments. Scoped to that boundary rather than solved by escaping, which never survives
        # two layers of quoting.
        if expression.startswith("@"):
            expression = Path(expression[1:]).read_text(encoding="utf-8")
        return self.client.evaluate(expression)

    def click(self, dev_id: str) -> str:
        """Click by data-dev-id, and report what actually happened.

        It reports rather than returns a bare boolean because a click that lands on a covered
        element is the failure that wasted a whole session once: the control was visible, enabled,
        and something else was on top of it. `elementFromPoint` is what distinguishes those.
        """
        selector = dev_id if dev_id.startswith("[") else f'[data-dev-id="{dev_id}"]'
        return self.eval(
            """
            (() => {
              const el = document.querySelector(%s);
              if (!el) return "MISSING: nothing matches";
              const r = el.getBoundingClientRect();
              if (!r.width || !r.height) return "HIDDEN: zero size";
              const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              if (top && !el.contains(top) && !top.contains(el)) {
                return "INTERCEPTED by <" + top.tagName.toLowerCase() +
                       " class='" + (top.className || "") + "'>";
              }
              el.click();
              return "clicked";
            })()
            """
            % json.dumps(selector)
        )

    def text(self, dev_id: str) -> str:
        selector = dev_id if dev_id.startswith("[") else f'[data-dev-id="{dev_id}"]'
        return self.eval(
            "(document.querySelector(%s)||{}).innerText || 'MISSING'" % json.dumps(selector)
        )

    def shot(self, out: Path) -> Path:
        """The WebView2's own rendered buffer, over the same connection.

        No desktop focus, no window raise, no chance of photographing the wrong window, and it
        works while the desktop is locked.
        """
        result = self.client.send("Page.captureScreenshot", {"format": "png"}, timeout=20.0)
        data = (result or {}).get("result", {}).get("data")
        if not data:
            raise RuntimeError("the window returned no screenshot data")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(data))
        return out

    def controls(self) -> list[dict]:
        """Every visible, clickable control on the current screen."""
        raw = self.eval(_ENUMERATE_JS)
        try:
            return json.loads(raw) if isinstance(raw, str) else []
        except json.JSONDecodeError:
            return []

    def settle(self, *, tries: int = 20, gap: float = 0.1) -> bool:
        """Wait until the screen STOPS CHANGING, then return.

        The signal is two identical fingerprints in a row - a real property of the page - so a fast
        machine continues immediately and a slow one is still waited for. `tries * gap` is only the
        backstop, and returning False says the UI never settled, which is itself a finding.
        """
        previous = None
        stable = 0
        for _ in range(tries):
            current = self.eval(_FINGERPRINT_JS)
            if current == previous:
                stable += 1
                if stable >= 1:
                    return True
            else:
                stable = 0
            previous = current
            time.sleep(gap)
        return False

    def dialog(self) -> str:
        """The dev-id of the open modal, or "" when none is open.

        Load-bearing for the tour's honesty. A control sitting behind an open modal's scrim is
        CORRECTLY unclickable, and reporting it as "renders but cannot be clicked" is a false
        positive - the first run of `tour` produced six of them from one About dialog it had opened
        itself. The sweep has to know the difference between a covered control and a modal.
        """
        found = self.eval(
            "(() => { const d = document.querySelector('[role=\"dialog\"]');"
            " return d ? (d.getAttribute('data-dev-id') || 'dialog') : ''; })()"
        )
        return found if isinstance(found, str) else ""

    def escape(self) -> str:
        """Dismiss an open modal and say whether it actually went.

        Returns "" when the screen is clear, or the dialog's id when it REFUSED to close - which is
        a real finding rather than a reason to keep sweeping into a scrim. Escape is dispatched with
        rawKeyDown as well as keyDown: a React handler bound to keydown sees the former, and without
        it the key silently does nothing.
        """
        if not self.dialog():
            return ""
        for kind in ("rawKeyDown", "keyDown", "keyUp"):
            self.client.send("Input.dispatchKeyEvent", {
                "type": kind, "key": "Escape", "code": "Escape",
                "windowsVirtualKeyCode": 27, "nativeVirtualKeyCode": 27,
            })
        self.settle()
        still = self.dialog()
        if still:
            # second chance: press the dialog's own close control, the way a person would
            for close_id in (f"{still.split('.')[0]}.close", "preview.close", "dialog.close"):
                if self.click(close_id) == "clicked":
                    self.settle()
                    break
        return self.dialog()

    def flush_events(self) -> None:
        """Make sure every console event the page has already emitted has ARRIVED.

        A sleep here would be a clock standing in for a signal. CDP delivers replies and events in
        order on one websocket, so a completed round trip IS the signal: once the reply to this
        evaluate comes back, everything the page emitted before it has already been handed to
        `_on_event`. It also returns as fast as the connection allows instead of always costing a
        fixed wait.
        """
        self.client.evaluate("0")

    def close(self) -> None:
        self.client.close()


# Controls a sweep must NOT press on a real library, matched against the dev-id.
#
# This is the whole reason `tour` is safe to point at the owner's own machine. A tester who clicks
# literally everything deletes a part, commits to git, rewrites the machine config, spends an API
# quota and burns an Altium licence seat - and does it in the first ten seconds. Anything that acts
# on the world is skipped by default and NAMED in the report, never silently passed over, so the
# report can never read as "everything was exercised" when it was not.
DESTRUCTIVE = (
    "delete", "remove", "detach", "clear", "reset",
    "apply", "adopt", "commit", "regenerate", "embed", "attach", "complete",
    "refresh", "enrich", "ingest", "add-", "capture", "prepare", "restore",
    "assign", "pin", "hygiene", "lfs", "sync", "rescan", "update", "activate",
)


def _is_destructive(dev_id: str) -> bool:
    lowered = dev_id.lower()
    return any(word in lowered for word in DESTRUCTIVE)


# The page-side sweep. Returns every VISIBLE, enabled, genuinely clickable control with its dev-id,
# tag, accessible name and whether something is covering it. Written as one expression so it costs a
# single round trip per screen rather than one per control.
_ENUMERATE_JS = """
(() => {
  const out = [];
  for (const el of document.querySelectorAll('[data-dev-id]')) {
    const id = el.getAttribute('data-dev-id');
    const tag = el.tagName.toLowerCase();
    const clickable =
      tag === 'button' || tag === 'a' || tag === 'summary' ||
      el.getAttribute('role') === 'button' || el.hasAttribute('onclick') ||
      el.tabIndex >= 0;
    if (!clickable) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (r.bottom < 0 || r.top > innerHeight) continue;
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    out.push({
      id,
      tag,
      name: (el.getAttribute('aria-label') || el.innerText || '').trim().slice(0, 60),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      covered: !!(top && !el.contains(top) && !top.contains(el)),
    });
  }
  return JSON.stringify(out);
})()
"""

# A cheap fingerprint of what is on screen. Two identical readings in a row mean the UI has SETTLED,
# which is a real signal; a fixed sleep after every click would be a clock pretending to be one.
_FINGERPRINT_JS = """
(() => {
  const d = document;
  return [
    d.readyState,
    d.querySelectorAll('*').length,
    (d.body.innerText || '').length,
    !!d.querySelector('[role="dialog"]'),
    location.hash,
  ].join('|');
})()
"""


def _install_dir() -> Path:
    """The owner's install: a git checkout at %LOCALAPPDATA%\\Stockroom\\app.

    DISCOVERED, never hardcoded to one machine - the env var is what Windows itself defines, and a
    checkout somewhere else is handled by --install.
    """
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise SystemExit("LOCALAPPDATA is not set, so this is not a Windows session; pass --install")
    return Path(local) / "Stockroom" / "app"


def cmd_up(args) -> int:
    """Launch the install with CDP exposed and wait for a REAL success signal.

    NOT a timeout. The success signal is a page target answering on the port; the failure signal is
    the process having exited. Both are polled, so a crash is reported in the second it happens
    instead of after the ceiling, and a slow machine is not called a failure.
    """
    install = Path(args.install) if args.install else _install_dir()
    python = install / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"no install python at {python}")
    env = dict(os.environ, STOCKROOM_CDP_PORT=str(args.port))
    proc = subprocess.Popen(
        [str(python), "-m", "stockroom.host.run"],
        cwd=str(install),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"FAILED: the host exited with code {proc.returncode} before opening a window")
            return 1
        try:
            if list_targets(args.port):
                print(f"OK: window up on port {args.port}, host pid {proc.pid}")
                return 0
        except Exception:
            pass
        time.sleep(0.25)
    print(f"NO WINDOW after {args.timeout}s, and the host is still running (pid {proc.pid}). "
          "That is a defect in this check, not a normal outcome - look at the host's own output.")
    return 1


def cmd_down(args) -> int:
    """Kill Stockroom by its process TREE from the owning python pid.

    NEVER `taskkill /IM msedgewebview2.exe`: measured on this machine, only 5 of 17 such processes
    were Stockroom's and the rest belonged to Windows Widgets and SearchHost.
    """
    try:
        pid = int(Drive(args.port).eval("window.__STOCKROOM_HOST_PID__ || 0") or 0)
    except Exception:
        pid = 0
    if not pid:
        # fall back to the python running the host module, still never the webview image name
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True,
        ).stdout
        for line in out.splitlines():
            if "stockroom.host.run" in line:
                pid = int(line.strip().split()[-1])
                break
    if not pid:
        print("no running Stockroom host found")
        return 1
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    print(f"stopped host pid {pid} and its tree")
    return 0


def cmd_tour(args) -> int:
    """Click through the app like a tester and report what is wrong.

    Not a screenshot script. It ENUMERATES every visible clickable control on each surface, presses
    the safe ones one at a time, waits for the screen to settle, and records what happened: did the
    click land, did something cover the control, did the page log an error, did the screen change at
    all. A control that renders perfectly and does nothing is invisible to a screenshot and obvious
    here - which is exactly the bug that cost a whole session when the viewer's chips were
    unclickable and every shot looked correct.

    Destructive controls are SKIPPED and listed, so the report never implies coverage it lacks.
    """
    out_dir = Path(args.out)
    try:
        drive = Drive(args.port)
    except NoWindow as exc:
        print(f"NO WINDOW: {exc}")
        return 2

    surfaces = args.surface or ["rail.nav-components", "rail.nav-projects", "rail.nav-stm"]
    findings: list[str] = []
    skipped: list[str] = []
    pressed = 0
    shot_n = 0

    try:
        for surface in surfaces:
            # Start each surface from a clear screen. A modal left open by the previous surface -
            # or by a previous RUN, since the app keeps running between them - sits over the rail
            # and makes every navigation report as unreachable, which is a fact about the leftover
            # dialog and not about the app.
            leftover = drive.escape()
            if leftover:
                findings.append(
                    f"STUCK MODAL on arrival: {leftover} was open and would not close, so "
                    f"{surface} could not be reached from a clean screen"
                )
            if drive.click(surface) != "clicked":
                findings.append(f"UNREACHABLE surface: {surface}")
                continue
            drive.settle()
            seen: set[str] = set()
            # Re-enumerate after every click: pressing something can reveal, hide or replace
            # controls, and a list captured once would press stale elements and miss new ones.
            for _ in range(args.max_clicks):
                candidates = [
                    c for c in drive.controls()
                    if c["id"] not in seen and not c["disabled"]
                ]
                if not candidates:
                    break
                control = candidates[0]
                seen.add(control["id"])
                if _is_destructive(control["id"]) and not args.include_destructive:
                    skipped.append(f'{surface} > {control["id"]} ({control["name"]})')
                    continue
                if control["covered"]:
                    # Only a finding when NOTHING is legitimately over the page. Behind an open
                    # modal's scrim, being uncovered would be the bug.
                    if not drive.dialog():
                        findings.append(
                            f'COVERED: {control["id"]} ({control["name"]}) is behind another '
                            f"element on {surface} - it renders but cannot be clicked"
                        )
                    continue
                before = drive.eval(_FINGERPRINT_JS)
                errors_before = len(drive.console)
                result = drive.click(control["id"])
                pressed += 1
                if result != "clicked":
                    findings.append(f'{surface} > {control["id"]}: {result}')
                    continue
                if not drive.settle():
                    findings.append(
                        f'NEVER SETTLED: {control["id"]} ({control["name"]}) left the screen '
                        "still changing - an animation that does not finish, or a render loop"
                    )
                after = drive.eval(_FINGERPRINT_JS)
                new_errors = drive.console[errors_before:]
                for line in new_errors:
                    if line.startswith("error"):
                        findings.append(f'ERROR after clicking {control["id"]}: {line}')
                # Re-pressing the surface you are already on correctly does nothing. Reporting that
                # is the detector firing on RELEVANCE rather than on a real miss.
                if after == before and not new_errors and control["id"] != surface:
                    findings.append(
                        f'NO EFFECT: {control["id"]} ({control["name"]}) changed nothing on screen '
                        "and logged nothing - a control that does not appear to do anything"
                    )
                if args.shots:
                    shot_n += 1
                    drive.shot(out_dir / f'{surface}-{shot_n:02d}-{control["id"]}.png')
                stuck = drive.escape()
                if stuck:
                    findings.append(
                        f"STUCK MODAL: {stuck} opened by {control['id']} would not close on Escape "
                        "or by its own close control - everything behind it is unreachable"
                    )
                    # leave the surface and come back, so one stuck dialog cannot end the sweep
                    drive.click(surface)
                drive.settle()
    finally:
        drive.close()

    print(f"\n=== TOUR: pressed {pressed} controls across {len(surfaces)} surfaces ===")
    if skipped:
        print(f"\nSKIPPED as destructive ({len(skipped)}) - NOT exercised, say so in any report:")
        for line in skipped:
            print(f"  {line}")
    if findings:
        print(f"\nFINDINGS ({len(findings)}):")
        for line in findings:
            print(f"  {line}")
    else:
        print("\nNo findings: every control pressed landed, settled, and changed something.")
    return 1 if findings else 0


def _run_steps(drive: Drive, steps: list[str], out_dir: Path) -> int:
    """Run a batch of steps over ONE connection. `click:x`, `text:x`, `eval:js`, `shot`, `wait:0.5`."""
    shot_n = 0
    failed = False
    for step in steps:
        verb, _, arg = step.partition(":")
        if verb == "click":
            result = drive.click(arg)
            print(f"click {arg}: {result}")
            if not str(result).startswith("clicked"):
                failed = True
        elif verb == "text":
            print(f"text {arg}: {drive.text(arg)}")
        elif verb == "eval":
            print(f"eval: {drive.eval(arg)}")
        elif verb == "wait":
            time.sleep(float(arg or 0.4))
        elif verb == "console":
            # mid-batch console read, so a click's own errors can be seen at the point they happen
            # rather than only in the dump at the end of the run
            drive.flush_events()
            print("console so far: " + ("; ".join(drive.console) or "(nothing logged)"))
        elif verb == "shot":
            shot_n += 1
            path = Path(arg) if arg else out_dir / f"drive-{shot_n}.png"
            print(f"shot -> {drive.shot(path)}")
        else:
            print(f"unknown step {step!r}")
            failed = True
    if drive.console:
        print("console:")
        for line in drive.console:
            print(f"  {line}")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--out", default="drive-shots", help="where bare `shot` steps write")
    sub = ap.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up", help="launch the install with CDP on")
    up.add_argument("--install", default="", help="override the discovered install directory")
    up.add_argument("--timeout", type=float, default=60.0)
    up.set_defaults(func=cmd_up)

    sub.add_parser("down", help="stop the host by its process tree").set_defaults(func=cmd_down)

    tour = sub.add_parser("tour", help="click through the app like a tester and report what breaks")
    tour.add_argument("--surface", action="append", default=[],
                      help="rail dev-id to visit (repeatable); defaults to every rail surface")
    tour.add_argument("--max-clicks", type=int, default=40, help="controls to press per surface")
    tour.add_argument("--shots", action="store_true", help="capture the window after every click")
    tour.add_argument("--include-destructive", action="store_true",
                      help="ALSO press deletes, commits and writes. Never on a real library.")
    tour.set_defaults(func=cmd_tour)

    for name, help_text in (
        ("click", "click a data-dev-id"),
        ("text", "read a data-dev-id's text"),
        ("eval", "evaluate an expression in the page"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("arg")
        p.add_argument("--shot", action="store_true", help="capture the window afterwards")
        p.set_defaults(single=name)

    p_shot = sub.add_parser("shot", help="capture the real window")
    p_shot.add_argument("arg", nargs="?", default="")
    p_shot.set_defaults(single="shot")

    sub.add_parser("console", help="what the page has logged").set_defaults(single="console")

    p_do = sub.add_parser("do", help="run several steps over ONE connection")
    p_do.add_argument("steps", nargs="+")
    p_do.set_defaults(single="do")

    args = ap.parse_args()
    if getattr(args, "func", None):
        return args.func(args)

    out_dir = Path(args.out)
    try:
        drive = Drive(args.port)
    except NoWindow as exc:
        print(f"NO WINDOW: {exc}")
        return 2
    try:
        if args.single == "do":
            return _run_steps(drive, args.steps, out_dir)
        if args.single == "console":
            drive.flush_events()
            for line in drive.console or ["(nothing logged)"]:
                print(line)
            return 0
        steps = [f"{args.single}:{args.arg}" if args.single != "shot" else f"shot:{args.arg}"]
        if getattr(args, "shot", False):
            steps.append("shot")
        return _run_steps(drive, steps, out_dir)
    finally:
        drive.close()


if __name__ == "__main__":
    raise SystemExit(main())
