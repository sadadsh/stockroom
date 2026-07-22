"""LIVE Windows validation of the real WebView2 download capture (plan Task 2.5 companion).

Where win_run_capture.py proves the pure pipeline with SIMULATED file drops, this opens the
REAL host guided-capture window against a local HTTP server that serves a KiCad test zip AS AN
ATTACHMENT, and asserts the actual WebView2 download is captured, classified, and forwarded
with the right requirements + the live session token - closing the one Phase 2 gate that a
simulated drop cannot: the tier-1 CoreWebView2 DownloadStarting intercept (or, if that pywebview
version does not match, the tier-2 Downloads watch) firing on a genuine download through a real
window. Reports which tier fired.

Windows-only (needs pywebview + WebView2); run from the winverify clone:
    uv run python -m stockroom.host.win_live_capture
It briefly opens a window on the desktop, drives one download, then closes itself.
"""

from __future__ import annotations

import http.server
import io
import json
import socketserver
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from stockroom.host import window as W


def _kicad_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("part.kicad_sym", "sym")
        zf.writestr("part.kicad_mod", "fp")
        zf.writestr("part.step", "model")
    return buf.getvalue()


_ZIP = _kicad_zip_bytes()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/").endswith(".zip"):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="stockroom-live-part.zip"')
            self.send_header("Content-Length", str(len(_ZIP)))
            self.end_headers()
            self.wfile.write(_ZIP)
        else:
            body = b"<!doctype html><meta charset=utf-8><title>dl</title><body>download</body>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):  # silence the request log
        pass


def main() -> int:
    import webview

    # Capture the forward without a real SPA: the emit->evaluate_js hop is trivial and already
    # Linux-tested; what we are validating here is the real download -> classify -> payload.
    captured: list[dict] = []
    W._emit_to_spa = lambda payload: captured.append(payload)

    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    srv.allow_reuse_address = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/stockroom-live-part.zip"

    result: dict = {"ok": False, "captured": None, "tier": None, "token_ok": None, "error": None}

    main_win = webview.create_window("stockroom-live", html="<html><body>host</body></html>", hidden=True)
    W._ACTIVE_WINDOW = main_win
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # same as run_window; WebView2 blocks downloads otherwise
    except Exception:  # noqa: BLE001
        pass

    def driver() -> None:
        try:
            time.sleep(1.5)  # let the GUI + WebView2 environment settle
            needs = ["kicad_symbol", "kicad_footprint", "kicad_model"]
            token = W._HostApi().open_cad_download(url, needs)
            deadline = time.time() + 25.0
            while time.time() < deadline and not captured:
                time.sleep(0.25)
            result["captured"] = list(captured)
            if captured:
                p = captured[0]
                temp = str(getattr(W._CAD_SESSION, "temp_dir", "") or "")
                result["tier"] = (
                    "tier1-intercept" if temp and str(p.get("path", "")).startswith(temp) else "tier2-watch"
                )
                result["token_ok"] = p.get("token") == token
                result["ok"] = result["token_ok"] and "kicad_symbol" in (p.get("requirements") or [])
        except Exception as e:  # noqa: BLE001
            result["error"] = repr(e)
        finally:
            for w in list(getattr(webview, "windows", [])):
                try:
                    w.destroy()
                except Exception:  # noqa: BLE001
                    pass

    profile = Path(tempfile.gettempdir()) / "stockroom-live-profile"
    profile.mkdir(parents=True, exist_ok=True)
    webview.start(driver, **W._webview_start_kwargs(webview.start, profile))
    try:
        srv.shutdown()
    except Exception:  # noqa: BLE001
        pass

    print("LIVE_RESULT " + json.dumps(result, default=str))
    if result["ok"]:
        print(f"PASS: real WebView2 download captured via {result['tier']} and forwarded with the session token")
        return 0
    print("FAIL: real WebView2 capture did not verify (see LIVE_RESULT)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
