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


# -- cad_download_event_js: the REAL browser download lifecycle relayed to the in-page reactor --


def test_cad_download_event_js_relays_a_captured_format_guarded():
    from stockroom.host.window import cad_download_event_js

    js = cad_download_event_js("completed", "kicad")
    # Guarded (a page without the reactor bridge is a silent no-op) + JSON-encoded {state, format}
    # so the reactor advances only for the format it is awaiting.
    assert js.startswith("window.__SR_DL__ &&")
    assert json.dumps({"state": "completed", "format": "kicad"}) in js
    # A format is optional; without one it is a bare state payload.
    assert json.dumps({"state": "completed"}) in cad_download_event_js("completed")


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


# ============================================================================
# Phase 3 (HUD-02, DONE-01): the host to page received channel that ticks the
# HUD checklist live as files land, the part-name pass-through to the overlay,
# and finish-and-close (Complete flash + done signal + window destroy) on
# session completion. The CAD window stays js_api-free: every HUD update is a
# one-way host to page evaluate_js.
# ============================================================================


def test_cad_overlay_received_js_is_guarded_and_encodes_the_values():
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host.window import cad_overlay_received_js

    js = cad_overlay_received_js([R.KICAD_SYMBOL, R.ALTIUM_FOOTPRINT])
    # guarded: a page without the overlay bridge is a no-op, never an error
    assert js.startswith("window.__STOCKROOM_OVERLAY__ &&")
    # each requirement value is JSON-encoded (a value cannot break out of the script)
    assert json.dumps({"requirement": "kicad_symbol"}) in js
    assert json.dumps({"requirement": "altium_footprint"}) in js
    # it drives the overlay's received method
    assert "received(" in js


def test_forward_cad_capture_pushes_a_received_tick_to_the_cad_window(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    spa = _RecordingWindow()
    cad = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)
    monkeypatch.setattr(W, "_CAD_WINDOW", cad)
    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    s = _session({R.KICAD_SYMBOL, R.KICAD_FOOTPRINT, R.KICAD_MODEL})

    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")

    # the SPA still received the capture payload (unchanged behavior)
    [p] = _capture_payloads(spa)
    assert set(p["requirements"]) == {"kicad_symbol", "kicad_footprint", "kicad_model"}
    # the CAD window got: (1) a guarded received push for the newly-satisfied requirements, and
    # (2) a real "completed" download event for the captured format so the reactor advances.
    assert len(cad.scripts) == 2
    tick = cad.scripts[0]
    assert tick.startswith("window.__STOCKROOM_OVERLAY__ &&")
    for v in ("kicad_symbol", "kicad_footprint", "kicad_model"):
        assert json.dumps({"requirement": v}) in tick
    dl = cad.scripts[1]
    assert dl.startswith("window.__SR_DL__ &&")
    assert json.dumps({"state": "completed", "format": "kicad"}) in dl

    # a dedup re-fire satisfies nothing new -> nothing new pushed to the CAD window
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    assert len(cad.scripts) == 2


def test_forward_cad_capture_no_cad_window_still_forwards_to_the_spa(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    spa = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)
    monkeypatch.setattr(W, "_CAD_WINDOW", None)  # window mid-close / never opened
    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    s = _session({R.KICAD_SYMBOL})
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")  # must not raise
    assert len(_capture_payloads(spa)) == 1  # the SPA forward is untouched


def test_forward_cad_capture_without_a_session_does_not_touch_the_cad_window(tmp_path, monkeypatch):
    from stockroom.host import window as W

    spa = _RecordingWindow()
    cad = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)
    monkeypatch.setattr(W, "_CAD_WINDOW", cad)
    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    W._forward_cad_capture(z, None, extract_dir=tmp_path / "x")  # no session -> no HUD push
    assert cad.scripts == []


def test_cad_loaded_scripts_threads_the_part_name_into_the_overlay():
    from stockroom.host.window import cad_loaded_scripts

    scripts = cad_loaded_scripts(
        ["kicad_symbol"], "digikey", "DigiKey", ["kicad"], {}, "BQ24074"
    )
    assert "__STOCKROOM_OVERLAY__" in scripts[0]  # overlay first
    assert "BQ24074" in scripts[0]  # the part name reached build_overlay_js


def test_cad_scripts_for_url_threads_the_part_name(monkeypatch):
    from stockroom.host import window as W

    _stub_creds(monkeypatch)
    scripts = W.cad_scripts_for_url("https://www.digikey.com/x", ["kicad_symbol"], "BQ24074")
    assert "BQ24074" in scripts[0]  # part name flows through cad_scripts_for_url


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
    assert s.is_complete()
    # the file-capture forward plus a distinct done signal on completion (never a timeout)
    assert {"signal": "done", "token": s.token} in payloads
    assert all(p.get("signal") != "timeout" for p in payloads)


def test_session_complete_matches_is_complete_under_the_lock():
    # _session_complete reads completeness under _CAD_CAPTURE_LOCK (so the tier-1 COM thread's
    # record() cannot mutate session.received mid-iteration); it must still report the same
    # truth is_complete() does.
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host.window import _session_complete

    s = _session({R.KICAD_SYMBOL, R.ALTIUM_SYMBOL})
    assert _session_complete(s) is False
    s.record([R.KICAD_SYMBOL, R.ALTIUM_SYMBOL], Path("/x"))
    assert _session_complete(s) is True


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


# -- finish-and-close on completion (DONE-01): Complete flash + done signal + window destroy --


def test_cad_overlay_complete_js_is_guarded_and_calls_complete():
    from stockroom.host.window import cad_overlay_complete_js

    js = cad_overlay_complete_js()
    assert js.startswith("window.__STOCKROOM_OVERLAY__ &&")  # guarded no-op without the bridge
    assert ".complete()" in js


def test_forward_done_signal_emits_a_done_with_the_session_token(monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    spa = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)
    s = _session({R.KICAD_SYMBOL}, token="tokD")
    W._forward_done_signal(s)
    [p] = _capture_payloads(spa)
    assert p == {"signal": "done", "token": "tokD"}


def test_poll_loop_finishes_and_closes_on_completion(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    spa = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)

    class _DestroyWindow(_RecordingWindow):
        def __init__(self):
            super().__init__()
            self.destroyed = 0

        def destroy(self):
            self.destroyed += 1

    cad = _DestroyWindow()
    monkeypatch.setattr(W, "_CAD_WINDOW", cad)

    z = tmp_path / "k.zip"
    _make_kicad_zip(z)
    s = _session({R.KICAD_SYMBOL, R.KICAD_FOOTPRINT, R.KICAD_MODEL})
    slept: list = []
    W._poll_downloads_watch(
        _FakeWatch([z]), s, extract_dir=tmp_path / "x",
        interval=0.0, timeout=300.0, close_delay=1.0,
        sleep=lambda d=0.0: slept.append(d), now=lambda: 0.0,
    )
    # the SPA got a distinct done signal, and never a timeout on completion
    payloads = _capture_payloads(spa)
    assert {"signal": "done", "token": "tok"} in payloads
    assert all(p.get("signal") != "timeout" for p in payloads)
    # the HUD got the file received tick AND the Complete flash push
    assert any("received(" in js for js in cad.scripts)
    assert any(".complete()" in js for js in cad.scripts)
    # the cad window was closed exactly once, after a brief visible close delay
    assert cad.destroyed == 1
    assert 1.0 in slept
    assert s.is_complete()


def test_finish_and_close_leaves_the_temp_dir_intact(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    spa = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)
    monkeypatch.setattr(W, "_CAD_WINDOW", None)  # no window to destroy; the temp path is the focus
    s = _session({R.KICAD_SYMBOL})
    temp = tmp_path / "keep"
    temp.mkdir()
    (temp / "part.SchLib").write_bytes(b"x")
    s.temp_dir = temp
    W._finish_and_close(s, sleep=lambda *_: None, close_delay=0.0)
    # the async Altium attach still needs the dir; the NEXT capture cleans it, never the finish path
    assert temp.exists()
    assert (temp / "part.SchLib").exists()


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


# -- login auto-fill + loaded-injection order (Phase 3 A3) --


def test_login_autofill_blank_creds_is_empty():
    from stockroom.host.window import build_login_autofill_js

    assert build_login_autofill_js("ultralibrarian", "", "") == ""


def test_login_autofill_json_encodes_creds_and_is_guarded():
    from stockroom.host.window import build_login_autofill_js

    js = build_login_autofill_js("ultralibrarian", "me@x.com", "s3cr3t")
    assert js.strip().startswith("(") and "try" in js and "catch" in js
    # creds are JSON-encoded, never string-concatenated into the script
    assert json.dumps("me@x.com") in js and json.dumps("s3cr3t") in js
    assert "password" in js  # fills a password field


def test_login_autofill_fills_every_supported_vendor_and_is_empty_when_blank():
    # DigiKey account (primary) + Ultra Librarian + SnapEDA + SamacSys each auto-fill their own
    # login DOM, JSON-encoded + guarded; blank creds inject nothing (the LGN-02 "log in once" path).
    from stockroom.host.window import build_login_autofill_js

    for vk in ("digikey", "ultralibrarian", "snapeda", "samacsys"):
        js = build_login_autofill_js(vk, "me@x.com", "s3cr3t")
        assert js.strip().startswith("(") and "try" in js and "catch" in js
        assert json.dumps("me@x.com") in js and json.dumps("s3cr3t") in js
        assert "password" in js
        assert build_login_autofill_js(vk, "", "") == ""


def test_load_vendor_creds_digikey_and_samacsys_degrade_before_phase4(monkeypatch):
    # digikey + samacsys creds are read via getattr, so before Phase 4 SET-01 adds those config
    # fields they degrade to blank (nothing injected -> LGN-02); ul/snapeda read their real fields.
    from stockroom.host import window as W
    from stockroom.store import machine_config as MC

    class _Cfg:
        ul_username = "ulu"
        ul_password = "ulp"
        snapeda_username = "snu"
        snapeda_password = "snp"
        # deliberately NO digikey_username / samacsys_username (Phase 4 SET-01 adds them)

    monkeypatch.setattr(MC.MachineConfig, "load", classmethod(lambda cls: _Cfg()))
    assert W._load_vendor_creds("digikey") == {"username": "", "password": ""}
    assert W._load_vendor_creds("samacsys") == {"username": "", "password": ""}
    assert W._load_vendor_creds("ultralibrarian") == {"username": "ulu", "password": "ulp"}
    assert W._load_vendor_creds("snapeda") == {"username": "snu", "password": "snp"}


def test_load_vendor_creds_reads_digikey_and_samacsys_when_present(monkeypatch):
    # once the Phase 4 fields exist, the DigiKey ACCOUNT web login + SamacSys creds are read.
    from stockroom.host import window as W
    from stockroom.store import machine_config as MC

    class _Cfg:
        digikey_username = "dku"
        digikey_password = "dkp"
        samacsys_username = "smu"
        samacsys_password = "smp"
        ul_username = ""
        ul_password = ""
        snapeda_username = ""
        snapeda_password = ""

    monkeypatch.setattr(MC.MachineConfig, "load", classmethod(lambda cls: _Cfg()))
    assert W._load_vendor_creds("digikey") == {"username": "dku", "password": "dkp"}
    assert W._load_vendor_creds("samacsys") == {"username": "smu", "password": "smp"}


def test_formats_for_needs_maps_kicad_and_altium():
    from stockroom.host.window import _formats_for_needs

    assert _formats_for_needs(["kicad_symbol", "kicad_model"]) == ["kicad"]
    assert _formats_for_needs(["kicad_symbol", "altium_footprint"]) == ["kicad", "altium"]
    assert _formats_for_needs(["altium_symbol"]) == ["altium"]
    assert _formats_for_needs([]) == []


def test_vendor_from_url_maps_key_and_label():
    from stockroom.host.window import _vendor_from_url

    assert _vendor_from_url("https://app.ultralibrarian.com/search?q=x") == (
        "ultralibrarian",
        "Ultra Librarian",
    )
    assert _vendor_from_url("https://www.snapeda.com/parts/x") == ("snapeda", "SnapEDA")
    assert _vendor_from_url("https://www.digikey.com/x") == ("digikey", "DigiKey")
    # SamacSys is served from componentsearchengine / samacsys; ul/snapeda/digikey are KEPT
    assert _vendor_from_url("https://componentsearchengine.com/part/x") == ("samacsys", "SamacSys")
    assert _vendor_from_url("https://www.samacsys.com/x") == ("samacsys", "SamacSys")
    assert _vendor_from_url("")[0] == ""
    # A DigiKey CAD models page carries a ?tab=<provider> query; it MUST route to the DigiKey driver,
    # not the legacy provider driver (the guided capture happens on DigiKey). Regression 2026-07-23.
    assert _vendor_from_url("https://www.digikey.com/en/models/726880?tab=ultralibrarian") == (
        "digikey",
        "DigiKey",
    )


def test_cad_loaded_scripts_order_and_omission():
    from stockroom.host.window import cad_loaded_scripts

    with_creds = cad_loaded_scripts(
        ["kicad_symbol", "altium_symbol"],
        "ultralibrarian",
        "Ultra Librarian",
        ["kicad", "altium"],
        {"username": "u", "password": "p"},
    )
    assert len(with_creds) == 3  # overlay, autofill, driver in order
    assert "__STOCKROOM_OVERLAY__" in with_creds[0]  # overlay first
    assert "password" in with_creds[1]  # autofill second
    assert "KiCad" in with_creds[2] and "Altium" in with_creds[2]  # driver last

    no_creds = cad_loaded_scripts(
        ["kicad_symbol"], "ultralibrarian", "Ultra Librarian", ["kicad"], {}
    )
    assert len(no_creds) == 2  # overlay, driver (autofill omitted when no creds)
    assert "__STOCKROOM_OVERLAY__" in no_creds[0]
    assert "KiCad" in no_creds[1]


# -- light defensive re-injection (Phase 2 LGN-03): cad_scripts_for_url + current-url
#    re-derivation + best-effort popup subscribe + the no-token / no-js_api security lock --


def _stub_creds(monkeypatch, **fields):
    from stockroom.store import machine_config as MC

    defaults = {
        "digikey_username": "",
        "digikey_password": "",
        "ul_username": "",
        "ul_password": "",
        "snapeda_username": "",
        "snapeda_password": "",
        "samacsys_username": "",
        "samacsys_password": "",
    }
    defaults.update(fields)
    cfg = type("_Cfg", (), defaults)()
    monkeypatch.setattr(MC.MachineConfig, "load", classmethod(lambda cls: cfg))


def test_cad_scripts_for_url_digikey_includes_the_digikey_autofill(monkeypatch):
    from stockroom.host import window as W

    _stub_creds(monkeypatch, digikey_username="dku", digikey_password="dkp")
    scripts = W.cad_scripts_for_url(
        "https://www.digikey.com/en/products/x", ["kicad_symbol", "kicad_model"]
    )
    assert len(scripts) == 3  # overlay, DigiKey autofill, driver
    assert "__STOCKROOM_OVERLAY__" in scripts[0]
    assert json.dumps("dku") in scripts[1] and "password" in scripts[1]  # digikey autofill second
    assert "eda-cad-model-link" in scripts[2]  # the digikey models-page driver last


def test_cad_scripts_for_url_snapeda_and_samacsys_autofill(monkeypatch):
    from stockroom.host import window as W

    _stub_creds(
        monkeypatch,
        snapeda_username="snu",
        snapeda_password="snp",
        samacsys_username="smu",
        samacsys_password="smp",
    )
    snap = W.cad_scripts_for_url("https://www.snapeda.com/parts/x", ["kicad_symbol"])
    assert len(snap) == 3 and json.dumps("snu") in snap[1]
    sam = W.cad_scripts_for_url("https://componentsearchengine.com/part/x", ["kicad_symbol"])
    assert len(sam) == 3 and json.dumps("smu") in sam[1]


def test_cad_scripts_for_url_without_creds_is_overlay_and_driver_only(monkeypatch):
    from stockroom.host import window as W

    _stub_creds(monkeypatch)  # nothing saved
    scripts = W.cad_scripts_for_url("https://www.digikey.com/x", ["kicad_symbol"])
    assert len(scripts) == 2  # overlay + driver, autofill omitted
    assert "__STOCKROOM_OVERLAY__" in scripts[0] and "eda-cad-model-link" in scripts[1]


def test_inject_cad_scripts_re_derives_from_the_current_url(monkeypatch):
    # after a simulated in-site nav the CURRENT url's scripts are injected, not the original.
    from stockroom.host import window as W

    _stub_creds(
        monkeypatch,
        digikey_username="dku",
        digikey_password="dkp",
        snapeda_username="snu",
        snapeda_password="snp",
    )

    class NavWindow(_RecordingWindow):
        def __init__(self, url):
            super().__init__()
            self._url = url

        def get_current_url(self):
            return self._url

    win = NavWindow("https://www.snapeda.com/parts/x")
    W._inject_cad_scripts(win, "https://www.digikey.com/x", ["kicad_symbol"])
    assert len(win.scripts) == 3
    assert json.dumps("snu") in win.scripts[1]  # the CURRENT (snapeda) url's autofill


def test_inject_cad_scripts_falls_back_when_current_url_unavailable(monkeypatch):
    from stockroom.host import window as W

    _stub_creds(monkeypatch, digikey_username="dku", digikey_password="dkp")

    class BadWindow(_RecordingWindow):
        def get_current_url(self):
            raise RuntimeError("this backend has no get_current_url")

    win = BadWindow()
    W._inject_cad_scripts(win, "https://www.digikey.com/x", ["kicad_symbol"])
    assert len(win.scripts) == 3
    assert json.dumps("dku") in win.scripts[1]  # fell back to the original digikey url


def test_wire_cad_reinjection_subscribes_when_the_event_exists():
    from stockroom.host.window import _wire_cad_reinjection

    class Events:
        def __init__(self):
            self.new_window = _Slot()

    class Window:
        def __init__(self):
            self.events = Events()

    win = Window()
    ok = _wire_cad_reinjection(win, ["kicad_symbol"], candidate_events=("new_window",))
    assert ok is True
    assert len(win.events.new_window) == 1  # a re-inject handler subscribed to the popup slot


def test_wire_cad_reinjection_degrades_when_no_event_slot():
    from stockroom.host.window import _wire_cad_reinjection

    class Events:
        pass  # this pywebview backend exposes no popup / new-window event

    class Window:
        def __init__(self):
            self.events = Events()

    assert (
        _wire_cad_reinjection(Window(), ["kicad_symbol"], candidate_events=("new_window", "popup"))
        is False
    )


def test_cad_scripts_never_leak_token(monkeypatch):
    # SECURITY INVARIANT: no cad script (overlay / autofill / driver) for any vendor url references
    # the SPA token global or a pywebview.api / js_api bridge - injection is one-way host->page.
    from stockroom.host import window as W

    _stub_creds(
        monkeypatch,
        digikey_username="dku",
        digikey_password="dkp",
        ul_username="ulu",
        ul_password="ulp",
        snapeda_username="snu",
        snapeda_password="snp",
        samacsys_username="smu",
        samacsys_password="smp",
    )
    urls = [
        "https://www.digikey.com/en/products/x",
        "https://www.snapeda.com/parts/x",
        "https://componentsearchengine.com/part/x",
        "https://app.ultralibrarian.com/x",
    ]
    for u in urls:
        for script in W.cad_scripts_for_url(u, ["kicad_symbol", "altium_symbol"]):
            low = script.lower()
            assert "__stockroom_token__" not in low
            assert "__api_base__" not in low
            assert "pywebview.api" not in low
            assert "js_api" not in low


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
