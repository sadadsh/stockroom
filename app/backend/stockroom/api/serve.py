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
        # the in-repo library lives beside this package; resolved by the launcher
        libraries_root = _LIBRARIES_ROOT
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
