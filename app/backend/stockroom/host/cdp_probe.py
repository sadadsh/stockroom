"""A tiny Chrome DevTools Protocol (CDP) client for LIVE visibility into the WebView2
guided-capture page (the vendor cad window).

Why this exists: the guided-capture driver runs as injected JS inside a REMOTE WebView2
page. When a step stalls, pywebview's `evaluate_js` from a background thread can return
None (a busy page never answers), and a screenshot only shows the last frame - so past
sessions debugged the two-format download BLIND and went in circles. CDP is a separate,
out-of-band channel: WebView2 exposes it when launched with
`--remote-debugging-port=<N>` (pywebview wires that from `webview.settings['REMOTE_
DEBUGGING_PORT']`). Over it we read `console.log` / thrown exceptions AS THEY HAPPEN
(buffered by the browser, so they survive a page that later goes unresponsive) and run
`Runtime.evaluate` in the REAL page context on demand.

Pure-ish: `websocket` + `urllib` imports are lazy inside methods, so the module imports on
Linux (where WebView2/CDP does not exist) and only ever connects on Windows against a live
WebView2 debug port. Everything degrades to a logged no-op rather than raising, so a probe
failure can never crash the capture it is only observing."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from typing import Any, Callable

_log = logging.getLogger("stockroom.host.cdp")

# CDP RemoteObject subtypes we render specially when formatting console args.
_MAX_ARG = 400


def list_targets(port: int, *, host: str = "127.0.0.1", timeout: float = 2.0) -> list[dict]:
    """The debug targets WebView2 exposes at http://host:port/json (each a dict with
    `type`, `url`, `title`, `webSocketDebuggerUrl`). [] on any error - the port may not be
    open yet while CoreWebView2 is still initializing."""
    url = f"http://{host}:{port}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback debug port
            data = resp.read()
        parsed = json.loads(data.decode("utf-8"))
        return parsed if isinstance(parsed, list) else []
    except Exception:  # noqa: BLE001 - port not ready / no CDP; caller retries or degrades
        return []


def wait_for_target(
    port: int,
    url_contains: str = "",
    *,
    host: str = "127.0.0.1",
    tries: int = 40,
    delay: float = 0.25,
    sleep=time.sleep,
) -> dict | None:
    """Poll list_targets until a page target whose url contains `url_contains` (case-
    insensitive; "" matches the first page) appears, or `tries` elapse. Returns the target
    dict or None. WebView2's CoreWebView2 inits async, so the debug port and its page target
    only appear a beat after the window is created - hence the poll."""
    needle = (url_contains or "").lower()
    for _ in range(max(1, tries)):
        for t in list_targets(port, host=host):
            if t.get("type") != "page":
                continue
            if not needle or needle in (t.get("url", "") or "").lower():
                if t.get("webSocketDebuggerUrl"):
                    return t
        sleep(delay)
    return None


def _fmt_remote_object(obj: dict) -> str:
    """Render one CDP RemoteObject (a console arg) to a short string."""
    if not isinstance(obj, dict):
        return str(obj)
    if "value" in obj:
        v = obj["value"]
        s = v if isinstance(v, str) else json.dumps(v, default=str)
    elif obj.get("description"):
        s = str(obj["description"])
    elif obj.get("type") == "undefined":
        s = "undefined"
    else:
        s = str(obj.get("preview") or obj.get("type") or "?")
    return s[:_MAX_ARG]


def format_console_args(args: list) -> str:
    return " ".join(_fmt_remote_object(a) for a in (args or []))


class CDPClient:
    """A minimal single-target CDP client. Connect to one page target, enable Runtime + Log,
    stream console/exception events to a sink callback, and run evaluate() synchronously.

    Threading: one daemon reader thread pumps the socket; command replies are matched by id
    through an Event+result box, events go to the sink. send() is serialized under a lock.
    Never raises out of the public methods once constructed - a dead socket degrades to
    None/logged so it cannot crash the capture being observed."""

    def __init__(self, ws_url: str, on_event: Callable[[dict], None] | None = None):
        self._ws_url = ws_url
        self._on_event = on_event
        self._ws = None
        self._id = 0
        self._id_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pending: dict[int, dict] = {}
        self._pending_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._closed = False

    def connect(self, *, open_timeout: float = 5.0) -> bool:
        try:
            import websocket  # websocket-client; lazy so the module imports on Linux
        except Exception:  # noqa: BLE001 - lib missing; probe unavailable, caller degrades
            _log.warning("cdp: websocket-client not installed; probe disabled")
            return False
        try:
            # A big max frame - CDP evaluate results (DOM dumps) can be large.
            # suppress_origin=True: Chromium/WebView2 reject a DevTools WebSocket whose Origin
            # header is not in --remote-allow-origins (empty by default -> 403 Forbidden). A
            # connection with NO Origin header (a non-browser client) is allowed, so we suppress
            # it rather than needing to also pass --remote-allow-origins on the browser side.
            self._ws = websocket.create_connection(
                self._ws_url,
                timeout=open_timeout,
                max_size=None,
                enable_multithread=True,
                suppress_origin=True,
            )
            self._ws.settimeout(None)  # blocking recv on the reader thread
        except Exception as e:  # noqa: BLE001
            _log.warning("cdp: connect failed: %r", e)
            return False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def _read_loop(self) -> None:
        while not self._closed:
            try:
                raw = self._ws.recv()
            except Exception:  # noqa: BLE001 - socket closed / error; stop pumping
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            mid = msg.get("id")
            if mid is not None:
                with self._pending_lock:
                    box = self._pending.get(mid)
                if box is not None:
                    box["result"] = msg
                    box["event"].set()
                continue
            if self._on_event is not None:
                try:
                    self._on_event(msg)
                except Exception:  # noqa: BLE001 - a sink error must not kill the reader
                    pass

    def _next_id(self) -> int:
        with self._id_lock:
            self._id += 1
            return self._id

    def send(self, method: str, params: dict | None = None, *, timeout: float = 8.0) -> dict | None:
        """Send a CDP command and wait for its reply (the full message dict), or None on
        timeout / dead socket."""
        if self._ws is None or self._closed:
            return None
        mid = self._next_id()
        box = {"event": threading.Event(), "result": None}
        with self._pending_lock:
            self._pending[mid] = box
        payload = json.dumps({"id": mid, "method": method, "params": params or {}})
        try:
            with self._send_lock:
                self._ws.send(payload)
        except Exception as e:  # noqa: BLE001
            _log.warning("cdp: send %s failed: %r", method, e)
            with self._pending_lock:
                self._pending.pop(mid, None)
            return None
        got = box["event"].wait(timeout)
        with self._pending_lock:
            self._pending.pop(mid, None)
        return box["result"] if got else None

    def enable(self) -> None:
        """Turn on the domains that surface console + errors. Runtime.enable makes the page
        replay any console API calls and start streaming Runtime.consoleAPICalled /
        Runtime.exceptionThrown; Log.enable adds browser log entries (network, etc.)."""
        self.send("Runtime.enable")
        self.send("Log.enable")
        self.send("Page.enable")

    def evaluate(self, expression: str, *, timeout: float = 8.0, await_promise: bool = False) -> Any:
        """Run `expression` in the page's top context and return its value (returnByValue).
        Returns None on any failure so a probe read can never raise into the caller."""
        msg = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "timeout": int(timeout * 1000),
            },
            timeout=timeout + 2.0,
        )
        if not msg:
            return None
        result = (msg.get("result") or {}).get("result") or {}
        if "value" in result:
            return result["value"]
        return result.get("description")

    def close(self) -> None:
        self._closed = True
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:  # noqa: BLE001
            pass


class ConsoleTap:
    """Turn raw CDP events into human-readable console/exception lines and hand each to a
    `write(line)` sink (e.g. a file writer). Attach ConsoleTap.on_event as the CDPClient's
    on_event. Every line is `+<ms since start> <LEVEL> <text>` so the driver's step timeline
    is directly readable."""

    def __init__(self, write: Callable[[str], None], *, now=time.time):
        self._write = write
        self._now = now
        self._t0 = now()

    def _stamp(self) -> str:
        return f"+{int((self._now() - self._t0) * 1000):>7}ms"

    def on_event(self, msg: dict) -> None:
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}
        if method == "Runtime.consoleAPICalled":
            level = str(params.get("type", "log")).upper()
            text = format_console_args(params.get("args", []))
            self._write(f"{self._stamp()} {level:<7} {text}")
        elif method == "Runtime.exceptionThrown":
            det = params.get("exceptionDetails", {}) or {}
            exc = det.get("exception", {}) or {}
            text = exc.get("description") or det.get("text") or "exception"
            url = det.get("url", "")
            line = det.get("lineNumber", "?")
            self._write(f"{self._stamp()} EXC     {text} @ {url}:{line}")
        elif method == "Log.entryAdded":
            entry = params.get("entry", {}) or {}
            lvl = str(entry.get("level", "info")).upper()
            if lvl in ("ERROR", "WARNING"):
                self._write(f"{self._stamp()} LOG-{lvl:<4} {entry.get('text', '')}")
