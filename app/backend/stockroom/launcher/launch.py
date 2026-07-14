"""M9d: the frozen-once launcher supervisor.

The portable Stockroom exe is a tiny, STABLE process manager, frozen ONCE with PyInstaller.
It owns a git working copy of the app repo (code + UI) and runs the WebView2 host from it;
every code / UI update flows through the in-app self-updater (git pull --ff-only + uv sync +
a graceful restart), so the exe itself never needs re-freezing (spec section 12). This
module is the PURE supervisor logic; the three shell-outs (clone / uv sync / spawn the host)
are injected so the whole loop is testable on Linux exactly like updater.py.

Requires git + uv on the machine (uv is bundled beside the exe; git is the one hard external
dependency of a git-native app). A missing git / uv is an honest loud failure at the shell
boundary, never a silent stub.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from stockroom.launcher.exit_codes import EXIT_RESTART

# The public app repo the launcher clones + the in-app updater pulls (github.com/sadadsh/stockroom).
APP_REPO_REMOTE = "https://github.com/sadadsh/stockroom.git"


# CREATE_NO_WINDOW on Windows so a shelled-out git / uv never flashes a console window (the exe
# is windowed); a harmless 0 on POSIX. Mirrors kicad/checks.py + vcs/repo.py.
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def _meipass() -> Path | None:
    """The PyInstaller unpack dir when running as the frozen exe, else None (a source run)."""
    if getattr(sys, "frozen", False):
        mp = getattr(sys, "_MEIPASS", None)
        if mp:
            return Path(mp)
    return None


def _bundled(*parts: str) -> str | None:
    """An absolute path to a file bundled beside the frozen exe, or None if absent / a source run."""
    mp = _meipass()
    if mp is not None:
        p = mp.joinpath(*parts)
        if p.exists():
            return str(p)
    return None


def _uv_bin() -> str:
    """The uv executable. A FROZEN exe bundles its own uv, so a target machine needs no system uv
    (the WinError 2 fix); a source run uses 'uv' from PATH."""
    return _bundled("uv.exe" if os.name == "nt" else "uv") or "uv"


def _git_bin() -> str:
    """The git executable. A FROZEN exe bundles portable git (MinGit) so a bare Windows box with
    no git still clones + self-updates; a source run uses 'git' from PATH."""
    return _bundled("mingit", "cmd", "git.exe" if os.name == "nt" else "git") or "git"


def _child_env() -> dict:
    """The environment for the spawned host. Prepends the bundled git (and uv) dirs to PATH so the
    HOST's OWN git operations (library sync, project commits, the in-app self-update) resolve the
    bundled git too, not just the launcher's clone. On a source run this is os.environ unchanged."""
    env = os.environ.copy()
    mp = _meipass()
    if mp is not None:
        extra = [str(mp / "mingit" / "cmd"), str(mp / "mingit" / "bin"), str(mp)]
        extra = [d for d in extra if os.path.isdir(d)]
        if extra:
            env["PATH"] = os.pathsep.join(extra) + os.pathsep + env.get("PATH", "")
    return env


def _require_git() -> None:
    """git is the one hard external dependency of this git-native app. A frozen exe bundles it, so
    this only fires on a source run with no git: an honest, readable failure, not a WinError 2."""
    if _git_bin() == "git" and shutil.which("git") is None:
        raise RuntimeError(
            "git was not found on this machine. Stockroom needs git (https://git-scm.com) to "
            "fetch and update its app files. Install git, make sure it is on PATH, then relaunch."
        )


# The Edge WebView2 runtime's stable client GUID (same across the Evergreen distributions).
_WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_installed() -> bool:
    """Whether the Microsoft Edge WebView2 runtime is present (pywebview needs it to open the
    window). True (no-op) off Windows. On Windows, reads the runtime's `pv` version under the
    per-machine (incl. WOW6432Node) and per-user Edge Update client keys; a present, non-zero pv
    means installed."""
    if os.name != "nt":
        return True
    try:
        import winreg  # Windows-only, imported lazily
    except ImportError:  # pragma: no cover - non-Windows
        return True
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
    ]
    for hive, path in roots:  # pragma: no cover - real Windows registry read
        try:
            with winreg.OpenKey(hive, path) as key:
                pv, _ = winreg.QueryValueEx(key, "pv")
                if pv and pv not in ("", "0.0.0.0"):
                    return True
        except OSError:
            continue
    return False


def _webview2_setup_bin() -> str | None:
    """The bundled Evergreen Bootstrapper (~2 MB), or None on a source run / when not bundled."""
    return _bundled("webview2", "MicrosoftEdgeWebview2Setup.exe")


def ensure_webview2(*, installed=None, install=None) -> None:
    """Guarantee the WebView2 runtime before the host opens its window. No-op off Windows and
    when already present. On a bare Windows box it silently installs the runtime (per-user, no
    UAC) via the bundled Evergreen Bootstrapper. Fails LOUD with a clear message, never a stub.
    `installed` / `install` are injected for testing."""
    if (installed or webview2_installed)():
        return
    (install or _install_webview2)()


def _install_webview2() -> None:  # pragma: no cover - real Windows shell-out
    setup = _webview2_setup_bin()
    if setup is None:
        raise RuntimeError(
            "The Microsoft Edge WebView2 runtime is required to display Stockroom and was not "
            "found. Install it from https://developer.microsoft.com/microsoft-edge/webview2/ "
            "then relaunch."
        )
    proc = subprocess.run(
        [setup, "/silent", "/install"], capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    # Do not trust the exit code alone: the bootstrapper can exit 0 on a partial/no-op install.
    if proc.returncode != 0 or not webview2_installed():
        raise RuntimeError(
            "Could not install the Microsoft Edge WebView2 runtime automatically (exit "
            f"{proc.returncode}). This device may be offline or the install was blocked. Install "
            "WebView2 from https://developer.microsoft.com/microsoft-edge/webview2/ then relaunch."
        )


def _os_name() -> str:
    return os.name


def app_workdir() -> Path:
    """Where the launcher keeps its managed app working copy: a per-user, writable, stable
    location so the same checkout is reused (and self-updated) across launches.

    STOCKROOM_APP_DIR wins (tests + portable installs); then %LOCALAPPDATA%/Stockroom/app on
    Windows; then ${XDG_DATA_HOME:-~/.local/share}/stockroom/app elsewhere."""
    override = os.environ.get("STOCKROOM_APP_DIR")
    if override:
        return Path(override)
    if _os_name() == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Stockroom" / "app"
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "stockroom" / "app"


def ensure_clone(
    workdir: Path,
    *,
    remote: str = APP_REPO_REMOTE,
    clone: Callable[[str, Path], None] | None = None,
) -> None:
    """Clone the app repo into `workdir` on first run. Idempotent: a working copy that already
    carries a `.git` is left untouched (self-update pulls it in place, never re-clones)."""
    workdir = Path(workdir)
    if (workdir / ".git").exists():
        return
    (clone or _git_clone)(remote, workdir)


def supervise(
    workdir: Path,
    *,
    spawn: Callable[[Path], int] | None = None,
    uv_sync: Callable[[Path], None] | None = None,
    ensure: Callable[[Path], None] | None = None,
    webview2: Callable[[], None] | None = None,
    progress: Callable[[str], None] | None = None,
    remote: str = APP_REPO_REMOTE,
    clone: Callable[[str, Path], None] | None = None,
) -> int:
    """Run the host, relaunching whenever it exits with EXIT_RESTART (a self-update: the
    in-app updater has already pulled + synced, so the loop just re-runs on the new code).
    Returns the host's final non-restart exit code. The shell-outs are injected for testing;
    the defaults clone / guarantee WebView2 / `uv sync --frozen` / `uv run python -m
    stockroom.host.run`. `progress(phase)` (a splash callback: clone / webview2 / sync /
    starting) lets the first-run splash show what is happening during the slow provision, and
    is signalled 'starting' right before the FIRST host spawn so the splash can close."""
    workdir = Path(workdir)
    _ensure = ensure or (lambda wd: ensure_clone(wd, remote=remote, clone=clone))
    _webview2 = webview2 or ensure_webview2
    _uv = uv_sync or _uv_sync
    _spawn = spawn or _spawn_host
    _progress = progress or (lambda _phase: None)
    _progress("clone")
    _ensure(workdir)
    _progress("webview2")
    _webview2()  # guarantee the runtime the host's window needs BEFORE any host spawn
    started = False
    while True:
        _progress("sync")
        _uv(workdir)
        if not started:
            _progress("starting")  # provisioning done; the splash closes, the host window appears
            started = True
        code = _spawn(workdir)
        if code != EXIT_RESTART:
            return code


# -- default shell-outs (Windows-run; injected in tests) ----------------------


def _git_clone(remote: str, workdir: Path) -> None:  # pragma: no cover - real shell-out
    _require_git()
    workdir = Path(workdir)
    workdir.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [_git_bin(), "clone", remote, str(workdir)],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"could not clone the Stockroom app repo: {proc.stderr.strip()}")


def _uv_sync(workdir: Path) -> None:  # pragma: no cover - real shell-out
    # Capture output so a failure (offline, proxy, cert) surfaces as a readable message the
    # entry-point dialog can show, not a bare CalledProcessError into a windowed void.
    proc = subprocess.run(
        [_uv_bin(), "sync", "--frozen"], cwd=str(workdir),
        capture_output=True, text=True, env=_child_env(), creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "could not set up the Stockroom environment: "
            + ((proc.stderr or proc.stdout) or "").strip()
        )


def _spawn_host(workdir: Path) -> int:  # pragma: no cover - real shell-out
    # --frozen --no-sync: supervise() already ran `uv sync --frozen`, so do NOT let `uv run`
    # re-validate against the network on every launch (that would break offline relaunch).
    proc = subprocess.run(
        [_uv_bin(), "run", "--frozen", "--no-sync", "python", "-m", "stockroom.host.run"],
        cwd=str(workdir), env=_child_env(), creationflags=_NO_WINDOW,
    )
    return proc.returncode


def main() -> int:  # pragma: no cover - the frozen exe entry point
    # Show a first-run progress splash during the slow provision (clone + WebView2 + uv sync); it
    # degrades to a plain run if a splash cannot be shown, so it never blocks the launch.
    from stockroom.launcher import splash

    return splash.run(lambda progress: supervise(app_workdir(), progress=progress))
