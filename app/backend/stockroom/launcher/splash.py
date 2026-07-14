"""A first-run progress splash for the frozen launcher (M9).

The launcher's provisioning (clone + WebView2 install + `uv sync`, which downloads Python + the
deps) can take minutes on first run with the console suppressed, so without this the user sees
NOTHING after double-clicking. This shows a small native window ("Setting up Stockroom...") with
the current phase and an indeterminate bar, closing the moment provisioning finishes and the host
window is about to appear.

SAFE BY DESIGN: if tkinter is unavailable or fails for ANY reason, run() falls back to running the
work directly (no splash), so the splash can NEVER stop the app from launching. tkinter is stdlib
and PyInstaller bundles Tcl/Tk. The GUI path is not unit-tested (headless CI has no display); the
fallback path IS tested.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from typing import Callable

Work = Callable[[Callable[[str], None]], int]

_PHASE_TEXT = {
    "clone": "Downloading Stockroom...",
    "webview2": "Preparing the display runtime...",
    "sync": "Installing components (first run can take a few minutes)...",
    "starting": "Starting Stockroom...",
}


def run(work: Work) -> int:
    """Run `work(progress)` while showing a first-run splash, returning work's exit code. `work`
    is supervise bound to a workdir; it receives a progress(phase) callback. Falls back to running
    work with a no-op progress if a splash cannot be shown, so the splash never blocks the launch."""
    try:
        return _run_with_splash(work)
    except Exception:  # noqa: BLE001 - a splash must NEVER stop the app from launching
        return work(lambda _phase: None)


def _run_with_splash(work: Work) -> int:  # pragma: no cover - GUI path, needs a real display
    import queue
    import threading
    import tkinter as tk
    from tkinter import ttk

    events: queue.Queue = queue.Queue()
    result: dict = {}

    def worker() -> None:
        try:
            result["code"] = work(lambda phase: events.put(phase))
        except BaseException as exc:  # noqa: BLE001 - carried back after the mainloop returns
            result["error"] = exc
        finally:
            events.put("__done__")

    root = tk.Tk()
    root.title("Stockroom")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Stockroom", font=("Segoe UI", 14, "bold")).pack(anchor="w")
    status = ttk.Label(frame, text="Setting up Stockroom...", width=46)
    status.pack(anchor="w", pady=(6, 10))
    bar = ttk.Progressbar(frame, mode="indeterminate", length=340)
    bar.pack(fill="x")
    bar.start(12)

    thread = threading.Thread(target=worker, daemon=True, name="stockroom-provision")
    thread.start()

    def poll() -> None:
        close = False
        try:
            while True:
                phase = events.get_nowait()
                if phase in ("starting", "__done__"):
                    close = True
                else:
                    status.config(text=_PHASE_TEXT.get(phase, "Setting up Stockroom..."))
        except queue.Empty:
            pass
        if close:
            root.destroy()
            return
        root.after(120, poll)

    root.after(120, poll)
    root.mainloop()

    # The splash closed once provisioning finished; the worker (supervise) keeps running the host
    # for the whole session. Wait for it, then surface its result / error to the entry point.
    thread.join()
    if "error" in result:
        raise result["error"]
    return int(result.get("code", 0))
