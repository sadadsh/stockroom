import json

from stockroom.host.window import (
    _HostApi,
    _webview_start_kwargs,
    active_window,
    inject_script,
    should_inject,
)


def test_active_window_is_none_before_a_window_runs():
    assert active_window() is None


def test_inject_script_hands_the_spa_the_base_and_token():
    js = inject_script("http://127.0.0.1:5123", "tok-abc123")
    assert f"window.__API_BASE__ = {json.dumps('http://127.0.0.1:5123')}" in js
    assert f"window.__STOCKROOM_TOKEN__ = {json.dumps('tok-abc123')}" in js
    assert "serviceWorker" in js and "unregister" in js


def test_inject_script_escapes_special_characters():
    js = inject_script("http://127.0.0.1:5123", 'tok"quote\\back')
    token = js.split("window.__STOCKROOM_TOKEN__ = ", 1)[1].split(";", 1)[0]
    base = js.split("window.__API_BASE__ = ", 1)[1].split(";", 1)[0]
    assert json.loads(token) == 'tok"quote\\back'
    assert json.loads(base) == "http://127.0.0.1:5123"


def test_should_inject_only_on_the_loopback_spa_origin():
    base = "http://127.0.0.1:5123"
    assert should_inject("http://127.0.0.1:5123/", base) is True
    assert should_inject("http://127.0.0.1:5123/index.html", base) is True
    assert should_inject("https://www.digikey.com/en/products/x", base) is False
    assert should_inject("https://challenges.cloudflare.com/turnstile", base) is False
    assert should_inject("http://127.0.0.1:9999/", base) is False
    assert should_inject(None, base) is False
    assert should_inject("", base) is False


def test_host_api_exposes_only_the_project_folder_picker():
    methods = {
        name
        for name, value in vars(_HostApi).items()
        if callable(value) and not name.startswith("__")
    }
    assert methods == {"pick_project_folder"}


def test_webview_start_kwargs_persist_the_shell_profile_when_supported(tmp_path):
    def start(func=None, private_mode=True, storage_path=None): ...

    profile = tmp_path / "webview-profile"
    assert _webview_start_kwargs(start, profile) == {
        "private_mode": False,
        "storage_path": str(profile),
    }


def test_webview_start_kwargs_empty_on_an_older_pywebview(tmp_path):
    def start(func=None): ...

    assert _webview_start_kwargs(start, tmp_path / "p") == {}
