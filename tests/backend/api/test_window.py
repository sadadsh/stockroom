import json

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
