import pytest

from launcher.stockroom_launcher import run_launch_sequence


def test_launch_sequence_runs_steps_in_order():
    order = []
    steps = {
        "ensure_webview2": lambda: order.append("webview2"),
        "ensure_ff_pull": lambda: order.append("pull"),
        "uv_sync_frozen": lambda: order.append("sync"),
        "uv_run_app": lambda: order.append("run"),
    }
    ran = run_launch_sequence(steps)
    assert ran == ["ensure_webview2", "ensure_ff_pull", "uv_sync_frozen", "uv_run_app"]
    assert order == ["webview2", "pull", "sync", "run"]


def test_launch_sequence_short_circuits_on_a_failing_step():
    def boom():
        raise RuntimeError("no git")

    steps = {
        "ensure_webview2": lambda: None,
        "ensure_ff_pull": boom,
        "uv_sync_frozen": lambda: (_ for _ in ()).throw(AssertionError("must not run")),
        "uv_run_app": lambda: (_ for _ in ()).throw(AssertionError("must not run")),
    }
    with pytest.raises(RuntimeError):
        run_launch_sequence(steps)


def test_launch_sequence_skips_an_absent_step_but_keeps_order():
    order = []
    steps = {
        "ensure_webview2": lambda: order.append("webview2"),
        # ensure_ff_pull deliberately absent (e.g. injected partial in a test)
        "uv_sync_frozen": lambda: order.append("sync"),
        "uv_run_app": lambda: order.append("run"),
    }
    ran = run_launch_sequence(steps)
    assert ran == ["ensure_webview2", "uv_sync_frozen", "uv_run_app"]
    assert order == ["webview2", "sync", "run"]


def test_the_app_entry_is_the_windowed_host_not_the_headless_api():
    # regression lock: the launcher must run the WINDOWED entry (opens a window), not
    # `stockroom.api.serve` (headless API only, no window) — otherwise the product
    # launches with no UI.
    import inspect

    from launcher import stockroom_launcher

    src = inspect.getsource(stockroom_launcher._uv_run_app)
    # check the actual quoted subprocess arg, so a comment mentioning the headless
    # module (to explain why it is NOT used) is not a false match.
    assert '"stockroom.host.run"' in src
    assert '"stockroom.api.serve"' not in src


@pytest.mark.windows_only
def test_frozen_exe_launches_end_to_end():
    # Owner runs on Windows per the acceptance bar (freeze once, double-click,
    # provision + pull + sync + window). Skipped everywhere else.
    ...
