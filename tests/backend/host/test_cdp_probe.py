"""Unit tests for the pure helpers of the CDP probe (the WebView2 live X-ray). The websocket
client itself only runs against a real Windows WebView2 debug port; these cover the parsing,
target-polling, and console-formatting logic that runs anywhere."""

from stockroom.host import cdp_probe
from stockroom.host.cdp_probe import ConsoleTap, format_console_args, wait_for_target


def test_format_console_args_renders_values_descriptions_and_undefined():
    args = [
        {"type": "string", "value": "[SRDRV]"},
        {"type": "number", "value": 3},
        {"type": "object", "description": "Error: boom"},
        {"type": "undefined"},
    ]
    out = format_console_args(args)
    assert "[SRDRV]" in out and "3" in out and "Error: boom" in out and "undefined" in out


def test_wait_for_target_polls_until_a_matching_page_target_appears(monkeypatch):
    # The debug port + its page target come up asynchronously, so wait_for_target polls list_targets
    # and returns the first PAGE target whose url matches (with a webSocketDebuggerUrl).
    calls = {"n": 0}
    target = {"type": "page", "url": "https://www.digikey.com/en/models/1", "webSocketDebuggerUrl": "ws://x"}

    def fake_list_targets(port, host="127.0.0.1"):
        calls["n"] += 1
        return [target] if calls["n"] >= 3 else []

    monkeypatch.setattr(cdp_probe, "list_targets", fake_list_targets)
    got = wait_for_target(9222, "digikey", tries=10, delay=0, sleep=lambda _s: None)
    assert got is target and calls["n"] == 3


def test_wait_for_target_ignores_non_page_and_non_matching_targets(monkeypatch):
    targets = [
        {"type": "service_worker", "url": "https://www.digikey.com/x", "webSocketDebuggerUrl": "ws://sw"},
        {"type": "page", "url": "https://other.com/", "webSocketDebuggerUrl": "ws://o"},
    ]
    monkeypatch.setattr(cdp_probe, "list_targets", lambda *a, **k: targets)
    assert wait_for_target(9222, "digikey", tries=2, delay=0, sleep=lambda _s: None) is None


def test_console_tap_writes_stamped_console_and_exception_lines():
    lines = []
    tick = {"t": 0.0}
    tap = ConsoleTap(lines.append, now=lambda: tick["t"])
    tick["t"] = 1.5
    tap.on_event(
        {"method": "Runtime.consoleAPICalled",
         "params": {"type": "log", "args": [{"value": "[SRDRV] nextFmt"}]}}
    )
    tap.on_event(
        {"method": "Runtime.exceptionThrown",
         "params": {"exceptionDetails": {"exception": {"description": "TypeError: x"}, "lineNumber": 5}}}
    )
    assert any("LOG" in ln and "[SRDRV] nextFmt" in ln for ln in lines)
    assert any("EXC" in ln and "TypeError: x" in ln for ln in lines)
    assert all(ln.startswith("+") and "ms" in ln for ln in lines)  # each line is time-stamped
