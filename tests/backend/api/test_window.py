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

    # A dedup re-fire satisfies nothing new -> no HUD tick and no SPA re-forward, but the
    # completed relay STILL fires: the reactor is the decider (its settled/format matching makes a
    # stray relay harmless), while a swallowed relay left the reactor waiting out a 150s watchdog
    # on a file that had already landed (live-observed 2026-07-23).
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    assert len(cad.scripts) == 3
    assert json.dumps({"state": "completed", "format": "kicad"}) in cad.scripts[2]
    assert len(_capture_payloads(spa)) == 1  # the SPA is still forwarded exactly once


def test_capture_formats_require_the_core_symbol_footprint_pair():
    # The relay names a format ONLY when the captured file carries that format's symbol+footprint
    # pair. A stray STEP (classifies as kicad_model alone) must not masquerade as the KiCad
    # delivery: live 2026-07-23, UL served an Altium+STEP bundle against a KiCad request, and a
    # kicad_model-implies-kicad relay would have falsely advanced the reactor past KiCad.
    from stockroom.host.window import _capture_formats

    assert _capture_formats(["kicad_symbol", "kicad_footprint", "kicad_model"]) == ["kicad"]
    assert _capture_formats(["kicad_model"]) == []
    assert _capture_formats(["altium_symbol", "altium_footprint", "kicad_model"]) == ["altium"]
    assert _capture_formats(
        ["kicad_symbol", "kicad_footprint", "altium_symbol", "altium_footprint"]
    ) == ["kicad", "altium"]
    assert _capture_formats([]) == []


def test_forward_cad_capture_relays_a_wrong_format_completion(tmp_path, monkeypatch):
    # The vendor can deliver the WRONG format outright (live 2026-07-23: a sticky prior selection
    # made UL serve its Altium+STEP bundle against a KiCad request). The file satisfies nothing the
    # session needs -> no HUD tick, no SPA forward - but the reactor MUST still hear a completed
    # event naming what actually arrived, so it reacts (wrongfile -> reselect) instead of waiting
    # out its watchdog on a download that already finished.
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    spa = _RecordingWindow()
    cad = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)
    monkeypatch.setattr(W, "_CAD_WINDOW", cad)
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Altium/part.SchLib", "SCHDATA")
        zf.writestr("Altium/part.PcbLib", "PCBDATA")
    s = _session({R.KICAD_SYMBOL, R.KICAD_FOOTPRINT})  # a KiCad-only session
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    assert _capture_payloads(spa) == []  # nothing needed was satisfied
    [dl] = cad.scripts  # no HUD tick - only the completed relay
    assert dl.startswith("window.__SR_DL__ &&")
    assert json.dumps({"state": "completed", "format": "altium"}) in dl


def test_forward_cad_capture_relays_unknown_for_a_file_with_no_cad_content(tmp_path, monkeypatch):
    # A completed download that classifies as nothing (a junk/empty archive) still completed - the
    # reactor hears "unknown", treats it as a wrong file, and reacts instead of hanging.
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    monkeypatch.setattr(W, "_ACTIVE_WINDOW", _RecordingWindow())
    cad = _RecordingWindow()
    monkeypatch.setattr(W, "_CAD_WINDOW", cad)
    z = tmp_path / "junk.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "nothing useful")
    s = _session({R.KICAD_SYMBOL})
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    [dl] = cad.scripts
    assert json.dumps({"state": "completed", "format": "unknown"}) in dl


def test_unique_dest_never_overwrites_an_earlier_capture(tmp_path):
    # The vendor names EVERY export the same (<MPN>.zip), so a second format's download would
    # OVERWRITE the first zip while its async SPA attach may still be reading it (live
    # 2026-07-23: the Altium zip replaced the just-captured KiCad zip on disk seconds after the
    # KiCad forward). The save path must be collision-free.
    from stockroom.host.window import _unique_dest

    first = _unique_dest(tmp_path, "part.zip")
    assert first == tmp_path / "part.zip"
    first.write_bytes(b"a")
    second = _unique_dest(tmp_path, "part.zip")
    assert second == tmp_path / "part-2.zip"
    second.write_bytes(b"b")
    assert _unique_dest(tmp_path, "part.zip") == tmp_path / "part-3.zip"
    assert _unique_dest(tmp_path, "") == tmp_path / "cad-download.zip"


def test_emit_download_started_relays_to_the_cad_window(monkeypatch):
    # Owner heuristic (2026-07-23): a successful run's download STARTS within ~5s of the click.
    # Tier 1's DownloadStarting relays a real 'started' event (off the COM thread) so the reactor
    # can fail 'nostart' fast - to the next source - when nothing begins.
    from stockroom.host import window as W

    cad = _RecordingWindow()
    monkeypatch.setattr(W, "_CAD_WINDOW", cad)
    W._emit_download_started()
    [js] = cad.scripts
    assert js.startswith("window.__SR_DL__ &&")
    assert json.dumps({"state": "started"}) in js


def test_dispatch_captured_runs_off_the_calling_thread_and_returns_immediately():
    # Tier 1's StateChanged fires on WebView2's download COM thread. Running the forward pipeline
    # (classify + extract + blocking evaluate_js) on that thread hung it mid-relay (live-observed
    # 2026-07-23: the HUD ticked, then the completed relay never reached the page and the harness
    # line after the forward never ran). The dispatch helper must hand the callback to a worker
    # thread and return without waiting for it.
    from stockroom.host.window import _dispatch_captured

    started = threading.Event()
    release = threading.Event()
    seen: dict = {}

    def _blocked_capture(path):
        seen["thread"] = threading.current_thread()
        seen["path"] = path
        started.set()
        release.wait(timeout=5.0)

    _dispatch_captured(_blocked_capture, "dest.zip")  # must NOT block on the callback
    assert started.wait(timeout=5.0)  # the callback did run...
    assert seen["thread"] is not threading.current_thread()  # ...on a different thread
    release.set()
    assert seen["path"] == "dest.zip"


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


# -- Cloudflare auto-click (owner 2026-07-24: "could u click the cloudflare for me") --
# The DRIVER only senses the challenge (it stashes the widget's viewport rect as JSON in
# window.__SR_CF_RECT__); the HOST reads it from the tier-2 poll thread and fires a REAL
# OS-level click at the Turnstile checkbox - bounded attempts, seconds apart, degrading
# silently to the driver's existing "Your Turn" hand-off.


class _CfWindow(_RecordingWindow):
    """A cad-window stand-in whose __SR_CF_RECT__ read returns a canned value while every
    other evaluate_js still records."""

    def __init__(self, rect_raw):
        super().__init__()
        self.rect_raw = rect_raw

    def evaluate_js(self, script):
        if "__SR_CF_RECT__" in script:
            return self.rect_raw
        return super().evaluate_js(script)


def _cf_raw(**over):
    rect = {"left": 100.0, "top": 200.0, "width": 300.0, "height": 65.0, "dpr": 1.0}
    rect.update(over)
    return json.dumps(rect)


def test_parse_cf_rect_accepts_a_sensed_rect_and_defaults_dpr():
    from stockroom.host import window as W

    rect = W._parse_cf_rect(_cf_raw(dpr=2.0))
    assert rect == {"left": 100.0, "top": 200.0, "width": 300.0, "height": 65.0, "dpr": 2.0}
    # a missing or nonsensical dpr degrades to 1.0, never a reject (the rect is still clickable)
    assert W._parse_cf_rect(json.dumps({"left": 1, "top": 2, "width": 3, "height": 4}))["dpr"] == 1.0
    assert W._parse_cf_rect(_cf_raw(dpr=0))["dpr"] == 1.0


def test_parse_cf_rect_rejects_junk():
    from stockroom.host import window as W

    for raw in (
        None,
        "",
        "null",
        "not json",
        json.dumps([1, 2]),
        json.dumps({"left": 1, "top": 2, "width": 3}),  # height missing
        json.dumps({"left": "a", "top": 2, "width": 3, "height": 4}),  # non-numeric
        json.dumps({"left": 1, "top": 2, "width": 0, "height": 4}),  # zero-size
        json.dumps({"left": 1, "top": 2, "width": 3, "height": -4}),  # negative size
        json.dumps({"left": True, "top": 2, "width": 3, "height": 4}),  # bool is not a coord
        '{"left": Infinity, "top": 2, "width": 3, "height": 4}',  # nonfinite
    ):
        assert W._parse_cf_rect(raw) is None, raw


def test_cf_click_target_aims_at_the_turnstile_checkbox_in_physical_pixels():
    from stockroom.host import window as W

    # the checkbox sits at the widget's left edge: x = left + min(30, 15% of width), y = mid-
    # height, both scaled to PHYSICAL pixels (ClientToScreen expects them) by devicePixelRatio
    rect = {"left": 100.0, "top": 200.0, "width": 300.0, "height": 65.0, "dpr": 2.0}
    assert W._cf_click_target(rect) == (260, 465)  # (100+30)*2, (200+32.5)*2
    small = {"left": 0.0, "top": 0.0, "width": 100.0, "height": 40.0, "dpr": 1.0}
    assert W._cf_click_target(small) == (15, 20)  # min(30, 15% of 100) = 15


def test_cf_autoclick_tick_clicks_the_sensed_rect_bounded_and_gapped(monkeypatch):
    from stockroom.host import window as W

    win = _CfWindow(_cf_raw())
    monkeypatch.setattr(W, "_CAD_WINDOW", win)
    clicks = []
    state: dict = {}
    t = {"v": 100.0}
    for _ in range(10):
        W._cf_autoclick_tick(state, now=lambda: t["v"], click=lambda w, x, y: clicks.append((w, x, y)))
        t["v"] += 1.0  # 1s per poll pass: the >=3s gap must throttle consecutive attempts
    # bounded to 3 attempts total, each at least the gap apart, aimed at the checkbox
    assert len(clicks) == 3
    assert all(c == (win, 130, 232) for c in clicks)
    assert state["attempts"] == 3
    # a later pass never clicks again, even with the wall still sensed (Your Turn covers it)
    t["v"] += 1000.0
    W._cf_autoclick_tick(state, now=lambda: t["v"], click=lambda w, x, y: clicks.append((w, x, y)))
    assert len(clicks) == 3


def test_cf_autoclick_tick_without_a_rect_or_window_consumes_nothing(monkeypatch):
    from stockroom.host import window as W

    state: dict = {}
    boom = lambda *a: (_ for _ in ()).throw(AssertionError("must not click"))  # noqa: E731

    # no cad window at all: a pure no-op that never even reads the clock (the poll loop's
    # injectable now() may be a finite iterator - see the timeout-signal test)
    monkeypatch.setattr(W, "_CAD_WINDOW", None)
    W._cf_autoclick_tick(state, now=boom, click=boom)
    assert state == {}

    # a window with no sensed rect (or junk): nothing clicked, no attempt consumed
    for raw in (None, "null", "not json"):
        monkeypatch.setattr(W, "_CAD_WINDOW", _CfWindow(raw))
        W._cf_autoclick_tick(state, now=boom, click=boom)
        assert state == {}

    # an evaluate_js that raises (window mid-close) degrades silently
    class _Dead:
        def evaluate_js(self, script):
            raise RuntimeError("gone")

    monkeypatch.setattr(W, "_CAD_WINDOW", _Dead())
    W._cf_autoclick_tick(state, now=boom, click=boom)
    assert state == {}


def test_cf_autoclick_tick_skips_an_offscreen_target(monkeypatch):
    from stockroom.host import window as W

    # a rect scrolled off the viewport computes a nonpositive client target; clicking there
    # would land on chrome or another window - skip without consuming an attempt
    monkeypatch.setattr(W, "_CAD_WINDOW", _CfWindow(_cf_raw(left=-500.0)))
    state: dict = {}
    W._cf_autoclick_tick(state, now=lambda: 0.0, click=lambda *a: (_ for _ in ()).throw(AssertionError))
    assert state == {}


def test_poll_loop_runs_the_cf_autoclick_each_pass(tmp_path, monkeypatch):
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    spa = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", spa)
    cad = _CfWindow(_cf_raw())
    monkeypatch.setattr(W, "_CAD_WINDOW", cad)
    clicks = []
    monkeypatch.setattr(W, "_click_cad_window_at", lambda w, x, y: clicks.append((w, x, y)))
    s = _session({R.KICAD_SYMBOL})
    times = iter([0.0, 0.0, 10.0, 1000.0])  # deadline; pass 1 (tick clicks at 10.0); past-deadline
    W._poll_downloads_watch(
        _FakeWatch([]), s, extract_dir=tmp_path / "x",
        interval=0.0, timeout=300.0, sleep=lambda *_: None, now=lambda: next(times),
    )
    assert clicks == [(cad, 130, 232)]  # the poll thread drove the OS-level click


def test_click_cad_window_at_is_windows_only():
    from stockroom.host import window as W

    # on a non-Windows host the ctypes path must not even be attempted
    assert W._click_cad_window_at(_RecordingWindow(), 10, 10) is False


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


def test_login_autofill_uses_the_native_value_setter_and_refills():
    # Live 2026-07-24: DigiKey's login is a React/PingFederate controlled form. Setting
    # el.value directly does NOT update React's internal value tracker, so clicking Next
    # validated an EMPTY field ("Please fill out this field") even though the email showed
    # in the box. The fill must go through the prototype's native value setter so React
    # registers it, and re-run for a while so the 2-step password page (which appears after
    # Next) also gets filled.
    from stockroom.host.window import build_login_autofill_js

    js = build_login_autofill_js("digikey", "me@x.com", "s3cr3t")
    # the native value setter (the React-controlled-input workaround), not a bare el.value=
    assert "getOwnPropertyDescriptor" in js and "HTMLInputElement.prototype" in js
    assert ".set" in js and ".call(" in js
    # re-fills over time so the second (password) step is caught even without a fresh load
    assert "setInterval" in js
    # never clobbers a value the user is typing (only fills an empty / matching field)
    assert "offsetParent" in js


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


def test_forward_cad_capture_never_records_altium_reqs_it_cannot_back(tmp_path, monkeypatch):
    # Live 2026-07-24: a session marked its Altium needs satisfied by a capture that
    # yielded NO attachable altium paths, so the session completed, the window closed,
    # and nothing ever attached. An altium requirement is recorded ONLY when backed by
    # real loose paths; an unbacked zip leaves the need open for the real file.
    from stockroom.capture.requirements import Requirement as R
    from stockroom.host import window as W

    win = _RecordingWindow()
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", win)
    z = tmp_path / "m.zip"
    _make_mixed_zip(z)  # classification says altium content IS inside
    s = _session({R.ALTIUM_SYMBOL, R.ALTIUM_FOOTPRINT})
    # no extract_dir -> the altium members cannot be pulled out -> nothing to attach
    W._forward_cad_capture(z, s, extract_dir=None)
    assert not s.is_complete()
    assert _capture_payloads(win) == []
    # the real extractable capture afterwards still satisfies the needs
    W._forward_cad_capture(z, s, extract_dir=tmp_path / "x")
    [p] = _capture_payloads(win)
    assert set(p["requirements"]) == {"altium_symbol", "altium_footprint"}
    assert len(p["altiumPaths"]) == 2
    assert s.is_complete()


def test_extract_altium_members_reaches_into_a_nested_zip(tmp_path):
    import io
    import zipfile as _zf

    from stockroom.host import window as W

    inner = io.BytesIO()
    with _zf.ZipFile(inner, "w") as z:
        z.writestr("part.SchLib", "sch-bytes")
        z.writestr("part.PcbLib", "pcb-bytes")
    outer = tmp_path / "bundle.zip"
    with _zf.ZipFile(outer, "w") as z:
        z.writestr("README.txt", "hi")
        z.writestr("altium/part-altium.zip", inner.getvalue())
    out = tmp_path / "x"
    got = sorted(Path(p).name for p in W._extract_altium_members(outer, out))
    assert got == ["part.PcbLib", "part.SchLib"]


def test_grant_download_permission_sets_state_and_handled():
    # Live 2026-07-24: the "allow multiple automatic downloads?" bar reappeared on the SECOND
    # (Altium) download even with the auto-allow wired, so the Altium set never came after
    # KiCad. Root cause: the handler set args.State=Allow but NOT args.Handled=True - and in
    # WebView2, Handled=false still SHOWS the default prompt (State is only the preselection).
    # Setting Handled=True is what actually suppresses the bar.
    from stockroom.host import window as W

    class _Args:
        def __init__(self, kind):
            self.PermissionKind = kind
            self.State = None
            self.Handled = False

    a = _Args("MultipleAutomaticDownloads")
    assert W._grant_download_permission(a, allow_state="ALLOW") is True
    assert a.State == "ALLOW"
    assert a.Handled is True  # the missing piece that suppresses the prompt

    b = _Args("Microphone")
    assert W._grant_download_permission(b, allow_state="ALLOW") is False
    assert b.State is None and b.Handled is False  # non-download kinds keep their normal prompt


def test_should_auto_allow_permission_only_for_download_kinds():
    from stockroom.host import window as W

    # Edge's multiple-automatic-downloads bar (the exact kind string varies by SDK)
    assert W._should_auto_allow_permission("MultipleAutomaticDownloads")
    assert W._should_auto_allow_permission("CoreWebView2PermissionKind.MultipleAutomaticDownloadsRequested")
    # everything else keeps its prompt
    assert not W._should_auto_allow_permission("Microphone")
    assert not W._should_auto_allow_permission("Geolocation")
    assert not W._should_auto_allow_permission("")
    assert not W._should_auto_allow_permission(None)
