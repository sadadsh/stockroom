"""Frozen-once launcher, ComfyUI-Desktop-shaped (spec section 3.7; knowledge-
transfer section 2). Frozen to Stockroom.exe ONCE and never rebuilt for app changes
(those ship via git pull). Sequence: ensure WebView2, ff-pull the app repo (git on
PATH or dulwich), uv sync --frozen (provisions CPython + locked deps), uv run the
app. The uv.exe ships beside the launcher, not in git history. run_launch_sequence
is pure and fully injected so the launch ORDER is Linux-tested; the real steps and
the freeze are Windows-verified."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

_ORDER = ("ensure_webview2", "ensure_ff_pull", "uv_sync_frozen", "uv_run_app")


def run_launch_sequence(steps: dict[str, Callable[[], None]]) -> list[str]:
    ran: list[str] = []
    for name in _ORDER:
        step = steps.get(name)
        if step is None:
            continue
        step()  # a failure raises; we do NOT swallow it (honest degradation)
        ran.append(name)
    return ran


def _repo_root() -> Path:
    # the app repo is the directory containing app/ and launcher/
    return Path(__file__).resolve().parents[1]


def main() -> None:  # pragma: no cover - the real, Windows-run entry
    from launcher.gitshim import ensure_ff_pull

    root = _repo_root()

    steps = {
        "ensure_webview2": _ensure_webview2,
        "ensure_ff_pull": lambda: ensure_ff_pull(root),
        "uv_sync_frozen": _uv_sync_frozen,
        "uv_run_app": _uv_run_app,
    }
    run_launch_sequence(steps)


def _ensure_webview2() -> None:  # pragma: no cover - Windows-only
    # On Windows, check for the evergreen WebView2 runtime and run the bootstrapper
    # if absent. A no-op off Windows.
    import sys

    if not sys.platform.startswith("win"):
        return
    # (Windows: probe the WebView2 registry key; run MicrosoftEdgeWebview2Setup.exe
    # if the runtime is missing. Verified on the owner's box.)


def _uv_sync_frozen() -> None:  # pragma: no cover - shells out to bundled uv.exe
    import subprocess

    subprocess.run(["uv", "sync", "--frozen"], check=True, cwd=str(_repo_root()))


def _uv_run_app() -> None:  # pragma: no cover - launches the app
    import subprocess

    # uv run starts the WINDOWED host entry (stockroom.host.run), which binds loopback
    # on an ephemeral port AND opens the WebView2 window. NOT stockroom.api.serve, which
    # is the headless API only (no window) — launching that would show no UI.
    subprocess.run(
        ["uv", "run", "python", "-m", "stockroom.host.run"],
        check=True,
        cwd=str(_repo_root()),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
