"""Real-Windows proof for the guided-capture host pipeline (plan
docs/superpowers/plans/2026-07-22-guided-capture-workflow.md, Task 2.5).

Run on real Windows Python from the winverify clone:

    uv run python -m stockroom.host.win_run_capture

It drives the REAL host capture functions - CaptureSession, the widened DownloadsWatch,
_poll_downloads_watch, _forward_cad_capture, classify_asset, _extract_altium_members - with
SIMULATED file drops into a temp watch dir (the same shape a vendor download lands in),
capturing every CaptureForward the SPA would receive via a recording stand-in window, and
asserting:

  1. a KiCad zip forwards with its path + the KiCad requirements + the live session token;
  2. a loose Altium .SchLib forwards its own path as the attach source;
  3. a mixed zip forwards the loose Altium paths extracted from it + all the needed
     requirements (KiCad + Altium together, the both-format goal);
  4. a stale prior session, once stopped, never forwards onto the session that replaced it
     (B4) - a late file dropped after the stop reaches no one;
  5. a deadline reached with unmet needs forwards a {signal:'timeout'} (B1, host side);
  6. the session temp dir is cleaned on stop (B8).

This exercises the whole capture -> classify -> extract -> forward -> session-gating pipeline
against real files and real threads. It deliberately does NOT open a WebView2 window or arm
the tier-1 download intercept: those are the one Windows-only piece owner-verified against a
live vendor download (the actual click-to-save timing), and the real both-format AUTO-ATTACH
against the live ingest + Altium pipelines is Task 3.4. Because it uses only pure host
functions (no pywebview), it also runs on Linux - useful for smoke-testing the harness itself
- but its POINT is to prove the zip/IntLib extraction + threading run correctly under real
Windows Python.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from stockroom.capture.requirements import Requirement
from stockroom.capture.session import CaptureSession
from stockroom.host import window as W
from stockroom.host.download_capture import DownloadsWatch

R = Requirement


class _Recorder:
    """A stand-in for the SPA window: records every CaptureForward it is handed so a forward
    can be asserted without a real WebView2."""

    def __init__(self) -> None:
        self.scripts: list[str] = []

    def evaluate_js(self, script: str) -> None:
        self.scripts.append(script)

    def payloads(self) -> list[dict]:
        import json

        head = "window.__STOCKROOM_CAD_DOWNLOAD__("
        out = []
        for js in self.scripts:
            body = js.split(head, 1)[1]
            out.append(json.loads(body[:-2]))
        return out


def _atomic(path: Path, write) -> None:
    """Write `path` atomically: build into a sibling with a non-watched suffix, then rename
    into place. This mirrors how a real browser download appears - it writes to a
    *.crdownload and renames to the final name on completion - so the watch never reads a
    file mid-write (which would classify a half-written zip as unusable and mark it seen)."""
    tmp = Path(str(path) + ".building")  # .building is not a watched suffix, so poll skips it
    write(tmp)
    os.replace(tmp, path)


def _make_kicad_zip(path: Path) -> None:
    def _w(target: Path) -> None:
        with zipfile.ZipFile(target, "w") as zf:
            zf.writestr("KiCad/part.kicad_sym", "sym")
            zf.writestr("KiCad/part.kicad_mod", "fp")
            zf.writestr("KiCad/part.step", "model")

    _atomic(path, _w)


def _make_mixed_zip(path: Path) -> None:
    def _w(target: Path) -> None:
        with zipfile.ZipFile(target, "w") as zf:
            zf.writestr("KiCad/part.kicad_sym", "sym")
            zf.writestr("KiCad/part.kicad_mod", "fp")
            zf.writestr("Altium/part.SchLib", "SCHDATA")
            zf.writestr("Altium/part.PcbLib", "PCBDATA")

    _atomic(path, _w)


def _run_capture(needs, drop, *, token, timeout=8.0):
    """Arm the REAL tier-2 poll loop over a fresh temp watch dir, let `drop(watch_dir)` create
    the simulated download, and return (payloads, session, temp_dir) once the session
    completes or the poll thread ends. The watch is armed a few seconds in the past so a
    freshly written file's (possibly coarse) mtime is unambiguously after the start."""
    watch_dir = Path(tempfile.mkdtemp(prefix="wrc-watch-"))
    extract_dir = Path(tempfile.mkdtemp(prefix="wrc-extract-"))
    recorder = _Recorder()
    W._ACTIVE_WINDOW = recorder
    session = CaptureSession.start("", frozenset(needs), now=time.time(), token=token)
    session.temp_dir = extract_dir
    watch = DownloadsWatch(watch_dir, time.time() - 5.0)
    thread = threading.Thread(
        target=W._poll_downloads_watch,
        args=(watch, session),
        kwargs={"extract_dir": extract_dir, "interval": 0.1, "timeout": timeout},
        daemon=True,
    )
    thread.start()
    drop(watch_dir)
    deadline = time.time() + timeout + 2.0
    while thread.is_alive() and time.time() < deadline and not session.is_complete():
        time.sleep(0.05)
    # Let the poll loop run its own completion path (which fires the done signal + closes) rather
    # than racing it with an external stop; only stop as a fallback if it never completed.
    thread.join(timeout=2.0)
    session.stop()
    W._ACTIVE_WINDOW = None
    shutil.rmtree(watch_dir, ignore_errors=True)
    return recorder.payloads(), session, extract_dir


class _Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, cond: bool, label: str) -> None:
        mark = "PASS" if cond else "FAIL"
        print(f"  [{mark}] {label}")
        if not cond:
            self.failures.append(label)


def _scenario_kicad_zip(c: _Checks) -> None:
    print("Scenario 1: a KiCad zip forwards path + kicad requirements + token")
    payloads, session, temp = _run_capture(
        {R.KICAD_SYMBOL, R.KICAD_FOOTPRINT, R.KICAD_MODEL},
        lambda d: _make_kicad_zip(d / "part-cad.zip"),
        token="tok-kicad",
    )
    forwards = [x for x in payloads if "path" in x]
    c.ok(len(forwards) == 1, "exactly one forward")
    c.ok({"signal": "done", "token": "tok-kicad"} in payloads, "a done signal fired on completion")
    p = forwards[0] if forwards else {}
    c.ok(p.get("path", "").endswith("part-cad.zip"), "forward carries the zip path")
    c.ok(p.get("token") == "tok-kicad", "forward carries the live session token")
    c.ok(
        set(p.get("requirements", [])) == {"kicad_symbol", "kicad_footprint", "kicad_model"},
        "forward classifies all three KiCad requirements",
    )
    c.ok("altiumPaths" not in p, "no Altium paths on a KiCad-only capture")
    c.ok(session.is_complete(), "session reached complete")
    shutil.rmtree(temp, ignore_errors=True)


def _scenario_loose_altium(c: _Checks) -> None:
    print("Scenario 2: a loose Altium .SchLib forwards its own path")

    def drop(d: Path) -> None:
        _atomic(d / "part.SchLib", lambda t: t.write_bytes(b"SCHDATA"))

    payloads, _session, temp = _run_capture({R.ALTIUM_SYMBOL}, drop, token="tok-altium")
    forwards = [x for x in payloads if "path" in x]
    c.ok(len(forwards) == 1, "exactly one forward")
    c.ok({"signal": "done", "token": "tok-altium"} in payloads, "a done signal fired on completion")
    p = forwards[0] if forwards else {}
    c.ok(set(p.get("requirements", [])) == {"altium_symbol"}, "classifies altium_symbol")
    c.ok(
        [Path(a).name for a in p.get("altiumPaths", [])] == ["part.SchLib"],
        "the loose .SchLib is handed over as the altium attach path",
    )
    shutil.rmtree(temp, ignore_errors=True)


def _scenario_mixed_zip(c: _Checks) -> None:
    print("Scenario 3: a mixed zip forwards extracted Altium paths + both formats")
    payloads, session, temp = _run_capture(
        {R.KICAD_SYMBOL, R.ALTIUM_SYMBOL, R.ALTIUM_FOOTPRINT},
        lambda d: _make_mixed_zip(d / "bundle.zip"),
        token="tok-mixed",
    )
    forwards = [x for x in payloads if "path" in x]
    c.ok(len(forwards) == 1, "exactly one forward")
    c.ok({"signal": "done", "token": "tok-mixed"} in payloads, "a done signal fired on completion")
    p = forwards[0] if forwards else {}
    c.ok(
        set(p.get("requirements", [])) == {"kicad_symbol", "altium_symbol", "altium_footprint"},
        "classifies the needed KiCad + Altium requirements together",
    )
    names = sorted(Path(a).name for a in p.get("altiumPaths", []))
    c.ok(names == ["part.PcbLib", "part.SchLib"], "both Altium members extracted to loose paths")
    c.ok(
        all(Path(a).exists() for a in p.get("altiumPaths", [])),
        "the extracted Altium files exist on disk for the attach route",
    )
    c.ok(session.is_complete(), "session reached complete")
    shutil.rmtree(temp, ignore_errors=True)


def _scenario_stale_session_isolated(c: _Checks) -> None:
    print("Scenario 4: a stopped session never forwards onto the session that replaces it (B4)")
    watch_dir = Path(tempfile.mkdtemp(prefix="wrc-stale-"))
    extract_dir = Path(tempfile.mkdtemp(prefix="wrc-stale-x-"))
    recorder = _Recorder()
    W._ACTIVE_WINDOW = recorder
    stale = CaptureSession.start("", frozenset({R.KICAD_SYMBOL}), now=time.time(), token="STALE")
    stale.temp_dir = extract_dir
    watch = DownloadsWatch(watch_dir, time.time() - 5.0)
    thread = threading.Thread(
        target=W._poll_downloads_watch,
        args=(watch, stale),
        kwargs={"extract_dir": extract_dir, "interval": 0.1, "timeout": 8.0},
        daemon=True,
    )
    thread.start()
    stale.stop()  # replaced by a newer capture before any file lands
    thread.join(timeout=2.0)
    _make_kicad_zip(watch_dir / "late.zip")  # a late download arrives AFTER the stop
    time.sleep(0.5)
    W._ACTIVE_WINDOW = None
    c.ok(recorder.scripts == [], "the stopped session forwarded nothing (no misattribution)")
    shutil.rmtree(watch_dir, ignore_errors=True)
    shutil.rmtree(extract_dir, ignore_errors=True)


def _scenario_timeout_signal(c: _Checks) -> None:
    print("Scenario 5: a deadline with unmet needs forwards a timeout signal (B1)")
    recorder = _Recorder()
    W._ACTIVE_WINDOW = recorder
    session = CaptureSession.start("", frozenset({R.KICAD_SYMBOL}), now=time.time(), token="tok-to")
    times = iter([0.0, 0.0, 1000.0])  # deadline=300; first check in-window, next past it
    W._poll_downloads_watch(
        _EmptyWatch(), session, extract_dir=None,
        interval=0.0, timeout=300.0, sleep=lambda *_: None, now=lambda: next(times),
    )
    W._ACTIVE_WINDOW = None
    payloads = recorder.payloads()
    c.ok(payloads == [{"signal": "timeout", "token": "tok-to"}], "a single timeout signal fired")


def _scenario_temp_cleanup(c: _Checks) -> None:
    print("Scenario 6: _stop_active_capture cleans the session temp dir (B8)")
    session = CaptureSession.start("", frozenset({R.KICAD_SYMBOL}), now=time.time(), token="tok-c")
    temp = Path(tempfile.mkdtemp(prefix="wrc-clean-"))
    (temp / "part.SchLib").write_bytes(b"x")
    session.temp_dir = temp
    W._CAD_SESSION = session
    W._CAD_POLL_THREAD = None
    W._stop_active_capture()
    c.ok(not temp.exists(), "the temp dir was removed")
    c.ok(W._CAD_SESSION is None and W._CAD_POLL_THREAD is None, "the live-capture globals cleared")


class _EmptyWatch:
    def poll(self):
        return None


def main() -> int:
    print(f"win_run_capture: guided-capture host pipeline proof (os.name={__import__('os').name})")
    checks = _Checks()
    _scenario_kicad_zip(checks)
    _scenario_loose_altium(checks)
    _scenario_mixed_zip(checks)
    _scenario_stale_session_isolated(checks)
    _scenario_timeout_signal(checks)
    _scenario_temp_cleanup(checks)
    print()
    if checks.failures:
        print(f"FAILED ({len(checks.failures)}): " + "; ".join(checks.failures))
        return 1
    print("ALL SCENARIOS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
