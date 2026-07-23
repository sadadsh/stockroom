"""Server bootstrap: bind loopback on an OS-assigned ephemeral port and hand the
base URL plus the per-launch token to the host (knowledge-transfer section 2). Only
ever binds 127.0.0.1; a non-loopback host is refused so the API is never exposed
beyond the machine (spec section 2.2, fail-proof)."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from stockroom.api.context import AppContext, build_context as _build_context
from stockroom.api.security import mint_token
from stockroom.store.machine_config import MachineConfig

# The app repo (the CODE/UI/DATA repo that contains THIS package) is four parents
# up: serve.py -> api -> stockroom -> backend -> app -> <repo root>. The in-repo
# library lives beside the `app/` tree at <repo root>/libraries.
_APP_REPO_ROOT = Path(__file__).resolve().parents[4]
_LIBRARIES_ROOT = Path(__file__).resolve().parents[3].parent / "libraries"


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _uv_sync() -> None:  # pragma: no cover - shells out to the bundled uv
    """Run `uv sync --frozen` against the app repo after a self-update pull so the
    locked deps are installed before the restart. Frozen so the update never
    silently re-resolves the lockfile; a real failure raises (honest degradation,
    spec section 2.2) rather than being swallowed."""
    subprocess.run(["uv", "sync", "--frozen"], check=True, cwd=str(_APP_REPO_ROOT))


def build_context(libraries_root: Path | None = None, kicad_dir: Path | None = None) -> AppContext:
    config = MachineConfig.load()
    if libraries_root is None:
        # Guarantee a usable library exists so the server ALWAYS boots (M9a/M9b): the
        # persisted choice or the in-repo dev library if either is usable, else a freshly
        # created default. This turns a frozen first run (which ships no library) into a
        # bootable app that serves the onboarding UI, where the user opens / clones / creates
        # the real library and the engine repoints live, instead of a startup crash.
        from stockroom.store.onboarding import bootstrap_library

        libraries_root = bootstrap_library(config)
    else:
        # A provided library may not carry this machine's active-profile name (a config from
        # another machine, or a retired/renamed profile - e.g. the old "Main" after it is
        # deleted). Repair it to a profile that actually exists here so the immediately-following
        # _build_context never 404s the profile - the same drift repair bootstrap_library does.
        from stockroom.store.profile import ProfileStore
        from stockroom.vcs.repo import GitError, GitRepo

        try:
            names = ProfileStore(Path(libraries_root), GitRepo(Path(libraries_root))).list()
            if names and config.active_profile not in names:
                config.active_profile = names[0]
        except GitError:
            pass
    ctx = _build_context(libraries_root, kicad_dir=kicad_dir, config=config, token=mint_token())
    # Attach the app-repo GitRepo + a real uv_sync runner for the self-updater. The
    # app repo (this file's repo) is distinct from the library repo the context
    # already wired. request_restart stays the safe no-op default here: serve.py
    # runs the API standalone with no host window to reload; the real restart hook
    # is wired by the pywebview host (Task 17), and faking one would be dishonest.
    from stockroom.vcs.repo import GitError, GitRepo

    try:
        ctx.app_repo = GitRepo(_APP_REPO_ROOT)
    except GitError:
        # git absent: leave app_repo as the context default so the update route
        # surfaces the state honestly rather than crashing the whole bootstrap.
        pass
    ctx.uv_sync = _uv_sync
    # S5: the real app renders JS distributor pages through the portable, stealthed,
    # anti-ban-governed headless Chromium engine (retires the HTTP-only default and the
    # never-shipped WebView2 seam). Lazy: Chromium only launches on the first render, so
    # boot stays fast and a machine that never enriches never starts a browser.
    import atexit

    from stockroom.enrich.scrape_adapter import default_rendered_dom_fetcher

    _fetcher = default_rendered_dom_fetcher(Path(ctx.enrich_cache_dir) / "rendered")
    ctx.rendered_dom_fetcher = _fetcher
    # Best-effort: close the render runtime (browser + node driver) on a normal quit or a
    # self-update restart, so a headless Chromium is not orphaned. The runtime is a daemon
    # thread, so this is a courtesy, not required for a hard kill.
    atexit.register(_fetcher.close)
    # Wire KiCad at the active library on every real boot (both entries - the
    # windowed host and standalone serve - build their context here), so the
    # library is visible in KiCad without the manual Doctor click. rewire_kicad
    # never raises: it skips when KiCad is absent and captures failures into
    # ctx.last_wiring, which Settings surfaces honestly.
    ctx.rewire_kicad()
    return ctx


def run(host: str = "127.0.0.1", port: int = 0) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"refusing to bind a non-loopback host: {host!r}")
    import uvicorn

    from stockroom.api.app import create_app

    ctx = build_context()
    app = create_app(ctx)
    uvicorn.run(app, host=host, port=port or pick_free_port(), log_level="warning")


if __name__ == "__main__":  # pragma: no cover - launcher entry (`uv run python -m stockroom.api.serve`)
    run()
