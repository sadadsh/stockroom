import json
import threading
import zipfile
from pathlib import Path

import pytest

from stockroom.host.window import (
    active_window,
    drop_forward_js,
    dropped_paths_to_inspect_body,
    inject_script,
    native_drop_paths,
    should_inject,
)


def test_dropped_paths_become_an_inspect_body():
    body = dropped_paths_to_inspect_body([r"C:\Users\me\part.zip", r"C:\Users\me\sym.kicad_sym"])
    assert body == {
        "paths": [r"C:\Users\me\part.zip", r"C:\Users\me\sym.kicad_sym"],
        "lcsc_ids": [],
    }


def test_dropped_paths_empty_is_an_empty_inspect_body():
    assert dropped_paths_to_inspect_body([]) == {"paths": [], "lcsc_ids": []}


def test_active_window_is_none_before_a_window_runs():
    assert active_window() is None


# -- native drop (WebView2 only exposes real paths to pywebview-registered handlers) --


def test_native_drop_paths_extracts_pywebview_full_paths():
    event = {
        "dataTransfer": {
            "files": [
                {"name": "part.zip", "pywebviewFullPath": "C:\\Users\\me\\part.zip"},
                {"name": "model.step", "pywebviewFullPath": "C:\\Users\\me\\model.step"},
            ]
        }
    }
    assert native_drop_paths(event) == [
        "C:\\Users\\me\\part.zip",
        "C:\\Users\\me\\model.step",
    ]


def test_native_drop_paths_skips_files_without_a_path():
    event = {
        "dataTransfer": {
            "files": [
                {"name": "a.zip"},  # WebView2 exposed no path for this one
                "not-a-dict",
                {"name": "b.zip", "pywebviewFullPath": ""},
                {"name": "c.zip", "pywebviewFullPath": "C:\\c.zip"},
            ]
        }
    }
    assert native_drop_paths(event) == ["C:\\c.zip"]


def test_native_drop_paths_tolerates_a_malformed_event():
    assert native_drop_paths({}) == []
    assert native_drop_paths({"dataTransfer": None}) == []
    assert native_drop_paths({"dataTransfer": {"files": None}}) == []
    assert native_drop_paths(None) == []


def test_drop_forward_js_is_guarded_and_json_safe():
    tricky = 'C:\\Users\\quo"te\\part.zip'
    js = drop_forward_js([tricky])
    # guarded: a renderer that has not registered the hook is a no-op, not an error
    assert js.startswith("window.__STOCKROOM_NATIVE_DROP__ &&")
    # JSON-encoded so a quote or backslash in a path cannot break out of the script
    assert json.dumps([tricky]) in js


def test_inject_script_hands_the_spa_the_base_and_token():
    js = inject_script("http://127.0.0.1:5123", "tok-abc123")
    # the SPA reads EXACTLY these two globals (app/frontend/src/lib/runtime.ts):
    # window.__API_BASE__ and window.__STOCKROOM_TOKEN__ — anything else and the
    # window opens but the SPA cannot authenticate (a blank page).
    assert f"window.__API_BASE__ = {json.dumps('http://127.0.0.1:5123')}" in js
    assert f"window.__STOCKROOM_TOKEN__ = {json.dumps('tok-abc123')}" in js
    # service workers are cleared so a self-update never serves a stale bundle
    assert "serviceWorker" in js and "unregister" in js


def test_inject_script_escapes_a_token_with_special_characters():
    # a token containing a quote/backslash must not break out of the JS string; the
    # values are JSON-encoded, so the raw quote never appears unescaped.
    js = inject_script("http://127.0.0.1:5123", 'tok"quote\\back')
    tok = js.split("window.__STOCKROOM_TOKEN__ = ", 1)[1].split(";", 1)[0]
    assert json.loads(tok) == 'tok"quote\\back'
    base = js.split("window.__API_BASE__ = ", 1)[1].split(";", 1)[0]
    assert json.loads(base) == "http://127.0.0.1:5123"


def test_should_inject_only_on_the_loopback_spa_origin():
    base = "http://127.0.0.1:5123"
    # the SPA itself (same loopback origin) gets the token
    assert should_inject("http://127.0.0.1:5123/", base) is True
    assert should_inject("http://127.0.0.1:5123/index.html", base) is True
    # a remote vendor / anti-bot page NEVER receives the token (the leak the review found)
    assert should_inject("https://www.digikey.com/en/products/x", base) is False
    assert should_inject("https://challenges.cloudflare.com/turnstile", base) is False
    # a different local port is a different origin -> also denied
    assert should_inject("http://127.0.0.1:9999/", base) is False
    # unknown / blank current url fails CLOSED (never hand out the token)
    assert should_inject(None, base) is False
    assert should_inject("", base) is False


@pytest.mark.windows_only
def test_real_window_opens_and_serves_a_non_blank_page():
    # Owner runs on Windows per the acceptance bar; asserts the window loads the
    # FastAPI-served page, the token is injected, drag/drop posts a full path, and
    # closing stops uvicorn. Skipped everywhere else.
    ...


# -- bind_native_drop registers real DOM handlers (revert-safe coverage of the fix) --


class _Slot(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self


def _fake_window_with_document():
    class Events:
        def __init__(self):
            self.dragover = _Slot()
            self.drop = _Slot()

    class Document:
        def __init__(self):
            self.events = Events()

    class Dom:
        def __init__(self):
            self.document = Document()

    class Window:
        def __init__(self):
            self.dom = Dom()

    return Window()


def test_bind_native_drop_registers_dragover_and_drop_handlers():
    from stockroom.host.window import bind_native_drop

    win = _fake_window_with_document()
    captured = {}

    def fake_dom_event_handler(fn, prevent_default=False, stop_propagation=False, debounce=0):
        captured.setdefault("prevent_default", []).append(prevent_default)
        return ("H", fn)

    ok = bind_native_drop(win, lambda e: None, dom_event_handler=fake_dom_event_handler)
    assert ok is True
    # both a dragover (to preventDefault so drop fires) and a drop handler landed
    assert len(win.dom.document.events.dragover) == 1
    assert len(win.dom.document.events.drop) == 1
    assert captured["prevent_default"] == [True, True]


def test_bind_native_drop_is_false_when_dom_api_absent():
    from stockroom.host.window import bind_native_drop

    class NoDom:
        @property
        def dom(self):
            raise RuntimeError("this backend has no DOM API")

    assert bind_native_drop(NoDom(), lambda e: None,
                            dom_event_handler=lambda *a, **k: None) is False


# ============================================================================
# Guided capture (Phase 2, Tasks 2.2 + 2.3): the capture forward carries the
# live session token + the classified requirements (+ loose Altium paths pulled
# from a captured zip), and the poll loop drives the CaptureSession to
# completion, stops on replace, and forwards an honest timeout signal (B1).
# ============================================================================


class _RecordingWindow:
    """A stand-in SPA window that records every evaluate_js it is handed, so a
    forward can be asserted without a real WebView2."""

    def __init__(self):
        self.scripts: list[str] = []

    def evaluate_js(self, script):
        self.scripts.append(script)


def _capture_payloads(win: _RecordingWindow) -> list[dict]:
    """Parse every CaptureForward object the recording window received."""
    head = "window.__STOCKROOM_CAD_DOWNLOAD__("
    out = []
    for js in win.scripts:
        assert js.startswith("window.__STOCKROOM_CAD_DOWNLOAD__ &&")  # guarded
        body = js.split(head, 1)[1]
        assert body.endswith(");")
        out.append(json.loads(body[:-2]))
    return out


class _FakeWatch:
    """A DownloadsWatch stand-in: yields the queued Paths on successive poll()s,
    then None forever."""

    def __init__(self, sequence):
        self._seq = list(sequence)

    def poll(self):
        return self._seq.pop(0) if self._seq else None


def _session(needs, *, now=0.0, token="tok"):
    from stockroom.capture.session import CaptureSession

    return CaptureSession.start("", frozenset(needs), now=now, token=token)


def _make_kicad_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("KiCad/part.kicad_sym", "x")
        zf.writestr("KiCad/part.kicad_mod", "x")
        zf.writestr("KiCad/part.step", "x")


def _make_mixed_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("KiCad/part.kicad_sym", "x")
        zf.writestr("KiCad/part.kicad_mod", "x")
        zf.writestr("Altium/part.SchLib", "SCHDATA")
        zf.writestr("Altium/part.PcbLib", "PCBDATA")


# -- build_capture_payload (pure) --


def test_build_capture_payload_includes_present_fields():
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host.window import build_capture_payload

    p = build_capture_payload(
        r"C:\dl\part.zip",
        "tok123",
        [R.KICAD_SYMBOL, R.ALTIUM_SYMBOL],
        [r"C:\tmp\a.SchLib", r"C:\tmp\a.PcbLib"],
    )
    assert p == {
        "path": r"C:\dl\part.zip",
        "token": "tok123",
        "requirements": ["kicad_symbol", "altium_symbol"],
        "altiumPaths": [r"C:\tmp\a.SchLib", r"C:\tmp\a.PcbLib"],
    }


def test_build_capture_payload_omits_empty_fields():
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host.window import build_capture_payload

    p = build_capture_payload(r"C:\dl\part.zip", None, [R.KICAD_SYMBOL], None)
    assert p == {"path": r"C:\dl\part.zip", "requirements": ["kicad_symbol"]}
    assert "token" not in p and "altiumPaths" not in p


# -- cad_forward_js (pure, now a dict payload) --


def test_cad_forward_js_encodes_the_payload_and_is_guarded():
    from stockroom.host.window import cad_forward_js

    payload = {"path": 'C:\\q"u\\part.zip', "token": "t", "requirements": ["kicad_symbol"]}
    js = cad_forward_js(payload)
    assert js.startswith("window.__STOCKROOM_CAD_DOWNLOAD__ &&")
    # JSON-encoded so a quote/backslash in a path cannot break out of the script
    assert json.dumps(payload) in js


# -- _extract_altium_members (pure) --


def test_extract_altium_members_pulls_loose_altium_files_only(tmp_path):
    from stockroom.host.window import _extract_altium_members

    z = tmp_path / "bundle.zip"
    _make_mixed_zip(z)
    out = tmp_path / "extracted"
    members = _extract_altium_members(z, out)
    assert sorted(Path(m).name for m in members) == ["part.PcbLib", "part.SchLib"]
    assert (out / "part.SchLib").read_bytes() == b"SCHDATA"  # vendor bytes verbatim
    assert all(Path(m).parent == out for m in members)


def test_extract_altium_members_on_a_kicad_only_zip_is_empty(tmp_path):
    from stockroom.host.window import _extract_altium_members

    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    assert _extract_altium_members(z, tmp_path / "o") == []


def test_extract_altium_members_on_a_bad_zip_is_empty(tmp_path):
    from stockroom.host.window import _extract_altium_members

    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert _extract_altium_members(bad, tmp_path / "o") == []


def test_extract_altium_members_flattens_paths_no_traversal(tmp_path):
    from stockroom.host.window import _extract_altium_members

    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../../evil.SchLib", "d")
        zf.writestr("a/b/c/deep.PcbLib", "d")
    out = tmp_path / "o"
    members = _extract_altium_members(z, out)
    assert sorted(Path(m).name for m in members) == ["deep.PcbLib", "evil.SchLib"]
    # flattened to basenames INSIDE out_dir: no path escapes the extraction dir
    assert all(Path(m).parent == out for m in members)


# -- _parse_needs (pure) --


def test_parse_needs_maps_known_values_and_drops_unknown():
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host.window import _parse_needs

    got = _parse_needs(["kicad_symbol", "altium_footprint", "bogus", None])
    assert got == frozenset({R.KICAD_SYMBOL, R.ALTIUM_FOOTPRINT})
    assert _parse_needs(None) == frozenset()


# -- _forward_cad_capture (classify + record + emit) --


def test_forward_cad_capture_kicad_zip_records_and_emits(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    s = _session({R.KICAD_SYMBOL, R.KICAD_FOOTPRINT, R.KICAD_MODEL})
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    [p] = _capture_payloads(win)
    assert p["path"] == str(z)
    assert p["token"] == "tok"
    assert set(p["requirements"]) == {"kicad_symbol", "kicad_footprint", "kicad_model"}
    assert "altiumPaths" not in p
    assert s.is_complete()


def test_forward_cad_capture_mixed_zip_extracts_altium(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    z = tmp_path / "m.zip"
    _make_mixed_zip(z)
    extract = tmp_path / "x"
    s = _session({R.KICAD_SYMBOL, R.ALTIUM_SYMBOL, R.ALTIUM_FOOTPRINT})
    W._forward_cad_capture(z, s, extract_dir=extract)
    [p] = _capture_payloads(win)
    assert p["path"] == str(z)
    assert set(p["requirements"]) == {"kicad_symbol", "altium_symbol", "altium_footprint"}
    assert sorted(Path(a).name for a in p["altiumPaths"]) == ["part.PcbLib", "part.SchLib"]
    assert all(Path(a).parent == extract for a in p["altiumPaths"])


def test_forward_cad_capture_dedups_and_ignores_non_needed(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    s = _session({R.KICAD_SYMBOL})  # needs only the symbol
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    [p] = _capture_payloads(win)
    assert set(p["requirements"]) == {"kicad_symbol"}  # footprint/model are not needed
    # a second identical capture satisfies nothing new -> no second emit
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    assert len(win.scripts) == 1


def test_forward_cad_capture_loose_altium_file_passes_its_own_path(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    schlib = tmp_path / "part.SchLib"
    schlib.write_bytes(b"x")
    s = _session({R.ALTIUM_SYMBOL})
    W._forward_cad_capture(schlib, s, extract_dir=tmp_path / "x")
    [p] = _capture_payloads(win)
    assert set(p["requirements"]) == {"altium_symbol"}
    # the backend attach reads a loose file directly; hand it as the altium path
    assert p["altiumPaths"] == [str(schlib)]


def test_forward_cad_capture_no_active_window_is_a_noop(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    monkeypatch.setattr(W, "_ACTIVE_WINDOW", None)
    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    s = _session({R.KICAD_SYMBOL})
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")  # must not raise
    # the requirement is still recorded so the session's completeness stays honest
    assert s.remaining() == frozenset()


# -- _poll_downloads_watch (session-driven) --


def test_poll_loop_forwards_a_capture_then_returns_on_completion(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    s = _session({R.KICAD_SYMBOL, R.KICAD_FOOTPRINT, R.KICAD_MODEL})
    watch = _FakeWatch([z])
    W._poll_downloads_watch(
        watch, s, extract_dir=tmp_path / "x",
        interval=0.0, timeout=300.0, sleep=lambda *_: None, now=lambda: 0.0,
    )
    payloads = _capture_payloads(win)
    assert len(payloads) == 1 and s.is_complete()
    assert all("signal" not in p for p in payloads)  # completed, no timeout signal


def test_poll_loop_forwards_a_timeout_signal_when_nothing_lands(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    s = _session({R.KICAD_SYMBOL}, token="tokT")
    times = iter([0.0, 0.0, 1000.0])  # deadline=300; 1st check in-window; 2nd check past it
    W._poll_downloads_watch(
        _FakeWatch([]), s, extract_dir=tmp_path / "x",
        interval=0.0, timeout=300.0, sleep=lambda *_: None, now=lambda: next(times),
    )
    [p] = _capture_payloads(win)
    assert p == {"signal": "timeout", "token": "tokT"}


def test_poll_loop_stops_silently_when_the_session_is_stopped(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    s = _session({R.KICAD_SYMBOL})
    s.stop()  # replaced by a newer capture before the loop even runs
    W._poll_downloads_watch(
        _FakeWatch([]), s, extract_dir=tmp_path / "x",
        interval=0.0, timeout=300.0, sleep=lambda *_: None, now=lambda: 0.0,
    )
    assert win.scripts == []  # no forward, and crucially no timeout signal onto a new part


# -- _stop_active_capture (B4 stop/replace + B8 temp cleanup) --


def test_stop_active_capture_stops_prior_session_joins_thread_and_cleans_temp(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    prior = _session({R.KICAD_SYMBOL})
    tmp = tmp_path / "prior-temp"
    tmp.mkdir()
    (tmp / "f.SchLib").write_bytes(b"x")
    prior.temp_dir = tmp

    finished = threading.Event()

    def _fake_poll():
        while not prior.stop_flag["stop"]:
            pass
        finished.set()

    th = threading.Thread(target=_fake_poll, daemon=True)
    th.start()
    monkeypatch.setattr(W, "_CAD_SESSION", prior)
    monkeypatch.setattr(W, "_CAD_POLL_THREAD", th)

    W._stop_active_capture()

    assert prior.stop_flag["stop"] is True
    assert finished.wait(2.0)  # the prior poll thread actually exited
    assert not tmp.exists()  # its temp dir was cleaned (B8)
    assert W._CAD_SESSION is None and W._CAD_POLL_THREAD is None


# -- persistent vendor WebView2 profile (B5): the storage kwargs for webview.start --


def test_webview_start_kwargs_persist_the_profile_when_supported(tmp_path):
    from stockroom.host.window import _webview_start_kwargs

    def start(func=None, private_mode=True, storage_path=None):
        ...

    prof = tmp_path / "webview-profile"
    assert _webview_start_kwargs(start, prof) == {
        "private_mode": False,
        "storage_path": str(prof),
    }


def test_webview_start_kwargs_empty_on_an_older_pywebview(tmp_path):
    from stockroom.host.window import _webview_start_kwargs

    def start(func=None):  # a pywebview without private_mode/storage_path
        ...

    assert _webview_start_kwargs(start, tmp_path / "p") == {}
